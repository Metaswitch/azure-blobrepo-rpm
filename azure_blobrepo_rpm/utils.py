# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Utility functions."""

import contextlib
import os
import tempfile
from typing import Generator


@contextlib.contextmanager
def temporary_filename() -> Generator[str, None, None]:
    """Create a temporary file and return the filename."""
    try:
        with tempfile.NamedTemporaryFile(delete=False) as f:
            temporary_name = f.name
        yield temporary_name
    finally:
        os.unlink(temporary_name)
