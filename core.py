"""HomePulse core: the one brain behind the website, the AI helper and the Alexa+ MCP server.

A device here works the way Amazon describes smart home devices: it has an id, a name,
a category and a list of CAPABILITIES (power, brightness, lock ...). Each capability has a
reported VALUE. A command asks for a value; HomePulse then checks what the device reports.
"""
import copy
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

import adapters
from datetime import datetime
from pathlib import Path

# Where the home is stored. Set HOMEPULSE_DATA to keep it somewhere else (the tests do).
FILE = Path(os.environ.get("HOMEPULSE_DATA") or Path(__file__).resolve().parent / "home.json")
HOME_LOCK = threading.RLock()      # held while a background command writes its results back

# ---------------------------------------------------------------- catalog

# What a device can do. "enum" = pick one word. "range" = a number between min and max.
CAPABILITIES = {
    "power":       {"type": "enum",  "options": ["on", "off"], "default": "on"},
    "brightness":  {"type": "range", "min": 0, "max": 100, "unit": "%", "default": 100},
    "lock":        {"type": "enum",  "options": ["locked", "unlocked"], "default": "unlocked"},
    "openclose":   {"type": "enum",  "options": ["open", "closed"], "default": "open"},
    "temperature": {"type": "range", "min": 10, "max": 35, "unit": "\u00b0C", "default": 24},
    "climate":     {"type": "enum",  "options": ["off", "heat", "cool", "auto"], "default": "off"},
    "volume":      {"type": "range", "min": 0, "max": 100, "unit": "%", "default": 30},
    "playback":    {"type": "enum",  "options": ["playing", "paused", "stopped"], "default": "stopped"},
    "speed":       {"type": "range", "min": 0, "max": 100, "unit": "%", "default": 50},
    "security":    {"type": "enum",  "options": ["armed", "disarmed"], "default": "disarmed"},
    "cleaning":    {"type": "enum",  "options": ["cleaning", "docked"], "default": "docked"},
    # A REAL check: HomePulse tries to reach the device's network address.
    "reachable":   {"type": "enum",  "options": ["online", "offline"], "default": "offline"},
}

# Kinds of device, and the capabilities each one starts with.
CATEGORIES = {
    "light": ["power", "brightness"],
    "plug": ["power"],
    "fan": ["power", "speed"],
    "ac": ["power", "temperature"],
    "heater": ["power"],
    "thermostat": ["temperature", "climate"],
    "tv": ["power", "volume"],
    "speaker": ["power", "playback", "volume"],
    "blinds": ["openclose"],
    "lock": ["lock"],
    "garage": ["openclose"],
    "gate": ["openclose"],
    "camera": ["power"],
    "alarm": ["security"],
    "vacuum": ["cleaning"],
    "washer": ["power"],
    "oven": ["power", "temperature"],
    "coffee_maker": ["power"],
    "kettle": ["power"],
    "purifier": ["power", "speed"],
    "water_heater": ["power", "temperature"],
    "sprinkler": ["power"],
    "other": ["power"],
    "network": ["reachable"],      # a real device or service, checked over the network
}

BEHAVIORS = ["ok", "flaky", "cloud_down", "offline"]   # demo only: how a simulated device misbehaves


def catalog():
    return {"capabilities": CAPABILITIES, "categories": CATEGORIES, "behaviors": BEHAVIORS}


# ---------------------------------------------------------------- storing the home

def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", str(text).strip().lower()).strip("_")


def default_state(capabilities):
    return {c: CAPABILITIES[c]["default"] for c in capabilities if c in CAPABILITIES}


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("home file is not a JSON object")
    return data


def load_home():
    """Read the home. If the file is damaged, fall back to the last good backup instead of
    silently starting empty, and keep the damaged file for inspection."""
    home = {"devices": {}, "routines": {}, "history": []}
    backup = FILE.with_name(FILE.name + ".bak")
    if FILE.exists():
        try:
            home.update(_read_json(FILE))
        except (OSError, ValueError):
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            try:
                FILE.replace(FILE.with_name(f"{FILE.stem}.damaged-{stamp}.json"))
            except OSError:
                pass
            if backup.exists():
                try:
                    home.update(_read_json(backup))
                except (OSError, ValueError):
                    pass
    if migrate(home):
        save_home(home)
    return home


def save_home(home):
    """Write the home safely: a temporary file first, then one atomic swap, keeping the
    previous version as home.json.bak. A crash mid-save can no longer wipe the home."""
    with HOME_LOCK:
        FILE.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=FILE.parent, prefix=".home-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(home, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            if FILE.exists():
                try:
                    _read_json(FILE)                       # only back up a file that is itself valid
                    (FILE.with_name(FILE.name + ".bak")).write_bytes(FILE.read_bytes())
                except (OSError, ValueError):
                    pass
            os.replace(tmp, FILE)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)


# Old home.json files described a device by "kind" plus one state word. Convert them.
STATE_ALIASES = {"dimmed": ("brightness", 30), "heating": ("climate", "heat"),
                 "cooling": ("climate", "cool"), "running": ("power", "on")}


def _map_old_state(category, word):
    """Turn an old one-word state into (capability, value), or None."""
    if word in STATE_ALIASES:
        cap, value = STATE_ALIASES[word]
        if cap in CATEGORIES.get(category, []):
            return cap, value
    for cap in CATEGORIES.get(category, []):
        spec = CAPABILITIES[cap]
        if spec["type"] == "enum" and word in spec["options"]:
            return cap, word
    return None


def migrate(home):
    changed = False
    for key in ("devices", "routines"):
        if key not in home or not isinstance(home[key], dict):
            home[key] = {}
            changed = True
    if not isinstance(home.get("history"), list):
        home["history"] = []
        changed = True
    if not isinstance(home.get("events"), list):
        home["events"] = []
        changed = True

    for dev_id, d in list(home["devices"].items()):
        if "capabilities" in d:
            continue
        category = d.get("kind") if d.get("kind") in CATEGORIES else "other"
        caps = list(CATEGORIES[category])
        state = default_state(caps)
        old = _map_old_state(category, str(d.get("state", "")))
        if old:
            state[old[0]] = old[1]
        home["devices"][dev_id] = {
            "id": dev_id, "name": d.get("name", dev_id), "category": category, "room": d.get("room", ""),
            "capabilities": caps, "state": state, "behavior": d.get("behavior", "ok"), "source": "manual",
        }
        changed = True

    for name, r in list(home["routines"].items()):
        if "actions" in r:
            continue
        actions = []
        for rule in r.get("rules", []):
            if rule.get("device_id") and rule["device_id"] in home["devices"]:
                target = {"type": "device", "id": rule["device_id"]}
                category = home["devices"][rule["device_id"]]["category"]
            elif rule.get("kind"):
                category = rule["kind"] if rule["kind"] in CATEGORIES else "other"
                target = {"type": "category", "id": category}
            else:
                continue
            mapped = _map_old_state(category, str(rule.get("set_to", "")))
            if mapped:
                actions.append({"target": target, "capability": mapped[0], "value": mapped[1]})
        home["routines"][name] = {"name": r.get("name", name), "actions": actions}
        changed = True
    return changed


# ---------------------------------------------------------------- values

def clean_value(capability, value):
    """Check a requested value is allowed for the capability. Returns the cleaned value."""
    spec = CAPABILITIES.get(capability)
    if spec is None:
        raise ValueError(f"Unknown capability: {capability}")
    if spec["type"] == "range":
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{capability} needs a number")
        if not spec["min"] <= number <= spec["max"]:
            raise ValueError(f"{capability} must be between {spec['min']} and {spec['max']}")
        return int(round(number))
    value = str(value).strip().lower()
    if value not in spec["options"]:
        raise ValueError(f"{capability} must be one of: {', '.join(spec['options'])}")
    return value


def same(capability, reported, wanted):
    if CAPABILITIES[capability]["type"] == "range":
        try:
            return abs(float(reported) - float(wanted)) < 0.5
        except (TypeError, ValueError):
            return False
    return str(reported) == str(wanted)


# ---------------------------------------------------------------- creating devices

_PING_HOST = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-]{0,252}")      # a plain host name or IPv4 address only


def valid_address(address):
    """A live device is reached at an http(s) URL, at host:port, or by ping (ping://192.168.1.1).
    Raises ValueError if it is none of these."""
    address = str(address or "").strip()
    if address.lower().startswith("ping://"):
        host = address[7:].strip()
        if not _PING_HOST.fullmatch(host):
            raise ValueError("Use ping:// followed by a host name or an address, like ping://192.168.1.1")
        return "ping://" + host
    if address.lower().startswith(("http://", "https://")):
        rest = address.split("://", 1)[1]
        if not rest or rest.startswith("/"):
            raise ValueError("That web address has no host name")
        return address
    host, sep, port = address.rpartition(":")
    if not (sep and host and port.isdigit() and 0 < int(port) < 65536) or "/" in host or " " in address:
        raise ValueError("Use a web address like http://192.168.1.20 or a host and port like 192.168.1.20:80")
    return address


def _ping(host, timeout=1.5):
    """Send one real ping with the computer's own ping tool. Only a genuine reply (it shows a TTL) counts,
    because Windows prints 'host unreachable' with a success code."""
    if not _PING_HOST.fullmatch(host):
        return False
    wait = int(timeout * 1000) if sys.platform.startswith(("win", "darwin")) else max(1, round(timeout))
    flag_count, flag_wait = ("-n", "-w") if sys.platform.startswith("win") else ("-c", "-W")
    try:
        out = subprocess.run(["ping", flag_count, "1", flag_wait, str(wait), host],
                             capture_output=True, text=True, timeout=timeout + 3)
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0 and "ttl=" in out.stdout.lower()


def probe(address, timeout=1.5):
    """Really try to reach an address. True if something answers properly.
    http(s): any answer below 500 counts (even 404 means the server is alive). host:port: a TCP connection.
    ping://host: one real ping."""
    try:
        if address.lower().startswith("ping://"):
            return _ping(address[7:], timeout)
        if address.lower().startswith(("http://", "https://")):
            request = urllib.request.Request(address, headers={"User-Agent": "HomePulse/1.0"})
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    return response.status < 500
            except urllib.error.HTTPError as error:
                return error.code < 500
        host, _, port = address.rpartition(":")
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except Exception:
        return False


def new_device(home, name, category="other", room="", behavior="ok", source="manual", device_id=None, capabilities=None,
               address="", fallback_address="", adapter=""):
    if adapter:
        if adapter not in adapters.KINDS:
            raise ValueError("Unknown plug type. Choose one of: " + ", ".join(adapters.KINDS))
        if not address:
            raise ValueError("A smart plug needs the address it can be reached at")
        category, capabilities = "plug", ["power", "reachable"]
    category = category if category in CATEGORIES else "other"
    caps = [c for c in (capabilities or CATEGORIES[category]) if c in CAPABILITIES]
    base = device_id or slug(name) or "device"
    dev_id, n = base, 2
    while dev_id in home["devices"]:
        dev_id, n = f"{base}_{n}", n + 1
    device = {
        "id": dev_id, "name": str(name).strip() or dev_id, "category": category, "room": str(room).strip(),
        "capabilities": caps, "state": default_state(caps),
        "behavior": behavior if behavior in BEHAVIORS else "ok", "source": source,
    }
    if address:                                   # a live device: HomePulse really probes this address
        device["address"] = valid_address(address)
        device["behavior"] = "live"
        device["source"] = "live"
        if adapter:
            device["adapter"] = adapter
        if fallback_address:
            device["fallback_address"] = valid_address(fallback_address)
        if "reachable" not in device["capabilities"]:
            device["capabilities"].append("reachable")
            device["state"]["reachable"] = CAPABILITIES["reachable"]["default"]
    home["devices"][dev_id] = device
    return device


SAMPLE_DEVICES = [
    ("front_lock", "Front door lock", "lock", "Entrance", "ok"),
    ("back_lock", "Back door lock", "lock", "Entrance", "cloud_down"),
    ("living_light", "Living room light", "light", "Living room", "ok"),
    ("kitchen_light", "Kitchen light", "light", "Kitchen", "flaky"),
    ("garage", "Garage door", "garage", "Garage", "offline"),
    ("coffee", "Coffee maker", "coffee_maker", "Kitchen", "ok"),
]

# Pretend "devices nearby", found when you press Discover devices.
DISCOVERY_POOL = [
    ("bedroom_lamp", "Bedroom lamp", "light", "Bedroom", "ok"),
    ("bedroom_fan", "Bedroom fan", "fan", "Bedroom", "ok"),
    ("living_tv", "Living room TV", "tv", "Living room", "ok"),
    ("living_speaker", "Living room speaker", "speaker", "Living room", "flaky"),
    ("hall_thermostat", "Hallway thermostat", "thermostat", "Hallway", "cloud_down"),
    ("front_camera", "Front door camera", "camera", "Entrance", "ok"),
    ("vacuum", "Robot vacuum", "vacuum", "Hallway", "ok"),
    ("sprinkler", "Garden sprinkler", "sprinkler", "Garden", "offline"),
    ("blinds", "Window blinds", "blinds", "Living room", "ok"),
    ("alarm", "Home alarm", "alarm", "Entrance", "ok"),
]


def load_sample(home):
    """Add the sample devices (skipping ones already there) and two sample routines."""
    added = 0
    for dev_id, name, category, room, behavior in SAMPLE_DEVICES:
        if dev_id not in home["devices"]:
            new_device(home, name, category, room, behavior, source="sample", device_id=dev_id)
            added += 1
    home["routines"].setdefault("secure_house", {"name": "secure_house", "actions": [
        {"target": {"type": "category", "id": "lock"}, "capability": "lock", "value": "locked"},
        {"target": {"type": "category", "id": "garage"}, "capability": "openclose", "value": "closed"},
        {"target": {"type": "category", "id": "light"}, "capability": "power", "value": "off"},
        {"target": {"type": "category", "id": "coffee_maker"}, "capability": "power", "value": "off"},
    ]})
    home["routines"].setdefault("movie_night", {"name": "movie_night", "actions": [
        {"target": {"type": "room", "id": "Living room"}, "capability": "brightness", "value": 20},
        {"target": {"type": "category", "id": "speaker"}, "capability": "playback", "value": "playing"},
        {"target": {"type": "category", "id": "tv"}, "capability": "power", "value": "on"},
    ]})
    return added


def discover(home):
    """Pretend to scan the network. Returns the devices that were newly found."""
    found = []
    for dev_id, name, category, room, behavior in DISCOVERY_POOL:
        if dev_id not in home["devices"]:
            found.append(new_device(home, name, category, room, behavior, source="discovered", device_id=dev_id))
    return found


# ---------------------------------------------------------------- importing from Alexa

# Amazon's smart home interfaces that we understand, and what they become here.
INTERFACE_MAP = {
    "Alexa.PowerController": ["power"],
    "Alexa.BrightnessController": ["brightness"],
    "Alexa.LockController": ["lock"],
    "Alexa.ThermostatController": ["temperature", "climate"],
    "Alexa.Speaker": ["volume"],
    "Alexa.PlaybackController": ["playback"],
    "Alexa.SecurityPanelController": ["security"],
}
IGNORED_INTERFACES = {"Alexa", "Alexa.EndpointHealth", "Alexa.Discovery"}
DISPLAY_CATEGORY_MAP = {
    "LIGHT": "light", "SMARTLOCK": "lock", "SMARTPLUG": "plug", "SWITCH": "plug", "THERMOSTAT": "thermostat",
    "FAN": "fan", "TV": "tv", "SPEAKER": "speaker", "MUSIC_SYSTEM": "speaker", "CAMERA": "camera",
    "GARAGE_DOOR": "garage", "INTERIOR_BLIND": "blinds", "EXTERIOR_BLIND": "blinds",
    "SECURITY_PANEL": "alarm", "SECURITY_SYSTEM": "alarm", "VACUUM_CLEANER": "vacuum", "WASHER": "washer",
    "OVEN": "oven", "COFFEE_MAKER": "coffee_maker", "AIR_PURIFIER": "purifier", "WATER_HEATER": "water_heater",
}


def find_endpoints(payload):
    """Accept the full discovery response, just the payload, or a plain list of endpoints."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        if isinstance(payload.get("endpoints"), list):
            return payload["endpoints"]
        inner = payload.get("event", {}).get("payload", {}) if isinstance(payload.get("event"), dict) else {}
        if isinstance(inner.get("endpoints"), list):
            return inner["endpoints"]
        if "endpointId" in payload:
            return [payload]
    raise ValueError("No endpoints found in that JSON")


def import_alexa(home, payload):
    """Add devices described in Alexa's discovery format. Returns (added, skipped, notes)."""
    endpoints = find_endpoints(payload)
    added, skipped, notes = [], 0, set()
    for ep in endpoints:
        if not isinstance(ep, dict):
            skipped += 1
            continue
        caps = []
        for c in ep.get("capabilities", []) or []:
            iface = c.get("interface") if isinstance(c, dict) else None
            if iface in INTERFACE_MAP:
                for cap in INTERFACE_MAP[iface]:
                    if cap not in caps:
                        caps.append(cap)
            elif iface and iface not in IGNORED_INTERFACES:
                notes.add(iface)
        if not caps:
            skipped += 1
            continue
        category = "other"
        for dc in ep.get("displayCategories", []) or []:
            if dc in DISPLAY_CATEGORY_MAP:
                category = DISPLAY_CATEGORY_MAP[dc]
                break
        name = ep.get("friendlyName") or ep.get("endpointId") or "Device"
        device = new_device(home, name, category, "", "ok", source="alexa-import", capabilities=caps,
                            device_id=slug(ep.get("endpointId") or name) or None)
        added.append(device)
    return added, skipped, sorted(notes)


# ---------------------------------------------------------------- running commands

def send_command(device, capability, value, route="cloud"):
    """Pretend to talk to a real device. It returns nothing, so the only way to know
    whether it worked is to ask the device for its state afterwards."""
    behavior = device.get("behavior", "ok")
    if behavior == "offline":
        return
    if behavior == "cloud_down" and route == "cloud":
        return
    if behavior == "flaky" and not device.get("glitched"):
        device["glitched"] = True
        return
    device["state"][capability] = value


ATTEMPT_PLAN = [("cloud", "first try"), ("cloud", "retry"), ("local", "backup route")]
OUTCOME_BY_ATTEMPTS = {1: "confirmed", 2: "recovered by retry", 3: "recovered by local fallback"}
FAILED_OUTCOME = "FAILED - needs attention"


def verify_live(device, capability, value):
    """The REAL version: probe the device's network address, retry, then try its backup address."""
    plan = [(device["address"], "cloud", "first try"), (device["address"], "cloud", "retry")]
    if device.get("fallback_address"):
        plan.append((device["fallback_address"], "local", "backup route"))
    attempts = []
    for number, (address, route, label) in enumerate(plan, 1):
        started = time.perf_counter()
        answered = probe(address)
        device["state"]["reachable"] = "online" if answered else "offline"
        reported = device["state"]["reachable"]
        matched = same(capability, reported, value)
        attempts.append({"attempt": number, "label": label, "route": route, "address": address, "reported": reported,
                         "matched": matched, "ms": round((time.perf_counter() - started) * 1000)})
        if matched:
            return {"outcome": OUTCOME_BY_ATTEMPTS[number], "verified": True, "attempts": attempts}
    return {"outcome": FAILED_OUTCOME, "verified": False, "attempts": attempts}


def verify_adapter(device, capability, value):
    """The REAL control loop for a smart plug: send the command over the network, then ask the plug what it
    reports. Retry, then try the backup address. Nothing is assumed: only the plug's own answer counts."""
    kind = device["adapter"]
    plan = [(device["address"], "cloud", "first try"), (device["address"], "cloud", "retry")]
    if device.get("fallback_address"):
        plan.append((device["fallback_address"], "local", "backup route"))
    attempts = []
    for number, (address, route, label) in enumerate(plan, 1):
        started = time.perf_counter()
        adapters.set_power(kind, address, value)
        reported = adapters.read_power(kind, address)
        device["state"]["reachable"] = "online" if reported is not None else "offline"
        if reported is not None:
            device["state"][capability] = reported
        matched = reported is not None and same(capability, reported, value)
        attempts.append({"attempt": number, "label": label, "route": route, "address": address,
                         "reported": reported if reported is not None else "no answer",
                         "matched": matched, "ms": round((time.perf_counter() - started) * 1000)})
        if matched:
            return {"outcome": OUTCOME_BY_ATTEMPTS[number], "verified": True, "attempts": attempts}
    return {"outcome": FAILED_OUTCOME, "verified": False, "attempts": attempts}


def verify_detailed(device, capability, value, pause=None):
    """Send, check, retry, then try the backup route. Returns a record of every attempt.
    `pause` (optional) is called after each send, so a server can simulate network delay."""
    if device.get("behavior") == "live" and device.get("adapter") and capability == "power":
        return verify_adapter(device, capability, value)
    if device.get("behavior") == "live" and capability == "reachable":
        return verify_live(device, capability, value)
    attempts = []
    for number, (route, label) in enumerate(ATTEMPT_PLAN, 1):
        started = time.perf_counter()
        send_command(device, capability, value, route)
        if pause:
            pause()
        reported = device["state"].get(capability)
        matched = same(capability, reported, value)
        attempts.append({"attempt": number, "label": label, "route": route, "reported": reported,
                         "matched": matched, "ms": round((time.perf_counter() - started) * 1000)})
        if matched:
            return {"outcome": OUTCOME_BY_ATTEMPTS[number], "verified": True, "attempts": attempts}
    return {"outcome": FAILED_OUTCOME, "verified": False, "attempts": attempts}


def apply_and_verify(device, capability, value):
    """Same as verify_detailed, but returns only the outcome text."""
    return verify_detailed(device, capability, value)["outcome"]


def explain_step(name, capability, wanted, outcome, reported=None, attempts=3):
    """One plain-language sentence about what happened to one device."""
    if capability == "reachable":                  # a real network check
        if outcome == "confirmed":
            return f"{name}: really checked, and it answered on the first try."
        if outcome == "recovered by retry":
            return f"{name}: did not answer the first check, but answered the second."
        if outcome == "recovered by local fallback":
            return f"{name}: its main address did not answer, but its backup address did."
        return (f"{name}: did not answer after {attempts} real checks (last result: {reported}). "
                "It looks unreachable - check its power and network.")
    if outcome == "confirmed":
        return f"{name}: set {capability} to {wanted} and confirmed it on the first try."
    if outcome == "recovered by retry":
        return f"{name}: ignored the first message, so HomePulse asked again and then confirmed {capability} is {wanted}."
    if outcome == "recovered by local fallback":
        return (f"{name}: the usual internet route did not get through, so HomePulse used the backup "
                f"(local) route and confirmed {capability} is {wanted}.")
    return (f"{name}: never confirmed {capability} = {wanted} after {attempts} attempts "
            f"(last reported: {reported}). It looks unreachable - check its power and Wi-Fi.")


def resolve_targets(home, target):
    kind, ident = target.get("type"), str(target.get("id", ""))
    devices = list(home["devices"].values())
    if kind == "device":
        return [d for d in devices if d["id"] == ident]
    if kind == "room":
        return [d for d in devices if d.get("room", "").strip().lower() == ident.strip().lower()]
    if kind == "category":
        return [d for d in devices if d.get("category") == ident]
    if kind == "all":
        return devices
    return []


def run_actions(home, actions, pause=None):
    """Run a list of actions on a copy of the devices (the real home is not changed).
    Returns (results, unmatched) where unmatched counts steps that touched no device."""
    devices = copy.deepcopy(home["devices"])
    for d in devices.values():
        d["glitched"] = False
    work = {"devices": devices}
    results, unmatched = [], 0
    for action in actions:
        cap = action["capability"]
        value = clean_value(cap, action["value"])
        hit = [d for d in resolve_targets(work, action["target"]) if cap in d["capabilities"]]
        if not hit:
            unmatched += 1
            continue
        for device in hit:
            started = time.perf_counter()
            detail = verify_detailed(device, cap, value, pause)
            reported = device["state"].get(cap)
            if device.get("behavior") == "live" and not detail["verified"] and detail["attempts"][-1]["reported"] == "no answer":
                reported = "no answer"                      # the device was silent: do not show an old state as if it were fresh
            results.append({
                "device": device["name"], "device_id": device["id"], "room": device.get("room", ""),
                "category": device.get("category", ""), "capability": cap,
                "wanted": value, "reported": reported,
                "verified": detail["verified"], "outcome": detail["outcome"],
                "attempts": detail["attempts"], "ms": round((time.perf_counter() - started) * 1000),
                "explanation": explain_step(device["name"], cap, value, detail["outcome"], reported, len(detail["attempts"])),
            })
    return results, unmatched


def summarize(label, results, unmatched):
    failed = [r["device"] for r in results if not r["verified"]]
    text = f"{label}: confirmed {len(results) - len(failed)} of {len(results)} checks."
    if failed:
        text += " Could not confirm: " + ", ".join(sorted(set(failed))) + ". Please check them."
    if unmatched:
        text += f" {unmatched} step(s) matched no device."
    return text


def record_history(home, label, results):
    ok = sum(1 for r in results if r["verified"])
    home.setdefault("history", []).append({
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"), "routine": label,
        "confirmed": ok, "total": len(results), "results": results,
    })
    home["history"] = home["history"][-50:]


def clean_actions(actions):
    """Validate actions that came from outside (the website, the AI, Alexa+)."""
    out = []
    for a in actions:
        target = a.get("target") or {}
        if target.get("type") not in ("device", "room", "category", "all"):
            raise ValueError("Each step needs a target: device, room, category or all")
        cap = a.get("capability")
        out.append({"target": {"type": target["type"], "id": str(target.get("id", ""))},
                    "capability": cap, "value": clean_value(cap, a.get("value"))})
    return out


# ---------------------------------------------------------------- the pulse (home health)

def device_stats(home):
    """Per-device track record, worked out from the saved history of checks."""
    stats = {}
    for entry in home.get("history", []):
        for r in entry.get("results", []):
            st = stats.setdefault(r.get("device_id"), {"checks": 0, "first_try": 0, "retry": 0,
                                                       "backup": 0, "failed": 0, "recent": [], "last_failure": None})
            st["checks"] += 1
            outcome = r.get("outcome", "")
            if outcome == "confirmed":
                st["first_try"] += 1
            elif outcome == "recovered by retry":
                st["retry"] += 1
            elif outcome == "recovered by local fallback":
                st["backup"] += 1
            else:
                st["failed"] += 1
                st["last_failure"] = entry.get("time")
            st["recent"].append(outcome)
    for st in stats.values():
        st["recent"] = st["recent"][-5:]
    return stats


def pulse(home):
    """A plain health report for the whole home: a score, what needs attention, and why."""
    stats = device_stats(home)
    devices, rows = home.get("devices", {}), []
    for dev_id, d in devices.items():
        st = stats.get(dev_id)
        if not st:
            rows.append({"device_id": dev_id, "name": d["name"], "room": d.get("room", ""), "health": "untested",
                         "checks": 0, "reason": "No command has been checked on this device yet."})
            continue
        recent = st["recent"]
        if recent[-1] not in ("confirmed", "recovered by retry", "recovered by local fallback"):
            health, reason = "failing", (f"Its last command was never confirmed ({st['failed']} failure(s) "
                                         f"in {st['checks']} checks). It looks unreachable.")
        elif sum(1 for o in recent if o != "confirmed") >= 2:
            health = "fragile"
            reason = (f"It needed a retry or the backup route in {sum(1 for o in recent if o != 'confirmed')} of its "
                      f"last {len(recent)} commands. It works, but not reliably.")
        else:
            health, reason = "healthy", "Recent commands were confirmed without trouble."
        rows.append({"device_id": dev_id, "name": d["name"], "room": d.get("room", ""), "health": health,
                     "checks": st["checks"], "first_try": st["first_try"], "retry": st["retry"],
                     "backup": st["backup"], "failed": st["failed"], "last_failure": st["last_failure"],
                     "reason": reason})

    tested = [r for r in rows if r["health"] != "untested"]
    weight = {"healthy": 1.0, "fragile": 0.5, "failing": 0.0}
    score = round(100 * sum(weight[r["health"]] for r in tested) / len(tested)) if tested else None

    attention = []
    for r in rows:
        if r["health"] == "failing":
            attention.append({"level": "urgent", "device_id": r["device_id"], "name": r["name"], "room": r["room"],
                              "failed": r["failed"], "checks": r["checks"], "reason": r["reason"], "suggestion": "Check that it has power and a Wi-Fi connection, then run the command again."})
        elif r["health"] == "fragile":
            recent = stats[r["device_id"]]["recent"]
            attention.append({"level": "watch", "device_id": r["device_id"], "name": r["name"], "room": r["room"],
                              "issues": sum(1 for o in recent if o != "confirmed"), "recent": len(recent),
                              "reason": r["reason"], "suggestion": "Move it closer to the router, or check its battery or power."})
    by_room = {}
    for r in rows:
        if r["health"] in ("failing", "fragile") and r["room"]:
            by_room.setdefault(r["room"], []).append(r["name"])
    patterns = [{"room": room, "devices": names,
                 "note": f"{len(names)} devices in {room} are struggling at the same time. The cause may be that room's Wi-Fi coverage or a shared hub, rather than each device."}
                for room, names in by_room.items() if len(names) >= 2]

    delivery = {"first_try": 0, "retry": 0, "backup": 0, "failed": 0}
    for st in stats.values():
        for k in delivery:
            delivery[k] += st[k]
    total = sum(delivery.values())
    if not total:
        headline = "No commands have been checked yet. Run a routine or send a command and the pulse will fill in."
    elif not attention:
        headline = f"Everything is healthy. {total} commands checked."
    else:
        urgent = sum(1 for a in attention if a["level"] == "urgent")
        headline = (f"{urgent} device(s) need attention now and {len(attention) - urgent} to watch."
                    if urgent else f"{len(attention)} device(s) to watch.")
    return {"score": score, "headline": headline, "devices": rows, "attention": attention,
            "patterns": patterns, "delivery": delivery, "total_checks": total,
            "saved_by_recovery": delivery["retry"] + delivery["backup"]}
