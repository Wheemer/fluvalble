# Upstream issue coverage (Wheemer fork)

Open issues surveyed across Fluvalble forks (2026-07-19). Other public forks
have issues disabled; actionable trackers are **MrMooreUK/fluvalble** and
**mrzottel/fluvalble**.

| Source | # | Title | Status in this fork |
|--------|---|-------|---------------------|
| MrMooreUK | [#6](https://github.com/MrMooreUK/fluvalble/issues/6) | Aquasky 2.0 connected, no command response | **Mitigated** — prefer write-without-response; debug logs include raw + encrypted + `response=` |
| MrMooreUK | [#8](https://github.com/MrMooreUK/fluvalble/issues/8) | Schedule wrong after power cut (RTC) | **Mitigated** — clock sync on connect + Sync clock button; flag clears on disconnect so reconnect re-syncs |
| MrMooreUK | [#14](https://github.com/MrMooreUK/fluvalble/issues/14) | Spectrum / graph discussion | **Present** — schedule / spectrum / wavelength Lovelace cards (merged upstream #15); UX polish ongoing |
| MrMooreUK | [#16](https://github.com/MrMooreUK/fluvalble/issues/16) | Configure gear 500 | **Fixed** — modern `OptionsFlow` + lamp profile; options reload entry |
| MrMooreUK | [#17](https://github.com/MrMooreUK/fluvalble/issues/17) | Plant shown as Aquasky | **Fixed** — Plant/AquaSky 2.0/3.0 name detection + lamp-type override |
| mrzottel | [#2](https://github.com/mrzottel/fluvalble/issues/2) | Connected but no actions | Same root class as #6 — write/framing path mitigated here |
| mrzottel | [#1](https://github.com/mrzottel/fluvalble/issues/1) | Skeleton / job list | Superseded by maintained forks |

## Hardware still needed

- Confirm #6 / mrzottel#2 on a real Aquasky 2.0 (ESPHome proxy)
- Confirm #8 after a real power cut (Automatic mode stays aligned)
- Plant RGB translation preview vs tank appearance (tune `PLANT_CHANNEL_RGB` if needed)
