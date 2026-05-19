"""Tests for config and subentry flows."""
from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.door_supervisor.const import (
    DOMAIN,
    HUB_AUTO_LOCK_ENABLED,
    HUB_NOTIFICATIONS_ENABLED,
    HUB_UNIQUE_ID,
)


async def test_hub_setup_creates_entry_with_defaults(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Door Supervisor"
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.unique_id == HUB_UNIQUE_ID
    assert entry.data.get(HUB_NOTIFICATIONS_ENABLED) is True
    assert entry.data.get(HUB_AUTO_LOCK_ENABLED) is True


async def test_only_one_hub_allowed(hass: HomeAssistant):
    await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_hub_switches_exist_with_default_on(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    await hass.async_block_till_done()
    notifications = hass.states.get("switch.door_supervisor_notifications_enabled")
    auto_lock = hass.states.get("switch.door_supervisor_auto_lock_enabled")
    assert notifications is not None
    assert auto_lock is not None
    assert notifications.state == "on"
    assert auto_lock.state == "on"


async def test_hub_switch_toggle_persists(hass: HomeAssistant):
    await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    await hass.async_block_till_done()
    await hass.services.async_call(
        "switch", "turn_off",
        {"entity_id": "switch.door_supervisor_notifications_enabled"},
        blocking=True,
    )
    state = hass.states.get("switch.door_supervisor_notifications_enabled")
    assert state.state == "off"
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.data[HUB_NOTIFICATIONS_ENABLED] is False
