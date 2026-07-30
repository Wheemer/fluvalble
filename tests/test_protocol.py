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


def test_cbor_signed_timezone_offset():
    packet = protocol.cbor_map({protocol.WIFI_TZ_OFFSET_KEY: -150})
    decoded = protocol.decode_cbor_map(packet)
    assert decoded[protocol.WIFI_TZ_OFFSET_KEY] == -150
