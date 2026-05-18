<!-- PLUGIN BADGES -->
![Project Stage][project-stage-shield]
![Project Maintenance][maintenance-shield]
[![License][license-shield]](LICENSE)

[![RHFest][rhfest-shield]][rhfest-url]

# Local Voice

This is a basic template repository for creating a plugin for the RotorHazard timing platform. It is intended to be used as a starting point for creating a new plugin.

## Features

- **Pre-commit checks**: to run checks and tests on each commit.
- **Python virtual environment**: uses [uv] to manage the python virtual environment and dependencies.
- **RHFest validation**: GitHub action to validate the plugin manifest file against the RHFest schema.
- **Renovate**: uses [Renovate](https://docs.renovatebot.com/) to keep dependencies up to date.

## Development

This Python project relies on [uv] as its dependency manager, providing comprehensive management and control over project dependencies.

You need the following tools to get started:

- [uv] - A python virtual environment/package manager
- [Python] 3.12 (or higher) - The programming language

### Installation

1. Clone the repository
2. Install all dependencies with UV. This will create a virtual environment and install all dependencies

```bash
uv sync --all-groups
```

### Prek check

As this repository uses the [prek][prek] framework, all changes are linted and tested with each commit.

To install the prek check, run:

```bash
uv run prek install
```

To run all checks and tests manually, use the following command:

```bash
uv run prek run --all-files
```

To manual run only on the staged files, use the following command:

```bash
uv run prek run
```

## License

Distributed under the **MIT** License. See [`LICENSE`](LICENSE) for more information.

<!-- LINK -->
[uv]: https://docs.astral.sh/uv/
[Python]: https://www.python.org/
[prek]: https://prek.j178.dev/

[license-shield]: https://img.shields.io/github/license/dutchdronesquad/rh-local-voice.svg
[maintenance-shield]: https://img.shields.io/maintenance/yes/2026.svg
[project-stage-shield]: https://img.shields.io/badge/project%20stage-experimental-yellow.svg
[rhfest-shield]: https://github.com/dutchdronesquad/rh-local-voice/actions/workflows/rhfest.yaml/badge.svg
[rhfest-url]: https://github.com/dutchdronesquad/rh-local-voice/actions/workflows/rhfest.yaml
[rhcp-shield]: https://img.shields.io/badge/RotorHazard-Community_Plugins-orange.svg
