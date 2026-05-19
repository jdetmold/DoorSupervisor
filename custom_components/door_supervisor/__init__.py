"""Door Supervisor integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, HUB_AUTO_LOCK_ENABLED, HUB_NOTIFICATIONS_ENABLED, PLATFORMS
from .coordinator import Coordinator
from .hub import HubState


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hub_state = HubState(
        notifications_enabled=entry.data.get(HUB_NOTIFICATIONS_ENABLED, True),
        auto_lock_enabled=entry.data.get(HUB_AUTO_LOCK_ENABLED, True),
    )
    coordinator = Coordinator(hass, entry, hub_state)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "hub_state": hub_state,
        "coordinator": coordinator,
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.start()
    entry.async_on_unload(
        entry.add_update_listener(_async_reload_entry)
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = hass.data[DOMAIN].get(entry.entry_id, {})
    coordinator: Coordinator | None = data.get("coordinator")
    if coordinator:
        coordinator.stop()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
