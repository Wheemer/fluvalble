"""The Fluval Aquarium LED integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import importlib
import inspect
import logging
from datetime import timedelta
from pathlib import Path
import re
import sys
from time import monotonic
from typing import TypeAlias

import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC, EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import CoreState, HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store

from .core import (
    CONF_ACTIVE_TIME,
    CONF_PING_INTERVAL,
    DEFAULT_ACTIVE_TIME,
    DEFAULT_PING_INTERVAL,
    DOMAIN,
)
from .core.device import Device

try:
    from homeassistant.config_entries import ConfigEntryState
except ImportError:  # pragma: no cover - stubbed test environments
    ConfigEntryState = None  # type: ignore[misc, assignment]

_LOGGER = logging.getLogger(__name__)


@dataclass
class FluvalRuntimeData:
    """Runtime state for one Fluval config entry (stored on entry.runtime_data)."""

    device: Device


try:
    FluvalConfigEntry: TypeAlias = ConfigEntry[FluvalRuntimeData]
except TypeError:  # pragma: no cover - stubbed test ConfigEntry isn't generic
    FluvalConfigEntry: TypeAlias = ConfigEntry  # type: ignore[misc,assignment]

DISCOVERY_LOG_INTERVAL = 5
SERVICE_SET_CHANNELS = "set_channels"
SERVICE_PREVIEW_SCHEDULE = "preview_schedule"
SERVICE_STOP_PREVIEW = "stop_preview"
SERVICE_SAVE_SCHEDULE = "save_schedule"
SERVICES_REGISTERED = "services_registered"
STATIC_REGISTERED = "static_registered"
WEBSOCKET_REGISTERED = "websocket_registered"
STATIC_URL = "/fluvalble"
STORAGE_KEY = "fluvalble_schedules"
STORAGE_VERSION = 1
STARTUP_SCHEDULE_RETRY_SECONDS = 5
STARTUP_SCHEDULE_RETRY_COUNT = 12
MAX_SCHEDULE_POINTS = 96
SCHEDULE_CHANNELS = ("red", "green", "blue", "white", "channel_5")
SCHEDULE_POINT_FIELDS = {"time", *SCHEDULE_CHANNELS}
LEGACY_ENTITY_UNIQUE_ID_SUFFIXES = ("_diagnostics", "_refresh_diagnostics")


def _validate_schedule_points(points: object) -> list[dict]:
    """Validate untrusted schedule data before storing it or driving BLE writes."""
    if not isinstance(points, list) or not 2 <= len(points) <= MAX_SCHEDULE_POINTS:
        raise vol.Invalid(f"Schedule must contain 2 to {MAX_SCHEDULE_POINTS} points")

    validated = []
    for point in points:
        if not isinstance(point, dict) or set(point) - SCHEDULE_POINT_FIELDS:
            raise vol.Invalid("Each schedule point must contain only supported fields")
        time_value = point.get("time")
        if not isinstance(time_value, str) or re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", time_value) is None:
            raise vol.Invalid("Schedule times must use HH:MM in the 24-hour range")

        validated_point: dict[str, str | int] = {"time": time_value}
        for channel in SCHEDULE_CHANNELS:
            value = point.get(channel, 0)
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
                raise vol.Invalid(f"{channel} must be an integer from 0 to 100")
            validated_point[channel] = value
        validated.append(validated_point)

    return validated


CHANNEL_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): str,
        vol.Optional("mac"): str,
        vol.Optional("red"): vol.All(int, vol.Range(min=0, max=100)),
        vol.Optional("green"): vol.All(int, vol.Range(min=0, max=100)),
        vol.Optional("blue"): vol.All(int, vol.Range(min=0, max=100)),
        vol.Optional("white"): vol.All(int, vol.Range(min=0, max=100)),
        vol.Optional("channel_5"): vol.All(int, vol.Range(min=0, max=100)),
        vol.Optional("transition", default=0): vol.All(int, vol.Range(min=0, max=86400)),
        vol.Optional("step_seconds", default=30): vol.All(int, vol.Range(min=1, max=3600)),
    }
)

PREVIEW_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): str,
        vol.Optional("mac"): str,
        vol.Required("points"): _validate_schedule_points,
        vol.Optional("duration", default=60): vol.All(int, vol.Range(min=1, max=3600)),
        vol.Optional("step_seconds", default=2): vol.All(int, vol.Range(min=1, max=300)),
    }
)

STOP_PREVIEW_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): str,
        vol.Optional("mac"): str,
    }
)

SCHEDULE_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): str,
        vol.Optional("mac"): str,
        vol.Required("points"): _validate_schedule_points,
        vol.Optional("mode"): vol.In(["manual", "auto", "professional"]),
    }
)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.LIGHT,
]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up domain-wide Fluval actions once per Home Assistant start."""
    del config
    hass.data.setdefault(DOMAIN, {})
    _register_services(hass)
    return True


def _manifest_version() -> str:
    """Return the installed manifest version for reload fingerprints."""
    try:
        import json

        manifest = json.loads((Path(__file__).parent / "manifest.json").read_text(encoding="utf-8"))
        return str(manifest.get("version", "unknown"))
    except Exception:  # noqa: BLE001
        return "unknown"


def _reload_package_modules() -> None:
    """Reload loaded Fluval modules so config-entry reload picks up disk changes."""
    package = __name__
    prefix = f"{package}."
    module_names = [
        name
        for name, module in sys.modules.items()
        if (name == package or name.startswith(prefix)) and getattr(module, "__spec__", None) is not None
    ]
    module_names.sort(key=lambda name: (name.count("."), name), reverse=True)

    reloaded = 0
    for name in module_names:
        module = sys.modules.get(name)
        if module is None:
            continue
        importlib.reload(module)
        reloaded += 1

    _LOGGER.info(
        "Fluval package reloaded from disk (version=%s modules=%s)",
        _manifest_version(),
        reloaded,
    )


async def async_setup_entry(hass: HomeAssistant, entry: FluvalConfigEntry) -> bool:
    """Set up Fluval Aquarium LED from a config entry.

    Create typed runtime data, forward platforms, and register unload callbacks.
    """
    _reload_package_modules()
    from .core.device import Device as RuntimeDevice  # noqa: PLC0415

    hass.data.setdefault(DOMAIN, {})
    await _register_static_paths(hass)
    _register_websocket(hass)

    mac_raw = entry.data.get(CONF_MAC)
    mac = mac_raw.strip().upper() if mac_raw else None
    if not mac:
        _LOGGER.error("Config entry %s has no MAC address", entry.entry_id)
        return False

    # Discovery uses lowercase format_mac unique_ids. Migrate legacy uppercase
    # unique_ids so the same lamp is not rediscovered as a new device.
    desired_unique_id = format_mac(mac)
    if entry.unique_id != desired_unique_id:
        hass.config_entries.async_update_entry(entry, unique_id=desired_unique_id)

    _migrate_legacy_registry_entries(hass, entry, mac)

    ping_interval = entry.options.get(CONF_PING_INTERVAL, DEFAULT_PING_INTERVAL)
    active_time = entry.options.get(CONF_ACTIVE_TIME, DEFAULT_ACTIVE_TIME)
    config_data = {**dict(entry.data), **dict(entry.options)}

    _LOGGER.info("Fluval setup entry %s mac=%s", entry.entry_id, mac)
    device = RuntimeDevice(
        entry.title,
        hass=hass,
        config_data=config_data,
        ping_interval=ping_interval,
        active_time=active_time,
    )

    # Prefer BLE cache so the first advertisement is applied before platforms load.
    try:
        get_last = getattr(bluetooth, "async_last_service_info", None)
        if get_last:
            service_info = get_last(hass, mac, connectable=True)
            if service_info:
                device.update_ble(service_info.device, service_info.advertisement)
    except Exception:  # noqa: BLE001
        _LOGGER.debug("BLE cache lookup failed for %s", mac, exc_info=True)

    runtime = FluvalRuntimeData(device=device)
    entry.runtime_data = runtime

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    last_discovery_log = 0.0

    @callback
    def update_ble(
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        nonlocal last_discovery_log
        now = monotonic()
        if now - last_discovery_log >= DISCOVERY_LOG_INTERVAL:
            last_discovery_log = now
            _LOGGER.debug("Fluval BLE update: %s %s", service_info.device, change)
        runtime.device.update_ble(service_info.device, service_info.advertisement)

    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            update_ble,
            {"address": mac},
            bluetooth.BluetoothScanningMode.ACTIVE,
        )
    )
    entry.async_on_unload(
        async_track_time_interval(
            hass,
            lambda now: hass.loop.call_soon_threadsafe(
                lambda: hass.async_create_task(_async_run_auto_schedule(hass, entry.entry_id))
            ),
            timedelta(minutes=1),
        )
    )
    if hass.state is CoreState.running:
        hass.async_create_task(_async_apply_startup_schedule(hass, entry.entry_id))
    else:
        entry.async_on_unload(
            hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED,
                lambda event: hass.create_task(_async_apply_startup_schedule(hass, entry.entry_id)),
            )
        )
    if active_time == 0:
        hass.async_create_task(runtime.device.async_start_persistent_connection())
    _LOGGER.info("Device %s ready", mac)
    return True


async def async_reload_entry(hass: HomeAssistant, entry: FluvalConfigEntry) -> bool:
    """Reload a Fluval config entry using the standard unload/setup lifecycle."""
    unload_ok = await async_unload_entry(hass, entry)
    if not unload_ok:
        return False
    return await async_setup_entry(hass, entry)


@callback
def _migrate_legacy_registry_entries(hass: HomeAssistant, entry: ConfigEntry, mac: str) -> None:
    """Remove retired entities and clear the MAC formerly shown as a serial."""
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    entity_registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        if str(entity.unique_id).endswith(LEGACY_ENTITY_UNIQUE_ID_SUFFIXES):
            _LOGGER.info("Removing retired Fluval entity %s", entity.entity_id)
            entity_registry.async_remove(entity.entity_id)

    device_registry = dr.async_get(hass)
    for device_entry in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        if device_entry.serial_number == mac:
            _LOGGER.info("Clearing MAC address from serial number for %s", device_entry.id)
            device_registry.async_update_device(device_entry.id, serial_number=None)


async def _register_static_paths(hass: HomeAssistant) -> None:
    """Serve the Fluval BLE Lovelace card from the integration directory."""
    if hass.data[DOMAIN].get(STATIC_REGISTERED):
        return

    static_path = str(Path(__file__).parent / "www")
    register_one = getattr(hass.http, "async_register_static_path", None)
    register_many = getattr(hass.http, "async_register_static_paths", None)

    try:
        if register_one is not None:
            result = register_one(STATIC_URL, static_path, cache_headers=False)
            if inspect.isawaitable(result):
                await result
        elif register_many is not None:
            from homeassistant.components.http import StaticPathConfig  # noqa: PLC0415

            result = register_many([StaticPathConfig(STATIC_URL, static_path, cache_headers=False)])
            if inspect.isawaitable(result):
                await result
        else:
            _LOGGER.warning(
                "Unable to register Fluval BLE Lovelace card static path; "
                "copy fluvalble-schedule-card.js to /config/www manually"
            )
            return
    except Exception:  # noqa: BLE001
        _LOGGER.warning(
            "Unable to register Fluval BLE Lovelace card static path; "
            "integration will continue without the built-in card resource",
            exc_info=True,
        )
        return

    hass.data[DOMAIN][STATIC_REGISTERED] = True


def _register_services(hass: HomeAssistant) -> None:
    """Register integration services once for the domain."""
    if hass.data[DOMAIN].get(SERVICES_REGISTERED):
        return

    def get_device(call: ServiceCall) -> Device:
        entry_id = call.data.get("entry_id")
        mac = (call.data.get("mac") or "").upper()
        for candidate_entry_id, runtime in _iter_entry_runtime(hass):
            device = runtime.device
            if entry_id and candidate_entry_id != entry_id:
                continue
            if mac and device.mac.upper() != mac:
                continue
            return device
        raise HomeAssistantError("No matching Fluval BLE device is ready")

    def get_entry_id(data: dict) -> str:
        entry_id = data.get("entry_id")
        mac = (data.get("mac") or "").upper()
        for candidate_entry_id, runtime in _iter_entry_runtime(hass):
            device = runtime.device
            if entry_id and candidate_entry_id == entry_id:
                return candidate_entry_id
            if mac and device.mac.upper() == mac:
                return candidate_entry_id

        for entry in hass.config_entries.async_entries(DOMAIN):
            entry_mac = (entry.data.get(CONF_MAC) or "").upper()
            if entry_id and entry.entry_id == entry_id:
                return entry.entry_id
            if mac and entry_mac == mac:
                return entry.entry_id

        if not entry_id and not mac:
            entries = hass.config_entries.async_entries(DOMAIN)
            if entries:
                return entries[0].entry_id

        raise HomeAssistantError("No matching Fluval BLE config entry was found")

    async def async_set_channels(call: ServiceCall) -> None:
        device = get_device(call)
        values = {
            channel: call.data[color]
            for channel, color in (
                ("channel_1", "red"),
                ("channel_2", "green"),
                ("channel_3", "blue"),
                ("channel_4", "white"),
                ("channel_5", "channel_5"),
            )
            if color in call.data
        }
        if not values:
            raise HomeAssistantError("At least one channel value is required")
        await device.async_set_channels(
            values,
            transition=call.data["transition"],
            step_seconds=call.data["step_seconds"],
        )

    async def async_preview_schedule(call: ServiceCall) -> None:
        device = get_device(call)
        await device.async_preview_schedule(
            call.data["points"],
            duration=call.data["duration"],
            step_seconds=call.data["step_seconds"],
        )

    async def async_stop_preview(call: ServiceCall) -> None:
        device = get_device(call)
        await device.async_stop_preview()

    async def async_save_schedule(call: ServiceCall) -> None:
        entry_id = get_entry_id(call.data)
        await _async_save_schedule(
            hass,
            entry_id,
            call.data["points"],
            mode=call.data.get("mode"),
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_CHANNELS,
        async_set_channels,
        schema=CHANNEL_SERVICE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_PREVIEW_SCHEDULE,
        async_preview_schedule,
        schema=PREVIEW_SERVICE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_STOP_PREVIEW,
        async_stop_preview,
        schema=STOP_PREVIEW_SERVICE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SAVE_SCHEDULE,
        async_save_schedule,
        schema=SCHEDULE_SERVICE_SCHEMA,
    )
    hass.data[DOMAIN][SERVICES_REGISTERED] = True


def _register_websocket(hass: HomeAssistant) -> None:
    """Register websocket commands for Lovelace schedule loading."""
    if hass.data[DOMAIN].get(WEBSOCKET_REGISTERED):
        return

    @websocket_api.websocket_command(
        {
            vol.Required("type"): "fluvalble/get_schedule",
            vol.Optional("entry_id"): str,
            vol.Optional("mac"): str,
        }
    )
    @websocket_api.async_response
    async def websocket_get_schedule(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict,
    ) -> None:
        """Return the saved schedule for a Fluval entry."""
        try:
            entry_id = _entry_id_from_message(hass, msg)
        except HomeAssistantError as err:
            connection.send_error(msg["id"], "not_found", str(err))
            return

        saved = await _async_load_schedule_data(hass, entry_id)
        connection.send_result(
            msg["id"],
            {
                "entry_id": entry_id,
                "points": saved.get("points"),
                "mode": saved.get("mode", "manual"),
            },
        )

    websocket_api.async_register_command(hass, websocket_get_schedule)
    hass.data[DOMAIN][WEBSOCKET_REGISTERED] = True


def _entry_id_from_message(hass: HomeAssistant, msg: dict) -> str:
    """Resolve a websocket message target to a config entry id."""
    entry_id = msg.get("entry_id")
    mac = (msg.get("mac") or "").upper()

    for entry in hass.config_entries.async_entries(DOMAIN):
        entry_mac = (entry.data.get(CONF_MAC) or "").upper()
        if entry_id and entry.entry_id == entry_id:
            return entry.entry_id
        if mac and entry_mac == mac:
            return entry.entry_id

    if not entry_id and not mac:
        entries = hass.config_entries.async_entries(DOMAIN)
        if entries:
            return entries[0].entry_id

    raise HomeAssistantError("No matching Fluval BLE config entry was found")


async def _async_load_schedule(hass: HomeAssistant, entry_id: str) -> list | None:
    """Load one saved schedule from storage."""
    return (await _async_load_schedule_data(hass, entry_id)).get("points")


async def _async_load_schedule_data(hass: HomeAssistant, entry_id: str) -> dict:
    """Load one saved schedule record from storage."""
    store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    data = await store.async_load() or {}
    schedules = data.get("schedules", {})
    saved = schedules.get(entry_id)
    if isinstance(saved, list):
        return {"points": saved, "mode": "manual"}
    if isinstance(saved, dict):
        return {
            "points": saved.get("points"),
            "mode": saved.get("mode", "manual"),
        }
    return {"points": None, "mode": "manual"}


async def _async_save_schedule(
    hass: HomeAssistant,
    entry_id: str,
    points: list,
    *,
    mode: str | None = None,
) -> None:
    """Save one schedule to storage."""
    store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    data = await store.async_load() or {}
    schedules = data.setdefault("schedules", {})
    existing = schedules.get(entry_id)
    existing_mode = existing.get("mode", "manual") if isinstance(existing, dict) else "manual"
    schedule_mode = mode or existing_mode
    schedules[entry_id] = {
        "points": points,
        "mode": schedule_mode,
    }
    await store.async_save(data)

    device = _device_for_entry(hass, entry_id)
    if device is not None:
        device.schedule_mode = schedule_mode
        for handler in device.updates_component:
            handler()


def _iter_entry_runtime(hass: HomeAssistant) -> list[tuple[str, FluvalRuntimeData]]:
    """Yield (entry_id, runtime_data) for loaded Fluval entries."""
    results: list[tuple[str, FluvalRuntimeData]] = []
    loaded = getattr(hass.config_entries, "async_loaded_entries", None)
    if loaded is not None:
        entries = loaded(DOMAIN)
    elif ConfigEntryState is not None:
        entries = [
            entry for entry in hass.config_entries.async_entries(DOMAIN) if entry.state is ConfigEntryState.LOADED
        ]
    else:
        entries = list(hass.config_entries.async_entries(DOMAIN))
    for entry in entries:
        runtime = getattr(entry, "runtime_data", None)
        if isinstance(runtime, FluvalRuntimeData):
            results.append((entry.entry_id, runtime))
    return results


def _device_for_entry(hass: HomeAssistant, entry_id: str) -> Device | None:
    """Return the runtime device for a config entry across old and new storage shapes."""
    config_entries = getattr(hass, "config_entries", None)
    async_get_entry = getattr(config_entries, "async_get_entry", None)
    if async_get_entry is not None:
        entry = async_get_entry(entry_id)
        runtime = getattr(entry, "runtime_data", None) if entry is not None else None
        if isinstance(runtime, FluvalRuntimeData):
            return runtime.device

    entry_data = hass.data.get(DOMAIN, {}).get(entry_id)
    if isinstance(entry_data, dict):
        device = entry_data.get("device")
        if isinstance(device, Device):
            return device
    return None


async def async_set_schedule_mode(hass: HomeAssistant, entry_id: str, mode: str) -> None:
    """Set the HA-owned schedule mode exposed in the device controls."""
    if mode not in {"manual", "auto"}:
        raise HomeAssistantError(f"Unsupported HA schedule mode: {mode}")

    saved = await _async_load_schedule_data(hass, entry_id)
    await _async_save_schedule(hass, entry_id, saved.get("points") or [], mode=mode)
    if mode == "auto":
        await _async_run_auto_schedule(hass, entry_id)


async def _async_apply_auto_schedule(hass: HomeAssistant, entry_id: str) -> bool:
    """Apply the saved schedule for one entry when HA schedule mode is auto."""
    device = _device_for_entry(hass, entry_id)
    if device is None:
        return False

    saved = await _async_load_schedule_data(hass, entry_id)
    device.schedule_mode = saved.get("mode", "manual")
    if saved.get("mode") != "auto":
        device.diagnostics.update(
            {
                "auto_schedule_mode": saved.get("mode", "manual"),
                "auto_schedule_last_result": "manual_mode",
            }
        )
        return True
    if device.channel_test_active:
        device.diagnostics.update(
            {
                "auto_schedule_mode": "auto",
                "auto_schedule_last_result": "channel_test_active",
            }
        )
        return True
    if not saved.get("points"):
        device.diagnostics.update(
            {
                "auto_schedule_mode": "auto",
                "auto_schedule_last_result": "no_schedule",
            }
        )
        return True

    from homeassistant.util import dt as dt_util  # noqa: PLC0415

    local_now = dt_util.now()
    minute = (local_now.hour * 60) + local_now.minute
    points = device._normalize_schedule_points(saved["points"])  # noqa: SLF001
    channels = device._interpolate_schedule(points, minute)  # noqa: SLF001
    device.diagnostics.update(
        {
            "auto_schedule_mode": "auto",
            "auto_schedule_last_run": local_now.isoformat(),
            "auto_schedule_time": device._format_minute(minute),  # noqa: SLF001
            "auto_schedule_target": channels,
        }
    )
    last_seen = device.conn_info.get("last_seen")
    is_recent = bool(
        last_seen and (dt_util.utcnow() - last_seen).total_seconds() <= timedelta(minutes=5).total_seconds()
    )
    needs_recovery = not device.connected or not is_recent
    if not needs_recovery and all(int(device.values.get(channel, -1)) == value for channel, value in channels.items()):
        device.diagnostics.update(
            {
                "status": "auto_schedule_skipped",
                "auto_schedule_last_result": "unchanged",
            }
        )
        for handler in device.updates_connect:
            handler()
        return True

    ok = await device.async_set_channels(channels, force=needs_recovery)
    confirmation_required = bool(device.client is not None and device.client.raw_facebd)
    verified = bool(not confirmation_required or (device.client is not None and device.client.last_write_verified))
    applied = bool(ok and verified)
    device.diagnostics.update(
        {
            "status": (
                "auto_schedule_applied" if applied else ("auto_schedule_unverified" if ok else "auto_schedule_failed")
            ),
            "auto_schedule_last_result": ("applied" if applied else ("unverified" if ok else "failed")),
            "auto_schedule_last_error": (
                None
                if applied
                else (
                    "The AquaSky did not confirm the requested channel state"
                    if ok
                    else device.diagnostics.get("last_error")
                )
            ),
        }
    )
    for handler in device.updates_connect:
        handler()
    return applied


async def _async_run_auto_schedule(hass: HomeAssistant, entry_id: str) -> bool:
    """Run the auto schedule without allowing a timer exception to be lost."""
    entry_data = hass.data.get(DOMAIN, {}).setdefault(entry_id, {})
    lock = entry_data.setdefault("auto_schedule_lock", asyncio.Lock())
    try:
        async with lock:
            return await _async_apply_auto_schedule(hass, entry_id)
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Unable to apply auto schedule for entry %s", entry_id)
        device = _device_for_entry(hass, entry_id)
        if device is not None:
            device.diagnostics.update(
                {
                    "status": "auto_schedule_failed",
                    "auto_schedule_last_result": "exception",
                    "auto_schedule_last_error": "Unexpected scheduler error; check the Home Assistant log",
                }
            )
            for handler in device.updates_connect:
                handler()
        return False


async def _async_apply_startup_schedule(hass: HomeAssistant, entry_id: str) -> None:
    """Apply Auto mode once the Bluetooth device is available after startup."""
    for attempt in range(STARTUP_SCHEDULE_RETRY_COUNT):
        device = _device_for_entry(hass, entry_id)
        if device is not None:
            device.diagnostics["auto_schedule_startup_attempt"] = attempt + 1
            if await _async_run_auto_schedule(hass, entry_id):
                return
        await asyncio.sleep(STARTUP_SCHEDULE_RETRY_SECONDS)

    _LOGGER.warning(
        "Fluval device for entry %s was not available after %s seconds; "
        "the next one-minute Auto schedule tick will retry",
        entry_id,
        STARTUP_SCHEDULE_RETRY_SECONDS * STARTUP_SCHEDULE_RETRY_COUNT,
    )


async def async_unload_entry(hass: HomeAssistant, entry: FluvalConfigEntry) -> bool:
    """Unload platforms and close the config entry's BLE client."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    runtime = getattr(entry, "runtime_data", None)
    if isinstance(runtime, FluvalRuntimeData):
        await runtime.device.async_shutdown()

    return True
