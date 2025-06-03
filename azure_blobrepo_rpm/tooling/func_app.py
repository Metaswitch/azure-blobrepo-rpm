# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Management of function applications"""

import json
import logging
import subprocess
import time
from pathlib import Path
from subprocess import CalledProcessError
from types import TracebackType
from typing import Any, Dict, Optional, Type

from azure_blobrepo_rpm.tooling.azcmd import AzCmdJson, AzCmdNone
from azure_blobrepo_rpm.tooling.bicep_deployment import BicepDeployment

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())


class FuncApp:
    """Basic class for managing function apps."""

    def __init__(self, name: str, resource_group: str, output_path: Path) -> None:
        """Create a FuncApp object."""
        self.name = name
        self.resource_group = resource_group
        self.output_path = output_path

    def wait_for_event_trigger(self) -> None:
        """Wait until the function app has an eventGridTrigger function."""
        cmd = AzCmdJson(
            [
                "az",
                "functionapp",
                "function",
                "list",
                "-n",
                self.name,
                "-g",
                self.resource_group,
                "--query",
                "[].name",
            ]
        )
        log.info("Awaiting event trigger on function app %s", self.name)

        while True:
            try:
                functions = cmd.run_expect_list()
                log.info("App functions (%s): %s", self.name, functions)

                for function in functions:
                    if "eventGridTrigger" in function:
                        log.info("Found Event Grid trigger: %s", function)
                        return

            except json.JSONDecodeError as e:
                log.warning("Error decoding JSON: %s", e)
            except CalledProcessError as e:
                log.debug("Error running command: %s", e)

            time.sleep(5)

    def __enter__(self) -> "FuncApp":
        """Return the object for use in a context manager."""
        return self

    def __exit__(
        self,
        _exc_type: Optional[Type[BaseException]],
        _exc_value: Optional[BaseException],
        _exc_traceback: Optional[TracebackType],
    ) -> None:
        """Clean up the object."""
        if self.output_path.exists():
            self.output_path.unlink()

    def deploy(self) -> None:
        """Deploy the function application."""
        raise NotImplementedError(
            "Subclasses must implement the deploy method to deploy the function app."
        )


class FuncAppBundle(FuncApp):
    """Bundles the function app using the core-tools tooling."""

    def __init__(
        self,
        name: str,
        resource_group: str,
        storage_account: str,
        python_container: str,
        parameters: Dict[str, Any],
    ) -> None:
        """Create a FuncAppBundle object."""
        # The function app bundle gets created as function_app.zip
        super().__init__(name, resource_group, Path("function_app.zip"))
        self.storage_account = storage_account
        self.python_container = python_container
        self.parameters = parameters

        cwd = Path.cwd()

        # Pack the application using the core-tools tooling
        # Should generate a file called function_app.zip
        cmd = [
            "docker",
            "run",
            "-it",
            "--rm",
            "-v",
            "/var/run/docker.sock:/var/run/docker.sock",
            "-v",
            f"{cwd}:/function_app",
            "-w",
            "/function_app",
            "mcr.microsoft.com/azure-functions/python:4-python3.11-core-tools",
            "bash",
            "-c",
            "func pack --python --build-native-deps",
        ]
        log.debug("Running %s", cmd)
        subprocess.run(cmd, check=True)

    def deploy(self) -> None:
        """Deploy the function application."""
        log.info("Copying function app code to %s", self.python_container)
        cmd = AzCmdNone(
            [
                "az",
                "storage",
                "blob",
                "upload",
                "--auth-mode",
                "login",
                "--account-name",
                self.storage_account,
                "--container-name",
                self.python_container,
                "--file",
                str(self.output_path),
                "--name",
                str(self.output_path),
                "--overwrite",
            ]
        )
        cmd.run()

        # Create the function app
        func_app_params = {
            "use_shared_keys": False,
        }
        func_app_params.update(self.parameters)

        func_app_deploy = BicepDeployment(
            deployment_name=f"deploy_{self.name}",
            resource_group_name=self.resource_group,
            template_file=Path("rg_funcapp.bicep"),
            parameters=func_app_params,
            description="function app",
        )
        func_app_deploy.create()
