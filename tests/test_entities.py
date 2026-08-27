"""Tests for Home Assistant entity platform glue."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.light import ATTR_BRIGHTNESS

from custom_components.fluvalble import (
    _cleanup_duplicate_devices,
    _migrate_legacy_registry_entries,
    binary_sensor,
    button,
    diagnostics,
    light,
    select,
    sensor,
)
from custom_components.fluvalble.core import DOMAIN
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
    device.conn_info["rssi_updated_at"] = now
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
    assert rssi._attr_state_class.value == "measurement"
    assert rssi._attr_extra_state_attributes["last_advertisement"] == device.conn_info["rssi_updated_at"]
    assert last_seen._attr_native_value == device.conn_info["last_seen"]


def test_downloadable_diagnostics_redact_identifiers_but_keep_protocol_fields():
    report = diagnostics._redact_diagnostics(
        {
            "configured_mac": "AA:BB:CC:DD:EE:FF",
            "name": "PlantPro_AABBCC",
            "connection_info": {
                "mac": "AA:BB:CC:DD:EE:FF",
                "service_uuids": ["0000fff0-0000-1000-8000-00805f9b34fb"],
                "manufacturer_data": {"12592": "secret"},
            },
            "product_id": 259,
            "channel_count": 4,
        }
    )

    assert report["configured_mac"] == diagnostics.REDACTED
    assert report["name"] == diagnostics.REDACTED
    assert report["connection_info"]["mac"] == diagnostics.REDACTED
    assert report["connection_info"]["manufacturer_data"] == diagnostics.REDACTED
    assert report["connection_info"]["service_uuids"] == ["0000fff0-0000-1000-8000-00805f9b34fb"]
    assert report["product_id"] == 259
    assert report["channel_count"] == 4


def test_duplicate_device_registry_entries_are_merged_safely(monkeypatch):
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    canonical = SimpleNamespace(
        id="canonical",
        identifiers={(DOMAIN, "aa:bb:cc:dd:ee:ff")},
        connections=set(),
    )
    duplicate = SimpleNamespace(id="duplicate", identifiers={(DOMAIN, "legacy")}, connections=set())
    own_entity = SimpleNamespace(
        entity_id="sensor.legacy_signal",
        device_id="duplicate",
        config_entry_id="entry-id",
    )
    device_registry = SimpleNamespace(async_remove_device=MagicMock())
    entity_registry = SimpleNamespace(
        entities={own_entity.entity_id: own_entity},
        async_update_entity=MagicMock(),
    )
    monkeypatch.setattr(dr, "async_get", lambda hass: device_registry, raising=False)
    monkeypatch.setattr(
        dr,
        "async_entries_for_config_entry",
        lambda registry, entry_id: [canonical, duplicate],
        raising=False,
    )
    monkeypatch.setattr(er, "async_get", lambda hass: entity_registry, raising=False)
    monkeypatch.setattr(
        er,
        "async_entries_for_config_entry",
        lambda registry, entry_id: [own_entity],
        raising=False,
    )

    _cleanup_duplicate_devices(
        MagicMock(),
        SimpleNamespace(entry_id="entry-id"),
        "AA:BB:CC:DD:EE:FF",
    )

    entity_registry.async_update_entity.assert_called_once_with(
        "sensor.legacy_signal",
        device_id="canonical",
    )
    device_registry.async_remove_device.assert_called_once_with("duplicate")


def test_retired_switch_number_and_diagnostic_entities_are_removed(monkeypatch):
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    entries = [
        SimpleNamespace(entity_id="switch.fluval_led", unique_id="AABBCCDDEEFF_led_on_off"),
        SimpleNamespace(entity_id="number.fluval_red", unique_id="AABBCCDDEEFF_channel_1"),
        SimpleNamespace(entity_id="sensor.fluval_diagnostics", unique_id="AABBCCDDEEFF_diagnostics"),
        SimpleNamespace(entity_id="light.fluval_light", unique_id="AABBCCDDEEFF_light"),
        SimpleNamespace(entity_id="sensor.fluval_signal", unique_id="AABBCCDDEEFF_rssi"),
    ]
    entity_registry = SimpleNamespace(async_remove=MagicMock())
    device_registry = SimpleNamespace(async_update_device=MagicMock())
    device_entry = SimpleNamespace(id="device-id", serial_number="AA:BB:CC:DD:EE:FF")

    monkeypatch.setattr(er, "async_get", lambda hass: entity_registry, raising=False)
    monkeypatch.setattr(
        er,
        "async_entries_for_config_entry",
        lambda registry, entry_id: entries,
        raising=False,
    )
    monkeypatch.setattr(dr, "async_get", lambda hass: device_registry, raising=False)
    monkeypatch.setattr(
        dr,
        "async_entries_for_config_entry",
        lambda registry, entry_id: [device_entry],
        raising=False,
    )

    _migrate_legacy_registry_entries(
        MagicMock(),
        SimpleNamespace(entry_id="entry-id"),
        "AA:BB:CC:DD:EE:FF",
    )

    assert [call.args[0] for call in entity_registry.async_remove.call_args_list] == [
        "switch.fluval_led",
        "number.fluval_red",
        "sensor.fluval_diagnostics",
    ]
    device_registry.async_update_device.assert_called_once_with("device-id", serial_number=None)


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
