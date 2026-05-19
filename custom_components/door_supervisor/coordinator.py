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
        # Seed from current states (suppress notifications for the seed pass)
        for eid in entity_ids:
            state = self.hass.states.get(eid)
            if state is not None:
                self._apply_state(eid, state.state, seed=True)

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
        self._apply_state(event.data["entity_id"], new.state, seed=False)

    def _apply_state(self, entity_id: str, state: str, seed: bool = False) -> None:
        if entity_id == self.config.lock_entity_id:
            effects = self.door.on_lock_state(state)
        elif entity_id == self.config.cover_entity_id:
            effects = self.door.on_cover_state(state)
        elif entity_id == self.config.sensor_entity_id:
            effects = self.door.on_sensor_state(state == "on")
        else:
            return
        if seed:
            # During startup seed, drop Notify effects but keep Schedule/Cancel/LockNow.
            # LockNow is unlikely but we still let it through (defensive); Schedules
            # for thresholds need to be installed so warnings fire after restart.
            effects = [e for e in effects if not isinstance(e, Notify)]
        self._apply_effects(effects)

    def _apply_effects(self, effects: list) -> None:
        for effect in effects:
            if isinstance(effect, Notify):
                self.coordinator.dispatch_notify(self.config, effect)
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
        self.entity_factory: Callable[[str, DoorRuntime], None] | None = None

    def start(self) -> None:
        for sub_id, sub in self.entry.subentries.items():
            if sub.subentry_type != SUBENTRY_DOOR:
                continue
            cfg = _build_config(sub)
            runtime = DoorRuntime(self.hass, self, sub_id, cfg)
            runtime.start()
            self.doors[sub_id] = runtime
            if self.entity_factory is not None:
                self.entity_factory(sub_id, runtime)
        # Watch for subentry additions/removals in-memory (avoids full reload)
        self.entry.async_on_unload(
            self.entry.add_update_listener(self._on_entry_updated)
        )

    async def _on_entry_updated(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Handle entry updates by syncing DoorRuntime instances to current subentries.

        Called when the entry changes (e.g. a subentry is added). We add new
        DoorRuntime instances for new subentries without tearing down existing ones,
        so in-flight auto-lock and threshold timers are preserved.
        Entry data changes (e.g. from switch toggles) are already reflected in-memory
        via HubState and do not require any runtime change.
        """
        current_sub_ids = {
            sub_id
            for sub_id, sub in entry.subentries.items()
            if sub.subentry_type == SUBENTRY_DOOR
        }
        known_sub_ids = set(self.doors.keys())
        # Add runtimes for newly created subentries
        for sub_id in current_sub_ids - known_sub_ids:
            sub = entry.subentries[sub_id]
            cfg = _build_config(sub)
            runtime = DoorRuntime(hass, self, sub_id, cfg)
            runtime.start()
            self.doors[sub_id] = runtime
            if self.entity_factory is not None:
                self.entity_factory(sub_id, runtime)
        # Stop runtimes for removed subentries
        for sub_id in known_sub_ids - current_sub_ids:
            self.doors.pop(sub_id).stop()

    def stop(self) -> None:
        for runtime in self.doors.values():
            runtime.stop()
        self.doors.clear()

    def dispatch_notify(self, cfg: DoorConfig, eff: Notify) -> None:
        if not self.hub_state.notifications_enabled:
            return
        extras = eff.extras_dict
        # Suppress auto-lock notifications when global auto-lock is disabled
        if extras.get("auto") is True and not self.hub_state.auto_lock_enabled:
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
