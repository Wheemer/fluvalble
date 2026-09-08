# Contributing

Thanks for your interest in the Fluval BLE Home Assistant integration.
This project is small and friendly — please open an issue or discussion
before sending a large change so we can agree on direction first.

## Branch workflow

This repository uses short-lived branches merged into `main`:

- `main` is the released code. Do not push directly to it; open a PR from a
  focused branch and merge only after the required checks pass.
- Feature/fix branches follow the `feature/<slug>` or `fix/<slug>`
  convention. Use `release/vX.Y.Z` for release preparation.

## Local development

```bash
# 1. Install dev tooling
python -m venv .venv
source .venv/bin/activate
pip install --upgrade -r requirements.txt
pre-commit install

# 2. Run the test suite
pytest tests/ -v

# 3. Lint + format
ruff check custom_components/ tests/
ruff format --check custom_components/ tests/
```

Python development dependencies are intentionally unpinned in `requirements.in`.
`requirements.txt` includes that list; it is not a generated lockfile.
Fresh CI environments resolve the latest compatible versions. To update an
existing local environment, run `pip install --upgrade -r requirements.txt`.
Pre-commit uses that environment's Ruff rather than a separately pinned copy.
Dependency changes can affect builds without a repository commit; CI checks
compatibility when it runs. GitHub Actions retain their security commit pins.

## Tests

- New behaviour **must** come with a unit test. We use `pytest` and
  `pytest-asyncio`.
- Keep the suite green. The CI lint and test jobs must pass before a
  PR can be merged.
- Coverage must remain at or above the floor in `pyproject.toml`
  (currently 33%, with a target of ~70% as entity-platform tests land).

## Code style

- Ruff enforces the style — there is no separate style guide. Run
  `ruff format` before committing.
- Type hints are encouraged but not yet enforced. Mypy runs in CI as a
  soft check.

## Reporting bugs

Before opening a new issue, please check the open issues and the
`docs/bug-triage.md` document. When you do open an issue, include:

1. Integration version (Settings → Devices & services → ⓘ)
2. Lamp model (Plant 3.0, Aquasky 2.0, etc.)
3. Bluetooth adapter (built-in, ESP32 proxy, etc.)
4. A debug log snippet with `custom_components.fluvalble: debug` enabled
5. The exact steps to reproduce

## Release process

Releases are tag-driven. The maintainer:

1. Adds a dated `## [X.Y.Z]` entry to `CHANGELOG.md` covering the release.
2. Bumps `version` in `custom_components/fluvalble/manifest.json`.
3. Opens and merges a `release/vX.Y.Z` PR into `main` after CI passes.
4. Tags that exact merge commit: `git tag vX.Y.Z && git push origin vX.Y.Z`.
5. The `release.yml` workflow builds the release assets and publishes
   a GitHub release. Verify the release, zip asset, and manifest version before
   announcing it.

## License

By contributing, you agree that your contributions will be licensed
under the Apache License 2.0 (see `LICENSE`).
