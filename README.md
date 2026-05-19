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

**Note on `opened` / `closed` events:** these fire only for doors with a cover entity configured (with `cover_event_notifications` enabled). Sensor-only doors emit only `left_open_warning`. If you want to be notified every time a sensor-only door opens or closes, configure thresholds — or add a cover entity if your hardware supports it.

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
