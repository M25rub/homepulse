"""The command ledger: how HomePulse runs a command in the background and remembers the answer.

Why this exists: an assistant like Alexa+ needs an answer within about half a second, but
checking a device (send, verify, retry, try the backup route) takes longer. So a command is
split in two:

    submit()  -> returns at once with status PENDING and a command_id
    status()  -> later returns PENDING, or one final answer: VERIFIED, PARTIAL or FAILED

Final answers are never guessed. VERIFIED means the device itself reported the new value.
"""
import copy
import os
import threading
import time
import uuid
from datetime import datetime

import core

PENDING, VERIFIED, PARTIAL, FAILED = "PENDING", "VERIFIED", "PARTIAL", "FAILED"

# Simulated network delay for each attempt, so the PENDING -> final step is real and visible.
LATENCY_MS = int(os.environ.get("HOMEPULSE_LATENCY_MS", "150"))

_COMMANDS = {}
_LOCK = threading.Lock()
MAX_KEPT = 200


def _pause():
    if LATENCY_MS > 0:
        time.sleep(LATENCY_MS / 1000)


def _remember(record):
    with _LOCK:
        _COMMANDS[record["command_id"]] = record
        while len(_COMMANDS) > MAX_KEPT:
            _COMMANDS.pop(next(iter(_COMMANDS)))


def reset():
    """Forget every command. Used by the tests."""
    with _LOCK:
        _COMMANDS.clear()


def _final_status(results):
    if not results:
        return FAILED
    good = sum(1 for r in results if r["verified"])
    if good == len(results):
        return VERIFIED
    return PARTIAL if good else FAILED


def _how(results):
    """A short label for how the answer was reached."""
    outcomes = {r["outcome"] for r in results}
    if outcomes == {"confirmed"}:
        return "confirmed on the first try"
    parts = []
    if "recovered by retry" in outcomes:
        parts.append("needed a retry")
    if "recovered by local fallback" in outcomes:
        parts.append("needed the backup (local) route")
    if core.FAILED_OUTCOME in outcomes:
        parts.append("at least one device never responded")
    return ", ".join(parts)


def _run(command_id, actions):
    started = time.perf_counter()
    record = _COMMANDS[command_id]
    try:
        with core.HOME_LOCK:
            home = core.load_home()
        results, unmatched = core.run_actions(home, actions, pause=_pause)
        with core.HOME_LOCK:
            home = core.load_home()                       # fresh copy: keep any edits made meanwhile
            for r in results:
                device = home["devices"].get(r["device_id"])
                if device is None:
                    continue
                if device.get("behavior") == "live":
                    silent = r["reported"] == "no answer"
                    if "reachable" in device["capabilities"]:
                        device["state"]["reachable"] = "offline" if silent else "online"
                    if not silent:
                        device["state"][r["capability"]] = r["reported"]       # the device itself reported this
                elif r["verified"]:
                    device["state"][r["capability"]] = r["reported"]           # the device itself reported this
            core.record_history(home, record["label"], results)
            core.save_home(home)
        status = _final_status(results)
        record.update({
            "status": status, "steps": results, "unmatched_steps": unmatched,
            "how": _how(results) if results else "no device matched",
            "summary": core.summarize(record["label"], results, unmatched),
            "explanation": [r["explanation"] for r in results],
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "finished": datetime.now().isoformat(timespec="seconds"),
        })
    except Exception as error:                            # never leave a command stuck on PENDING
        record.update({"status": FAILED, "steps": [], "how": "internal error", "summary": f"HomePulse hit an error: {error}",
                       "explanation": [], "elapsed_ms": round((time.perf_counter() - started) * 1000)})


def submit(actions, label, run_in_background=True):
    """Start a command. Returns at once with the PENDING record (the contract Alexa+ needs)."""
    command_id = "cmd_" + uuid.uuid4().hex[:12]
    record = {
        "command_id": command_id, "status": PENDING, "label": label,
        "requested_action": copy.deepcopy(actions), "created": datetime.now().isoformat(timespec="seconds"),
        "steps": [], "elapsed_ms": None,
    }
    _remember(record)
    if run_in_background:
        threading.Thread(target=_run, args=(command_id, actions), daemon=True).start()
    else:
        _run(command_id, actions)
    return command_id


def status(command_id):
    """The current record for a command, or None if the id is unknown."""
    with _LOCK:
        record = _COMMANDS.get(command_id)
    return copy.deepcopy(record) if record else None


def wait(command_id, timeout=5.0):
    """Block until a command finishes. For tests and scripts, not for the MCP tools."""
    end = time.time() + timeout
    while time.time() < end:
        record = status(command_id)
        if record and record["status"] != PENDING:
            return record
        time.sleep(0.02)
    return status(command_id)
