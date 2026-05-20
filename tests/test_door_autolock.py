"""Tests for auto-lock behavior (unlock-triggered, reset-on-close model)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

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


def _cfg_lock_only(**overrides):
    base = dict(
        name="Smart Lock Door",
        lock_entity_id="lock.smartlock",
        auto_lock_enabled=True,
        auto_lock_delay_minutes=5,
    )
    base.update(overrides)
    return DoorConfig(**base)


# --- Core new behavior: unlock-triggered ---


def test_unlock_while_closed_schedules_auto_lock():
    door = Door(_cfg_with_signal(), clock=_clock())
    door.on_sensor_state(False)  # closed
    effects = door.on_lock_state("unlocked")
    assert Schedule(name=SCHED_AUTO_LOCK, delay_seconds=5 * 60) in effects


def test_unlocked_never_opened_fires_auto_lock():
    """The gap this change fixes: unlock a closed door, never open it, it still locks."""
    door = Door(_cfg_with_signal(), clock=_clock())
    door.on_sensor_state(False)
    door.on_lock_state("unlocked")
    effects = door.on_schedule_fired(SCHED_AUTO_LOCK)
    assert LockNow() in effects
    assert Notify.make(EVENT_LOCKED, "lock.front", auto=True) in effects


def test_unlock_while_open_does_not_schedule():
    door = Door(_cfg_with_signal(), clock=_clock())
    door.on_sensor_state(True)  # open
    effects = door.on_lock_state("unlocked")
    assert not any(isinstance(e, Schedule) and e.name == SCHED_AUTO_LOCK for e in effects)


def test_open_during_countdown_cancels():
    door = Door(_cfg_with_signal(), clock=_clock())
    door.on_sensor_state(False)
    door.on_lock_state("unlocked")  # countdown active
    effects = door.on_sensor_state(True)  # open
    assert Cancel(name=SCHED_AUTO_LOCK) in effects
    assert door.auto_lock_eta is None


def test_close_restarts_countdown_while_unlocked():
    door = Door(_cfg_with_signal(), clock=_clock())
    door.on_sensor_state(False)
    door.on_lock_state("unlocked")
    door.on_sensor_state(True)   # open → cancel
    effects = door.on_sensor_state(False)  # close → restart
    assert Schedule(name=SCHED_AUTO_LOCK, delay_seconds=5 * 60) in effects


def test_close_resets_countdown_timer():
    holder = {"t": T0}

    def clock():
        return holder["t"]

    door = Door(_cfg_with_signal(), clock=clock)
    door.on_sensor_state(False)
    door.on_lock_state("unlocked")  # eta = T0 + 5min
    holder["t"] = T0 + timedelta(minutes=3)
    door.on_sensor_state(True)            # open at +3
    door.on_sensor_state(False)           # close at +3 → eta should be +8
    assert door.auto_lock_eta == T0 + timedelta(minutes=3) + timedelta(minutes=5)


def test_manual_lock_cancels_countdown():
    door = Door(_cfg_with_signal(), clock=_clock())
    door.on_sensor_state(False)
    door.on_lock_state("unlocked")
    effects = door.on_lock_state("locked")
    assert Cancel(name=SCHED_AUTO_LOCK) in effects
    assert door.auto_lock_eta is None


def test_auto_lock_disabled_does_not_schedule():
    door = Door(_cfg_with_signal(auto_lock_enabled=False), clock=_clock())
    door.on_sensor_state(False)
    effects = door.on_lock_state("unlocked")
    assert not any(isinstance(e, Schedule) and e.name == SCHED_AUTO_LOCK for e in effects)


def test_auto_lock_eta_set_during_countdown():
    door = Door(_cfg_with_signal(), clock=_clock())
    door.on_sensor_state(False)
    door.on_lock_state("unlocked")
    assert door.auto_lock_eta == T0 + timedelta(minutes=5)


def test_auto_lock_eta_cleared_after_firing():
    door = Door(_cfg_with_signal(), clock=_clock())
    door.on_sensor_state(False)
    door.on_lock_state("unlocked")
    door.on_schedule_fired(SCHED_AUTO_LOCK)
    assert door.auto_lock_eta is None


def test_auto_lock_does_not_fire_when_open():
    """Defensive: a stale timer firing while the door is open must not lock."""
    door = Door(_cfg_with_signal(), clock=_clock())
    door.on_sensor_state(False)
    door.on_lock_state("unlocked")
    # Force the door open via the public API without it cancelling (simulate race):
    # directly drive sensor open AFTER capturing — instead we mutate state then fire.
    door._sensor_open = True  # noqa: SLF001 - testing the defensive guard
    effects = door.on_schedule_fired(SCHED_AUTO_LOCK)
    assert LockNow() not in effects


# --- Lock-only doors (no open/close signal) ---


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


def test_lock_only_auto_lock_fires():
    door = Door(_cfg_lock_only(), clock=_clock())
    door.on_lock_state("unlocked")
    effects = door.on_schedule_fired(SCHED_AUTO_LOCK)
    assert LockNow() in effects
    assert Notify.make(EVENT_LOCKED, "lock.smartlock", auto=True) in effects


def test_lock_only_auto_lock_eta_set_and_cleared():
    door = Door(_cfg_lock_only(), clock=_clock())
    door.on_lock_state("unlocked")
    assert door.auto_lock_eta == T0 + timedelta(minutes=5)
    door.on_lock_state("locked")
    assert door.auto_lock_eta is None
