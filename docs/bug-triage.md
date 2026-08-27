# Open Bug Triage

See [`issue-coverage.md`](issue-coverage.md) for the full matrix across forks.

| # | Title | Status in this fork |
|---|-------|---------------------|
| [#6](https://github.com/MrMooreUK/fluvalble/issues/6) | Aquasky 2.0: commands ignored | Fixed and hardware-validated for product `0x0103` through an ESPHome Bluetooth proxy; other variants still need reports |
| [#8](https://github.com/MrMooreUK/fluvalble/issues/8) | RTC / schedule after power cut | Mitigated — sync on connect + button; re-sync after disconnect |
| [#16](https://github.com/MrMooreUK/fluvalble/issues/16) | Options Configure 500 | Fixed |
| [#17](https://github.com/MrMooreUK/fluvalble/issues/17) | Plant shown as Aquasky | Fixed |
| [#14](https://github.com/MrMooreUK/fluvalble/issues/14) | Spectrum graph discussion | Cards present; ongoing polish |

## Hardware-gated protocol work

- Plant Pro / 4.0 core control and native schedule keys 1-13 are implemented.
  Status keys 14-22 remain undecoded; do not infer additional effects from APK
  images alone.
- AquaSky 3.0/FACEBD fixture-native schedules and effects still need captures.
- Siena 2.0, Roma/Shaker 2.0, V&V and Reef Pro require advertisement, GATT and
  command captures before discovery or support claims are added.
- Classic Sunrise (`0x0A`, effect 12), Find (`0x0F`), native Auto (`0x07`),
  native Pro (`0x10`) and scheduled effects (`0x11`) are documented by old
  unlicensed source, but remain intentionally unexposed until captured or
  hardware-verified.

## Reporting a new bug

1. Confirm the integration version.
2. Enable debug logging:
   ```yaml
   logger:
     default: info
     logs:
       custom_components.fluvalble: debug
   ```
3. Capture the log around a failing command (`Writing Fluval packet to … response=…`).
4. Note lamp model and Bluetooth adapter.
