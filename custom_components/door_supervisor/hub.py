"""Hub-level shared state."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class HubState:
    """Mutable global state shared between switches and the coordinator."""

    notifications_enabled: bool = True
    auto_lock_enabled: bool = True
