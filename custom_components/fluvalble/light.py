"""Light platform: real HA light with proper channel ↔ color translation."""

from __future__ import annotations

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_RGB_COLOR,
    ATTR_RGBW_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .core import DOMAIN
from .core.device import Device
from .core.entity import FluvalEntity

PARALLEL_UPDATES = 0

# Default “daylight” looks when turning on a lamp with no prior channel mix.
_DEFAULT_PLANT_RGB = (170, 210, 255)
_DEFAULT_AQUASKY_RGBW = (0, 0, 0, 255)


def create_entities(device: Device) -> list:
    """Build the entity list for this platform."""
    return [FluvalLight(device, "light")]


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, add_entities: AddEntitiesCallback) -> None:
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    device = entry_data["device"]

    if device:
        add_entities(create_entities(device))
    else:
        entry_data["pending_add_entities"][Platform.LIGHT] = add_entities


class FluvalLight(FluvalEntity, LightEntity):
    """Real Home Assistant light for Fluval lamps.

    Plant/Marine use ColorMode.RGB with a bidirectional translator so the
    colour preview matches the Rose/Blue/CW/PW/WW mix. AquaSky uses ColorMode.RGBW.
    """

    _attr_icon = "mdi:led-strip-variant"
    _attr_name = "Light"

    def __init__(self, device: Device, attr: str) -> None:
        super().__init__(device, attr)
        if device.light_mode() == "rgb":
            self._attr_supported_color_modes = {ColorMode.RGB}
            self._attr_color_mode = ColorMode.RGB
        else:
            self._attr_supported_color_modes = {ColorMode.RGBW}
            self._attr_color_mode = ColorMode.RGBW

    def internal_update(self) -> None:
        self._attr_available = self.device.connected
        self._attr_is_on = bool(self.device.values.get("led_on_off")) and self.device.master_brightness() > 0
        self._attr_brightness = self.device.light_brightness_255() or None

        if self.device.light_mode() == "rgb":
            self._attr_color_mode = ColorMode.RGB
            self._attr_rgb_color = self.device.light_rgb_255()
            self._attr_rgbw_color = None
        else:
            self._attr_color_mode = ColorMode.RGBW
            self._attr_rgbw_color = self.device.light_rgbw_255()
            self._attr_rgb_color = None

        if self.hass:
            self._async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        """Turn on and apply colour / brightness."""
        brightness = max(1, min(255, int(kwargs.get(ATTR_BRIGHTNESS, self._attr_brightness or 255))))

        if ATTR_BRIGHTNESS in kwargs and ATTR_RGB_COLOR not in kwargs and ATTR_RGBW_COLOR not in kwargs:
            await self._async_brightness_only(brightness)
            self.internal_update()
            return

        channels = self._channels_from_kwargs(kwargs, brightness)
        if channels is None:
            if self.device.master_brightness() > 0:
                if not await self.device.async_set_switch("led_on_off", True):
                    self.internal_update()
                else:
                    self.internal_update()
                return
            channels = (
                self.device.channels_from_rgb(_DEFAULT_PLANT_RGB, brightness)
                if self.device.light_mode() == "rgb"
                else self.device.channels_from_rgbw(_DEFAULT_AQUASKY_RGBW, brightness)
            )

        if not await self.device.async_apply_light_channels(channels):
            self.internal_update()
            return
        self.internal_update()

    def _channels_from_kwargs(self, kwargs: dict, brightness: int) -> dict[str, int] | None:
        """Build channel percents from light turn_on kwargs, or None if absent."""
        if self.device.light_mode() == "rgb":
            if ATTR_RGB_COLOR in kwargs:
                return self.device.channels_from_rgb(kwargs[ATTR_RGB_COLOR], brightness)
            return None

        if ATTR_RGBW_COLOR in kwargs:
            return self.device.channels_from_rgbw(kwargs[ATTR_RGBW_COLOR], brightness)
        if ATTR_RGB_COLOR in kwargs:
            r, g, b = kwargs[ATTR_RGB_COLOR]
            return self.device.channels_from_rgbw((r, g, b, 0), brightness)
        return None

    async def _async_brightness_only(self, brightness: int) -> bool:
        """Scale the current mix, ensuring the LED is on."""
        if not await self.device.async_set_master_brightness(round(brightness / 255 * 100)):
            return False
        if not self.device.values.get("led_on_off"):
            return await self.device.async_set_switch("led_on_off", True)
        return True

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the light off."""
        if not await self.device.async_set_switch("led_on_off", False):
            self.internal_update()
            return

        self._attr_is_on = False
        self._async_write_ha_state()
