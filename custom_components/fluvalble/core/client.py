"""Client class connecting the Fluval BLE Entity to a bluetooth connection."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import contextlib
import logging
import time

from bleak import BleakClient, BleakError, BleakGATTCharacteristic, BLEDevice
from bleak_retry_connector import establish_connection

from . import encryption, protocol

_LOGGER = logging.getLogger(__name__)

ACTIVE_TIME = 120
CONNECT_TIMEOUT = 20
CONNECT_RETRIES = 3
WRITE_RETRIES = 2
WRITE_DELAY = 0.3
COMMAND_GAP = 0.75
POST_WRITE_STATE_DELAY = 0.8

# Official FluvalConnect GATT map (BleSppGattAttributes):
#   facebd80 = WiFi-over-BLE write + notify (raw CBOR, keys 103+)
#   facebd01 = FACEBD BLE write path
#   facebd02 = FACEBD BLE read/notify path
#   0000fff0 / fff2 / fff1 = mesh (0xD1 + CBOR)
# The working probe script and Fluval app both write WiFi CBOR to facebd80.
# Preferring facebd02/facebd01 first for commands sends correct CBOR packets to
# the wrong characteristic, so the light never reacts.
WIFI_COMMAND_WRITE_UUIDS = (
    "FACEBD80-7261-6262-6974-696F74626C65",
    "FACEBD80-0000-1000-8000-00805F9B34FB",
)
BLE_COMMAND_WRITE_UUIDS = (
    "FACEBD01-7261-6262-6974-696F74626C65",
    "FACEBD01-0000-1000-8000-00805F9B34FB",
    "FACEBD02-7261-6262-6974-696F74626C65",
    "FACEBD02-0000-1000-8000-00805F9B34FB",
    "00001001-0000-1000-8000-00805F9B34FB",
    "0000FFF2-0000-1000-8000-00805F9B34FB",
)
# facebd02 is intentionally excluded: it is the BLE read/notify char, not the
# WiFi CBOR write target used by on/off/mode/channel packets.
COMMAND_WRITE_UUIDS = WIFI_COMMAND_WRITE_UUIDS + BLE_COMMAND_WRITE_UUIDS
NOTIFY_UUIDS = (
    "FACEBD80-7261-6262-6974-696F74626C65",
    "FACEBD80-0000-1000-8000-00805F9B34FB",
    "FACEBD02-7261-6262-6974-696F74626C65",
    "FACEBD02-0000-1000-8000-00805F9B34FB",
    "FACEBD03-7261-6262-6974-696F74626C65",
    "FACEBD03-0000-1000-8000-00805F9B34FB",
    "00001002-0000-1000-8000-00805F9B34FB",
    "0000FFF1-0000-1000-8000-00805F9B34FB",
)
INIT_WRITE_UUIDS = (
    "FACEBD01-7261-6262-6974-696F74626C65",
    "FACEBD01-0000-1000-8000-00805F9B34FB",
    "00001001-0000-1000-8000-00805F9B34FB",
    "0000FFF2-0000-1000-8000-00805F9B34FB",
)
WAKE_READ_UUIDS = (
    "FACEBD81-7261-6262-6974-696F74626C65",
    "FACEBD81-0000-1000-8000-00805F9B34FB",
    "FACEBD80-7261-6262-6974-696F74626C65",
    "FACEBD80-0000-1000-8000-00805F9B34FB",
    "FACEBD02-7261-6262-6974-696F74626C65",
    "FACEBD02-0000-1000-8000-00805F9B34FB",
    "00001004-0000-1000-8000-00805F9B34FB",
    "0000FFF6-0000-1000-8000-00805F9B34FB",
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
    ) -> None:
        """Initialize the client."""
        self.device = device
        self.status_callback = status_callback
        self.update_callback = update_callback
        self.ready_callback = ready_callback
        self._ping_interval = ping_interval
        self._active_time = active_time

        self.client: BleakClient | None = None

        self.ping_future: asyncio.Future | None = None
        self.ping_task: asyncio.Task | None = None
        self.ping_time = 0

        self.connect_task: asyncio.Task | None = None

        self.receive_buffer = b""
        self.notify_uuid = None
        self.notify_uuids: list[str] = []
        self.init_write_uuid = None
        self.command_write_uuid = None
        self.command_write_uuids: list[str] = []
        self.wake_read_uuid = None
        self.state_read_uuids: list[str] = []
        self.raw_facebd = False
        self.raw_mesh = False
        self._command_lock = asyncio.Lock()
        self.last_error: str | None = None
        self.last_write_targets: list[str] = []
        self.last_command_at = 0.0
        self.connect_task = asyncio.create_task(self._connect())

    def configure_timing(self, *, ping_interval: int | None = None, active_time: int | None = None) -> None:
        """Update keep-alive timing from options without recreating the client."""
        if ping_interval is not None:
            self._ping_interval = ping_interval
        if active_time is not None:
            self._active_time = active_time

    def _get_characteristic(self, uuid: str) -> BleakGATTCharacteristic | None:
        """Return a characteristic if present, without raising on missing UUIDs."""
        try:
            return self.client.services.get_characteristic(uuid)
        except BleakError:
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
        self.command_write_uuids = self._find_characteristics(COMMAND_WRITE_UUIDS, require_write=True)
        if not self.command_write_uuids:
            raise BleakError(f"None of the command UUIDs are available: {COMMAND_WRITE_UUIDS}")
        self.command_write_uuid = self.command_write_uuids[0]
        self.notify_uuids = self._find_characteristics(NOTIFY_UUIDS, require_notify=True)
        if not self.notify_uuids:
            raise BleakError(f"None of the notify UUIDs are available: {NOTIFY_UUIDS}")
        self.notify_uuid = self.notify_uuids[0]
        # Init write is only needed by the older encrypted BLE protocol.
        self.init_write_uuid = self._find_characteristic(INIT_WRITE_UUIDS, require_write=True, required=False)
        self.wake_read_uuid = self._find_characteristic(WAKE_READ_UUIDS, required=False)
        self.state_read_uuids = self._find_characteristics(WAKE_READ_UUIDS)

        write_uuid = self.command_write_uuid.lower()
        self.raw_facebd = write_uuid.startswith("facebd")
        service_uuids = self._service_uuid_prefixes()
        has_old = any(uuid.startswith("00001000") for uuid in service_uuids)
        has_mesh = any(uuid.startswith("0000fff0") for uuid in service_uuids)
        # Mesh uses fff2 with D1+CBOR. Prefer old encrypted framing only when the
        # classic 00001000 service is present (1001 is already preferred in the
        # candidate list when both exist).
        self.raw_mesh = write_uuid.startswith("0000fff2") and (has_mesh or not has_old) and not self.raw_facebd
        _LOGGER.debug(
            "Resolved Fluval GATT profile writes=%s notifies=%s reads=%s init=%s wake=%s "
            "raw_facebd=%s raw_mesh=%s",
            self.command_write_uuids,
            self.notify_uuids,
            self.state_read_uuids,
            self.init_write_uuid,
            self.wake_read_uuid,
            self.raw_facebd,
            self.raw_mesh,
        )

    async def _ensure_client(self):
        """Connect and subscribe to notifications if needed."""
        if self.client and self.client.is_connected:
            return self.client

        last_error: Exception | None = None
        for attempt in range(1, CONNECT_RETRIES + 1):
            try:
                self.client = await establish_connection(
                    BleakClient, self.device, self.device.address, timeout=CONNECT_TIMEOUT
                )
                break
            except (TimeoutError, BleakError, EOFError) as err:
                last_error = err
                self.last_error = f"connect attempt {attempt} failed: {type(err).__name__}: {err}"
                _LOGGER.debug("Fluval connect attempt %s failed", attempt, exc_info=err)
                await self._safe_disconnect()
                await asyncio.sleep(attempt)
        else:
            raise BleakError(f"Unable to connect to Fluval: {last_error}")

        await self._resolve_characteristics()
        for uuid in self.notify_uuids:
            with contextlib.suppress(BleakError):
                await self.client.start_notify(uuid, self.notify_callback)

        if self.status_callback:
            self.status_callback(True)
        self.last_error = None

        return self.client

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

    def ping(self):
        """Start the ping task to periodically talk to the Fluval."""
        self.ping_time = time.time() + self._active_time

        if not self.ping_task:
            self.ping_task = asyncio.create_task(self._ping_loop())

    def notify_callback(self, sender: BleakGATTCharacteristic, data: bytearray):
        """Handle packets sent by the Fluval."""
        if self.raw_facebd or self.raw_mesh:
            _LOGGER.debug("Got raw Fluval data (facebd=%s mesh=%s): %s", self.raw_facebd, self.raw_mesh, to_hex(data))
            if self.update_callback:
                self.update_callback(bytes(data))
            return

        decrypted = decrypt(data)
        if len(decrypted) == 17:
            self.receive_buffer += decrypted
        else:
            self.receive_buffer += decrypted
            _LOGGER.debug("Got all data: %s ", to_hex(self.receive_buffer))
            if self.update_callback:
                self.update_callback(self.receive_buffer)
            self.receive_buffer = b""

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
            elif self.init_write_uuid:
                await self._write_packet(self.init_write_uuid, protocol.old_read_params_packet())

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

    async def _ping_loop(self):
        """Keep the BLE link warm with periodic wake reads."""
        loop = asyncio.get_event_loop()
        while time.time() < self.ping_time:
            try:
                client = await self._ensure_client()

                while time.time() < self.ping_time:
                    if self.wake_read_uuid:
                        with contextlib.suppress(BleakError):
                            await client.read_gatt_char(self.wake_read_uuid)

                    self.ping_future = loop.create_future()
                    loop.call_later(self._ping_interval, self.ping_future.cancel)
                    with contextlib.suppress(asyncio.CancelledError):
                        await self.ping_future

                await client.disconnect()
            except TimeoutError:
                pass
            except BleakError as e:
                _LOGGER.debug("ping error", exc_info=e)
            except Exception as e:
                _LOGGER.warning("ping error", exc_info=e)
            finally:
                self.client = None
                if self.status_callback:
                    self.status_callback(False)
                await asyncio.sleep(1)

        self.ping_task = None

    async def _write_packet(self, uuid: str, data: bytes):
        """Write a packet using the right wire format for the active profile."""
        if self.raw_facebd or self.raw_mesh:
            payload = data
        else:
            payload = protocol.encrypted_old_packet(data)

        characteristic = self._get_characteristic(uuid)
        # Prefer write-without-response when available — matches ESPHome
        # fluval_ble_led and fixes Aquasky 2.0 lights that ignore response writes (#6).
        properties = set(characteristic.properties) if characteristic is not None else set()
        if "write-without-response" in properties:
            response = False
        elif "write" in properties:
            response = True
        else:
            response = False

        _LOGGER.debug(
            "Writing Fluval packet to %s response=%s raw=%s encrypted=%s",
            uuid,
            response,
            to_hex(data),
            to_hex(payload),
        )
        await self.client.write_gatt_char(uuid, data=payload, response=response)

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
        async with self._command_lock:
            try:
                client = await self._ensure_client()
                if self.wake_read_uuid:
                    with contextlib.suppress(BleakError):
                        await client.read_gatt_char(self.wake_read_uuid)

                wait_time = self.last_command_at + COMMAND_GAP - time.time()
                if wait_time > 0:
                    await asyncio.sleep(wait_time)

                multi_target = self.raw_facebd
                write_targets = self.command_write_uuids if multi_target else [self.command_write_uuid]
                wrote_targets: list[str] = []
                for uuid in write_targets:
                    for attempt in range(1, WRITE_RETRIES + 1):
                        try:
                            await self._write_packet(uuid, data)
                        except (TimeoutError, BleakError, EOFError) as err:
                            self.last_error = f"write {uuid} attempt {attempt} failed: " f"{type(err).__name__}: {err}"
                            _LOGGER.debug(
                                "Fluval BLE write target failed: %s attempt %s",
                                uuid,
                                attempt,
                                exc_info=err,
                            )
                            if attempt == WRITE_RETRIES:
                                break
                            await asyncio.sleep(WRITE_DELAY)
                        else:
                            wrote_targets.append(uuid)
                            break
                    if wrote_targets and not multi_target:
                        break
                    if wrote_targets and multi_target:
                        await asyncio.sleep(WRITE_DELAY)

                if not wrote_targets:
                    raise BleakError("No Fluval BLE write target accepted the command")

                self.last_write_targets = wrote_targets
                self.last_command_at = time.time()
                _LOGGER.debug("Fluval write completed on targets: %s", wrote_targets)

                # Keep the link warm briefly so HA can continue issuing commands
                # without reconnecting for every toggle.
                self.ping()

                if self.raw_facebd or self.raw_mesh:
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
            return False

    async def _safe_disconnect(self):
        """Disconnect the underlying BLE client without masking the original error."""
        if self.client:
            with contextlib.suppress(Exception):
                await self.client.disconnect()
            self.client = None

    async def disconnect(self):
        """Disconnect from the Fluval and stop background work."""
        self.ping_time = 0

        if self.ping_future:
            self.ping_future.cancel()

        if self.ping_task:
            self.ping_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.ping_task
            self.ping_task = None

        if self.connect_task:
            self.connect_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.connect_task

        await self._safe_disconnect()

        if self.status_callback:
            self.status_callback(False)

    async def stop(self):
        """Compatibility wrapper for the integration unload path."""
        await self.disconnect()


def decrypt(data: bytearray) -> bytearray:
    """Decrypt a packet that has been received by the Fluval."""
    return encryption.decrypt(data)


def to_hex(data: bytes) -> str:
    """Print a byte array as hex strings for debugging."""
    return " ".join(format(x, "02x") for x in data)
