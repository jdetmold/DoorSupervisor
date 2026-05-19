"""Tests for Door state machine open/close signal handling."""
from __future__ import annotations

import pytest

from custom_components.door_supervisor.models import DoorConfig


def test_door_config_requires_at_least_one_entity():
    with pytest.raises(ValueError):
        DoorConfig(name="Empty Door")


def test_door_config_thresholds_sorted_unique():
    cfg = DoorConfig(
        name="Front Door",
        sensor_entity_id="binary_sensor.front_door",
        left_open_thresholds_minutes=(90, 30, 60, 30),
    )
    assert cfg.left_open_thresholds_minutes == (30, 60, 90)


def test_has_open_close_signal_true_for_sensor_or_cover():
    assert DoorConfig(name="A", sensor_entity_id="binary_sensor.a").has_open_close_signal
    assert DoorConfig(name="B", cover_entity_id="cover.b").has_open_close_signal


def test_has_open_close_signal_false_for_lock_only():
    assert not DoorConfig(name="C", lock_entity_id="lock.c").has_open_close_signal


from datetime import datetime, timezone

from custom_components.door_supervisor.const import EVENT_OPENED, EVENT_CLOSED
from custom_components.door_supervisor.door import Door
from custom_components.door_supervisor.models import Notify


def _fixed_clock(t: datetime):
    def now():
        return t
    return now


def test_sensor_opening_fires_opened_event():
    cfg = DoorConfig(name="Front Door", sensor_entity_id="binary_sensor.front_door")
    door = Door(cfg, clock=_fixed_clock(datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)))
    effects = door.on_sensor_state(True)  # True = open
    assert Notify.make(EVENT_OPENED, "binary_sensor.front_door") in effects


def test_sensor_closing_fires_closed_event():
    cfg = DoorConfig(name="Front Door", sensor_entity_id="binary_sensor.front_door")
    door = Door(cfg, clock=_fixed_clock(datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)))
    door.on_sensor_state(True)
    effects = door.on_sensor_state(False)
    assert Notify.make(EVENT_CLOSED, "binary_sensor.front_door") in effects


def test_repeated_sensor_state_emits_no_duplicate_events():
    cfg = DoorConfig(name="Front Door", sensor_entity_id="binary_sensor.front_door")
    door = Door(cfg, clock=_fixed_clock(datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)))
    door.on_sensor_state(True)
    effects = door.on_sensor_state(True)  # same state again
    assert not any(isinstance(e, Notify) for e in effects)


def test_cover_open_state_fires_opened_event():
    cfg = DoorConfig(name="Garage", cover_entity_id="cover.garage")
    door = Door(cfg, clock=_fixed_clock(datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)))
    effects = door.on_cover_state("open")
    assert Notify.make(EVENT_OPENED, "cover.garage") in effects


def test_cover_opening_state_also_fires_opened_event():
    cfg = DoorConfig(name="Garage", cover_entity_id="cover.garage")
    door = Door(cfg, clock=_fixed_clock(datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)))
    effects = door.on_cover_state("opening")
    assert Notify.make(EVENT_OPENED, "cover.garage") in effects


def test_cover_closed_state_fires_closed_event():
    cfg = DoorConfig(name="Garage", cover_entity_id="cover.garage")
    door = Door(cfg, clock=_fixed_clock(datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)))
    door.on_cover_state("open")
    effects = door.on_cover_state("closed")
    assert Notify.make(EVENT_CLOSED, "cover.garage") in effects


def test_sensor_wins_precedence_when_both_configured():
    """When both sensor and cover are configured, the sensor drives open_state.

    Cover signal is ignored for the purpose of open/close tracking.
    """
    cfg = DoorConfig(
        name="Front",
        sensor_entity_id="binary_sensor.front",
        cover_entity_id="cover.front",
    )
    door = Door(cfg, clock=_fixed_clock(datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)))
    # Sensor says closed; cover says open. Door should report closed.
    door.on_sensor_state(False)
    effects = door.on_cover_state("open")
    # No opened event because sensor (the authority) still says closed
    assert not any(isinstance(e, Notify) and e.event_type == EVENT_OPENED for e in effects)


def test_cover_unknown_state_clears_open_since():
    """When a cover-only door transitions to an unknown state (e.g. 'stopped'),
    _open_since must be cleared so open_duration_minutes does not report stale data."""
    cfg = DoorConfig(name="Garage", cover_entity_id="cover.garage")
    door = Door(cfg, clock=_fixed_clock(datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)))
    door.on_cover_state("open")
    assert door.open_since is not None
    door.on_cover_state("stopped")
    assert door.is_open is None
    assert door.open_since is None
    assert door.open_duration_minutes() == 0
