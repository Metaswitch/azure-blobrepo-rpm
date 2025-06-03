# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Functions for displaying advice after creating a repository"""


def advice_distribution_repo(
    upload_directory: str,
    package_container: str,
    storage_account: str,
    function_app_name: str,
    base_url: str,
) -> None:
    """Print advice for a distribution repository."""
    print(
        f"""The repository has been created!
Upload packages to the '{upload_directory}/' directory in the
'{package_container}' container in the '{storage_account}' storage account.
The function app '{function_app_name}' will be triggered by new packages
in that container and regenerate the repository.

To download packages:
  - Install `dnf-plugin-azure-auth`.
    - Install the plugin from https://github.com/microsoft/dnf-plugin-azure-auth

  - Create a repository file `/etc/yum.repos.d/{storage_account}.repo` with the following content
    for each distribution you want to support:

[{storage_account}`dist`]
name={storage_account}`dist`
baseurl={base_url}/`dist-letters`/`dist-numbers`/
enabled=1
gpgcheck=0
skip_if_unavailable=1

    and add an entry to `/etc/dnf/plugins/azure_auth.conf` with the following format:

[{storage_account}`dist`]

    For example, to support a distribution 'el8' the repository file would look like:

[{storage_account}el8]
name={storage_account}el8
baseurl={base_url}/el/8/
enabled=1
gpgcheck=0
skip_if_unavailable=1

    and the `azure_auth.conf` configuration entry would look like

[{storage_account}el8]

    A distribution 'fc34' would have a repository file like:

[{storage_account}fc34]
name={storage_account}fc34
baseurl={base_url}/fc/34/
enabled=1
gpgcheck=0
skip_if_unavailable=1

    and the `azure_auth.conf` configuration entry would look like

[{storage_account}fc34]

    Multiple repository definitions can exist in the same file.
    Multiple entries can exist in `azure_auth.conf`.

  - Now, use yum/dnf as normal!"""
    )


def advice_flat_repo(
    upload_directory: str,
    package_container: str,
    storage_account: str,
    function_app_name: str,
    base_url: str,
) -> None:
    """Print advice for a flat repository."""
    print(
        f"""The repository has been created!
Upload packages to the '{upload_directory}/' directory in the
'{package_container}' container in the '{storage_account}' storage account.
The function app '{function_app_name}' will be triggered by new packages
in that container and regenerate the repository.

To download packages:
  - Install `dnf-plugin-azure-auth`.
    - Install the plugin from https://github.com/microsoft/dnf-plugin-azure-auth

  - Create a repository file `/etc/yum.repos.d/{storage_account}.repo` with the following content:

[{storage_account}]
name={storage_account}
baseurl={base_url}/
enabled=1
gpgcheck=0
skip_if_unavailable=1

  - Add an entry to `/etc/dnf/plugins/azure_auth.conf` with the following format:

[{storage_account}]

  - Now, use yum/dnf as normal!"""
    )
