# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Added
- Added transport-neutral fixture-native Auto and Professional schedules for
  classic, AquaSky 3.0/FACEBD, and Plant Pro/4.0 controllers using the exact
  FluvalConnect packet layouts, including native readback and chunked BLE
  writes for larger schedule payloads.
- Added a **Fixture native** schedule-card mode that uploads a 2-12 point curve
  once, replacing the former minute-by-minute Home Assistant executor.
- Retained the fork's persistent BLE default (`active_time: 0`) while making
  finite 30-600 second idle windows an explicit configuration alternative.

### Fixed
- Corrected AquaSky 3.0/FACEBD to its four-channel RGBW profile and retained the
  last known channel state while controllers report an Automatic or
  Professional native mode.
- Restored explicit lamp-profile precedence after the upstream reconciliation so
  four-channel AquaSky controllers cannot treat trailing status bytes as a
  fifth physical channel.
- Replaced disconnected Bleak clients instead of reconnecting the same object,
  while resolving Home Assistant's latest local-adapter or ESPHome-proxy route
  for each fresh connection.
- Serialized reconnects with commands and integration unload so an old command
  cannot disconnect a replacement client or restart work after shutdown.

---

## [0.1.2] - 2026-08-30

### Fixed
- Kept classic Fluval manufacturer data as discovery evidence without treating
  it as proof of the newer FACEBD protocol, preventing incorrect initial
  protocol and channel-profile selection.
- Restored canonical lowercase GATT UUIDs and defensive case-insensitive
  characteristic lookup for ESPHome 2026.x / esp-idf 5.x Bluetooth proxies.
- Normalized live Bluetooth addresses, entity unique IDs, and device-registry
  identifiers to uppercase so mixed-case proxy reports cannot duplicate or
  orphan Fluval entities.
- Completed classic discovery corroboration by combining the Fluval/Hagen
  manufacturer ID with a valid APK-format product payload.

---

## [0.1.1] - 2026-08-27

### Fixed
- Corrected the documented minimum Home Assistant version to 2025.8.0, where
  `OptionsFlowWithReload` became available, and synchronized the HACS metadata.
- Legacy switch and per-channel number entities are now removed from the entity
  registry during config-entry setup, alongside the retired diagnostic entities.
- Replaced misleading MAC-shaped entity IDs with clearly labeled examples and
  clarified that Home Assistant assigns the actual entity IDs.
- Qualified native-effect support according to its real APK and hardware evidence,
  consolidated duplicate Plant Pro schedule documentation, and documented all
  connection options and integration actions, including profile-correct physical
  channel labels in the Home Assistant action UI.

---

## [0.1.0] - 2026-08-27

This is the first consolidated stable release from the Wheemer fork. It includes
the previously documented 0.0.32 and 0.0.33 work, which had not been published as
GitHub releases.

### Added
- First-class Home Assistant light control with protocol-aware colour mapping for
  classic Plant/Marine, AquaSky RGBW, AquaSky 3.0, and Plant Pro / 4.0 profiles.
- Eleven verified classic FluvalSmart dynamic effect IDs and the four native
  Plant Pro / 4.0 Sun/Moon scene indices exposed through Home Assistant effects.
- Home Assistant-managed scheduling plus Plant Pro / 4.0 fixture-native Auto and
  Professional schedule write/readback support.
- Clock synchronization, lamp-profile selection, redacted diagnostics, and a
  Bluetooth **Reachable** diagnostic based on recent advertisements or a live
  GATT connection.
- Plant Pro / 4.0 mesh/SPP (`fff0`/`fff1`/`fff2`, `0xD1` + CBOR) control,
  including five-channel Red/Blue/Cool White/Warm White/Amber handling.

### Changed
- Home Assistant config entries now use the standard unload/setup lifecycle;
  options reload without the integration attempting Python module self-reloads.
- BLE connection handling uses one bounded retry cycle, immediate serialized
  recovery for unexpected persistent-session drops, and optional permanent
  connections via `active_time: 0` for low command latency.
- Discovery is restricted to Fluval-specific names, services, and manufacturer
  data, while configured lights are deduplicated by Bluetooth identity.
- Python, CI, pre-commit, branding, and GitHub Actions dependencies are pinned at
  current releases and monitored by Dependabot; CodeQL and repository security
  automation are enabled.
- User, contributor, agent, issue-triage, and release documentation now reflects
  the light-first entity model, current hardware evidence, and branch-to-`main`
  release process. Release-readiness checks run for `release/*` PRs.

### Fixed
- Power-off no longer sends intermediate colour frames or visibly fades through
  unrelated colours.
- Corrected classic and Plant Pro effect assignments, classic Blue-family channel
  counts, AquaSky colour-state restoration, and ESPHome-proxy write behavior.
- Fixed false Bluetooth detections, duplicate Fluval device-registry rows, stale
  entity cleanup, options-flow failures, clock-sync retries, and reload teardown.
- Diagnostics redact Bluetooth addresses, advertised names, manufacturer/service
  payloads, and registry identifiers.

### Credits
- Original Fluval BLE integration and upstream project by
  [@MrMooreUK](https://github.com/MrMooreUK) and prior contributors.
- Plant Pro / 4.0 protocol behavior was derived from FluvalConnect APK analysis
  and cross-checked against the hardware-validated MIT-licensed
  [cryystyy/fluval-plant-pro-4-homeassistant](https://github.com/cryystyy/fluval-plant-pro-4-homeassistant)
  project.
- Classic protocol research and supporting work by
  [@kw217](https://github.com/kw217) and the Fluval community.
- Hardware validation, Home Assistant refinements, and consolidated release work
  by [@Wheemer](https://github.com/Wheemer).

---

## [0.0.33] - 2026-08-27

### Added
- Plant Pro / Plant 4.0 BLE support using the FluvalConnect `fff0`/`fff1`/`fff2`
  mesh/SPP protocol (`0xD1` + CBOR).
- Plant Pro / 4.0 native Sun, Crescent Moon, Full Moon, and Half Moon scenes
  through the Home Assistant light effect control, using the four mesh indices
  present in FluvalConnect.
- Native Plant Pro / 4.0 Auto schedule writes using the fixture's sunrise,
  sunset, sleep, day-level, and night-level packet fields.
- Native Plant Pro / 4.0 Professional schedule writes using fixture-side
  point-schedule storage.
- Native Plant Pro / 4.0 Auto and Professional schedule readback from status
  keys 8-13 for diagnostics and future UI use.
- Plant Pro / 4.0 lamp profile with Red / Blue / Cool White / Warm White /
  Amber channel labels.
- Bluetooth discovery matchers for Plant Pro, Plant 4.0, Reef 4.0, and Reef
  Nano 4.0 names while preserving strict filtering against generic mesh devices.
- Tests covering Plant Pro / 4.0 packet shapes, mixed-service GATT resolution,
  discovery matching, effects, native schedule services, and HA schedule
  compatibility.

### Changed
- Fresh BLE connections now use one bounded `bleak-retry-connector` retry cycle
  instead of nesting three outer attempts around four internal attempts.
- Unexpected drops in always-connected mode trigger an immediate serialized
  reconnect instead of waiting for the next keep-alive interval.
- **Reachable** is true for a live GATT session or recent BLE activity and
  re-evaluates when `last_seen` ages out.
- **`active_time: 0`** keeps the GATT session connected permanently (connects on integration load).
- RSSI remains raw advertisement data, now includes its advertisement timestamp,
  and uses the Home Assistant measurement state class.
- Plant Pro Professional schedules are capped at the official, hardware-tested
  limit of 12 points; sunrise/sunset ramps are capped at 240 minutes.
- Native Professional service validation now preserves explicit Plant Pro
  `channel_1`-`channel_5` values instead of forcing them through RGBW aliases.
- Mesh / Plant Pro devices that expose both old `1000` and mesh `fff0` services
  now prefer the mesh `fff2` write and `fff1` notify characteristics.
- Home Assistant runtime data handling now preserves HA-managed schedule mode and
  locking across the newer config-entry runtime-data lifecycle.

### Fixed
- Removed the nonstandard `importlib.reload()` package self-reloader. Config
  entries now use Home Assistant's normal unload/setup lifecycle without mixing
  old and new Python class generations.
- Power-off no longer emits intermediate colour frames, preventing yellow/white
  mixes from visibly drifting red during shutdown while retaining the prior mix
  for the next power-on.
- Corrected the four Plant Pro mesh effect assignments, which had reused classic
  thunder/color-cycle names for the APK's sun and moon indices.
- Corrected classic Blue-family product IDs `0x0161`-`0x0164` to four channels.
- Existing duplicate Fluval device-registry rows are safely merged into the
  canonical Bluetooth-MAC device when no other integration references them.
- Downloadable diagnostics redact Bluetooth addresses, local names, raw service
  data, manufacturer data, and registry identifiers.
- Fixed an unawaited keep-alive coroutine warning in the test suite.

### Credits
- Plant Pro / 4.0 packet behavior was informed by FluvalConnect APK
  reverse-engineering.
- Plant Pro / 4.0 protocol design was cross-checked against
  [cryystyy/fluval-plant-pro-4-homeassistant](https://github.com/cryystyy/fluval-plant-pro-4-homeassistant).
- Hardware behavior and Home Assistant integration refinements by
  [@Wheemer](https://github.com/Wheemer).
- Original Fluval BLE integration and upstream project maintained by
  [@MrMooreUK](https://github.com/MrMooreUK) and prior contributors.

---

## [0.0.32] - 2026-07-21

### Added
- Real **light entity** with proper translation: Plant/Marine RGB ↔ Rose/Blue/CW/PW/WW (preview matches mix); AquaSky native RGBW.
- AquaSky 3.0/FACEBD discovery, diagnostics, and write support.
- Lovelace schedule, spectrum bar, and wavelength preview cards.
- HA-managed schedule storage, auto mode, and physical preview services.
- **Lamp type** option (Plant / AquaSky 2.0 / AquaSky 3.0 / auto) with Plant channel labels (Rose / Blue / Cold White / Pure White / Warm White).
- **Sync clock** button and automatic RTC sync on connect (old `0x0E`, FACEBD keys 101/102, mesh `0xCD`).
- Experimental **mesh** (`0000fff0`) support: `0xD1` + CBOR framing.

### Changed
- Per-channel number sliders disabled by default (advanced); use the Light entity as primary control.
- Channel entities use 0–100% consistently; old BLE wire scale (0–1000) is converted on decode.
- Prefer BLE write-without-response when available (ESPHome-compatible, Aquasky 2.0).
- Skip unchanged channel writes and throttle physical preview writes.
- Options changes reload the integration so ping/active-time take effect.

### Fixed
- Restored AquaSky colours remain synchronized with the Home Assistant icon after power-on.
- Options Configure gear 500 (`OptionsFlow` / missing `config_entry`) — #16.
- Plant devices mis-identified as AquaSky — #17.
- AquaSky 3.0 names no longer forced to 4 channels.
- Clock sync retries after BLE disconnect/reconnect (#8).
- Preview stop/restore behavior and FACEBD write target handling.
- Removed dead send-queue / legacy state-packet paths; public schedule helpers.

### Notes
- Clock sync, Aquasky 2.0 write behaviour, and mesh path still need hardware validation.
- For issues with other Fluval lights, please open a GitHub issue with the
  model, Home Assistant version, diagnostics output, and relevant logs.

---

## [0.0.6] — 2026-06-08

### Added
- **`docs/bug-triage.md`** — internal triage document for the two
  currently-open bugs (#6 Aquasky 2.0 no response, #8 schedule drift
  after power cut), with what we know, what we need from reporters,
  and the workarounds to use in the meantime.
- **`CONTRIBUTING.md`** — contributor guidance (dev branch workflow,
  test expectations, local linting, release process).
- **`AGENTS.md`** — guidance for AI coding agents working in this repo
  (test commands, branch rules, what _not_ to change).
- **`.pre-commit-config.yaml`** — `ruff format` + `ruff check` run on
  every commit.
- **`mypy` in CI** — soft, non-gating static type-checking job.
  Reports existing type errors in the job log so progress is visible
  as the integration gains type hints.
- **`pytest-cov` in CI** — coverage report uploaded to Codecov when
  the `CODECOV_TOKEN` secret is configured. The job degrades
  gracefully without it.
- **`pyproject.toml` config** — `[tool.mypy]` and `[tool.coverage.*]`
  sections, with a 33% coverage floor.

---

## [0.0.5] — 2026-06-06

### Added
- **Light entity** — a master dimmer (`light.fluval_xxxx_light`) that turns the fixture
  on/off and sets overall brightness, scaling all channels together while preserving
  their relative ratios. Works with HA light cards, voice assistants, and light
  automations. The per-channel number sliders remain for fine control.

### Fixed
- **BLE client stays reusable after idle** — previously the client called
  `_safe_disconnect()` when the active window expired, leaving the device unavailable
  on some HA Bluetooth proxy setups until the config entry was reloaded. The client
  now stays alive; a subsequent command wakes and reconnects it automatically.
- **Ping restart guard** — `ping()` now returns immediately if the client has been
  stopped, preventing an accidental restart after the integration is unloaded.
- **Entity sync after channel change** — `updates_component` handlers (which push
  state to HA) now fire on every channel change, not only when switching modes.
  Previously, sliders in manual mode wouldn't update each other or the new light entity.

### Changed
- **Protocol constants** — command bytes (`CMD_HEADER`, `CMD_MODE`, `CMD_SWITCH`,
  `CMD_BRIGHTNESS`, `CMD_STATUS`) are now named constants in `core/__init__.py`
  instead of inline magic numbers, making the BLE command set self-documenting.

---

## [0.0.4] — 2026-03-05

### Fixed
- **Entity availability on disconnect** — switch, channel sliders and mode selector now
  correctly become _unavailable_ when the Fluval light goes offline (previously they
  stayed shown as available with stale values, misleading users into thinking commands
  were being sent).

### Added
- **Options flow** — after setup, open _Settings → Devices & Services → Fluval Aquarium
  LED → Configure_ to tune the keep-alive interval (5–60 s, default 10 s) and the
  active-connection window (30–600 s, default 120 s) without removing and re-adding
  the integration.
- **Entity icons** — switch shows `mdi:led-strip-variant`, channel sliders show
  `mdi:brightness-6`, and the mode selector shows `mdi:tune`.
- **Brightness sliders** — channel number entities now render as sliders in the HA UI
  instead of plain text input boxes (`NumberMode.SLIDER`).
- **Better device titles** — when a light is found via Bluetooth auto-discovery the
  entry title now uses the BLE advertised name (e.g. "Fluval Plant 3.0") instead of
  the raw MAC address.
- **Model detection** — device card in HA shows "Aquasky 2.0" or "Aquarium LED 3.0"
  based on the channel count detected from the first state packet.
- **`loggers` in manifest.json** — users can now enable debug-level logging for the
  integration via HA's _Logger_ UI (`Settings → System → Logs → Set custom logger`
  and choose `custom_components.fluvalble`).
- **`PARALLEL_UPDATES = 0`** — declared on all entity platforms (correct for
  push-based `local_push` integrations).
- **`domains` in hacs.json** — HACS now correctly associates the integration with
  its domain.
- **CI/CD** — GitHub Actions workflows for automated linting, testing, and release
  asset publishing.

---

## [0.0.3] — 2025-12-01

### Added
- Bluetooth auto-discovery — Home Assistant prompts to add the light when it is seen
  via BLE advertisement (no manual MAC entry required).
- Entity translation strings — proper names and state labels for all entities.
- Keep-alive reconnect loop — connection is automatically re-established after drops.
- BLE packet reassembly — correctly handles split Fluval notifications.

### Fixed
- Short-packet crash on malformed BLE notifications.
- `channel_5` entity incorrectly shown for 4-channel Aquasky 2.0 lamps.

---

## [0.0.2] — 2025-10-15

### Added
- Manual Bluetooth MAC address entry in the config flow.
- Discovered-device picker — lists nearby Fluval lights filtered by service UUID.
- Mode select entity (manual / automatic / professional).
- Binary sensor for BLE connection status (diagnostic category).

### Fixed
- Smart mode switching — channel brightness commands now automatically switch the
  lamp to manual mode first so changes take effect immediately.

---

## [0.0.1] — 2025-09-01

### Added
- Initial release.
- BLE client using `bleak` and `bleak-retry-connector`.
- Switch entity for LED on/off.
- Number entities for up to 5 brightness channels.
- AES-style packet encryption matching the Fluval/Planted Tank BLE protocol.
