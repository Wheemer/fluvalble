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
