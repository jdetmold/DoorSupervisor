"""Restart behavior tests."""
from __future__ import annotations

from datetime import timedelta

from freezegun import freeze_time
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.door_supervisor.const import (
    CONF_DOOR_SENSOR,
    CONF_NAME,
    DOMAIN,
    SUBENTRY_DOOR,
)


async def test_open_at_startup_starts_threshold_from_now_not_retroactive(hass: HomeAssistant):
    """Door open at integration setup should NOT retroactively warn."""
    events = []
    hass.bus.async_listen(f"{DOMAIN}.left_open_warning", lambda e: events.append(e))
    # Pre-existing state: door is already open
    hass.states.async_set("binary_sensor.basement", "on")

    with freeze_time(dt_util.utcnow()) as frozen:
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
        # Immediately after setup: no warnings have fired (door just "opened" at startup)
        assert events == []
        # Advance 5 minutes — NOW the warning should fire (counting from startup, not before)
        frozen.tick(delta=timedelta(minutes=5, seconds=1))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        assert len(events) == 1


async def test_cover_open_at_startup_does_not_fire_opened_notification(hass: HomeAssistant):
    """A cover that is open at integration startup must NOT emit a spurious
    'opened' notification — only the threshold countdown should start."""
    events = []
    hass.bus.async_listen(f"{DOMAIN}.opened", lambda e: events.append(e))
    # Pre-existing state: cover already open
    hass.states.async_set("cover.garage", "open")

    await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    await hass.async_block_till_done()
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_DOOR), context={"source": "user"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_NAME: "Garage"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"cover": "cover.garage"}
    )
    await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {"cover_event_notifications": True, "left_open_thresholds_minutes": ""},
    )
    await hass.async_block_till_done()
    # No opened event should have fired during seed
    assert events == [], f"Expected no opened-at-startup event, got: {events}"
