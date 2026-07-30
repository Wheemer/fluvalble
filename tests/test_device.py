"""Tests for Fluval device schedule and channel behavior."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from custom_components.fluvalble.core import LAMP_PROFILE_PLANT
from custom_components.fluvalble.core import encryption, protocol
from custom_components.fluvalble.core.device import (
    AQUASKY_NUMBERS,
    CHANNEL_NAMES_PLANT,
    Device,
    NUMBERS,
    WEATHER_EFFECTS,
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


def test_device_honors_configured_wire_dialect():
    device = _make_device(wire_dialect=encryption.DIALECT_XOR_0E)

    assert device.wire_dialect == encryption.DIALECT_XOR_0E
    client = device._make_client(MagicMock(address=device.address))
    assert client.wire_dialect == encryption.DIALECT_XOR_0E


def test_device_defaults_unknown_wire_dialect_to_apk_random():
    device = _make_device(wire_dialect="not-a-dialect")

    assert device.wire_dialect == encryption.DIALECT_RANDOM


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


def test_plant_rgb_commanded_colour_sticks_in_preview():
    device = _make_device(
        name="Fish Tank",
        model="Plant Bluetooth LED",
        lamp_profile=LAMP_PROFILE_PLANT,
    )
    channels = device.channels_from_rgb((255, 40, 40), 255)
    device.values.update(channels)
    device.values["led_on_off"] = True
    device.remember_commanded_light(rgb=(255, 40, 40), brightness=255)

    assert device.light_rgb_255() == (255, 40, 40)
    assert channels["channel_1"] > channels["channel_2"]


def test_plant_colour_uses_only_6804_when_already_manual_and_on():
    asyncio.run(_async_test_plant_colour_uses_only_6804_when_already_manual_and_on())


async def _async_test_plant_colour_uses_only_6804_when_already_manual_and_on():
    device = _make_device(
        name="Fish Tank",
        model="Plant Bluetooth LED",
        lamp_profile=LAMP_PROFILE_PLANT,
    )
    device.values["mode"] = "manual"
    device.values["led_on_off"] = True
    device._async_prepare_command = AsyncMock(return_value=True)
    device._async_send_packets = AsyncMock(return_value=True)

    assert await device.async_apply_light_channels(device.channels_from_rgb((255, 0, 0), 255))

    packets = device._async_send_packets.await_args.args[0]
    assert len(packets) == 1
    assert packets[0][0:2] == bytes((0x68, 0x04))


def test_plant_colour_prepares_state_only_when_needed():
    asyncio.run(_async_test_plant_colour_prepares_state_only_when_needed())


async def _async_test_plant_colour_prepares_state_only_when_needed():
    device = _make_device(
        name="Fish Tank",
        model="Plant Bluetooth LED",
        lamp_profile=LAMP_PROFILE_PLANT,
    )
    device.values["mode"] = "automatic"
    device.values["led_on_off"] = False
    device._async_prepare_command = AsyncMock(return_value=True)
    device._async_send_packets = AsyncMock(return_value=True)

    assert await device.async_apply_light_channels(device.channels_from_rgb((0, 0, 255), 255))

    packets = device._async_send_packets.await_args.args[0]
    assert [packet[0:2] for packet in packets] == [
        bytes((0x68, 0x02)),
        bytes((0x68, 0x03)),
        bytes((0x68, 0x04)),
    ]


def test_native_weather_effect_uses_apk_680a_packet():
    asyncio.run(_async_test_native_weather_effect())


async def _async_test_native_weather_effect():
    device = _make_device(name="AquaSky2.0_Test", model="AquaSky 2.0 Bluetooth LED")
    device.values["mode"] = "manual"
    device.values["led_on_off"] = False
    device._async_prepare_command = AsyncMock(return_value=True)
    device._async_send_packets = AsyncMock(return_value=True)

    assert await device.async_set_effect("Lightning")

    packets = device._async_send_packets.await_args.args[0]
    assert packets == [
        protocol.old_switch_packet(True),
        protocol.old_weather_effect_packet(2),
    ]
    assert device.values["effect"] == "Lightning"
    assert device.values["led_on_off"] is True


def test_aquasky_0103_keeps_all_apk_native_effects_available():
    device = _make_device(name="AquaSky2.0_Test", model="AquaSky 2.0 Bluetooth LED")
    device.product_id = 0x0103

    assert device.effect_list() == ["None", *WEATHER_EFFECTS]


def test_product_0103_channel_hint_overrides_plant_profile():
    device = _make_device(
        name="Fish Fluval LED",
        model="Bluetooth LED",
        lamp_profile=LAMP_PROFILE_PLANT,
    )
    device.product_id = 0x0103
    device._channel_count_hint = protocol.channel_count_for_product_id(device.product_id)

    assert device.numbers() == AQUASKY_NUMBERS
    assert device.light_mode() == "rgbw"


def test_stopping_effect_restores_previous_static_channels():
    asyncio.run(_async_test_stopping_effect_restores_previous_static_channels())


async def _async_test_stopping_effect_restores_previous_static_channels():
    device = _make_device(name="AquaSky2.0_Test", model="AquaSky 2.0 Bluetooth LED")
    original = {"channel_1": 100, "channel_2": 90, "channel_3": 20, "channel_4": 0}
    device.values.update(original)
    device.values["led_on_off"] = True
    device._effect_restore_channels = dict(original)
    device.values.update({"channel_1": 10, "channel_2": 100, "channel_3": 10})
    device.values["effect"] = "Full moon"
    device._async_prepare_command = AsyncMock(return_value=True)
    device._async_send_packets = AsyncMock(return_value=True)

    assert await device.async_stop_effect()

    packets = device._async_send_packets.await_args.args[0]
    assert packets == [protocol.old_all_zone_packet([100, 90, 20, 0])]
    assert device.values["effect"] is None


def test_effect_active_off_sends_only_apk_switch_packet():
    asyncio.run(_async_test_effect_active_off_sends_only_apk_switch_packet())


async def _async_test_effect_active_off_sends_only_apk_switch_packet():
    device = _make_device(name="AquaSky2.0_Test", model="AquaSky 2.0 Bluetooth LED")
    restore = {"channel_1": 10, "channel_2": 20, "channel_3": 30, "channel_4": 40}
    device.values.update(restore)
    device.values["led_on_off"] = True
    device.values["effect"] = "Lightning"
    device._effect_restore_channels = dict(restore)
    device._async_prepare_command = AsyncMock(return_value=True)
    device._async_send_packets = AsyncMock(return_value=True)

    assert await device.async_fade_off()

    packets = device._async_send_packets.await_args.args[0]
    assert packets == [protocol.old_switch_packet(False)]
    assert device.values["led_on_off"] is False
    assert device.values["effect"] is None
    assert device.channels_before_off() == restore


def test_classic_off_fades_channels_proportionally_to_zero_before_power_off():
    asyncio.run(_async_test_classic_off_fade())


async def _async_test_classic_off_fade():
    device = _make_device(name="AquaSky2.0_Test", model="AquaSky 2.0 Bluetooth LED")
    original = {
        "channel_1": 100,
        "channel_2": 91,
        "channel_3": 23,
        "channel_4": 0,
    }
    device.values.update(original)
    device.values["led_on_off"] = True
    device._async_prepare_command = AsyncMock(return_value=True)
    device._async_send_packets = AsyncMock(return_value=True)

    assert await device.async_fade_off()

    packets = device._async_send_packets.await_args.args[0]
    assert packets == [
        protocol.old_all_zone_packet([67, 61, 15, 0]),
        protocol.old_all_zone_packet([33, 30, 8, 0]),
        protocol.old_all_zone_packet([0, 0, 0, 0]),
        protocol.old_switch_packet(False),
    ]
    assert device.values["led_on_off"] is False
    assert device.channels_before_off() == original

    device._async_send_packets.reset_mock()
    assert await device.async_apply_light_channels(device.channels_before_off())
    restore_packets = device._async_send_packets.await_args.args[0]
    assert [packet[0:2] for packet in restore_packets] == [
        bytes((0x68, 0x03)),
        bytes((0x68, 0x04)),
    ]
    assert device.channels_before_off() is None


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
            "led_on_off": True,
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
    assert device.is_reachable() is False
    assert device.attribute("connection")["extra"]["gatt_connected"] is True


def test_reachability_refresh_notifies_connect_handlers_when_last_seen_expires():
    from datetime import UTC, datetime, timedelta
    from unittest.mock import MagicMock

    from custom_components.fluvalble.core.device import REACHABLE_SECONDS

    device = _make_device()
    handler = MagicMock()
    device.register_update("connection", handler)
    device.connected = False
    device.conn_info["last_seen"] = datetime.now(UTC) - timedelta(seconds=REACHABLE_SECONDS + 10)

    device._refresh_reachability_entities()

    handler.assert_called_once()
    assert device.attribute("connection")["is_on"] is False
