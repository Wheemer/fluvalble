## Release: branch → main

**Version:** <!-- e.g. 0.1.0 -->

## Pre-merge checklist
- [ ] All PR checks pass
- [ ] `manifest.json` version matches the intended release version
- [ ] `CHANGELOG.md` has an entry for this version with today's date
- [ ] Manually tested on a real Fluval light (or all changes are non-functional)
- [ ] No debug/temporary code left in

## Post-merge steps
1. Tag the exact `main` merge commit: `git tag vX.Y.Z && git push origin vX.Y.Z`
2. Confirm the release workflow creates a GitHub Release with the versioned zip asset
3. Verify the zip contains `custom_components/fluvalble` and its manifest matches the tag
4. HACS users will see the update after HACS refreshes release metadata

## What's included
<!-- Paste the relevant CHANGELOG section here for quick review -->
