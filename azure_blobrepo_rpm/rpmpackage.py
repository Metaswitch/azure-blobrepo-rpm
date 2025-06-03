# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Classes to extract RPM package information for a given package file."""

import logging
import re
import shutil
import tempfile
from collections import namedtuple
from pathlib import Path
from typing import Optional

import rpmfile
from azure.storage.blob import BlobClient, ContainerClient

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())


PackageInfo = namedtuple("PackageInfo", ["name", "version", "dist", "arch", "release"])


class BaseRpmPackage:
    """Base class for RPM package information."""

    def name(self) -> str:
        """Get the name of the package."""
        raise NotImplementedError

    def version(self) -> str:
        """Get the version of the package."""
        raise NotImplementedError

    def dist(self) -> Optional[str]:
        """Get the distribution of the package."""
        raise NotImplementedError

    def arch(self) -> str:
        """Get the architecture of the package."""
        raise NotImplementedError

    def release(self) -> str:
        """Get the release of the package."""
        raise NotImplementedError

    def package_filename(self) -> str:
        """Get the filename of the package."""
        raise NotImplementedError

    def _package_info(self, path: Path) -> PackageInfo:
        """Extract the package information from the RPM file."""
        with rpmfile.open(str(path)) as rpm:
            # Load data from the RPM headers. The data is binary, so we
            # need to decode it.
            headers = rpm.headers

            # Extract the package name and version.
            name = headers["name"].decode("utf-8")
            version = headers["version"].decode("utf-8")

            # Extract the release number and architecture if they exist.
            release = headers.get("release", b"").decode("utf-8")
            arch = headers.get("arch", b"").decode("utf-8")

            # The Fedora versioning guidelines say to use the %autorelease macro
            # to control the release number. This macro is the number of
            # builds since the last version change, suffixed with the
            # distribution of the build (e.g. 1%{?dist}, 2%{?dist}, etc.).
            # Since this is a `should` and not a `must`, we can't rely on it,
            # but if the version number matches the format, let's use it.
            #
            # AzureLinux doesn't use %autorelease but does use the same N%{?dist}
            # scheme.
            #
            # Technically there can also be a `minor_bump` in the release number,
            # which is a number after a dot. We should also handle that.
            pattern = r"^\d+\.([^\.]+)"

            dist: Optional[str]

            if m := re.match(pattern, release):
                dist = m.group(1)
            else:
                dist = None

            return PackageInfo(name, version, dist, arch, release)

    def move(self, new_path_str: str) -> None:
        """Move the package."""
        raise NotImplementedError


class LocalRpmPackage(BaseRpmPackage):
    """A class to extract RPM package information from a package file."""

    def __init__(self, path: Path) -> None:
        """Create a new LocalRpmPackage object."""
        self.path = path

        info = self._package_info(path)
        self._name = info.name
        self._version = info.version
        self._dist = info.dist
        self._arch = info.arch
        self._release = info.release

    def name(self) -> str:
        """Get the name of the package."""
        return self._name

    def version(self) -> str:
        """Get the version of the package."""
        return self._version

    def dist(self) -> Optional[str]:
        """Get the distribution of the package."""
        return self._dist

    def arch(self) -> str:
        """Get the architecture of the package."""
        return self._arch

    def release(self) -> str:
        """Get the release of the package."""
        return self._release

    def package_filename(self) -> str:
        """Get the filename of the package."""
        return self.path.name

    def move(self, new_path_str: str) -> None:
        """Move the package."""
        old_path = self.path
        new_path = Path(new_path_str)
        self.path.rename(new_path)
        self.path = new_path
        log.debug("Package moved from %s to %s", old_path, new_path)

    def __str__(self) -> str:
        """Return a string representation of the package."""
        return (
            f"{self.__class__.__name__}(name: {self.name()}; "
            f"version: {self.version()}; dist: {self.dist()})"
        )


class RemoteRpmPackage(BaseRpmPackage):
    """A class to extract RPM package information from a remote package file."""

    def __init__(self, path: Path, container_client: ContainerClient) -> None:
        """Create a new RemoteRpmPackage object."""
        self.path = path
        self.container_client = container_client
        self.local_package: Optional[LocalRpmPackage] = None

    def __repr__(self) -> str:
        """Return a string representation of the package."""
        return f"{self.__class__.__name__}({self.path!r}, {self.container_client!r})"

    def __str__(self) -> str:
        """Return a string representation of the package."""
        return f"{self.__class__.__name__}({self.path})"

    def _get_package(self) -> LocalRpmPackage:
        """Download the package to a temporary file."""
        if self.local_package is None:
            # Need to download the package
            with tempfile.NamedTemporaryFile(delete=False) as f:
                temp_filename = f.name

            blob_client = self.blob_client()

            with open(temp_filename, "wb") as f:
                stream = blob_client.download_blob()
                f.write(stream.readall())

            self.local_package = LocalRpmPackage(Path(temp_filename))
            log.debug("Package downloaded to %s", temp_filename)

        return self.local_package

    def blob_client(self) -> BlobClient:
        """Get the BlobClient for the package."""
        return self.container_client.get_blob_client(str(self.path))

    def name(self) -> str:
        """Get the name of the package."""
        return self._get_package().name()

    def version(self) -> str:
        """Get the version of the package."""
        return self._get_package().version()

    def dist(self) -> Optional[str]:
        """Get the distribution of the package."""
        return self._get_package().dist()

    def arch(self) -> str:
        """Get the architecture of the package."""
        return self._get_package().arch()

    def release(self) -> str:
        """Get the release of the package."""
        return self._get_package().release()

    def package_filename(self) -> str:
        """Get the filename of the package."""
        return self.path.name

    def move(self, new_path_str: str) -> None:
        """Rename the package in the container."""
        old_path = self.path
        blob_client = self.blob_client()
        new_blob_client = self.container_client.get_blob_client(new_path_str)

        # Check if the new blob already exists
        if new_blob_client.exists():
            raise FileExistsError(f"{new_path_str} already exists")

        # Copy the blob to the new location
        new_blob_client.start_copy_from_url(blob_client.url)

        # Delete the old blob
        blob_client.delete_blob()

        # Update the path
        self.path = Path(new_path_str)
        log.info("Package moved from %s to %s", old_path, new_path_str)

    def copy_local(self, local_path: Path) -> None:
        """Copy the package to a local file."""
        package = self._get_package()
        shutil.copy(package.path, local_path)
        log.debug("Package copied to %s", local_path)
