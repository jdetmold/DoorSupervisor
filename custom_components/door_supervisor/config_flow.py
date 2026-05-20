"""Config flow for door_supervisor."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
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
            if self.source == SOURCE_RECONFIGURE:
                return self.async_update_and_abort(
                    self._get_entry(),
                    self._get_reconfigure_subentry(),
                    title=title,
                    data=self._data,
                )
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
