"""A single Fluval BLE connected LED device."""

from collections.abc import Callable
import asyncio
import contextlib
from datetime import UTC, datetime
import logging
from time import monotonic
from typing import Any, TypedDict

from bleak import AdvertisementData, BLEDevice, BleakError, BleakScanner
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

from . import (
    CONF_LAMP_PROFILE,
    DEFAULT_LAMP_PROFILE,
    LAMP_PROFILE_AQUASKY,
    LAMP_PROFILE_AQUASKY3,
    LAMP_PROFILE_AUTO,
    LAMP_PROFILE_PLANT,
)
from .client import Client
from .discovery import (
    CONF_MODEL,
    FLUVAL_MANUFACTURER_IDS,
    detect_model,
)
from . import protocol

_LOGGER = logging.getLogger(__name__)

NUMBERS = ["channel_1", "channel_2", "channel_3", "channel_4", "channel_5"]
SELECTS = ["mode"]
SENSORS = ["rssi", "last_seen"]
DIAGNOSTICS = ["diagnostics"]
AQUASKY_NUMBERS = ["channel_1", "channel_2", "channel_3", "channel_4"]
CHANNEL_NAMES_AQUASKY = {
    "channel_1": "Red",
    "channel_2": "Green",
    "channel_3": "Blue",
    "channel_4": "White",
    "channel_5": "Violet",
}
CHANNEL_NAMES_PLANT = {
    "channel_1": "Rose",
    "channel_2": "Blue",
    "channel_3": "Cold White",
    "channel_4": "Pure White",
    "channel_5": "Warm White",
}
# Back-compat alias used by tests / schedule helpers
CHANNEL_NAMES = CHANNEL_NAMES_AQUASKY
MODES = ["manual", "automatic", "professional"]
MODE_TO_CODE = {mode: index for index, mode in enumerate(MODES)}
DIAGNOSTIC_UPDATE_INTERVAL = 5
BLE_LOOKUP_TIMEOUT = 10
BLE_LOOKUP_RETRIES = 3
PREVIEW_STEP_SECONDS = 2
TRANSITION_STEP_SECONDS = 30
DAY_MINUTES = 24 * 60

# Approximate sRGB appearance of each Plant LED channel (0–1).
# Used to translate channel mixes ↔ HA light color so the preview matches the look.
PLANT_CHANNEL_RGB = {
    "channel_1": (1.00, 0.28, 0.38),  # Rose
    "channel_2": (0.18, 0.38, 1.00),  # Blue
    "channel_3": (0.72, 0.84, 1.00),  # Cold White
    "channel_4": (1.00, 1.00, 1.00),  # Pure White
    "channel_5": (1.00, 0.72, 0.42),  # Warm White
}


class Attribute(TypedDict, total=False):
    """Attributes used by entities like binary_sensor and number."""

    options: list[str]
    default: str

    min: int
    max: int
    step: int
    value: int

    is_on: bool
    extra: dict
    device_class: str
    native_unit_of_measurement: str | None


class Device:
    """Fluval BLE LED device class."""

    def __init__(
        self,
        name: str,
        device: BLEDevice | None = None,
        advertisement: AdvertisementData | None = None,
        hass: HomeAssistant | None = None,
        config_data: dict[str, Any] | None = None,
        ping_interval: int = 10,
        active_time: int = 120,
    ) -> None:
        """Initialize the device."""
        config_data = config_data or {}
        self.hass = hass
        self.name = name or (device.name if device else None) or "Fluval"
        self.model = config_data.get(CONF_MODEL) or detect_model(
            (device.name if device else None) or name, advertisement
        )
        self.lamp_profile = config_data.get(CONF_LAMP_PROFILE, DEFAULT_LAMP_PROFILE)
        self._channel_count_hint: int | None = None
        self.address = (config_data.get("mac") or (device.address if device else "")).upper()
        self.client: Client | None = None
        self._ping_interval = ping_interval
        self._active_time = active_time
        self.connected = False
        self.conn_info = {
            "mac": self.address,
            "model": self.model,
            "service_uuids": config_data.get("service_uuids", []),
            "service_data": config_data.get("service_data", {}),
        }
        self.facebd = self._uses_facebd_protocol(
            self.name,
            self.conn_info["service_uuids"],
            self.conn_info["service_data"],
            config_data.get("manufacturer_data", {}),
        )
        self.updates_connect: list = []
        self.updates_component: list = []
        self._last_diagnostic_update = 0.0
        self.values = {}
        for channel in NUMBERS:
            self.values[channel] = 0
        self.values["mode"] = "manual"
        self.values["led_on_off"] = False
        self.diagnostics: dict[str, Any] = {
            "status": "not_run",
            "configured_mac": self.address,
        }
        self.preview_task: asyncio.Task | None = None
        self.preview_restore_values: dict[str, int] | None = None
        self._clock_synced = False
        self._clock_sync_lock = asyncio.Lock()

        if device and advertisement:
            self.update_ble(device, advertisement)

    @property
    def mac(self) -> str:
        """Expose the MAC address of the device."""
        return self.address

    @property
    def model_name(self) -> str:
        """Expose a model name for Home Assistant device info."""
        return self.model

    def update_ble(self, device: BLEDevice, advertisement: AdvertisementData):
        """Update BLE metadata."""
        self.address = device.address
        self.conn_info["mac"] = device.address
        self.conn_info["last_seen"] = datetime.now(UTC)
        self.conn_info["rssi"] = advertisement.rssi
        self.conn_info["service_uuids"] = list(advertisement.service_uuids)
        self.conn_info["service_data"] = {
            key: bytes(value).hex() for key, value in advertisement.service_data.items()
        }
        self.facebd = self._uses_facebd_protocol(
            device.name,
            advertisement.service_uuids,
            advertisement.service_data,
            advertisement.manufacturer_data,
        )

        if self.client is None:
            self.client = self._make_client(device)
        else:
            self.client.device = device

        self._notify_diagnostics_throttled()

    def _make_client(self, device: BLEDevice) -> Client:
        """Create a BLE client wired to this device."""
        return Client(
            device,
            self.set_connected,
            self.decode_update_packet,
            ping_interval=self._ping_interval,
            active_time=self._active_time,
            ready_callback=self._async_on_client_ready,
        )

    async def _async_on_client_ready(self) -> None:
        """Run post-connect housekeeping after the BLE link is established."""
        ok = await self.async_sync_clock(force=False)
        if not ok:
            _LOGGER.warning("Fluval clock sync failed after connect for %s", self.address)

    def set_connected(self, connected: bool):
        """Set the connection status."""
        self.connected = connected
        if not connected:
            # Allow clock sync again on the next successful connect (#8).
            self._clock_synced = False

        for handler in self.updates_connect:
            handler()

    def _notify_diagnostics_throttled(self):
        """Notify diagnostic entities at most once per interval."""
        now = monotonic()
        if now - self._last_diagnostic_update < DIAGNOSTIC_UPDATE_INTERVAL:
            return

        self._last_diagnostic_update = now
        for handler in self.updates_connect:
            handler()

    def numbers(self) -> list[str]:
        """List of numbers provided by the device."""
        if self._resolved_channel_count() == 4:
            return list(AQUASKY_NUMBERS)
        return list(NUMBERS)

    def _resolved_channel_count(self) -> int:
        """Return 4 or 5 channels from profile, packet hint, or name heuristics."""
        profile = (self.lamp_profile or LAMP_PROFILE_AUTO).lower()
        if profile == LAMP_PROFILE_AQUASKY:
            return 4
        if profile in (LAMP_PROFILE_PLANT, LAMP_PROFILE_AQUASKY3):
            return 5
        if self._channel_count_hint in (4, 5):
            return self._channel_count_hint
        if self.facebd or self._uses_mesh_protocol():
            return 5

        model_l = (self.model or "").lower()
        name_l = (self.name or "").lower()
        combined = f"{model_l} {name_l}"

        if any(token in combined for token in ("plant", "marine", "reef")):
            return 5
        # AquaSky 3.x / FACEBD-era names are 5-channel; only classic 2.0 is 4.
        if "aquasky" in combined:
            if any(token in combined for token in ("3.0", "3_", "aquasky3", "3.0 bluetooth")):
                return 5
            if any(token in combined for token in ("2.0", "2_", "aquasky2")):
                return 4
            # Ambiguous "AquaSky" without version → 4 (classic default).
            return 4
        return 5

    def _channel_labels(self) -> dict[str, str]:
        """Return channel labels for the active lamp profile."""
        profile = (self.lamp_profile or LAMP_PROFILE_AUTO).lower()
        if profile == LAMP_PROFILE_PLANT:
            return CHANNEL_NAMES_PLANT
        if profile in (LAMP_PROFILE_AQUASKY, LAMP_PROFILE_AQUASKY3):
            return CHANNEL_NAMES_AQUASKY
        model_l = (self.model or "").lower()
        name_l = (self.name or "").lower()
        if "plant" in model_l or "plant" in name_l or "marine" in model_l or "reef" in model_l:
            return CHANNEL_NAMES_PLANT
        return CHANNEL_NAMES_AQUASKY

    def uses_plant_spectrum(self) -> bool:
        """True when channels are Plant Rose/Blue/CW/PW/WW (not AquaSky RGB)."""
        return self._channel_labels() == CHANNEL_NAMES_PLANT

    def light_mode(self) -> str:
        """Return HA light mode: plant spectrum → rgb (translated), AquaSky → rgbw."""
        if self.uses_plant_spectrum():
            return "rgb"
        if self._resolved_channel_count() == 4:
            return "rgbw"
        return "rgbw"

    def master_brightness(self) -> int:
        """Overall brightness as the brightest supported channel (0–100)."""
        chans = self.numbers()
        return max((self.values.get(ch, 0) for ch in chans), default=0)

    def light_brightness_255(self) -> int:
        """Brightness for the HA light entity (0–255)."""
        return round(self.master_brightness() / 100 * 255)

    def light_rgb_255(self) -> tuple[int, int, int]:
        """Translate the current Plant channel mix into an HA RGB preview color."""
        mix_r = mix_g = mix_b = 0.0
        for channel, (cr, cg, cb) in PLANT_CHANNEL_RGB.items():
            weight = max(0, min(100, int(self.values.get(channel, 0)))) / 100.0
            mix_r += cr * weight
            mix_g += cg * weight
            mix_b += cb * weight
        peak = max(mix_r, mix_g, mix_b, 1e-6)
        return (
            max(0, min(255, round(mix_r / peak * 255))),
            max(0, min(255, round(mix_g / peak * 255))),
            max(0, min(255, round(mix_b / peak * 255))),
        )

    def light_rgbw_255(self) -> tuple[int, int, int, int]:
        """Current AquaSky channels as HA RGBW (0–255), relative to max channel."""
        r = int(self.values.get("channel_1", 0))
        g = int(self.values.get("channel_2", 0))
        b = int(self.values.get("channel_3", 0))
        w = int(self.values.get("channel_4", 0))
        peak = max(r, g, b, w, 1)
        return (
            round(r / peak * 255),
            round(g / peak * 255),
            round(b / peak * 255),
            round(w / peak * 255),
        )

    @staticmethod
    def _ha_component_to_percent(component: int, brightness: int) -> int:
        """Convert a 0–255 HA color component + brightness into 0–100%."""
        component = max(0, min(255, int(component)))
        brightness = max(0, min(255, int(brightness)))
        return max(0, min(100, round(component / 255 * brightness / 255 * 100)))

    def channels_from_rgbw(
        self,
        rgbw: tuple[int, int, int, int],
        brightness: int,
    ) -> dict[str, int]:
        """Map HA RGBW (+ brightness) onto Fluval channel percents."""
        r, g, b, w = rgbw
        values = {
            "channel_1": self._ha_component_to_percent(r, brightness),
            "channel_2": self._ha_component_to_percent(g, brightness),
            "channel_3": self._ha_component_to_percent(b, brightness),
            "channel_4": self._ha_component_to_percent(w, brightness),
        }
        if "channel_5" in self.numbers():
            values["channel_5"] = int(self.values.get("channel_5", 0))
        return values

    def channels_from_rgb(
        self,
        rgb: tuple[int, int, int],
        brightness: int,
    ) -> dict[str, int]:
        """Translate an HA RGB color into Plant Rose/Blue/CW/PW/WW levels.

        Decomposes the requested color into the five real LED channels so the
        resulting mix (and therefore the HA preview after refresh) matches the
        look as closely as the hardware allows — not a 1:1 fake channel alias.
        """
        r = max(0, min(255, int(rgb[0]))) / 255.0
        g = max(0, min(255, int(rgb[1]))) / 255.0
        b = max(0, min(255, int(rgb[2]))) / 255.0
        scale = max(0, min(255, int(brightness))) / 255.0

        # Shared white from the RGB floor, split cold/pure/warm by hue bias.
        white = min(r, g, b)
        rem_r, rem_g, rem_b = r - white, g - white, b - white
        warmth = r / (r + b + 1e-6)  # 0 = cool, 1 = warm
        cool = 1.0 - warmth

        rose = rem_r + white * 0.08 * warmth
        blue = rem_b + white * 0.10 * cool
        # No green LED: leftover green intensifies pure white (looks correct in mix).
        pure = white * (0.35 + 0.40 * (1.0 - abs(warmth - 0.5) * 2.0)) + rem_g
        cold = white * (0.55 * cool + 0.15)
        warm = white * (0.55 * warmth + 0.15)

        def _pct(value: float) -> int:
            return max(0, min(100, round(value * scale * 100)))

        return {
            "channel_1": _pct(rose),
            "channel_2": _pct(blue),
            "channel_3": _pct(cold),
            "channel_4": _pct(pure),
            "channel_5": _pct(warm),
        }

    async def async_set_master_brightness(self, level: int) -> bool:
        """Scale all supported channels to level, preserving ratios."""
        level = max(0, min(100, int(level)))
        chans = self.numbers()
        old_values = dict(self.values)
        current_max = max((self.values.get(ch, 0) for ch in chans), default=0)
        if current_max <= 0:
            for ch in chans:
                self.values[ch] = level
        else:
            factor = level / current_max
            for ch in chans:
                self.values[ch] = min(100, max(0, round(self.values.get(ch, 0) * factor)))

        if not await self.async_set_value(chans[0], self.values[chans[0]]):
            self.values = old_values
            return False
        return True

    async def async_apply_light_channels(self, values: dict[str, int]) -> bool:
        """Apply channel percents from the light entity and ensure the LED is on."""
        if not await self.async_set_channels(values):
            return False
        if not self.values.get("led_on_off"):
            return await self.async_set_switch("led_on_off", True)
        return True

    def entity_name(self, attr: str) -> str:
        """Return a user-facing entity suffix for this device attribute."""
        labels = self._channel_labels()
        if attr in labels:
            return labels[attr]
        return attr.replace("_", " ").title()

    def selects(self) -> list[str]:
        """List of select boxes provided by the device."""
        return list(SELECTS)

    def sensors(self) -> list[str]:
        """List of diagnostics sensors provided by the device."""
        return list(SENSORS) + list(DIAGNOSTICS)

    def attribute(self, attr: str) -> Attribute:
        """Provide attributes to the entities like switches, numbers etc."""
        if attr == "connection":
            return Attribute(is_on=self.connected, extra=self.conn_info)
        if attr.startswith("channel_"):
            return Attribute(min=0, max=100, step=1, value=self.values[attr])
        if attr == "mode":
            return Attribute(options=MODES, default=self.values[attr])
        if attr == "led_on_off":
            return Attribute(is_on=self.values[attr])
        if attr == "rssi":
            return Attribute(
                value=self.conn_info.get("rssi"),
                native_unit_of_measurement="dBm",
            )
        if attr == "last_seen":
            return Attribute(value=self.conn_info.get("last_seen"))
        if attr == "diagnostics":
            return Attribute(
                value=self.diagnostics.get("status"),
                extra=self.diagnostics,
            )
        return Attribute()

    def register_update(self, attr: str, handler: Callable):
        """Register handlers for updates."""
        if attr in ("connection", "rssi", "last_seen"):
            self.updates_connect.append(handler)
        elif attr in DIAGNOSTICS:
            self.updates_connect.append(handler)
        else:
            self.updates_component.append(handler)

    def deregister_update(self, attr: str, handler: Callable):
        """Remove a previously registered update handler."""
        target = (
            self.updates_connect
            if attr in ("connection", "rssi", "last_seen", *DIAGNOSTICS)
            else self.updates_component
        )
        with contextlib.suppress(ValueError):
            target.remove(handler)

    async def async_set_value(self, attr: str, value: int) -> bool:
        """Set values received by entities such as numbers and switches."""
        if attr.startswith("channel_"):
            return await self.async_set_channels({attr: int(value)})

        _LOGGER.debug("Value %s changed to %s", attr, value)
        return False

    async def async_set_channels(
        self,
        values: dict[str, int],
        *,
        transition: int = 0,
        step_seconds: int = TRANSITION_STEP_SECONDS,
    ) -> bool:
        """Set multiple channel values, optionally ramping over time."""
        channels = self.numbers()
        targets = {channel: max(0, min(100, int(values.get(channel, self.values[channel])))) for channel in channels}
        if not targets:
            return False

        if all(int(self.values.get(channel, -1)) == value for channel, value in targets.items()):
            _LOGGER.debug("Skipping Fluval channel write because targets are unchanged: %s", targets)
            return True

        old_values = dict(self.values)
        if not await self._async_prepare_command():
            _LOGGER.warning("Cannot set Fluval channel before BLE device is available")
            self.values = old_values
            return False

        if self.values.get("mode") != "manual":
            ok = await self._async_send_packet(self._mode_packet(MODE_TO_CODE["manual"]))
            if not ok:
                self.values = old_values
                return False
            self.values["mode"] = "manual"

        if transition <= 0:
            for channel, value in targets.items():
                self.values[channel] = value
            return await self._async_send_channel_state(old_values)

        steps = max(1, int(transition / max(1, step_seconds)))
        start_values = {channel: int(old_values[channel]) for channel in channels}
        for step in range(1, steps + 1):
            ratio = step / steps
            for channel in channels:
                start = start_values[channel]
                end = targets[channel]
                self.values[channel] = round(start + ((end - start) * ratio))
            if not await self._async_send_channel_state(old_values):
                self.values = old_values
                return False
            if step < steps:
                await asyncio.sleep(step_seconds)

        return True

    async def _async_send_channel_state(self, old_values: dict[str, Any]) -> bool:
        """Send the current channel values to the controller."""
        if self._uses_wifi_protocol() or self._uses_mesh_protocol():
            if any(self._channel_values()) and not self.values["led_on_off"]:
                self.values["led_on_off"] = True
                if not await self._async_send_packet(self._switch_packet(True)):
                    self.values = old_values
                    return False
            ok = await self._async_send_packet(self._channels_packet(self._channel_values()))
        else:
            ok = await self._async_send_packet(self._channels_packet(self._channel_values()))

        if not ok:
            self.values = old_values
            for handler in self.updates_component:
                handler()
        return ok

    async def async_preview_schedule(
        self,
        points: list[dict[str, Any]],
        *,
        duration: int = 60,
        step_seconds: int = PREVIEW_STEP_SECONDS,
    ) -> bool:
        """Preview a 24-hour schedule on the real light in compressed time."""
        await self.async_stop_preview()
        self.preview_restore_values = {channel: int(self.values.get(channel, 0)) for channel in self.numbers()}
        self.preview_task = asyncio.create_task(self._async_preview_schedule(points, duration, step_seconds))
        return True

    async def async_stop_preview(self) -> None:
        """Stop any running physical schedule preview."""
        if self.preview_task and not self.preview_task.done():
            self.preview_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.preview_task
        self.preview_task = None
        if self.preview_restore_values:
            restore_values = self.preview_restore_values
            self.preview_restore_values = None
            await self.async_set_channels(restore_values)

    async def _async_preview_schedule(
        self,
        points: list[dict[str, Any]],
        duration: int,
        step_seconds: int,
    ) -> None:
        """Run the schedule preview task."""
        normalized = self._normalize_schedule_points(points)
        if len(normalized) < 2:
            self._set_diagnostic_error(
                "preview_failed",
                "Schedule preview requires at least two points",
            )
            return

        steps = max(1, int(duration / max(1, step_seconds)))
        self.diagnostics.update(
            {
                "status": "preview_running",
                "schedule_points": normalized,
            }
        )
        for handler in self.updates_connect:
            handler()

        try:
            for step in range(steps + 1):
                minute = round((step / steps) * DAY_MINUTES) % DAY_MINUTES
                channels = self._interpolate_schedule(normalized, minute)
                self.diagnostics.update(
                    {
                        "status": "preview_running",
                        "preview_minute": minute,
                        "preview_time": self._format_minute(minute),
                        "spectrum": self._spectrum_report(channels),
                    }
                )
                await self.async_set_channels(channels)
                if step < steps:
                    await asyncio.sleep(step_seconds)
        except asyncio.CancelledError:
            self.diagnostics["status"] = "preview_stopped"
            raise
        else:
            self.diagnostics["status"] = "preview_complete"
        finally:
            for handler in self.updates_connect:
                handler()

    def normalize_schedule_points(self, points: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normalize schedule points to minutes and channel values."""
        if self.uses_plant_spectrum():
            aliases = {
                "channel_1": ("rose", "red"),
                "channel_2": ("blue", "green"),
                "channel_3": ("cold_white", "cold"),
                "channel_4": ("pure_white", "pure", "white"),
                "channel_5": ("warm_white", "warm", "violet", "channel_5"),
            }
        else:
            aliases = {
                "channel_1": ("red",),
                "channel_2": ("green",),
                "channel_3": ("blue",),
                "channel_4": ("white",),
                "channel_5": ("violet", "channel_5"),
            }

        normalized = []
        for point in points:
            minute = self._parse_time_to_minute(str(point["time"]))
            channels: dict[str, int] = {}
            for channel, names in aliases.items():
                value = point.get(channel)
                if value is None:
                    for name in names:
                        if name in point:
                            value = point[name]
                            break
                channels[channel] = max(0, min(100, int(value or 0)))
            normalized.append({"minute": minute, "time": self._format_minute(minute), **channels})

        return sorted(normalized, key=lambda item: item["minute"])

    # Back-compat for older call sites / tests
    _normalize_schedule_points = normalize_schedule_points

    def interpolate_schedule(self, points: list[dict[str, Any]], minute: int) -> dict[str, int]:
        """Return interpolated channel values for one minute of the day."""
        previous = points[-1]
        next_point = points[0]
        for index, point in enumerate(points):
            if point["minute"] <= minute:
                previous = point
                next_point = points[(index + 1) % len(points)]

        start = previous["minute"]
        end = next_point["minute"]
        if end <= start:
            end += DAY_MINUTES
        current = minute if minute >= start else minute + DAY_MINUTES
        ratio = 0 if end == start else (current - start) / (end - start)

        return {
            channel: round(previous[channel] + ((next_point[channel] - previous[channel]) * ratio))
            for channel in NUMBERS
        }

    # Back-compat for older call sites / tests
    _interpolate_schedule = interpolate_schedule

    def _spectrum_report(self, channels: dict[str, int]) -> dict[str, Any]:
        """Return graph-friendly spectrum data for diagnostics and previews."""
        if self.uses_plant_spectrum():
            color_values = {
                "rose": channels["channel_1"],
                "blue": channels["channel_2"],
                "cold_white": channels["channel_3"],
                "pure_white": channels["channel_4"],
                "warm_white": channels["channel_5"],
            }
        else:
            color_values = {
                "red": channels["channel_1"],
                "green": channels["channel_2"],
                "blue": channels["channel_3"],
                "white": channels["channel_4"],
                "channel_5": channels["channel_5"],
            }
        return {
            "channels": color_values,
            "peak": max(color_values.values()),
            "total": sum(color_values.values()),
        }

    def _parse_time_to_minute(self, value: str) -> int:
        """Parse HH:MM into minutes from midnight."""
        hour, minute = value.split(":", 1)
        return ((int(hour) % 24) * 60) + int(minute)

    def _format_minute(self, minute: int) -> str:
        """Format minutes from midnight as HH:MM."""
        minute %= DAY_MINUTES
        return f"{minute // 60:02d}:{minute % 60:02d}"

    async def async_set_switch(self, attr: str, value: bool) -> bool:
        """Set switch values and send the updated state to the light."""
        _LOGGER.debug("Switch %s changed to %s", attr, value)
        old_values = dict(self.values)
        self.values[attr] = value
        if not await self._async_prepare_command():
            _LOGGER.warning("Cannot set Fluval switch before BLE device is available")
            self.values = old_values
            return False

        ok = await self._async_send_packet(self._switch_packet(value))

        if not ok:
            self.values = old_values
            for handler in self.updates_component:
                handler()
        return ok

    async def async_select_option(self, attr: str, option: str) -> bool:
        """Set select values and send the updated state to the light."""
        if attr != "mode" or option not in MODES:
            return False

        _LOGGER.debug("Mode changed to %s", option)
        old_values = dict(self.values)
        self.values[attr] = option
        if not await self._async_prepare_command():
            _LOGGER.warning("Cannot set Fluval mode before BLE device is available")
            self.values = old_values
            return False

        ok = await self._async_send_packet(self._mode_packet(MODE_TO_CODE[option]))

        if not ok:
            self.values = old_values
            for handler in self.updates_component:
                handler()
        return ok

    async def async_sync_clock(self, *, force: bool = False) -> bool:
        """Sync the lamp RTC from the Home Assistant host clock (#8)."""
        if self._clock_synced and not force:
            return True

        async with self._clock_sync_lock:
            if self._clock_synced and not force:
                return True

            if self.client is None:
                if not await self._async_ensure_client():
                    return False
            elif not await self.client.ensure_connected():
                self._set_diagnostic_error(
                    "clock_sync_failed",
                    self.client.last_error or "Unable to connect for clock sync",
                )
                return False

            if self._uses_wifi_protocol():
                packets = [protocol.wifi_timezone_packet(), protocol.wifi_clock_packet()]
            elif self._uses_mesh_protocol():
                packets = [protocol.mesh_clock_packet()]
            else:
                packets = [protocol.old_clock_packet()]

            for packet in packets:
                if not await self._async_send_packet(packet):
                    self._set_diagnostic_error("clock_sync_failed", "Unable to sync lamp clock")
                    return False

            self._clock_synced = True
            self.diagnostics.update(
                {
                    "status": "clock_synced",
                    "clock_synced_at": datetime.now(UTC).isoformat(),
                    "last_error": None,
                }
            )
            for handler in self.updates_connect:
                handler()
            return True

    def _switch_packet(self, is_on: bool) -> bytes:
        if self._uses_wifi_protocol():
            return protocol.wifi_switch_packet(is_on)
        if self._uses_mesh_protocol():
            return protocol.mesh_switch_packet(is_on)
        return protocol.old_switch_packet(is_on)

    def _mode_packet(self, mode: int) -> bytes:
        if self._uses_wifi_protocol():
            return protocol.wifi_mode_packet(mode)
        if self._uses_mesh_protocol():
            return protocol.mesh_mode_packet(mode)
        return protocol.old_mode_packet(mode)

    def _channels_packet(self, values: list[int]) -> bytes:
        if self._uses_wifi_protocol():
            return protocol.wifi_all_zone_packet(values)
        if self._uses_mesh_protocol():
            return protocol.mesh_all_zone_packet(values)
        return protocol.old_all_zone_packet(values)

    def _uses_wifi_protocol(self) -> bool:
        """Prefer the live GATT profile over advertisement heuristics."""
        if self.client is not None and self.client.command_write_uuid:
            write_uuid = self.client.command_write_uuid.lower()
            if write_uuid.startswith("facebd"):
                self.facebd = True
                return True
            if write_uuid.startswith(("00001001", "0000fff2")):
                self.facebd = False
                return False

        return self.facebd

    def _uses_mesh_protocol(self) -> bool:
        """Return true when the live GATT profile is Fluval mesh (fff0/D1)."""
        if self.client is not None:
            return bool(self.client.raw_mesh)
        return any(str(uuid).lower().startswith("0000fff0") for uuid in self.conn_info.get("service_uuids", []))

    async def _async_prepare_command(self) -> bool:
        """Resolve the BLE device and connect far enough to know the protocol."""
        if not await self._async_ensure_client():
            self._set_diagnostic_error("device_not_found", "BLE device is not available")
            return False
        ok = await self.client.ensure_connected()
        if not ok:
            self._set_diagnostic_error(
                "connect_failed",
                self.client.last_error or "Unable to connect to BLE device",
            )
        return ok

    async def _async_send_packet(self, packet: bytes) -> bool:
        """Send one already-built command packet to the controller."""
        if not await self._async_ensure_client():
            _LOGGER.warning("Cannot send Fluval state before BLE device is available")
            return False

        _LOGGER.debug(
            "Sending Fluval packet via %s (facebd=%s mesh=%s raw_facebd=%s): %s",
            self.client.command_write_uuid,
            self.facebd,
            self.client.raw_mesh,
            self.client.raw_facebd,
            packet.hex(),
        )
        if not await self.client.send_now(packet):
            self._set_diagnostic_error(
                "write_failed",
                self.client.last_error or "BLE write failed",
            )
            return False

        self.diagnostics.update(
            {
                "status": "last_write_ok",
                "last_write_at": datetime.now(UTC).isoformat(),
                "last_write_packet": packet.hex(),
                "last_write_targets": list(self.client.last_write_targets),
                "last_error": None,
            }
        )

        for handler in self.updates_component:
            handler()
        for handler in self.updates_connect:
            handler()
        return True

    async def async_refresh_state(self) -> bool:
        """Resolve the controller and request its current state."""
        if not await self._async_ensure_client():
            return False

        try:
            await self.client.request_state()
        except (TimeoutError, BleakError) as err:
            _LOGGER.debug("Unable to refresh Fluval state", exc_info=err)
            return False

        return True

    async def async_collect_diagnostics(self) -> dict[str, Any]:
        """Collect practical BLE diagnostics for this configured device."""
        if self.client is not None:
            await self.client.disconnect()
        now = datetime.now(UTC)
        report: dict[str, Any] = {
            "status": "running",
            "checked_at": now.isoformat(),
            "configured_mac": self.address,
            "name": self.name,
            "known_connection_info": dict(self.conn_info),
            "facebd": self.facebd,
            "connected": self.connected,
            "client_created": self.client is not None,
        }

        if self.hass is not None and self.address:
            service_info = bluetooth.async_last_service_info(self.hass, self.address, connectable=True)
            if service_info is None:
                service_info = bluetooth.async_last_service_info(self.hass, self.address)

            report["ha_last_service_info_found"] = service_info is not None
            if service_info is not None:
                report["ha_last_service_info"] = self._service_info_report(service_info)
                self.update_ble(service_info.device, service_info.advertisement)

        direct_device = None
        if self.address:
            try:
                direct_device = await BleakScanner.find_device_by_address(self.address, timeout=BLE_LOOKUP_TIMEOUT)
            except (TimeoutError, BleakError) as err:
                report["direct_scan_error"] = f"{type(err).__name__}: {err}"

        report["direct_scan_found"] = direct_device is not None
        if direct_device is not None:
            report["direct_scan_device"] = self._ble_device_report(direct_device)
            self._update_from_ble_device(direct_device)
            if self.client is None:
                self.client = self._make_client(direct_device)

        report["refresh_state_attempted"] = False
        report["refresh_state_ok"] = False
        if direct_device is not None or self.client is not None:
            report["refresh_state_attempted"] = True
            report["refresh_state_ok"] = await self.async_refresh_state()

        report["status"] = "ok" if report.get("direct_scan_found") else "not_found"
        report["updated_connection_info"] = dict(self.conn_info)
        self.diagnostics = report

        for handler in self.updates_connect:
            handler()

        return report

    def _channel_values(self) -> list[int]:
        """Return the current channel values in Fluval app order."""
        return [self.values[channel] for channel in NUMBERS]

    async def _async_ensure_client(self) -> bool:
        """Create a BLE client from the configured MAC when HA has not populated one."""
        if self.client is not None:
            return True

        if not self.address:
            return False

        device = await self._async_find_device()

        if device is None:
            return False

        self._update_from_ble_device(device)
        self.client = self._make_client(device)
        return True

    async def _async_find_device(self) -> BLEDevice | None:
        """Find the configured BLE device using HA cache first, then active scan."""
        if self.hass is not None:
            service_info = bluetooth.async_last_service_info(self.hass, self.address, connectable=True)
            if service_info is None:
                service_info = bluetooth.async_last_service_info(self.hass, self.address)
            if service_info is not None:
                self.update_ble(service_info.device, service_info.advertisement)
                return service_info.device

        for attempt in range(1, BLE_LOOKUP_RETRIES + 1):
            try:
                device = await BleakScanner.find_device_by_address(self.address, timeout=BLE_LOOKUP_TIMEOUT)
            except (TimeoutError, BleakError) as err:
                _LOGGER.debug(
                    "Unable to resolve Fluval device by address, attempt %s",
                    attempt,
                    exc_info=err,
                )
                await asyncio.sleep(attempt)
                continue
            if device is not None:
                return device

        return None

    def _set_diagnostic_error(self, status: str, message: str) -> None:
        """Store command failures in the diagnostics sensor for quick copying."""
        self.diagnostics.update(
            {
                "status": status,
                "last_error": message,
                "last_error_at": datetime.now(UTC).isoformat(),
                "configured_mac": self.address,
                "known_connection_info": dict(self.conn_info),
            }
        )
        for handler in self.updates_connect:
            handler()

    def _update_from_ble_device(self, device: BLEDevice) -> None:
        """Populate metadata from a directly resolved BLEDevice."""
        self.address = device.address
        self.conn_info["mac"] = device.address
        self.conn_info["last_seen"] = datetime.now(UTC)

        details = device.details if isinstance(device.details, dict) else {}
        props = details.get("props", {})
        self.conn_info["rssi"] = props.get("RSSI", self.conn_info.get("rssi"))

        service_uuids = list(props.get("UUIDs", self.conn_info.get("service_uuids", [])))
        self.conn_info["service_uuids"] = service_uuids
        self.facebd = self._uses_facebd_protocol(
            device.name,
            service_uuids,
            props.get("ServiceData", {}),
            props.get("ManufacturerData", {}),
        )
        self._notify_diagnostics_throttled()

    def _ble_device_report(self, device: BLEDevice) -> dict[str, Any]:
        """Return a copyable, JSON-friendly BLEDevice summary."""
        details = device.details if isinstance(device.details, dict) else {}
        props = details.get("props", {})
        return {
            "name": device.name,
            "address": device.address,
            "rssi": props.get("RSSI"),
            "uuids": list(props.get("UUIDs", [])),
            "service_data_keys": list(props.get("ServiceData", {})),
            "manufacturer_data_keys": [str(key) for key in props.get("ManufacturerData", {})],
            "path": details.get("path"),
        }

    def _service_info_report(self, service_info) -> dict[str, Any]:
        """Return a compact HA Bluetooth service info summary."""
        advertisement = service_info.advertisement
        return {
            "name": service_info.name,
            "address": service_info.address,
            "rssi": advertisement.rssi,
            "service_uuids": list(advertisement.service_uuids),
            "service_data": {key: bytes(value).hex() for key, value in advertisement.service_data.items()},
            "manufacturer_data": {
                str(key): bytes(value).hex() for key, value in advertisement.manufacturer_data.items()
            },
            "connectable": getattr(service_info, "connectable", None),
            "source": getattr(service_info, "source", None),
        }

    def _uses_facebd_protocol(
        self,
        name: str | None,
        service_uuids: list[str],
        service_data: dict,
        manufacturer_data: dict,
    ) -> bool:
        """Return true when advertisements match the newer FACEBD controllers."""
        if any(uuid.lower().startswith("facebd") for uuid in service_uuids):
            return True

        if any(str(uuid).lower().startswith("facebd") for uuid in service_data):
            return True

        manufacturer_ids = {int(key) for key in manufacturer_data}
        return bool(FLUVAL_MANUFACTURER_IDS.intersection(manufacturer_ids))

    def decode_update_packet(self, data: bytearray):
        """Decode the received Fluval packet and sort into values."""
        payload = bytes(data)
        if self._uses_mesh_protocol() or (payload and payload[0] in (protocol.MESH_OPCODE_SET, protocol.MESH_OPCODE_READ)):
            payload = protocol.strip_mesh_opcode(payload)

        is_cbor_map = bool(payload and payload[0] >> 5 == 5)
        if is_cbor_map:
            try:
                cbor = protocol.decode_cbor_map(payload)
            except ValueError as err:
                _LOGGER.debug("Ignoring unsupported Fluval CBOR packet", exc_info=err)
                return

            if cbor is not None:
                self._decode_cbor_update(cbor)
            return

        if len(payload) < 13:
            _LOGGER.debug("Ignoring short Fluval update packet: %s", payload.hex())
            return
        if payload[0] != 0x68:
            _LOGGER.debug("Ignoring non-state Fluval packet: %s", payload.hex())
            return

        if payload[2] == 0x00:
            self.values["mode"] = MODES[0]
        elif payload[2] == 0x01:
            self.values["mode"] = MODES[1]
        elif payload[2] == 0x02:
            self.values["mode"] = MODES[2]

        self.values["led_on_off"] = payload[3] > 0x00

        if self.values["mode"] == "manual":
            # Wire scale is 0–1000 (percent * 10); HA entities use 0–100.
            channels = [
                ((payload[6] << 8) | (payload[5] & 0xFF)),
                ((payload[8] << 8) | (payload[7] & 0xFF)),
                ((payload[10] << 8) | (payload[9] & 0xFF)),
                ((payload[12] << 8) | (payload[11] & 0xFF)),
            ]
            if len(payload) > 14:
                channels.append((payload[14] << 8) | (payload[13] & 0xFF))
            self._channel_count_hint = 5 if len(channels) >= 5 else 4
            for index, raw in enumerate(channels):
                self.values[f"channel_{index + 1}"] = max(0, min(100, round(raw / 10)))
        else:
            for channel in NUMBERS:
                self.values[channel] = 0

        _LOGGER.debug(
            "led: %s mode: %s channels: %s / %s / %s / %s / %s",
            self.values["led_on_off"],
            self.values["mode"],
            self.values["channel_1"],
            self.values["channel_2"],
            self.values["channel_3"],
            self.values["channel_4"],
            self.values["channel_5"],
        )

        for handler in self.updates_component:
            handler()

    def _decode_cbor_update(self, data: dict[int, Any]):
        """Decode a FACEBD or mesh CBOR state update."""
        mode_key = protocol.WIFI_MODE_KEY if protocol.WIFI_MODE_KEY in data else protocol.MESH_MODE_KEY
        switch_key = protocol.WIFI_SWITCH_KEY if protocol.WIFI_SWITCH_KEY in data else protocol.MESH_SWITCH_KEY
        channel_keys = (
            protocol.WIFI_CHANNEL_KEYS if protocol.WIFI_CHANNEL_KEYS[0] in data else protocol.MESH_CHANNEL_KEYS
        )

        if mode_key in data:
            mode = data[mode_key]
            if isinstance(mode, int) and 0 <= mode < len(MODES):
                self.values["mode"] = MODES[mode]

        if switch_key in data:
            self.values["led_on_off"] = bool(data[switch_key])

        present = 0
        for channel, key in zip(NUMBERS, channel_keys, strict=False):
            if key in data and isinstance(data[key], int):
                raw = int(data[key])
                # Some mesh firmwares use 0–1000; normalize to percent.
                value = round(raw / 10) if raw > 100 else raw
                self.values[channel] = max(0, min(100, value))
                present += 1
        if present:
            self._channel_count_hint = 5 if present >= 5 else 4

        for handler in self.updates_component:
            handler()
