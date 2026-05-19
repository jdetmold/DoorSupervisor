"""Tests for notification dispatch and gating."""
from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from custom_components.door_supervisor.const import (
    CONF_DOOR_SENSOR,
    CONF_LOCK,
    CONF_NAME,
    CONF_NOTIFICATION_SCRIPT,
    DOMAIN,
    SUBENTRY_DOOR,
)


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
        result["flow_id"],
        {CONF_NAME: "Front Door", CONF_NOTIFICATION_SCRIPT: "script.notify"},
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


async def test_lock_event_fires_script_with_payload(hass: HomeAssistant):
    calls = []

    async def fake_script(call):
        calls.append(call.data)

    hass.services.async_register("script", "notify", fake_script)
    await _setup_front_door(hass)
    hass.states.async_set("lock.front", "unlocked")
    await hass.async_block_till_done()
    assert any(
        c.get("variables", {}).get("event_type") == "unlocked"
        and c["variables"]["door_name"] == "Front Door"
        and c["variables"]["message"] == "Front Door unlocked"
        and c["variables"]["entity_id"] == "lock.front"
        for c in calls
    )


async def test_global_notifications_off_suppresses(hass: HomeAssistant):
    calls = []

    async def fake_script(call):
        calls.append(call.data)

    hass.services.async_register("script", "notify", fake_script)
    await _setup_front_door(hass)
    await hass.services.async_call(
        "switch", "turn_off",
        {"entity_id": "switch.door_supervisor_notifications_enabled"},
        blocking=True,
    )
    calls.clear()
    hass.states.async_set("lock.front", "unlocked")
    await hass.async_block_till_done()
    assert calls == []


async def test_lock_event_notifications_off_suppresses(hass: HomeAssistant):
    calls = []

    async def fake_script(call):
        calls.append(call.data)

    hass.services.async_register("script", "notify", fake_script)
    await _setup_front_door(hass, lock_event_notifications=False)
    hass.states.async_set("lock.front", "unlocked")
    await hass.async_block_till_done()
    assert not any(
        c.get("variables", {}).get("event_type") in ("locked", "unlocked")
        for c in calls
    )


async def test_no_script_configured_suppresses_silently(hass: HomeAssistant):
    """Door without a notification_script still wires up — but no notifications fire."""
    calls = []

    async def fake_script(call):
        calls.append(call.data)

    hass.services.async_register("script", "notify", fake_script)
    # Set up via direct subentry flow that omits the script
    hass.states.async_set("binary_sensor.basement", "off")
    await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    await hass.async_block_till_done()
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_DOOR), context={"source": "user"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_NAME: "Basement"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_DOOR_SENSOR: "binary_sensor.basement"}
    )
    await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"left_open_thresholds_minutes": "5"}
    )
    await hass.async_block_till_done()
    hass.states.async_set("binary_sensor.basement", "on")
    await hass.async_block_till_done()
    assert calls == []  # no script configured, no notification


async def test_auto_lock_notification_suppressed_when_global_auto_lock_off(hass: HomeAssistant):
    """When global auto-lock is disabled, the schedule fires but no LockNow service call
    nor auto=True notification should happen."""
    calls = []

    async def fake_script(call):
        calls.append(call.data)

    hass.services.async_register("script", "notify", fake_script)
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
    from datetime import timedelta

    from freezegun import freeze_time
    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    with freeze_time(dt_util.utcnow()) as frozen:
        # close the door to start the countdown
        hass.states.async_set("binary_sensor.front_door", "on")
        await hass.async_block_till_done()
        hass.states.async_set("binary_sensor.front_door", "off")
        await hass.async_block_till_done()
        calls.clear()
        frozen.tick(delta=timedelta(minutes=5, seconds=1))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        # auto-lock fired internally but should be globally blocked
        auto_lock_notifications = [
            c for c in calls
            if c.get("variables", {}).get("auto") is True
        ]
        assert auto_lock_notifications == [], (
            f"Expected no auto=True notifications, got: {auto_lock_notifications}"
        )


async def test_left_open_warning_payload_contains_minutes_open(hass: HomeAssistant):
    from datetime import timedelta

    from freezegun import freeze_time
    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    calls = []

    async def fake_script(call):
        calls.append(call.data)

    hass.services.async_register("script", "notify", fake_script)
    with freeze_time(dt_util.utcnow()) as frozen:
        await _setup_front_door(hass, left_open_thresholds_minutes="5")
        calls.clear()
        hass.states.async_set("binary_sensor.front_door", "on")
        await hass.async_block_till_done()
        frozen.tick(delta=timedelta(minutes=5, seconds=1))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        warnings = [
            c for c in calls
            if c.get("variables", {}).get("event_type") == "left_open_warning"
        ]
        assert warnings, f"Expected a left_open_warning call, got: {calls}"
        assert warnings[0]["variables"]["minutes_open"] == 5
        assert warnings[0]["variables"]["message"] == "Front Door has been open for 5 minutes"
