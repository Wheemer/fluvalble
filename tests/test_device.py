"""Tests for Fluval device schedule and channel behavior."""

import asyncio
from unittest.mock import AsyncMock

from custom_components.fluvalble.core import LAMP_PROFILE_PLANT
from custom_components.fluvalble.core.device import (
    AQUASKY_NUMBERS,
    CHANNEL_NAMES_PLANT,
    Device,
    NUMBERS,
)


def _make_device(name="AquaSky3.0_Test", model="AquaSky Bluetooth LED", **config):
    return Device(
        name,
        config_data={
            "mac": "AA:BB:CC:DD:EE:FF",
            "model": model,
            **config,
        },
    )


def test_initial_values_include_all_channels():
    device = _make_device()

    assert device.connected is False
    for channel in NUMBERS:
        assert device.values[channel] == 0
    assert device.values["mode"] == "manual"
    assert device.values["led_on_off"] is False


def test_aquasky_2_exposes_four_color_channels():
    device = _make_device(name="AquaSky2.0_Test", model="AquaSky 2.0 Bluetooth LED")

    assert device.numbers() == AQUASKY_NUMBERS
    assert device.light_mode() == "rgbw"


def test_aquasky_3_name_exposes_five_channels():
    device = _make_device(name="AquaSky3.0_2F3176", model="AquaSky 3.0 Bluetooth LED")

    assert device.numbers() == NUMBERS


def test_clock_sync_flag_resets_on_disconnect():
    device = _make_device(name="Plant 3.0", model="Plant 3.0 Bluetooth LED")
    device._clock_synced = True
    device.set_connected(False)
    assert device._clock_synced is False


def test_plant_profile_exposes_five_channels_with_plant_labels():
    device = _make_device(
        name="Fish Tank",
        model="Unknown Bluetooth LED",
        lamp_profile=LAMP_PROFILE_PLANT,
    )

    assert device.numbers() == NUMBERS
    assert device.entity_name("channel_1") == CHANNEL_NAMES_PLANT["channel_1"]
    assert device.entity_name("channel_5") == CHANNEL_NAMES_PLANT["channel_5"]
    assert device.light_mode() == "rgb"
    assert device.uses_plant_spectrum() is True


def test_plant_rgb_roundtrip_preview_stays_plausible():
    device = _make_device(
        name="Fish Tank",
        model="Plant Bluetooth LED",
        lamp_profile=LAMP_PROFILE_PLANT,
    )
    channels = device.channels_from_rgb((255, 180, 120), 255)
    device.values.update(channels)
    preview = device.light_rgb_255()

    # Warm daylight → warm preview (R high, B lower), not a fake green swatch.
    assert preview[0] > preview[2]
    assert channels["channel_1"] > 0  # rose contributes
    assert channels["channel_5"] > 0  # warm white contributes


def test_aquasky_uses_rgbw_light_mode():
    device = _make_device()
    assert device.light_mode() == "rgbw"
    channels = device.channels_from_rgbw((255, 0, 0, 128), 255)
    assert channels["channel_1"] == 100
    assert channels["channel_4"] == 50


def test_plant_name_exposes_five_channels():
    device = _make_device(name="Plant 3.0_AABB", model="Plant 3.0 Bluetooth LED")

    assert device.numbers() == NUMBERS
    assert device.entity_name("channel_3") == "Cold White"


def test_old_status_packet_scales_to_percent():
    device = _make_device(name="Plant 3.0", model="Plant 3.0 Bluetooth LED")
    # Manual mode, on, five channels at 10/20/30/40/50% => wire 100/200/...
    packet = bytearray(
        [
            0x68,
            0x18,
            0x00,
            0x01,
            0x00,
            100 & 0xFF,
            100 >> 8,
            200 & 0xFF,
            200 >> 8,
            300 & 0xFF,
            300 >> 8,
            400 & 0xFF,
            400 >> 8,
            500 & 0xFF,
            500 >> 8,
        ]
    )

    device.decode_update_packet(packet)

    assert device.values["channel_1"] == 10
    assert device.values["channel_2"] == 20
    assert device.values["channel_5"] == 50
    assert device._channel_count_hint == 5


def test_schedule_points_are_normalized_from_color_names():
    device = _make_device()

    points = device._normalize_schedule_points(
        [
            {"time": "11:00", "red": 10, "green": 20, "blue": 30, "white": 40},
            {"time": "10:00", "red": 0, "green": 0, "blue": 0, "white": 0},
        ]
    )

    assert [point["time"] for point in points] == ["10:00", "11:00"]
    assert points[1]["channel_1"] == 10
    assert points[1]["channel_4"] == 40


def test_schedule_interpolation_ramps_between_points():
    device = _make_device()
    points = device._normalize_schedule_points(
        [
            {"time": "10:00", "red": 0, "green": 0, "blue": 0, "white": 0},
            {"time": "11:00", "red": 10, "green": 20, "blue": 30, "white": 40},
        ]
    )

    channels = device._interpolate_schedule(points, 10 * 60 + 30)

    assert channels["channel_1"] == 5
    assert channels["channel_2"] == 10
    assert channels["channel_3"] == 15
    assert channels["channel_4"] == 20


def test_set_channels_skips_unchanged_targets_before_ble_connect():
    asyncio.run(_async_test_set_channels_skips_unchanged_targets_before_ble_connect())


async def _async_test_set_channels_skips_unchanged_targets_before_ble_connect():
    device = _make_device()
    device.values.update(
        {
            "channel_1": 10,
            "channel_2": 20,
            "channel_3": 30,
            "channel_4": 40,
        }
    )
    device._async_prepare_command = AsyncMock()

    assert await device.async_set_channels(
        {
            "channel_1": 10,
            "channel_2": 20,
            "channel_3": 30,
            "channel_4": 40,
        }
    )
    device._async_prepare_command.assert_not_called()


def test_set_channels_switches_to_manual_before_write():
    asyncio.run(_async_test_set_channels_switches_to_manual_before_write())


async def _async_test_set_channels_switches_to_manual_before_write():
    device = _make_device()
    device.values["mode"] = "automatic"
    device._async_prepare_command = AsyncMock(return_value=True)
    device._async_send_packet = AsyncMock(return_value=True)
    device._async_send_channel_state = AsyncMock(return_value=True)

    assert await device.async_set_channels({"channel_1": 25})

    assert device.values["mode"] == "manual"
    device._async_send_packet.assert_called_once()
    device._async_send_channel_state.assert_called_once()


def test_connection_attribute_uses_reachability_not_gatt_only():
    from datetime import UTC, datetime, timedelta

    from custom_components.fluvalble.core.device import REACHABLE_SECONDS

    device = _make_device()
    device.connected = False
    device.conn_info["last_seen"] = datetime.now(UTC)
    assert device.is_reachable() is True
    attr = device.attribute("connection")
    assert attr["is_on"] is True
    assert attr["extra"]["gatt_connected"] is False

    device.conn_info["last_seen"] = datetime.now(UTC) - timedelta(seconds=REACHABLE_SECONDS + 10)
    assert device.is_reachable() is False
    assert device.attribute("connection")["is_on"] is False

    device.connected = True
    assert device.is_reachable() is True
