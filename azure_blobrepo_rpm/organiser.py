# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Classes to organise RPM packages."""

import logging
import re
from pathlib import Path
from typing import Callable, List

from azure.storage.blob import ContainerClient

from azure_blobrepo_rpm.rpmpackage import (
    BaseRpmPackage,
    LocalRpmPackage,
    RemoteRpmPackage,
)

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())


class BaseOrganiser:
    """Base class for organising RPM packages."""

    def get_path(self, package: BaseRpmPackage) -> Path:
        """Get the relative path of the package under this organiser."""
        raise NotImplementedError

    def list_uploads(self) -> List[BaseRpmPackage]:
        """List uploaded packages."""
        raise NotImplementedError

    def organise(self) -> None:
        """Organise the uploaded packages."""
        raise NotImplementedError


class LocalOrganiserMixin:
    """Mixin class for local organisation of RPM packages."""

    def __init__(self, root: Path, upload_directory: str = "upload") -> None:
        """Create a new DistributionOrganiser."""
        self.root = root
        self.upload_directory = self.root / upload_directory

    def list_uploads(self) -> List[BaseRpmPackage]:
        """List the uploaded packages."""
        packages: list[BaseRpmPackage] = [
            LocalRpmPackage(path) for path in self.upload_directory.glob("*.rpm")
        ]
        return packages

    def organise(self) -> None:
        """Organise the uploaded packages."""
        for package in self.list_uploads():
            log.debug("Organising package: %s", package)
            path = self.get_path(package)
            path.parent.mkdir(parents=True, exist_ok=True)

            # Move the package to the new path
            package.move(str(path))

    get_path: Callable[[BaseRpmPackage], Path]


class AzureOrganiserMixin:
    """Mixin class for organising RPM packages in Azure Blob Storage."""

    def __init__(
        self,
        container_client: ContainerClient,
        root: Path,
        upload_directory: str = "upload",
    ) -> None:
        """Create a new AzureDistributionOrganiser."""
        self.container_client = container_client
        self.root = root
        self.upload_directory = self.root / upload_directory

    def list_uploads(self) -> List[BaseRpmPackage]:
        """List the uploaded packages."""
        # List the blobs in the container prefixed with the upload directory
        blobs = self.container_client.list_blobs(
            name_starts_with=str(self.upload_directory)
        )

        packages: list[BaseRpmPackage] = []

        for blob in blobs:
            blob_path = Path(blob.name)
            if blob_path.suffix != ".rpm":
                log.info("Skipping non-RPM blob: %s", blob)
                continue

            # Create a new RemoteRpmPackage object
            package = RemoteRpmPackage(blob_path, self.container_client)
            packages.append(package)

        log.info("Found %d packages in %s", len(packages), self.upload_directory)
        log.debug("Packages: %s", packages)
        return packages

    def organise(self) -> None:
        """Organise the uploaded packages."""
        for package in self.list_uploads():
            log.debug("Organising package: %s", package)
            path = self.get_path(package)

            # Move the package to the new path
            try:
                package.move(str(path))
            except FileExistsError as e:
                # If the file already exists, log a warning and continue
                log.warning("File already exists: %s", e)

    get_path: Callable[[BaseRpmPackage], Path]


class DistributionPathMixin:
    """Implementation of the get_path method for distributions."""

    root: Path

    def get_path(self, package: BaseRpmPackage) -> Path:
        """Get the path of the package under this organiser."""
        # Normalize the package filename.
        name = package.name()
        version = package.version()
        distribution = package.dist()
        release = package.release()
        arch = package.arch()

        filename = f"{name}-{version}-{release}.{arch}.rpm"
        log.debug("Normalised filename: %s", filename)

        # Attempt to split up the distribution into components. Most
        # distributions that have a distribution use a two digit letter code
        # followed by a version number.
        # A few examples:
        # - fc34: Fedora 34
        # - el7: RHEL 7
        # - cm2: AzureLinux 2
        pattern = r"^([a-z]+)(\d+)$"

        if distribution and (m := re.match(pattern, distribution)):
            path = self.root / m.group(1) / m.group(2) / filename
        else:
            # If we don't have a distribution, put it in the "rejected" directory.
            path = self.root / "rejected" / filename

        log.debug("Package %s belongs as %s", package, path)
        return path


class FlatPathMixin:
    """Implementation of the get_path method for flat repositories."""

    root: Path

    def get_path(self, package: BaseRpmPackage) -> Path:
        """Get the path of the package under this organiser."""
        # Normalize the package filename.
        name = package.name()
        version = package.version()
        release = package.release()
        arch = package.arch()

        filename = f"{name}-{version}-{release}.{arch}.rpm"
        log.debug("Normalised filename: %s", filename)

        path = self.root / filename

        log.debug("Package %s belongs as %s", package, path)
        return path


class DistributionOrganiser(DistributionPathMixin, LocalOrganiserMixin):
    """Organiser for RPM packages based on distribution."""


class FlatOrganiser(FlatPathMixin, LocalOrganiserMixin):
    """Organiser for RPM packages as a flat directory."""


class AzureDistributionOrganiser(DistributionPathMixin, AzureOrganiserMixin):
    """Organiser for RPM packages based on distribution in Azure Blob Storage."""


class AzureFlatOrganiser(FlatPathMixin, AzureOrganiserMixin):
    """Organiser for RPM packages as flat packages in Azure Blob Storage."""
