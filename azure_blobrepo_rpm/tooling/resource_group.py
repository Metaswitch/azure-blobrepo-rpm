# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Manages resource groups."""

import logging

from azure_blobrepo_rpm.tooling.azcmd import AzCmdNone

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())


def create_rg(
    resource_group: str, location: str, subscription: str | None = None
) -> None:
    """Create a resource group."""
    log.debug("Creating resource group %s in location %s", resource_group, location)

    cmd = AzCmdNone(
        ["az", "group", "create", "--name", resource_group, "--location", location],
        subscription=subscription,
    )
    cmd.run()
    log.info("Created resource group %s in location %s", resource_group, location)
