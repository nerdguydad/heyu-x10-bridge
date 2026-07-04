# Entity Map: MisterHouse `test.mht` → Home Assistant

This is the canonical mapping of every device defined in MisterHouse
(`reference/test.mht`) to a Home Assistant entity exposed by the heyu MQTT
bridge. The machine-readable version lives in `heyu-bridge/devices.yaml`
(bridge.py reads it; this doc is the human review).

## Conventions

- **Powerline X10** (CM11): address `A1` etc. heyu command `heyu on A1` / `heyu off A1`.
- **RF security** (W800RF32A, 315 MHz): address like `b2`, `DA`, `80`. Receive-only
  (sensors/keyfobs). heyu decodes via the W800; we map each security code to a name.
- **MQTT topics**:
  - state: `x10/state/<name>` → `ON`/`OFF` (or `alert`/`normal` normalized to ON/OFF for sensors)
  - command: `x10/cmnd/<name>` → `ON`/`OFF` (controllable devices only)
  - discovery: `homeassistant/<component>/x10/<name>/config`
- **One-way X10 caveat**: basic lamp/appliance modules report no state back.
  The bridge publishes **optimistic** state on command and updates from heyu
  monitor events when the powerline is observed. RF sensors/keyfobs are
  event-driven (reliable).

## A. Lights (powerline lamp modules, controllable on/off) → `light`

| name | addr | notes |
|---|---|---|
| garage_light | A1 | |
| basement_stairwell | A10 | also auto-driven by stairwell_door / basement_motion (see automations.md) |
| backyard_light | D2 | ⚠ same address as `family_room_lamp` (D2) — see Collisions |
| bedroom_light1 | C1 | ⚠ same address as `bedroom_light2` (C1) — see Collisions |
| bedroom_light2 | C1 | ⚠ same address as `bedroom_light1` (C1) |
| laundry_room_light | C10 | also auto-driven by laundry_room motion |
| upstairs_hall_light | C12 | also auto-driven by armed-home night-light logic |
| main_floor_hall_light | C13 | also auto-driven by armed-home night-light logic |

> Brightness/dim: the stock modules here are basic (no preset dim). The bridge
> exposes these as on/off lights first. If any module is an LM14/preset-dim,
> brightness can be added later via `heyu dim`/`heyu brighten` (relative) or
> `heyu dimlevel` (preset). Flag the module type per device when known.

## B. Switches (powerline appliance / virtual control channels) → `switch`

These are X10 addresses that are commanded (and/or received) but whose *effect*
in the current system is often to trigger a Meross/Broadlink action. In HA they
become `switch` entities (state from heyu), and the trigger action becomes an
**HA automation** (see automations.md). Several need clarification on whether a
**physical X10 controller** (keypad/remote/keyfob) sends them — see "Virtual
control channels" below.

| name | addr | drives | notes |
|---|---|---|---|
| chime | C9 | (X10 chime module) | momentary on/off pulses the chime |
| disable_chime | D8 | (virtual) | chime-mute timer; effectively an input_boolean |
| family_room_floor_lamp | D1 | Meross `…810953` (Family Room Floor Lamp) | physical X10 appliance module or virtual channel? |
| family_room_lamp | D2 | Meross `…85a4a` (Family Room Lamp) | ⚠ D2 collides with `backyard_light` |
| select_hdmi | D7 | Broadlink HDMI switch macro | on→HDMI1, off→HDMI2 |
| family_room_fan | D6 | Broadlink fan IR | on→fan_on, off→fan_rotate, brighten→fan_speed, dim→fan_speed:3 |
| bedside_1 | M1 | Meross `…8582c` (Bedroom Tara Light) | |
| bedside_2 | M2 | Meross `…866a1` (Bedroom Craig Lamp) | |
| bedside_3 | M3 | Meross `…85a62` (?) | ⚠ UUID `…85a62` not in current Meross device list — removed/renamed? |
| bedside_4 | M4 | (none — no logic references bedside_4) | defined but unused; candidate for removal |
| powerhorn | E12 | (X10 powerhorn module) | pulsed on/off by powerhorn_trigger logic |

## C. Binary sensors — motion / door / light-level → `binary_sensor`

### RF security (W800, 315 MHz) — door sensors
| name | code | payload |
|---|---|---|
| garage_house_door | F4 | ON=alert(open), OFF=normal(closed) |
| stairwell_door | F7 | ON=alert, OFF=normal |
| front_door | b2 | ON=alert, OFF=normal |
| sliding_door | DA | ON=alert, OFF=normal |
| garage_outside_door | F3 | ON=alert, OFF=normal |

### RF security (W800) — motion sensors
| name | code | payload |
|---|---|---|
| front_hall | 80 | ON=alert(motion), OFF=normal |
| laundry_room | 38 | ON=alert, OFF=normal |
| upstairs_hall | CB | ON=alert, OFF=normal |

### Powerline MS13 motion sensors (CM11) — `*_motion`
| name | addr | companion dark addr |
|---|---|---|
| garage_motion | C5 | C6 (garage_motion_dark) |
| basement_motion | I1 | I2 (basement_motion_dark) |
| master_motion | K1 | (none) |

### Powerline MS13 light-level companions → `binary_sensor` (dark)
| name | addr | meaning |
|---|---|---|
| garage_motion_dark | C6 | ON=dark, OFF=light (from MS13 brightness) |
| basement_motion_dark | I2 | ON=dark, OFF=light |

## D. Triggers / keyfobs (RF security, W800) → `device_trigger` or `sensor`

These emit discrete events (not simple on/off). Represented as HA
`device_trigger` (for automation triggers) and/or a `sensor` with last-event
state.

| name | code | events |
|---|---|---|
| craig_security_fob | BE | `lights_on`, `lights_off` (drives 2 Meross living-room lamps) |
| craig_bedside_control | B8 | `arm_home`, `arm_away`, `disarm` (drives alarm modes) |
| tara_bedside_control | E1 | `arm_home`, `arm_away`, `disarm` (drives alarm modes) |

## E. Trigger input → `binary_sensor` / `sensor`
| name | addr | notes |
|---|---|---|
| powerhorn_trigger | E13 | ON triggers the powerhorn pulse pattern (see automations.md) |

## F. MisterHouse modes (virtual, from `test_x10.pl`) → HA

These are MH-internal state set by the keyfobs and read by the alarm logic.
In HA they become real entities:

| MH mode | HA component | states |
|---|---|---|
| mode_security | `alarm_control_panel` | disarmed / armed_home / armed_away |
| mode_occupied | `input_select` (or sensor) | home / work |
| mode_sleeping | `input_select` (or sensor) | all / none |

The keyfobs (craig/tara_bedside_control) arm/disarm the panel; the armed-home
night-light logic reads the panel state (see automations.md).

---

## ⚠ Collisions to resolve (pre-existing in `test.mht`)

1. **D2 — `backyard_light` (X10I) and `family_room_lamp` (X10A).**
   Same powerline address. Sending D2 ON would both toggle the backyard light
   **and** trigger the family_room_lamp Meross action. Almost certainly a
   config error or an intentional (but confusing) reuse. **Needs your call:**
   move one to a free address, or confirm they're meant to share D2.

2. **C1 — `bedroom_light1` and `bedroom_light2` (both X10I).**
   Same address → cannot be independently controlled (one X10 command drives
   both). Likely two physical lamps on one address, or a duplicate. **Needs your
   call:** merge to one entity, or reassign one to a free address.

## ❓ Virtual control channels — clarification needed

Several X10 addresses (D1, D2-lamp, D6, D7, M1–M4) appear to be **control
channels**: a physical X10 transmitter (keypad, mini-controller, keyfob, motion
sensor) sends the address, MisterHouse catches it, and drives a Meross/Broadlink
device. The bridge will **receive** these (so existing physical controllers keep
working) and expose them as switch/sensor entities; the Meross/Broadlink action
becomes an HA automation.

**Question for each:** is there a physical X10 controller that sends this
address today? If **yes**, keep it as a received trigger. If **no** (only MH
code ever set it internally), it's vestigial and can be dropped — the
upstream trigger (e.g. keyfob RF) can directly drive the HA automation.

Please confirm which of {family_room_floor_lamp D1, family_room_lamp D2,
select_hdmi D7, family_room_fan D6, bedside_1–4 M1–M4} have physical X10
controllers behind them.
