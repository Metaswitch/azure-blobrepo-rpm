#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Creates resources for the rpm package function in Azure."""

import argparse
import logging
import sys
from pathlib import Path

from azure_blobrepo_rpm.tooling import common_logging
from azure_blobrepo_rpm.tooling.advice import advice_distribution_repo, advice_flat_repo
from azure_blobrepo_rpm.tooling.bicep_deployment import BicepDeployment
from azure_blobrepo_rpm.tooling.func_app import FuncAppBundle
from azure_blobrepo_rpm.tooling.poetry import extract_requirements
from azure_blobrepo_rpm.tooling.resource_group import create_rg

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())


def main() -> None:
    """Create resources."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "resource_group", help="The name of the resource group to create resources in."
    )
    parser.add_argument(
        "--location",
        default="eastus",
        help="The location of the resources to create. A list of location names can be obtained by running 'az account list-locations --query \"[].name\"'",
    )
    parser.add_argument(
        "--suffix",
        help="Unique suffix for the repository name. If not provided, a random suffix will be generated. Must be 14 characters or fewer.",
    )
    parser.add_argument(
        "--upload-directory",
        default="upload",
        help="Path within the storage container to upload packages to.",
    )
    parser.add_argument(
        "--repo-type",
        choices=["flat", "distribution"],
        default="distribution",
        help="The type of repository to create.",
    )

    args = parser.parse_args()

    if args.suffix and len(args.suffix) > 14:
        raise ValueError("Suffix must be 14 characters or fewer.")

    # Create the resource group
    create_rg(args.resource_group, args.location)

    # Ensure requirements.txt exists
    extract_requirements(Path("requirements.txt"))

    # Create resources with Bicep
    #
    # Set up parameters for the Bicep deployment
    common_parameters = {}
    if args.suffix:
        common_parameters["suffix"] = args.suffix

    initial_parameters = {
        "use_shared_keys": False,
        "repo_type": args.repo_type,
        "upload_directory": args.upload_directory,
    }
    initial_parameters.update(common_parameters)

    # Use the same deployment name as the resource group
    deployment_name = args.resource_group

    initial_resources = BicepDeployment(
        deployment_name=deployment_name,
        resource_group_name=args.resource_group,
        template_file=Path("rg.bicep"),
        parameters=initial_parameters,
        description="initial resources",
    )
    initial_resources.create()

    outputs = initial_resources.outputs()
    log.debug("Deployment outputs: %s", outputs)
    base_url = outputs["base_url"]
    function_app_name = outputs["function_app_name"]
    package_container = outputs["package_container"]
    python_container = outputs["python_container"]
    storage_account = outputs["storage_account"]

    # Create the function app
    funcapp_parameters = {
        "repo_type": args.repo_type,
        "upload_directory": args.upload_directory,
    }
    funcapp_parameters.update(common_parameters)

    funcapp = FuncAppBundle(
        name=function_app_name,
        resource_group=args.resource_group,
        storage_account=storage_account,
        python_container=python_container,
        parameters=funcapp_parameters,
    )

    with funcapp as cm:
        cm.deploy()
        cm.wait_for_event_trigger()

    # At this point the function app exists and the event trigger exists, so the
    # event grid deployment can go ahead.
    event_grid_deployment = BicepDeployment(
        deployment_name=f"{deployment_name}_eg",
        resource_group_name=args.resource_group,
        template_file=Path("rg_add_eventgrid.bicep"),
        parameters=common_parameters,
        description="Event Grid trigger configuration",
    )
    event_grid_deployment.create()

    # Inform the user of success!
    if args.repo_type == "distribution":
        advice_distribution_repo(
            args.upload_directory,
            package_container,
            storage_account,
            function_app_name,
            base_url,
        )
    elif args.repo_type == "flat":
        advice_flat_repo(
            args.upload_directory,
            package_container,
            storage_account,
            function_app_name,
            base_url,
        )
    else:
        raise ValueError(f"Invalid repo type: {args.repo_type}")


def run() -> None:
    """Entrypoint which sets up logging."""
    common_logging(__name__, __file__, stream=sys.stderr)
    main()


if __name__ == "__main__":
    run()
