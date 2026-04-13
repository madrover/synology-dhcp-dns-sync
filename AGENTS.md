# Repository Guidelines

## Project Structure & Module Organization
Source code lives under `src/synology_dhcp_dns_sync/`. Key modules include `cli.py` for command entrypoints, `syncer.py` for the main DHCP-to-DNS workflow, `watcher.py` for polling mode, and supporting modules such as `config.py`, `dhcp.py`, and `zone.py`. Tests live in `tests/` and mirror the package by behavior, for example `tests/test_syncer.py` and `tests/test_cli.py`. Operational notes and design decisions live in `docs/`. Use `config.example.ini` as the starting point for local or DSM deployment config.

## Build, Test, and Development Commands
Install the package locally with:

```bash
python3 -m pip install .
```

Run the CLI directly from the repo during development:

```bash
PYTHONPATH=src python3 -m synology_dhcp_dns_sync validate-config --config config.example.ini
PYTHONPATH=src python3 -m synology_dhcp_dns_sync sync --config config.example.ini --dry-run
PYTHONPATH=src python3 -m synology_dhcp_dns_sync watch --config config.example.ini
```

Run the test suite with:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

## Coding Style & Naming Conventions
Target Python `>=3.8`. Follow existing style: 4-space indentation, type hints on public functions, small focused modules, and standard-library-first solutions where practical. Use `snake_case` for functions, variables, and modules; `PascalCase` for classes; and clear, explicit names such as `perform_sync` or `validate_runtime_environment`. Keep CLI messages and logs concise and operationally useful.

## Testing Guidelines
This repository uses `unittest`. Add tests alongside the behavior you change and name files `test_<module>.py`. Prefer isolated tests using `tempfile.TemporaryDirectory()` and repo-style fixtures over real system paths, reload scripts, or DSM services. Cover both success and failure paths, especially rollback, locking, and config validation behavior.

## Commit & Pull Request Guidelines
There is no established commit history yet, so use short imperative commit subjects such as `Add rollback test for reload failures`. Keep commits focused on one change. Pull requests should explain the behavior change, list validation steps you ran, and note any DSM-specific assumptions or config impacts. Include sample commands or log snippets when they help reviewers verify operational behavior.

## Security & Configuration Tips
Do not commit real NAS paths, secrets, or environment-specific `config.ini` files. Treat zone paths, reload script paths, and DHCP sources as deployment-specific; use `config.example.ini` and `--dry-run` to validate changes safely before touching live zones.
