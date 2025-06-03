# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Fixtures for the RPM package function tests."""

import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Generator, List

import pytest

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())


def create_rpm_in_dir(directory: Path, name: str, version: str, release: str) -> Path:
    """Create a test RPM package in a directory."""
    # Create a temporary file to have inside the RPM package
    temp_file = directory / "tempfile"
    temp_file.touch()

    # Create an RPM package using `fpm`.
    cmd = [
        "fpm",
        "-s",
        "dir",
        "-t",
        "rpm",
        "--name",
        name,
        "--version",
        version,
        "--iteration",
        release,
        f"{temp_file}=/tempfile",
    ]
    subprocess.run(cmd, cwd=directory, check=True)

    # Find the RPM package and return it
    rpm_packages = directory.glob("*.rpm")

    return next(rpm_packages)


@pytest.fixture(name="rpm_packages", scope="function")
def fixture_rpm_packages(request) -> Generator[List[Path], None, None]:  # noqa: ANN001
    """Create a test RPM package."""
    # Unpack the parameters
    config: List[Dict[str, Any]] = request.param

    with tempfile.TemporaryDirectory() as temp_dir:
        packages = []
        for package_config in config:
            name = package_config["name"]
            version = package_config["version"]
            release = package_config["release"]

            temp_path = Path(temp_dir) / f"{name}-{version}-{release}"
            temp_path.mkdir()
            package = create_rpm_in_dir(temp_path, name, version, release)
            packages.append(package)

        yield packages

    # Upon return everything will be deleted in the temporary directory


@pytest.fixture(name="repository", scope="function")
def fixture_repository(request) -> Generator[Path, None, None]:  # noqa: ANN001
    """Create a test repository."""
    # Unpack the parameters

    config: Dict[str, Any] = request.param

    upload_directory = str(config["upload_directory"])
    upload_packages = config.get("upload_packages", [])

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        upload_dir = root / upload_directory
        upload_dir.mkdir(parents=True)

        for upload_package in upload_packages:
            name = upload_package["name"]
            version = upload_package["version"]
            release = upload_package["release"]
            create_rpm_in_dir(upload_dir, name, version, release)

        yield root

    # Upon return everything will be deleted in the temporary directory
