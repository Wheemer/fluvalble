"""Tests for Fluval packet builders."""

from datetime import datetime, timezone

from custom_components.fluvalble.core import protocol


def test_wifi_all_zone_packet_contains_manual_key_and_channel_values():
    packet = protocol.wifi_all_zone_packet([10, 20, 30, 40, 50])

    decoded = protocol.decode_cbor_map(packet)

    assert decoded[protocol.WIFI_MANUAL_KEY] == 0
    assert decoded[protocol.WIFI_CHANNEL_KEYS[0]] == 10
    assert decoded[protocol.WIFI_CHANNEL_KEYS[4]] == 50


def test_wifi_values_are_clamped_to_percent_range():
    packet = protocol.wifi_all_zone_packet([-1, 101, 25, 50, 75])

    decoded = protocol.decode_cbor_map(packet)

    assert decoded[protocol.WIFI_CHANNEL_KEYS[0]] == 0
    assert decoded[protocol.WIFI_CHANNEL_KEYS[1]] == 100


def test_wifi_mode_packet_uses_mode_key():
    packet = protocol.wifi_mode_packet(1)

    assert protocol.decode_cbor_map(packet) == {protocol.WIFI_MODE_KEY: 1}


def test_wifi_clock_and_timezone_packets():
    moment = datetime(2026, 7, 19, 12, 30, 0, tzinfo=timezone.utc)
    clock = protocol.decode_cbor_map(protocol.wifi_clock_packet(moment))
    tz = protocol.decode_cbor_map(protocol.wifi_timezone_packet(moment))

    assert clock[protocol.WIFI_CLOCK_MS_KEY] == int(moment.timestamp() * 1000)
    assert tz[protocol.WIFI_TZ_OFFSET_KEY] == 0


def test_old_clock_packet_shape():
    moment = datetime(2026, 7, 19, 12, 30, 45, tzinfo=timezone.utc)
    local = moment.astimezone()
    packet = protocol.old_clock_packet(moment)

    assert packet[0] == 0x68
    assert packet[1] == protocol.OLD_CLOCK
    assert packet[2] == local.year % 100
    assert packet[3] == local.month
    assert packet[4] == local.day
    assert packet[5] == local.isoweekday()
    assert packet[6] == local.hour
    assert packet[7] == local.minute
    assert packet[8] == local.second


def test_old_all_zone_scales_percent_to_wire_be():
    """APK integerToHexLittle(progress*10) is zero-padded BE, not byte-swapped."""
    packet = protocol.old_all_zone_packet([10, 20, 30, 40, 50])

    assert packet[0:2] == bytes((0x68, 0x04))
    assert packet[2:4] == bytes((100 >> 8, 100 & 0xFF))
    # CRC over 6804 + five BE words
    assert packet[-1] == protocol.old_packet(packet[:-1])[-1]

    # 100% → 1000 = 0x03E8
    full = protocol.old_all_zone_packet([100])
    assert full[2:4] == bytes((0x03, 0xE8))


def test_old_weather_effect_packet_matches_apk_680a_command():
    packet = protocol.old_weather_effect_packet(2)

    assert packet[0:3] == bytes((0x68, 0x0A, 0x02))
    assert packet[-1] == protocol.old_packet(packet[:-1])[-1]


def test_mesh_set_packets_use_d1_prefix():
    packet = protocol.mesh_switch_packet(True)

    assert packet[0] == protocol.MESH_OPCODE_SET
    assert protocol.decode_cbor_map(packet[1:]) == {protocol.MESH_SWITCH_KEY: True}


def test_mesh_channels_and_clock():
    channels = protocol.mesh_all_zone_packet([1, 2, 3, 4, 5])
    assert channels[0] == protocol.MESH_OPCODE_SET
    decoded = protocol.decode_cbor_map(channels[1:])
    assert decoded[protocol.MESH_CHANNEL_KEYS[0]] == 1
    assert decoded[protocol.MESH_MANUAL_KEY] == 0

    moment = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    local = moment.astimezone()
    clock = protocol.mesh_clock_packet(moment)
    assert clock[0] == protocol.MESH_OPCODE_CLOCK
    assert list(clock[1:8]) == [
        local.year % 100,
        local.month,
        local.day,
        local.isoweekday(),
        local.hour,
        local.minute,
        local.second,
    ]


def test_plant_pro_mesh_switch_packets_match_reference_capture():
    assert protocol.mesh_switch_packet(True) == bytes.fromhex("d1 a1 02 f5")
    assert protocol.mesh_switch_packet(False) == bytes.fromhex("d1 a1 02 f4")


def test_plant_pro_mesh_mode_packets_match_reference_capture():
    assert protocol.mesh_mode_packet(0) == bytes.fromhex("d1 a1 01 00")
    assert protocol.mesh_mode_packet(1) == bytes.fromhex("d1 a1 01 01")
    assert protocol.mesh_mode_packet(2) == bytes.fromhex("d1 a1 01 02")


def test_plant_pro_mesh_all_zone_packet_matches_reference_shape():
    packet = protocol.mesh_all_zone_packet([100, 20, 30, 40, 50])

    assert packet == bytes.fromhex("d1 a6 03 18 64 04 14 05 18 1e 06 18 28 07 18 32 0e 00")
    assert protocol.decode_cbor_update(packet) == {
        protocol.MESH_CHANNEL_KEYS[0]: 100,
        protocol.MESH_CHANNEL_KEYS[1]: 20,
        protocol.MESH_CHANNEL_KEYS[2]: 30,
        protocol.MESH_CHANNEL_KEYS[3]: 40,
        protocol.MESH_CHANNEL_KEYS[4]: 50,
        protocol.MESH_MANUAL_KEY: 0,
    }


def test_plant_pro_mesh_weather_effect_packet_matches_apk_shape():
    packet = protocol.mesh_weather_effect_packet(4)

    assert packet == bytes.fromhex("d1 a1 0e 04")
    assert protocol.decode_cbor_update(packet) == {protocol.MESH_WEATHER_KEY: 4}


def test_plant_pro_mesh_auto_schedule_packet_matches_apk_keys():
    packet = protocol.mesh_auto_schedule_packet(
        sunrise=(8, 0, 60),
        sunset=(21, 0, 45),
        sleep=None,
        day_levels=[80, 70, 60, 50, 40],
        night_levels=[0, 10, 0, 0, 0],
    )

    decoded = protocol.decode_cbor_update(packet)

    assert decoded[protocol.MESH_AUTO_SUNRISE_KEY] == bytes([8, 0, 60])
    assert decoded[protocol.MESH_AUTO_SUNSET_KEY] == bytes([21, 0, 45])
    assert decoded[protocol.MESH_AUTO_SLEEP_KEY] == bytes([0xFF, 0xFF])
    assert decoded[protocol.MESH_AUTO_DAY_LEVELS_KEY] == bytes([80, 70, 60, 50, 40])
    assert decoded[protocol.MESH_AUTO_NIGHT_LEVELS_KEY] == bytes([0, 10, 0, 0, 0])


def test_plant_pro_mesh_pro_schedule_packet_matches_apk_blob_shape():
    packet = protocol.mesh_pro_schedule_packet(
        [
            {"minute": 8 * 60, "channel_1": 1, "channel_2": 2, "channel_3": 3, "channel_4": 4, "channel_5": 5},
            {
                "minute": 12 * 60 + 30,
                "channel_1": 10,
                "channel_2": 20,
                "channel_3": 30,
                "channel_4": 40,
                "channel_5": 50,
            },
        ]
    )

    decoded = protocol.decode_cbor_update(packet)

    assert decoded[protocol.MESH_PRO_SCHEDULE_KEY] == bytes([2, 8, 0, 1, 2, 3, 4, 5, 12, 30, 10, 20, 30, 40, 50])


def test_plant_pro_mesh_status_strips_d2_header_and_keeps_schedule_blobs():
    status = bytes.fromhex(
        "d2 aa 00 0e 01 00 02 f5 03 18 64 04 18 64 05 18 64 06 18 64 07 18 64 08 43 0d 00 a0 09 43 15 03 26"
    )

    decoded = protocol.decode_cbor_update(status)

    assert decoded[protocol.MESH_MODE_KEY] == 0
    assert decoded[protocol.MESH_SWITCH_KEY] is True
    assert decoded[protocol.MESH_CHANNEL_KEYS[0]] == 100
    assert decoded[8] == bytes.fromhex("0d00a0")


def test_cbor_signed_timezone_offset():
    packet = protocol.cbor_map({protocol.WIFI_TZ_OFFSET_KEY: -150})
    decoded = protocol.decode_cbor_map(packet)
    assert decoded[protocol.WIFI_TZ_OFFSET_KEY] == -150
