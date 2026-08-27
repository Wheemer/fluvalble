# AGENTS.md

Guidance for AI coding agents (Hermes, Claude Code, Codex, Cursor, etc.)
working in this repository. Read this before you start changing code.

## Project at a glance

- **What:** Home Assistant custom integration for Fluval aquarium LED
  lights over BLE.
- **Language:** Python 3.11 / 3.12.
- **Framework:** Home Assistant core APIs (`homeassistant.components.bluetooth`,
  `ConfigEntry`, `Platform`).
- **Test framework:** `pytest` + `pytest-asyncio`.
- **Lint/format:** `ruff` (lint + format). Mypy runs in CI as a soft
  check (not yet gating).
- **Coverage floor:** 33% (configured in `pyproject.toml`). The floor
  is intentionally low to start — most of the platform/entity code is
  exercised via HA's own test harness rather than unit tests. A follow-up
  PR should add entity-platform tests and raise the floor to ~70%.
- **Branch model:** focused feature/fix/release branches → `main`. Direct pushes
  to `main` are not part of the release workflow.

## Where to look

| Concern | Path |
|---|---|
| Integration entry point, platforms, lifecycle | `custom_components/fluvalble/__init__.py` |
| BLE client (connection, read/write) | `custom_components/fluvalble/core/client.py` |
| Device state machine | `custom_components/fluvalble/core/device.py` |
| Fluval packet encryption | `custom_components/fluvalble/core/encryption.py` |
| BLE protocol constants | `custom_components/fluvalble/core/__init__.py` |
| HA config flow | `custom_components/fluvalble/config_flow.py` |
| Entities (light, mode, clock sync, reachable, diagnostics) | `custom_components/fluvalble/{light,select,button,binary_sensor,sensor}.py` |
| Tests | `tests/` |
| CI/release | `.github/workflows/ci.yml`, `.github/workflows/release-readiness.yml`, `.github/workflows/release.yml` |

## Commands an agent will need

```bash
# Run the test suite (must pass)
pytest tests/ -v

# Lint + format check
ruff check custom_components/ tests/
ruff format --check custom_components/ tests/

# Auto-format the codebase
ruff format custom_components/ tests/

# Type-check (soft, not gating)
mypy custom_components/fluvalble/

# Coverage report
pytest tests/ --cov=custom_components/fluvalble --cov-report=term-missing
```

## What agents must NOT do

- **Do not** push directly to `main`. Use a focused branch and a PR with passing
  checks.
- **Do not** change the BLE protocol implementation
  (`core/encryption.py`, command bytes / constants in `core/__init__.py`
  and `core/client.py`) without a protocol capture or hardware
  verification. See `docs/bug-triage.md` for the open issues
  (#6 Aquasky 2.0, #8 RTC drift) that need protocol evidence to fix.
- **Do not** bump the `version` in `manifest.json` without also
  updating `CHANGELOG.md`.
- **Do not** edit the existing `release-readiness.yml` or `release.yml`
  workflows without a maintainer review — they own the release train.
- **Do not** add new top-level dependencies to `manifest.json` without
  considering whether they should be `requirements` (run-time) or development
  only (pinned in `requirements.in` and compiled into `requirements.txt`).
- **Do not** rename the integration domain (`fluvalble`). It is the
  config-flow key and HACS identifier.

## What agents SHOULD do

- Read `docs/bug-triage.md` before assuming an open issue is unfixed.
- Add a unit test for any new behaviour in `core/`, `__init__.py`, or
  any of the entity platforms.
- Keep the public BLE interface (anything in `core/`) backward
  compatible — the config flow and platforms depend on it.
- Prefer editing an existing file to creating a new one unless the new
  file has a clear single concern.

## Verifying a change

Before handing a change back to the maintainer, run:

```bash
pytest tests/ -v
ruff check custom_components/ tests/
ruff format --check custom_components/ tests/
```

All three must pass. If the change touched a platform file
(`light.py`, `select.py`, etc.) or the config flow, also re-read the
relevant section of `README.md` and update it if the user-visible
behaviour changed.

## Background

- Reverse-engineering credits and protocol sources are in
  `README.md` → "How it works".
- Hardware-gated issues and protocol boundaries are tracked in
  `docs/bug-triage.md`. Do not turn unverified protocol guesses into support
  claims; record the exact model, transport, and validation evidence.
