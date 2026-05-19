"""Door Supervisor integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, HUB_AUTO_LOCK_ENABLED, HUB_NOTIFICATIONS_ENABLED, PLATFORMS
from .hub import HubState


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the hub config entry."""
    hub_state = HubState(
        notifications_enabled=entry.data.get(HUB_NOTIFICATIONS_ENABLED, True),
        auto_lock_enabled=entry.data.get(HUB_AUTO_LOCK_ENABLED, True),
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"hub_state": hub_state}
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
