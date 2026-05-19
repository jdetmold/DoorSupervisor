"""Tests for lock/unlock event emission."""
from __future__ import annotations

from datetime import datetime, timezone

from custom_components.door_supervisor.const import EVENT_LOCKED, EVENT_UNLOCKED
from custom_components.door_supervisor.door import Door
from custom_components.door_supervisor.models import DoorConfig, Notify


T0 = datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)


def _clock(t=T0):
    def now():
        return t
    return now


def test_lock_locking_emits_locked_event_auto_false():
    cfg = DoorConfig(name="Front", lock_entity_id="lock.front")
    door = Door(cfg, clock=_clock())
    effects = door.on_lock_state("locked")
    assert Notify.make(EVENT_LOCKED, "lock.front", auto=False) in effects


def test_lock_unlocking_emits_unlocked_event():
    cfg = DoorConfig(name="Front", lock_entity_id="lock.front")
    door = Door(cfg, clock=_clock())
    door.on_lock_state("locked")
    effects = door.on_lock_state("unlocked")
    assert Notify.make(EVENT_UNLOCKED, "lock.front") in effects


def test_repeated_lock_state_does_not_re_emit():
    cfg = DoorConfig(name="Front", lock_entity_id="lock.front")
    door = Door(cfg, clock=_clock())
    door.on_lock_state("locked")
    effects = door.on_lock_state("locked")
    assert not any(isinstance(e, Notify) for e in effects)


def test_unknown_lock_state_emits_nothing():
    cfg = DoorConfig(name="Front", lock_entity_id="lock.front")
    door = Door(cfg, clock=_clock())
    effects = door.on_lock_state("jammed")
    assert effects == []
