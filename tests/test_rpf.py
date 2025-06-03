# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Tests for the RPM package function."""

import logging
import os
from pathlib import Path
from typing import List, Union

import pytest
from azure.identity import DefaultAzureCredential
from azure.storage.blob import ContainerClient

from azure_blobrepo_rpm import (
    AzureDistributionOrganiser,
    AzureDistributionRepository,
    AzureFlatOrganiser,
    AzureFlatRepository,
    DistributionOrganiser,
    FlatOrganiser,
    LocalRpmPackage,
)

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())

# Turn down logging for spammy functions
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(
    logging.WARNING
)
logging.getLogger("urllib3").setLevel(logging.WARNING)


TEST_DIR = Path(__file__).parent


@pytest.mark.parametrize(
    "rpm_packages",
    [
        [
            {
                "name": "azurelinux",
                "version": "1.0",
                "release": "1.cm2",
            },
            {
                "name": "centos",
                "version": "1.0",
                "release": "1.el7",
            },
            {
                "name": "nodistributioninfo",
                "version": "1.0",
                "release": "1",
            },
        ]
    ],
    indirect=True,
)
def test_various_packages(rpm_packages: List[Path]) -> None:
    """Test that LocalRpmPackage can handle different things being thrown at it."""
    for rpm_package in rpm_packages:
        LocalRpmPackage(rpm_package)


@pytest.mark.parametrize(
    "rpm_packages",
    [
        [
            {
                "name": "test",
                "version": "1.0",
                "release": "1.cm2",
            }
        ]
    ],
    indirect=True,
)
def test_organiser(rpm_packages: List[Path]) -> None:
    """Test that the organiser returns the correct path for a package."""
    rpm_package = rpm_packages[0]
    package = LocalRpmPackage(rpm_package)
    organiser = DistributionOrganiser(Path("test"))

    # Test the path that the organiser would return
    path = organiser.get_path(package)

    assert path == Path(f"test/cm/2/{rpm_package.name}")


@pytest.mark.parametrize(
    "rpm_packages",
    [
        [
            {
                "name": "test",
                "version": "1.0",
                "release": "1.cm2",
            }
        ]
    ],
    indirect=True,
)
def test_flat_organiser(rpm_packages: List[Path]) -> None:
    """Test that the organiser organiser returns the correct path for a package."""
    rpm_package = rpm_packages[0]
    package = LocalRpmPackage(rpm_package)
    organiser = FlatOrganiser(Path("test"))

    # Test the path that the organiser would return
    path = organiser.get_path(package)

    assert path == Path(f"test/{rpm_package.name}")


@pytest.mark.parametrize(
    "repository",
    [
        {
            "upload_directory": "upload",
            "upload_packages": [
                {
                    "name": "list_packages",
                    "version": "2.0",
                    "release": "1.cm2",
                }
            ],
        }
    ],
    indirect=True,
)
def test_list_packages(repository) -> None:  # noqa: ANN001
    """Test that the organiser can find packages."""

    organiser = DistributionOrganiser(repository)
    packages = organiser.list_uploads()

    assert len(packages) == 1
    assert packages[0].name() == "list_packages"
    assert packages[0].version() == "2.0"
    assert packages[0].dist() == "cm2"


def live_clean_package(
    package: Path,
    organiser: Union[AzureDistributionOrganiser, AzureFlatOrganiser],
    assert_exists: bool = False,
) -> None:
    """Clean up an existing package."""
    # Determine the path of the package
    sorted_path = organiser.get_path(LocalRpmPackage(package))
    log.debug("Cleaning up package %s", sorted_path)

    # Clean up an existing package
    sorted_blob = organiser.container_client.get_blob_client(str(sorted_path))

    if assert_exists:
        # Check that the sorted blob exists before deleting it.
        assert sorted_blob.exists()

    if sorted_blob.exists():
        sorted_blob.delete_blob()

    # Clean the metadata
    metadata = sorted_path.with_suffix(".package")
    metadata_blob = organiser.container_client.get_blob_client(str(metadata))
    if metadata_blob.exists():
        log.debug("Cleaning up metadata %s", metadata)
        metadata_blob.delete_blob()


def live_clean_and_upload_package(
    package: Path,
    organiser: Union[AzureDistributionOrganiser, AzureFlatOrganiser],
    upload_directory: str = "upload",
) -> None:
    """Clean up any existing packages and upload a package to the container."""
    live_clean_package(package, organiser)

    # Upload the package to the container in the upload directory
    upload_path = Path(upload_directory) / package.name
    upload_client = organiser.container_client.get_blob_client(str(upload_path))
    with open(package, "rb") as f:
        upload_client.upload_blob(f, overwrite=True)
    log.debug("Uploaded package %s to %s", package, upload_path)


def live_clean_metadata(container_client: ContainerClient, metadata: Path) -> None:
    """Clean up any existing metadata."""
    blobs = container_client.list_blobs(name_starts_with=str(metadata))
    for blob in blobs:
        blob_client = container_client.get_blob_client(blob.name)
        log.debug("Deleting metadata file: %s", blob.name)
        blob_client.delete_blob()


@pytest.mark.skipif(
    "BLOB_CONTAINER_URL" not in os.environ,
    reason="BLOB_CONTAINER_URL not set",
)
@pytest.mark.parametrize(
    "rpm_packages",
    [
        [
            {
                "name": "test",
                "version": "1.0",
                "release": "1.cm2",
            }
        ]
    ],
    indirect=True,
)
def test_live_organiser(rpm_packages) -> None:  # noqa: ANN001
    """Test that the AzureDistributionOrganiser can find packages."""
    rpm_package = rpm_packages[0]
    credential = DefaultAzureCredential()
    container_client = ContainerClient.from_container_url(
        container_url=os.environ["BLOB_CONTAINER_URL"],
        credential=credential,
    )
    upload_directory = "upload"

    # Now check that the file is listed
    organiser = AzureDistributionOrganiser(
        container_client, Path("."), upload_directory=upload_directory
    )

    # Clean the container and upload the package
    live_clean_and_upload_package(
        rpm_package, organiser, upload_directory=upload_directory
    )

    # List the packages in upload/
    packages = organiser.list_uploads()

    # Ensure that there's one package, and it's the one we uploaded
    assert len(packages) == 1
    package = packages[0]
    assert package.package_filename() == rpm_package.name

    # Check that we can organise the package
    organiser.organise()

    # Finally clean up the sorted package
    live_clean_package(rpm_package, organiser, assert_exists=True)


@pytest.mark.skipif(
    "BLOB_CONTAINER_URL" not in os.environ,
    reason="BLOB_CONTAINER_URL not set",
)
@pytest.mark.parametrize(
    "rpm_packages",
    [
        [
            {
                "name": "first",
                "version": "1.0",
                "release": "1.cm2",
            },
            {
                "name": "second",
                "version": "1.0",
                "release": "1.cm2",
            },
            {
                "name": "rejected",
                "version": "2.0",
                "release": "1",
            },
        ]
    ],
    indirect=True,
)
def test_live_repository(rpm_packages) -> None:  # noqa: ANN001
    """Test that the AzureDistributionRepository works."""
    credential = DefaultAzureCredential()
    container_client = ContainerClient.from_container_url(
        container_url=os.environ["BLOB_CONTAINER_URL"],
        credential=credential,
    )
    upload_directory = "upload"

    # Create a new AzureDistributionRepository
    repo = AzureDistributionRepository(
        container_client, upload_directory=upload_directory
    )

    # Clean the container and upload the packages
    live_clean_metadata(container_client, Path("cm/2/repodata"))
    for rpm_package in rpm_packages:
        log.info("Uploading package %s", rpm_package)
        live_clean_and_upload_package(
            rpm_package, repo.organiser, upload_directory=upload_directory
        )

    # Kick the repository as if it had been invoked by the function app.
    repo.process()

    # Running the process again will only regenerate the repository data.
    repo.process()

    # Clean up the repository
    live_clean_metadata(container_client, Path("cm/2/repodata"))
    for rpm_package in rpm_packages:
        live_clean_package(rpm_package, repo.organiser, assert_exists=True)


@pytest.mark.skipif(
    "BLOB_CONTAINER_URL" not in os.environ,
    reason="BLOB_CONTAINER_URL not set",
)
@pytest.mark.parametrize(
    "rpm_packages",
    [
        [
            {
                "name": "first",
                "version": "1.0",
                "release": "1.cm2",
            },
            {
                "name": "second",
                "version": "1.0",
                "release": "1.cm2",
            },
            {
                "name": "notrejected",
                "version": "2.0",
                "release": "1",
            },
        ]
    ],
    indirect=True,
)
def test_live_flat_repository(rpm_packages) -> None:  # noqa: ANN001
    """Test that the AzureFlatRepository works."""
    credential = DefaultAzureCredential()
    container_client = ContainerClient.from_container_url(
        container_url=os.environ["BLOB_CONTAINER_URL"],
        credential=credential,
    )
    upload_directory = "upload"

    # Create a new AzureFlatRepository
    repo = AzureFlatRepository(container_client, upload_directory=upload_directory)

    # Clean the container and upload the packages
    live_clean_metadata(container_client, Path("./repodata"))
    for rpm_package in rpm_packages:
        log.info("Uploading package %s", rpm_package)
        live_clean_and_upload_package(
            rpm_package, repo.organiser, upload_directory=upload_directory
        )

    # Kick the repository as if it had been invoked by the function app.
    repo.process()

    # # Running the process again will only regenerate the repository data.
    # repo.process()

    # # Clean up the repository
    # live_clean_metadata(container_client, Path("./repodata"))
    # for rpm_package in rpm_packages:
    #     live_clean_package(rpm_package, repo.organiser, assert_exists=True)
