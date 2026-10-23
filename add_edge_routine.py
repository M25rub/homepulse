"""Adds a routine called edge_case_test to a running HomePulse, so you can watch every kind of outcome in one run.

    python add_edge_routine.py              (HomePulse must be running; press "Discover devices" first for the full test)
"""
import json
import sys
import urllib.request

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"

STEPS = [  # (target type, target id, what to change, value)   -> what you should see
    ("device", "front_lock", "lock", "locked"),             # Confirmed (first try)
    ("device", "back_lock", "lock", "locked"),              # Backup route (its internet connection is down)
    ("device", "kitchen_light", "power", "off"),            # Second try (it ignores its first message)
    ("device", "kitchen_light", "power", "on"),             # Confirmed (it only glitches once per run)
    ("device", "garage", "openclose", "closed"),            # Needs attention (completely offline)
    ("room", "Kitchen", "power", "off"),                    # ONE step, TWO devices (light + coffee maker)
    ("device", "living_light", "brightness", 0),            # lowest allowed value
    ("device", "living_light", "brightness", 100),          # highest allowed value
    ("category", "speaker", "playback", "playing"),         # Second try (needs Discover devices)
    ("category", "thermostat", "temperature", 22),          # Backup route (needs Discover devices)
    ("category", "oven", "power", "on"),                    # no oven in the home: "1 step matched no device"
]

body = {"name": "edge_case_test", "actions": [
    {"target": {"type": t, "id": i}, "capability": c, "value": v} for t, i, c, v in STEPS]}
request = urllib.request.Request(URL + "/routines", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
try:
    print("Done:", urllib.request.urlopen(request, timeout=5).read().decode())
    print("Now open the Routines page and run edge_case_test.")
except Exception as error:
    print("Could not add it. Is HomePulse running (python run.py)?  Details:", error)
