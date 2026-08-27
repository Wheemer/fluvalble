"""Tests for the Home Assistant Fluval light entity."""

import asyncio
from unittest.mock import AsyncMock

from custom_components.fluvalble.core.device import EFFECT_NONE, Device
from custom_components.fluvalble.light import FluvalLight


def _make_light() -> tuple[Device, FluvalLight]:
    device = Device(
        "AquaSky2.0_Test",
        config_data={
            "mac": "AA:BB:CC:DD:EE:FF",
            "model": "AquaSky 2.0 Bluetooth LED",
        },
    )
    return device, FluvalLight(device, "light")


def test_light_exposes_apk_native_effects():
    _device, light = _make_light()

    assert EFFECT_NONE in light._attr_effect_list
    assert "Lightning" in light._attr_effect_list
    assert "Colour cycle" in light._attr_effect_list
    assert "Full moon" in light._attr_effect_list


def test_light_turn_on_routes_effect_to_device():
    asyncio.run(_async_test_light_turn_on_routes_effect_to_device())


async def _async_test_light_turn_on_routes_effect_to_device():
    device, light = _make_light()
    device.async_set_effect = AsyncMock(return_value=True)

    await light.async_turn_on(effect="Full moon")

    device.async_set_effect.assert_awaited_once_with("Full moon")


def test_turn_on_restores_rgbw_state_shown_in_home_assistant():
    asyncio.run(_async_test_turn_on_restores_rgbw_state_shown_in_home_assistant())


async def _async_test_turn_on_restores_rgbw_state_shown_in_home_assistant():
    device, light = _make_light()
    restored = {
        "channel_1": 13,
        "channel_2": 100,
        "channel_3": 14,
        "channel_4": 0,
    }
    device._off_restore_channels = dict(restored)
    device.async_apply_light_channels = AsyncMock(return_value=True)

    await light.async_turn_on()

    device.async_apply_light_channels.assert_awaited_once_with(restored)
    assert device._commanded_rgbw == (33, 255, 36, 0)

    # A stale zero-channel status packet must not make HA show black after the
    # restored green mix was successfully sent to the physical fixture.
    device.values.update(
        {
            "channel_1": 0,
            "channel_2": 0,
            "channel_3": 0,
            "channel_4": 0,
            "led_on_off": True,
        }
    )
    light.internal_update()

    assert light._attr_rgbw_color == (33, 255, 36, 0)
