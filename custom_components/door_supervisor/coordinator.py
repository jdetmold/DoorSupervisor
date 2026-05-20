"""Coordinator: wires HA state changes to Door state machines and dispatches effects."""
from __future__ import annotations

import logging
from typing import Callable

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import (
    CONF_AUTO_LOCK_DELAY_MINUTES,
    CONF_AUTO_LOCK_ENABLED,
    CONF_COVER,
    CONF_DOOR_SENSOR,
    CONF_LEFT_OPEN_THRESHOLDS,
    CONF_LOCK,
    CONF_LOCK_EVENT_NOTIFICATIONS,
    CONF_NAME,
    CONF_OPEN_CLOSE_NOTIFICATIONS,
    DEFAULT_AUTO_LOCK_DELAY_MINUTES,
    DEFAULT_AUTO_LOCK_ENABLED,
    DEFAULT_LOCK_EVENT_NOTIFICATIONS,
    DEFAULT_OPEN_CLOSE_NOTIFICATIONS,
    DOMAIN,
    EVENT_CLOSED,
    EVENT_LOCKED,
    EVENT_OPENED,
    EVENT_UNLOCKED,
    LEGACY_CONF_COVER_EVENT_NOTIFICATIONS,
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
        auto_lock_enabled=data.get(CONF_AUTO_LOCK_ENABLED, DEFAULT_AUTO_LOCK_ENABLED),
        auto_lock_delay_minutes=data.get(
            CONF_AUTO_LOCK_DELAY_MINUTES, DEFAULT_AUTO_LOCK_DELAY_MINUTES
        ),
        lock_event_notifications=data.get(
            CONF_LOCK_EVENT_NOTIFICATIONS, DEFAULT_LOCK_EVENT_NOTIFICATIONS
        ),
        open_close_notifications=data.get(
            CONF_OPEN_CLOSE_NOTIFICATIONS,
            data.get(LEGACY_CONF_COVER_EVENT_NOTIFICATIONS, DEFAULT_OPEN_CLOSE_NOTIFICATIONS),
        ),
        left_open_thresholds_minutes=tuple(thresholds),
    )


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
        _LOGGER.debug(
            "Door %s: state change %s=%s (seed=%s)",
            self.config.name, entity_id, state, seed,
        )
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
                self.coordinator.fire_event(self.config, effect)
            elif isinstance(effect, LockNow):
                if self.coordinator.should_block_auto_lock():
                    _LOGGER.debug(
                        "Auto-lock for %s blocked by global auto-lock switch",
                        self.config.name,
                    )
                    continue
                _LOGGER.info(
                    "Auto-lock firing for %s: calling lock.lock on %s",
                    self.config.name,
                    self.config.lock_entity_id,
                )
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
            _LOGGER.info(
                "Door Supervisor: watching '%s' (lock=%s cover=%s sensor=%s "
                "auto_lock=%s delay=%smin thresholds=%s)",
                cfg.name, cfg.lock_entity_id, cfg.cover_entity_id,
                cfg.sensor_entity_id, cfg.auto_lock_enabled,
                cfg.auto_lock_delay_minutes, cfg.left_open_thresholds_minutes,
            )
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

    def fire_event(self, cfg: DoorConfig, eff: Notify) -> None:
        """Fire an HA event for a door supervisor notification.

        Gating layers:
        - Global notifications_enabled switch
        - Per-door category toggle (lock_event_notifications, open_close_notifications)

        Left-open warnings are always fired (the threshold list is the schedule).
        """
        if not self.hub_state.notifications_enabled:
            _LOGGER.debug("Event %s for %s suppressed: global notifications off",
                          eff.event_type, cfg.name)
            return
        extras = eff.extras_dict
        # Suppress auto-lock fired notifications when global auto-lock is disabled
        if extras.get("auto") is True and not self.hub_state.auto_lock_enabled:
            _LOGGER.debug("Event %s (auto=true) for %s suppressed: global auto-lock off",
                          eff.event_type, cfg.name)
            return
        # Per-category gating
        if eff.event_type in (EVENT_LOCKED, EVENT_UNLOCKED):
            if not cfg.lock_event_notifications:
                _LOGGER.debug("Event %s for %s suppressed: lock_event_notifications off",
                              eff.event_type, cfg.name)
                return
        elif eff.event_type in (EVENT_OPENED, EVENT_CLOSED):
            if not cfg.open_close_notifications:
                _LOGGER.debug(
                    "Event %s for %s suppressed: open_close_notifications off",
                    eff.event_type, cfg.name,
                )
                return
        # Fire the event
        event_type = f"{DOMAIN}.{eff.event_type}"
        event_data = {
            "door": cfg.name,
            "entity_id": eff.entity_id,
            **extras,
        }
        _LOGGER.info("Firing event %s for door %s: %s", event_type, cfg.name, event_data)
        self.hass.bus.async_fire(event_type, event_data)

    def should_block_auto_lock(self) -> bool:
        return not self.hub_state.auto_lock_enabled
