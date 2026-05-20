# Door Supervisor

A Home Assistant custom integration that centralizes door supervision:

- **Auto-lock** doors after they've been closed for N minutes (waits for the door to actually close when a sensor is configured — no bolt-into-jamb)
- **Left-open warnings** at configurable thresholds (e.g. 30, 60, 90 minutes)
- **Native HA events** for every lock/cover/open/close/warning, so you route notifications with a normal HA automation — full trace support, any notify channel, any logic

One config entry per install, one subentry per door — no more piles of per-door automations for the supervision logic itself.

## Installation (HACS)

1. HACS → Integrations → ⋮ → Custom repositories.
2. Add `https://github.com/jdetmold/DoorSupervisor` with category **Integration**.
3. Install **Door Supervisor**, restart Home Assistant.
4. Settings → Devices & Services → Add Integration → Door Supervisor.
5. The hub is created. Click **Add door** to add each door.

## Per-door configuration

Each door is a name + any combination of:

- **Lock** (`lock.*`) — required for auto-lock and lock events
- **Cover** (`cover.*`) — for garage doors and similar
- **Door sensor** (`binary_sensor.*`) — authoritative open/closed signal

At least one is required. If both a sensor and a cover are configured, the **sensor wins** for open/closed determination (cover state can be unreliable on some hardware).

Edit any door later via the gear icon on the integration page — all settings (entities, auto-lock delay, thresholds, toggles) are editable.

## Auto-lock

The countdown starts when the door is **unlocked** and resets every time the door **closes**:

- Unlock a door → countdown starts (even if you never open it — it'll still lock).
- Open the door → countdown pauses (we won't throw the bolt into an open door). It restarts when the door closes.
- Each close resets the countdown to the full delay.
- Manually lock → countdown cancels.

For **lock-only doors** (no door sensor or cover), the countdown simply runs from the unlock event and locks after the delay.

The global **Auto-lock** switch on the hub suppresses all auto-locking when off.

## Left-open warnings

Configure a comma-separated list of minute thresholds (e.g. `5` or `30,60,90`). One warning event fires at each threshold. After the last threshold, no more until the door closes and reopens.

## Notifications — you write one automation

Door Supervisor fires native HA events. You handle notifications however you like in a normal automation (with full trace support).

### Events fired

| Event | Data | When |
|-------|------|------|
| `door_supervisor.opened` | `door`, `entity_id` | Door opened (cover-based doors) |
| `door_supervisor.closed` | `door`, `entity_id` | Door closed (cover-based doors) |
| `door_supervisor.locked` | `door`, `entity_id`, `auto` | Lock locked (`auto: true` if auto-lock fired) |
| `door_supervisor.unlocked` | `door`, `entity_id` | Lock unlocked |
| `door_supervisor.left_open_warning` | `door`, `entity_id`, `minutes_open` | A configured threshold elapsed |

Notes:
- `opened`/`closed` events fire only for doors with a **cover** configured (and `cover_event_notifications` enabled). Sensor-only doors fire `left_open_warning` only.
- `locked`/`unlocked` fire only when `lock_event_notifications` is enabled for the door.
- The global **Notifications** switch (on the hub device) suppresses all events when off.
- The global **Auto-lock** switch suppresses both the lock action and the `auto: true` event when off.

### Example notification automation

```yaml
- alias: "Door Supervisor notifications"
  trigger:
    - platform: event
      event_type: door_supervisor.unlocked
    - platform: event
      event_type: door_supervisor.locked
    - platform: event
      event_type: door_supervisor.left_open_warning
  action:
    - variables:
        door: "{{ trigger.event.data.door }}"
        kind: "{{ trigger.event.event_type.split('.')[1] }}"
    - choose:
        - conditions: "{{ kind == 'left_open_warning' }}"
          sequence:
            - service: notify.mobile_app_jjdiphone15
              data:
                title: "⚠️ {{ door }} left open"
                message: "{{ door }} has been open for {{ trigger.event.data.minutes_open }} minutes"
        - conditions: "{{ kind == 'locked' }}"
          sequence:
            - service: notify.mobile_app_jjdiphone15
              data:
                message: >
                  {{ door }} {{ 'auto-locked' if trigger.event.data.auto else 'locked' }}
      default:
        - service: notify.mobile_app_jjdiphone15
          data:
            message: "{{ door }} {{ kind }}"
```

### Adding "who unlocked" (Keymaster, RFID, etc.)

Because notifications are just an automation, you have full access to whatever other integrations expose. Look it up at trigger time — no Door Supervisor configuration required. For example, with Keymaster:

```yaml
    - service: notify.mobile_app_jjdiphone15
      data:
        message: >
          {{ door }} unlocked
          {%- set who = state_attr('sensor.front_door_keymaster', 'usercode_name') %}
          {%- if who %} by {{ who }}{% endif %}
```

Use whatever attribute or entity your setup actually exposes — the integration doesn't need to know about it.

## Global controls

Two switches on the **Door Supervisor** hub device:

- `switch.door_supervisor_notifications_enabled` — kill switch for all events
- `switch.door_supervisor_auto_lock_enabled` — kill switch for all auto-locks

## Per-door entities

Each door produces:

- `sensor.<door>_status` — `closed` / `open` / `open_warning` / `unknown`
- `sensor.<door>_open_duration_minutes` — minutes since opening
- `sensor.<door>_auto_lock_eta` — timestamp; dashboards render as a live countdown

## Troubleshooting

Enable debug logging to see exactly what the integration is doing:

```yaml
logger:
  default: info
  logs:
    custom_components.door_supervisor: debug
```

You'll see lines for every state change received, every event fired (and why one was suppressed), and every auto-lock service call. If an auto-lock log appears but the lock doesn't move, the problem is with the lock/Z-Wave, not this integration.

## License

MIT.
