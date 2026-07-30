"""Packet builders for Fluval light protocols."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from . import encryption

# FACEBD / WiFi-over-BLE CBOR keys (FluvalConnect)
WIFI_TZ_OFFSET_KEY = 101
WIFI_CLOCK_MS_KEY = 102
WIFI_MODE_KEY = 103
WIFI_SWITCH_KEY = 104
WIFI_MANUAL_KEY = 109
WIFI_CHANNEL_KEYS = (110, 111, 112, 113, 114)

# Mesh BLE (service 0000fff0) CBOR keys — FluvalConnect
MESH_MODE_KEY = 1
MESH_SWITCH_KEY = 2
MESH_MANUAL_KEY = 14
MESH_CHANNEL_KEYS = (3, 4, 5, 6, 7)
MESH_OPCODE_READ = 0xD0
MESH_OPCODE_SET = 0xD1
MESH_OPCODE_CLOCK = 0xCD

OLD_READ_PARAMS = bytes((0x68, 0x05))
OLD_MODE = 0x02
OLD_SWITCH = 0x03
OLD_ALL_ZONE = 0x04
OLD_WEATHER_EFFECT = 0x0A
OLD_CLOCK = 0x0E


def wifi_switch_packet(is_on: bool) -> bytes:
    """Build the FACEBD WiFi-over-BLE on/off packet."""
    return cbor_map({WIFI_SWITCH_KEY: is_on})


def wifi_mode_packet(mode: int) -> bytes:
    """Build the FACEBD WiFi-over-BLE mode packet."""
    return cbor_map({WIFI_MODE_KEY: mode})


def wifi_all_zone_packet(values: Iterable[int]) -> bytes:
    """Build the FACEBD WiFi-over-BLE packet for the five color channels."""
    packet = {WIFI_MANUAL_KEY: 0}
    packet.update({key: _clamp_percent(value) for key, value in zip(WIFI_CHANNEL_KEYS, values, strict=False)})
    return cbor_map(packet)


def wifi_clock_packet(now: datetime | None = None) -> bytes:
    """Build FACEBD clock sync (milliseconds since Unix epoch)."""
    moment = now or datetime.now().astimezone()
    millis = int(moment.timestamp() * 1000)
    return cbor_map({WIFI_CLOCK_MS_KEY: millis})


def wifi_timezone_packet(now: datetime | None = None) -> bytes:
    """Build FACEBD timezone offset in minutes from UTC."""
    moment = now or datetime.now().astimezone()
    offset = moment.utcoffset()
    minutes = int(offset.total_seconds() // 60) if offset is not None else 0
    return cbor_map({WIFI_TZ_OFFSET_KEY: minutes})


def mesh_switch_packet(is_on: bool) -> bytes:
    """Build mesh on/off packet (0xD1 + CBOR)."""
    return mesh_set_packet({MESH_SWITCH_KEY: is_on})


def mesh_mode_packet(mode: int) -> bytes:
    """Build mesh mode packet (0xD1 + CBOR)."""
    return mesh_set_packet({MESH_MODE_KEY: mode})


def mesh_all_zone_packet(values: Iterable[int]) -> bytes:
    """Build mesh multi-channel packet (0xD1 + CBOR)."""
    packet: dict[int, bool | int] = {MESH_MANUAL_KEY: 0}
    packet.update({key: _clamp_percent(value) for key, value in zip(MESH_CHANNEL_KEYS, values, strict=False)})
    return mesh_set_packet(packet)


def mesh_read_params_packet() -> bytes:
    """Build mesh status read request."""
    return bytes((MESH_OPCODE_READ, 0xFF))


def mesh_clock_packet(now: datetime | None = None) -> bytes:
    """Build mesh clock sync (opcode 0xCD + Y M D W h m s)."""
    return bytes((MESH_OPCODE_CLOCK,)) + _clock_payload(now)


def mesh_set_packet(values: dict[int, bool | int]) -> bytes:
    """Wrap a CBOR map with the mesh set opcode."""
    return bytes((MESH_OPCODE_SET,)) + cbor_map(values)


def old_read_params_packet() -> bytes:
    """Build the old BLE parameter read packet."""
    return old_packet(OLD_READ_PARAMS)


def old_switch_packet(is_on: bool) -> bytes:
    """Build the old BLE on/off packet."""
    return old_packet(bytes((0x68, OLD_SWITCH, 0x01 if is_on else 0x00)))


def old_weather_effect_packet(effect_id: int) -> bytes:
    """Build the APK's classic live weather-effect packet (680A + ID)."""
    if not 1 <= effect_id <= 11:
        raise ValueError("Classic Fluval effect ID must be between 1 and 11")
    return old_packet(bytes((0x68, OLD_WEATHER_EFFECT, effect_id)))


def old_mode_packet(mode: int) -> bytes:
    """Build the old BLE mode packet."""
    return old_packet(bytes((0x68, OLD_MODE, mode & 0xFF)))


def old_all_zone_packet(values: Iterable[int], *, endian: str = "be") -> bytes:
    """Build old BLE all-channel packet (``6804`` + progress*10 + XOR CRC).

    FluvalConnect ``OldLightKxtKt.createLightAllZoneValueForOld`` appends each
    channel via ``HexUtil.integerToHexLittle(progress * 10)``. Despite the name,
    that helper zero-pads to 4 hex digits and does **not** swap bytes — wire
    words are big-endian (e.g. 100 → ``0064``). Status notifications parse the
    same scale little-endian; do not use LE for outbound commands.
    """
    packet = bytearray((0x68, OLD_ALL_ZONE))
    for value in values:
        scaled = _clamp_percent(value) * 10
        if endian == "le":
            # Kept only for tests / accidental legacy callers — never for writes.
            packet.extend((scaled & 0xFF, (scaled >> 8) & 0xFF))
        else:
            packet.extend(((scaled >> 8) & 0xFF, scaled & 0xFF))
    return old_packet(packet)


def old_clock_packet(now: datetime | None = None) -> bytes:
    """Build old BLE clock sync (cmd 0x0E: Y M D W h m s)."""
    return old_packet(bytes((0x68, OLD_CLOCK)) + _clock_payload(now))


def old_packet(packet: bytes) -> bytes:
    """Append the XOR checksum used by the old light protocol."""
    checksum = 0
    for item in packet:
        checksum ^= item
    return bytes(packet) + bytes((checksum,))


def encrypted_old_packet(packet: bytes, dialect: str | None = None) -> bytearray:
    """Encrypt one checksummed plaintext frame (single chunk).

    Prefer ``encrypted_old_frames`` for writes — the APK chunks at 15 bytes.
    ``dialect`` is legacy; omitted means APK ``encodeMessage`` (random key).
    """
    frames = encrypted_old_frames(packet, dialect=dialect)
    return frames[0]


def encrypted_old_frames(packet: bytes, dialect: str | None = None) -> list[bytearray]:
    """Classic old-light write path: CRC'd plaintext → ≤15-byte chunks → encode.

    Default dialect is the APK's random embedded key. ``rand0`` and ``xor_0e``
    remain explicit compatibility options. ``old_*_packet`` already has XOR CRC.
    """
    if dialect == encryption.DIALECT_XOR_0E:
        return encryption.encode_message_chunks(packet, key=0x0E)
    if dialect == encryption.DIALECT_RAND0:
        return encryption.encode_message_chunks(packet, key=0)
    # Default / APK FluvalConnect: random key per chunk (encodeMessage).
    return encryption.encode_message_chunks(packet, key=None)


def decode_channel_words(payload: bytes, count: int) -> tuple[list[int], str]:
    """Decode ``count`` 16-bit channel words from a classic status frame.

    FluvalConnect ``LightKxtKt.analyticLightParameterToOld`` (manual mode)
    builds each color short as little-endian:
    ``lo | (hi << 8)`` at offsets after mode/switch/dyn. Prefer LE when both
    endiannesses score; fall back to BE only if LE is out of 0–1000.
    """
    words_le: list[int] = []
    words_be: list[int] = []
    # Status layout after 6805 strip varies; Device passes already-sliced
    # payloads. Offset 5 matches [0]=0x68 [1]=cmd [2]=mode [3]=switch [4]=dyn.
    offset = 5
    for index in range(count):
        lo = offset + index * 2
        hi = lo + 1
        if hi >= len(payload):
            break
        words_le.append((payload[hi] << 8) | payload[lo])
        words_be.append((payload[lo] << 8) | payload[hi])

    def _score(values: list[int]) -> int:
        if not values:
            return -1
        if any(value < 0 or value > 1000 for value in values):
            return -1
        return len(values)

    score_le = _score(words_le)
    score_be = _score(words_be)
    if score_le >= 0:
        return words_le, "le"
    if score_be >= 0:
        return words_be, "be"
    return words_le, "le"


# Fluval company ID in manufacturer data (ScanOldLight / Ble ads).
FLUVAL_MFG_COMPANY_ID = 12592  # 0x3140

# LightDeviceUtils.getLightType → 3 (RGBW / 4-channel), including LIGHT_ID_385_OLD.
_OLD_LIGHT_TYPE_3_IDS = frozenset(
    {
        # Live controller B8:80:4F:3D:67:C0 advertises ASCII product 0103.
        # It rejects five-channel 6804 packets and physically accepts the
        # four-channel RGBW form, so preserve this device-derived override
        # even though 259 is absent from the current APK's static ID table.
        259,
        532,
        321,
        322,
        323,
        324,
        325,
        326,
        327,
        328,
        329,
        336,
        384,
        609,
        369,
        370,
        371,
        372,
        564,
        29057,  # LIGHT_ID_385_OLD
    }
)

# LightDeviceUtils.getLightType → 2 (plant pink/blue/CW/PW/WW), including LIGHT_ID_386_OLD.
_OLD_LIGHT_TYPE_2_IDS = frozenset(
    {
        386,
        545,
        548,
        305,
        306,
        307,
        308,
        309,
        310,
        311,
        387,
        388,
        338,
        537,
        641,
        373,
        374,
        375,
        376,
        377,
        563,
        29058,  # LIGHT_ID_386_OLD
    }
)


def product_id_from_manufacturer_data(manufacturer_data: dict[Any, Any]) -> int | None:
    """APK ``ScanOldLightActivity`` productId from Fluval manufacturer payload.

    Full scan uses ``scanRecord[9:13]`` as ASCII hex (``0181``→``7181``,
    ``0182``→``7182``), then ``Integer.parseInt(hex, 16)``.

    With the common ``02 01 06`` + mfg AD layout, that slice is bytes ``[2:6]``
    of the company-12592 payload (after the 2-byte company ID in the AD).
    """
    for key, value in manufacturer_data.items():
        try:
            company = int(key)
        except (TypeError, ValueError):
            continue
        if company != FLUVAL_MFG_COMPANY_ID:
            continue
        if isinstance(value, str):
            try:
                raw = bytes.fromhex(value)
            except ValueError:
                continue
        else:
            raw = bytes(value)
        if len(raw) < 6:
            continue
        try:
            hex_str = raw[2:6].decode("ascii")
        except UnicodeDecodeError:
            continue
        if hex_str == "0181":
            hex_str = "7181"
        elif hex_str == "0182":
            hex_str = "7182"
        if len(hex_str) != 4 or any(c not in "0123456789abcdefABCDEF" for c in hex_str):
            continue
        return int(hex_str, 16)
    return None


def light_type_from_product_id(product_id: int) -> int:
    """APK ``LightDeviceUtils.getLightType`` (1 marine / 2 plant / 3 RGBW)."""
    if product_id in _OLD_LIGHT_TYPE_3_IDS:
        return 3
    if product_id in _OLD_LIGHT_TYPE_2_IDS:
        return 2
    # Type-1 list + default unknown → marine 5-channel.
    return 1


def channel_count_for_product_id(product_id: int | None) -> int | None:
    """APK ``getChannelCount``: 4 when type 3, else 5."""
    if product_id is None:
        return None
    return 4 if light_type_from_product_id(product_id) == 3 else 5


def old_receive_frame_ready(payload: bytes, *, channel_count: int | None = None) -> bool:
    """True when APK ``analyticLightParameterToOld`` would accept the cache.

    ``LightDetailActivity.onCharacteristicChanged`` accumulates decrypted bytes
    and only acts when parse returns non-null. Incomplete multi-notify status
    must not be delivered to HA.
    """
    if not encryption.is_valid_fluval_frame(payload):
        return False
    if len(payload) < 4:
        return False
    # Non-6805 classic frames (acks): deliver when XOR frame is complete.
    if payload[1] != OLD_READ_PARAMS[1]:
        return True

    body = payload[2:-1]
    if not body:
        return False
    mode = body[0]
    counts = [channel_count] if channel_count in (4, 5) else [5, 4]
    for count in counts:
        if count is None:
            continue
        if mode == 0:
            # Manual: (channels * 6) + 3  (open + dyn + colors + P1–P4)
            if len(body) == count * 6 + 3:
                return True
        elif mode == 1:
            # Auto: several accepted lengths in analyticLightParameterToOld.
            base = count * 2 + 9
            if len(body) in (base, count * 2 + 12, count * 2 + 15, count * 2 + 18):
                return True
        elif mode == 2:
            # Pro: length depends on point count at body[1].
            if len(body) < 2:
                continue
            points = body[1]
            stride = count + 2
            expected = points * stride + 2
            if len(body) in (expected, expected + 6):
                return True
    return False


def strip_mesh_opcode(data: bytes) -> bytes:
    """Remove a leading mesh opcode byte when present."""
    if data and data[0] in (MESH_OPCODE_SET, MESH_OPCODE_READ, 0xFF):
        return data[1:]
    return data


def cbor_map(values: dict[int, bool | int]) -> bytes:
    """Encode the tiny CBOR subset used by Fluval WiFi/mesh BLE light commands."""
    if len(values) > 23:
        raise ValueError("CBOR helper only supports small maps")

    packet = bytearray((0xA0 | len(values),))
    for key, value in values.items():
        packet.extend(_cbor_uint(key))
        if isinstance(value, bool):
            packet.append(0xF5 if value else 0xF4)
        else:
            packet.extend(_cbor_int(value))
    return bytes(packet)


def decode_cbor_map(data: bytes) -> dict[Any, Any] | None:
    """Decode the CBOR maps the FACEBD/mesh controllers use for light state."""
    if not data or data[0] >> 5 != 5:
        return None

    value, _offset = _read_cbor_value(data, 0)
    if not isinstance(value, dict):
        return None
    return value


def _clock_payload(now: datetime | None = None) -> bytes:
    """Return Y M D W h m s used by old and mesh clock sync."""
    moment = (now or datetime.now().astimezone()).astimezone()
    # FluvalConnect TimeUtil.getWeeks: Monday = 1 ... Sunday = 7.
    weekday = moment.isoweekday()
    return bytes(
        (
            moment.year % 100,
            moment.month,
            moment.day,
            weekday,
            moment.hour,
            moment.minute,
            moment.second,
        )
    )


def _clamp_percent(value: int) -> int:
    return max(0, min(100, int(value)))


def _cbor_int(value: int) -> bytes:
    if value >= 0:
        return _cbor_uint(value)
    # Major type 1: negative integer -1 - n
    return _cbor_major(1, -1 - value)


def _cbor_uint(value: int) -> bytes:
    if value < 0:
        raise ValueError("CBOR helper only supports unsigned integers")
    return _cbor_major(0, value)


def _cbor_major(major: int, value: int) -> bytes:
    if value < 24:
        return bytes(((major << 5) | value,))
    if value <= 0xFF:
        return bytes(((major << 5) | 24, value))
    if value <= 0xFFFF:
        return bytes(((major << 5) | 25, value >> 8, value & 0xFF))
    if value <= 0xFFFFFFFF:
        return bytes(((major << 5) | 26, *value.to_bytes(4, "big")))
    return bytes(((major << 5) | 27, *value.to_bytes(8, "big")))


def _read_cbor_value(data: bytes, offset: int) -> tuple[Any, int]:
    if offset >= len(data):
        raise ValueError("Unexpected end of CBOR data")

    item = data[offset]
    major = item >> 5

    if item == 0xF4:
        return False, offset + 1
    if item == 0xF5:
        return True, offset + 1

    if major == 0:
        return _read_cbor_uint(data, offset)
    if major == 1:
        value, offset = _read_cbor_length(data, offset)
        return -1 - value, offset
    if major in (2, 3):
        length, offset = _read_cbor_length(data, offset)
        end = offset + length
        if end > len(data):
            raise ValueError("CBOR byte/text string is truncated")
        raw = data[offset:end]
        if major == 2:
            return bytes(raw), end
        return raw.decode("utf-8", errors="replace"), end
    if major == 4:
        length, offset = _read_cbor_length(data, offset)
        items = []
        for _ in range(length):
            value, offset = _read_cbor_value(data, offset)
            items.append(value)
        return items, offset
    if major == 5:
        length, offset = _read_cbor_length(data, offset)
        result = {}
        for _ in range(length):
            key, offset = _read_cbor_value(data, offset)
            value, offset = _read_cbor_value(data, offset)
            result[key] = value
        return result, offset
    if major == 7:
        if item == 0xF6:
            return None, offset + 1
        if item == 0xF9:
            return None, offset + 3
        if item == 0xFA:
            return None, offset + 5
        if item == 0xFB:
            return None, offset + 9

    raise ValueError(f"Unsupported CBOR item 0x{item:02x}")


def _read_cbor_uint(data: bytes, offset: int) -> tuple[int, int]:
    item = data[offset]
    major = item >> 5
    if major != 0:
        raise ValueError(f"Expected unsigned CBOR integer, got 0x{item:02x}")
    return _read_cbor_length(data, offset)


def _read_cbor_length(data: bytes, offset: int) -> tuple[int, int]:
    """Read a CBOR additional-info length or unsigned integer."""
    item = data[offset]
    additional = item & 0x1F
    if additional < 24:
        return additional, offset + 1
    if additional == 24:
        _require_length(data, offset, 2)
        return data[offset + 1], offset + 2
    if additional == 25:
        _require_length(data, offset, 3)
        return int.from_bytes(data[offset + 1 : offset + 3], "big"), offset + 3
    if additional == 26:
        _require_length(data, offset, 5)
        return int.from_bytes(data[offset + 1 : offset + 5], "big"), offset + 5
    if additional == 27:
        _require_length(data, offset, 9)
        return int.from_bytes(data[offset + 1 : offset + 9], "big"), offset + 9
    raise ValueError(f"Unsupported CBOR integer length {additional}")


def _require_length(data: bytes, offset: int, needed: int) -> None:
    if offset + needed > len(data):
        raise ValueError("CBOR value is truncated")
