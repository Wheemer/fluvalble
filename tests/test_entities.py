"""Tests for Home Assistant entity platform glue."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.light import ATTR_BRIGHTNESS

from custom_components.fluvalble import binary_sensor, button, light, select, sensor
from custom_components.fluvalble.core.device import Device


def _make_device():
    now = datetime.now(UTC)
    device = Device(
        "AquaSky3.0_Test",
        config_data={
            "mac": "AA:BB:CC:DD:EE:FF",
            "model": "AquaSky Bluetooth LED",
        },
    )
    device.connected = True
    device.conn_info["rssi"] = -70
    device.conn_info["last_seen"] = now
    device.diagnostics["status"] = "ok"
    device.values.update(
        {
            "channel_1": 10,
            "channel_2": 20,
            "channel_3": 30,
            "channel_4": 40,
            "led_on_off": True,
            "mode": "manual",
        }
    )
    return device


def test_create_entities_for_platforms():
    device = _make_device()

    assert len(select.create_entities(device)) == 1
    assert len(sensor.create_entities(device)) == 2
    assert len(button.create_entities(device)) == 1
    assert len(binary_sensor.create_entities(device)) == 1
    assert len(light.create_entities(device)) == 1


def test_select_internal_update_and_select_option():
    asyncio.run(_async_test_select_internal_update_and_select_option())


async def _async_test_select_internal_update_and_select_option():
    device = _make_device()
    entity = select.FluvalSelect(device, "mode")
    device.async_select_option = AsyncMock(return_value=True)

    entity.internal_update()
    await entity.async_select_option("automatic")

    assert "manual" in entity._attr_options
    assert entity._attr_current_option == "automatic"
    device.async_select_option.assert_awaited_once_with("mode", "automatic")


def test_diagnostic_entities_update_from_device_attributes():
    device = _make_device()

    connection = binary_sensor.FluvalSensor(device, "connection")
    rssi = sensor.FluvalSensor(device, "rssi")
    last_seen = sensor.FluvalSensor(device, "last_seen")

    connection.internal_update()
    rssi.internal_update()
    last_seen.internal_update()

    assert connection._attr_is_on is True
    assert rssi._attr_native_value == -70
    assert last_seen._attr_native_value == device.conn_info["last_seen"]


def test_sync_clock_button_presses_device_clock_sync():
    asyncio.run(_async_test_sync_clock_button_presses_device_clock_sync())


async def _async_test_sync_clock_button_presses_device_clock_sync():
    device = _make_device()
    device.async_sync_clock = AsyncMock(return_value=True)
    entity = button.FluvalSyncClockButton(device, "sync_clock")

    await entity.async_press()

    device.async_sync_clock.assert_awaited_once_with(force=True)


def test_light_internal_update_and_actions():
    asyncio.run(_async_test_light_internal_update_and_actions())


async def _async_test_light_internal_update_and_actions():
    device = _make_device()
    entity = light.FluvalLight(device, "light")
    device.async_set_master_brightness = AsyncMock(return_value=True)
    device.async_set_switch = AsyncMock(return_value=True)
    device.async_fade_off = AsyncMock(return_value=True)
    device.values["led_on_off"] = False

    entity.internal_update()
    await entity.async_turn_on(**{ATTR_BRIGHTNESS: 128})
    await entity.async_turn_off()

    assert entity._attr_is_on is False
    device.async_set_master_brightness.assert_awaited_once()
    assert device.async_set_switch.await_args_list[0].args == ("led_on_off", True)
    device.async_fade_off.assert_awaited_once()


def test_entity_unregisters_update_handler():
    device = _make_device()
    device.deregister_update = MagicMock()
    entity = select.FluvalSelect(device, "mode")

    asyncio.run(entity.async_will_remove_from_hass())

    device.deregister_update.assert_called_once_with("mode", entity._update_handler)


def test_controls_remain_available_when_recently_seen_but_not_connected():
    device = _make_device()
    device.connected = False
    device.client = None
    device.conn_info["last_seen"] = datetime(2026, 1, 1, tzinfo=UTC)

    select_entity = select.FluvalSelect(device, "mode")
    light_entity = light.FluvalLight(device, "light")

    assert select_entity._attr_available is True
    assert light_entity._attr_available is True


def test_connection_changes_refresh_control_entities():
    device = _make_device()
    device.connected = False
    sensor.FluvalSensor(device, "rssi")
    handler = MagicMock()
    device.updates_connect.append(handler)

    device.set_connected(True)

    handler.assert_called_once()
