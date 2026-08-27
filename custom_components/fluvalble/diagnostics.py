"""Diagnostics support for the Fluval Aquarium LED integration.

HA downloads this from the device/integration page — not as a sensor entity.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry

REDACTED = "**REDACTED**"
REDACT_KEYS = {
    "address",
    "advertisement_name",
    "configured_mac",
    "mac",
    "manufacturer_data",
    "name",
    "path",
    "service_data",
    "title",
    "unique_id",
}


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
        return _redact_diagnostics(
            {
                "status": "not_ready",
                "entry": {
                    "title": entry.title,
                    "data": dict(entry.data),
                    "options": dict(entry.options),
                },
            }
        )

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
    return _redact_diagnostics(report)


def _redact_diagnostics(value: Any, *, key: str | None = None) -> Any:
    """Recursively redact device identifiers while retaining protocol evidence."""
    if key in REDACT_KEYS:
        return REDACTED
    if isinstance(value, dict):
        return {item_key: _redact_diagnostics(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, list):
        return [_redact_diagnostics(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_diagnostics(item) for item in value)
    return value
