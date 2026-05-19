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
