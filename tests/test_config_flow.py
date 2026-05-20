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
    assert result["reason"] == "already_configured"


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


from custom_components.door_supervisor.const import (
    CONF_AUTO_LOCK_DELAY_MINUTES,
    CONF_AUTO_LOCK_ENABLED,
    CONF_COVER,
    CONF_COVER_EVENT_NOTIFICATIONS,
    CONF_DOOR_SENSOR,
    CONF_LEFT_OPEN_THRESHOLDS,
    CONF_LOCK,
    CONF_LOCK_EVENT_NOTIFICATIONS,
    CONF_NAME,
    CONF_NOTIFICATION_SCRIPT,
    SUBENTRY_DOOR,
)


async def _setup_hub(hass):
    await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    await hass.async_block_till_done()
    return hass.config_entries.async_entries(DOMAIN)[0]


async def test_subentry_add_lock_plus_sensor_door(hass: HomeAssistant):
    entry = await _setup_hub(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_DOOR),
        context={"source": "user"},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "basics"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {CONF_NAME: "Front Door", CONF_NOTIFICATION_SCRIPT: "script.notify_phone"},
    )
    assert result["step_id"] == "entities"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            CONF_LOCK: "lock.front",
            CONF_DOOR_SENSOR: "binary_sensor.front_door",
        },
    )
    assert result["step_id"] == "features"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            CONF_AUTO_LOCK_ENABLED: True,
            CONF_AUTO_LOCK_DELAY_MINUTES: 5,
            CONF_LOCK_EVENT_NOTIFICATIONS: True,
            CONF_LEFT_OPEN_THRESHOLDS: "5",
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    sub = next(iter(entry.subentries.values()))
    assert sub.data[CONF_NAME] == "Front Door"
    assert sub.data[CONF_LEFT_OPEN_THRESHOLDS] == [5]


async def test_subentry_requires_at_least_one_entity(hass: HomeAssistant):
    entry = await _setup_hub(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_DOOR),
        context={"source": "user"},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {CONF_NAME: "Empty Door"},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {},  # no entities selected
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "at_least_one_entity"}


async def test_subentry_cover_only_features_step_omits_lock_fields(hass: HomeAssistant):
    entry = await _setup_hub(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_DOOR),
        context={"source": "user"},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_NAME: "Garage"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_COVER: "cover.garage"}
    )
    schema_keys = {k.schema if hasattr(k, "schema") else k for k in result["data_schema"].schema}
    assert CONF_AUTO_LOCK_ENABLED not in schema_keys
    assert CONF_COVER_EVENT_NOTIFICATIONS in schema_keys
    assert CONF_LEFT_OPEN_THRESHOLDS in schema_keys


async def test_subentry_reconfigure_updates_existing_door(hass: HomeAssistant):
    """Reconfigure flow walks all 3 steps and updates the existing subentry
    in place — does NOT create a duplicate."""
    entry = await _setup_hub(hass)
    # First, add a door
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_DOOR),
        context={"source": "user"},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_NAME: "Front Door"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_LOCK: "lock.front"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            CONF_AUTO_LOCK_ENABLED: True,
            CONF_AUTO_LOCK_DELAY_MINUTES: 5,
            CONF_LOCK_EVENT_NOTIFICATIONS: True,
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert len(entry.subentries) == 1
    sub_id = next(iter(entry.subentries))

    # Now reconfigure: change delay from 5 to 10 minutes
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_DOOR),
        context={"source": "reconfigure", "subentry_id": sub_id},
    )
    assert result["step_id"] == "basics"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_NAME: "Front Door"}
    )
    assert result["step_id"] == "entities"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_LOCK: "lock.front"}
    )
    assert result["step_id"] == "features"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            CONF_AUTO_LOCK_ENABLED: True,
            CONF_AUTO_LOCK_DELAY_MINUTES: 10,
            CONF_LOCK_EVENT_NOTIFICATIONS: True,
        },
    )
    # Subentry should still be exactly ONE — same id, updated data
    assert len(entry.subentries) == 1
    assert sub_id in entry.subentries
    assert entry.subentries[sub_id].data[CONF_AUTO_LOCK_DELAY_MINUTES] == 10
