# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""A function app to manage an RPM repository in Azure Blob Storage."""

import logging
import os

import azure.functions as func
from azure.identity import DefaultAzureCredential
from azure.storage.blob import ContainerClient

from azure_blobrepo_rpm import (
    AzureBaseRepository,
    AzureDistributionRepository,
    AzureFlatRepository,
)

app = func.FunctionApp()
log = logging.getLogger("azure-blobrepo-rpm")
log.addHandler(logging.NullHandler())

# Turn down logging for azure functions
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(
    logging.WARNING
)

CONTAINER_NAME = os.environ["BLOB_CONTAINER"]
UPLOAD_DIRECTORY = os.environ.get("UPLOAD_DIRECTORY", "upload")
REPO_TYPE = os.environ.get("REPO_TYPE", "distribution")


@app.function_name(name="eventGridTrigger")
@app.event_grid_trigger(arg_name="event")
def event_grid_trigger(event: func.EventGridEvent) -> None:
    """Process an event grid trigger for a new blob in the container."""
    log.info("Processing event %s", event.id)

    container_client: ContainerClient

    if "AzureWebJobsStorage" in os.environ:
        # Use a connection string to access the storage account
        connection_string = os.environ["AzureWebJobsStorage"]
        container_client = ContainerClient.from_connection_string(
            conn_str=connection_string, container_name=CONTAINER_NAME
        )
    else:
        # Use credentials to access the container. Used when shared-key
        # access is disabled.
        credential = DefaultAzureCredential()
        container_client = ContainerClient.from_container_url(
            container_url=os.environ["BLOB_CONTAINER_URL"],
            credential=credential,
        )

    # Create a repository object based on the repo type
    repo: AzureBaseRepository

    if REPO_TYPE == "flat":
        repo = AzureFlatRepository(container_client, upload_directory=UPLOAD_DIRECTORY)
    elif REPO_TYPE == "distribution":
        repo = AzureDistributionRepository(
            container_client, upload_directory=UPLOAD_DIRECTORY
        )
    else:
        raise ValueError(f"Invalid repo type: {REPO_TYPE}")

    # Process the event
    repo.process()

    log.info("Done processing event %s", event.id)
