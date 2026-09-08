"""Fixture-resident manual preset scenes for classic Fluval lights."""

from __future__ import annotations

from homeassistant.components.scene import Scene
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import require_entry_runtime_data
from .core.device import Device
from .core.entity import FluvalEntity

PARALLEL_UPDATES = 0
MANUAL_PRESET_SLOTS = range(1, 5)


def create_entities(device: Device) -> list:
    """Build the APK-defined P1-P4 scenes for a classic controller."""
    if not device.supports_manual_presets():
        return []
    return [FluvalManualPresetScene(device, slot) for slot in MANUAL_PRESET_SLOTS]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    add_entities: AddEntitiesCallback,
) -> None:
    """Set up fixture-resident manual preset scenes."""
    runtime = require_entry_runtime_data(hass, config_entry)
    device = runtime.device

    if device:
        add_entities(create_entities(device))
    else:
        runtime.pending_add_entities[Platform.SCENE] = add_entities


class FluvalManualPresetScene(FluvalEntity, Scene):
    """Recall one fixture-resident classic P1-P4 preset."""

    _attr_icon = "mdi:palette-swatch"

    def __init__(self, device: Device, slot: int) -> None:
        self.slot = slot
        super().__init__(device, f"manual_preset_{slot}")

    def internal_update(self) -> None:
        """Expose the scene only while its fixture readback can be applied."""
        self._attr_available = (
            self.device.controls_available
            and bool(self.device.values.get("led_on_off"))
            and self.device.manual_preset_available(self.slot)
        )
        if self.hass:
            self._async_write_ha_state()

    async def async_activate(self, **kwargs) -> None:
        """Recall this preset using the existing APK-backed command path."""
        if not await self.device.async_recall_manual_preset(self.slot):
            self.internal_update()
            self._raise_command_error()
        self.internal_update()
