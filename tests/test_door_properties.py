"""Tests for Door derived properties."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from custom_components.door_supervisor.const import (
    STATUS_CLOSED,
    STATUS_OPEN,
    STATUS_OPEN_WARNING,
    STATUS_UNKNOWN,
)
from custom_components.door_supervisor.door import Door
from custom_components.door_supervisor.models import DoorConfig


T0 = datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)


class FakeClock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t


def test_status_unknown_when_no_signal_received():
    cfg = DoorConfig(name="A", sensor_entity_id="binary_sensor.a")
    door = Door(cfg, clock=FakeClock())
    assert door.status == STATUS_UNKNOWN


def test_status_closed_after_closed_signal():
    cfg = DoorConfig(name="A", sensor_entity_id="binary_sensor.a")
    door = Door(cfg, clock=FakeClock())
    door.on_sensor_state(False)
    assert door.status == STATUS_CLOSED


def test_status_open_after_open_signal_before_threshold():
    cfg = DoorConfig(name="A", sensor_entity_id="binary_sensor.a",
                     left_open_thresholds_minutes=(30,))
    door = Door(cfg, clock=FakeClock())
    door.on_sensor_state(True)
    assert door.status == STATUS_OPEN


def test_status_open_warning_after_threshold_fires():
    cfg = DoorConfig(name="A", sensor_entity_id="binary_sensor.a",
                     left_open_thresholds_minutes=(30,))
    door = Door(cfg, clock=FakeClock())
    door.on_sensor_state(True)
    door.on_schedule_fired("threshold_0")
    assert door.status == STATUS_OPEN_WARNING


def test_open_duration_zero_when_closed():
    cfg = DoorConfig(name="A", sensor_entity_id="binary_sensor.a")
    door = Door(cfg, clock=FakeClock())
    door.on_sensor_state(False)
    assert door.open_duration_minutes() == 0


def test_open_duration_increments_with_clock():
    cfg = DoorConfig(name="A", sensor_entity_id="binary_sensor.a")
    clock = FakeClock()
    door = Door(cfg, clock=clock)
    door.on_sensor_state(True)
    clock.t = T0 + timedelta(minutes=7)
    assert door.open_duration_minutes() == 7


def test_status_unknown_for_lock_only_door():
    cfg = DoorConfig(name="A", lock_entity_id="lock.a")
    door = Door(cfg, clock=FakeClock())
    assert door.status == STATUS_UNKNOWN
