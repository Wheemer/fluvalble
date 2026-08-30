"""Client class connecting the Fluval BLE Entity to a bluetooth connection."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import contextlib
import logging
import time

from bleak import BleakClient, BleakError, BleakGATTCharacteristic, BLEDevice
from bleak_retry_connector import establish_connection

from . import DEFAULT_ACTIVE_TIME, encryption, protocol

_LOGGER = logging.getLogger(__name__)

ACTIVE_TIME = DEFAULT_ACTIVE_TIME
CONNECT_TIMEOUT = 20
CONNECT_RETRIES = 3
WRITE_RETRIES = 2
# FluvalConnect WriteOptions: package 5ms / request 10ms; AffairManager uses 200ms.
WRITE_DELAY = 0.05
COMMAND_GAP = 0.2
CHUNK_WRITE_GAP = 0.01
POST_WRITE_STATE_DELAY = 0.25

# Official FluvalConnect GATT map (BleSppGattAttributes):
#   facebd80 = WiFi-over-BLE write + notify (raw CBOR, keys 103+)
#   facebd01 = FACEBD BLE write path
#   facebd02 = FACEBD BLE read/notify path
#   0000fff0 / fff2 / fff1 = mesh (0xD1 + CBOR)
# The working probe script and Fluval app both write WiFi CBOR to facebd80.
# Preferring facebd02/facebd01 first for commands sends correct CBOR packets to
# the wrong characteristic, so the light never reacts.
WIFI_COMMAND_WRITE_UUIDS = (
    "facebd80-7261-6262-6974-696f74626c65",
    "facebd80-0000-1000-8000-00805f9b34fb",
)
BLE_COMMAND_WRITE_UUIDS = (
    "facebd01-7261-6262-6974-696f74626c65",
    "facebd01-0000-1000-8000-00805f9b34fb",
    "facebd02-7261-6262-6974-696f74626c65",
    "facebd02-0000-1000-8000-00805f9b34fb",
    "00001001-0000-1000-8000-00805f9b34fb",
    "0000fff2-0000-1000-8000-00805f9b34fb",
)
MESH_COMMAND_WRITE_UUIDS = ("0000fff2-0000-1000-8000-00805f9b34fb",)
CLASSIC_COMMAND_WRITE_UUIDS = ("00001001-0000-1000-8000-00805f9b34fb",)
# facebd02 is intentionally excluded: it is the BLE read/notify char, not the
# WiFi CBOR write target used by on/off/mode/channel packets.
COMMAND_WRITE_UUIDS = WIFI_COMMAND_WRITE_UUIDS + BLE_COMMAND_WRITE_UUIDS
NOTIFY_UUIDS = (
    "facebd80-7261-6262-6974-696f74626c65",
    "facebd80-0000-1000-8000-00805f9b34fb",
    "facebd02-7261-6262-6974-696f74626c65",
    "facebd02-0000-1000-8000-00805f9b34fb",
    "facebd03-7261-6262-6974-696f74626c65",
    "facebd03-0000-1000-8000-00805f9b34fb",
    "00001002-0000-1000-8000-00805f9b34fb",
    "0000fff1-0000-1000-8000-00805f9b34fb",
)
MESH_NOTIFY_UUIDS = ("0000fff1-0000-1000-8000-00805f9b34fb",)
CLASSIC_NOTIFY_UUIDS = ("00001002-0000-1000-8000-00805f9b34fb",)
INIT_WRITE_UUIDS = (
    "facebd01-7261-6262-6974-696f74626c65",
    "facebd01-0000-1000-8000-00805f9b34fb",
    "00001001-0000-1000-8000-00805f9b34fb",
)
# FluvalConnect BleKxtKt.setNotificationToOldBle requests MTU 220.
CLASSIC_MTU = 220
# Present on some classic 00001000 stacks. FluvalConnect old-light UI never
# writes these (no readReg / 0x0F / 0x47). Kept only for diagnostics.
CLASSIC_WRITE_REG_UUIDS = ("00001005-0000-1000-8000-00805f9b34fb",)
CLASSIC_READ_REG_UUIDS = ("00001004-0000-1000-8000-00805f9b34fb",)
WAKE_READ_UUIDS = (
    "facebd81-7261-6262-6974-696f74626c65",
    "facebd81-0000-1000-8000-00805f9b34fb",
    "facebd80-7261-6262-6974-696f74626c65",
    "facebd80-0000-1000-8000-00805f9b34fb",
    "facebd02-7261-6262-6974-696f74626c65",
    "facebd02-0000-1000-8000-00805f9b34fb",
    "0000fff6-0000-1000-8000-00805f9b34fb",
)
WRITE_PROPERTIES = frozenset({"write", "write-without-response"})


class Client:
    """Basic client handling BLE sending and callbacks."""

    def __init__(
        self,
        device: BLEDevice,
        status_callback: Callable | None = None,
        update_callback: Callable | None = None,
        ping_interval: int = 10,
        active_time: int = ACTIVE_TIME,
        ready_callback: Callable[[], Awaitable[None]] | None = None,
        wire_dialect: str | None = None,
        channel_endian: str | None = None,
        profile_learned_callback: Callable[[str, str], Awaitable[None] | None] | None = None,
    ) -> None:
        """Initialize the client."""
        self.device = device
        self.status_callback = status_callback
        self.update_callback = update_callback
        self.ready_callback = ready_callback
        self.profile_learned_callback = profile_learned_callback
        self._ping_interval = ping_interval
        self._active_time = active_time

        self.client: BleakClient | None = None

        self.ping_future: asyncio.Future | None = None
        self.ping_task: asyncio.Task | None = None
        self.ping_time: float = 0.0
        self._stopping = False

        self.connect_task: asyncio.Task | None = None

        self.receive_buffer = b""
        self.notify_uuid = None
        self.notify_uuids: list[str] = []
        self.init_write_uuid = None
        self.command_write_uuid = None
        self.command_write_uuids: list[str] = []
        self.wake_read_uuid = None
        self.state_read_uuids: list[str] = []
        self.write_reg_uuid: str | None = None
        self.read_reg_uuid: str | None = None
        self.raw_facebd = False
        self.raw_mesh = False
        self._command_lock = asyncio.Lock()
        self.last_error: str | None = None
        self.last_write_targets: list[str] = []
        # FACEBD has no implemented command acknowledgement yet. Keep this
        # explicit so callers report an unverified write instead of crashing.
        self.last_write_verified = False
        self.last_command_at = 0.0
        # Classic outbound defaults to FluvalConnect EncodeUtil.encodeMessage,
        # while retaining explicit legacy choices for older controllers.
        self.wire_dialect = wire_dialect if wire_dialect in encryption.DIALECTS else encryption.DIALECT_RANDOM
        self.channel_endian = "be"
        self._classic_session_ready = False
        self._classic_handshake_done = False
        self._product_channel_count: int | None = None
        self._ready_fired = False
        # Connect on first command — do not contend with HA startup BLE.
        self.connect_task = None

    def configure_timing(self, *, ping_interval: int | None = None, active_time: int | None = None) -> None:
        """Update keep-alive timing from options without recreating the client."""
        if ping_interval is not None:
            self._ping_interval = ping_interval
        if active_time is not None:
            self._active_time = active_time

    def _get_characteristic(self, uuid: str) -> BleakGATTCharacteristic | None:
        """Return a characteristic if present, without raising on missing UUIDs."""
        if self.client is None:
            return None
        target = str(uuid).lower()
        try:
            characteristic = self.client.services.get_characteristic(target)
        except BleakError:
            characteristic = None
        if characteristic is not None:
            return characteristic

        # Be defensive around adapters that preserve non-canonical UUID case.
        try:
            for service in self.client.services:
                for characteristic in getattr(service, "characteristics", ()):
                    if str(characteristic.uuid).lower() == target:
                        return characteristic
        except (AttributeError, TypeError, BleakError):
            return None
        return None

    def _find_characteristic(
        self,
        candidates: tuple[str, ...],
        *,
        require_write: bool = False,
        require_notify: bool = False,
        required: bool = True,
    ) -> str | None:
        """Return the first candidate matching the requested properties."""
        for uuid in candidates:
            characteristic = self._get_characteristic(uuid)
            if characteristic is None:
                continue

            properties = set(characteristic.properties)
            if require_write and not properties.intersection(WRITE_PROPERTIES):
                continue
            if require_notify and "notify" not in properties and "indicate" not in properties:
                # Some FACEBD WiFi controllers still accept start_notify on facebd80
                # even when the advertised property list is incomplete.
                if not characteristic.uuid.lower().startswith("facebd80"):
                    continue

            return characteristic.uuid

        if required:
            raise BleakError(f"None of the candidate UUIDs are available: {candidates}")
        return None

    def _find_characteristics(
        self,
        candidates: tuple[str, ...],
        *,
        require_write: bool = False,
        require_notify: bool = False,
    ) -> list[str]:
        """Return all candidates matching the requested properties."""
        found: list[str] = []
        for uuid in candidates:
            characteristic = self._get_characteristic(uuid)
            if characteristic is None:
                continue

            properties = set(characteristic.properties)
            if require_write and not properties.intersection(WRITE_PROPERTIES):
                continue
            if require_notify and "notify" not in properties and "indicate" not in properties:
                if not characteristic.uuid.lower().startswith("facebd80"):
                    continue

            if characteristic.uuid not in found:
                found.append(characteristic.uuid)
        return found

    def _service_uuid_prefixes(self) -> set[str]:
        """Return lowercase service UUID prefixes present on the connected client."""
        if self.client is None:
            return set()
        prefixes: set[str] = set()
        for service in self.client.services:
            uuid = service.uuid.lower()
            prefixes.add(uuid)
            prefixes.add(uuid[:8])
        return prefixes

    async def _resolve_characteristics(self):
        """Resolve the Fluval characteristic profile exposed by this device."""
        service_uuids = self._service_uuid_prefixes()
        has_old = any(uuid.startswith("00001000") for uuid in service_uuids)
        has_mesh = any(uuid.startswith("0000fff0") for uuid in service_uuids)

        # FluvalConnect routes LightType.OLD exclusively through service 1000,
        # write 1001, notify 1002. Do not let unrelated vendor characteristics
        # win merely because they appear earlier in a generic candidate list.
        if has_mesh:
            write_candidates = MESH_COMMAND_WRITE_UUIDS
            notify_candidates = MESH_NOTIFY_UUIDS
        elif has_old:
            write_candidates = CLASSIC_COMMAND_WRITE_UUIDS
            notify_candidates = CLASSIC_NOTIFY_UUIDS
        else:
            write_candidates = COMMAND_WRITE_UUIDS
            notify_candidates = NOTIFY_UUIDS
        self.command_write_uuids = self._find_characteristics(write_candidates, require_write=True)
        if not self.command_write_uuids:
            raise BleakError(f"None of the command UUIDs are available: {write_candidates}")
        self.command_write_uuid = self.command_write_uuids[0]
        self.notify_uuids = self._find_characteristics(notify_candidates, require_notify=True)
        if not self.notify_uuids:
            raise BleakError(f"None of the notify UUIDs are available: {notify_candidates}")
        self.notify_uuid = self.notify_uuids[0]
        # Init write is only needed by the older encrypted BLE protocol.
        self.init_write_uuid = (
            self.command_write_uuid
            if has_old
            else self._find_characteristic(INIT_WRITE_UUIDS, require_write=True, required=False)
        )
        self.wake_read_uuid = self._find_characteristic(WAKE_READ_UUIDS, required=False)
        self.state_read_uuids = self._find_characteristics(WAKE_READ_UUIDS)
        self.write_reg_uuid = self._find_characteristic(CLASSIC_WRITE_REG_UUIDS, require_write=True, required=False)
        self.read_reg_uuid = self._find_characteristic(CLASSIC_READ_REG_UUIDS, required=False)

        write_uuid = self.command_write_uuid.lower()
        self.raw_facebd = write_uuid.startswith("facebd")
        # Mesh uses fff2 with D1+CBOR. Prefer old encrypted framing only when the
        # classic 00001000 service is present (1001 is already preferred in the
        # candidate list when both exist).
        self.raw_mesh = write_uuid.startswith("0000fff2") and (has_mesh or not has_old) and not self.raw_facebd
        _LOGGER.debug(
            "Resolved Fluval GATT profile writes=%s notifies=%s reads=%s init=%s wake=%s "
            "write_reg=%s read_reg=%s raw_facebd=%s raw_mesh=%s",
            self.command_write_uuids,
            self.notify_uuids,
            self.state_read_uuids,
            self.init_write_uuid,
            self.wake_read_uuid,
            self.write_reg_uuid,
            self.read_reg_uuid,
            self.raw_facebd,
            self.raw_mesh,
        )

    async def _ensure_client(self):
        """Connect and subscribe to notifications if needed."""
        if self.client and self.client.is_connected:
            return self.client

        if self.client is not None:
            # Reconnect an existing BleakClient instance first. This avoids the
            # full establish_connection recreation path after ping-timeout
            # disconnects, which noticeably reduces perceived wake-up time.
            for attempt in range(1, CONNECT_RETRIES + 1):
                try:
                    connected = await self.client.connect(timeout=CONNECT_TIMEOUT)
                    if connected:
                        break
                    raise BleakError("connect returned False")
                except (TimeoutError, BleakError, EOFError) as err:
                    self.last_error = f"reconnect attempt {attempt} failed: {type(err).__name__}: {err}"
                    _LOGGER.debug("Fluval reconnect attempt %s failed", attempt, exc_info=err)
                    if attempt < CONNECT_RETRIES:
                        await asyncio.sleep(attempt)
                    else:
                        self.client = None

            if self.client is not None and self.client.is_connected:
                if self.command_write_uuid is None or not self.notify_uuids:
                    await self._resolve_characteristics()
                for uuid in self.notify_uuids:
                    with contextlib.suppress(BleakError):
                        await self.client.start_notify(uuid, self.notify_callback)
                if not self.raw_facebd and not self.raw_mesh and not self._classic_session_ready:
                    await self._async_classic_session_init()
                if self.status_callback:
                    self.status_callback(True)
                self.last_error = None
                return self.client

        # bleak-retry-connector already owns its retry loop. Wrapping it in a
        # second three-attempt loop caused up to twelve attempts and made an
        # ordinary reconnect look hung. Keep one bounded connector cycle.
        try:
            self.client = await establish_connection(
                BleakClient,
                self.device,
                self.device.address,
                disconnected_callback=self._on_disconnected,
                max_attempts=CONNECT_RETRIES,
                timeout=CONNECT_TIMEOUT,
            )
        except (TimeoutError, BleakError, EOFError) as err:
            self.last_error = f"connect failed: {type(err).__name__}: {err}"
            await self._safe_disconnect()
            raise

        await self._resolve_characteristics()
        if not self.raw_facebd and not self.raw_mesh:
            await self._async_request_classic_mtu()
        for uuid in self.notify_uuids:
            with contextlib.suppress(BleakError):
                await self.client.start_notify(uuid, self.notify_callback)

        if not self.raw_facebd and not self.raw_mesh:
            await self._async_classic_session_init()

        if self.status_callback:
            self.status_callback(True)
        self.last_error = None

        if self.ready_callback and not self._ready_fired:
            self._ready_fired = True
            try:
                await self.ready_callback()
            except Exception as err:  # pylint: disable=broad-except
                _LOGGER.warning("Fluval post-connect callback failed", exc_info=err)

        return self.client

    def _on_disconnected(self, client: BleakClient) -> None:
        """Update state immediately and restore an opted-in persistent link."""
        if client is not self.client:
            return
        self._classic_session_ready = False
        self._classic_handshake_done = False
        self._ready_fired = False
        if self.status_callback:
            self.status_callback(False)
        if self._stopping or self._active_time != 0:
            return
        if self.connect_task and not self.connect_task.done():
            return
        self.connect_task = asyncio.create_task(self._async_restore_persistent_connection())

    async def _async_restore_persistent_connection(self) -> None:
        """Reconnect once after an unexpected persistent-session drop."""
        try:
            async with self._command_lock:
                if self._stopping or self._active_time != 0:
                    return
                await self._ensure_client()
                self.ping()
        except (TimeoutError, BleakError, EOFError) as err:
            self.last_error = f"persistent reconnect failed: {type(err).__name__}: {err}"
            _LOGGER.debug("Fluval persistent reconnect failed", exc_info=err)
        finally:
            self.connect_task = None

    async def _async_request_classic_mtu(self) -> None:
        """Request the OLD-light MTU before enabling notifications (APK order)."""
        if self.client is None:
            return
        with contextlib.suppress(Exception):
            for name in ("exchange_mtu", "request_mtu"):
                exchange = getattr(self.client, name, None)
                if callable(exchange):
                    await exchange(CLASSIC_MTU)
                    break

    async def ensure_connected(self) -> bool:
        """Connect far enough to resolve the live GATT profile."""
        try:
            await self._ensure_client()
            return True
        except (TimeoutError, BleakError) as err:
            _LOGGER.debug("Fluval connect for profile resolution failed", exc_info=err)
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.warning(
                "Unexpected Fluval connect failure during profile resolution",
                exc_info=err,
            )

        if self.status_callback:
            self.status_callback(False)
        return False

    def extend_session(self) -> None:
        """Extend the idle disconnect deadline while the lamp is still advertising."""
        if not self.ping_task or self._active_time == 0:
            return
        self.ping_time = max(self.ping_time, time.time() + self._active_time)

    def ping(self):
        """Start the ping task to periodically talk to the Fluval."""
        self._stopping = False
        if self._active_time == 0:
            self.ping_time = float("inf")
        else:
            self.ping_time = time.time() + self._active_time

        if not self.ping_task:
            self.ping_task = asyncio.create_task(self._ping_loop())

    def notify_callback(self, sender: BleakGATTCharacteristic, data: bytearray):
        """Handle packets sent by the Fluval.

        Classic path matches ``LightDetailActivity.onCharacteristicChanged`` for
        OLD: ``decodeMessage`` each notify; if plaintext starts with ``0x68``
        clear the receive cache; append; only act when
        ``analyticLightParameterToOld`` would succeed.
        """
        sender_uuid = getattr(sender, "uuid", str(sender))
        _LOGGER.debug("Got raw Fluval notification from %s: %s", sender_uuid, to_hex(data))
        if self.raw_facebd or self.raw_mesh:
            _LOGGER.debug("Got raw Fluval data (facebd=%s mesh=%s): %s", self.raw_facebd, self.raw_mesh, to_hex(data))
            if self.update_callback:
                self.update_callback(bytes(data))
            return

        decrypted = encryption.decrypt(data)
        if not decrypted:
            return

        # APK: if (bArrDecodeMessage[0] == 104) cache.clear(); then append all.
        if decrypted[0] == 0x68:
            self.receive_buffer = b""
        self.receive_buffer += decrypted

        if not protocol.old_receive_frame_ready(self.receive_buffer, channel_count=self._product_channel_count):
            return

        payload = self.receive_buffer
        self.receive_buffer = b""
        _LOGGER.debug("Got all data: %s ", to_hex(payload))
        if self.update_callback:
            self.update_callback(payload)

    async def _connect(self):
        """Connect to the Fluval and subscribe to notifications."""
        try:
            client = await self._ensure_client()

            if self.wake_read_uuid:
                with contextlib.suppress(BleakError):
                    await client.read_gatt_char(self.wake_read_uuid)

            if self.raw_facebd:
                await self.request_state()
            elif self.raw_mesh:
                await self._write_packet(self.command_write_uuid, protocol.mesh_read_params_packet())
            # Classic: clock + 6805 already sent in _async_classic_session_init.

            if self.ready_callback:
                try:
                    await self.ready_callback()
                except Exception as err:  # pylint: disable=broad-except
                    _LOGGER.warning("Fluval post-connect callback failed", exc_info=err)
        except (TimeoutError, BleakError) as err:
            _LOGGER.debug("Fluval initial connection failed", exc_info=err)
            if self.status_callback:
                self.status_callback(False)
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.warning("Unexpected Fluval initial connection error", exc_info=err)
            if self.status_callback:
                self.status_callback(False)

    async def _async_classic_session_init(self) -> None:
        """Classic connect — FluvalConnect OLD path only.

        ``setNotificationToOldBle``: MTU 220 + notify 1002.
        ``onNotificationChanged``: Affair clock ``680E`` then ``6805``.
        No ``1005`` / ``0x0F`` / ``0x47`` — FluvalConnect light UI never does that.
        """
        if self._classic_session_ready or self.raw_facebd or self.raw_mesh:
            return
        if self.client is None or not self.init_write_uuid:
            return

        await self._write_packet(self.init_write_uuid, protocol.old_clock_packet())
        await asyncio.sleep(0.2)
        await self._write_packet(self.init_write_uuid, protocol.old_read_params_packet())
        # The APK routes initialization and UI commands through the same
        # AffairManager queue, which enforces a 200 ms inter-packet delay.
        # Record 6805 as the latest command so send_sequence also waits before
        # the first user command; without this, power-on was written ~1 ms
        # after 6805 and this controller ignored it.
        self.last_command_at = time.time()
        self._classic_session_ready = True
        self._classic_handshake_done = False
        _LOGGER.info(
            "Fluval classic session ready for %s (APK: MTU + notify + clock + 6805, encode=%s)",
            self.device.address,
            self.wire_dialect,
        )

    @property
    def classic_session_ready(self) -> bool:
        """Return whether the APK classic clock/read initialization completed."""
        return self._classic_session_ready

    async def _ping_loop(self):
        """Keep the BLE link warm with periodic wake reads."""
        loop = asyncio.get_event_loop()
        while time.time() < self.ping_time and not self._stopping:
            try:
                client = await self._ensure_client()

                while time.time() < self.ping_time and not self._stopping:
                    if self.wake_read_uuid:
                        with contextlib.suppress(BleakError):
                            await client.read_gatt_char(self.wake_read_uuid)

                    self.ping_future = loop.create_future()
                    loop.call_later(self._ping_interval, self.ping_future.cancel)
                    with contextlib.suppress(asyncio.CancelledError, TimeoutError):
                        await self.ping_future

                if self._stopping:
                    break

                # Idle window expired. Never tear down while a command holds
                # the lock — extend the window and keep the session.
                if self._command_lock.locked():
                    self.ping_time = time.time() + max(self._ping_interval, 5)
                    continue

                if self._active_time == 0:
                    self.ping_time = float("inf")
                    continue

                async with self._command_lock:
                    if self.client is not None:
                        with contextlib.suppress(BleakError, TimeoutError):
                            await self.client.disconnect()
                        self._classic_session_ready = False
                        self._classic_handshake_done = False
                    if self.status_callback:
                        self.status_callback(False)
            except TimeoutError:
                pass
            except asyncio.CancelledError:
                break
            except BleakError as e:
                _LOGGER.debug("ping error", exc_info=e)
                self.client = None
                if self.status_callback:
                    self.status_callback(False)
                await asyncio.sleep(1)
            except Exception as e:
                _LOGGER.warning("ping error", exc_info=e)
                self.client = None
                if self.status_callback:
                    self.status_callback(False)
                await asyncio.sleep(1)

        self.ping_task = None

    async def _write_packet(self, uuid: str, data: bytes, *, dialect: str | None = None):
        """Write a packet using FluvalConnect framing for the active profile.

        Classic old BLE (``00001000``): CRC'd plaintext → ≤15-byte chunks →
        APK random-key encode → ``00001001``. Prefer no-response when property
        bit 4 is exposed, matching FluvalConnect; otherwise use response writes.
        """
        del dialect  # Legacy probe arg; outbound uses encrypted_old_frames default.
        characteristic = self._get_characteristic(uuid)
        properties = set(characteristic.properties) if characteristic is not None else set()
        # Aquasky/old-BLE via proxy often ignores write-with-response (#6).
        # Prefer write-without-response when the characteristic allows it.
        if "write-without-response" in properties:
            response = False
        elif "write" in properties:
            response = True
        else:
            response = False
        payloads: list[bytes | bytearray]
        if self.raw_facebd or self.raw_mesh:
            payloads = [data]
        else:
            payloads = [bytes(frame) for frame in protocol.encrypted_old_frames(data, dialect=self.wire_dialect)]

        client = self.client
        if client is None:
            raise BleakError("Fluval BLE client disconnected before write")

        for index, payload in enumerate(payloads):
            log = _LOGGER.info if not self.raw_facebd and not self.raw_mesh else _LOGGER.debug
            log(
                "Writing Fluval packet to %s response=%s chunk=%s/%s raw=%s encrypted=%s",
                uuid,
                response,
                index + 1,
                len(payloads),
                to_hex(data) if index == 0 else "(cont)",
                to_hex(payload),
            )
            await client.write_gatt_char(uuid, data=payload, response=response)
            if index + 1 < len(payloads):
                # Each encoded chunk is a separate APK write request. FluvalConnect
                # configures requestWriteDelayMillis(10) (package delay is 5 ms).
                await asyncio.sleep(CHUNK_WRITE_GAP)

    def set_channel_endian(self, endian: str) -> None:
        """No-op: classic channel commands are always big-endian (APK)."""
        del endian
        self.channel_endian = "be"

    async def request_state(self):
        """Read the current controller state when the protocol supports it."""
        client = await self._ensure_client()

        if self.wake_read_uuid:
            with contextlib.suppress(BleakError):
                await client.read_gatt_char(self.wake_read_uuid)

        if self.raw_mesh and self.command_write_uuid:
            await self._write_packet(self.command_write_uuid, protocol.mesh_read_params_packet())
            return

        if self.raw_facebd and self.notify_uuid:
            # Read every available FACEBD state char. Some controllers return
            # only a wake byte on facebd81 and the real CBOR map on facebd80/02.
            for read_uuid in self.state_read_uuids or [self.notify_uuid]:
                try:
                    data = await client.read_gatt_char(read_uuid)
                except BleakError as err:
                    _LOGGER.debug("Fluval state read failed from %s", read_uuid, exc_info=err)
                    continue
                _LOGGER.debug("Read Fluval state from %s: %s", read_uuid, to_hex(data))
                if self.update_callback:
                    self.update_callback(bytes(data))
            return

        if self.init_write_uuid:
            await self._write_packet(self.init_write_uuid, protocol.old_read_params_packet())

    async def send_now(self, data: bytes) -> bool:
        """Connect and write a packet before returning to Home Assistant."""
        return await self.send_sequence([data])

    async def send_sequence(self, packets: list[bytes], *, refresh_state: bool = False) -> bool:
        """Write one or more packets on a single connection (APK Affair-style spacing)."""
        if not packets:
            return True
        async with self._command_lock:
            try:
                client = await self._ensure_client()
                if self.wake_read_uuid:
                    with contextlib.suppress(BleakError):
                        await client.read_gatt_char(self.wake_read_uuid)

                # Prefer the primary write UUID (facebd80 / 1001). Do not spray every FACEBD char.
                write_uuid = self.command_write_uuid
                if not write_uuid:
                    raise BleakError("No Fluval BLE write characteristic resolved")

                wrote_targets: list[str] = []
                for index, data in enumerate(packets):
                    wait_time = self.last_command_at + COMMAND_GAP - time.time()
                    if wait_time > 0:
                        await asyncio.sleep(wait_time)

                    wrote = False
                    for attempt in range(1, WRITE_RETRIES + 1):
                        try:
                            await self._write_packet(write_uuid, data)
                        except (TimeoutError, BleakError, EOFError) as err:
                            self.last_error = (
                                f"write {write_uuid} attempt {attempt} failed: {type(err).__name__}: {err}"
                            )
                            _LOGGER.debug(
                                "Fluval BLE write failed: %s attempt %s packet %s/%s",
                                write_uuid,
                                attempt,
                                index + 1,
                                len(packets),
                                exc_info=err,
                            )
                            if attempt == WRITE_RETRIES:
                                break
                            await asyncio.sleep(WRITE_DELAY)
                        else:
                            wrote = True
                            wrote_targets = [write_uuid]
                            self.last_command_at = time.time()
                            break

                    if not wrote:
                        raise BleakError("No Fluval BLE write target accepted the command")

                self.last_write_targets = wrote_targets
                _LOGGER.debug(
                    "Fluval wrote %s packet(s) on %s",
                    len(packets),
                    wrote_targets,
                )

                self.ping()

                if refresh_state and (self.raw_facebd or self.raw_mesh):
                    await asyncio.sleep(POST_WRITE_STATE_DELAY)
                    with contextlib.suppress(BleakError):
                        await self.request_state()

                self.last_error = None
                return True
            except (TimeoutError, BleakError, EOFError) as err:
                self.last_error = f"{type(err).__name__}: {err}"
                _LOGGER.warning("Fluval BLE write failed", exc_info=err)
            except Exception as err:  # pylint: disable=broad-except
                self.last_error = f"{type(err).__name__}: {err}"
                _LOGGER.warning("Unexpected Fluval BLE write failure", exc_info=err)

            if self.status_callback:
                self.status_callback(False)
            await self._safe_disconnect()
            self._classic_session_ready = False
            self._classic_handshake_done = False
            self._ready_fired = False
            return False

    async def _safe_disconnect(self):
        """Disconnect the underlying BLE client without masking the original error."""
        if self.client:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.client.disconnect(), timeout=5)
            self.client = None
        self._classic_session_ready = False
        self._classic_handshake_done = False

    async def disconnect(self):
        """Disconnect from the Fluval and stop background work."""
        self._stopping = True
        self.ping_time = 0

        if self.ping_future:
            self.ping_future.cancel()

        if self.ping_task:
            self.ping_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, TimeoutError):
                await asyncio.wait_for(self.ping_task, timeout=3)
            self.ping_task = None

        if self.connect_task:
            self.connect_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, TimeoutError):
                await asyncio.wait_for(self.connect_task, timeout=3)
            self.connect_task = None

        with contextlib.suppress(Exception):
            await asyncio.wait_for(self._safe_disconnect(), timeout=6)

        if self.status_callback:
            self.status_callback(False)

    async def stop(self):
        """Compatibility wrapper for the integration unload path."""
        await self.disconnect()


def decrypt(data: bytearray) -> bytes:
    """Decrypt a packet that has been received by the Fluval."""
    return encryption.decrypt(data)


def to_hex(data: bytes | bytearray) -> str:
    """Print a byte array as hex strings for debugging."""
    return " ".join(format(x, "02x") for x in data)
