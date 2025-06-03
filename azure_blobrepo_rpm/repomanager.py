# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Classes to manage repositories."""

import logging
import tarfile
import tempfile
from pathlib import Path
from typing import List, Optional, Set, Union

import createrepo_c
from azure.storage.blob import ContainerClient

from azure_blobrepo_rpm import AzureDistributionOrganiser, AzureFlatOrganiser
from azure_blobrepo_rpm.rpmpackage import RemoteRpmPackage

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())

METADATA_CHECK_KEY = "RpmLastModified"


class BaseRepository:
    """Base class for repositories."""

    def process(self) -> None:
        """Run upkeep operations on the repository."""
        raise NotImplementedError


class AzureBaseRepository(BaseRepository):
    """A class to manage an RPM repository organised by distribution in ABS."""

    def __init__(
        self,
        container_client: ContainerClient,
        organiser: Union[AzureDistributionOrganiser, AzureFlatOrganiser],
    ) -> None:
        """Create an AzureDistributionRepository object."""
        self.container_client = container_client
        self.organiser = organiser

    def process(self) -> None:
        """Run upkeep operations on the repository."""
        log.info("Processing repository")
        # First, organise any uploaded packages
        self.organiser.organise()

        # Next, regenerate repository metadata for packages that haven't had
        # it generated yet.
        all_packages = self.list_all_packages()
        for package in all_packages:
            self.check_metadata(package)

        # Now that all of the metadata is up to date, we can regenerate the
        # repository metadata.
        paths = self.list_all_package_paths()
        for path in paths:
            self.merge_metadata(path)

    def _skip_blob(self, blob_name: Path) -> bool:
        """Check if a blob should be skipped."""
        if blob_name.suffix != ".rpm":
            log.debug("Skipping non-RPM blob: %s", blob_name)
            return True

        parent_parts = blob_name.parent.parts
        if parent_parts and parent_parts[-1] == "upload":
            log.debug("Skipping upload package: %s", blob_name)
            return True

        if parent_parts and parent_parts[-1] == "rejected":
            log.debug("Skipping rejected package: %s", blob_name)
            return True

        return False

    def list_all_packages(self) -> List[RemoteRpmPackage]:
        """List all packages in the repository."""
        blobs = self.container_client.list_blobs()

        packages = []

        for blob in blobs:
            blob_path = Path(blob.name)

            if self._skip_blob(blob_path):
                continue

            # Create a new RemoteRpmPackage object
            package = RemoteRpmPackage(blob_path, self.container_client)
            packages.append(package)

        log.info("Found %d packages in total", len(packages))
        log.debug("Packages: %s", packages)
        return packages

    def list_all_package_paths(self) -> Set[Path]:
        """List all package parents in the repository."""
        blobs = self.container_client.list_blobs()

        paths: Set[Path] = set()

        for blob in blobs:
            blob_path = Path(blob.name)
            if self._skip_blob(blob_path):
                continue

            paths.add(blob_path.parent)

        log.info("Found %d paths in total", len(paths))
        log.debug("Paths: %s", paths)
        return paths

    def check_metadata(self, package: RemoteRpmPackage) -> None:
        """Check that package metadata exists and is correct."""
        blob_client = package.blob_client()
        metadata_path = package.path.with_suffix(".package")
        metadata_blob_client = self.container_client.get_blob_client(str(metadata_path))

        # Check if the metadata file exists and if it doesn't, create it
        if not metadata_blob_client.exists():
            log.error("Metadata file missing for: %s", package.path)
            self.create_metadata(package)
            return

        # Check to make sure that the LastModified time of the package is the same as
        # the LastModified metadata variable on the metadata file.
        package_properties = blob_client.get_blob_properties()
        metadata_properties = metadata_blob_client.get_blob_properties()

        if METADATA_CHECK_KEY not in metadata_properties.metadata:
            log.error("Metadata file missing RpmLastModified for: %s", package.path)
            self.create_metadata(package)
            return

        if str(package_properties.last_modified) != str(
            metadata_properties.metadata[METADATA_CHECK_KEY]
        ):
            log.error(
                "Metadata file out of date for: %s (%s != %s)",
                package.path,
                package_properties.last_modified,
                metadata_properties.metadata[METADATA_CHECK_KEY],
            )
            self.create_metadata(package)
            return

        log.debug("Package %s metadata is up to date", package.path)

    def create_metadata(
        self,
        package: RemoteRpmPackage,
    ) -> None:
        """Create metadata information."""
        log.info("Creating metadata for package: %s", package.path)

        # Start by creating a temporary directory structure
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)

            # Generate the full path of the package under the temp root
            temp_package_path = temp_root / package.path
            log.debug("Temp package path: %s", temp_package_path)

            # Generate the package structure.
            temp_package_path.parent.mkdir(parents=True, exist_ok=True)

            # Copy the package to the temporary path
            package.copy_local(temp_package_path)

            # Generate the repository metadata using the createrepo_c program
            log.debug("Generating metadata in %s", temp_root)

            rc = createrepo_c._program(  # pylint: disable=protected-access
                "createrepo_c", ["--compatibility", str(temp_root)]
            )
            if rc != 0:
                raise RuntimeError("Failed to generate metadata")

            # Tar up the metadata
            metadata_tar_gz = package.path.with_suffix(".tar.gz")

            with tempfile.TemporaryDirectory() as temp_metadata_dir:
                temp_metadata_file = Path(temp_metadata_dir) / metadata_tar_gz.name
                with tarfile.open(temp_metadata_file, "w:gz") as tar:
                    tar.add(temp_root / "repodata", arcname="repodata")

                log.debug("Created metadata tarball: %s", temp_metadata_file)

                # Upload the metadata to the container
                metadata_path = package.path.with_suffix(".package")
                metadata_blob_client = self.container_client.get_blob_client(
                    str(metadata_path)
                )
                with open(temp_metadata_file, "rb") as f:
                    metadata_blob_client.upload_blob(f, overwrite=True)

                log.debug("Uploaded metadata to %s", metadata_path)

                # Set the details on the uploaded metadata file.
                blob_client = package.blob_client()
                blob_properties = blob_client.get_blob_properties()
                metadata = {METADATA_CHECK_KEY: str(blob_properties.last_modified)}
                metadata_blob_client.set_blob_metadata(metadata)
                log.debug(
                    "Set %s to %s", METADATA_CHECK_KEY, metadata[METADATA_CHECK_KEY]
                )

    def merge_metadata(self, path: Path) -> None:
        """Merge metadata files."""
        log.info("Merging metadata for path: %s", path)
        # Create a temporary directory to work in
        with tempfile.TemporaryDirectory() as f:
            temp_root = Path(f)

            # Generate the folder structure under the temp root
            package_dir = temp_root / path
            package_dir.mkdir(parents=True, exist_ok=True)
            log.debug("Created package directory: %s", package_dir)

            # Find all the metadata files under the given path
            # If the path is empty, we want to list all the blobs in the container
            prefix: Optional[str]
            if path.parts:
                prefix = str(path)
            else:
                prefix = None

            blobs = self.container_client.list_blobs(name_starts_with=prefix)

            downloaded_metadata = []

            for blob in blobs:
                blob_path = Path(blob.name)
                if blob_path.suffix != ".package":
                    log.debug("Skipping non-metadata file: %s", blob.name)
                    continue

                # Found a metadata file. Download it to the temp directory
                metadata_path = temp_root / blob_path.name
                metadata_blob_client = self.container_client.get_blob_client(blob.name)
                with open(metadata_path, "wb") as g:
                    stream = metadata_blob_client.download_blob()
                    g.write(stream.readall())
                log.debug("Downloaded metadata %s to %s", blob_path, metadata_path)

                downloaded_metadata.append(metadata_path)

            # Now iterate over the downloaded metadata files and extract them
            extract_roots = []

            for index, metadata_path in enumerate(downloaded_metadata):
                extract_root = package_dir / f"metadata-{index}"
                extract_root.mkdir(parents=True, exist_ok=True)
                log.debug("Extracting metadata %s to %s", metadata_path, extract_root)
                extract_repodata = extract_root / "repodata"

                with tarfile.open(metadata_path, "r:gz") as tar:
                    tar.extractall(path=extract_root)
                    if not extract_repodata.exists():
                        raise FileNotFoundError("Failed to extract metadata")

                extract_roots.append(extract_root)
                log.debug("Extracted metadata %s to %s", metadata_path, extract_root)

            # Now that we've extracted all the metadata's let's merge them together.
            # Construct the command to merge the metadata
            output_dir = temp_root / "out"

            args = [
                "-d",
                "--all",
                "--omit-baseurl",
                "--compress-type=gz",
                "--outputdir",
                str(output_dir),
            ]

            for extract_root in extract_roots:
                args.extend(["--repo", str(extract_root)])

            rc = createrepo_c._program(  # pylint: disable=protected-access
                "mergerepo_c", args
            )
            if rc != 0:
                raise RuntimeError("Failed to generate metadata")

            # Check that the output directory repodata exists
            output_repodata = output_dir / "repodata"
            if not output_repodata.exists():
                raise FileNotFoundError("Failed to merge metadata")

            log.info("Merged metadata for path %s to %s", path, output_repodata)

            # Work out the set of remote metadata files that already exist.
            target_repodata = path / "repodata"

            existing_remote_metadata = set(
                Path(blob.name).name
                for blob in self.container_client.list_blobs(
                    name_starts_with=str(target_repodata)
                )
            )
            log.debug(
                "There are %d existing metadata files", len(existing_remote_metadata)
            )

            new_metadata = set(metadata.name for metadata in output_repodata.iterdir())

            to_delete = existing_remote_metadata - new_metadata
            log.debug("There are %d metadata files to delete", len(to_delete))
            log.debug("Files to delete: %s", to_delete)

            # Upload all the metadata files to the container
            for metadata_file in output_repodata.iterdir():
                target_path = path / "repodata" / metadata_file.name

                metadata_blob_client = self.container_client.get_blob_client(
                    str(target_path)
                )
                with open(metadata_file, "rb") as g:
                    metadata_blob_client.upload_blob(g, overwrite=True)
                log.debug("Uploaded metadata %s to %s", metadata_file, target_path)

            # Delete any metadata files that are no longer needed
            for delete_file in to_delete:
                delete_path = path / "repodata" / delete_file
                delete_client = self.container_client.get_blob_client(str(delete_path))
                delete_client.delete_blob()
                log.debug("Deleted obsolete metadata %s", delete_path)


class AzureDistributionRepository(AzureBaseRepository):
    """A class to manage an RPM repository organised by distribution in ABS."""

    def __init__(
        self, container_client: ContainerClient, upload_directory: str = "upload"
    ) -> None:
        """Create an AzureDistributionRepository object."""
        organiser = AzureDistributionOrganiser(
            container_client, Path("."), upload_directory=upload_directory
        )
        super().__init__(
            container_client,
            organiser,
        )


class AzureFlatRepository(AzureBaseRepository):
    """A class to manage a flat RPM repository in ABS."""

    def __init__(
        self, container_client: ContainerClient, upload_directory: str = "upload"
    ) -> None:
        """Create an AzureFlatRepository object."""
        organiser = AzureFlatOrganiser(
            container_client, Path("."), upload_directory=upload_directory
        )
        super().__init__(
            container_client,
            organiser,
        )
