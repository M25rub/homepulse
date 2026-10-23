"""The live watch: HomePulse keeps checking your real devices in the background, even when nobody is
pressing buttons, and writes down when something went offline and when it came back.

Plain rules, so it can be trusted:
  * Only LIVE devices are watched (the ones with a real network address). Simulated devices are not.
  * One missed check is not an outage. A device is called "down" only after CONFIRM_AFTER misses in a
    row, so a single dropped packet never raises a false alarm.
  * "Went down" is dated from the FIRST missed check, and "back up" says how long it was away.
  * Checks run side by side with a short timeout, so one dead device cannot slow down the others.
  * It never crashes the app: a check that blows up counts as "no answer", and the loop survives errors.
"""
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import adapters
import core

INTERVAL = float(os.environ.get("HOMEPULSE_WATCH_SECONDS", "60"))      # 0 switches the watch off
CONFIRM_AFTER = max(1, int(os.environ.get("HOMEPULSE_WATCH_CONFIRMS", "2")))
MAX_EVENTS = 300
MAX_PARALLEL = 8

_STATE = {}                 # device_id -> what the watch currently believes (kept in memory)
_LOCK = threading.Lock()
_THREAD = {"stop": None, "thread": None}


def check_one(device):
    """One real check of one live device. True if it answered. Never raises."""
    try:
        addresses = [device["address"]] + ([device["fallback_address"]] if device.get("fallback_address") else [])
        for address in addresses:
            if device.get("adapter"):
                if adapters.read_power(device["adapter"], address) is not None:
                    return True
            elif core.probe(address):
                return True
        return False
    except Exception:
        return False


def _seconds_between(start, end):
    try:
        return max(0, round((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()))
    except (TypeError, ValueError):
        return 0


def tick(now=None):
    """One round of checks. Returns the new events it recorded (went_down / back_up)."""
    with core.HOME_LOCK:
        home = core.load_home()
    live = {i: d for i, d in home["devices"].items() if d.get("behavior") == "live" and d.get("address")}
    with _LOCK:
        for gone in [i for i in _STATE if i not in live]:      # a removed device is simply forgotten
            del _STATE[gone]
    if not live:
        return []
    with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL, len(live))) as pool:
        answers = dict(zip(live, pool.map(check_one, live.values())))

    stamp = (now or datetime.now()).isoformat(timespec="seconds")
    new_events, changed = [], False
    with core.HOME_LOCK:
        home = core.load_home()                                 # fresh copy: keep edits made while we checked
        for dev_id, answered in answers.items():
            device = home["devices"].get(dev_id)
            if device is None or device.get("behavior") != "live":
                continue                                        # removed or changed while we were checking
            with _LOCK:
                st = _STATE.setdefault(dev_id, {"status": "unknown", "fails": 0, "since": stamp,
                                                "first_miss": None, "last_checked": stamp})
                st["last_checked"] = stamp
                if answered:
                    if st["status"] == "down":
                        new_events.append({"device_id": dev_id, "name": device["name"], "type": "back_up", "at": stamp,
                                           "down_for_seconds": _seconds_between(st["since"], stamp)})
                    if st["status"] != "up":
                        st["status"], st["since"] = "up", stamp
                    st["fails"], st["first_miss"] = 0, None
                    if device["state"].get("reachable") != "online":
                        device["state"]["reachable"] = "online"
                        changed = True
                else:
                    st["fails"] += 1
                    st["first_miss"] = st["first_miss"] or stamp
                    if st["fails"] >= CONFIRM_AFTER and st["status"] != "down":
                        st["status"], st["since"] = "down", st["first_miss"]
                        new_events.append({"device_id": dev_id, "name": device["name"], "type": "went_down",
                                           "at": st["first_miss"]})
                        if device["state"].get("reachable") != "offline":
                            device["state"]["reachable"] = "offline"
                            changed = True
        if new_events:
            home["events"] = (home.get("events", []) + new_events)[-MAX_EVENTS:]
            changed = True
        if changed:
            core.save_home(home)
    return new_events


def _loop(stop):
    stop.wait(3)                                                # let the app finish starting first
    while not stop.is_set():
        try:
            tick()
        except Exception:                                       # the watch must never take the app down
            pass
        stop.wait(INTERVAL)


def start():
    """Start watching in the background. Does nothing if switched off (HOMEPULSE_WATCH_SECONDS=0)."""
    if INTERVAL <= 0:
        return False
    stop()
    flag = threading.Event()
    thread = threading.Thread(target=_loop, args=(flag,), daemon=True, name="homepulse-watch")
    _THREAD.update(stop=flag, thread=thread)
    thread.start()
    return True


def stop():
    if _THREAD["stop"] is not None:
        _THREAD["stop"].set()
    _THREAD.update(stop=None, thread=None)


def reset():
    """Forget what the watch believes. Used by the tests."""
    with _LOCK:
        _STATE.clear()


def running():
    thread = _THREAD["thread"]
    return bool(thread and thread.is_alive())


def status(limit=20):
    """What the website shows: each watched device, and the latest events (newest first)."""
    home = core.load_home()
    rows = []
    with _LOCK:
        for dev_id, d in home["devices"].items():
            if d.get("behavior") != "live" or not d.get("address"):
                continue
            st = _STATE.get(dev_id)
            rows.append({"device_id": dev_id, "name": d["name"], "address": d["address"],
                         "status": st["status"] if st else "unknown",
                         "since": st["since"] if st and st["status"] != "unknown" else None,
                         "last_checked": st["last_checked"] if st else None,
                         "missed_in_a_row": st["fails"] if st else 0})
    return {"running": running(), "interval_seconds": INTERVAL, "confirm_after": CONFIRM_AFTER,
            "devices": rows, "events": list(reversed(home.get("events", [])))[:limit]}


def outages(hours=24, now=None):
    """The story of the last few hours, for people and for the MCP tool."""
    hours = max(1, min(int(hours), 24 * 30))
    cutoff = ((now or datetime.now()) - timedelta(hours=hours)).isoformat(timespec="seconds")
    snapshot = status(limit=MAX_EVENTS)
    recent = [e for e in snapshot["events"] if e["at"] >= cutoff]
    down_now = [d["name"] for d in snapshot["devices"] if d["status"] == "down"]
    drops = [e for e in recent if e["type"] == "went_down"]
    return {"hours": hours, "watching": len(snapshot["devices"]), "watch_running": snapshot["running"],
            "currently_down": down_now, "went_down_count": len(drops), "events": recent}


def sentence(report):
    """A short plain sentence about outages (used by the helper and the simulated Alexa+)."""
    if not report["watching"]:
        return "Nothing is being watched yet. Use Check my real network on the Devices page to start."
    hours = report["hours"]
    parts = []
    if report["currently_down"]:
        parts.append("Right now " + ", ".join(report["currently_down"]) + (" is" if len(report["currently_down"]) == 1 else " are") + " offline.")
    if report["went_down_count"]:
        names = sorted({e["name"] for e in report["events"] if e["type"] == "went_down"})
        n = report["went_down_count"]
        parts.append(f"In the last {hours} hours there {'was' if n == 1 else 'were'} {n} outage{'s' if n != 1 else ''}: {', '.join(names)}.")
    if not parts:
        parts.append(f"Nothing has gone offline in the last {hours} hours. I'm watching {report['watching']} device{'s' if report['watching'] != 1 else ''}.")
    return " ".join(parts)
