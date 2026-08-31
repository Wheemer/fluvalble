<p align="center">
  <img src="images/logo.png" alt="Fluval BLE — Aquarium LED lighting for Home Assistant" width="760"/>
</p>

<p align="center">
  <a href="https://github.com/Wheemer/fluvalble/actions/workflows/ci.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/Wheemer/fluvalble/ci.yml?branch=main&style=for-the-badge&label=CI"></a>
  <a href="https://github.com/Wheemer/fluvalble/releases"><img alt="Release" src="https://img.shields.io/github/v/release/Wheemer/fluvalble?style=for-the-badge&label=release"></a>
  <a href="https://github.com/Wheemer/fluvalble/blob/main/LICENSE"><img alt="License" src="https://img.shields.io/badge/license-Apache%202.0-blue?style=for-the-badge"></a>
</p>

<p align="center">
  <strong>Premium local control for Fluval aquarium LED lights in Home Assistant.</strong><br/>
  No cloud. No vendor app dependency. Just Bluetooth, your tank, and automations that behave.
</p>

---

## Why Fluval BLE?

Fluval BLE turns compatible Fluval aquarium lights into first-class Home Assistant devices. Control colour and brightness through a normal `light` entity, plus mode and clock sync, while keeping every command local over Bluetooth Low Energy.

---

## Features

| Feature | Description |
|--------|-------------|
| **Local-first control** | Talk directly to the LED fixture over BLE; no internet, cloud account, or app login required. |
| **Light** | Real Home Assistant `light` entity with on/off, brightness, and colour. **Plant/Marine**: RGB picker translated to/from Rose·Blue·CW·PW·WW. **Plant Pro / 4.0**: RGB picker translated to/from Red·Blue·Cool White·Warm White·Amber. **AquaSky**: native RGBW. |
| **Mode** | Select **Manual**, **Automatic**, or **Professional**. Changing colour or brightness switches to Manual when needed. |
| **Native effects** | Classic controllers expose 11 FluvalSmart effect IDs mapped from FluvalConnect; the command path is hardware-tested on product `0x0103`, but every visual effect has not been validated on every classic model. Plant Pro / 4.0 exposes the four Sun/Moon scene indices found in FluvalConnect and cross-checked against the credited hardware project. Effects are protocol-family specific. |
| **Native schedules** | Classic, AquaSky 3.0/FACEBD, and Plant Pro/4.0 controllers can store Auto sunrise/sunset and Professional schedules in the fixture. The dashboard's **Fixture native** mode uploads a 2-12 point curve once instead of writing channels every minute. |
| **Clock sync** | Syncs the lamp RTC on connect (and via a **Sync clock** button). |
| **Reachable** | Shows whether the lamp was seen recently over BLE (not the same as an idle GATT session). |
| **Auto-discovery** | Home Assistant detects nearby Fluval lights and prompts you to add them. |

Each device exposes one light as the primary control, plus mode, clock sync, and diagnostic sensors.

---

## Supported devices

Support depends on the controller protocol, not only the retail product name.

| Protocol/profile | Known families | Control status | Native schedule/effect status |
|---|---|---|---|
| Classic encrypted `1000/1001/1002` | AquaSky 2.0, Plant/Marine/Reef 3.0-era and first-generation BLE controllers | Power, mode, four/five channels, clock and state readback. Product `0x0103` is hardware-verified as four-channel RGBW. | APK-mapped dynamic IDs 1-11 and native Auto/Pro schedules are exposed. Regular control is hardware-verified on product `0x0103`; native schedule behavior still needs broader fixture validation. |
| AquaSky 3.0 `FACEBD` CBOR | AquaSky 3.0 | Power, mode, four RGBW channels, clock and state readback. | Native Auto/Pro write and readback use FluvalConnect CBOR keys 114-122. This path is APK-derived and needs AquaSky 3.0 hardware validation before it is considered verified. |
| Plant Pro / 4.0 `FFF0/FFF1/FFF2` CBOR | Plant Pro and protocol-compatible Plant/Reef/Nano 4.0 controllers | Power, mode, five channels and state readback. Plant Pro is hardware-validated by the credited reference project; other 4.0 variants still need testers. | Native Auto/Pro write and readback are implemented. Four FluvalConnect Sun/Moon scene indices are exposed; keys 14-22 are not fully decoded. |

The support boundary follows FluvalConnect's own product table and its OLD,
WIFI/FACEBD, and MESH controller routing. The integration does not speculate
about products or protocols that are absent from the manufacturer APK.

---

## Requirements

- **Home Assistant 2025.8.0** or later with a working **Bluetooth** stack (built-in or add-on Bluetooth adapter). The integration uses Home Assistant's `OptionsFlowWithReload` lifecycle helper introduced in 2025.8.
- The Fluval light must be in range and powered on so it advertises over BLE.
- Your HA host (or the machine running the Bluetooth proxy) must be able to see the light in BLE scans.

---

## Installation

### Option A: HACS (recommended)

[![Open your Home Assistant instance and open this repository inside HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Wheemer&repository=fluvalble&category=integration)

1. Ensure [HACS](https://hacs.xyz/) is installed.
2. In HACS: **Integrations** → **⋮** → **Custom repositories**.
3. Add: `https://github.com/Wheemer/fluvalble`
   Type: **Integration**.
4. Search for **Fluval Aquarium LED** or **Fluval BLE**, then install.
5. Restart Home Assistant (needed once so HA loads the custom component modules).

### Option B: Manual

1. Download or clone this repo.
2. Copy the `custom_components/fluvalble` folder into your Home Assistant `custom_components` directory so you have:
   ```text
   config/
   └── custom_components/
       └── fluvalble/
           ├── __init__.py
           ├── manifest.json
           ├── config_flow.py
           ├── ...
   ```
3. Restart Home Assistant.

---

## Configuration

### Automatic (recommended)

When Home Assistant detects a Fluval light advertising over BLE, it will show a notification in **Settings → Devices & services** prompting you to set it up. Click **Configure**, confirm the device name, and the integration is ready.

### Manual

1. Go to **Settings** → **Devices & services** → **Add integration**.
2. Search for **Fluval Aquarium LED** (or **Fluval BLE**).
3. **Select your light** from the dropdown. The list shows only devices that look like Fluval lights (by Bluetooth service or name), so your aquarium light is easy to find. Ensure the light is **on** and in range before adding.
   - If your light appears: choose it and submit. The integration creates one device with a primary light entity, mode select, clock-sync button, Reachable status, and diagnostic sensors. Advanced per-channel entities from older releases are cleaned up.
   - If it's not in the list: choose **"My device isn't in the list — enter MAC address manually"**, then enter the MAC (e.g. `AA:BB:CC:DD:EE:FF`). You can find the MAC in your phone's Bluetooth settings or the Fluval app.
4. After setup, the light and supporting entities appear on the device. If you only see the integration card (for example, "Update") and no light entity, see [Troubleshooting](#troubleshooting) below.

No cloud account or app login is needed; the integration talks directly to the light over BLE.

---

## Connection options

Open **Settings → Devices & services → Fluval Aquarium LED → Configure**. Saving
these options unloads and reloads only the config entry; it does not restart Home
Assistant Core.

| Option | Range/default | Purpose |
|---|---|---|
| **Lamp type** | Auto-detect (default), Plant/Marine 5-channel, Plant Pro/4.0, AquaSky 2.0, AquaSky 3.0/FACEBD | Override detection when the colour model or channel profile is wrong. |
| **BLE command encoding** | FluvalConnect random-key (default), fixed XOR `0x0E`, zero-key envelope | Keep the recommended FluvalConnect encoding unless protocol evidence shows that a legacy controller needs another envelope. |
| **Keep-alive interval** | 5-60 seconds; default 10 | Controls how often an open GATT session is read. |
| **Active connection window** | 0-600 seconds; default 0 | `0` keeps GATT connected; a positive value disconnects after that many idle seconds and reconnects on demand. Use a finite window when FluvalConnect or a Fluval Gateway must share a Plant Pro/4.0 fixture. |

---

## Integration actions

The integration registers six Home Assistant actions. With one configured Fluval
light, the target can be omitted. With multiple lights, provide either `entry_id`
or `mac`. The Home Assistant action editor displays the full field schema from
[`services.yaml`](custom_components/fluvalble/services.yaml).

| Action | Purpose |
|---|---|
| `fluvalble.set_channels` | Set one or more physical channel positions, with an optional ramp. The legacy `red`/`green`/`blue`/`white` field names map to channels 1-4; the light entity performs the configured profile's colour translation. |
| `fluvalble.preview_schedule` | Compress and physically preview an HA-managed 24-hour channel schedule. |
| `fluvalble.stop_preview` | Stop an active physical preview and restore the appropriate schedule state. |
| `fluvalble.save_schedule` | Save a schedule in Manual or Fixture native mode. Fixture native uploads 2-12 points once as a Professional curve. |
| `fluvalble.set_native_auto_schedule` | Write protocol-native sunrise, sunset, sleep, day-level, and night-level values into a classic, FACEBD, or Plant Pro fixture. |
| `fluvalble.set_native_pro_schedule` | Write 2-12 protocol-native Professional points into a classic, FACEBD, or Plant Pro fixture. |

---

## Lovelace dashboard cards

Optional dashboard cards are available for AquaSky 3.0 schedule editing,
spectrum bar preview, and wavelength preview. See
[`docs/lovelace-cards.md`](docs/lovelace-cards.md) for setup instructions,
example YAML, usage notes, and preview safety guidance. Choose **Fixture native**
to upload a 2-12 point curve to the controller's onboard scheduler.

---

## Entities

After setup you'll see one device with entities like:

| Entity | Display name | Purpose |
|--------|-------------|---------|
| **Light** | Light | Primary control — on/off, colour, brightness. |
| **Select** | Mode | Manual / Automatic / Professional. |
| **Button** | Sync clock | Re-sync the lamp RTC (also runs automatically on connect). |
| **Binary sensor** | Reachable | Lamp seen recently over BLE. |
| **Sensors** | Signal / Last seen | Raw advertisement RSSI and the last successful BLE activity time. RSSI includes the time of its last advertisement as an attribute. |

Redacted downloadable diagnostics are available from the Home Assistant device page. They retain protocol/profile information while removing Bluetooth addresses, advertised names, manufacturer payloads and registry identifiers.

Home Assistant creates entity IDs from the device and entity names, not directly
from the Bluetooth address. The examples below use placeholders such as
`light.your_fluval_light`; find the actual IDs under **Settings → Devices &
services → Fluval Aquarium LED → entities**.

---

## Example automations

**Turn the tank light on at sunrise and off at sunset**

```yaml
- id: fluval_morning
  alias: "Tank light on at sunrise"
  trigger:
    - platform: sun
      event: sunrise
  action:
    - service: light.turn_on
      target:
        entity_id: light.your_fluval_light

- id: fluval_evening
  alias: "Tank light off at sunset"
  trigger:
    - platform: sun
      event: sunset
  action:
    - service: light.turn_off
      target:
        entity_id: light.your_fluval_light
```

**Dim the light when you're away**

```yaml
- id: fluval_away_dim
  alias: "Dim tank light when away"
  trigger:
    - platform: state
      entity_id:
        - person.you
      to: "not_home"
  action:
    - service: light.turn_on
      target:
        entity_id: light.your_fluval_light
      data:
        brightness_pct: 20
```

**Notify if the light is no longer reachable**

```yaml
- id: fluval_unreachable
  alias: "Tank light unreachable"
  trigger:
    - platform: state
      entity_id: binary_sensor.your_fluval_reachable
      to: "off"
  action:
    - service: notify.mobile
      data:
        message: "Fluval tank light has not been seen over Bluetooth."
```

Replace entity IDs with yours, and `person.you` / `notify.mobile` with your actual entities.

---

## Native fixture schedules

Compatible classic, FACEBD, and Plant Pro / 4.0 fixtures can store schedules
directly in the light. In the schedule card, **Fixture native** uploads the
current curve as a Professional schedule and activates it; the fixture then runs
from its own clock without recurring Home Assistant channel writes. The native
services below are also available for automations and scripts.

### Native Auto schedule

```yaml
service: fluvalble.set_native_auto_schedule
data:
  entry_id: your_config_entry_id
  sunrise:
    hour: 8
    minute: 0
    ramp: 60
  sunset:
    hour: 21
    minute: 0
    ramp: 60
  sleep:
    hour: 22
    minute: 30
  day_levels:
    channel_1: 80
    channel_2: 70
    channel_3: 60
    channel_4: 50
    channel_5: 40
  night_levels:
    channel_1: 0
    channel_2: 10
    channel_3: 0
    channel_4: 0
    channel_5: 0
  activate: true
```

### Native Professional schedule

```yaml
service: fluvalble.set_native_pro_schedule
data:
  entry_id: your_config_entry_id
  points:
    - time: "08:00"
      channel_1: 0
      channel_2: 0
      channel_3: 0
      channel_4: 0
      channel_5: 0
    - time: "12:30"
      channel_1: 60
      channel_2: 60
      channel_3: 60
      channel_4: 60
      channel_5: 60
  activate: true
```

For Plant Pro / 4.0, the channels are Red, Blue, Cool White, Warm White, and
Amber. AquaSky uses channels 1-4 as RGBW and ignores channel 5. You can target
either `entry_id` or `mac` when more than one Fluval light is configured.

---

## Troubleshooting

| Issue | What to try |
|-------|---------------------|
| **Integration not found** | Restart HA after installation. Ensure the `fluvalble` folder is directly under `custom_components`. |
| **Only see "Update", no light or device entities** | The device wasn't in the Bluetooth cache when the integration loaded. Remove the integration config entry, ensure the fixture is **on** and in range, then add the integration again and select the light. Restart Home Assistant only when newly installed Python source must be loaded. |
| **Cannot connect / no entities** | Confirm the light is on and in BLE range. Check that HA has Bluetooth enabled and that the adapter can see other BLE devices. Verify the MAC address (no typos, correct format AA:BB:CC:DD:EE:FF). |
| **My light isn't in the dropdown** | Ensure the light is on and advertising. Use "My device isn't in the list" and enter the MAC manually (from phone Bluetooth settings or the Fluval app). |
| **Lamp connected but doesn't respond to actions** | Try the Fluval app first to confirm the light works. If the app works but HA doesn't, open an issue with your model and HA logs. |
| **Light entity doesn't turn the fixture on/off** | Confirm the configured lamp profile and that the official app can control the fixture. Close the app so it releases BLE, then reload the Fluval BLE config entry and retry. Plant Pro / 4.0 permits only one Bluetooth central. |
| **Entities show "unavailable"** | The light may be out of range, off, or the BLE connection dropped. Move the light or HA adapter closer; check Reachable and RSSI. |
| **Wrong model or channel count** | Open **Configure** on the integration and set **Lamp type** (Plant 5ch / Plant Pro 4.0 / AquaSky 2.0 / AquaSky 3.0). Plant names are detected from the BLE advertisement; FACEBD/mesh and status packets refine channel count. |
| **Schedule wrong after power cut** | Use the **Sync clock** button (also runs automatically on connect), then upload the native schedule again if the fixture did not retain it. |
| **Channels or mode don't update** | Some features (e.g. mode change) may require the device to send state back; if the firmware doesn't report mode, the dropdown may not reflect external changes. |
| **Colour or brightness changes don't reach the fixture** | See [Colour and brightness troubleshooting](#colour-and-brightness-troubleshooting) below. |

### Colour and brightness troubleshooting

If power or mode works but colour and brightness changes have no effect:

1. **Enable debug logging** to see what's being sent. Add to `configuration.yaml`:
   ```yaml
   logger:
     default: info
     logs:
       custom_components.fluvalble: debug
   ```
   Restart Home Assistant after changing `configuration.yaml`, change the light
   colour or brightness, then check **Settings → System → Logs** (or the full log
   file). Look for lines like:
   ```text
   Writing Fluval packet to XX:XX:XX:XX:XX:XX response=False chunk=1/1 raw=6804... encrypted=54...
   ```
   - `raw` = command before encryption (e.g. `68 04` = brightness command, then channel bytes as 16-bit big-endian values)
   - `encrypted` = what goes over BLE

2. **Verify the Fluval app works** — If the app can change brightness, the hardware is fine; the protocol may differ for your model.

3. **Confirm you're in Manual mode** — The integration automatically switches to Manual when you change colour or brightness, but if that mode command is dropped (for example, because the connection is unstable), the fixture may ignore the following command. Select Manual first, then retry from the light entity.

4. **Check your model** — Different Fluval models (Plant 3.0, Reef 3.0, AquaSky 2.0, etc.) use different command formats. Open an issue with your model name and a log snippet showing the `raw` and `encrypted` bytes for the failed light command.

5. **Packet capture (advanced)** — Use an ESP32 or nRF Sniffer to capture BLE traffic while changing brightness in the Fluval app, then compare with what this integration sends.

If you have a different Fluval BLE model and the light or other controls don't behave as expected, open an issue with your model name and (if possible) a note on what works in the official app.

---

## How it works

The integration uses Home Assistant's Bluetooth support to connect directly to the controller. Classic FluvalSmart controllers use checksummed, encrypted frames. AquaSky 3.0/FACEBD and Plant Pro/4.0 use unencrypted CBOR command maps over their respective GATT characteristics. No light-control data is sent to Fluval or any third party.

**BLE connection lifecycle:**
- On load the integration checks Home Assistant's Bluetooth cache. With `active_time: 0` it opens the persistent session immediately; finite sessions connect on demand.
- A keep-alive loop reads at the configured interval while a session is open.
- Unexpected persistent-session drops schedule an immediate serialized reconnect. Fresh connections use one bounded three-attempt `bleak-retry-connector` cycle rather than nested retry loops.
- The default remains `active_time: 0` for low command latency. Plant Pro / 4.0 allows only one Bluetooth central, so permanent mode blocks FluvalConnect and the Fluval Gateway while Home Assistant is connected. Select a finite window under **Configure** when app/gateway coexistence matters.
- RSSI comes only from advertisements. It can remain unchanged while a controller is connected and no longer advertising; this does not mean the value is fabricated.

Home Assistant config-entry reloads unload entities, cancel callbacks/tasks, close BLE, and set the entry up again without restarting Core. Installing changed Python source is different: Home Assistant must load those modules once after installation, so a Core restart is required for a newly installed code version. The integration does not attempt unsafe in-process `importlib.reload()` hot swapping.

---

## Credits & license

- Original integration and upstream project by [@MrMooreUK](https://github.com/MrMooreUK) and contributors, building on earlier Fluval BLE work including [@mrzottel](https://github.com/mrzottel).
- Plant Pro / 4.0 transport, command and native-schedule behavior was independently integrated from FluvalConnect APK evidence and cross-checked against the hardware-validated MIT-licensed [cryystyy/fluval-plant-pro-4-homeassistant](https://github.com/cryystyy/fluval-plant-pro-4-homeassistant) project.
- Historical FluvalSmart Android and controller-firmware repositories by [@kw217](https://github.com/kw217) were used as protocol documentation only; their source code was not copied because those repositories do not state a software license.
- Community reverse‑engineering of the Fluval BLE protocol, including Planted Tank Forum and ESPHome/fluval projects.
- Hardware testing and Home Assistant-focused refinements by [@Wheemer](https://github.com/Wheemer).
- Licensed under the **Apache License 2.0**. See [LICENSE](LICENSE) in this repo.

---

**Enjoy your smarter aquarium lighting.**

*This README is the integration's main documentation and is kept up to date with each release in this repo.*
