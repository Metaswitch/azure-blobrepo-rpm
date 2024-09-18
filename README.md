# rpm-package-function

Functionality to create an RPM package repository in Azure Blob Storage with
an Azure Function App to keep it up to date, and a DNF plugin to use it.

# Getting Started

## Required tools

- `poetry` and `poetry-plugin-export`: required for running the creation commands and exporting dependencies to requirements.txt format.
  - Poetry installation instructions are available at https://python-poetry.org/docs/#installation
  - Once poetry is installed, run
    ```bash
    poetry self add poetry-plugin-export
    ```
    to install `poetry-plugin-export`.
- Azure CLI
  - Installation instructions available at https://learn.microsoft.com/en-us/cli/azure/install-azure-cli

- Docker
  - Installation instructions available at https://docs.docker.com/engine/install/

## Basic usage

To create a new RPM package repository with an Azure Function App, run

```bash
poetry run create-resources <resource_group_name>
```

with the name of the desired resource group. The scripting will autogenerate a
package repository name for you - `rpmrepo` followed by a unique string to
differentiate it across Azure.

If you wish to control the suffix used, you can pass the `--suffix` parameter:

```bash
poetry run create-resources --suffix <suffix> <resource_group_name>
```
which will attempt to create a storage container named `rpmrepo<suffix>`.

By default all resources are created in the `eastus` location - this can be
overridden by passing the `--location` parameter:

```bash
poetry run create-resources --location uksouth <resource_group_name>
```

## Installing the `dnf` plugin and downloading packages

To download packages:

- Copy the `dnf-plugins/dnf-plugin-azure-auth.py` module to the Python
  system site-packages directory, under the `dnf-plugins` subdirectory.
  - The system site packages directory can be determined by running:

    ```shell
    python3 -c 'import site; print(site.getsitepackages())'
    ```

- Create a repository file `/etc/yum.repos.d/<storage account name>.repo` with the following content
  for each distribution you want to support:

  ```ini
  [<storage account name>{distribution}]
  name=<storage account name>{distribution}
  baseurl={base url given by create-resources}/{distribution-letters}/{distribution-numbers}/
  enabled=1
  gpgcheck=0
  skip_if_unavailable=1
  ```

  For example, to support a distribution `el8` in storage account `rpmrepodemo`
  the repository file might look like:

  ```ini
  [rpmrepodemoel8]
  name=rpmrepodemoel8
  baseurl=https://rpmrepodemo.blob.core.windows.net/packages/el/8/
  enabled=1
  gpgcheck=0
  skip_if_unavailable=1
  ```

  and a distribution 'fc34' would look like:

  ```ini
  [rpmrepodemofc34]
  name=rpmrepodemofc34
  baseurl=https://rpmrepodemo.blob.core.windows.net/packages/fc/34/
  enabled=1
  gpgcheck=0
  skip_if_unavailable=1
  ```

  Multiple repository definitions can exist in the same file.

- Create an authentication token in the environment with the name `AZURE_STORAGE_TOKEN_<storage account uppercased>` (e.g. `AZURE_STORAGE_TOKEN_RPMREPODEMO`)

  export `AZURE_STORAGE_TOKEN_<storage account uppercased>`=$(az account get-access-token --query accessToken --output tsv --resource https://storage.azure.com)

  You must have 'Storage Blob Data Reader' access to the storage account.
- Now, use yum/dnf as normal!

  ```shell
  $ dnf list | grep rpmrepo
  Using Azure authentication for rpmrepodemocm2
  demo.x86_64                                                    1.0.0-1.cm2                    rpmrepodemocm2
  ```

# Design

The function app works as follows:

- It is triggered whenever an `.rpm` file is uploaded to the monitored blob
  storage container in the configured upload directory.
    - It is triggered by an Event Grid trigger.
- The packages are organised by distribution.
    - This is determined by the `release` of the package - the expected format
      for this is
      `<version number>.<distribution>[.<minor bump>]`
    - The distribution is expected to be a series of letters followed by a series
      of numbers
    - Any packages without a distribution are moved to the `rejected` folder.
    - Any packages that have the same name as an existing package remain in
      the upload directory.
- It then iterates over all `.rpm` files and looks for a matching `.package` file.
- If that file does not exist, it is created
    - The `.rpm` file is downloaded and repository metadata is generated using
      `createrepo_c`.
    - The metadata is bundled into the `.package` file.
- All `.package` files within a distribution are iterated over, downloaded, and
  combined into a single set of repository metadata using `mergerepo_c`.

## Speed of repository update

The function app triggers at the speed of an Event Grid trigger running in Consumption
mode; in the worst case this means triggering from a Cold Start. In practice
the repository is updated within 1 minute.

# Project

## Contributing

This project welcomes contributions and suggestions.  Most contributions require you to agree to a
Contributor License Agreement (CLA) declaring that you have the right to, and actually do, grant us
the rights to use your contribution. For details, visit https://cla.opensource.microsoft.com.

When you submit a pull request, a CLA bot will automatically determine whether you need to provide
a CLA and decorate the PR appropriately (e.g., status check, comment). Simply follow the instructions
provided by the bot. You will only need to do this once across all repos using our CLA.

This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/).
For more information see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/) or
contact [opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional questions or comments.

## Trademarks

This project may contain trademarks or logos for projects, products, or services. Authorized use of Microsoft
trademarks or logos is subject to and must follow
[Microsoft's Trademark & Brand Guidelines](https://www.microsoft.com/en-us/legal/intellectualproperty/trademarks/usage/general).
Use of Microsoft trademarks or logos in modified versions of this project must not cause confusion or imply Microsoft sponsorship.
Any use of third-party trademarks or logos are subject to those third-party's policies.
