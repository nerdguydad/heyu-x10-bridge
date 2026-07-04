# Automation Port List: `test_x10.pl` → Home Assistant automations

Every behavior in `reference/test_x10.pl`, translated to an HA automation.
Pure-X10 behaviors run on entities from the bridge; Meross/Broadlink behaviors
run on **native HA** entities (see meross-broadlink.md) and are triggered by the
X10/RF entities the bridge exposes.

Legend: `[X10]` = uses bridge entities only; `[MEROSS]` = drives native Meross;
`[BROADLINK]` = drives native Broadlink; `[MODE]` = reads/writes HA alarm/mode.

## 1. Stairwell door → basement stairwell light  `[X10]`
- Trigger: `stairwell_door` → alert (ON)
  - Action: turn `basement_stairwell` ON; cancel its off-timer
- Trigger: `stairwell_door` → normal (OFF)
  - Action: start/restart 5-min timer
- Timer expired: turn `basement_stairwell` OFF

## 2. Basement motion → basement stairwell light  `[X10]`
- Trigger: `basement_motion` → ON
  - Action: turn `basement_stairwell` ON; start/restart 5-min timer
- (shares the same off-timer as #1)

## 3. Garage house door → Meross Garage Overhead Light  `[MEROSS]`
- Trigger: `garage_house_door` → alert
  - Action: turn ON Meross `Garage Overhead Light` (`…80f4ed`)
- Trigger: `garage_house_door` → normal
  - Action: start/restart `garage_lights_timer` (10 min, or 20 min in winter)
- `garage_lights_timer` expired: turn OFF Meross Garage Overhead Light
- Winter = Dec–Feb (or use a seasonal template sensor)

## 4. Garage outside door → same Meross Garage Overhead Light  `[MEROSS]`
- Same pattern as #3, trigger is `garage_outside_door` → alert/normal
- Shares `garage_lights_timer` (10 min / 20 min winter)

## 5. Garage motion overrides garage light timer  `[X10]` (interacts with #3/#4)
- Trigger: `garage_motion` → ON: cancel `garage_lights_timer`
- Trigger: `garage_motion` → OFF: start/restart `garage_lights_timer` (10 min / 20 min winter)

## 6. Family room floor lamp (D1) → Meross Family Room Floor Lamp  `[MEROSS]`
- Trigger: `family_room_floor_lamp` → on/off
  - Action: set Meross `Family Room Floor Lamp` (`…810953`) to same state

## 7. ~~Family room lamp (D2) → Meross Family Room Lamp~~  `[REMOVED]`
- Meross Family Room Lamp not plugged in; D2 removed from bridge.
- If lamp is restored, re-add D2 as X10 entity and recreate this automation.

## 8. select_hdmi (D7) → Broadlink HDMI switch  `[BROADLINK]`
- Trigger: `select_hdmi` → ON: fire Broadlink macro `hdmi_1/input_select/delay/source_hdmi_1`
- Trigger: `select_hdmi` → OFF: fire Broadlink macro `hdmi_2/input_select/delay/source_hdmi_2`
- ⚠ current code calls `http://192.168.86.200:8000/...` but broadlinkgo device is
  at `.65`; in HA this becomes native Broadlink IR commands (no HTTP) — see meross-broadlink.md

## 9. family_room_fan (D6) → Broadlink fan IR  `[BROADLINK]`
- Physical X10 palmpad confirmed — D6 stays as X10 entity
- D6 ON → Broadlink IR `fan_on`
- D6 OFF → Broadlink IR `fan_rotate`
- D6 brighten → Broadlink IR `fan_speed`
- D6 dim → Broadlink IR `fan_speed` (was `fan_speed:3` URL hack)
- HA automation fires Broadlink scripts on D6 state changes

## 10. master_motion (K1) → Meross lamp  `[MEROSS]`
- Trigger: `master_motion` → ON: turn ON Meross master bedroom light (TBD UUID)
- Sensor (K1) is alive; needs a new Meross light to be set up in master bedroom

## 11. disable_chime (D8) → chime-mute timer  `[X10]`
- `disable_chime` ON → start 10-min `chime_disable_timer`
- `disable_chime` OFF / timer expired → clear mute
- (read by #12/#13)

## 12. front_door chime  `[X10]`
- Trigger: `front_door` → alert: if mute inactive, pulse `chime` ON then OFF;
  start 30-s `front_door_chime_timer`
- Trigger: `front_door` → normal: cancel timer
- Timer expired: re-pulse chime; restart timer (keeps chiming while open)

## 13. sliding_door chime  `[X10]`
- Same pattern as #12, trigger is `sliding_door`

## 14. laundry_room motion → laundry_room_light  `[X10]`
- Trigger: `laundry_room` → alert: turn `laundry_room_light` ON
- Trigger: `laundry_room` → normal: start 5-min `laundry_room_light_timer`
- Timer expired: turn `laundry_room_light` OFF

## 15. powerhorn_trigger → powerhorn pulse  `[X10]`
- Trigger: `powerhorn_trigger` → ON: pulse `powerhorn` on/off 3x; start 1-s timer
- Trigger: `powerhorn_trigger` → OFF: cancel timer
- Timer expired: pulse `powerhorn` on/off; restart 1-s timer (continuous while trigger on)

## 16. craig_security_fob → 2 Meross living-room lamps  `[MEROSS]`
- Trigger: `craig_security_fob` → `lights_on`/`lights_off`
  - Action: set Meross `Living Room Green Lamp` (`…86c7b`) and
    `Living Room Corner Lamp` (`…86741`) to that state
  - (commented-out 3rd: `Living Room Gooseneck` `…865e3`)

## 17. bedside_1/2/3 → Meross lamps  `[MEROSS]`
- `bedside_1` on/off → Meross `Bedroom Tara Light` (`…8582c`)
- `bedside_2` on/off → Meross `Bedroom Craig Lamp` (`…866a1`)
- `bedside_3` on/off → Meross master bedroom light (TBD UUID, same as #10)
- Physical X10 bedside remotes confirmed for M1/M2/M3

## 17b. bedside_4 (M4) → TBD  `[NEW]`
- Physical X10 bedside remote confirmed for M4
- New use — to be determined

## 18. Keyfob arm/disarm → alarm modes  `[MODE]`
- `craig_bedside_control` / `tara_bedside_control`:
  - `arm_home` → `alarm_control_panel` armed_home; mode_occupied=home; mode_sleeping=all
  - `arm_away` → armed_away; mode_occupied=work; mode_sleeping=none
  - `disarm` → disarmed; mode_occupied=home; mode_sleeping=none

## 19. Armed-home night lights (front_hall / upstairs_hall)  `[MODE]`+`[X10]`
- Condition: `mode_security` == armed_home (i.e. occupied=home)
- `front_hall` alert → turn ON `upstairs_hall_light` + `main_floor_hall_light`
- `front_hall` normal → start 60-s `night_light_timer`
- `upstairs_hall` alert → turn ON `upstairs_hall_light`
- `upstairs_hall` normal → start 60-s `night_light_timer`
- `night_light_timer` expired → turn OFF `upstairs_hall_light` + `main_floor_hall_light`
- TODO (commented in MH): "any door openings trigger the alarm immediately" when
  armed_away; and "sound the alarm for any movement" when armed_away — currently
  stubbed. Decide whether to implement now or later.

## Notes
- Timers: implement with HA `timer` entities + automations, or `delay`/`wait`.
- The armed-away alarm siren (powerhorn) path is a stub in MH — flag for decision.
- Several automations (#3,#4,#5) share `garage_lights_timer`; keep that logic
  coherent in HA (one timer, multiple restart sources).

---

# Non-X10 Automations (Zigbee)

## Aqara Cube T1 Pro — Shake → Family Room Light + Fan OFF  `[ZIGBEE]`
- Trigger: MQTT topic `zigbee2mqtt/0x54ef441000eee0ef/action` payload `shake`
- Action: turn off Meross Family Room Floor Lamp + toggle Broadlink fan off
- Device: Aqara Cube T1 Pro (CTP-R01), IEEE 0x54ef441000eee0ef, scene_mode
- Available gestures: shake, flip_to_side, side_up, rotate (with angle)
- Automation ID: `aqara_cube_shake_off` in `/config/automations.yaml`
