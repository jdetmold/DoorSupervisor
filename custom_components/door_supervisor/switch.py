"""Hub-level global switches."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, HUB_AUTO_LOCK_ENABLED, HUB_NOTIFICATIONS_ENABLED
from .hub import HubState


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the two global hub switches."""
    hub_state: HubState = hass.data[DOMAIN][entry.entry_id]["hub_state"]
    async_add_entities(
        [
            _HubSwitch(
                entry=entry,
                hub_state=hub_state,
                key=HUB_NOTIFICATIONS_ENABLED,
                translation_key="notifications_enabled",
            ),
            _HubSwitch(
                entry=entry,
                hub_state=hub_state,
                key=HUB_AUTO_LOCK_ENABLED,
                translation_key="auto_lock_enabled",
            ),
        ]
    )


class _HubSwitch(SwitchEntity):
    """A global switch on the hub device."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False

    def __init__(
        self,
        entry: ConfigEntry,
        hub_state: HubState,
        key: str,
        translation_key: str,
    ) -> None:
        self._entry = entry
        self._hub_state = hub_state
        self._key = key
        self._attr_translation_key = translation_key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Door Supervisor",
            manufacturer="Door Supervisor",
            model="Hub",
        )

    @property
    def is_on(self) -> bool:
        return getattr(self._hub_state, self._key)

    async def async_turn_on(self, **kwargs: Any) -> None:
        setattr(self._hub_state, self._key, True)
        self._persist()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        setattr(self._hub_state, self._key, False)
        self._persist()
        self.async_write_ha_state()

    def _persist(self) -> None:
        new_data = {
            **self._entry.data,
            self._key: getattr(self._hub_state, self._key),
        }
        self.hass.config_entries.async_update_entry(self._entry, data=new_data)
