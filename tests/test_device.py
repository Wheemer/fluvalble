"""Tests for Fluval device schedule and channel behavior."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.fluvalble.core import (
    LAMP_PROFILE_AQUASKY,
    LAMP_PROFILE_AQUASKY3,
    LAMP_PROFILE_PLANT,
    LAMP_PROFILE_PLANT_PRO,
)
from custom_components.fluvalble.core import encryption, protocol
from custom_components.fluvalble.core.device import (
    AQUASKY_NUMBERS,
    CHANNEL_NAMES_PLANT,
    CHANNEL_NAMES_PLANT_PRO,
    Device,
    EFFECT_NONE,
    NUMBERS,
    WEATHER_EFFECTS,
)
from custom_components.fluvalble.core.effects import effect_id, effect_list, mesh_effect_id, mesh_effect_list


def _make_device(name="AquaSky3.0_Test", model="AquaSky Bluetooth LED", **config):
    return Device(
        name,
        config_data={
            "mac": "AA:BB:CC:DD:EE:FF",
            "model": model,
            **config,
        },
    )


def _mesh_client():
    return SimpleNamespace(raw_mesh=True, command_write_uuid="0000fff2-0000-1000-8000-00805f9b34fb")


def _facebd_client():
    return SimpleNamespace(
        raw_facebd=True,
        raw_mesh=False,
        command_write_uuid="facebd03-7261-6262-6974-696f74626c65",
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


def test_classic_manufacturer_data_is_not_facebd_protocol_evidence():
    device = _make_device(
        name="AquaSky2.0_Test",
        model="AquaSky 2.0 Bluetooth LED",
        service_uuids=["00001000-0000-1000-8000-00805f9b34fb"],
        manufacturer_data={"12592": "3438303130330000000000000000000000000000"},
    )

    assert device.product_id == 0x0103
    assert device.facebd is False
    assert device.numbers() == AQUASKY_NUMBERS


def test_facebd_service_uuid_selects_facebd_protocol():
    device = _make_device(
        service_uuids=["facebd00-7261-6262-6974-696f74626c65"],
        manufacturer_data={},
    )

    assert device.facebd is True


def test_update_ble_keeps_mac_uppercase():
    device = _make_device()
    ble_device = MagicMock(address="aa:bb:cc:dd:ee:ff", name="AquaSky2.0_Test")
    advertisement = MagicMock(
        rssi=-60,
        service_uuids=["00001000-0000-1000-8000-00805f9b34fb"],
        service_data={},
        manufacturer_data={12592: bytes.fromhex("3438303130330000000000000000000000000000")},
    )

    device.update_ble(ble_device, advertisement)

    assert device.address == "AA:BB:CC:DD:EE:FF"
    assert device.conn_info["mac"] == "AA:BB:CC:DD:EE:FF"


def test_aquasky_3_name_exposes_four_rgbw_channels():
    device = _make_device(name="AquaSky3.0_2F3176", model="AquaSky 3.0 Bluetooth LED")

    assert device.numbers() == AQUASKY_NUMBERS


def test_aquasky_3_profile_exposes_four_rgbw_channels():
    device = _make_device(lamp_profile=LAMP_PROFILE_AQUASKY3)

    assert device.numbers() == AQUASKY_NUMBERS


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


def test_plant_pro_profile_exposes_five_channels_with_pro_labels():
    device = _make_device(
        name="PlantPro_AABBCC",
        model="PlantPro_AABBCC",
        lamp_profile=LAMP_PROFILE_PLANT_PRO,
    )

    assert device.numbers() == NUMBERS
    assert device.entity_name("channel_1") == CHANNEL_NAMES_PLANT_PRO["channel_1"]
    assert device.entity_name("channel_5") == CHANNEL_NAMES_PLANT_PRO["channel_5"]
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


def test_classic_weather_effect_catalog_is_stable():
    assert effect_list() == [EFFECT_NONE, *WEATHER_EFFECTS]
    assert effect_id("Lightning") == 2
    assert effect_id("Colour cycle") == 4
    assert effect_id("Full moon") == 9
    assert effect_id("Not a Fluval effect") is None


def test_plant_pro_mesh_weather_effect_catalog_is_stable():
    assert mesh_effect_list() == [EFFECT_NONE, "Sun", "Crescent moon", "Full moon", "Half moon"]
    assert mesh_effect_id("Sun") == 4
    assert mesh_effect_id("Crescent moon") == 3
    assert mesh_effect_id("Full moon") == 1
    assert mesh_effect_id("Half moon") == 2
    assert mesh_effect_id("Lightning") is None


def test_mesh_device_exposes_plant_pro_effect_subset():
    device = _make_device(name="PlantPro_AABBCC", model="PlantPro_AABBCC")
    device.client = _mesh_client()

    assert device.effect_list() == mesh_effect_list()


def test_mesh_native_weather_effect_uses_apk_cbor_packet():
    asyncio.run(_async_test_mesh_native_weather_effect())


async def _async_test_mesh_native_weather_effect():
    device = _make_device(name="PlantPro_AABBCC", model="PlantPro_AABBCC")
    device.client = _mesh_client()
    device.values["mode"] = "automatic"
    device.values["led_on_off"] = False
    device._async_prepare_command = AsyncMock(return_value=True)
    device._async_send_packets = AsyncMock(return_value=True)

    assert await device.async_set_effect("Sun")

    packets = device._async_send_packets.await_args.args[0]
    assert packets == [
        protocol.mesh_mode_packet(0),
        protocol.mesh_switch_packet(True),
        protocol.mesh_weather_effect_packet(4),
    ]
    assert device.values["effect"] == "Sun"
    assert device.values["led_on_off"] is True
    assert device.values["mode"] == "manual"


def test_explicit_lamp_profile_overrides_detected_channel_hint():
    device = _make_device(
        name="Fish Fluval LED",
        model="Bluetooth LED",
        lamp_profile=LAMP_PROFILE_PLANT,
    )
    device.product_id = 0x0103
    device._channel_count_hint = protocol.channel_count_for_product_id(device.product_id)

    assert device.numbers() != AQUASKY_NUMBERS
    assert device.light_mode() == "rgb"


def test_aquasky_profile_does_not_decode_trailing_status_bytes_as_channel_five():
    device = _make_device(
        name="AquaSky2.0_Test",
        model="AquaSky 2.0 Bluetooth LED",
        lamp_profile=LAMP_PROFILE_AQUASKY,
    )
    # The fifth word is deliberately non-zero. For an explicitly configured
    # four-channel AquaSky it is trailing packet data, not a physical channel.
    packet = bytearray(
        [
            0x68,
            0x18,
            0x00,
            0x01,
            0x00,
            100,
            0,
            200,
            0,
            44,
            1,
            144,
            1,
            0xE8,
            0x03,
        ]
    )

    device.decode_update_packet(packet)

    assert device.numbers() == AQUASKY_NUMBERS
    assert device.values["channel_1"] == 10
    assert device.values["channel_4"] == 40
    assert device.values["channel_5"] == 0


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


def test_classic_off_sends_only_power_command_without_colour_shift():
    asyncio.run(_async_test_classic_off_without_colour_writes())


async def _async_test_classic_off_without_colour_writes():
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
    assert packets == [protocol.old_switch_packet(False)]
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


def test_connection_attribute_uses_recent_activity_or_live_gatt():
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
    assert device.attribute("connection")["is_on"] is True
    assert device.attribute("connection")["extra"]["gatt_connected"] is True


def test_persistent_connection_retries_after_initial_failure():
    asyncio.run(_async_test_persistent_connection_retries_after_initial_failure())


async def _async_test_persistent_connection_retries_after_initial_failure():
    device = _make_device()
    device._active_time = 0
    device._async_prepare_command = AsyncMock(side_effect=[False, True])
    client = MagicMock()
    device.client = client

    with patch("custom_components.fluvalble.core.device.asyncio.sleep", new=AsyncMock()) as sleep:
        await device.async_start_persistent_connection()

    assert device._async_prepare_command.await_count == 2
    sleep.assert_awaited_once_with(5)
    client.ping.assert_called_once()


def test_start_persistent_connection_schedules_single_task():
    device = _make_device()
    device._active_time = 0
    device.hass = MagicMock()
    connect_coro = object()
    task = MagicMock()
    task.done.return_value = False
    device.hass.async_create_task.return_value = task
    device.async_start_persistent_connection = MagicMock(return_value=connect_coro)

    device.start_persistent_connection()
    device.start_persistent_connection()

    device.hass.async_create_task.assert_called_once_with(connect_coro)
    assert device._persistent_connect_task is task


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


def test_mesh_native_auto_schedule_sends_fixture_schedule_and_auto_mode():
    asyncio.run(_async_test_mesh_native_auto_schedule())


async def _async_test_mesh_native_auto_schedule():
    device = _make_device(name="PlantPro_AABBCC", model="PlantPro_AABBCC")
    device.client = _mesh_client()
    device._async_prepare_command = AsyncMock(return_value=True)
    device._async_send_packets = AsyncMock(return_value=True)

    assert await device.async_set_native_auto_schedule(
        sunrise=(8, 0, 60),
        sunset=(21, 0, 45),
        sleep=(22, 30),
        day_levels=[80, 70, 60, 50, 40],
        night_levels=[0, 10, 0, 0, 0],
    )

    packets = device._async_send_packets.await_args.args[0]
    assert packets == [
        protocol.mesh_auto_schedule_packet(
            sunrise=(8, 0, 60),
            sunset=(21, 0, 45),
            sleep=(22, 30),
            day_levels=[80, 70, 60, 50, 40],
            night_levels=[0, 10, 0, 0, 0],
        ),
        protocol.mesh_mode_packet(1),
    ]
    assert device.values["mode"] == "automatic"


def test_mesh_native_pro_schedule_sends_fixture_schedule_and_professional_mode():
    asyncio.run(_async_test_mesh_native_pro_schedule())


async def _async_test_mesh_native_pro_schedule():
    device = _make_device(name="PlantPro_AABBCC", model="PlantPro_AABBCC")
    device.client = _mesh_client()
    device._async_prepare_command = AsyncMock(return_value=True)
    device._async_send_packets = AsyncMock(return_value=True)

    assert await device.async_set_native_pro_schedule(
        [
            {"time": "08:00", "channel_1": 1, "channel_2": 2, "channel_3": 3, "channel_4": 4, "channel_5": 5},
            {"time": "12:30", "channel_1": 10, "channel_2": 20, "channel_3": 30, "channel_4": 40, "channel_5": 50},
        ]
    )

    packets = device._async_send_packets.await_args.args[0]
    assert packets == [
        protocol.mesh_pro_schedule_packet(
            [
                {
                    "time": "08:00",
                    "minute": 480,
                    "channel_1": 1,
                    "channel_2": 2,
                    "channel_3": 3,
                    "channel_4": 4,
                    "channel_5": 5,
                },
                {
                    "time": "12:30",
                    "minute": 750,
                    "channel_1": 10,
                    "channel_2": 20,
                    "channel_3": 30,
                    "channel_4": 40,
                    "channel_5": 50,
                },
            ]
        ),
        protocol.mesh_mode_packet(2),
    ]
    assert device.values["mode"] == "professional"


def test_facebd_native_schedules_use_apk_cbor_and_four_channels():
    asyncio.run(_async_test_facebd_native_schedules())


async def _async_test_facebd_native_schedules():
    device = _make_device(service_uuids=["facebd00-7261-6262-6974-696f74626c65"])
    device.client = _facebd_client()
    device._async_prepare_command = AsyncMock(return_value=True)
    device._async_send_packets = AsyncMock(return_value=True)

    assert await device.async_set_native_auto_schedule(
        sunrise=(8, 0, 60),
        sunset=(21, 0, 45),
        sleep=(22, 30),
        day_levels=[80, 70, 60, 50, 40],
        night_levels=[0, 10, 0, 0, 99],
    )
    auto_packets = device._async_send_packets.await_args.args[0]
    assert protocol.decode_cbor_map(auto_packets[0]) == {
        114: [480, 540],
        115: [1215, 1260],
        116: 1350,
        117: bytes([80, 70, 60, 50]),
        118: bytes([0, 10, 0, 0]),
    }
    assert auto_packets[1] == protocol.wifi_mode_packet(1)

    device._async_send_packets.reset_mock()
    assert await device.async_set_native_pro_schedule(
        [{"time": "08:00", "channel_1": 1, "channel_2": 2, "channel_3": 3, "channel_4": 4, "channel_5": 99}]
    )
    pro_packets = device._async_send_packets.await_args.args[0]
    assert protocol.decode_cbor_map(pro_packets[0]) == {120: 1, 121: [480], 122: bytes([1, 2, 3, 4])}
    assert pro_packets[1] == protocol.wifi_mode_packet(2)


def test_classic_native_schedules_use_apk_commands():
    asyncio.run(_async_test_classic_native_schedules())


async def _async_test_classic_native_schedules():
    device = _make_device(name="AquaSky2.0_Test", model="AquaSky 2.0 Bluetooth LED")
    device.client = SimpleNamespace(
        raw_facebd=False,
        raw_mesh=False,
        command_write_uuid="00001001-0000-1000-8000-00805f9b34fb",
    )
    device._async_prepare_command = AsyncMock(return_value=True)
    device._async_send_packets = AsyncMock(return_value=True)

    assert await device.async_set_native_auto_schedule(
        sunrise=(8, 0, 60),
        sunset=(21, 0, 45),
        sleep=None,
        day_levels=[80, 70, 60, 50],
        night_levels=[0, 10, 0, 0],
    )
    auto_packets = device._async_send_packets.await_args.args[0]
    assert auto_packets[0][0:2] == bytes((0x68, protocol.OLD_AUTO_SCHEDULE))
    assert auto_packets[1] == protocol.old_mode_packet(1)

    device._async_send_packets.reset_mock()
    assert await device.async_set_native_pro_schedule(
        [{"time": "08:00", "channel_1": 1, "channel_2": 2, "channel_3": 3, "channel_4": 4}]
    )
    pro_packets = device._async_send_packets.await_args.args[0]
    assert pro_packets[0][0:2] == bytes((0x68, protocol.OLD_PRO_SCHEDULE))
    assert pro_packets[1] == protocol.old_mode_packet(2)


def test_mesh_status_populates_native_schedule_readback():
    device = _make_device(name="PlantPro_AABBCC", model="PlantPro_AABBCC")
    device.client = _mesh_client()
    packet = protocol.mesh_set_packet(
        {
            protocol.MESH_AUTO_SUNRISE_KEY: bytes([8, 0, 60]),
            protocol.MESH_AUTO_SUNSET_KEY: bytes([21, 0, 45]),
            protocol.MESH_AUTO_SLEEP_KEY: bytes([22, 30]),
            protocol.MESH_AUTO_DAY_LEVELS_KEY: bytes([80, 70, 60, 50, 40]),
            protocol.MESH_AUTO_NIGHT_LEVELS_KEY: bytes([0, 10, 0, 0, 0]),
            protocol.MESH_PRO_SCHEDULE_KEY: bytes([1, 12, 30, 10, 20, 30, 40, 50]),
        }
    )

    device.decode_update_packet(bytearray(packet))

    assert device.values["native_auto_schedule"]["sunrise"] == {"hour": 8, "minute": 0, "ramp": 60}
    assert device.values["native_auto_schedule"]["sleep"] == {"hour": 22, "minute": 30}
    assert device.values["native_pro_schedule"] == [
        {
            "minute": 750,
            "channel_1": 10,
            "channel_2": 20,
            "channel_3": 30,
            "channel_4": 40,
            "channel_5": 50,
        }
    ]
