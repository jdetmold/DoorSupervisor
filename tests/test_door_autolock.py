"""Tests for auto-lock behavior."""
from __future__ import annotations

from datetime import datetime, timezone

from custom_components.door_supervisor.const import EVENT_LOCKED, SCHED_AUTO_LOCK
from custom_components.door_supervisor.door import Door
from custom_components.door_supervisor.models import Cancel, DoorConfig, LockNow, Notify, Schedule


T0 = datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)


def _clock(t=T0):
    def now():
        return t
    return now


def _cfg_with_signal(**overrides):
    base = dict(
        name="Front",
        lock_entity_id="lock.front",
        sensor_entity_id="binary_sensor.front",
        auto_lock_enabled=True,
        auto_lock_delay_minutes=5,
    )
    base.update(overrides)
    return DoorConfig(**base)


def test_closing_schedules_auto_lock_when_signal_present():
    door = Door(_cfg_with_signal(), clock=_clock())
    door.on_sensor_state(True)
    effects = door.on_sensor_state(False)
    assert Schedule(name=SCHED_AUTO_LOCK, delay_seconds=5 * 60) in effects


def test_reopening_cancels_auto_lock_countdown():
    door = Door(_cfg_with_signal(), clock=_clock())
    door.on_sensor_state(True)
    door.on_sensor_state(False)
    effects = door.on_sensor_state(True)
    assert Cancel(name=SCHED_AUTO_LOCK) in effects


def test_reclosing_restarts_auto_lock_countdown():
    door = Door(_cfg_with_signal(), clock=_clock())
    door.on_sensor_state(True)
    door.on_sensor_state(False)
    door.on_sensor_state(True)  # opens again, cancels
    effects = door.on_sensor_state(False)  # closes again
    assert Schedule(name=SCHED_AUTO_LOCK, delay_seconds=5 * 60) in effects


def test_auto_lock_fires_lock_now_and_emits_auto_locked():
    door = Door(_cfg_with_signal(), clock=_clock())
    door.on_sensor_state(True)
    door.on_sensor_state(False)
    effects = door.on_schedule_fired(SCHED_AUTO_LOCK)
    assert LockNow() in effects
    assert Notify.make(EVENT_LOCKED, "lock.front", auto=True) in effects


def test_auto_lock_disabled_does_not_schedule():
    door = Door(_cfg_with_signal(auto_lock_enabled=False), clock=_clock())
    door.on_sensor_state(True)
    effects = door.on_sensor_state(False)
    assert not any(isinstance(e, Schedule) and e.name == SCHED_AUTO_LOCK for e in effects)


def test_auto_lock_eta_set_during_countdown():
    from datetime import timedelta
    door = Door(_cfg_with_signal(), clock=_clock())
    door.on_sensor_state(True)
    door.on_sensor_state(False)
    assert door.auto_lock_eta == T0 + timedelta(minutes=5)


def test_auto_lock_eta_cleared_on_reopen():
    door = Door(_cfg_with_signal(), clock=_clock())
    door.on_sensor_state(True)
    door.on_sensor_state(False)
    door.on_sensor_state(True)
    assert door.auto_lock_eta is None


def test_auto_lock_eta_cleared_after_firing():
    door = Door(_cfg_with_signal(), clock=_clock())
    door.on_sensor_state(True)
    door.on_sensor_state(False)
    door.on_schedule_fired(SCHED_AUTO_LOCK)
    assert door.auto_lock_eta is None


def _cfg_lock_only(**overrides):
    base = dict(
        name="Smart Lock Door",
        lock_entity_id="lock.smartlock",
        auto_lock_enabled=True,
        auto_lock_delay_minutes=5,
    )
    base.update(overrides)
    return DoorConfig(**base)


def test_lock_only_unlock_schedules_auto_lock():
    door = Door(_cfg_lock_only(), clock=_clock())
    effects = door.on_lock_state("unlocked")
    assert Schedule(name=SCHED_AUTO_LOCK, delay_seconds=5 * 60) in effects


def test_lock_only_manual_relock_cancels_auto_lock():
    door = Door(_cfg_lock_only(), clock=_clock())
    door.on_lock_state("unlocked")
    effects = door.on_lock_state("locked")
    assert Cancel(name=SCHED_AUTO_LOCK) in effects


def test_lock_only_disabled_does_not_schedule():
    door = Door(_cfg_lock_only(auto_lock_enabled=False), clock=_clock())
    effects = door.on_lock_state("unlocked")
    assert not any(isinstance(e, Schedule) and e.name == SCHED_AUTO_LOCK for e in effects)


def test_lock_only_auto_lock_eta_set_and_cleared():
    from datetime import timedelta
    door = Door(_cfg_lock_only(), clock=_clock())
    door.on_lock_state("unlocked")
    assert door.auto_lock_eta == T0 + timedelta(minutes=5)
    door.on_lock_state("locked")
    assert door.auto_lock_eta is None


def test_with_signal_unlock_does_not_schedule_auto_lock():
    """When the door has an open/close signal, the auto-lock trigger is the closed event,
    not the unlock event. This test guards against double-scheduling."""
    door = Door(_cfg_with_signal(), clock=_clock())
    effects = door.on_lock_state("unlocked")
    assert not any(isinstance(e, Schedule) and e.name == SCHED_AUTO_LOCK for e in effects)
