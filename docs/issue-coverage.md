# Upstream issue coverage (Wheemer fork)

Open issues surveyed across Fluvalble forks (updated 2026-08-27). Other public forks
have issues disabled; actionable trackers are **MrMooreUK/fluvalble** and
**mrzottel/fluvalble**.

| Source | # | Title | Status in this fork |
|--------|---|-------|---------------------|
| MrMooreUK | [#6](https://github.com/MrMooreUK/fluvalble/issues/6) | Aquasky 2.0 connected, no command response | **Fixed for hardware-tested product `0x0103` through an ESPHome proxy** — write target/response handling and classic framing corrected; other variants still need reports |
| MrMooreUK | [#8](https://github.com/MrMooreUK/fluvalble/issues/8) | Schedule wrong after power cut (RTC) | **Mitigated** — clock sync on connect + Sync clock button; flag clears on disconnect so reconnect re-syncs |
| MrMooreUK | [#14](https://github.com/MrMooreUK/fluvalble/issues/14) | Spectrum / graph discussion | **Present** — schedule / spectrum / wavelength Lovelace cards (merged upstream #15); UX polish ongoing |
| MrMooreUK | [#16](https://github.com/MrMooreUK/fluvalble/issues/16) | Configure gear 500 | **Fixed** — modern `OptionsFlow` + lamp profile; options reload entry |
| MrMooreUK | [#17](https://github.com/MrMooreUK/fluvalble/issues/17) | Plant shown as Aquasky | **Fixed** — Plant/AquaSky 2.0/3.0 name detection + lamp-type override |
| mrzottel | [#2](https://github.com/mrzottel/fluvalble/issues/2) | Connected but no actions | Same root class as #6 — write/framing path fixed for the validated AquaSky hardware |
| mrzottel | [#1](https://github.com/mrzottel/fluvalble/issues/1) | Skeleton / job list | Superseded by maintained forks |

## Hardware still needed

- Validate the #6 / mrzottel#2 fix on additional AquaSky 2.0 product variants
- Confirm #8 after a real power cut (Automatic mode stays aligned)
- Plant RGB translation preview vs tank appearance (tune `PLANT_CHANNEL_RGB` if needed)
