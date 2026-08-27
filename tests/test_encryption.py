"""
Unit tests for the Fluval BLE encryption module.

Matches FluvalConnect libhy_api EncodeUtil.encodeMessage / decodeMessage.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from custom_components.fluvalble.core import encryption, protocol


class TestAddCrc:
    def test_empty_packet(self):
        data = bytearray()
        result = encryption.add_crc(data)
        assert result == bytearray([0x00])

    def test_single_byte(self):
        data = bytearray([0x68])
        result = encryption.add_crc(data)
        assert result[-1] == 0x68

    def test_two_bytes(self):
        data = bytearray([0x68, 0x05])
        result = encryption.add_crc(data)
        assert result[-1] == 0x6D

    def test_crc_appended_in_place(self):
        data = bytearray([0x01, 0x02, 0x03])
        original_len = len(data)
        result = encryption.add_crc(data)
        assert len(result) == original_len + 1
        assert result is data


class TestEncodeMessageApk:
    def test_libhy_api_header_layout(self):
        payload = bytearray([0x68, 0x05, 0x6D])
        result = encryption.encode_message(payload, key=0x0E)
        assert result[0] == 0x54
        assert result[1] == (len(payload) + 1) ^ 0x54
        assert result[2] == 0x54 ^ 0x0E
        assert list(result[3:]) == [b ^ 0x0E for b in payload]

    def test_round_trip_random_and_fixed(self):
        original = bytearray([0x68, 0x04, 0x00, 0x64, 0x00, 0x64, 0x0C])
        for key in (0, 0x0E, 0xAB, None):
            encrypted = encryption.encode_message(original, key=key)
            assert list(encryption.decode_message(encrypted)) == list(original)

    def test_chunks_at_fifteen_bytes(self):
        # 17-byte plaintext → two encodeMessage frames (APK LightDetailActivity)
        payload = bytes(range(17))
        frames = encryption.encode_message_chunks(payload, key=0x11)
        assert len(frames) == 2
        assert len(frames[0]) == 18  # 15 + 3 header
        assert len(frames[1]) == 5  # 2 + 3 header
        assert encryption.decode_message(frames[0]) == payload[:15]
        assert encryption.decode_message(frames[1]) == payload[15:]


class TestDialectCompat:
    def test_encrypt_wrappers(self):
        payload = bytearray([0x68, 0x03, 0x01, 0x6A])
        xor_wire = encryption.encrypt(payload, encryption.DIALECT_XOR_0E)
        rand0_wire = encryption.encrypt(payload, encryption.DIALECT_RAND0)
        assert xor_wire[2] == 0x5A
        assert rand0_wire[2] == 0x54
        assert list(encryption.decrypt(xor_wire)) == list(payload)


class TestEncryptedOldPacket:
    def test_does_not_double_crc(self):
        raw = protocol.old_switch_packet(True)
        assert raw == bytes((0x68, 0x03, 0x01, 0x6A))
        wire = protocol.encrypted_old_packet(raw, encryption.DIALECT_XOR_0E)
        assert bytes(encryption.decrypt(wire)) == raw

    def test_channel_packet_is_single_chunk(self):
        # 5 channels: 2 + 10 + 1 CRC = 13 <= 15
        raw = protocol.old_all_zone_packet([10, 20, 30, 40, 50])
        frames = protocol.encrypted_old_frames(raw, encryption.DIALECT_XOR_0E)
        assert len(frames) == 1
        assert bytes(encryption.decrypt(frames[0])) == raw


class TestChannelEndianDecode:
    def test_prefers_le_status_like_apk(self):
        # APK analyticLightParameterToOld: lo | (hi << 8)
        payload = bytearray(15)
        payload[0] = 0x68
        payload[5] = 100 & 0xFF
        payload[6] = 100 >> 8
        payload[7] = 200 & 0xFF
        payload[8] = 200 >> 8
        words, endian = protocol.decode_channel_words(bytes(payload), 2)
        assert endian == "le"
        assert words[0] == 100
        assert words[1] == 200
