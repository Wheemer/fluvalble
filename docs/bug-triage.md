# Open Bug Triage

See [`issue-coverage.md`](issue-coverage.md) for the full matrix across forks.

| # | Title | Status in this fork |
|---|-------|---------------------|
| [#6](https://github.com/MrMooreUK/fluvalble/issues/6) | Aquasky 2.0: commands ignored | Mitigated — write-without-response preferred; needs HW confirm |
| [#8](https://github.com/MrMooreUK/fluvalble/issues/8) | RTC / schedule after power cut | Mitigated — sync on connect + button; re-sync after disconnect |
| [#16](https://github.com/MrMooreUK/fluvalble/issues/16) | Options Configure 500 | Fixed |
| [#17](https://github.com/MrMooreUK/fluvalble/issues/17) | Plant shown as Aquasky | Fixed |
| [#14](https://github.com/MrMooreUK/fluvalble/issues/14) | Spectrum graph discussion | Cards present; ongoing polish |

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
