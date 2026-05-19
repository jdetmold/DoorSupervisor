"""Tests for per-door entities."""
from __future__ import annotations

from datetime import timedelta

from freezegun import freeze_time
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.door_supervisor.const import (
    CONF_DOOR_SENSOR,
    CONF_LEFT_OPEN_THRESHOLDS,
    CONF_LOCK,
    CONF_NAME,
    DOMAIN,
    SUBENTRY_DOOR,
)


async def _setup(hass, door_data):
    hass.states.async_set("binary_sensor.front_door", "off")
    hass.states.async_set("lock.front", "locked")
    await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    await hass.async_block_till_done()
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_DOOR), context={"source": "user"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_NAME: door_data[CONF_NAME]}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {k: v for k, v in door_data.items() if k in {CONF_LOCK, CONF_DOOR_SENSOR, "cover"}},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {k: v for k, v in door_data.items()
         if k not in {CONF_NAME, CONF_LOCK, CONF_DOOR_SENSOR, "cover"}},
    )
    await hass.async_block_till_done()
    return entry


async def test_status_sensor_reports_open(hass: HomeAssistant):
    await _setup(hass, {
        CONF_NAME: "Front Door",
        CONF_LOCK: "lock.front",
        CONF_DOOR_SENSOR: "binary_sensor.front_door",
        "auto_lock_enabled": False,
        "lock_event_notifications": True,
        CONF_LEFT_OPEN_THRESHOLDS: "",
    })
    hass.states.async_set("binary_sensor.front_door", "on")
    await hass.async_block_till_done()
    state = hass.states.get("sensor.front_door_status")
    assert state.state == "open"


async def test_open_duration_sensor_ticks(hass: HomeAssistant):
    with freeze_time(dt_util.utcnow()) as frozen:
        await _setup(hass, {
            CONF_NAME: "Front Door",
            CONF_DOOR_SENSOR: "binary_sensor.front_door",
            CONF_LEFT_OPEN_THRESHOLDS: "",
        })
        hass.states.async_set("binary_sensor.front_door", "on")
        await hass.async_block_till_done()
        state = hass.states.get("sensor.front_door_open_duration_minutes")
        assert state.state == "0"
        frozen.tick(delta=timedelta(minutes=3, seconds=1))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        state = hass.states.get("sensor.front_door_open_duration_minutes")
        assert state.state == "3"


async def test_auto_lock_eta_sensor_set_on_close(hass: HomeAssistant):
    with freeze_time(dt_util.utcnow()):
        await _setup(hass, {
            CONF_NAME: "Front Door",
            CONF_LOCK: "lock.front",
            CONF_DOOR_SENSOR: "binary_sensor.front_door",
            "auto_lock_enabled": True,
            "auto_lock_delay_minutes": 5,
            "lock_event_notifications": False,
            CONF_LEFT_OPEN_THRESHOLDS: "",
        })
        hass.states.async_set("binary_sensor.front_door", "on")
        await hass.async_block_till_done()
        hass.states.async_set("binary_sensor.front_door", "off")
        await hass.async_block_till_done()
        state = hass.states.get("sensor.front_door_auto_lock_eta")
        # should be a timestamp ~5 minutes from now, not "unavailable"
        assert state.state != "unavailable"
