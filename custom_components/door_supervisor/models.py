"""Data types shared between the Door state machine and the coordinator."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DoorConfig:
    """Per-door configuration passed to the Door state machine.

    Any of lock/cover/sensor entity ids may be None, but at least one
    must be set. The state machine enforces this in __post_init__.
    """

    name: str
    lock_entity_id: str | None = None
    cover_entity_id: str | None = None
    sensor_entity_id: str | None = None
    notification_script: str | None = None
    auto_lock_enabled: bool = True
    auto_lock_delay_minutes: int = 5
    lock_event_notifications: bool = True
    cover_event_notifications: bool = True
    left_open_thresholds_minutes: tuple[int, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not any((self.lock_entity_id, self.cover_entity_id, self.sensor_entity_id)):
            raise ValueError("DoorConfig requires at least one of lock/cover/sensor")
        # thresholds must be sorted ascending and unique for left-open scheduling logic
        thr = tuple(sorted(set(self.left_open_thresholds_minutes)))
        object.__setattr__(self, "left_open_thresholds_minutes", thr)

    @property
    def has_open_close_signal(self) -> bool:
        """Whether this door can know if it is open or closed."""
        return self.sensor_entity_id is not None or self.cover_entity_id is not None


# --- Effects emitted by Door methods ---


@dataclass(frozen=True)
class Notify:
    """Notification request. Coordinator decides whether to call the script."""

    event_type: str
    entity_id: str
    extras: tuple[tuple[str, object], ...] = ()  # frozen tuple to keep dataclass hashable

    @classmethod
    def make(cls, event_type: str, entity_id: str, **extras: object) -> "Notify":
        return cls(event_type=event_type, entity_id=entity_id, extras=tuple(sorted(extras.items())))

    @property
    def extras_dict(self) -> dict[str, object]:
        return dict(self.extras)


@dataclass(frozen=True)
class LockNow:
    """Tell the coordinator to call lock.lock on the configured lock entity."""


@dataclass(frozen=True)
class Schedule:
    """Ask the coordinator to call door.on_schedule_fired(name) after delay_seconds."""

    name: str
    delay_seconds: int


@dataclass(frozen=True)
class Cancel:
    """Ask the coordinator to cancel a previously scheduled wake-up."""

    name: str


DoorEffect = Notify | LockNow | Schedule | Cancel
