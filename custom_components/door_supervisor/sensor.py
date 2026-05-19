"""Per-door diagnostic sensors."""
from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import DOMAIN, SUBENTRY_DOOR
from .coordinator import Coordinator, DoorRuntime


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: Coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    # Coordinator may not have started yet when this runs; do it after the forward returns.
    # We rely on Coordinator.start being called in __init__'s async_setup_entry after platform forwards.
    # But platform setup runs synchronously inside async_forward_entry_setups; doors are wired in start().
    # We register a callback to add entities for each door as it's created.

    @callback
    def _add_door_entities(sub_id: str, runtime: DoorRuntime) -> None:
        async_add_entities(
            [
                StatusSensor(entry, sub_id, runtime),
                OpenDurationSensor(entry, sub_id, runtime),
                AutoLockEtaSensor(entry, sub_id, runtime),
            ]
        )

    coordinator.entity_factory = _add_door_entities
    # Also add for any doors already running (defensive — order-independent setup)
    for sub_id, runtime in coordinator.doors.items():
        _add_door_entities(sub_id, runtime)


class _DoorSensorBase(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        entry: ConfigEntry,
        sub_id: str,
        runtime: DoorRuntime,
        translation_key: str,
        suffix: str,
    ) -> None:
        self._entry = entry
        self._sub_id = sub_id
        self._runtime = runtime
        self._attr_translation_key = translation_key
        self._attr_unique_id = f"{entry.entry_id}_{sub_id}_{suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{sub_id}")},
            name=runtime.config.name,
            manufacturer="Door Supervisor",
            model="Door",
            via_device=(DOMAIN, entry.entry_id),
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._runtime.add_listener(self.async_write_ha_state))


class StatusSensor(_DoorSensorBase):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["closed", "open", "open_warning", "unknown"]

    def __init__(self, entry, sub_id, runtime):
        super().__init__(entry, sub_id, runtime, "door_status", "status")

    @property
    def native_value(self) -> str:
        return self._runtime.door.status


class OpenDurationSensor(_DoorSensorBase):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = "min"

    def __init__(self, entry, sub_id, runtime):
        super().__init__(entry, sub_id, runtime, "open_duration_minutes", "open_duration_minutes")

    @property
    def native_value(self) -> int:
        return self._runtime.door.open_duration_minutes()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Tick once a minute to refresh duration while door is open
        self.async_on_remove(
            async_track_time_interval(
                self.hass, self._tick, timedelta(seconds=60)
            )
        )

    @callback
    def _tick(self, _now: datetime) -> None:
        self.async_write_ha_state()


class AutoLockEtaSensor(_DoorSensorBase):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, entry, sub_id, runtime):
        super().__init__(entry, sub_id, runtime, "auto_lock_eta", "auto_lock_eta")

    @property
    def native_value(self) -> datetime | None:
        return self._runtime.door.auto_lock_eta

    @property
    def available(self) -> bool:
        return self._runtime.door.auto_lock_eta is not None
