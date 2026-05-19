# Door Supervisor — Design Spec

**Date:** 2026-05-19
**Status:** Approved (pending user spec review)

## Goal

A Home Assistant custom integration that centralizes door supervision logic — auto-lock, left-open warnings, and lock/cover event notifications — so users can manage many doors from one place instead of accumulating N×M automations.

Inspired by LockManager, but scoped tightly to door behavior: each "door" is a composite of any combination of a lock, a cover, and a door sensor, plus a notification script.

## Non-goals (v1)

- **Custom Lovelace card.** The integration exposes diagnostic entities; existing HA cards render them. A custom card may be added later.
- **Per-event-category runtime switches.** Per-door category toggles (lock events, cover events, left-open) live in config only. The two global switches (notifications, auto-lock) are the only runtime knobs.
- **Retroactive notifications across HA restart.** State is reconstructed on startup; no warnings fire for time elapsed before the integration was running.
- **Multi-language UI.** English only in v1. Translation infrastructure is left in place (HA's standard `strings.json` + `translations/`) for later contribution.

## Distribution

- HACS-compatible custom integration.
- Repo follows HACS conventions: `custom_components/door_supervisor/`, `hacs.json`, README, brand assets later.

## Architecture

**Single integration, one hub config entry, N door subentries.**

```
custom_components/door_supervisor/
  __init__.py          # entry setup/teardown, platform forwarding
  config_flow.py       # main flow + subentry flow + options flow
  const.py             # DOMAIN, config keys, event_type literals, defaults
  coordinator.py       # owns all Door state machines, dispatches events
  hub.py               # hub device + global switches
  door.py              # Door state machine (pure logic, easy to unit test)
  sensor.py            # status, open_duration_minutes, auto_lock_eta
  switch.py            # global notifications + global auto-lock switches
  manifest.json
  strings.json
  translations/en.json
hacs.json
README.md
LICENSE
```

The **hub** is a single device representing the integration itself. It owns the global switches. Each **door** is a subentry of the hub config entry and becomes its own device. This pattern uses HA's subentries feature (available 2024.11+).

## Door composition

A door is **a user-given name + any combination of {lock, cover, door sensor} + an optional notification script**. At least one of {lock, cover, sensor} must be configured.

| Lock | Cover | Sensor | Valid features |
|------|-------|--------|----------------|
| ✓    |       |        | Auto-lock (counts from unlock), lock event notifications |
| ✓    |       | ✓      | Auto-lock (waits for closed), lock events, left-open warnings |
| ✓    | ✓     |        | Auto-lock (waits for closed via cover), lock + cover events, left-open warnings |
| ✓    | ✓     | ✓      | All features; sensor wins as open/closed source |
|      | ✓     |        | Cover events, left-open warnings |
|      | ✓     | ✓      | Cover events, left-open warnings (sensor wins) |
|      |       | ✓      | Left-open warnings only |

**Open/closed signal precedence:** sensor > cover. Rationale: cover state can be unreliable on some hardware; an external sensor is the source of truth when both are configured.

## Config flow

### Initial install (hub)

One step, no fields. Creates the hub config entry. Hub device appears with both global switches in default-on state.

### Add door (subentry flow)

**Step 1 — basics**
- `name` (string, required) — e.g., "Front Door"
- `notification_script` (`script.*` selector, optional) — script called for every notification this door emits

**Step 2 — entities** (at least one required)
- `lock` (`lock.*` selector, optional)
- `cover` (`cover.*` selector, optional)
- `door_sensor` (`binary_sensor.*` selector, optional; UI hints at `device_class: door` or `opening` but does not enforce)

Validation: at least one of the three must be set; else step shows an error.

**Step 3 — features** (adaptive based on step 2)
- If lock present:
  - `auto_lock_enabled` (bool, default true)
  - `auto_lock_delay_minutes` (number ≥ 1, default 5)
  - `lock_event_notifications` (bool, default true)
- If cover present:
  - `cover_event_notifications` (bool, default true)
- If sensor or cover present:
  - `left_open_thresholds_minutes` (list of positive integers, e.g. `[5]` or `[30, 60, 90]`; empty list = disabled, default empty)

### Edit door (options flow)

Same three steps, pre-filled with current values.

## Door state machine

Each door runs an internal state machine driven by HA state-change events. The coordinator owns all state machines and dispatches resulting notifications and entity updates.

### Tracked per-door state

- `open_state`: `closed` / `open` / `unknown` — derived from sensor if configured else cover if configured else `unknown` (lock-only doors).
- `open_since`: timestamp of the most recent `closed → open` transition; `None` when closed.
- `next_threshold_idx`: pointer into the sorted thresholds list — which warning fires next.
- `auto_lock_eta`: timestamp the auto-lock will fire; `None` when not counting down.

### Inputs

- Lock entity state change → `locked` / `unlocked` events
- Cover entity state change → mapped to `opened` / `closed` (open/opening states → `opened`; closed/closing → `closed`)
- Sensor entity state change → `on` → `opened`, `off` → `closed`
- HA scheduled callbacks → threshold elapsed, auto-lock delay elapsed

### Auto-lock logic

Gated by: lock configured AND `auto_lock_enabled` AND global `auto_lock_enabled` switch on.

- **With open/closed signal (sensor or cover):** countdown starts on `closed` event. Cancels on `opened`. Restarts from zero on next `closed`. After delay elapses, calls `lock.lock` service on the configured lock and emits a `locked` event with `auto: true`.
- **Without open/closed signal (lock-only):** countdown starts on `unlocked` event. Cancels if a `locked` event arrives before delay elapses. Otherwise locks.

### Left-open logic

Gated by: (sensor or cover configured) AND thresholds list non-empty.

- On `opened`: set `next_threshold_idx = 0`, schedule a callback for `thresholds[0]` minutes from now.
- When callback fires: emit `left_open_warning` with `minutes_open = thresholds[next_threshold_idx]`, increment `next_threshold_idx`, schedule next callback if more thresholds remain, else stop scheduling.
- On `closed`: cancel any pending callback, reset state.

Each `left_open_warning` fires exactly once per open cycle. No repeat after the last threshold; users who want indefinite warnings add more thresholds.

### Status transitions

`sensor.<door>_status` is derived:
- `closed` if `open_state == closed`
- `open` if `open_state == open` AND `next_threshold_idx == 0`
- `open_warning` if `open_state == open` AND at least one threshold has fired (`next_threshold_idx > 0`)
- `unknown` if `open_state == unknown`

## Notification model

The configured per-door script (if any) is called for every event the door emits, subject to gating:

1. Global `notifications_enabled` switch is **off** → suppress all.
2. `notification_script` is **unset** → suppress all (door still works for auto-lock).
3. The relevant per-door category toggle is off → suppress that category only.

### Payload

The script receives variables matching HA's `service: script.<name>` variable-passing convention:

```yaml
door_name: "Front Door"          # required, user-given name
event_type: "locked"             # required, see values below
message: "Front Door locked"     # required, pre-formatted English message
entity_id: "lock.front_door"     # required, entity that triggered the event
minutes_open: 30                 # only on left_open_warning
auto: true                       # only on locked; true if auto-lock fired, false otherwise
```

### Event types

| event_type | When | Extra fields | Gating toggle |
|------------|------|--------------|---------------|
| `locked` | Lock entity → locked | `auto: bool` | `lock_event_notifications` |
| `unlocked` | Lock entity → unlocked | — | `lock_event_notifications` |
| `opened` | Door open detected | — | `cover_event_notifications` (if cover) / treated as a cover-event for the toggle |
| `closed` | Door closed detected | — | `cover_event_notifications` |
| `left_open_warning` | Threshold elapsed | `minutes_open: int` | thresholds list non-empty |

**Note on the `opened`/`closed` gating:** these are tied to the `cover_event_notifications` toggle for cover-based doors. For sensor-only doors (no cover, no lock), `opened`/`closed` events are not user-facing notifications — only `left_open_warning` is. (This avoids spamming users with `opened` notifications from interior door sensors that don't track a cover.)

### Pre-formatted message reference

- `locked` (auto=false): `"{door_name} locked"`
- `locked` (auto=true): `"{door_name} auto-locked"`
- `unlocked`: `"{door_name} unlocked"`
- `opened`: `"{door_name} opened"`
- `closed`: `"{door_name} closed"`
- `left_open_warning`: `"{door_name} has been open for {minutes_open} minutes"`

## Entity exposure

### Hub device (`Door Supervisor`)

- `switch.door_supervisor_notifications_enabled` — global notifications kill-switch (default on)
- `switch.door_supervisor_auto_lock_enabled` — global auto-lock kill-switch (default on)

### Per-door device (named after the door)

Slug = HA-standard slug of the user-given name. Example: `Front Door` → `front_door`.

- `sensor.<slug>_status` — `closed` / `open` / `open_warning` / `unknown`
- `sensor.<slug>_open_duration_minutes` — integer minutes since `open_since`; `0` when closed. Updated on a 60-second tick while open.
- `sensor.<slug>_auto_lock_eta` — `device_class: timestamp`, value is the scheduled auto-lock fire time; `unavailable` when not counting down. Dashboards render as a live countdown via standard HA cards.

## Restart behavior

On HA start or integration reload, for each door:

1. Read current state of all configured entities. Derive `open_state` from the precedence rule.
2. If `open_state == open` at startup: set `open_since = now()`. Schedule left-open thresholds counting from now. **No retroactive notifications** for time elapsed before restart.
3. Any auto-lock countdown that was in progress before restart is dropped. Auto-lock only restarts on the next `closed` event (with-signal mode) or `unlocked` event (lock-only mode).
4. Status sensor updates to reflect derived state.

## Testing

### Unit tests (pure Python, no HA)

`door.py` state machine isolated from HA. Driven by injected events and a fake clock. Cover matrix:

- All seven door shapes from the composition table.
- Auto-lock variants: with-signal (cancel on reopen, restart on close), lock-only (cancel on manual lock during countdown).
- Threshold scheduling: single threshold, multiple thresholds, restart on close, no fire past last threshold.
- Global switches: auto-lock off → no lock service call; notifications off → no script call.

### Integration tests

Use `pytest-homeassistant-custom-component` (standard HA custom-integration test harness):

- Config flow happy path: hub setup, then add three doors of different shapes via subentry flow.
- Options flow round-trips: edit a door, values persist correctly.
- Entities are created on the right devices with correct device classes and names.
- Global switches suppress behavior end-to-end.
- Script is called with the expected payload schema per event type.
- Restart: load with door already open, verify no retroactive notifications and correct state reconstruction.

### Manual smoke test

Local HA dev container, install via HACS pointing at local repo. Set up the three real-world doors (front door, garage man door, garage car door). Verify end-to-end with a test script that writes to `persistent_notification`.

## Open questions / future work

- **Custom Lovelace card** for a richer per-door dashboard (countdown + override toggles in one place).
- **Translations** for non-English locales — strings already pulled into `strings.json` to ease later contribution.
- **Brand assets** (icon/logo) for HA brands repo submission.
- **Per-door overrides** if global-only proves too coarse in practice.
- **Manual "lock now" / "extend countdown" service calls** if dashboard interaction reveals the need.
