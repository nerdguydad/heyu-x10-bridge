#!/usr/bin/env python3
"""
heyu MQTT bridge for Home Assistant.

Bridges X10 powerline (CM11) and X10 security RF (W800RF32A, 315 MHz) — as
managed by `heyu` — to Home Assistant over MQTT, using MQTT discovery so HA
auto-creates entities.

Design:
  - Reads devices.yaml (the device map translated from MisterHouse test.mht).
  - Publishes HA MQTT discovery for every device (light/switch/binary_sensor/
    sensor/device_trigger/alarm_control_panel/input_select).
  - Subscribes to command topics for controllable devices; on command, runs
    `heyu on|off <addr>` (and dim/brighten for lights, future).
  - Runs `heyu monitor` as a subprocess and parses events to publish state.
    RF security sensors and MS13 motion are event-driven (reliable). Basic
    powerline lamp modules are one-way; their state is optimistic (set on
    command, corrected if heyu monitor observes a powerline state change).

This runs inside the HA OS add-on container. MQTT broker is reached via the
add-on `mqtt` service (credentials supplied in env by HA). heyu engine must be
running (started by run.sh) for `heyu monitor` to receive events.

NOTE: the exact format of `heyu monitor` output is verified during Phase 2
testing against real hardware. The parser below is structured to be adjusted
with the real field layout; it is intentionally defensive.
"""

import argparse
import json
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt
import yaml

log = logging.getLogger("heyu-bridge")

# ───────────────────────── helpers ─────────────────────────

def normalize_state(raw: str) -> str:
    """Map raw heyu state text to HA ON/OFF where possible."""
    if raw is None:
        return ""
    r = raw.strip().lower()
    if not r:
        return ""
    if r.startswith("alert"):
        return "ON"
    if r.startswith("normal"):
        return "OFF"
    if r in ("on", "open", "motion"):
        return "ON"
    if r in ("off", "closed", "still"):
        return "OFF"
    return r  # pass through (e.g. discrete keyfob events)


class DeviceMap:
    """Loaded devices.yaml, indexed by heyu address and by name."""

    def __init__(self, path: Path):
        with open(path) as f:
            data = yaml.safe_load(f)
        self.devices = []  # flat list of dicts
        self.by_addr = {}  # addr (upper) -> list of devices (powerline addr may collide)
        self.by_name = {}
        # the yaml groups; iterate all
        for group in [
            "lights", "switches", "rf_door_sensors", "rf_motion_sensors",
            "powerline_motion_sensors", "powerline_dark_sensors",
            "rf_keyfobs", "trigger_inputs", "modes",
        ]:
            for d in data.get(group, []) or []:
                if d.get("removed"):
                    continue
                d["_group"] = group
                self.devices.append(d)
                self.by_name[d["name"]] = d
                if d.get("kind") in ("powerline", "rf") and d.get("addr"):
                    key = d["addr"].upper()
                    self.by_addr.setdefault(key, []).append(d)

    def controllable(self):
        return [d for d in self.devices if d.get("controllable")]

    def find_by_addr(self, addr: str):
        return self.by_addr.get(addr.upper(), [])


# ───────────────────────── bridge ─────────────────────────

class HeyuBridge:
    def __init__(self, devices_path, mqtt_host, mqtt_port, mqtt_user, mqtt_pw,
                 heyu_bin, topic_prefix="x10", discovery_prefix="homeassistant",
                 cm11_addr=None, w800_addr=None):
        self.dm = DeviceMap(devices_path)
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.mqtt_user = mqtt_user
        self.mqtt_pw = mqtt_pw
        self.heyu = heyu_bin
        self.topic_prefix = topic_prefix
        self.discovery_prefix = discovery_prefix
        self.cm11_addr = cm11_addr
        self.w800_addr = w800_addr
        self.client = mqtt.Client(client_id="heyu-bridge")
        if mqtt_user:
            self.client.username_pw_set(mqtt_user, mqtt_pw)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self._stop = threading.Event()

    # -- MQTT --
    def connect(self):
        self.client.connect(self.mqtt_host, self.mqtt_port, 60)
        self.client.loop_start()

    def _on_connect(self, client, userdata, flags, rc):
        log.info("MQTT connected rc=%s", rc)
        self.publish_discovery()
        # subscribe to command topics for controllable devices
        for d in self.dm.controllable():
            topic = f"{self.topic_prefix}/cmnd/{d['name']}"
            client.subscribe(topic)
            log.debug("subscribed %s", topic)
        # also subscribe to mode command topics (alarm panel / input_select commands)
        for d in self.dm.devices:
            if d.get("component") in ("alarm_control_panel", "input_select"):
                client.subscribe(f"{self.topic_prefix}/cmnd/{d['name']}")
        # birth
        client.publish(f"{self.topic_prefix}/bridge/status", "online", retain=True)

    def _on_message(self, client, userdata, msg):
        try:
            self.handle_command(msg.topic, msg.payload.decode(errors="replace"))
        except Exception:
            log.exception("handle_command failed topic=%s", msg.topic)

    def publish_state(self, name, state, retain=True):
        # Debounce: skip if state hasn't changed (avoid flooding HA with duplicate RF events)
        if not hasattr(self, "_state_cache"):
            self._state_cache = {}
        if self._state_cache.get(name) == state:
            log.debug("debounce: skipping duplicate state %s for %s", state, name)
            return
        self._state_cache[name] = state
        self.client.publish(f"{self.topic_prefix}/state/{name}", state, retain=retain)

    # -- discovery --
    def publish_discovery(self):
        for d in self.dm.devices:
            self._publish_one_discovery(d)

    def _publish_one_discovery(self, d):
        comp = d["component"]
        name = d["name"]
        node = "x10"
        # For device_trigger (keyfobs), publish the sensor entity under "sensor"
        # component so HA creates a sensor entity. Device automations are published
        # separately below.
        disc_comp = "sensor" if comp == "device_trigger" else comp
        disc = f"{self.discovery_prefix}/{disc_comp}/{node}/{name}/config"
        st_topic = f"{self.topic_prefix}/state/{name}"
        cmd_topic = f"{self.topic_prefix}/cmnd/{name}"
        cfg = {
            "name": name.replace("_", " ").title(),
            "uniq_id": f"x10_{name}",
            "state_topic": st_topic,
            "availability_topic": f"{self.topic_prefix}/bridge/status",
            "device": {"identifiers": ["x10_bridge"], "name": "X10 (heyu bridge)"},
        }
        if d.get("controllable"):
            cfg["command_topic"] = cmd_topic
        if comp == "light":
            cfg["payload_on"] = "ON"
            cfg["payload_off"] = "OFF"
            cfg["optimistic"] = True
        elif comp == "switch":
            cfg["payload_on"] = "ON"
            cfg["payload_off"] = "OFF"
        elif comp == "binary_sensor":
            cfg["payload_on"] = d.get("payload_on", "ON")
            cfg["payload_off"] = d.get("payload_off", "OFF")
            # device class
            cls = "motion" if "motion" in name or name in (
                "front_hall", "laundry_room", "upstairs_hall") else None
            if name.endswith("_door"):
                cls = "door"
            if name.endswith("_dark"):
                cls = "light"
            if cls:
                cfg["device_class"] = cls
        elif comp == "sensor":
            cfg["state_topic"] = st_topic
        elif comp == "device_trigger":
            # keyfobs: expose a sensor showing last event + a device trigger per event
            cfg = {
                "name": name.replace("_", " ").title() + " last event",
                "uniq_id": f"x10_{name}_last",
                "state_topic": st_topic,
                "availability_topic": f"{self.topic_prefix}/bridge/status",
                "device": {"identifiers": ["x10_bridge"], "name": "X10 (heyu bridge)"},
            }
        elif comp == "alarm_control_panel":
            cfg["command_topic"] = cmd_topic
            cfg["payload_disarm"] = "disarm"
            cfg["payload_arm_home"] = "arm_home"
            cfg["payload_arm_away"] = "arm_away"
            cfg["state_disarmed"] = "disarmed"
            cfg["state_armed_home"] = "armed_home"
            cfg["state_armed_away"] = "armed_away"
        elif comp == "input_select":
            cfg["command_topic"] = cmd_topic
            cfg["options"] = d.get("states", [])
        self.client.publish(disc, json.dumps(cfg), retain=True)
        # for keyfobs, also publish device triggers per event so automations can use them
        if comp == "device_trigger":
            for ev in d.get("events", []):
                t = {
                    "automation_type": "trigger",
                    "type": ev,
                    "topic": st_topic,
                    "payload": ev,
                    "device": {"identifiers": ["x10_bridge"], "name": "X10 (heyu bridge)"},
                }
                self.client.publish(
                    f"{self.discovery_prefix}/device_automation/{name}/{ev}/config",
                    json.dumps(t), retain=True)

    # -- commands (HA -> heyu) --
    def handle_command(self, topic, payload):
        # topic = x10/cmnd/<name>
        m = re.match(rf"^{re.escape(self.topic_prefix)}/cmnd/(.+)$", topic)
        if not m:
            return
        name = m.group(1)
        d = self.dm.by_name.get(name)
        if not d:
            log.warning("command for unknown device %s", name)
            return
        comp = d.get("component")
        if comp == "alarm_control_panel":
            self._set_mode("mode_security", payload)
            return
        if comp == "input_select":
            self._set_mode(name, payload)
            return
        if not d.get("controllable"):
            log.warning("command for non-controllable device %s", name)
            return
        addr = d["addr"]
        p = payload.strip().upper()
        if p in ("ON", "OFF"):
            self._heyu(p.lower(), addr)
            self.publish_state(name, p)  # optimistic
        elif p in ("DIM", "BRIGHTEN"):
            self._heyu(p.lower(), addr)
        else:
            log.warning("unknown payload %r for %s", payload, name)

    def _set_mode(self, name, payload):
        # mode entities are bridge-local state; just publish
        self.publish_state(name, str(payload).lower())

    def _heyu(self, action, addr):
        cmd = [self.heyu, action, addr]
        log.info("heyu: %s", " ".join(cmd))
        try:
            subprocess.run(cmd, check=False, timeout=10,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        except Exception:
            log.exception("heyu command failed: %s", cmd)

    # -- heyu monitor (events -> MQTT) --
    def run_monitor(self):
        """Run `heyu monitor` and publish state from parsed events.

        heyu monitor output format is verified in Phase 2. The parser handles
        the common shapes (powerline house/unit + function; RF security lines)
        defensively and logs unparsed lines so they can be mapped.
        """
        cmd = [self.heyu, "monitor"]
        log.info("starting %s", " ".join(cmd))
        self._last_monitor_time = time.time()
        # Start watchdog thread to detect heyu engine stalls (CM11A comm issues)
        wd = threading.Thread(target=self._monitor_watchdog, daemon=True)
        wd.start()
        while not self._stop.is_set():
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True,
                                        bufsize=1)
            except FileNotFoundError:
                log.error("heyu binary not found at %s — retrying in 10s", self.heyu)
                time.sleep(10)
                continue
            for line in proc.stdout:
                if self._stop.is_set():
                    break
                line = line.strip()
                if not line:
                    continue
                self._last_monitor_time = time.time()
                self._parse_monitor_line(line)
            rc = proc.poll()
            log.warning("heyu monitor exited rc=%s; restarting in 5s", rc)
            if self._stop.is_set():
                break
            time.sleep(5)

    def _monitor_watchdog(self):
        """Watchdog: if heyu monitor is silent for >90s, unstick the CM11A.

        The W800RF32A receives motion sensor events every ~10s, so 90s of
        silence means heyu is likely stuck on CM11A communication.

        Instead of restarting all heyu daemons (which would also restart the
        aux/W800RF32A and lose RF events), we send SIGUSR1 to the heyu_relay
        process.  The patched relay.c has a signal handler that closes and
        reopens just the CM11A serial port — the MisterHouse-style "unstick"
        operation.  The engine and aux daemons keep running uninterrupted.
        """
        while not self._stop.is_set():
            time.sleep(30)
            if self._stop.is_set():
                break
            silence = time.time() - self._last_monitor_time
            if silence > 90:
                log.warning("watchdog: heyu monitor silent for %.0fs; sending SIGUSR1 to heyu_relay", silence)
                try:
                    # Send SIGUSR1 to heyu_relay to close/reopen the CM11A serial port
                    result = subprocess.run(
                        ["pkill", "-USR1", "heyu_relay"],
                        timeout=10, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    if result.returncode == 0:
                        log.info("watchdog: SIGUSR1 sent to heyu_relay (CM11A port reopened)")
                    else:
                        # Fallback: if pkill fails (e.g. process name mismatch),
                        # try finding the PID via the lock file
                        log.warning("watchdog: pkill heyu_relay failed (rc=%s), trying pidof", result.returncode)
                        result2 = subprocess.run(
                            ["sh", "-c", "pidof heyu_relay | xargs -r kill -USR1"],
                            timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        if result2.returncode == 0:
                            log.info("watchdog: SIGUSR1 sent via pidof")
                        else:
                            log.error("watchdog: could not find heyu_relay process to signal")
                except Exception as e:
                    log.error("watchdog: failed to send SIGUSR1 to heyu_relay: %s", e)
                self._last_monitor_time = time.time()  # reset to avoid repeated triggers

    def _parse_monitor_line(self, line: str):
        """Parse one `heyu monitor` line and publish state.

        Phase 2 TODO: confirm exact field layout against real output. The
        patterns below cover typical heyu monitor output:
          powerline:  `A1        on` / `A1  Unit  On`  (house+unit + function)
          RF sec:     lines containing a security code + state (alert/normal)
                      or an RF device alias.
          snda RF:    `snda addr unit 1 : hu D1` / `snda func On : hc D`
                      (W800RF32A security RF format)
        """
        log.debug("monitor: %s", line)
        # Try snda RF format (W800RF32A security RF)
        if "snda" in line.lower():
            # Parse house code and unit from snda addr line: "snda addr unit 1 : hu D1"
            m = re.search(r"snda addr unit\s+(\d+)\s*:\s*hu\s+([A-Pa-p])(\d*)", line)
            if m:
                unit = m.group(1)
                house = m.group(2).upper()
                addr = f"{house}{unit}"
                # Store the last addressed unit for the next snda func line
                self._last_snda_addr = addr
                log.debug("snda addr: stored last addr=%s", addr)
                return
            # Parse function from snda func line: "snda func On : hc D"
            m = re.search(r"snda func\s+(\w+)\s*:\s*hc\s+([A-Pa-p])", line)
            if m:
                func = m.group(1).lower()
                house = m.group(2).upper()
                state = "ON" if func in ("on", "onunit", "bright") else "OFF" if func in ("off", "offunit", "alllightsoff") else None
                if state:
                    # Use the last addressed unit if available
                    last_addr = getattr(self, "_last_snda_addr", None)
                    if last_addr and last_addr.upper().startswith(house):
                        addr = last_addr
                        log.debug("snda func: applying %s to last addr=%s", func, addr)
                        for d in self.dm.find_by_addr(addr):
                            if d.get("component") in ("light", "switch", "binary_sensor"):
                                log.info("snda: publishing state %s for %s (addr=%s)", state, d["name"], addr)
                                self.publish_state(d["name"], state)
                    else:
                        # Fall back to matching any device with this house code
                        for d in self.dm.devices:
                            if d.get("addr", "").upper().startswith(house):
                                if d.get("component") in ("light", "switch", "binary_sensor"):
                                    log.info("snda: publishing state %s for %s (addr=%s)", state, d["name"], d.get("addr"))
                                    self.publish_state(d["name"], state)
                return
        # Try powerline: look for a house/unit token like A1, C10, M1 ...
        m = re.search(r"\b([A-Pa-p]\d{1,2})\b", line)
        if m:
            addr = m.group(1).upper()
            func = self._func_from_line(line)
            if func:
                state = "ON" if func in ("on", "onunit", "bright") else "OFF" if func in ("off", "offunit", "alllightsoff") else None
                if state:
                    for d in self.dm.find_by_addr(addr):
                        if d.get("component") in ("light", "switch", "binary_sensor"):
                            self.publish_state(d["name"], state)
                return
        # Try RF security: match known RF codes anywhere in the line
        upper = line.upper()
        for code, devs in self.dm.by_addr.items():
            for d in devs:
                if d.get("kind") != "rf":
                    continue
                # Match code as token (e.g. "7D" matches "0x7D" in line)
                # Also try with 0x prefix for heyu's "Type Sec ID 0x7D" format
                pat = rf"(?:0x)?{re.escape(code)}\b"
                if re.search(pat, upper):
                    ev = self._rf_event_from_line(line, d)
                    if ev:
                        if d.get("component") == "device_trigger":
                            log.info("rf: publishing event %s for %s", ev, d["name"])
                            self.publish_state(d["name"], ev, retain=False)
                        else:
                            log.info("rf: publishing state %s for %s", normalize_state(ev), d["name"])
                            self.publish_state(d["name"], normalize_state(ev))
                    return
        log.debug("unparsed monitor line: %s", line)

    def _func_from_line(self, line):
        low = line.lower()
        for f in ("on", "off", "dim", "brighten", "bright", "alllightsoff",
                  "allon", "alloff"):
            if f in low:
                return f
        return None

    def _rf_event_from_line(self, line, d):
        low = line.lower()
        if "alert" in low:
            return "alert"
        if "normal" in low:
            return "normal"
        # keyfob: decode data byte using device's data_map
        data_map = d.get("data_map")
        if data_map:
            m = re.search(r"Data\s+(0x[0-9A-Fa-f]+)", line)
            if m:
                data_byte = m.group(1)
                # Try exact match, uppercase hex digits only (keep 0x prefix lowercase)
                ev = data_map.get(data_byte)
                if not ev:
                    # Normalize: lowercase 0x prefix, uppercase hex digits
                    normalized = "0x" + data_byte[2:].upper()
                    ev = data_map.get(normalized)
                if not ev:
                    ev = data_map.get(data_byte.upper())
                if not ev:
                    ev = data_map.get(data_byte.lower())
                if ev:
                    log.debug("keyfob data byte %s -> event %s", data_byte, ev)
                    return ev
        # keyfob discrete events (fallback: match event name in line)
        for ev in d.get("events", []):
            if ev.replace("_", "") in low.replace("_", ""):
                return ev
        return None

    # -- lifecycle --
    def stop(self, *a):
        log.info("stopping")
        self._stop.set()
        try:
            self.client.publish(f"{self.topic_prefix}/bridge/status", "offline", retain=True)
        except Exception:
            pass
        self.client.loop_stop()
        sys.exit(0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--devices", default="/data/devices.yaml")
    ap.add_argument("--heyu", default="heyu")
    ap.add_argument("--mqtt-host", default=os.environ.get("MQTT_HOST", "core-mosquitto"))
    ap.add_argument("--mqtt-port", type=int, default=int(os.environ.get("MQTT_PORT", "1883")))
    ap.add_argument("--mqtt-user", default=os.environ.get("MQTT_USERNAME", ""))
    ap.add_argument("--mqtt-password", default=os.environ.get("MQTT_PASSWORD", ""))
    ap.add_argument("--topic-prefix", default="x10")
    ap.add_argument("--discovery-prefix", default="homeassistant")
    args = ap.parse_args()

    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    bridge = HeyuBridge(Path(args.devices), args.mqtt_host, args.mqtt_port,
                        args.mqtt_user, args.mqtt_password, args.heyu,
                        args.topic_prefix, args.discovery_prefix)
    signal.signal(signal.SIGTERM, bridge.stop)
    signal.signal(signal.SIGINT, bridge.stop)

    bridge.connect()
    # give MQTT a moment to connect + publish discovery before starting monitor
    time.sleep(1)
    bridge.run_monitor()


if __name__ == "__main__":
    main()
