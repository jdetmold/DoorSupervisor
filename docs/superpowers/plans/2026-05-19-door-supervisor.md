# Door Supervisor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a HACS-compatible Home Assistant custom integration `door_supervisor` that centralizes per-door auto-lock, left-open warnings, and lock/cover event notifications. Each door is a name + any combination of {lock, cover, door sensor} + an optional notification script.

**Architecture:** One hub config entry per install (holds two global kill switches). Each door is a *subentry* of the hub (HA 2024.11+ subentries pattern) and produces its own device with diagnostic sensors. A pure-Python `Door` state machine emits typed *effects* (notify / lock / schedule / cancel) which a HA-side `Coordinator` interprets. This keeps all branching logic unit-testable without HA.

**Tech Stack:** Python 3.13, Home Assistant 2025.1+, `pytest`, `pytest-homeassistant-custom-component`, HACS.

---

## File Structure

```
custom_components/door_supervisor/
  __init__.py          # async_setup_entry / async_unload_entry, coordinator wiring
  manifest.json        # HA integration metadata
  config_flow.py       # main flow + DoorSubentryFlowHandler + options
  const.py             # DOMAIN, config keys, event_type literals, defaults
  models.py            # DoorConfig dataclass + DoorEffect union types
  door.py              # pure-Python Door state machine
  coordinator.py       # owns Door instances, listens to HA state, dispatches effects
  hub.py               # GlobalState (notifications/auto-lock enabled flags) shared object
  switch.py            # two global hub switches
  sensor.py            # per-door status, open_duration_minutes, auto_lock_eta
  strings.json         # UI strings (English source-of-truth)
  translations/
    en.json            # English translations (initially identical to strings.json)
tests/
  __init__.py
  conftest.py                # enable_custom_integrations autouse, common fixtures
  test_door_open_close.py    # state machine: open/close signal handling
  test_door_left_open.py     # state machine: left-open threshold scheduling
  test_door_lock_events.py   # state machine: lock/unlock events
  test_door_autolock.py      # state machine: auto-lock with signal AND lock-only
  test_door_properties.py    # state machine: status, duration, eta derivations
  test_config_flow.py        # hub setup, subentry add/edit
  test_coordinator.py        # HA wiring: state changes drive effects
  test_entities.py           # sensors + switches behave correctly
  test_notifications.py      # script payloads + gating
  test_restart.py            # restart with door already open
hacs.json
README.md
LICENSE
.gitignore
requirements_test.txt
pyproject.toml
```

**Why these splits:** `door.py` has no HA imports so it can be unit-tested in milliseconds. `coordinator.py` is the only file that translates between HA state-change events and door methods. Sensors / switches / config_flow each have one platform's responsibility. Hub state is a tiny shared object passed by reference into both switches and the coordinator.

---

## Task 1: Repo scaffolding & test harness

**Files:**
- Create: `custom_components/door_supervisor/__init__.py`
- Create: `custom_components/door_supervisor/manifest.json`
- Create: `custom_components/door_supervisor/const.py`
- Create: `hacs.json`
- Create: `README.md`
- Create: `LICENSE`
- Create: `.gitignore`
- Create: `requirements_test.txt`
- Create: `pyproject.toml`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create `.gitignore`**

```gitignore
__pycache__/
*.py[cod]
*.egg-info/
.pytest_cache/
.coverage
htmlcov/
.venv/
venv/
.tox/
*.swp
.DS_Store
.idea/
.vscode/
```

- [ ] **Step 2: Create `LICENSE` (MIT)**

```
MIT License

Copyright (c) 2026 <your name>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 3: Create `hacs.json`**

```json
{
  "name": "Door Supervisor",
  "render_readme": true,
  "homeassistant": "2025.1.0",
  "country": ["CA", "US"]
}
```

- [ ] **Step 4: Create `custom_components/door_supervisor/manifest.json`**

```json
{
  "domain": "door_supervisor",
  "name": "Door Supervisor",
  "codeowners": ["@techyyc"],
  "config_flow": true,
  "documentation": "https://github.com/techyyc/HA-DoorSupervisor",
  "iot_class": "local_push",
  "issue_tracker": "https://github.com/techyyc/HA-DoorSupervisor/issues",
  "requirements": [],
  "version": "0.1.0"
}
```

- [ ] **Step 5: Create `custom_components/door_supervisor/const.py`**

```python
"""Constants for door_supervisor."""
from __future__ import annotations

DOMAIN = "door_supervisor"

PLATFORMS = ["sensor", "switch"]

# Subentry types
SUBENTRY_DOOR = "door"

# Config keys (door subentry)
CONF_NAME = "name"
CONF_NOTIFICATION_SCRIPT = "notification_script"
CONF_LOCK = "lock"
CONF_COVER = "cover"
CONF_DOOR_SENSOR = "door_sensor"
CONF_AUTO_LOCK_ENABLED = "auto_lock_enabled"
CONF_AUTO_LOCK_DELAY_MINUTES = "auto_lock_delay_minutes"
CONF_LOCK_EVENT_NOTIFICATIONS = "lock_event_notifications"
CONF_COVER_EVENT_NOTIFICATIONS = "cover_event_notifications"
CONF_LEFT_OPEN_THRESHOLDS = "left_open_thresholds_minutes"

# Defaults
DEFAULT_AUTO_LOCK_DELAY_MINUTES = 5
DEFAULT_AUTO_LOCK_ENABLED = True
DEFAULT_LOCK_EVENT_NOTIFICATIONS = True
DEFAULT_COVER_EVENT_NOTIFICATIONS = True
DEFAULT_LEFT_OPEN_THRESHOLDS: list[int] = []

# Event type values passed to notification script
EVENT_LOCKED = "locked"
EVENT_UNLOCKED = "unlocked"
EVENT_OPENED = "opened"
EVENT_CLOSED = "closed"
EVENT_LEFT_OPEN_WARNING = "left_open_warning"

# Hub-level global switch keys (stored in hub config entry data)
HUB_NOTIFICATIONS_ENABLED = "notifications_enabled"
HUB_AUTO_LOCK_ENABLED = "auto_lock_enabled"

# Hub config entry unique_id — guarantees only one hub
HUB_UNIQUE_ID = "door_supervisor_hub"

# Internal schedule names used by Door state machine
SCHED_AUTO_LOCK = "auto_lock"
SCHED_THRESHOLD_PREFIX = "threshold_"  # e.g. "threshold_0", "threshold_1"

# Status sensor values
STATUS_CLOSED = "closed"
STATUS_OPEN = "open"
STATUS_OPEN_WARNING = "open_warning"
STATUS_UNKNOWN = "unknown"
```

- [ ] **Step 6: Create `custom_components/door_supervisor/__init__.py` (stub for now)**

```python
"""Door Supervisor integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the hub config entry. Door subentries are loaded by the coordinator."""
    hass.data.setdefault(DOMAIN, {})
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the hub config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
```

- [ ] **Step 7: Create `requirements_test.txt`**

```
pytest>=8.0
pytest-asyncio>=0.23
pytest-homeassistant-custom-component>=0.13.190
```

- [ ] **Step 8: Create `pyproject.toml`**

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
addopts = "-ra -q"

[tool.ruff]
line-length = 100
target-version = "py313"
```

- [ ] **Step 9: Create `tests/__init__.py`**

```python
"""Tests for door_supervisor."""
```

- [ ] **Step 10: Create `tests/conftest.py`**

```python
"""Test fixtures for door_supervisor."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Make custom_components/ discoverable in all tests."""
    yield
```

- [ ] **Step 11: Create a minimal `README.md`**

```markdown
# Door Supervisor

A Home Assistant custom integration that centralizes door supervision: auto-lock, left-open warnings, and lock/cover event notifications.

See `docs/superpowers/specs/2026-05-19-door-supervisor-design.md` for the design spec.

## Status

Pre-release. Not yet installable.
```

- [ ] **Step 12: Install test dependencies and verify pytest runs**

Run:
```bash
python -m venv .venv && source .venv/bin/activate && pip install -r requirements_test.txt
pytest
```

Expected: `no tests ran` with exit code 5 (pytest exits 5 when no tests collected — acceptable for now).

- [ ] **Step 13: Commit**

```bash
git add .gitignore LICENSE hacs.json README.md requirements_test.txt pyproject.toml \
        custom_components/door_supervisor/__init__.py \
        custom_components/door_supervisor/manifest.json \
        custom_components/door_supervisor/const.py \
        tests/__init__.py tests/conftest.py
git commit -m "Scaffold door_supervisor integration with HACS manifest and test harness"
```

---

## Task 2: Data models (DoorConfig + DoorEffect union)

**Files:**
- Create: `custom_components/door_supervisor/models.py`
- Test: `tests/test_door_open_close.py` (will use these types)

- [ ] **Step 1: Create `custom_components/door_supervisor/models.py`**

```python
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
        return cls(event_type=event_type, entity_id=entity_id, extras=tuple(extras.items()))

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
```

- [ ] **Step 2: Write failing test for DoorConfig validation**

Create `tests/test_door_open_close.py`:

```python
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
```

- [ ] **Step 3: Run tests, verify they pass**

Run: `pytest tests/test_door_open_close.py -v`

Expected: 4 passed.

- [ ] **Step 4: Commit**

```bash
git add custom_components/door_supervisor/models.py tests/test_door_open_close.py
git commit -m "Add DoorConfig and DoorEffect data types"
```

---

## Task 3: Door state machine — open/close signal handling

**Files:**
- Create: `custom_components/door_supervisor/door.py`
- Modify: `tests/test_door_open_close.py`

The `Door` class is the pure-Python state machine. Methods take input events and return a list of `DoorEffect`s. No HA imports; clock is injected.

- [ ] **Step 1: Add failing test for sensor opening fires `opened` notification**

Append to `tests/test_door_open_close.py`:

```python
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
```

- [ ] **Step 2: Run tests, verify they fail with ImportError**

Run: `pytest tests/test_door_open_close.py -v`

Expected: ImportError because `door.py` doesn't exist yet.

- [ ] **Step 3: Implement `custom_components/door_supervisor/door.py`**

```python
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
        """Emit opened/closed effects and update timers. Locks/thresholds handled in later tasks."""
        effects: list[DoorEffect] = []
        if new_open is True:
            self._open_since = self._clock()
            self._next_threshold_idx = 0
            effects.append(Notify.make(EVENT_OPENED, source_entity))
        elif new_open is False:
            self._open_since = None
            self._next_threshold_idx = 0
            effects.append(Notify.make(EVENT_CLOSED, source_entity))
        return effects
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `pytest tests/test_door_open_close.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add custom_components/door_supervisor/door.py tests/test_door_open_close.py
git commit -m "Add Door state machine with open/close signal handling and sensor-wins precedence"
```

---

## Task 4: Door state machine — left-open warnings

**Files:**
- Modify: `custom_components/door_supervisor/door.py`
- Create: `tests/test_door_left_open.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_door_left_open.py`:

```python
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
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_door_left_open.py -v`

Expected: AttributeError on `door.on_schedule_fired` and failures on scheduling.

- [ ] **Step 3: Extend `door.py` with threshold logic**

Modify `custom_components/door_supervisor/door.py`. Update `_handle_open_close_change` to schedule/cancel thresholds and add `on_schedule_fired`:

Replace the `_handle_open_close_change` method and append `on_schedule_fired`:

```python
    def _handle_open_close_change(
        self, new_open: bool | None, source_entity: str
    ) -> list[DoorEffect]:
        effects: list[DoorEffect] = []
        if new_open is True:
            self._open_since = self._clock()
            self._next_threshold_idx = 0
            effects.append(Notify.make(EVENT_OPENED, source_entity))
            effects.extend(self._schedule_next_threshold())
        elif new_open is False:
            # Cancel any pending threshold before resetting index
            if self.config.left_open_thresholds_minutes and self._open_since is not None:
                effects.append(
                    Cancel(name=f"{SCHED_THRESHOLD_PREFIX}{self._next_threshold_idx}")
                )
            self._open_since = None
            self._next_threshold_idx = 0
            effects.append(Notify.make(EVENT_CLOSED, source_entity))
        return effects

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
        if name.startswith(SCHED_THRESHOLD_PREFIX):
            return self._on_threshold_fired(name)
        return []

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
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `pytest tests/test_door_open_close.py tests/test_door_left_open.py -v`

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add custom_components/door_supervisor/door.py tests/test_door_left_open.py
git commit -m "Add left-open threshold scheduling to Door state machine"
```

---

## Task 5: Door state machine — lock events

**Files:**
- Modify: `custom_components/door_supervisor/door.py`
- Create: `tests/test_door_lock_events.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_door_lock_events.py`:

```python
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
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_door_lock_events.py -v`

Expected: AttributeError on `on_lock_state`.

- [ ] **Step 3: Add `on_lock_state` to `door.py`**

Append the method to the `Door` class (still in `custom_components/door_supervisor/door.py`):

```python
    def on_lock_state(self, state: str) -> list[DoorEffect]:
        """Handle a lock entity state change."""
        if state == "locked":
            new_locked: bool | None = True
        elif state == "unlocked":
            new_locked = False
        else:
            return []
        if self._lock_locked == new_locked:
            return []
        self._lock_locked = new_locked
        if new_locked:
            return [
                Notify.make(
                    EVENT_LOCKED,
                    self.config.lock_entity_id or "",
                    auto=False,
                )
            ]
        return [Notify.make(EVENT_UNLOCKED, self.config.lock_entity_id or "")]
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `pytest tests/test_door_lock_events.py -v`

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add custom_components/door_supervisor/door.py tests/test_door_lock_events.py
git commit -m "Emit locked/unlocked events from Door state machine"
```

---

## Task 6: Door state machine — auto-lock (with open/close signal)

**Files:**
- Modify: `custom_components/door_supervisor/door.py`
- Create: `tests/test_door_autolock.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_door_autolock.py`:

```python
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
    door = Door(_cfg_with_signal(), clock=_clock())
    door.on_sensor_state(True)
    door.on_sensor_state(False)
    assert door.auto_lock_eta is not None
    # eta is delay_minutes from clock time
    expected = T0.replace() + (door.auto_lock_eta - T0)
    assert door.auto_lock_eta == T0.replace() + (T0 - T0) + __import__("datetime").timedelta(minutes=5)


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
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_door_autolock.py -v`

Expected: tests fail because auto-lock scheduling not yet implemented.

- [ ] **Step 3: Extend `_handle_open_close_change` and `on_schedule_fired` in `door.py`**

Modify the `Door` class:

Replace `_handle_open_close_change` to also schedule/cancel auto-lock:

```python
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
            if self.config.left_open_thresholds_minutes and self._open_since is not None:
                effects.append(
                    Cancel(name=f"{SCHED_THRESHOLD_PREFIX}{self._next_threshold_idx}")
                )
            self._open_since = None
            self._next_threshold_idx = 0
            effects.append(Notify.make(EVENT_CLOSED, source_entity))
            effects.extend(self._maybe_schedule_auto_lock())
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
```

Update `on_schedule_fired` to handle auto-lock:

```python
    def on_schedule_fired(self, name: str) -> list[DoorEffect]:
        if name == SCHED_AUTO_LOCK:
            return self._on_auto_lock_fired()
        if name.startswith(SCHED_THRESHOLD_PREFIX):
            return self._on_threshold_fired(name)
        return []

    def _on_auto_lock_fired(self) -> list[DoorEffect]:
        if self._auto_lock_eta is None:
            return []  # stale
        self._auto_lock_eta = None
        # The door's open-state check matters: if open-close signal exists and door is open,
        # do nothing (defensive — the open-event should have already cancelled).
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
```

Also fix one test that has a calculation bug — replace `test_auto_lock_eta_set_during_countdown` with a clearer version. Modify `tests/test_door_autolock.py`:

```python
def test_auto_lock_eta_set_during_countdown():
    from datetime import timedelta
    door = Door(_cfg_with_signal(), clock=_clock())
    door.on_sensor_state(True)
    door.on_sensor_state(False)
    assert door.auto_lock_eta == T0 + timedelta(minutes=5)
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `pytest tests/test_door_autolock.py -v`

Expected: all 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add custom_components/door_supervisor/door.py tests/test_door_autolock.py
git commit -m "Add auto-lock countdown for doors with open/close signal"
```

---

## Task 7: Door state machine — auto-lock (lock-only mode)

**Files:**
- Modify: `custom_components/door_supervisor/door.py`
- Modify: `tests/test_door_autolock.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_door_autolock.py`:

```python
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
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_door_autolock.py -v`

Expected: new lock-only tests fail.

- [ ] **Step 3: Extend `on_lock_state` to handle lock-only auto-lock**

Replace the `on_lock_state` method in `door.py`:

```python
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
            # Manual relock cancels lock-only auto-lock countdown
            if self._auto_lock_eta is not None and not self.config.has_open_close_signal:
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
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `pytest tests/test_door_autolock.py -v`

Expected: all auto-lock tests pass.

- [ ] **Step 5: Commit**

```bash
git add custom_components/door_supervisor/door.py tests/test_door_autolock.py
git commit -m "Add lock-only auto-lock mode triggered by unlock event"
```

---

## Task 8: Door state machine — derived properties (status, duration, eta)

**Files:**
- Create: `tests/test_door_properties.py`

The properties are already implemented; this task verifies them with explicit tests.

- [ ] **Step 1: Write tests**

Create `tests/test_door_properties.py`:

```python
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
```

- [ ] **Step 2: Run tests, verify they pass**

Run: `pytest tests/test_door_properties.py -v`

Expected: all 7 pass (no implementation changes needed).

- [ ] **Step 3: Commit**

```bash
git add tests/test_door_properties.py
git commit -m "Add tests for Door derived properties (status, duration)"
```

---

## Task 9: Hub config flow + global switches

**Files:**
- Create: `custom_components/door_supervisor/config_flow.py`
- Create: `custom_components/door_supervisor/hub.py`
- Create: `custom_components/door_supervisor/switch.py`
- Modify: `custom_components/door_supervisor/__init__.py`
- Create: `custom_components/door_supervisor/strings.json`
- Create: `custom_components/door_supervisor/translations/en.json`
- Create: `tests/test_config_flow.py`

- [ ] **Step 1: Write failing test for hub config flow**

Create `tests/test_config_flow.py`:

```python
"""Tests for config and subentry flows."""
from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.door_supervisor.const import (
    DOMAIN,
    HUB_AUTO_LOCK_ENABLED,
    HUB_NOTIFICATIONS_ENABLED,
    HUB_UNIQUE_ID,
)


async def test_hub_setup_creates_entry_with_defaults(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Door Supervisor"
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.unique_id == HUB_UNIQUE_ID
    assert entry.data.get(HUB_NOTIFICATIONS_ENABLED) is True
    assert entry.data.get(HUB_AUTO_LOCK_ENABLED) is True


async def test_only_one_hub_allowed(hass: HomeAssistant):
    await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"
```

- [ ] **Step 2: Run test, verify it fails**

Run: `pytest tests/test_config_flow.py -v`

Expected: ImportError or AttributeError on missing config flow.

- [ ] **Step 3: Create `custom_components/door_supervisor/config_flow.py`**

```python
"""Config flow for door_supervisor."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult

from .const import (
    DOMAIN,
    HUB_AUTO_LOCK_ENABLED,
    HUB_NOTIFICATIONS_ENABLED,
    HUB_UNIQUE_ID,
)


class DoorSupervisorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Hub config flow. Only one instance allowed."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(HUB_UNIQUE_ID)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title="Door Supervisor",
            data={
                HUB_NOTIFICATIONS_ENABLED: True,
                HUB_AUTO_LOCK_ENABLED: True,
            },
        )
```

- [ ] **Step 4: Create `custom_components/door_supervisor/strings.json`**

```json
{
  "config": {
    "step": {
      "user": {
        "title": "Set up Door Supervisor",
        "description": "Creates the Door Supervisor hub. After setup, add individual doors as subentries."
      }
    },
    "abort": {
      "single_instance_allowed": "Door Supervisor is already configured."
    }
  },
  "entity": {
    "switch": {
      "notifications_enabled": {
        "name": "Notifications enabled"
      },
      "auto_lock_enabled": {
        "name": "Auto-lock enabled"
      }
    }
  }
}
```

- [ ] **Step 5: Create `custom_components/door_supervisor/translations/en.json`**

Copy the same content as `strings.json` (HA expects both files).

```json
{
  "config": {
    "step": {
      "user": {
        "title": "Set up Door Supervisor",
        "description": "Creates the Door Supervisor hub. After setup, add individual doors as subentries."
      }
    },
    "abort": {
      "single_instance_allowed": "Door Supervisor is already configured."
    }
  },
  "entity": {
    "switch": {
      "notifications_enabled": {
        "name": "Notifications enabled"
      },
      "auto_lock_enabled": {
        "name": "Auto-lock enabled"
      }
    }
  }
}
```

- [ ] **Step 6: Run hub config flow test, verify it passes**

Run: `pytest tests/test_config_flow.py -v`

Expected: both hub tests pass.

- [ ] **Step 7: Create `custom_components/door_supervisor/hub.py`**

```python
"""Hub-level shared state."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class HubState:
    """Mutable global state shared between switches and the coordinator."""

    notifications_enabled: bool = True
    auto_lock_enabled: bool = True
```

- [ ] **Step 8: Create `custom_components/door_supervisor/switch.py`**

```python
"""Hub-level global switches."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, HUB_AUTO_LOCK_ENABLED, HUB_NOTIFICATIONS_ENABLED
from .hub import HubState


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the two global hub switches."""
    hub_state: HubState = hass.data[DOMAIN][entry.entry_id]["hub_state"]
    async_add_entities(
        [
            _HubSwitch(
                entry=entry,
                hub_state=hub_state,
                key=HUB_NOTIFICATIONS_ENABLED,
                translation_key="notifications_enabled",
            ),
            _HubSwitch(
                entry=entry,
                hub_state=hub_state,
                key=HUB_AUTO_LOCK_ENABLED,
                translation_key="auto_lock_enabled",
            ),
        ]
    )


class _HubSwitch(SwitchEntity):
    """A global switch on the hub device."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False

    def __init__(
        self,
        entry: ConfigEntry,
        hub_state: HubState,
        key: str,
        translation_key: str,
    ) -> None:
        self._entry = entry
        self._hub_state = hub_state
        self._key = key
        self._attr_translation_key = translation_key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Door Supervisor",
            manufacturer="Door Supervisor",
            model="Hub",
        )

    @property
    def is_on(self) -> bool:
        return getattr(self._hub_state, self._key)

    async def async_turn_on(self, **kwargs: Any) -> None:
        setattr(self._hub_state, self._key, True)
        self._persist()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        setattr(self._hub_state, self._key, False)
        self._persist()
        self.async_write_ha_state()

    def _persist(self) -> None:
        new_data = {
            **self._entry.data,
            self._key: getattr(self._hub_state, self._key),
        }
        self.hass.config_entries.async_update_entry(self._entry, data=new_data)
```

- [ ] **Step 9: Update `custom_components/door_supervisor/__init__.py` to initialize hub_state**

```python
"""Door Supervisor integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, HUB_AUTO_LOCK_ENABLED, HUB_NOTIFICATIONS_ENABLED, PLATFORMS
from .hub import HubState


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the hub config entry."""
    hub_state = HubState(
        notifications_enabled=entry.data.get(HUB_NOTIFICATIONS_ENABLED, True),
        auto_lock_enabled=entry.data.get(HUB_AUTO_LOCK_ENABLED, True),
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"hub_state": hub_state}
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
```

- [ ] **Step 10: Add tests for hub switches**

Append to `tests/test_config_flow.py`:

```python
async def test_hub_switches_exist_with_default_on(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    await hass.async_block_till_done()
    notifications = hass.states.get("switch.door_supervisor_notifications_enabled")
    auto_lock = hass.states.get("switch.door_supervisor_auto_lock_enabled")
    assert notifications is not None
    assert auto_lock is not None
    assert notifications.state == "on"
    assert auto_lock.state == "on"


async def test_hub_switch_toggle_persists(hass: HomeAssistant):
    await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    await hass.async_block_till_done()
    await hass.services.async_call(
        "switch", "turn_off",
        {"entity_id": "switch.door_supervisor_notifications_enabled"},
        blocking=True,
    )
    state = hass.states.get("switch.door_supervisor_notifications_enabled")
    assert state.state == "off"
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.data[HUB_NOTIFICATIONS_ENABLED] is False
```

- [ ] **Step 11: Stub `sensor.py` so platform forwarding doesn't crash**

Create `custom_components/door_supervisor/sensor.py`:

```python
"""Per-door diagnostic sensors. Populated in a later task."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Sensors are added per-door in a later task."""
    return
```

- [ ] **Step 12: Run all tests, verify they pass**

Run: `pytest tests/test_config_flow.py -v`

Expected: all 4 tests pass.

- [ ] **Step 13: Commit**

```bash
git add custom_components/door_supervisor/config_flow.py \
        custom_components/door_supervisor/hub.py \
        custom_components/door_supervisor/switch.py \
        custom_components/door_supervisor/sensor.py \
        custom_components/door_supervisor/__init__.py \
        custom_components/door_supervisor/strings.json \
        custom_components/door_supervisor/translations/en.json \
        tests/test_config_flow.py
git commit -m "Add hub config entry with global notifications and auto-lock switches"
```

---

## Task 10: Door subentry flow (add, edit)

**Files:**
- Modify: `custom_components/door_supervisor/config_flow.py`
- Modify: `custom_components/door_supervisor/strings.json`
- Modify: `custom_components/door_supervisor/translations/en.json`
- Modify: `tests/test_config_flow.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_config_flow.py`:

```python
from custom_components.door_supervisor.const import (
    CONF_AUTO_LOCK_DELAY_MINUTES,
    CONF_AUTO_LOCK_ENABLED,
    CONF_COVER,
    CONF_COVER_EVENT_NOTIFICATIONS,
    CONF_DOOR_SENSOR,
    CONF_LEFT_OPEN_THRESHOLDS,
    CONF_LOCK,
    CONF_LOCK_EVENT_NOTIFICATIONS,
    CONF_NAME,
    CONF_NOTIFICATION_SCRIPT,
    SUBENTRY_DOOR,
)


async def _setup_hub(hass):
    await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    await hass.async_block_till_done()
    return hass.config_entries.async_entries(DOMAIN)[0]


async def test_subentry_add_lock_plus_sensor_door(hass: HomeAssistant):
    entry = await _setup_hub(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_DOOR),
        context={"source": "user"},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "basics"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {CONF_NAME: "Front Door", CONF_NOTIFICATION_SCRIPT: "script.notify_phone"},
    )
    assert result["step_id"] == "entities"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            CONF_LOCK: "lock.front",
            CONF_DOOR_SENSOR: "binary_sensor.front_door",
        },
    )
    assert result["step_id"] == "features"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            CONF_AUTO_LOCK_ENABLED: True,
            CONF_AUTO_LOCK_DELAY_MINUTES: 5,
            CONF_LOCK_EVENT_NOTIFICATIONS: True,
            CONF_LEFT_OPEN_THRESHOLDS: "5",
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    sub = next(iter(entry.subentries.values()))
    assert sub.data[CONF_NAME] == "Front Door"
    assert sub.data[CONF_LEFT_OPEN_THRESHOLDS] == [5]


async def test_subentry_requires_at_least_one_entity(hass: HomeAssistant):
    entry = await _setup_hub(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_DOOR),
        context={"source": "user"},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {CONF_NAME: "Empty Door"},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {},  # no entities selected
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "at_least_one_entity"}


async def test_subentry_cover_only_features_step_omits_lock_fields(hass: HomeAssistant):
    entry = await _setup_hub(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_DOOR),
        context={"source": "user"},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_NAME: "Garage"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_COVER: "cover.garage"}
    )
    schema_keys = {k.schema if hasattr(k, "schema") else k for k in result["data_schema"].schema}
    assert CONF_AUTO_LOCK_ENABLED not in schema_keys
    assert CONF_COVER_EVENT_NOTIFICATIONS in schema_keys
    assert CONF_LEFT_OPEN_THRESHOLDS in schema_keys
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_config_flow.py -v -k subentry`

Expected: tests fail because subentry flow doesn't exist.

- [ ] **Step 3: Add subentry flow to `config_flow.py`**

Replace the entire `custom_components/door_supervisor/config_flow.py`:

```python
"""Config flow for door_supervisor."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryData,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_AUTO_LOCK_DELAY_MINUTES,
    CONF_AUTO_LOCK_ENABLED,
    CONF_COVER,
    CONF_COVER_EVENT_NOTIFICATIONS,
    CONF_DOOR_SENSOR,
    CONF_LEFT_OPEN_THRESHOLDS,
    CONF_LOCK,
    CONF_LOCK_EVENT_NOTIFICATIONS,
    CONF_NAME,
    CONF_NOTIFICATION_SCRIPT,
    DEFAULT_AUTO_LOCK_DELAY_MINUTES,
    DEFAULT_AUTO_LOCK_ENABLED,
    DEFAULT_COVER_EVENT_NOTIFICATIONS,
    DEFAULT_LOCK_EVENT_NOTIFICATIONS,
    DOMAIN,
    HUB_AUTO_LOCK_ENABLED,
    HUB_NOTIFICATIONS_ENABLED,
    HUB_UNIQUE_ID,
    SUBENTRY_DOOR,
)


def _parse_thresholds(raw: str | list[int] | None) -> list[int]:
    if raw is None or raw == "":
        return []
    if isinstance(raw, list):
        return sorted({int(x) for x in raw if int(x) > 0})
    parts = [p.strip() for p in str(raw).split(",") if p.strip()]
    return sorted({int(p) for p in parts if int(p) > 0})


class DoorSupervisorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Hub config flow. Only one instance allowed."""

    VERSION = 1

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_DOOR: DoorSubentryFlow}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(HUB_UNIQUE_ID)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title="Door Supervisor",
            data={
                HUB_NOTIFICATIONS_ENABLED: True,
                HUB_AUTO_LOCK_ENABLED: True,
            },
        )


class DoorSubentryFlow(ConfigSubentryFlow):
    """Subentry flow for adding/editing a door."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    # --- ADD flow ---

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self.async_step_basics()

    async def async_step_basics(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_entities()
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=self._data.get(CONF_NAME, "")): str,
                vol.Optional(
                    CONF_NOTIFICATION_SCRIPT,
                    default=self._data.get(CONF_NOTIFICATION_SCRIPT, vol.UNDEFINED),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="script")
                ),
            }
        )
        return self.async_show_form(step_id="basics", data_schema=schema)

    async def async_step_entities(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not any(
                user_input.get(k) for k in (CONF_LOCK, CONF_COVER, CONF_DOOR_SENSOR)
            ):
                errors["base"] = "at_least_one_entity"
            else:
                self._data.update(user_input)
                return await self.async_step_features()
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_LOCK, default=self._data.get(CONF_LOCK, vol.UNDEFINED)
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="lock")),
                vol.Optional(
                    CONF_COVER, default=self._data.get(CONF_COVER, vol.UNDEFINED)
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="cover")),
                vol.Optional(
                    CONF_DOOR_SENSOR,
                    default=self._data.get(CONF_DOOR_SENSOR, vol.UNDEFINED),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="binary_sensor")
                ),
            }
        )
        return self.async_show_form(
            step_id="entities", data_schema=schema, errors=errors
        )

    async def async_step_features(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        if user_input is not None:
            features = dict(user_input)
            features[CONF_LEFT_OPEN_THRESHOLDS] = _parse_thresholds(
                features.get(CONF_LEFT_OPEN_THRESHOLDS)
            )
            self._data.update(features)
            title = self._data[CONF_NAME]
            return self.async_create_entry(title=title, data=self._data)
        return self.async_show_form(
            step_id="features", data_schema=self._features_schema()
        )

    def _features_schema(self) -> vol.Schema:
        has_lock = bool(self._data.get(CONF_LOCK))
        has_cover = bool(self._data.get(CONF_COVER))
        has_signal = has_cover or bool(self._data.get(CONF_DOOR_SENSOR))
        fields: dict[Any, Any] = {}
        if has_lock:
            fields[
                vol.Optional(
                    CONF_AUTO_LOCK_ENABLED,
                    default=self._data.get(CONF_AUTO_LOCK_ENABLED, DEFAULT_AUTO_LOCK_ENABLED),
                )
            ] = bool
            fields[
                vol.Optional(
                    CONF_AUTO_LOCK_DELAY_MINUTES,
                    default=self._data.get(
                        CONF_AUTO_LOCK_DELAY_MINUTES, DEFAULT_AUTO_LOCK_DELAY_MINUTES
                    ),
                )
            ] = vol.All(vol.Coerce(int), vol.Range(min=1, max=1440))
            fields[
                vol.Optional(
                    CONF_LOCK_EVENT_NOTIFICATIONS,
                    default=self._data.get(
                        CONF_LOCK_EVENT_NOTIFICATIONS, DEFAULT_LOCK_EVENT_NOTIFICATIONS
                    ),
                )
            ] = bool
        if has_cover:
            fields[
                vol.Optional(
                    CONF_COVER_EVENT_NOTIFICATIONS,
                    default=self._data.get(
                        CONF_COVER_EVENT_NOTIFICATIONS,
                        DEFAULT_COVER_EVENT_NOTIFICATIONS,
                    ),
                )
            ] = bool
        if has_signal:
            existing = self._data.get(CONF_LEFT_OPEN_THRESHOLDS, [])
            default_str = ",".join(str(x) for x in existing) if existing else ""
            fields[
                vol.Optional(CONF_LEFT_OPEN_THRESHOLDS, default=default_str)
            ] = str
        return vol.Schema(fields)

    # --- EDIT flow ---

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        sub: ConfigSubentryData = self._get_reconfigure_subentry()
        self._data = dict(sub.data)
        return await self.async_step_basics()
```

- [ ] **Step 4: Add subentry strings**

Modify `custom_components/door_supervisor/strings.json` — replace contents:

```json
{
  "config": {
    "step": {
      "user": {
        "title": "Set up Door Supervisor",
        "description": "Creates the Door Supervisor hub. After setup, add individual doors as subentries."
      }
    },
    "abort": {
      "single_instance_allowed": "Door Supervisor is already configured."
    }
  },
  "config_subentries": {
    "door": {
      "initiate_flow": {
        "user": "Add door",
        "reconfigure": "Edit door"
      },
      "step": {
        "basics": {
          "title": "Door basics",
          "data": {
            "name": "Door name",
            "notification_script": "Notification script (optional)"
          }
        },
        "entities": {
          "title": "Door entities",
          "description": "Select at least one of lock, cover, or door sensor. If both sensor and cover are configured, the sensor wins.",
          "data": {
            "lock": "Lock entity (optional)",
            "cover": "Cover entity (optional)",
            "door_sensor": "Door sensor (optional)"
          }
        },
        "features": {
          "title": "Features",
          "description": "Configure auto-lock and notification behavior. Empty threshold list disables left-open warnings.",
          "data": {
            "auto_lock_enabled": "Enable auto-lock",
            "auto_lock_delay_minutes": "Auto-lock delay (minutes)",
            "lock_event_notifications": "Notify on lock/unlock",
            "cover_event_notifications": "Notify on open/close",
            "left_open_thresholds_minutes": "Left-open thresholds (comma-separated minutes, e.g. 30,60,90)"
          }
        }
      },
      "error": {
        "at_least_one_entity": "Select at least one of lock, cover, or door sensor."
      }
    }
  },
  "entity": {
    "switch": {
      "notifications_enabled": {
        "name": "Notifications enabled"
      },
      "auto_lock_enabled": {
        "name": "Auto-lock enabled"
      }
    }
  }
}
```

Also copy this same content into `translations/en.json`.

- [ ] **Step 5: Update `manifest.json` to declare subentries**

Modify `custom_components/door_supervisor/manifest.json`:

```json
{
  "domain": "door_supervisor",
  "name": "Door Supervisor",
  "codeowners": ["@techyyc"],
  "config_flow": true,
  "config_subentries": ["door"],
  "documentation": "https://github.com/techyyc/HA-DoorSupervisor",
  "iot_class": "local_push",
  "issue_tracker": "https://github.com/techyyc/HA-DoorSupervisor/issues",
  "requirements": [],
  "version": "0.1.0"
}
```

- [ ] **Step 6: Run subentry tests, verify they pass**

Run: `pytest tests/test_config_flow.py -v`

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add custom_components/door_supervisor/config_flow.py \
        custom_components/door_supervisor/manifest.json \
        custom_components/door_supervisor/strings.json \
        custom_components/door_supervisor/translations/en.json \
        tests/test_config_flow.py
git commit -m "Add door subentry flow with adaptive features step"
```

---

## Task 11: Coordinator — HA event wiring and effect dispatch

**Files:**
- Create: `custom_components/door_supervisor/coordinator.py`
- Modify: `custom_components/door_supervisor/__init__.py`
- Create: `tests/test_coordinator.py`

The coordinator owns one `Door` per subentry. It subscribes to HA state-change events for the door's configured entities, translates them into `Door` method calls, and interprets the returned `DoorEffect`s.

- [ ] **Step 1: Write failing test for state change driving a Door effect**

Create `tests/test_coordinator.py`:

```python
"""Tests for the coordinator: HA state changes drive Door effects."""
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


async def _setup_hub_and_door(hass, door_data: dict) -> tuple:
    await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    await hass.async_block_till_done()
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_DOOR),
        context={"source": "user"},
    )
    # walk through the three steps
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {CONF_NAME: door_data[CONF_NAME], CONF_NOTIFICATION_SCRIPT: door_data.get(CONF_NOTIFICATION_SCRIPT)},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {k: v for k, v in door_data.items() if k in {CONF_LOCK, "cover", CONF_DOOR_SENSOR}},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {k: v for k, v in door_data.items()
         if k not in {CONF_NAME, CONF_NOTIFICATION_SCRIPT, CONF_LOCK, "cover", CONF_DOOR_SENSOR}},
    )
    await hass.async_block_till_done()
    return entry, result


async def test_state_change_drives_door(hass: HomeAssistant):
    hass.states.async_set("binary_sensor.front_door", "off")
    hass.states.async_set("lock.front", "locked")
    await _setup_hub_and_door(
        hass,
        {
            CONF_NAME: "Front Door",
            CONF_LOCK: "lock.front",
            CONF_DOOR_SENSOR: "binary_sensor.front_door",
            "auto_lock_enabled": True,
            "auto_lock_delay_minutes": 5,
            "lock_event_notifications": True,
            "left_open_thresholds_minutes": "5",
        },
    )
    # Open the door
    hass.states.async_set("binary_sensor.front_door", "on")
    await hass.async_block_till_done()
    # The door's status sensor should reflect "open"
    status = hass.states.get("sensor.front_door_status")
    assert status is not None
    assert status.state == "open"
```

- [ ] **Step 2: Run test, verify it fails**

Run: `pytest tests/test_coordinator.py -v`

Expected: failure because coordinator doesn't exist and sensor isn't created.

- [ ] **Step 3: Create `custom_components/door_supervisor/coordinator.py`**

```python
"""Coordinator: wires HA state changes to Door state machines and dispatches effects."""
from __future__ import annotations

import logging
from typing import Any, Callable

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import (
    CONF_AUTO_LOCK_DELAY_MINUTES,
    CONF_AUTO_LOCK_ENABLED,
    CONF_COVER,
    CONF_COVER_EVENT_NOTIFICATIONS,
    CONF_DOOR_SENSOR,
    CONF_LEFT_OPEN_THRESHOLDS,
    CONF_LOCK,
    CONF_LOCK_EVENT_NOTIFICATIONS,
    CONF_NAME,
    CONF_NOTIFICATION_SCRIPT,
    DEFAULT_AUTO_LOCK_DELAY_MINUTES,
    DEFAULT_AUTO_LOCK_ENABLED,
    DEFAULT_COVER_EVENT_NOTIFICATIONS,
    DEFAULT_LOCK_EVENT_NOTIFICATIONS,
    DOMAIN,
    EVENT_CLOSED,
    EVENT_LEFT_OPEN_WARNING,
    EVENT_LOCKED,
    EVENT_OPENED,
    EVENT_UNLOCKED,
    SUBENTRY_DOOR,
)
from .door import Door
from .hub import HubState
from .models import Cancel, DoorConfig, LockNow, Notify, Schedule

_LOGGER = logging.getLogger(__name__)


def _build_config(sub: ConfigSubentry) -> DoorConfig:
    data = sub.data
    thresholds = data.get(CONF_LEFT_OPEN_THRESHOLDS, []) or []
    if isinstance(thresholds, str):
        thresholds = [int(x.strip()) for x in thresholds.split(",") if x.strip()]
    return DoorConfig(
        name=data[CONF_NAME],
        lock_entity_id=data.get(CONF_LOCK),
        cover_entity_id=data.get(CONF_COVER),
        sensor_entity_id=data.get(CONF_DOOR_SENSOR),
        notification_script=data.get(CONF_NOTIFICATION_SCRIPT),
        auto_lock_enabled=data.get(CONF_AUTO_LOCK_ENABLED, DEFAULT_AUTO_LOCK_ENABLED),
        auto_lock_delay_minutes=data.get(
            CONF_AUTO_LOCK_DELAY_MINUTES, DEFAULT_AUTO_LOCK_DELAY_MINUTES
        ),
        lock_event_notifications=data.get(
            CONF_LOCK_EVENT_NOTIFICATIONS, DEFAULT_LOCK_EVENT_NOTIFICATIONS
        ),
        cover_event_notifications=data.get(
            CONF_COVER_EVENT_NOTIFICATIONS, DEFAULT_COVER_EVENT_NOTIFICATIONS
        ),
        left_open_thresholds_minutes=tuple(thresholds),
    )


def _format_message(door_name: str, event_type: str, extras: dict[str, Any]) -> str:
    if event_type == EVENT_LOCKED:
        if extras.get("auto"):
            return f"{door_name} auto-locked"
        return f"{door_name} locked"
    if event_type == EVENT_UNLOCKED:
        return f"{door_name} unlocked"
    if event_type == EVENT_OPENED:
        return f"{door_name} opened"
    if event_type == EVENT_CLOSED:
        return f"{door_name} closed"
    if event_type == EVENT_LEFT_OPEN_WARNING:
        return f"{door_name} has been open for {extras['minutes_open']} minutes"
    return f"{door_name}: {event_type}"


class DoorRuntime:
    """Per-door runtime: the Door state machine + HA listeners + scheduled callbacks."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: "Coordinator",
        subentry_id: str,
        config: DoorConfig,
    ) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.subentry_id = subentry_id
        self.config = config
        self.door = Door(config, clock=dt_util.utcnow)
        self._unsub_state: list[Callable[[], None]] = []
        self._timers: dict[str, Callable[[], None]] = {}
        self._listeners: list[Callable[[], None]] = []  # entity-update callbacks

    def start(self) -> None:
        entity_ids = [
            eid
            for eid in (
                self.config.lock_entity_id,
                self.config.cover_entity_id,
                self.config.sensor_entity_id,
            )
            if eid
        ]
        if entity_ids:
            self._unsub_state.append(
                async_track_state_change_event(
                    self.hass, entity_ids, self._on_state_change
                )
            )
        # Seed from current states
        for eid in entity_ids:
            state = self.hass.states.get(eid)
            if state is not None:
                self._apply_state(eid, state.state)

    def stop(self) -> None:
        for u in self._unsub_state:
            u()
        self._unsub_state.clear()
        for cancel in self._timers.values():
            cancel()
        self._timers.clear()

    def add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        """Called whenever Door state changes — used by sensors to refresh."""
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb)

    @callback
    def _on_state_change(self, event: Event[EventStateChangedData]) -> None:
        new = event.data["new_state"]
        if new is None:
            return
        self._apply_state(event.data["entity_id"], new.state)

    def _apply_state(self, entity_id: str, state: str) -> None:
        if entity_id == self.config.lock_entity_id:
            effects = self.door.on_lock_state(state)
        elif entity_id == self.config.cover_entity_id:
            effects = self.door.on_cover_state(state)
        elif entity_id == self.config.sensor_entity_id:
            effects = self.door.on_sensor_state(state == "on")
        else:
            return
        self._apply_effects(effects)

    def _apply_effects(self, effects: list) -> None:
        for effect in effects:
            if isinstance(effect, Notify):
                self.coordinator.dispatch_notify(self.config, effect)
            elif isinstance(effect, LockNow):
                self.hass.async_create_task(
                    self.hass.services.async_call(
                        "lock", "lock",
                        {"entity_id": self.config.lock_entity_id},
                        blocking=False,
                    )
                )
            elif isinstance(effect, Schedule):
                self._schedule(effect)
            elif isinstance(effect, Cancel):
                self._cancel(effect.name)
        for cb in list(self._listeners):
            cb()

    def _schedule(self, eff: Schedule) -> None:
        # Cancel any previous schedule with this name first
        self._cancel(eff.name)

        @callback
        def _fire(_now):
            self._timers.pop(eff.name, None)
            effects = self.door.on_schedule_fired(eff.name)
            self._apply_effects(effects)

        self._timers[eff.name] = async_call_later(self.hass, eff.delay_seconds, _fire)

    def _cancel(self, name: str) -> None:
        cancel = self._timers.pop(name, None)
        if cancel:
            cancel()


class Coordinator:
    """Single coordinator per hub entry. Owns all DoorRuntime instances."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, hub_state: HubState) -> None:
        self.hass = hass
        self.entry = entry
        self.hub_state = hub_state
        self.doors: dict[str, DoorRuntime] = {}

    def start(self) -> None:
        for sub_id, sub in self.entry.subentries.items():
            if sub.subentry_type != SUBENTRY_DOOR:
                continue
            cfg = _build_config(sub)
            runtime = DoorRuntime(self.hass, self, sub_id, cfg)
            runtime.start()
            self.doors[sub_id] = runtime

    def stop(self) -> None:
        for runtime in self.doors.values():
            runtime.stop()
        self.doors.clear()

    def dispatch_notify(self, cfg: DoorConfig, eff: Notify) -> None:
        if not self.hub_state.notifications_enabled:
            return
        # Per-category gating
        if eff.event_type in (EVENT_LOCKED, EVENT_UNLOCKED):
            if not cfg.lock_event_notifications:
                return
        elif eff.event_type in (EVENT_OPENED, EVENT_CLOSED):
            # Only notify open/close when a cover is configured AND cover_event_notifications is on
            if cfg.cover_entity_id is None or not cfg.cover_event_notifications:
                return
        # event_type == EVENT_LEFT_OPEN_WARNING is always allowed if it fires
        if not cfg.notification_script:
            return
        extras = eff.extras_dict
        message = _format_message(cfg.name, eff.event_type, extras)
        payload = {
            "door_name": cfg.name,
            "event_type": eff.event_type,
            "message": message,
            "entity_id": eff.entity_id,
            **extras,
        }
        domain, _, name = cfg.notification_script.partition(".")
        if domain != "script":
            _LOGGER.warning("notification_script %s is not a script entity", cfg.notification_script)
            return
        self.hass.async_create_task(
            self.hass.services.async_call(
                "script", name, {"variables": payload}, blocking=False
            )
        )

    def should_block_auto_lock(self) -> bool:
        return not self.hub_state.auto_lock_enabled
```

- [ ] **Step 4: Wire coordinator into `__init__.py`**

Modify `custom_components/door_supervisor/__init__.py`:

```python
"""Door Supervisor integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, HUB_AUTO_LOCK_ENABLED, HUB_NOTIFICATIONS_ENABLED, PLATFORMS
from .coordinator import Coordinator
from .hub import HubState


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hub_state = HubState(
        notifications_enabled=entry.data.get(HUB_NOTIFICATIONS_ENABLED, True),
        auto_lock_enabled=entry.data.get(HUB_AUTO_LOCK_ENABLED, True),
    )
    coordinator = Coordinator(hass, entry, hub_state)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "hub_state": hub_state,
        "coordinator": coordinator,
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.start()
    entry.async_on_unload(
        entry.add_update_listener(_async_reload_entry)
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = hass.data[DOMAIN].get(entry.entry_id, {})
    coordinator: Coordinator | None = data.get("coordinator")
    if coordinator:
        coordinator.stop()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
```

- [ ] **Step 5: Add hub-state hook so the global auto-lock switch blocks `LockNow` effects**

Modify `coordinator.py` `_apply_effects` in `DoorRuntime`:

Find the `LockNow` branch and wrap it:

```python
            elif isinstance(effect, LockNow):
                if self.coordinator.should_block_auto_lock():
                    continue
                self.hass.async_create_task(
                    self.hass.services.async_call(
                        "lock", "lock",
                        {"entity_id": self.config.lock_entity_id},
                        blocking=False,
                    )
                )
```

- [ ] **Step 6: Commit** (sensors not yet implemented, so the coordinator test will fail; we proceed and finish in the next task)

```bash
git add custom_components/door_supervisor/coordinator.py \
        custom_components/door_supervisor/__init__.py \
        tests/test_coordinator.py
git commit -m "Wire HA state changes through Door state machine via Coordinator"
```

---

## Task 12: Per-door sensors (status, open_duration, auto_lock_eta)

**Files:**
- Modify: `custom_components/door_supervisor/sensor.py`
- Modify: `custom_components/door_supervisor/strings.json`
- Modify: `custom_components/door_supervisor/translations/en.json`
- Create: `tests/test_entities.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_entities.py`:

```python
"""Tests for per-door entities."""
from __future__ import annotations

from datetime import timedelta

from freezegun import freeze_time
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.door_supervisor.const import (
    CONF_DOOR_SENSOR,
    CONF_LEFT_OPEN_THRESHOLDS,
    CONF_LOCK,
    CONF_NAME,
    DOMAIN,
    SUBENTRY_DOOR,
)


async def _setup(hass, door_data):
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
        result["flow_id"], {CONF_NAME: door_data[CONF_NAME]}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {k: v for k, v in door_data.items() if k in {CONF_LOCK, CONF_DOOR_SENSOR, "cover"}},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {k: v for k, v in door_data.items()
         if k not in {CONF_NAME, CONF_LOCK, CONF_DOOR_SENSOR, "cover"}},
    )
    await hass.async_block_till_done()
    return entry


async def test_status_sensor_reports_open(hass: HomeAssistant):
    await _setup(hass, {
        CONF_NAME: "Front Door",
        CONF_LOCK: "lock.front",
        CONF_DOOR_SENSOR: "binary_sensor.front_door",
        "auto_lock_enabled": False,
        "lock_event_notifications": True,
        CONF_LEFT_OPEN_THRESHOLDS: "",
    })
    hass.states.async_set("binary_sensor.front_door", "on")
    await hass.async_block_till_done()
    state = hass.states.get("sensor.front_door_status")
    assert state.state == "open"


async def test_open_duration_sensor_ticks(hass: HomeAssistant):
    with freeze_time(dt_util.utcnow()) as frozen:
        await _setup(hass, {
            CONF_NAME: "Front Door",
            CONF_DOOR_SENSOR: "binary_sensor.front_door",
            CONF_LEFT_OPEN_THRESHOLDS: "",
        })
        hass.states.async_set("binary_sensor.front_door", "on")
        await hass.async_block_till_done()
        state = hass.states.get("sensor.front_door_open_duration_minutes")
        assert state.state == "0"
        frozen.tick(delta=timedelta(minutes=3, seconds=1))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        state = hass.states.get("sensor.front_door_open_duration_minutes")
        assert state.state == "3"


async def test_auto_lock_eta_sensor_set_on_close(hass: HomeAssistant):
    with freeze_time(dt_util.utcnow()):
        await _setup(hass, {
            CONF_NAME: "Front Door",
            CONF_LOCK: "lock.front",
            CONF_DOOR_SENSOR: "binary_sensor.front_door",
            "auto_lock_enabled": True,
            "auto_lock_delay_minutes": 5,
            "lock_event_notifications": False,
            CONF_LEFT_OPEN_THRESHOLDS: "",
        })
        hass.states.async_set("binary_sensor.front_door", "on")
        await hass.async_block_till_done()
        hass.states.async_set("binary_sensor.front_door", "off")
        await hass.async_block_till_done()
        state = hass.states.get("sensor.front_door_auto_lock_eta")
        # should be a timestamp ~5 minutes from now, not "unavailable"
        assert state.state != "unavailable"
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_entities.py -v`

Expected: failures because sensors don't yet emit.

- [ ] **Step 3: Replace `custom_components/door_supervisor/sensor.py` with the real implementation**

```python
"""Per-door diagnostic sensors."""
from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import DOMAIN, SUBENTRY_DOOR
from .coordinator import Coordinator, DoorRuntime


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: Coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    # Coordinator may not have started yet when this runs; do it after the forward returns.
    # We rely on Coordinator.start being called in __init__'s async_setup_entry after platform forwards.
    # But platform setup runs synchronously inside async_forward_entry_setups; doors are wired in start().
    # We register a callback to add entities for each door as it's created.

    @callback
    def _add_door_entities(sub_id: str, runtime: DoorRuntime) -> None:
        async_add_entities(
            [
                StatusSensor(entry, sub_id, runtime),
                OpenDurationSensor(entry, sub_id, runtime),
                AutoLockEtaSensor(entry, sub_id, runtime),
            ]
        )

    coordinator.entity_factory = _add_door_entities
    # Also add for any doors already running (defensive — order-independent setup)
    for sub_id, runtime in coordinator.doors.items():
        _add_door_entities(sub_id, runtime)


class _DoorSensorBase(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        entry: ConfigEntry,
        sub_id: str,
        runtime: DoorRuntime,
        translation_key: str,
        suffix: str,
    ) -> None:
        self._entry = entry
        self._sub_id = sub_id
        self._runtime = runtime
        self._attr_translation_key = translation_key
        self._attr_unique_id = f"{entry.entry_id}_{sub_id}_{suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{sub_id}")},
            name=runtime.config.name,
            manufacturer="Door Supervisor",
            model="Door",
            via_device=(DOMAIN, entry.entry_id),
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._runtime.add_listener(self.async_write_ha_state))


class StatusSensor(_DoorSensorBase):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["closed", "open", "open_warning", "unknown"]

    def __init__(self, entry, sub_id, runtime):
        super().__init__(entry, sub_id, runtime, "door_status", "status")

    @property
    def native_value(self) -> str:
        return self._runtime.door.status


class OpenDurationSensor(_DoorSensorBase):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = "min"

    def __init__(self, entry, sub_id, runtime):
        super().__init__(entry, sub_id, runtime, "open_duration_minutes", "open_duration_minutes")

    @property
    def native_value(self) -> int:
        return self._runtime.door.open_duration_minutes()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Tick once a minute to refresh duration while door is open
        self.async_on_remove(
            async_track_time_interval(
                self.hass, self._tick, timedelta(seconds=60)
            )
        )

    @callback
    def _tick(self, _now: datetime) -> None:
        self.async_write_ha_state()


class AutoLockEtaSensor(_DoorSensorBase):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, entry, sub_id, runtime):
        super().__init__(entry, sub_id, runtime, "auto_lock_eta", "auto_lock_eta")

    @property
    def native_value(self) -> datetime | None:
        return self._runtime.door.auto_lock_eta

    @property
    def available(self) -> bool:
        return self._runtime.door.auto_lock_eta is not None
```

- [ ] **Step 4: Add `entity_factory` hook to coordinator**

Modify `coordinator.py` `Coordinator` class:

Add field `self.entity_factory: Callable[[str, DoorRuntime], None] | None = None` in `__init__`, and call it in `start()`:

```python
    def __init__(self, hass, entry, hub_state):
        self.hass = hass
        self.entry = entry
        self.hub_state = hub_state
        self.doors: dict[str, DoorRuntime] = {}
        self.entity_factory: Callable[[str, DoorRuntime], None] | None = None

    def start(self) -> None:
        for sub_id, sub in self.entry.subentries.items():
            if sub.subentry_type != SUBENTRY_DOOR:
                continue
            cfg = _build_config(sub)
            runtime = DoorRuntime(self.hass, self, sub_id, cfg)
            runtime.start()
            self.doors[sub_id] = runtime
            if self.entity_factory:
                self.entity_factory(sub_id, runtime)
```

- [ ] **Step 5: Add entity strings**

Modify `strings.json` and `translations/en.json` — add inside `"entity"`:

```json
    "sensor": {
      "door_status": {
        "name": "Status",
        "state": {
          "closed": "Closed",
          "open": "Open",
          "open_warning": "Open (warning)",
          "unknown": "Unknown"
        }
      },
      "open_duration_minutes": {
        "name": "Open duration"
      },
      "auto_lock_eta": {
        "name": "Auto-lock ETA"
      }
    }
```

The full `entity` block becomes:

```json
  "entity": {
    "switch": {
      "notifications_enabled": {"name": "Notifications enabled"},
      "auto_lock_enabled": {"name": "Auto-lock enabled"}
    },
    "sensor": {
      "door_status": {
        "name": "Status",
        "state": {
          "closed": "Closed",
          "open": "Open",
          "open_warning": "Open (warning)",
          "unknown": "Unknown"
        }
      },
      "open_duration_minutes": {"name": "Open duration"},
      "auto_lock_eta": {"name": "Auto-lock ETA"}
    }
  }
```

Apply this same change to both `strings.json` and `translations/en.json`.

- [ ] **Step 6: Add freezegun to test requirements**

Modify `requirements_test.txt`:

```
pytest>=8.0
pytest-asyncio>=0.23
pytest-homeassistant-custom-component>=0.13.190
freezegun>=1.5
```

Install: `pip install -r requirements_test.txt`

- [ ] **Step 7: Run all tests, verify they pass**

Run: `pytest tests/ -v`

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add custom_components/door_supervisor/sensor.py \
        custom_components/door_supervisor/coordinator.py \
        custom_components/door_supervisor/strings.json \
        custom_components/door_supervisor/translations/en.json \
        requirements_test.txt \
        tests/test_entities.py
git commit -m "Add per-door sensors (status, open_duration_minutes, auto_lock_eta)"
```

---

## Task 13: Notification dispatch tests (gating + payload shape)

**Files:**
- Create: `tests/test_notifications.py`

The dispatch logic already exists in `coordinator.py`. This task verifies it end-to-end via HA service mocking.

- [ ] **Step 1: Write tests**

Create `tests/test_notifications.py`:

```python
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
```

- [ ] **Step 2: Run tests, verify they pass**

Run: `pytest tests/test_notifications.py -v`

Expected: all 5 tests pass. If any fail, investigate the dispatch logic in `coordinator.py`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_notifications.py
git commit -m "Add notification dispatch tests for gating and payload shape"
```

---

## Task 14: Restart behavior + README + HACS polish

**Files:**
- Create: `tests/test_restart.py`
- Modify: `README.md`
- Verify: `hacs.json`, `manifest.json`

The restart logic is already implicit in `DoorRuntime.start()` — it seeds the Door from current entity states (which is "fresh" state — no retroactive timers). This task adds an explicit test for that behavior and polishes the README.

- [ ] **Step 1: Write restart test**

Create `tests/test_restart.py`:

```python
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
    calls = []

    async def fake_script(call):
        calls.append(call.data)

    hass.services.async_register("script", "notify", fake_script)
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
            result["flow_id"], {CONF_NAME: "Basement", "notification_script": "script.notify"}
        )
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], {CONF_DOOR_SENSOR: "binary_sensor.basement"}
        )
        await hass.config_entries.subentries.async_configure(
            result["flow_id"], {"left_open_thresholds_minutes": "5"}
        )
        await hass.async_block_till_done()
        # Immediately after setup: no warnings have fired (door just "opened" at startup)
        warnings = [
            c for c in calls
            if c.get("variables", {}).get("event_type") == "left_open_warning"
        ]
        assert warnings == []
        # Advance 5 minutes — NOW the warning should fire (counting from startup, not before)
        frozen.tick(delta=timedelta(minutes=5, seconds=1))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        warnings = [
            c for c in calls
            if c.get("variables", {}).get("event_type") == "left_open_warning"
        ]
        assert len(warnings) == 1
```

- [ ] **Step 2: Run test, verify it passes**

Run: `pytest tests/test_restart.py -v`

Expected: 1 passed. If it fails: confirm `DoorRuntime.start()` seeds state from `hass.states.get(...)` and that the resulting opened event schedules a threshold.

- [ ] **Step 3: Replace `README.md` with a complete user-facing README**

```markdown
# Door Supervisor

Home Assistant custom integration that centralizes door supervision:

- **Auto-lock** doors after they've been closed for N minutes (with smart "wait until actually closed" when a door sensor is configured)
- **Left-open warnings** at configurable thresholds (e.g. notify at 30, 60, and 90 minutes)
- **Lock and cover event notifications** routed through a script you control

One config entry per install, one subentry per door — no more piles of automations.

## Installation (HACS)

1. Add this repo as a custom HACS repository (type: Integration).
2. Install **Door Supervisor** from HACS.
3. Restart Home Assistant.
4. Settings → Devices & Services → Add Integration → Door Supervisor.
5. The hub is created. Click "Add door" to add each door.

## Per-door configuration

Each door is a name + any combination of:

- **Lock** entity (`lock.*`) — required for auto-lock and lock event notifications
- **Cover** entity (`cover.*`) — for garage doors and similar
- **Door sensor** (`binary_sensor.*`) — provides authoritative open/closed signal

At least one of these is required. If both a sensor and a cover are configured, the **sensor wins** for open/closed determination (because cover state can be unreliable on some hardware).

Plus optional:

- **Notification script** — a `script.*` entity that receives every notification this door emits. Without this, the door still functions (auto-lock, status sensor) but produces no notifications.

## Auto-lock

- **With open/close signal**: countdown starts when the door reaches *closed*. Cancels on open. Restarts on the next close. (No more bolt-into-jamb scenarios.)
- **Without open/close signal (lock only)**: countdown starts on the *unlock* event. Cancels if you re-lock manually.

## Left-open warnings

Configure a list of minute thresholds (e.g. `5` or `30,60,90`). The script is called once at each threshold. After the last threshold, no more warnings until the door closes and reopens.

## Notification script payload

The script receives these variables:

| Field | Always present? | Notes |
|-------|-----------------|-------|
| `door_name` | yes | User-given name |
| `event_type` | yes | `locked`, `unlocked`, `opened`, `closed`, `left_open_warning` |
| `message` | yes | Pre-formatted English message |
| `entity_id` | yes | The entity that triggered the event |
| `minutes_open` | only on `left_open_warning` | Threshold value that fired |
| `auto` | only on `locked` | `true` if auto-lock fired, `false` if manual |

Example script using the message as-is:

```yaml
notify_phone:
  fields:
    message: {}
    door_name: {}
    event_type: {}
  sequence:
    - service: notify.mobile_app_pixel
      data:
        message: "{{ message }}"
```

## Global controls

Two hub-level switches:

- `switch.door_supervisor_notifications_enabled` — kill switch for all notifications
- `switch.door_supervisor_auto_lock_enabled` — kill switch for all auto-locks

## Per-door entities

Each door produces:

- `sensor.<door>_status` — `closed` / `open` / `open_warning` / `unknown`
- `sensor.<door>_open_duration_minutes` — minutes since opening
- `sensor.<door>_auto_lock_eta` — timestamp; dashboards render as live countdown

## License

MIT.
```

- [ ] **Step 4: Run the full test suite**

Run: `pytest tests/ -v`

Expected: all tests pass.

- [ ] **Step 5: Sanity-check manifests**

Run:
```bash
python -c "import json; json.load(open('hacs.json'))"
python -c "import json; json.load(open('custom_components/door_supervisor/manifest.json'))"
python -c "import json; json.load(open('custom_components/door_supervisor/strings.json'))"
python -c "import json; json.load(open('custom_components/door_supervisor/translations/en.json'))"
```

Expected: no errors.

- [ ] **Step 6: Commit and tag**

```bash
git add tests/test_restart.py README.md
git commit -m "Add restart behavior test and complete README"
git tag v0.1.0
```

---

## Self-Review

**Spec coverage check** (each section/requirement → task):

| Spec section | Tasks |
|---|---|
| Repo layout / HACS structure | Task 1 |
| Door composition (3-entity matrix) | Task 2 (DoorConfig validation), Task 3 (sensor/cover), Task 4 (thresholds), Task 5 (lock events), Tasks 6+7 (auto-lock modes) |
| Hub config flow | Task 9 |
| Door subentry flow + options (reconfigure) | Task 10 |
| Door state machine | Tasks 3–8 |
| Open/closed precedence (sensor wins) | Task 3 |
| Auto-lock with signal | Task 6 |
| Auto-lock lock-only | Task 7 |
| Left-open thresholds | Task 4 |
| Status derivation | Task 8 |
| Notification payload | Task 13 (verifies payload shape end-to-end) |
| Gating (global + per-category + script-unset) | Task 13 |
| Hub global switches | Task 9 |
| Per-door sensors | Task 12 |
| Restart behavior | Task 14 |
| Testing strategy | Tasks 2–14 (every task is TDD) |
| Translations | Tasks 9, 10, 12 |
| README + HACS polish | Task 14 |

All spec sections covered.

**Placeholder scan:** no TBDs. Every step has executable content. Two tasks (8, 13) verify previously-written code rather than introducing new code; this is intentional and noted.

**Type consistency:**
- `DoorConfig` field names (`lock_entity_id`, `cover_entity_id`, `sensor_entity_id`) used consistently in Tasks 2–8 and Task 11 (`_build_config`).
- `Notify.make` signature (event_type, entity_id, **extras) used consistently in Tasks 3–7.
- Schedule names (`SCHED_AUTO_LOCK`, `f"{SCHED_THRESHOLD_PREFIX}{i}"`) used consistently in Tasks 4, 6, 7, 11.
- Event type constants used consistently in Tasks 3–7 and Task 13.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-19-door-supervisor.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
