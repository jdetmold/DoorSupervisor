"""Pure-Python Door state machine.

Driven by input events from the coordinator. Emits effects the
coordinator interprets. No HA imports — fully unit-testable.
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable

from .const import (
    EVENT_CLOSED,
    EVENT_LEFT_OPEN_WARNING,
    EVENT_LOCKED,
    EVENT_OPENED,
    EVENT_UNLOCKED,
    SCHED_AUTO_LOCK,
    SCHED_THRESHOLD_PREFIX,
    STATUS_CLOSED,
    STATUS_OPEN,
    STATUS_OPEN_WARNING,
    STATUS_UNKNOWN,
)
from .models import Cancel, DoorConfig, DoorEffect, LockNow, Notify, Schedule

# Cover states that we treat as "open"
_COVER_OPEN_STATES = frozenset({"open", "opening"})
_COVER_CLOSED_STATES = frozenset({"closed", "closing"})


class Door:
    """State machine for a single supervised door."""

    def __init__(self, config: DoorConfig, clock: Callable[[], datetime]) -> None:
        self.config = config
        self._clock = clock
        # open_state: True = open, False = closed, None = unknown
        self._sensor_open: bool | None = None
        self._cover_open: bool | None = None
        self._lock_locked: bool | None = None  # True locked, False unlocked
        self._open_since: datetime | None = None
        self._next_threshold_idx: int = 0
        self._auto_lock_eta: datetime | None = None

    # --- Public read-only state (used by coordinator to update sensors) ---

    @property
    def is_open(self) -> bool | None:
        """Authoritative open/closed state. None if unknown.

        Precedence: sensor > cover. If neither is configured, returns None.
        """
        if self.config.sensor_entity_id is not None:
            return self._sensor_open
        if self.config.cover_entity_id is not None:
            return self._cover_open
        return None

    @property
    def open_since(self) -> datetime | None:
        return self._open_since

    @property
    def auto_lock_eta(self) -> datetime | None:
        return self._auto_lock_eta

    @property
    def status(self) -> str:
        opened = self.is_open
        if opened is None:
            return STATUS_UNKNOWN
        if not opened:
            return STATUS_CLOSED
        if self._next_threshold_idx > 0:
            return STATUS_OPEN_WARNING
        return STATUS_OPEN

    def open_duration_minutes(self) -> int:
        if self._open_since is None:
            return 0
        delta = self._clock() - self._open_since
        return max(0, int(delta.total_seconds() // 60))

    # --- Input event handlers ---

    def on_sensor_state(self, is_open: bool) -> list[DoorEffect]:
        if self._sensor_open == is_open:
            return []
        prev_authoritative = self.is_open
        self._sensor_open = is_open
        new_authoritative = self.is_open
        if prev_authoritative == new_authoritative:
            return []
        return self._handle_open_close_change(
            new_open=new_authoritative,
            source_entity=self.config.sensor_entity_id or "",
        )

    def on_cover_state(self, state: str) -> list[DoorEffect]:
        if state in _COVER_OPEN_STATES:
            cover_open: bool | None = True
        elif state in _COVER_CLOSED_STATES:
            cover_open = False
        else:
            cover_open = None
        if self._cover_open == cover_open:
            return []
        # If sensor is the authority, cover update doesn't change is_open
        sensor_is_authority = self.config.sensor_entity_id is not None
        prev_authoritative = self.is_open
        self._cover_open = cover_open
        new_authoritative = self.is_open
        if sensor_is_authority or prev_authoritative == new_authoritative:
            return []
        return self._handle_open_close_change(
            new_open=new_authoritative,
            source_entity=self.config.cover_entity_id or "",
        )

    # --- Internal helpers ---

    def _handle_open_close_change(
        self, new_open: bool | None, source_entity: str
    ) -> list[DoorEffect]:
        effects: list[DoorEffect] = []
        if new_open is True:
            self._open_since = self._clock()
            self._next_threshold_idx = 0
            effects.append(Notify.make(EVENT_OPENED, source_entity))
            effects.extend(self._schedule_next_threshold())
            # Opening cancels any pending auto-lock countdown
            if self._auto_lock_eta is not None:
                effects.append(Cancel(name=SCHED_AUTO_LOCK))
                self._auto_lock_eta = None
        elif new_open is False:
            # Cancel any pending threshold before resetting index
            if self.config.left_open_thresholds_minutes and self._open_since is not None:
                effects.append(
                    Cancel(name=f"{SCHED_THRESHOLD_PREFIX}{self._next_threshold_idx}")
                )
            self._open_since = None
            self._next_threshold_idx = 0
            effects.append(Notify.make(EVENT_CLOSED, source_entity))
            effects.extend(self._maybe_schedule_auto_lock())
        else:
            # Transitioned to unknown — cancel any pending threshold and clear state.
            if self.config.left_open_thresholds_minutes and self._open_since is not None:
                effects.append(
                    Cancel(name=f"{SCHED_THRESHOLD_PREFIX}{self._next_threshold_idx}")
                )
            self._open_since = None
            self._next_threshold_idx = 0
        return effects

    def _maybe_schedule_auto_lock(self) -> list[DoorEffect]:
        """Schedule auto-lock from a closed state, if eligible."""
        if not self.config.lock_entity_id or not self.config.auto_lock_enabled:
            return []
        if not self.config.has_open_close_signal:
            # lock-only mode is handled separately by on_lock_state
            return []
        delay_seconds = self.config.auto_lock_delay_minutes * 60
        from datetime import timedelta

        self._auto_lock_eta = self._clock() + timedelta(seconds=delay_seconds)
        return [Schedule(name=SCHED_AUTO_LOCK, delay_seconds=delay_seconds)]

    def _schedule_next_threshold(self) -> list[DoorEffect]:
        """Schedule the next threshold callback, if any remain."""
        thresholds = self.config.left_open_thresholds_minutes
        if self._next_threshold_idx >= len(thresholds):
            return []
        next_total = thresholds[self._next_threshold_idx]
        prev_total = (
            thresholds[self._next_threshold_idx - 1] if self._next_threshold_idx > 0 else 0
        )
        delay_minutes = next_total - prev_total
        return [
            Schedule(
                name=f"{SCHED_THRESHOLD_PREFIX}{self._next_threshold_idx}",
                delay_seconds=delay_minutes * 60,
            )
        ]

    def on_schedule_fired(self, name: str) -> list[DoorEffect]:
        """Handle a scheduled callback firing."""
        if name == SCHED_AUTO_LOCK:
            return self._on_auto_lock_fired()
        if name.startswith(SCHED_THRESHOLD_PREFIX):
            return self._on_threshold_fired(name)
        return []

    def _on_auto_lock_fired(self) -> list[DoorEffect]:
        if self._auto_lock_eta is None:
            return []  # stale
        self._auto_lock_eta = None
        # Defensive: if door is open when callback fires, do nothing
        if self.config.has_open_close_signal and self.is_open:
            return []
        # Optimistically mark lock as locked to avoid double-emit when the lock entity reflects the change
        self._lock_locked = True
        return [
            LockNow(),
            Notify.make(
                EVENT_LOCKED,
                self.config.lock_entity_id or "",
                auto=True,
            ),
        ]

    def _on_threshold_fired(self, name: str) -> list[DoorEffect]:
        try:
            idx = int(name[len(SCHED_THRESHOLD_PREFIX):])
        except ValueError:
            return []
        thresholds = self.config.left_open_thresholds_minutes
        if idx != self._next_threshold_idx or idx >= len(thresholds):
            return []  # stale callback, ignore
        source = self.config.sensor_entity_id or self.config.cover_entity_id or ""
        effects: list[DoorEffect] = [
            Notify.make(
                EVENT_LEFT_OPEN_WARNING,
                source,
                minutes_open=thresholds[idx],
            )
        ]
        self._next_threshold_idx += 1
        effects.extend(self._schedule_next_threshold())
        return effects

    def on_lock_state(self, state: str) -> list[DoorEffect]:
        if state == "locked":
            new_locked: bool | None = True
        elif state == "unlocked":
            new_locked = False
        else:
            return []
        if self._lock_locked == new_locked:
            return []
        self._lock_locked = new_locked
        effects: list[DoorEffect] = []
        if new_locked:
            effects.append(
                Notify.make(EVENT_LOCKED, self.config.lock_entity_id or "", auto=False)
            )
            # Manual relock cancels any pending auto-lock countdown
            if self._auto_lock_eta is not None:
                effects.append(Cancel(name=SCHED_AUTO_LOCK))
                self._auto_lock_eta = None
        else:
            effects.append(Notify.make(EVENT_UNLOCKED, self.config.lock_entity_id or ""))
            # Lock-only mode: schedule auto-lock from unlock event
            if (
                self.config.auto_lock_enabled
                and not self.config.has_open_close_signal
                and self.config.lock_entity_id
            ):
                from datetime import timedelta

                delay = self.config.auto_lock_delay_minutes * 60
                self._auto_lock_eta = self._clock() + timedelta(seconds=delay)
                effects.append(Schedule(name=SCHED_AUTO_LOCK, delay_seconds=delay))
        return effects
