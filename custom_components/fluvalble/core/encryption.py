"""Fluval classic BLE framing — bit-exact with FluvalConnect ``libhy_api.so``.

Evidence (FluvalConnect APK):
* ``com.ble.api.EncodeUtil.encodeMessage`` / ``decodeMessage`` → JNI
  ``Java_com_ble_api_EncodeUtil_encodeMessage`` in ``libhy_api.so``
* Disassembly: ``out[0]=0x54``, ``out[1]=(len+1)^0x54``, ``out[2]=key^0x54``,
  ``out[3:]=payload^key`` where ``key = rand() & 0xFF``
* ``LightDetailActivity.sendDataForSingle`` (LightType old): plaintext is
  chunked to 15 bytes, then each chunk is ``encodeMessage``'d separately
  before write to ``00001001``

The lamp decrypts with ``key = IV ^ key_byte`` from the header, so any key
works; we still match the app and call ``rand``-style keys by default.
"""

from __future__ import annotations

import random
from typing import Final

IV: Final = 0x54
# FluvalConnect: ByteArrayKxtKt.chunkedByteArray(obj, 15) before encodeMessage
PLAINTEXT_CHUNK: Final = 15

# Legacy names kept for config-entry migration / older tests.
DIALECT_XOR_0E: Final = "xor_0e"
DIALECT_RAND0: Final = "rand0"
DIALECT_RANDOM: Final = "random"
DIALECTS: Final = (DIALECT_XOR_0E, DIALECT_RAND0, DIALECT_RANDOM)
# FluvalConnect phone path uses random keys. rand0 / xor_0e remain as dialects.
PROBE_ORDER: Final = (DIALECT_RANDOM, DIALECT_RAND0)


def encode_message(source: bytearray | bytes, *, key: int | None = None) -> bytearray:
    """APK ``EncodeUtil.encodeMessage`` / ``libhy_api`` encode.

    Default ``key=None`` → ``rand()``-style key (FluvalConnect). Pass an
    explicit key for Planted Tank ``0`` or ESPHome ``0x0E``.
    """
    payload = bytearray(source)
    use_key = random.randint(0, 255) if key is None else (key & 0xFF)
    encoded = bytearray([IV, (len(payload) + 1) ^ IV, IV ^ use_key])
    encoded.extend(b ^ use_key for b in payload)
    return encoded


def decode_message(source: bytes | bytearray) -> bytes:
    """APK ``EncodeUtil.decodeMessage`` — key is embedded in the header."""
    if len(source) < 3:
        return b""
    key = source[0] ^ source[2]
    return bytes(b ^ key for b in source[3:])


def encode_message_chunks(source: bytearray | bytes, *, key: int | None = None) -> list[bytearray]:
    """Chunk plaintext to 15 bytes and encode each chunk (APK send path)."""
    payload = bytes(source)
    if len(payload) <= PLAINTEXT_CHUNK:
        return [encode_message(payload, key=key)]
    chunks: list[bytearray] = []
    for offset in range(0, len(payload), PLAINTEXT_CHUNK):
        # Per-chunk random key matches calling encodeMessage on each slice.
        chunks.append(encode_message(payload[offset : offset + PLAINTEXT_CHUNK], key=key))
    return chunks


def encrypt(source: bytearray | bytes, dialect: str = DIALECT_RANDOM) -> bytearray:
    """Backward-compatible wrapper; prefer ``encode_message`` for new code."""
    if dialect == DIALECT_RAND0:
        return encode_message(source, key=0)
    if dialect == DIALECT_XOR_0E:
        return encode_message(source, key=0x0E)
    return encode_message(source)


def decrypt(source: bytes | bytearray) -> bytes:
    """Decrypt a BLE notification/write using the header key."""
    return decode_message(source)


def add_crc(source: bytearray) -> bytearray:
    """Append the Fluval XOR checksum (mutates and returns ``source``)."""
    crc = 0x0
    for b in source:
        crc = b ^ crc
    source.append(crc)
    return source


def dialect_from_key_byte(key_byte: int) -> str:
    """Map a wire header key byte to a legacy dialect name (inbound only)."""
    if key_byte == 0x5A:
        return DIALECT_XOR_0E
    if key_byte == IV:
        return DIALECT_RAND0
    return DIALECT_RANDOM


def learn_dialect_from_wire(source: bytes | bytearray) -> str | None:
    """Classify an inbound encrypted frame; outbound always uses encode_message."""
    if len(source) < 4 or source[0] != IV:
        return None
    decrypted = decrypt(source)
    if not decrypted:
        return None
    if decrypted[0] == 0x68 or _xor_checksum(decrypted) == 0:
        return dialect_from_key_byte(source[2])
    return None


def is_valid_fluval_frame(data: bytes | bytearray) -> bool:
    """True when data looks like a complete Fluval command/status frame."""
    if len(data) < 3 or data[0] != 0x68:
        return False
    return _xor_checksum(data) == 0


def _xor_checksum(data: bytes | bytearray) -> int:
    crc = 0
    for b in data:
        crc ^= b
    return crc
