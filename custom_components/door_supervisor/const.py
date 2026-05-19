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
DEFAULT_LEFT_OPEN_THRESHOLDS: tuple[int, ...] = ()

# Event type values passed to notification script
EVENT_LOCKED = "locked"
EVENT_UNLOCKED = "unlocked"
EVENT_OPENED = "opened"
EVENT_CLOSED = "closed"
EVENT_LEFT_OPEN_WARNING = "left_open_warning"

# Hub-level global switch keys (stored in hub config entry data)
# Note: the string values intentionally match per-door CONF_* keys above.
# These live in *separate* config entry data dicts (hub entry vs. door subentry)
# so the keys never collide in practice. They also match attribute names on
# HubState (added in a later task) so the switch entity can use getattr.
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
