# STIGA Robot Mower for Home Assistant

Unofficial Home Assistant integration for **STIGA A-series robot mowers** (the ones used with the
STIGA.GO app). See the robot's status, start it whatever its schedule says, send it home, change
the blade height and edit the weekly schedule — all from Home Assistant.

> Not affiliated with or endorsed by STIGA. The protocol is reverse-engineered; STIGA can change
> it at any time. Tested on a **STIGA A 6v** (firmware 0.2.x) with Home Assistant 2026.8.

> [!NOTE]
> **Built on Matthew Gream's [stiga-api](https://github.com/matthewgream/stiga-api).** This
> integration uses only part of the robot protocol he reverse-engineered. His project also offers
> a web interface, analysis tools and command-line tools for STIGA robots — have a look if you
> want more than Home Assistant control.

## Features

| Entity | What it does |
|---|---|
| `lawn_mower.<robot>` | Start mowing (now, regardless of the schedule), pause, return to the dock |
| `sensor.<robot>_status` — *Activity* | `home`, `mowing`, `returning`, `rain_pause`, `paused`, `error`, `updating`, `calibrating`. Attributes: raw robot state, docked, rain detected, rain sensor and delay, schedule enabled |
| `sensor.<robot>_error` — *Status* | `No error`, or what is wrong, e.g. *Stuck: trapped*, *High grass (going home)*, *Lid open* |
| `sensor.<robot>_battery` | Battery % |
| `sensor.<robot>_garden_coverage` / `_zone_coverage` | How much of the garden / current zone has been mowed, % |
| `sensor.<robot>_schedule` | One-line summary (e.g. *Mon–Fri 13:00–17:00*); per-day mowing times and the configured blocks as attributes |
| `number.<robot>_cutting_height` | Blade height, 20–60 mm in 5 mm steps. Only accepted while the robot is in its dock; every change is followed by a blade calibration |
| `switch.<robot>_<day>_<block>` | One switch per weekday and schedule block (default *morning* 09–13 and *afternoon* 13–17). Times outside the blocks are left untouched |

Status updates are pushed by the robot over the STIGA cloud; the integration additionally asks
for a fresh status every minute while mowing and every five minutes otherwise.

**Rain:** a pause caused by the rain sensor shows as `rain_pause`. The robot does not report when
the pause ends.

## Installation

### HACS (recommended)

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/frigussolutions/ha-stiga`,
   category **Integration**.
2. Install **STIGA Robot Mower** and restart Home Assistant.

### Manual

Copy `custom_components/stiga` to `<config>/custom_components/stiga` and restart Home Assistant.

## Setup

**Settings → Devices & services → Add integration → STIGA Robot Mower**, then sign in with your
STIGA.GO email and password. Every robot in the account's garage is added as a device.

### Schedule blocks

**Configure** on the integration lets you define up to three blocks (name, start, end, on half
hours; an end of 00:00 means midnight). Each block becomes one switch per weekday. Switching one
on schedules that whole block on that day; switching it off clears it.

## Dashboard card (optional)

`dashboard/stiga-schedule-card.js` draws the schedule as a grid of checkboxes: one row per
weekday, one column per block.

1. Copy it to `<config>/www/stiga-schedule-card.js`.
2. **Settings → Dashboards → ⋮ → Resources → Add**: `/local/stiga-schedule-card.js`,
   type *JavaScript module*.
3. Add the card:

```yaml
type: custom:stiga-schedule-card
entity: sensor.stiga_a6v_schedule   # your robot's schedule sensor
```

## The client certificate

The robot's MQTT broker requires the client certificate built into the STIGA.GO app. This
repository does **not** contain it. On first setup the integration downloads it once from the
[stiga-api](https://github.com/matthewgream/stiga-api) project, pinned to a specific commit and
checked against a SHA-256 hash, and keeps it in Home Assistant's storage.

To use your own copy instead (for example, extracted from the APK), put `client.crt` and
`client.key` in `<config>/stiga/`; they take precedence.

The brokers' certificates are verified against pinned copies of STIGA's CAs (`certs/`). A robot on
a broker without a pinned CA still connects, with a warning in the log.

## How it works

- Login: Firebase email/password authentication, as the STIGA.GO app does.
- Device list: `connectivity-production.stiga.com/api/garage`.
- Live data and commands: MQTT over TLS to `robot-mqtt-<broker>.stiga.com:8883`, with
  schemaless protobuf messages (`<MAC>/LOG/STATUS`, `<MAC>/CMD_ROBOT`, …).
- Settings changes send all settings back exactly as the robot reported them, with only the blade
  height changed, so nothing else gets reset. Schedule changes rewrite the weekly bitmap in the
  robot's own (packed varint) encoding.
- Only known, harmless commands are ever sent. Some undocumented command ids are known to
  damage robots; they are not used.

## Limitations

- Developed and tested on one A 6v. Other A-series models (A 1500, A 3000, …) share the protocol
  and should work, but are untested — reports welcome.
- Depends on the STIGA cloud; no local control.
- Coverage figures are what the robot reports; with one zone, garden and zone coverage are equal.

## Development

```bash
pip install -r requirements_test.txt
pytest
```

## Credits and licence

The protocol knowledge comes from Matthew Gream's reverse-engineered
[stiga-api](https://github.com/matthewgream/stiga-api) (Node.js). This integration is a Python
port and adaptation of the protocol elements it needs; the web interface, analysis tools and
command-line tools are only in stiga-api.

stiga-api itself is licensed CC BY-NC-SA 4.0. Matthew Gream has granted this integration a
permanent licence for this derived work under the **[MIT licence](LICENSE)**, on the condition
that the attribution and the link back to his project stay — please keep them in any fork. He
also agreed to the integration downloading the client certificate from his repository.

The integration icon is `robot-mower` from [Material Design Icons](https://pictogrammers.com/library/mdi/)
(Apache-2.0).

STIGA and STIGA.GO are trademarks of their respective owner.
