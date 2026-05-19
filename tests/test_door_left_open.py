"""Tests for left-open warning scheduling."""
from __future__ import annotations

from datetime import datetime, timezone

from custom_components.door_supervisor.const import (
    EVENT_LEFT_OPEN_WARNING,
    SCHED_THRESHOLD_PREFIX,
)
from custom_components.door_supervisor.door import Door
from custom_components.door_supervisor.models import Cancel, DoorConfig, Notify, Schedule


T0 = datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)


def _clock(t=T0):
    def now():
        return t
    return now


def test_opening_schedules_first_threshold():
    cfg = DoorConfig(
        name="Garage",
        cover_entity_id="cover.garage",
        left_open_thresholds_minutes=(30, 60, 90),
    )
    door = Door(cfg, clock=_clock())
    effects = door.on_cover_state("open")
    assert Schedule(name=f"{SCHED_THRESHOLD_PREFIX}0", delay_seconds=30 * 60) in effects


def test_closing_cancels_pending_threshold():
    cfg = DoorConfig(
        name="Garage",
        cover_entity_id="cover.garage",
        left_open_thresholds_minutes=(30, 60),
    )
    door = Door(cfg, clock=_clock())
    door.on_cover_state("open")
    effects = door.on_cover_state("closed")
    assert Cancel(name=f"{SCHED_THRESHOLD_PREFIX}0") in effects


def test_threshold_fire_emits_warning_and_schedules_next():
    cfg = DoorConfig(
        name="Garage",
        cover_entity_id="cover.garage",
        left_open_thresholds_minutes=(30, 60, 90),
    )
    door = Door(cfg, clock=_clock())
    door.on_cover_state("open")
    effects = door.on_schedule_fired(f"{SCHED_THRESHOLD_PREFIX}0")
    assert Notify.make(
        EVENT_LEFT_OPEN_WARNING, "cover.garage", minutes_open=30
    ) in effects
    # second threshold is at 60 minutes total → 30 minutes after first fires
    assert Schedule(
        name=f"{SCHED_THRESHOLD_PREFIX}1", delay_seconds=(60 - 30) * 60
    ) in effects


def test_last_threshold_does_not_schedule_more():
    cfg = DoorConfig(
        name="Garage",
        cover_entity_id="cover.garage",
        left_open_thresholds_minutes=(30, 60, 90),
    )
    door = Door(cfg, clock=_clock())
    door.on_cover_state("open")
    door.on_schedule_fired(f"{SCHED_THRESHOLD_PREFIX}0")
    door.on_schedule_fired(f"{SCHED_THRESHOLD_PREFIX}1")
    effects = door.on_schedule_fired(f"{SCHED_THRESHOLD_PREFIX}2")
    assert Notify.make(
        EVENT_LEFT_OPEN_WARNING, "cover.garage", minutes_open=90
    ) in effects
    assert not any(isinstance(e, Schedule) and e.name.startswith(SCHED_THRESHOLD_PREFIX) for e in effects)


def test_reopening_resets_threshold_cycle():
    cfg = DoorConfig(
        name="Garage",
        cover_entity_id="cover.garage",
        left_open_thresholds_minutes=(30, 60),
    )
    door = Door(cfg, clock=_clock())
    door.on_cover_state("open")
    door.on_schedule_fired(f"{SCHED_THRESHOLD_PREFIX}0")
    door.on_cover_state("closed")
    effects = door.on_cover_state("open")
    # back at threshold 0
    assert Schedule(name=f"{SCHED_THRESHOLD_PREFIX}0", delay_seconds=30 * 60) in effects


def test_no_thresholds_means_no_scheduling():
    cfg = DoorConfig(
        name="Sensor Only",
        sensor_entity_id="binary_sensor.basement_door",
        left_open_thresholds_minutes=(),
    )
    door = Door(cfg, clock=_clock())
    effects = door.on_sensor_state(True)
    assert not any(isinstance(e, Schedule) for e in effects)


def test_unknown_state_cancels_pending_threshold():
    """Cover transitioning to an unknown state must cancel a pending threshold."""
    cfg = DoorConfig(
        name="Garage",
        cover_entity_id="cover.garage",
        left_open_thresholds_minutes=(30,),
    )
    door = Door(cfg, clock=_clock())
    door.on_cover_state("open")
    effects = door.on_cover_state("stopped")
    assert Cancel(name=f"{SCHED_THRESHOLD_PREFIX}0") in effects
