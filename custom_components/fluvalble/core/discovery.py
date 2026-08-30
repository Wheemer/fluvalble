"""Bluetooth discovery helpers for Fluval BLE lights."""

from __future__ import annotations

import re
from typing import Any

from bleak import AdvertisementData

from .protocol import product_id_from_manufacturer_data

# Fluval/Hagen manufacturer/company ID present in Fluval LED advertisements.
# This identifies the vendor for discovery; it does not identify the lamp's
# GATT protocol family.
FLUVAL_MANUFACTURER_IDS = frozenset({12592})

# Exact Fluval GATT / FACEBD service UUIDs. Do NOT match generic prefixes like
# 0000fff0 (common on many BLE mesh devices) — that floods discovery prompts.
FLUVAL_SERVICE_UUIDS = frozenset(
    {
        "00001000-0000-1000-8000-00805f9b34fb",
        "00001002-0000-1000-8000-00805f9b34fb",
        "facebd00-7261-6262-6974-696f74626c65",
        "facebd00-0000-1000-8000-00805f9b34fb",
    }
)
CLASSIC_FLUVAL_SERVICE_UUIDS = frozenset(
    {
        "00001000-0000-1000-8000-00805f9b34fb",
        "00001002-0000-1000-8000-00805f9b34fb",
    }
)
FACEBD_FLUVAL_SERVICE_UUIDS = frozenset(
    {
        "facebd00-7261-6262-6974-696f74626c65",
        "facebd00-0000-1000-8000-00805f9b34fb",
    }
)

# Name tokens that are Fluval-branded on their own.
_FLUVAL_BRAND_NAMES = ("fluval", "aquasky", "plantpro")

# Plant/Marine/Reef Fluval advertisements look like "Plant 3.0_AABB", not
# arbitrary "plant sensor" / "marine radio" devices. Require a Fluval-style
# suffix (version, Nano, or underscore/hyphen serial).
_SERIES_NAME_RE = re.compile(
    r"^(?:plant\s*pro|plant|marine|reef)"
    r"(?:\s*nano|\s*(?:pro|[234](?:\.0)?))?"
    r"[_\-][a-z0-9]{3,}$",
    re.IGNORECASE,
)

CONF_MODEL = "model"
CONF_SERVICE_UUIDS = "service_uuids"
CONF_SERVICE_DATA = "service_data"
CONF_MANUFACTURER_DATA = "manufacturer_data"


def _data_as_hex(data: bytes | bytearray) -> str:
    """Return compact hex for storing BLE payloads in config entries."""
    return bytes(data).hex()


def _advertised_protocol_keys(advertisement: AdvertisementData) -> list[str]:
    """Return service UUIDs plus service-data UUID keys in lowercase."""
    return [str(key).lower() for key in (list(advertisement.service_uuids) + list(advertisement.service_data))]


def has_facebd_advertisement(advertisement: AdvertisementData | None) -> bool:
    """Return whether the advertisement exposes a FACEBD service."""
    if advertisement is None:
        return False
    return any(uuid.startswith("facebd") for uuid in _advertised_protocol_keys(advertisement))


def has_mesh_advertisement(advertisement: AdvertisementData | None) -> bool:
    """Return whether the advertisement exposes the mesh fff0 service."""
    if advertisement is None:
        return False
    return any(uuid.startswith("0000fff0") for uuid in _advertised_protocol_keys(advertisement))


def has_fluval_manufacturer_data(advertisement: AdvertisementData | None) -> bool:
    """Return whether an advertisement contains Fluval manufacturer data."""
    if advertisement is None:
        return False
    return bool(FLUVAL_MANUFACTURER_IDS.intersection(advertisement.manufacturer_data))


def has_fluval_service_uuid(advertisement: AdvertisementData | None) -> bool:
    """Return whether a strong Fluval service/manufacturer signal is advertised."""
    if advertisement is None:
        return False
    keys = _advertised_protocol_keys(advertisement)

    # FACEBD UUID variants are Fluval-specific enough to match on their own.
    if any(key in FACEBD_FLUVAL_SERVICE_UUIDS or key.startswith("facebd") for key in keys):
        return True

    # The classic 00001000/00001002 UUIDs are not unique in the wild; at least
    # one VEEPEAK OBD2 dongle advertises 00001000 and was falsely discovered as
    # a Fluval light. Require the APK-known Fluval manufacturer payload too.
    if any(key in CLASSIC_FLUVAL_SERVICE_UUIDS for key in keys):
        return (
            has_fluval_manufacturer_data(advertisement)
            and product_id_from_manufacturer_data(advertisement.manufacturer_data) is not None
        )

    return False


def name_looks_fluval(name: str | None) -> bool:
    """Return whether a BLE local name matches Fluval light naming."""
    lowered = (name or "").strip().lower()
    if not lowered or lowered == "unknown":
        return False
    if any(lowered.startswith(token) for token in _FLUVAL_BRAND_NAMES):
        return True
    # Require Fluval-style series names (Plant 3.0_… / Marine_…), not bare "plant".
    if _SERIES_NAME_RE.match(lowered):
        return True
    return False


def is_likely_fluval(
    name: str | None,
    advertisement: AdvertisementData | None = None,
) -> bool:
    """Return whether an advertisement looks like a Fluval LED controller.

    Strict on purpose: Home Assistant discovery prompts fire for every
    matcher hit. Generic name substrings (plant/marine) and common UUIDs
    (fff0 mesh) must not qualify alone.
    """
    if name_looks_fluval(name):
        return True
    return has_fluval_service_uuid(advertisement)


def detect_model(name: str | None, advertisement: AdvertisementData | None) -> str:
    """Infer the device model shown in Home Assistant DeviceInfo.

    Prefer the BLE local name when it looks Fluval-branded — that string is
    the model/serial the lamp actually advertises (e.g. ``Plant 3.0_AABBCC``)
    and is what users expect in the device header.
    """
    display_name = (name or "").strip()
    if display_name and name_looks_fluval(display_name):
        return display_name

    facebd = has_facebd_advertisement(advertisement)
    if has_fluval_service_uuid(advertisement):
        if facebd:
            return "AquaSky 3.0"
        if has_mesh_advertisement(advertisement):
            return "Fluval Mesh"
        return "Fluval LED"

    return "Unknown Fluval LED"


def discovery_metadata(name: str | None, advertisement: AdvertisementData) -> dict[str, Any]:
    """Build config-entry metadata from the latest BLE advertisement."""
    return {
        CONF_MODEL: detect_model(name, advertisement),
        CONF_SERVICE_UUIDS: list(advertisement.service_uuids),
        CONF_SERVICE_DATA: {key: _data_as_hex(value) for key, value in advertisement.service_data.items()},
        CONF_MANUFACTURER_DATA: {
            str(key): _data_as_hex(value) for key, value in advertisement.manufacturer_data.items()
        },
    }
