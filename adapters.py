"""Adapters: how HomePulse really talks to smart plugs over their local HTTP APIs.

Written from the manufacturers' public documentation:
  Shelly Gen1   GET  /relay/0                   -> {"ison": true}        POST /relay/0  (form field turn=on|off)
  Shelly Gen2+  GET  /rpc/Switch.GetStatus?id=0 -> {"output": true}      GET /rpc/Switch.Set?id=0&on=true|false
  Tasmota       GET  /cm?cmnd=Power             -> {"POWER": "ON"}       GET /cm?cmnd=Power%20On|Off

Tested against the included demo plug (demo_plug.py), which speaks these same protocols.
NOT tested against real Shelly or Tasmota hardware.
"""
import json
import urllib.error
import urllib.request

KINDS = {
    "shelly_gen1": "Shelly plug (Gen1)",
    "shelly_gen2": "Shelly plug (Gen2 and newer)",
    "tasmota": "Tasmota plug",
}
TIMEOUT = 1.5


def _request(url, data=None, timeout=TIMEOUT):
    """One HTTP request. Returns the parsed JSON, or None if the device did not answer properly."""
    try:
        request = urllib.request.Request(url, data=data, headers={"User-Agent": "HomePulse/1.0"})
        if data is not None:
            request.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status >= 400:
                return None
            body = response.read(65536)
        parsed = json.loads(body.decode("utf-8", "replace") or "{}")
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def read_power(kind, base):
    """What the device itself says right now: 'on', 'off', or None if it did not answer."""
    base = base.rstrip("/")
    if kind == "shelly_gen1":
        reply = _request(f"{base}/relay/0")
        state = None if reply is None else reply.get("ison")
    elif kind == "shelly_gen2":
        reply = _request(f"{base}/rpc/Switch.GetStatus?id=0")
        state = None if reply is None else reply.get("output")
    elif kind == "tasmota":
        reply = _request(f"{base}/cm?cmnd=Power")
        key = next((k for k in (reply or {}) if str(k).upper().startswith("POWER")), None)
        state = None if key is None else str(reply[key]).upper() == "ON"
    else:
        return None
    if state is None:
        return None
    return "on" if state else "off"


def set_power(kind, base, value):
    """Ask the device to switch. Returns True if the device accepted the request (not proof it obeyed)."""
    base = base.rstrip("/")
    on = value == "on"
    if kind == "shelly_gen1":
        reply = _request(f"{base}/relay/0", data=f"turn={'on' if on else 'off'}".encode())
    elif kind == "shelly_gen2":
        reply = _request(f"{base}/rpc/Switch.Set?id=0&on={'true' if on else 'false'}")
    elif kind == "tasmota":
        reply = _request(f"{base}/cm?cmnd=Power%20{'On' if on else 'Off'}")
    else:
        return False
    return reply is not None
