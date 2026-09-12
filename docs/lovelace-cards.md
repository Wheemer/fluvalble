# Schedule programming

Use Fluval Connect to edit and save schedules on the fixture. The experimental
Fluval dashboard planner and related cards are retired and are no longer loaded
by this integration. Remove their old instances from your dashboards.

Home Assistant retains the light entity, physical channel sliders, supported
effects, mode selection and schedule readback. Select Auto or Professional to
use the corresponding schedule already saved on the fixture.

Removing the cards does not clear or rewrite any fixture schedule. Schedule
editing, draft storage, and preview actions have also been removed. Delete old
Fluval planner resources and card instances from your dashboard, and remove
retired schedule actions from automations. No compatibility card or replacement
Home Assistant scheduler is installed. Schedule readback remains available.

Connections release after the configured idle timeout (30–600 seconds, default
120). Existing unlimited settings migrate to 120 seconds. Allow that timeout
to elapse without HA commands before connecting from Fluval Connect.

## Why this changed

Fluval Connect already provides the fixture-specific Auto, Professional, and
weather editors. The separate Home Assistant cards duplicated that workflow
and made it harder to understand. Home Assistant now handles everyday control;
Fluval Connect handles programming the schedules stored on the light.

## Updating an existing installation

1. Remove old Fluval custom cards from your dashboards and their
   `/fluvalble/fluvalble-schedule-card.js` resource, if you added it manually.
   No replacement custom card or resource is required.
2. Remove these retired actions from scripts and automations:
   `fluvalble.save_schedule`, `fluvalble.set_native_auto_schedule`,
   `fluvalble.set_native_pro_schedule`, `fluvalble.set_native_effect_schedule`,
   `fluvalble.preview_schedule`, `fluvalble.preview_native_schedule`, and
   `fluvalble.stop_preview`.
3. To edit a hardware schedule, let Home Assistant's idle connection expire,
   open Fluval Connect, and save the schedule there. Disconnect the app when
   finished so Home Assistant can reconnect.
4. Select Automatic or Professional in Home Assistant to use the stored mode.
   Ordinary HA light automations and the remaining `set_channels`,
   `recall_manual_preset`, and `save_manual_preset` actions are still supported.

Existing local drafts are not uploaded or converted automatically. Use the
schedule saved on the fixture or recreate an unsaved draft in Fluval Connect.
Updating does not delete the integration entry or erase fixture memory.
