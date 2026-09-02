"""
Tests for config flow helpers — MAC normalisation, validation, and title generation.

All HA stubs are registered by conftest.py before this module loads.
"""

import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import voluptuous as vol

from homeassistant import config_entries

# conftest.py registers all stubs before collection; just ensure path is set.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from custom_components.fluvalble import config_flow as config_flow_module
from custom_components.fluvalble import _active_time_from_options, async_migrate_entry
from custom_components.fluvalble.config_flow import (
    MANUAL_ENTRY,
    ConfigFlow,
    InvalidFormat,
    OptionsFlowHandler,
    _device_display_name,
    _format_bluetooth_mac,
    _get_discovered_devices,
    _is_likely_fluval,
    _options_for_form,
    normalize_mac,
    unique_id_from_mac,
    validate_active_time,
    validate_input,
    MAC_REGEX,
)

MAC = "AA:BB:CC:DD:EE:FF"


def _service_info(
    *,
    address: str = MAC,
    name: str = "Fluval Plant 3.0",
    local_name: str | None = "Fluval Plant 3.0",
):
    advertisement = SimpleNamespace(
        local_name=local_name,
        manufacturer_data={},
        service_data={},
        service_uuids=[],
        rssi=-55,
    )
    return SimpleNamespace(
        address=address,
        name=name,
        advertisement=advertisement,
        device=SimpleNamespace(address=address),
        source="scanner-source",
    )


def _flow(entries=()):
    flow = ConfigFlow()
    flow.hass = SimpleNamespace()
    flow.context = {}
    flow._async_current_entries = MagicMock(return_value=list(entries))
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()
    flow.async_abort = MagicMock(side_effect=lambda **kwargs: {"type": "abort", **kwargs})
    flow.async_create_entry = MagicMock(side_effect=lambda **kwargs: {"type": "create_entry", **kwargs})
    flow.async_show_form = MagicMock(side_effect=lambda **kwargs: {"type": "form", **kwargs})
    return flow


def test_options_flow_uses_home_assistant_reload_helper():
    """Options changes rely on HA's single automatic reload path."""
    assert issubclass(OptionsFlowHandler, config_entries.OptionsFlowWithReload)


def test_options_flow_uses_saved_values_as_suggestions():
    """Stored options are supplied through HA's suggested-value helper."""
    options = {
        "lamp_profile": "plant",
        "ping_interval": 15,
        "active_time": 0,
    }
    flow = OptionsFlowHandler()
    flow.config_entry.options = options
    suggested_schema = object()
    flow.add_suggested_values_to_schema = MagicMock(return_value=suggested_schema)
    flow.async_show_form = MagicMock(return_value={"type": "form"})

    result = asyncio.run(flow.async_step_init())

    assert result == {"type": "form"}
    flow.add_suggested_values_to_schema.assert_called_once()
    assert flow.add_suggested_values_to_schema.call_args.args[1] == {
        "lamp_profile": "plant",
        "ping_interval": 15,
        "active_time": 0,
    }
    flow.async_show_form.assert_called_once_with(step_id="init", data_schema=suggested_schema)


def test_options_flow_submission_is_owned_by_reload_helper():
    """The handler preserves internal options; its HA base class owns the reload."""
    flow = OptionsFlowHandler()
    flow.config_entry.options = {
        "active_time": 0,
        "wire_dialect": "rand0",
    }
    flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})
    submitted = {
        "lamp_profile": "auto",
        "ping_interval": 10,
        "active_time": 120,
    }

    result = asyncio.run(flow.async_step_init(submitted))

    assert result == {"type": "create_entry"}
    flow.async_create_entry.assert_called_once_with(
        title="",
        data={**submitted, "wire_dialect": "rand0"},
    )


def test_options_flow_rejects_connection_windows_between_one_and_twenty_nine():
    """The serializable numeric schema retains the documented validation gap."""
    flow = OptionsFlowHandler()
    suggested_schema = object()
    flow.add_suggested_values_to_schema = MagicMock(return_value=suggested_schema)
    flow.async_show_form = MagicMock(return_value={"type": "form"})
    submitted = {
        "lamp_profile": "auto",
        "ping_interval": 10,
        "active_time": 1,
    }

    result = asyncio.run(flow.async_step_init(submitted))

    assert result == {"type": "form"}
    flow.async_show_form.assert_called_once_with(
        step_id="init",
        data_schema=suggested_schema,
        errors={"active_time": "invalid_active_time"},
    )


class TestActiveTimeSchema:
    @pytest.mark.parametrize("value", [0, 30, 120, 600])
    def test_accepts_persistent_or_bounded_idle_window(self, value):
        assert validate_active_time(value) == value

    @pytest.mark.parametrize("value", [-1, 1, 29, 601])
    def test_rejects_churn_prone_or_out_of_range_values(self, value):
        with pytest.raises(vol.Invalid):
            validate_active_time(value)

    @pytest.mark.parametrize("value", [None, "invalid"])
    def test_rejects_non_integer_values(self, value):
        with pytest.raises(vol.Invalid, match="must be an integer"):
            validate_active_time(value)

    def test_short_lived_checkbox_options_are_translated_for_form(self):
        assert _options_for_form(
            {
                "lamp_profile": "marine",
                "ping_interval": 20,
                "always_connected": False,
                "idle_timeout": 300,
            }
        ) == {
            "lamp_profile": "marine",
            "ping_interval": 20,
            "active_time": 300,
        }

    def test_short_lived_always_connected_option_becomes_zero(self):
        assert _options_for_form(
            {
                "lamp_profile": "aquasky",
                "ping_interval": 10,
                "always_connected": True,
                "idle_timeout": 120,
            }
        ) == {
            "lamp_profile": "aquasky",
            "ping_interval": 10,
            "active_time": 0,
        }

    @pytest.mark.parametrize(
        ("options", "expected"),
        [
            ({"active_time": 0}, 0),
            ({"active_time": 180}, 180),
            ({"always_connected": True, "idle_timeout": 120}, 0),
            ({"always_connected": False, "idle_timeout": 300}, 300),
            ({}, 120),
        ],
    )
    def test_runtime_accepts_numeric_and_short_lived_options(self, options, expected):
        assert _active_time_from_options(options) == expected


def test_version_one_entry_migrates_without_changing_options():
    update_entry = MagicMock()
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=update_entry))
    entry = SimpleNamespace(version=1, options={"active_time": 0})

    assert asyncio.run(async_migrate_entry(hass, entry)) is True
    update_entry.assert_called_once_with(entry, version=2)


def test_version_two_entry_requires_no_migration():
    update_entry = MagicMock()
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=update_entry))
    entry = SimpleNamespace(version=2, options={"always_connected": True})

    assert asyncio.run(async_migrate_entry(hass, entry)) is True
    update_entry.assert_not_called()


class TestNormalizeMac:
    def test_already_normalized(self):
        assert normalize_mac("AA:BB:CC:DD:EE:FF") == "AA:BB:CC:DD:EE:FF"

    def test_lowercase(self):
        assert normalize_mac("aa:bb:cc:dd:ee:ff") == "AA:BB:CC:DD:EE:FF"

    def test_hyphens(self):
        assert normalize_mac("AA-BB-CC-DD-EE-FF") == "AA:BB:CC:DD:EE:FF"

    def test_no_separator_12_chars(self):
        assert normalize_mac("AABBCCDDEEFF") == "AA:BB:CC:DD:EE:FF"

    def test_spaces_stripped(self):
        assert normalize_mac("  AA:BB:CC:DD:EE:FF  ") == "AA:BB:CC:DD:EE:FF"

    def test_mixed_case_hyphens(self):
        assert normalize_mac("aa-BB-cc-DD-ee-FF") == "AA:BB:CC:DD:EE:FF"


class TestUniqueIdFromMac:
    def test_lowercase_stable(self):
        assert unique_id_from_mac("B8:80:4F:3D:67:C0") == "b8:80:4f:3d:67:c0"

    def test_matches_discovery_style(self):
        assert unique_id_from_mac("b8:80:4f:3d:67:c0") == unique_id_from_mac("B8:80:4F:3D:67:C0")

    def test_format_helper_falls_back_for_invalid_input(self, monkeypatch):
        monkeypatch.setattr(config_flow_module, "format_mac", MagicMock(side_effect=ValueError))
        assert _format_bluetooth_mac("aa-bb-cc-dd-ee-ff") == MAC


class TestMacRegex:
    @pytest.mark.parametrize(
        "mac",
        [
            "AA:BB:CC:DD:EE:FF",
            "00:11:22:33:44:55",
            "AB:CD:EF:01:23:45",
        ],
    )
    def test_valid_macs(self, mac):
        assert MAC_REGEX.match(mac)

    @pytest.mark.parametrize(
        "mac",
        [
            "AA:BB:CC:DD:EE",  # too short
            "AA:BB:CC:DD:EE:FF:00",  # too long
            "AABBCCDDEEFF",  # no colons
            "ZZ:BB:CC:DD:EE:FF",  # invalid hex
            "",  # empty
        ],
    )
    def test_invalid_macs(self, mac):
        assert not MAC_REGEX.match(mac)


class TestDiscoveryHelpers:
    def test_likely_fluval_uses_advertisement_name(self, monkeypatch):
        matcher = MagicMock(return_value=True)
        monkeypatch.setattr(config_flow_module, "is_likely_fluval", matcher)
        info = _service_info(local_name="Fluval Local")

        assert _is_likely_fluval(info)
        matcher.assert_called_once_with("Fluval Local", info.advertisement)

    def test_likely_fluval_handles_malformed_info(self):
        class MalformedAdvertisement:
            @property
            def local_name(self):
                raise RuntimeError

        info = SimpleNamespace(advertisement=MalformedAdvertisement())
        assert not _is_likely_fluval(info)

    def test_display_name_uses_fallbacks(self):
        info = _service_info(name="", local_name="unknown")
        assert _device_display_name(info, is_fluval=True) == f"Fluval LED ({MAC})"
        assert _device_display_name(None) == "Unknown device"

    def test_display_name_handles_malformed_info(self):
        class MalformedServiceInfo:
            @property
            def advertisement(self):
                raise RuntimeError

        assert _device_display_name(MalformedServiceInfo()) == "Unknown device"

    def test_get_discovered_devices_filters_every_result(self, monkeypatch):
        fluval = _service_info()
        other = _service_info(address="11:22:33:44:55:66", name="Other", local_name="Other")
        monkeypatch.setattr(
            config_flow_module.bluetooth,
            "async_discovered_service_info",
            MagicMock(return_value=[fluval, other]),
        )
        monkeypatch.setattr(config_flow_module, "_is_likely_fluval", lambda info: info is fluval)

        assert asyncio.run(_get_discovered_devices(SimpleNamespace())) == [fluval]

    def test_get_discovered_devices_handles_unavailable_api(self, monkeypatch):
        monkeypatch.delattr(config_flow_module.bluetooth, "async_discovered_service_info")
        assert asyncio.run(_get_discovered_devices(SimpleNamespace())) == []

    def test_get_discovered_devices_handles_bluetooth_failure(self, monkeypatch):
        monkeypatch.setattr(
            config_flow_module.bluetooth,
            "async_discovered_service_info",
            MagicMock(side_effect=RuntimeError),
        )
        assert asyncio.run(_get_discovered_devices(SimpleNamespace())) == []


class TestValidateInput:
    def test_invalid_mac_raises_invalid_format(self):
        with pytest.raises(InvalidFormat):
            asyncio.run(validate_input(SimpleNamespace(), {"mac": "not-a-mac"}))

    def test_offline_device_uses_safe_fallback_title(self, monkeypatch):
        get_last = MagicMock(return_value=None)
        monkeypatch.setattr(config_flow_module.bluetooth, "async_last_service_info", get_last)

        result = asyncio.run(validate_input(SimpleNamespace(), {"mac": MAC.lower()}))

        assert result == {"title": f"Fluval {MAC}", "data": {"mac": MAC}}
        assert get_last.call_count == 2

    def test_discovery_populates_title_and_product_metadata(self, monkeypatch):
        info = _service_info(name="Fluval Advertisement")
        monkeypatch.setattr(config_flow_module.bluetooth, "async_last_service_info", MagicMock(return_value=info))
        metadata = {"model": "Fluval Plant", "product_id": 386}
        decode = MagicMock(return_value=metadata)
        monkeypatch.setattr(config_flow_module, "discovery_metadata", decode)

        result = asyncio.run(validate_input(SimpleNamespace(), {"mac": MAC}, ble_name="Confirmed Name"))

        assert result == {
            "title": "Confirmed Name",
            "data": {"mac": MAC, **metadata},
        }
        decode.assert_called_once_with(info.name, info.advertisement)

    def test_discovery_name_is_used_when_no_confirmed_name(self, monkeypatch):
        info = _service_info(name="Fluval Advertisement", local_name=None)
        monkeypatch.setattr(config_flow_module.bluetooth, "async_last_service_info", MagicMock(return_value=info))
        monkeypatch.setattr(config_flow_module, "discovery_metadata", MagicMock(return_value={}))

        result = asyncio.run(validate_input(SimpleNamespace(), {"mac": MAC}))

        assert result["title"] == "Fluval Advertisement"


class TestConfigFlow:
    def test_existing_mac_matches_unique_id_or_entry_data(self):
        entries = [
            SimpleNamespace(unique_id=None, data={"mac": MAC.lower()}),
            SimpleNamespace(unique_id="11:22:33:44:55:66", data={}),
        ]
        flow = _flow(entries)

        assert flow._mac_already_configured(MAC)
        assert flow._mac_already_configured("11:22:33:44:55:66")
        assert not flow._mac_already_configured("22:33:44:55:66:77")

    def test_bluetooth_discovery_rejects_non_fluval(self, monkeypatch):
        flow = _flow()
        info = _service_info(name="OBD2", local_name="OBD2")
        monkeypatch.setattr(config_flow_module, "is_likely_fluval", MagicMock(return_value=False))

        result = asyncio.run(flow.async_step_bluetooth(info))

        assert result == {"type": "abort", "reason": "not_fluval"}
        flow.async_set_unique_id.assert_awaited_once_with(MAC.lower())

    def test_bluetooth_discovery_aborts_legacy_duplicate(self):
        flow = _flow([SimpleNamespace(unique_id=MAC.upper(), data={})])

        result = asyncio.run(flow.async_step_bluetooth(_service_info()))

        assert result == {"type": "abort", "reason": "already_configured"}

    def test_bluetooth_discovery_shows_confirmation(self, monkeypatch):
        flow = _flow()
        info = _service_info()
        monkeypatch.setattr(config_flow_module, "is_likely_fluval", MagicMock(return_value=True))

        result = asyncio.run(flow.async_step_bluetooth(info))

        assert result["type"] == "form"
        assert result["step_id"] == "bluetooth_confirm"
        assert flow._bluetooth_discovery_info is info
        assert MAC in flow.context["title_placeholders"]["name"]

    def test_bluetooth_confirm_creates_entry(self, monkeypatch):
        flow = _flow()
        flow._bluetooth_discovery_info = _service_info(local_name="Fluval Confirmed")
        validated = {"title": "Fluval Confirmed", "data": {"mac": MAC}}
        monkeypatch.setattr(config_flow_module, "validate_input", AsyncMock(return_value=validated))

        result = asyncio.run(flow.async_step_bluetooth_confirm({}))

        assert result == {"type": "create_entry", **validated}

    @pytest.mark.parametrize(
        ("error", "expected"),
        [(InvalidFormat(), "invalid_format"), (RuntimeError(), "unknown")],
    )
    def test_bluetooth_confirm_reports_validation_errors(self, monkeypatch, error, expected):
        flow = _flow()
        flow._bluetooth_discovery_info = _service_info()
        monkeypatch.setattr(config_flow_module, "validate_input", AsyncMock(side_effect=error))

        result = asyncio.run(flow.async_step_bluetooth_confirm({}))

        assert result["type"] == "form"
        assert result["errors"] == {"base": expected}

    def test_user_can_choose_manual_entry(self):
        flow = _flow()
        flow.async_step_manual = AsyncMock(return_value={"type": "manual"})

        result = asyncio.run(flow.async_step_user({"mac": MANUAL_ENTRY}))

        assert result == {"type": "manual"}

    def test_user_selection_creates_unique_entry(self, monkeypatch):
        flow = _flow()
        validated = {"title": "Fluval", "data": {"mac": MAC}}
        monkeypatch.setattr(config_flow_module, "validate_input", AsyncMock(return_value=validated))

        result = asyncio.run(flow.async_step_user({"mac": MAC.lower()}))

        assert result == {"type": "create_entry", **validated}
        flow.async_set_unique_id.assert_awaited_once_with(MAC.lower())

    def test_user_selection_rejects_legacy_duplicate(self):
        flow = _flow([SimpleNamespace(unique_id=None, data={"mac": MAC.lower()})])

        result = asyncio.run(flow.async_step_user({"mac": MAC}))

        assert result == {"type": "abort", "reason": "already_configured"}

    @pytest.mark.parametrize(
        ("error", "expected"),
        [(InvalidFormat(), "invalid_format"), (RuntimeError(), "unknown")],
    )
    def test_user_selection_reports_validation_errors(self, monkeypatch, error, expected):
        flow = _flow()
        monkeypatch.setattr(config_flow_module, "validate_input", AsyncMock(side_effect=error))
        monkeypatch.setattr(config_flow_module, "_get_discovered_devices", AsyncMock(return_value=[_service_info()]))

        result = asyncio.run(flow.async_step_user({"mac": MAC}))

        assert result["type"] == "form"
        assert result["errors"] == {"base": expected}

    def test_invalid_user_selection_returns_form(self, monkeypatch):
        flow = _flow()
        monkeypatch.setattr(config_flow_module, "_get_discovered_devices", AsyncMock(return_value=[_service_info()]))

        result = asyncio.run(flow.async_step_user({"mac": "invalid"}))

        assert result["type"] == "form"

    def test_user_list_excludes_configured_and_deduplicates_addresses(self, monkeypatch):
        configured = SimpleNamespace(unique_id=MAC.lower(), data={"mac": MAC})
        flow = _flow([configured])
        available = _service_info(
            address="11:22:33:44:55:66",
            name="Fluval Available",
            local_name="Fluval Available",
        )
        duplicate = _service_info(
            address="11:22:33:44:55:66",
            name="Fluval Newer Name",
            local_name="Fluval Newer Name",
        )
        monkeypatch.setattr(
            config_flow_module,
            "_get_discovered_devices",
            AsyncMock(return_value=[_service_info(), available, duplicate]),
        )

        result = asyncio.run(flow.async_step_user())

        assert result["type"] == "form"
        options = flow._device_options({MAC})
        assert MAC not in options
        assert list(options) == ["11:22:33:44:55:66", MANUAL_ENTRY]
        assert options["11:22:33:44:55:66"].startswith("Fluval Newer Name")
        assert result["description_placeholders"] == {"count": "1"}

    def test_user_without_discoveries_goes_directly_to_manual(self, monkeypatch):
        flow = _flow()
        flow.async_step_manual = AsyncMock(return_value={"type": "manual"})
        monkeypatch.setattr(config_flow_module, "_get_discovered_devices", AsyncMock(return_value=[]))

        assert asyncio.run(flow.async_step_user()) == {"type": "manual"}

    def test_manual_entry_rejects_invalid_mac(self):
        flow = _flow()

        result = asyncio.run(flow.async_step_manual({"mac": "invalid"}))

        assert result["type"] == "form"
        assert result["errors"] == {"base": "invalid_format"}

    def test_manual_entry_initial_form(self):
        flow = _flow()

        result = asyncio.run(flow.async_step_manual())

        assert result["type"] == "form"
        assert result["errors"] == {}

    def test_manual_entry_rejects_legacy_duplicate(self):
        flow = _flow([SimpleNamespace(unique_id=None, data={"mac": MAC.lower()})])

        result = asyncio.run(flow.async_step_manual({"mac": MAC}))

        assert result == {"type": "abort", "reason": "already_configured"}

    def test_manual_entry_creates_entry(self, monkeypatch):
        flow = _flow()
        validated = {"title": "Fluval", "data": {"mac": MAC}}
        monkeypatch.setattr(config_flow_module, "validate_input", AsyncMock(return_value=validated))

        result = asyncio.run(flow.async_step_manual({"mac": MAC.lower()}))

        assert result == {"type": "create_entry", **validated}

    @pytest.mark.parametrize(
        ("error", "expected"),
        [(InvalidFormat(), "invalid_format"), (RuntimeError(), "unknown")],
    )
    def test_manual_entry_reports_validation_errors(self, monkeypatch, error, expected):
        flow = _flow()
        monkeypatch.setattr(config_flow_module, "validate_input", AsyncMock(side_effect=error))

        result = asyncio.run(flow.async_step_manual({"mac": MAC}))

        assert result["type"] == "form"
        assert result["errors"] == {"base": expected}

    def test_options_flow_factory(self):
        assert isinstance(ConfigFlow.async_get_options_flow(SimpleNamespace()), OptionsFlowHandler)
