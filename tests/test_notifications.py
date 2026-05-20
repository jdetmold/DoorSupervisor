"""Tests for event firing and gating."""
from __future__ import annotations

from datetime import timedelta

from freezegun import freeze_time
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, Event
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


async def _capture_events(hass: HomeAssistant, event_type: str) -> list[Event]:
    """Subscribe to a domain event and collect them into a list."""
    captured: list[Event] = []

    def _on(event: Event) -> None:
        captured.append(event)

    hass.bus.async_listen(event_type, _on)
    return captured


async def _setup_front_door(hass: HomeAssistant, **overrides):
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
        result["flow_id"], {CONF_NAME: "Front Door"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {CONF_LOCK: "lock.front", CONF_DOOR_SENSOR: "binary_sensor.front_door"},
    )
    features = {
        "auto_lock_enabled": False,
        "auto_lock_delay_minutes": 5,
        "lock_event_notifications": True,
        "left_open_thresholds_minutes": "",
    }
    features.update(overrides)
    await hass.config_entries.subentries.async_configure(
        result["flow_id"], features
    )
    await hass.async_block_till_done()
    return entry


async def test_lock_event_fires_ha_event_with_data(hass: HomeAssistant):
    events = []
    hass.bus.async_listen(f"{DOMAIN}.unlocked", lambda e: events.append(e))
    await _setup_front_door(hass)
    hass.states.async_set("lock.front", "unlocked")
    await hass.async_block_till_done()
    assert len(events) == 1
    assert events[0].data["door"] == "Front Door"
    assert events[0].data["entity_id"] == "lock.front"


async def test_global_notifications_off_suppresses_events(hass: HomeAssistant):
    events = []
    hass.bus.async_listen(f"{DOMAIN}.unlocked", lambda e: events.append(e))
    await _setup_front_door(hass)
    await hass.services.async_call(
        "switch", "turn_off",
        {"entity_id": "switch.door_supervisor_notifications_enabled"},
        blocking=True,
    )
    hass.states.async_set("lock.front", "unlocked")
    await hass.async_block_till_done()
    assert events == []


async def test_lock_event_notifications_off_suppresses(hass: HomeAssistant):
    events = []
    hass.bus.async_listen(f"{DOMAIN}.unlocked", lambda e: events.append(e))
    await _setup_front_door(hass, lock_event_notifications=False)
    hass.states.async_set("lock.front", "unlocked")
    await hass.async_block_till_done()
    assert events == []


async def test_left_open_warning_event_includes_minutes_open(hass: HomeAssistant):
    events = []
    hass.bus.async_listen(f"{DOMAIN}.left_open_warning", lambda e: events.append(e))
    with freeze_time(dt_util.utcnow()) as frozen:
        await _setup_front_door(hass, left_open_thresholds_minutes="5")
        hass.states.async_set("binary_sensor.front_door", "on")
        await hass.async_block_till_done()
        frozen.tick(delta=timedelta(minutes=5, seconds=1))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
    assert len(events) == 1
    assert events[0].data["minutes_open"] == 5
    assert events[0].data["door"] == "Front Door"


async def test_auto_lock_event_includes_auto_true(hass: HomeAssistant):
    events = []
    hass.bus.async_listen(f"{DOMAIN}.locked", lambda e: events.append(e))
    hass.services.async_register("lock", "lock", lambda call: None)
    with freeze_time(dt_util.utcnow()) as frozen:
        await _setup_front_door(
            hass,
            auto_lock_enabled=True,
            auto_lock_delay_minutes=5,
            lock_event_notifications=True,
        )
        # Door is closed (sensor off). Unlock it → countdown starts.
        hass.states.async_set("lock.front", "unlocked")
        await hass.async_block_till_done()
        events.clear()
        frozen.tick(delta=timedelta(minutes=5, seconds=1))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
    auto_events = [e for e in events if e.data.get("auto") is True]
    assert len(auto_events) == 1
    assert auto_events[0].data["door"] == "Front Door"


async def test_auto_lock_event_suppressed_when_global_auto_lock_off(hass: HomeAssistant):
    events = []
    hass.bus.async_listen(f"{DOMAIN}.locked", lambda e: events.append(e))
    await _setup_front_door(
        hass,
        auto_lock_enabled=True,
        auto_lock_delay_minutes=5,
        lock_event_notifications=True,
    )
    await hass.services.async_call(
        "switch", "turn_off",
        {"entity_id": "switch.door_supervisor_auto_lock_enabled"},
        blocking=True,
    )
    with freeze_time(dt_util.utcnow()) as frozen:
        hass.states.async_set("lock.front", "unlocked")
        await hass.async_block_till_done()
        events.clear()
        frozen.tick(delta=timedelta(minutes=5, seconds=1))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
    auto_events = [e for e in events if e.data.get("auto") is True]
    assert auto_events == []
