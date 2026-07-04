# Meross & Broadlink → native Home Assistant

These two subsystems move to **native HA integrations** (no MisterHouse, no
custom bridge). The X10/RF triggers that currently drive them become HA
automations (see automations.md) firing on the native entities.

## Meross (WiFi smart plugs) → HA Meross integration

All current devices are supported by the HA Meross integration you already use.
Move them off the `merossiot/examples/misterhouse-interface.py` bridge entirely.

### Meross devices (verified 2026-07-02 — 7 active, 4 removed)
| name | uuid | type | HA entity | used by automation |
|---|---|---|---|---|
| Electronic Lab | 21031892218724290d5948e1e9651961 | mss425e (strip) | `switch.electronic_lab_mss425e_main_channel` + 4 sub-switches + USB + DND | — |
| Bedroom Tara Light | 2109273190475351807348e1e978582c | mss110 | `switch.bedroom_tara_light_mss110_main_channel` | #17 (M1) |
| Bedroom Craig Lamp | 2109270216191251807348e1e97866a1 | mss110 | `switch.bedroom_craig_lamp_mss110_main_channel` | #17 (M2) |
| Living Room Green Lamp | 2109275593887451807348e1e9786c7b | mss110 | `switch.living_room_green_lamp_mss110_main_channel` | #16 (keyfob) |
| Living Room Corner Lamp | 2109279915196351807348e1e9786741 | mss110 | `switch.living_room_corner_lamp_mss110_main_channel` | #16 (keyfob) |
| Family Room Floor Lamp | 2112093764679151859248e1e9810953 | mss110 | `switch.family_room_floor_lamp_mss110_main_channel` | #6 (D1) |
| Garage Overhead Light | 2112093212068551859248e1e980f4ed | mss110 | `switch.garage_overhead_light_mss110_main_channel` | #3, #4, #5 |

### Removed devices (2026-07-02)
| name | uuid | reason |
|---|---|---|
| Family Room Lamp | 2109270188328051807348e1e9785a4a | not plugged in |
| Bedroom Fan | 2109271350210351807348e1e9786fc5 | gone |
| Living Room Gooseneck | 2109274835840651807348e1e97865e3 | gone |
| Garage Door | 2110295666684836102548e1e97b0697 | new opener (not Meross) |

**Note:** Meross integration exposes all devices as `switch.*` entities (not `light.*`).
Automations must use `switch.turn_on` / `switch.turn_off` service calls.

### Open questions
- UUID `2109274178300251807348e1e9785a62` is targeted by `master_motion` and
  `bedside_3` in `test_x10.pl` but is **not** in the current Meross device list.
  Needs a new Meross plug for master bedroom. (Automations #10 and #17 depend on it.)
- Automation #7 (D2 palmpad → Family Room Lamp) — Meross lamp removed (not plugged in).
  Decide: remove automation, wait for lamp to be plugged back in, or repoint D2 to a different device.

### Migration step
1. Add the Meross integration in HA (Settings → Devices & services).
2. Confirm all devices above appear and are controllable.
3. Replace the MH bridge URL calls in automations with the native entity IDs.
4. Stop `merossiot/examples/misterhouse-interface.py` (part of retiring MH).

## Broadlink (IR/RF) → HA Broadlink integration

The current `broadlinkgo-linux-amd64` daemon sends IR commands to a Broadlink
device. HA has a **core Broadlink integration** that can learn/store IR codes
and fire them — replace broadlinkgo with it.

### Broadlink device
- `broadlinkgo/devices.gob` references MAC `ec:0b:ae:98:dd:a8` @ `192.168.86.65:24374`.
- HA entity: `remote.family_room` (already added to HA)

### Scripts created in HA (2026-07-02)
| script | IR code | status | fired by automation |
|---|---|---|---|
| `script.fan_on` | fan_on | ✅ tested | #9 (D6 ON) |
| `script.fan_rotate` | fan_rotate | ✅ tested | #9 (D6 OFF) |
| `script.fan_speed_up` | fan_speed | created, untested | #9 (D6 brighten) |
| `script.hdmi_select_1` | input_select + source_hdmi_1 | created, untested | #8 (D7 ON) |
| `script.hdmi_select_2` | input_select + source_hdmi_2 | created, untested | #8 (D7 OFF) |
| `script.tv_power_on` | power_on | ❌ stale code, needs relearn | — (not in MH automations) |

### TODO
- [ ] Test `hdmi_select_1` and `hdmi_select_2` with TV
- [ ] Test `fan_speed_up`
- [ ] Relearn `tv_power_on` via Broadlink learn_command (point TV remote at device)
- [ ] Stop `broadlinkgo-linux-amd64` on x10 box (part of retiring MH)
