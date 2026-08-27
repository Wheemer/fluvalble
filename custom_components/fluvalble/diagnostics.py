"""Diagnostics support for the Fluval Aquarium LED integration.

HA downloads this from the device/integration page — not as a sensor entity.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    return await _build_report(entry)


async def async_get_device_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
    device: DeviceEntry,
) -> dict[str, Any]:
    """Return diagnostics for a specific device."""
    del device
    return await _build_report(entry)


async def _build_report(entry: ConfigEntry) -> dict[str, Any]:
    """Collect live diagnostics from the runtime Device when available."""
    runtime = entry.runtime_data
    fluval = getattr(runtime, "device", None)
    if fluval is None:
        return {
            "status": "not_ready",
            "entry": {
                "title": entry.title,
                "data": dict(entry.data),
                "options": dict(entry.options),
            },
        }

    report = await fluval.async_collect_diagnostics()
    report["entry"] = {
        "title": entry.title,
        "unique_id": entry.unique_id,
        "data": dict(entry.data),
        "options": dict(entry.options),
    }
    report["model"] = fluval.model_name
    report["lamp_profile"] = fluval.lamp_profile
    report["values"] = dict(fluval.values)
    return report
