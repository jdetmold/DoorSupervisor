"""Tests for the coordinator: HA state changes drive Door effects."""
from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from custom_components.door_supervisor.const import (
    CONF_DOOR_SENSOR,
    CONF_LOCK,
    CONF_NAME,
    DOMAIN,
    SUBENTRY_DOOR,
)


async def _setup_hub_and_door(hass, door_data: dict) -> tuple:
    await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    await hass.async_block_till_done()
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_DOOR),
        context={"source": "user"},
    )
    # walk through the three steps
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {CONF_NAME: door_data[CONF_NAME]},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {k: v for k, v in door_data.items() if k in {CONF_LOCK, "cover", CONF_DOOR_SENSOR}},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {k: v for k, v in door_data.items()
         if k not in {CONF_NAME, CONF_LOCK, "cover", CONF_DOOR_SENSOR}},
    )
    await hass.async_block_till_done()
    return entry, result


async def test_state_change_drives_door(hass: HomeAssistant):
    hass.states.async_set("binary_sensor.front_door", "off")
    hass.states.async_set("lock.front", "locked")
    await _setup_hub_and_door(
        hass,
        {
            CONF_NAME: "Front Door",
            CONF_LOCK: "lock.front",
            CONF_DOOR_SENSOR: "binary_sensor.front_door",
            "auto_lock_enabled": True,
            "auto_lock_delay_minutes": 5,
            "lock_event_notifications": True,
            "left_open_thresholds_minutes": "5",
        },
    )
    # Open the door
    hass.states.async_set("binary_sensor.front_door", "on")
    await hass.async_block_till_done()
    # The door's status sensor should reflect "open"
    status = hass.states.get("sensor.front_door_status")
    assert status is not None
    assert status.state == "open"
