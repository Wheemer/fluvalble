"""Light platform: real HA light with Plant RGB / AquaSky RGBW translation."""

from __future__ import annotations

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    ATTR_RGBW_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .core.device import EFFECT_NONE, Device
from .core.entity import FluvalEntity

PARALLEL_UPDATES = 0

# Default “daylight” looks when turning on a lamp with no prior channel mix.
_DEFAULT_PLANT_RGB = (170, 210, 255)
_DEFAULT_AQUASKY_RGBW = (0, 0, 0, 255)


def create_entities(device: Device) -> list:
    """Build the entity list for this platform."""
    return [FluvalLight(device, "light")]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    add_entities: AddEntitiesCallback,
) -> None:
    """Set up Fluval light from a config entry."""
    del hass
    add_entities(create_entities(config_entry.runtime_data.device))


class FluvalLight(FluvalEntity, LightEntity):
    """Real Home Assistant light for Fluval lamps.

    Plant/Marine use ColorMode.RGB. The entity remembers the last commanded
    colour so the HA colour wheel does not snap after the lossy 5-channel
    Plant spectrum round-trip. AquaSky uses ColorMode.RGBW.

    The entity stays available while the device is known even if the GATT link
    is idle (active_time disconnect). Commands reconnect on demand.
    """

    _attr_icon = "mdi:led-strip-variant"
    _attr_name = "Light"

    def __init__(self, device: Device, attr: str) -> None:
        super().__init__(device, attr)
        self._attr_effect_list = device.effect_list()
        self._attr_supported_features = LightEntityFeature.EFFECT
        if device.light_mode() == "rgb":
            self._attr_supported_color_modes = {ColorMode.RGB}
            self._attr_color_mode = ColorMode.RGB
        else:
            self._attr_supported_color_modes = {ColorMode.RGBW}
            self._attr_color_mode = ColorMode.RGBW

    def internal_update(self) -> None:
        # Stay available when idle-disconnected so the UI isn't grayed out.
        self._attr_available = True
        self._attr_effect_list = self.device.effect_list()
        # Follow LED power — Automatic/Professional zero channel values in the
        # status packet, so brightness must not gate is_on.
        self._attr_is_on = bool(self.device.values.get("led_on_off"))
        if not self._attr_is_on:
            self._attr_brightness = None
            self._attr_rgb_color = None
            self._attr_rgbw_color = None
            self._attr_effect = None
            if self.hass:
                self._async_write_ha_state()
            return

        self._attr_brightness = self.device.light_brightness_255() or None
        self._attr_effect = self.device.values.get("effect")

        if self.device.light_mode() == "rgb":
            self._attr_color_mode = ColorMode.RGB
            self._attr_supported_color_modes = {ColorMode.RGB}
            self._attr_rgb_color = self.device.light_rgb_255()
            self._attr_rgbw_color = None
        else:
            self._attr_color_mode = ColorMode.RGBW
            self._attr_supported_color_modes = {ColorMode.RGBW}
            self._attr_rgbw_color = self.device.light_rgbw_255()
            self._attr_rgb_color = None

        if self.hass:
            self._async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        """Turn on and apply colour / brightness."""
        from homeassistant.exceptions import HomeAssistantError

        brightness = max(1, min(255, int(kwargs.get(ATTR_BRIGHTNESS, self._attr_brightness or 255))))
        requested_effect = kwargs.get(ATTR_EFFECT)
        if requested_effect and requested_effect != EFFECT_NONE:
            if not await self.device.async_set_effect(str(requested_effect)):
                raise HomeAssistantError(self.device.command_error_message())
            self.internal_update()
            return
        if requested_effect == EFFECT_NONE:
            if not await self.device.async_stop_effect():
                raise HomeAssistantError(self.device.command_error_message())
            self.internal_update()
            return

        saved_channels = self.device.channels_before_off()
        no_colour = ATTR_RGB_COLOR not in kwargs and ATTR_RGBW_COLOR not in kwargs
        if saved_channels is not None and no_colour and not self.device.values.get("led_on_off"):
            if ATTR_BRIGHTNESS in kwargs:
                current_max = max(saved_channels.values(), default=0)
                target_max = round(brightness / 255 * 100)
                if current_max > 0:
                    saved_channels = {
                        channel: round(value * target_max / current_max) for channel, value in saved_channels.items()
                    }
            if not await self.device.async_apply_light_channels(saved_channels):
                raise HomeAssistantError(self.device.command_error_message())
            if self.device.light_mode() == "rgbw":
                self.device.remember_commanded_light(
                    rgbw=self.device.rgbw_from_channels_255(saved_channels),
                    brightness=brightness,
                )
            else:
                self.device.remember_commanded_light(brightness=brightness)
            self.internal_update()
            return

        if ATTR_BRIGHTNESS in kwargs and ATTR_RGB_COLOR not in kwargs and ATTR_RGBW_COLOR not in kwargs:
            if not await self._async_brightness_only(brightness):
                raise HomeAssistantError(self.device.command_error_message())
            self.device.remember_commanded_light(brightness=brightness)
            self.internal_update()
            return

        channels = self._channels_from_kwargs(kwargs, brightness)
        if channels is None:
            if self.device.master_brightness() > 0 or bool(self.device.values.get("led_on_off")):
                if not await self.device.async_set_switch("led_on_off", True):
                    raise HomeAssistantError(self.device.command_error_message())
                self.device.remember_commanded_light(brightness=brightness)
                self.internal_update()
                return
            channels = (
                self.device.channels_from_rgb(_DEFAULT_PLANT_RGB, brightness)
                if self.device.light_mode() == "rgb"
                else self.device.channels_from_rgbw(_DEFAULT_AQUASKY_RGBW, brightness)
            )
            if self.device.light_mode() == "rgb":
                self.device.remember_commanded_light(rgb=_DEFAULT_PLANT_RGB, brightness=brightness)
            else:
                self.device.remember_commanded_light(rgbw=_DEFAULT_AQUASKY_RGBW, brightness=brightness)

        if ATTR_RGB_COLOR in kwargs:
            self.device.remember_commanded_light(rgb=tuple(kwargs[ATTR_RGB_COLOR]), brightness=brightness)
        elif ATTR_RGBW_COLOR in kwargs:
            self.device.remember_commanded_light(rgbw=tuple(kwargs[ATTR_RGBW_COLOR]), brightness=brightness)

        if not await self.device.async_apply_light_channels(channels):
            raise HomeAssistantError(self.device.command_error_message())
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
        if self.device.values.get("mode") != "manual":
            if not await self.device.async_select_option("mode", "manual"):
                return False
        if not await self.device.async_set_master_brightness(round(brightness / 255 * 100)):
            return False
        if not self.device.values.get("led_on_off"):
            return await self.device.async_set_switch("led_on_off", True)
        return True

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the light off."""
        from homeassistant.exceptions import HomeAssistantError

        if not await self.device.async_fade_off():
            raise HomeAssistantError(self.device.command_error_message())

        self.device.clear_commanded_light()
        self._attr_is_on = False
        self._attr_brightness = None
        self._attr_rgb_color = None
        self._attr_rgbw_color = None
        self._async_write_ha_state()
