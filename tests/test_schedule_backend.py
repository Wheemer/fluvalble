"""Tests for native fixture schedules and their saved configuration."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
import voluptuous as vol

from custom_components.fluvalble import (
    DOMAIN,
    FluvalRuntimeData,
    _async_load_schedule_data,
    _async_migrate_legacy_auto_schedule,
    _async_save_schedule,
    _async_upload_native_schedule,
    _validate_native_pro_schedule_points,
    _validate_schedule_points,
    _validate_time_dict,
    async_set_schedule_mode,
    async_unload_entry,
)
from custom_components.fluvalble.core.device import Device


class _MemoryStore:
    data = None

    def __init__(self, *args, **kwargs):
        pass

    async def async_load(self):
        return self.__class__.data

    async def async_save(self, data):
        self.__class__.data = data


class _FakeHass:
    def __init__(self, device=None):
        runtime = FluvalRuntimeData(device=device)
        self.data = {DOMAIN: {"entry_1": runtime}}


def _make_device():
    device = Device(
        "AquaSky3.0_Test",
        config_data={"mac": "AA:BB:CC:DD:EE:FF", "model": "AquaSky Bluetooth LED"},
    )
    device.connected = True
    return device


def _schedule_points():
    return [
        {"time": "19:00", "red": 3, "green": 0, "blue": 8, "white": 0},
        {"time": "20:00", "red": 0, "green": 0, "blue": 0, "white": 0},
    ]


def test_unload_cancels_entry_owned_tasks_before_device_shutdown():
    asyncio.run(_async_test_unload_cancels_entry_owned_tasks())


async def _async_test_unload_cancels_entry_owned_tasks():
    device = MagicMock()
    device.async_shutdown = AsyncMock()
    runtime = FluvalRuntimeData(device=device)
    started = asyncio.Event()

    async def background_work():
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(background_work())
    runtime.background_tasks.add(task)
    await started.wait()
    entry = MagicMock(runtime_data=runtime)
    hass = MagicMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    assert await async_unload_entry(hass, entry)
    assert task.cancelled()
    device.async_shutdown.assert_awaited_once()


def test_schedule_validators():
    with pytest.raises(vol.Invalid):
        _validate_schedule_points([{"time": "not-a-time"}, {"time": "20:00"}])
    with pytest.raises(vol.Invalid):
        _validate_schedule_points([{"time": "19:00", "unexpected": 1}, {"time": "20:00"}])
    with pytest.raises(vol.Invalid, match="2 to 12 points"):
        _validate_native_pro_schedule_points([{"time": f"{hour:02d}:00"} for hour in range(13)])
    with pytest.raises(vol.Invalid, match="2 to 12 points"):
        _validate_schedule_points([{"time": f"{hour:02d}:00"} for hour in range(13)])
    assert _validate_time_dict({"hour": 8, "minute": 0, "ramp": 240}, ramp=True)["ramp"] == 240
    with pytest.raises(vol.Invalid, match="0 to 240"):
        _validate_time_dict({"hour": 8, "minute": 0, "ramp": 241}, ramp=True)


def test_schedule_validator_normalizes_missing_channels():
    validated = _validate_schedule_points([{"time": "19:00", "blue": 8}, {"time": "20:00"}])
    assert validated[0] == {
        "time": "19:00",
        "red": 0,
        "green": 0,
        "blue": 8,
        "white": 0,
        "channel_5": 0,
    }


def test_save_and_load_native_schedule_data(monkeypatch):
    asyncio.run(_async_test_save_and_load_native_schedule_data(monkeypatch))


async def _async_test_save_and_load_native_schedule_data(monkeypatch):
    import custom_components.fluvalble as integration

    _MemoryStore.data = None
    monkeypatch.setattr(integration, "Store", _MemoryStore)
    points = _schedule_points()
    await _async_save_schedule(_FakeHass(), "entry_1", points, mode="native")
    assert await _async_load_schedule_data(_FakeHass(), "entry_1") == {"points": points, "mode": "native"}


def test_native_schedule_mode_uploads_once_to_the_fixture(monkeypatch):
    asyncio.run(_async_test_native_schedule_mode_uploads_once_to_the_fixture(monkeypatch))


async def _async_test_native_schedule_mode_uploads_once_to_the_fixture(monkeypatch):
    import custom_components.fluvalble as integration

    device = _make_device()
    device.async_set_native_pro_schedule = AsyncMock(return_value=True)
    points = _schedule_points()
    _MemoryStore.data = {"schedules": {"entry_1": {"points": points, "mode": "manual"}}}
    monkeypatch.setattr(integration, "Store", _MemoryStore)
    await async_set_schedule_mode(_FakeHass(device), "entry_1", "native")
    assert _MemoryStore.data["schedules"]["entry_1"]["mode"] == "native"
    device.async_set_native_pro_schedule.assert_awaited_once_with(points, activate=True)


def test_removed_ha_auto_mode_is_rejected(monkeypatch):
    asyncio.run(_async_test_removed_ha_auto_mode_is_rejected(monkeypatch))


async def _async_test_removed_ha_auto_mode_is_rejected(monkeypatch):
    import custom_components.fluvalble as integration
    from homeassistant.exceptions import HomeAssistantError

    _MemoryStore.data = {"schedules": {"entry_1": {"points": _schedule_points(), "mode": "manual"}}}
    monkeypatch.setattr(integration, "Store", _MemoryStore)
    with pytest.raises(HomeAssistantError, match="Unsupported fixture schedule mode"):
        await async_set_schedule_mode(_FakeHass(_make_device()), "entry_1", "auto")


def test_manual_schedule_mode_disables_the_fixture_scheduler(monkeypatch):
    asyncio.run(_async_test_manual_schedule_mode_disables_the_fixture_scheduler(monkeypatch))


async def _async_test_manual_schedule_mode_disables_the_fixture_scheduler(monkeypatch):
    import custom_components.fluvalble as integration

    device = _make_device()
    device.values["mode"] = "professional"
    device.async_select_option = AsyncMock(return_value=True)
    points = _schedule_points()
    _MemoryStore.data = {"schedules": {"entry_1": {"points": points, "mode": "native"}}}
    monkeypatch.setattr(integration, "Store", _MemoryStore)
    await async_set_schedule_mode(_FakeHass(device), "entry_1", "manual")
    device.async_select_option.assert_awaited_once_with("mode", "manual")
    assert _MemoryStore.data["schedules"]["entry_1"]["mode"] == "manual"


def test_native_schedule_upload_rejects_more_than_twelve_points():
    asyncio.run(_async_test_native_schedule_upload_rejects_more_than_twelve_points())


async def _async_test_native_schedule_upload_rejects_more_than_twelve_points():
    device = _make_device()
    device.async_set_native_pro_schedule = AsyncMock(return_value=True)
    points = [{"time": f"{hour:02d}:00"} for hour in range(13)]
    assert not await _async_upload_native_schedule(_FakeHass(device), "entry_1", points)
    device.async_set_native_pro_schedule.assert_not_awaited()


def test_failed_native_upload_preserves_manual_mode(monkeypatch):
    asyncio.run(_async_test_failed_native_upload_preserves_manual_mode(monkeypatch))


async def _async_test_failed_native_upload_preserves_manual_mode(monkeypatch):
    import custom_components.fluvalble as integration
    from homeassistant.exceptions import HomeAssistantError

    device = _make_device()
    device.async_set_native_pro_schedule = AsyncMock(return_value=False)
    device.command_error_message = MagicMock(return_value="write failed")
    points = _schedule_points()
    _MemoryStore.data = {"schedules": {"entry_1": {"points": points, "mode": "manual"}}}
    monkeypatch.setattr(integration, "Store", _MemoryStore)
    with pytest.raises(HomeAssistantError, match="write failed"):
        await async_set_schedule_mode(_FakeHass(device), "entry_1", "native")
    assert _MemoryStore.data["schedules"]["entry_1"]["mode"] == "manual"


def test_legacy_auto_schedule_migrates_to_fixture(monkeypatch):
    asyncio.run(_async_test_legacy_auto_schedule_migrates_to_fixture(monkeypatch))


async def _async_test_legacy_auto_schedule_migrates_to_fixture(monkeypatch):
    import custom_components.fluvalble as integration

    device = _make_device()
    device.async_set_native_pro_schedule = AsyncMock(return_value=True)
    points = _schedule_points()
    _MemoryStore.data = {"schedules": {"entry_1": {"points": points, "mode": "auto"}}}
    monkeypatch.setattr(integration, "Store", _MemoryStore)
    await _async_migrate_legacy_auto_schedule(_FakeHass(device), "entry_1")
    device.async_set_native_pro_schedule.assert_awaited_once_with(points, activate=True)
    assert _MemoryStore.data["schedules"]["entry_1"]["mode"] == "native"


def test_legacy_schedule_over_fixture_limit_becomes_manual(monkeypatch):
    asyncio.run(_async_test_legacy_schedule_over_fixture_limit_becomes_manual(monkeypatch))


async def _async_test_legacy_schedule_over_fixture_limit_becomes_manual(monkeypatch):
    import custom_components.fluvalble as integration

    device = _make_device()
    points = [{"time": f"{hour:02d}:00"} for hour in range(13)]
    _MemoryStore.data = {"schedules": {"entry_1": {"points": points, "mode": "auto"}}}
    monkeypatch.setattr(integration, "Store", _MemoryStore)
    await _async_migrate_legacy_auto_schedule(_FakeHass(device), "entry_1")
    assert _MemoryStore.data["schedules"]["entry_1"]["mode"] == "manual"
    assert device.diagnostics["native_schedule_last_result"] == "legacy_schedule_requires_edit"


def test_load_schedule_supports_legacy_list_records(monkeypatch):
    asyncio.run(_async_test_load_schedule_supports_legacy_list_records(monkeypatch))


async def _async_test_load_schedule_supports_legacy_list_records(monkeypatch):
    import custom_components.fluvalble as integration

    points = _schedule_points()
    _MemoryStore.data = {"schedules": {"entry_1": points}}
    monkeypatch.setattr(integration, "Store", _MemoryStore)
    assert await _async_load_schedule_data(_FakeHass(), "entry_1") == {"points": points, "mode": "manual"}
