"""Tests for BLE client notification and write behavior."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.fluvalble.core.client import Client
from custom_components.fluvalble.core import encryption, protocol


class _FakeTask:
    """Small task-like object so Client helpers do not start real BLE work."""

    def __init__(self, coroutine=None):
        if coroutine is not None:
            coroutine.close()

    def done(self):
        return False

    def cancel(self):
        pass

    def __await__(self):
        if False:
            yield None
        return None


def _make_client(address="AA:BB:CC:DD:EE:FF"):
    ble_device = MagicMock()
    ble_device.address = address
    with patch("asyncio.create_task", side_effect=lambda coro: _FakeTask(coro)):
        return Client(ble_device)


def _manual_status_frame(*, channels: list[int], channel_count: int = 5) -> bytes:
    """Build a checksummed 6805 Manual status matching APK length rules."""
    body = bytearray([0x00, 0x01, 0x00])  # mode Man, on, dyn
    padded = list(channels[:channel_count])
    while len(padded) < channel_count:
        padded.append(0)
    for value in padded:
        scaled = max(0, min(1000, int(value) * 10))
        body.extend((scaled & 0xFF, (scaled >> 8) & 0xFF))  # LE shorts
    # P1–P4 presets: channel_count bytes each
    body.extend(bytes(channel_count * 4))
    return protocol.old_packet(bytes((0x68, 0x05)) + bytes(body))


def test_client_does_not_eager_connect_on_init():
    client = _make_client()
    assert client.connect_task is None


def test_client_honors_configured_wire_dialect():
    ble_device = MagicMock(address="AA:BB:CC:DD:EE:FF")
    client = Client(ble_device, wire_dialect=encryption.DIALECT_XOR_0E)

    assert client.wire_dialect == encryption.DIALECT_XOR_0E


def test_fresh_connection_uses_one_bounded_connector_retry_cycle():
    asyncio.run(_async_test_fresh_connection_retry_cycle())


async def _async_test_fresh_connection_retry_cycle():
    client = _make_client()
    connected = SimpleNamespace(is_connected=True, start_notify=AsyncMock())
    client._resolve_characteristics = AsyncMock()
    client._async_request_classic_mtu = AsyncMock()
    client._async_classic_session_init = AsyncMock()

    with patch(
        "custom_components.fluvalble.core.client.establish_connection",
        new=AsyncMock(return_value=connected),
    ) as establish:
        result = await client._ensure_client()

    assert result is connected
    assert establish.await_count == 1
    assert establish.await_args.kwargs["max_attempts"] == 3
    assert establish.await_args.kwargs["disconnected_callback"] == client._on_disconnected


def test_unexpected_persistent_disconnect_schedules_immediate_reconnect():
    status_callback = MagicMock()
    ble_device = MagicMock(address="AA:BB:CC:DD:EE:FF")
    client = Client(ble_device, status_callback=status_callback, active_time=0)
    connected = MagicMock()
    client.client = connected
    client._classic_session_ready = True

    with patch(
        "custom_components.fluvalble.core.client.asyncio.create_task",
        side_effect=lambda coro: _FakeTask(coro),
    ) as create_task:
        client._on_disconnected(connected)

    status_callback.assert_called_once_with(False)
    create_task.assert_called_once()
    assert client.classic_session_ready is False


def test_classic_service_pins_apk_1001_and_1002_characteristics():
    asyncio.run(_async_test_classic_service_pins_apk_1001_and_1002_characteristics())


async def _async_test_classic_service_pins_apk_1001_and_1002_characteristics():
    client = _make_client()
    old_write = SimpleNamespace(
        uuid="00001001-0000-1000-8000-00805f9b34fb",
        properties=["write", "write-without-response"],
    )
    old_notify = SimpleNamespace(
        uuid="00001002-0000-1000-8000-00805f9b34fb",
        properties=["notify"],
    )
    unrelated_write = SimpleNamespace(
        uuid="FACEBD80-7261-6262-6974-696F74626C65",
        properties=["write", "notify"],
    )
    by_uuid = {
        old_write.uuid.lower(): old_write,
        old_notify.uuid.lower(): old_notify,
        unrelated_write.uuid.lower(): unrelated_write,
    }
    services = MagicMock()
    services.__iter__.return_value = iter([SimpleNamespace(uuid="00001000-0000-1000-8000-00805f9b34fb")])
    services.get_characteristic.side_effect = lambda uuid: by_uuid.get(uuid.lower())
    client.client = SimpleNamespace(services=services)

    await client._resolve_characteristics()

    assert client.command_write_uuid == old_write.uuid
    assert client.notify_uuids == [old_notify.uuid]
    assert client.init_write_uuid == old_write.uuid
    assert client.raw_facebd is False


def test_mesh_service_pins_apk_fff2_and_fff1_when_old_service_is_also_present():
    asyncio.run(_async_test_mesh_service_pins_apk_fff2_and_fff1_when_old_service_is_also_present())


async def _async_test_mesh_service_pins_apk_fff2_and_fff1_when_old_service_is_also_present():
    client = _make_client()
    old_write = SimpleNamespace(
        uuid="00001001-0000-1000-8000-00805f9b34fb",
        properties=["write", "write-without-response"],
    )
    old_notify = SimpleNamespace(
        uuid="00001002-0000-1000-8000-00805f9b34fb",
        properties=["notify"],
    )
    mesh_write = SimpleNamespace(
        uuid="0000fff2-0000-1000-8000-00805f9b34fb",
        properties=["write", "write-without-response"],
    )
    mesh_notify = SimpleNamespace(
        uuid="0000fff1-0000-1000-8000-00805f9b34fb",
        properties=["notify"],
    )
    by_uuid = {
        old_write.uuid.lower(): old_write,
        old_notify.uuid.lower(): old_notify,
        mesh_write.uuid.lower(): mesh_write,
        mesh_notify.uuid.lower(): mesh_notify,
    }
    services = MagicMock()
    services.__iter__.return_value = iter(
        [
            SimpleNamespace(uuid="00001000-0000-1000-8000-00805f9b34fb"),
            SimpleNamespace(uuid="0000fff0-0000-1000-8000-00805f9b34fb"),
        ]
    )
    services.get_characteristic.side_effect = lambda uuid: by_uuid.get(uuid.lower())
    client.client = SimpleNamespace(services=services)

    await client._resolve_characteristics()

    assert client.command_write_uuid == mesh_write.uuid
    assert client.notify_uuids == [mesh_notify.uuid]
    assert client.raw_mesh is True


def test_old_protocol_notify_callback_ignores_empty_decrypt():
    client = _make_client()
    update_callback = MagicMock()
    client.update_callback = update_callback

    # Header-only frame decrypts to empty payload — ignore.
    client.notify_callback(MagicMock(), bytearray([0x54, 0x55]))

    update_callback.assert_not_called()


def test_old_protocol_notify_callback_flushes_complete_status_frame():
    client = _make_client()
    client._product_channel_count = 5
    update_callback = MagicMock()
    client.update_callback = update_callback

    plaintext = _manual_status_frame(channels=[100, 0, 0, 0, 0], channel_count=5)
    wire = encryption.encode_message(plaintext, key=0x0E)
    client.notify_callback(MagicMock(), bytearray(wire))

    update_callback.assert_called_once_with(plaintext)


def test_old_protocol_notify_keeps_incomplete_status():
    """APK keeps cache until analyticLightParameterToOld succeeds."""
    client = _make_client()
    client._product_channel_count = 5
    update_callback = MagicMock()
    client.update_callback = update_callback

    # Valid XOR but wrong Manual length — must not deliver.
    plaintext = bytes([0x68, 0x05, 0x00, 0x01, 0x6C])
    wire = encryption.encode_message(plaintext, key=0x0E)
    client.notify_callback(MagicMock(), bytearray(wire))

    update_callback.assert_not_called()
    assert client.receive_buffer == plaintext


def test_raw_facebd_notify_callback_forwards_cbor_payload():
    client = _make_client()
    client.raw_facebd = True
    update_callback = MagicMock()
    client.update_callback = update_callback

    client.notify_callback(MagicMock(), bytearray([0xA1, 0x18, 0x68, 0xF5]))

    update_callback.assert_called_once_with(bytes([0xA1, 0x18, 0x68, 0xF5]))


def test_classic_write_packet_prefers_write_without_response_when_available():
    """Old-BLE via proxy: prefer write-without-response when both exist (#6)."""
    asyncio.run(_async_test_classic_write_packet_prefers_write_without_response())


async def _async_test_classic_write_packet_prefers_write_without_response():
    client = _make_client()
    client.raw_facebd = False
    client.raw_mesh = False
    mock_client = MagicMock()
    mock_client.write_gatt_char = AsyncMock()
    client.client = mock_client

    characteristic = MagicMock()
    characteristic.properties = ["write", "write-without-response"]
    client._get_characteristic = MagicMock(return_value=characteristic)

    with patch(
        "custom_components.fluvalble.core.client.protocol.encrypted_old_frames",
        return_value=[bytearray(b"\x54\x01")],
    ):
        await client._write_packet("00001001-0000-1000-8000-00805F9B34FB", bytes([0x68, 0x03, 0x01, 0x6A]))

    kwargs = mock_client.write_gatt_char.await_args.kwargs
    assert kwargs["response"] is False


def test_classic_notify_reassembles_chunked_status():
    """APK: clear on 0x68, append chunks, deliver when Manual status length matches."""
    client = _make_client()
    client._product_channel_count = 5
    update_callback = MagicMock()
    client.update_callback = update_callback

    full = _manual_status_frame(channels=[100, 0, 0, 0, 0], channel_count=5)
    part1 = full[:15]
    part2 = full[15:]
    assert part1[0] == 0x68
    assert part2[0] != 0x68

    client.notify_callback(MagicMock(), bytearray(encryption.encode_message(part1, key=0x0E)))
    update_callback.assert_not_called()
    client.notify_callback(MagicMock(), bytearray(encryption.encode_message(part2, key=0x0E)))
    update_callback.assert_called_once_with(full)


def test_facebd_write_packet_prefers_write_without_response():
    asyncio.run(_async_test_facebd_write_packet_prefers_write_without_response())


async def _async_test_facebd_write_packet_prefers_write_without_response():
    client = _make_client()
    client.raw_facebd = True
    client.raw_mesh = False
    mock_client = MagicMock()
    mock_client.write_gatt_char = AsyncMock()
    client.client = mock_client

    characteristic = MagicMock()
    characteristic.properties = ["write", "write-without-response"]
    client._get_characteristic = MagicMock(return_value=characteristic)

    await client._write_packet("FACEBD80-7261-6262-6974-696F74626C65", bytes([0xA1, 0x18, 0x6D, 0x00]))

    kwargs = mock_client.write_gatt_char.await_args.kwargs
    assert kwargs["response"] is False


def test_send_now_writes_primary_facebd_target_only():
    asyncio.run(_async_test_send_now_writes_primary_facebd_target_only())


async def _async_test_send_now_writes_primary_facebd_target_only():
    client = _make_client()
    client.raw_facebd = True
    client.command_write_uuid = "FACEBD80-7261-6262-6974-696F74626C65"
    client.command_write_uuids = [
        "FACEBD80-7261-6262-6974-696F74626C65",
        "FACEBD01-7261-6262-6974-696F74626C65",
    ]
    client.wake_read_uuid = None
    client._ensure_client = AsyncMock(return_value=MagicMock())
    client._write_packet = AsyncMock()
    client.request_state = AsyncMock()
    client.ping = MagicMock()

    assert await client.send_now(bytes([0xA1, 0x18, 0x6D, 0x00]))

    assert client._write_packet.await_count == 1
    assert client.last_write_targets == ["FACEBD80-7261-6262-6974-696F74626C65"]
    client.request_state.assert_not_awaited()
    client.ping.assert_called_once()


def test_send_sequence_writes_packets_in_order():
    asyncio.run(_async_test_send_sequence_writes_packets_in_order())


async def _async_test_send_sequence_writes_packets_in_order():
    client = _make_client()
    client.raw_facebd = False
    client.command_write_uuid = "00001001-0000-1000-8000-00805F9B34FB"
    client.wake_read_uuid = None
    client._ensure_client = AsyncMock(return_value=MagicMock())
    client._write_packet = AsyncMock()
    client.ping = MagicMock()

    packets = [bytes([0x68, 0x02, 0x00, 0x6A]), bytes([0x68, 0x04, 0x03, 0xE8, 0x00])]
    assert await client.send_sequence(packets)

    assert client._write_packet.await_count == 2
    assert client._write_packet.await_args_list[0].args[1] == packets[0]
    assert client._write_packet.await_args_list[1].args[1] == packets[1]


def test_classic_init_reserves_command_gap_after_6805():
    asyncio.run(_async_test_classic_init_reserves_command_gap_after_6805())


async def _async_test_classic_init_reserves_command_gap_after_6805():
    """The first UI command must wait 200 ms after the APK's 6805 init packet."""
    client = _make_client()
    client.client = MagicMock()
    client.init_write_uuid = "00001001-0000-1000-8000-00805F9B34FB"
    client._write_packet = AsyncMock()

    with (
        patch("custom_components.fluvalble.core.client.asyncio.sleep", new=AsyncMock()),
        patch("custom_components.fluvalble.core.client.time.time", return_value=123.5),
    ):
        await client._async_classic_session_init()

    assert client.last_command_at == 123.5
    assert client.classic_session_ready is True
    assert client._write_packet.await_count == 2


def test_extend_session_pushes_idle_disconnect_deadline():
    client = _make_client()
    client._active_time = 120
    client.ping_task = MagicMock()
    client.ping_time = 1000.0
    with patch("custom_components.fluvalble.core.client.time.time", return_value=900.0):
        client.extend_session()
    assert client.ping_time == 1020.0


def test_extend_session_noop_for_persistent_mode():
    client = _make_client()
    client._active_time = 0
    client.ping_task = MagicMock()
    client.ping_time = 1000.0
    client.extend_session()
    assert client.ping_time == 1000.0


def test_persistent_connection_uses_infinite_ping_deadline():
    client = _make_client()
    client._active_time = 0
    with patch(
        "custom_components.fluvalble.core.client.asyncio.create_task",
        side_effect=lambda coro: _FakeTask(coro),
    ):
        client.ping()
    assert client.ping_time == float("inf")
    assert client.ping_task is not None


def test_extend_session_noop_without_ping_task():
    client = _make_client()
    client.ping_time = 1000.0
    client.extend_session()
    assert client.ping_time == 1000.0


def test_product_id_from_mfg_payload_matches_apk_scan_slice():
    # ASCII "480103..." → scan[9:13] equivalent payload[2:6] = "0103" → 259
    payload = b"480103" + bytes(10)
    product = protocol.product_id_from_manufacturer_data({12592: payload.hex()})
    assert product == 0x0103
    assert protocol.channel_count_for_product_id(product) == 4
    assert protocol.light_type_from_product_id(product) == 3


def test_product_id_remap_0181_to_385_old():
    payload = b"xx0181" + bytes(10)
    # bytes [2:6] of "xx0181..." = "0181" → remapped 7181 → 29057
    product = protocol.product_id_from_manufacturer_data({12592: payload.hex()})
    assert product == 29057
    assert protocol.channel_count_for_product_id(product) == 4


@pytest.mark.parametrize("product_id", range(0x0161, 0x0165))
def test_blue_family_product_ids_are_four_channel(product_id):
    assert protocol.light_type_from_product_id(product_id) == 3
    assert protocol.channel_count_for_product_id(product_id) == 4
