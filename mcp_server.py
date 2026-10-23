"""HomePulse MCP server: lets an assistant such as Alexa+ control the home AND get a true answer.

Tools (all return in well under 500 ms; slow work happens in the background):

    list_devices        what is in the home
    get_device_state    what one device last reported
    set_device_state    ask for a change      -> PENDING + command_id (returns at once)
    check_device        really check a live device is reachable -> PENDING + command_id
    run_routine         run a saved routine   -> PENDING + command_id (returns at once)
    get_command_status  the verified answer   -> PENDING, or VERIFIED / PARTIAL / FAILED
    list_routines       saved routines
    get_home_pulse      health score, what needs attention, and why
    get_device_history  one device's track record
    get_outages         what went offline lately, and what is offline now (from the live watch)
"""
from mcp.server.mcpserver import MCPServer

import commands
import core
import watcher

INSTRUCTIONS = (
    "HomePulse controls a smart home and CHECKS that each command really happened. "
    "Changing a device is a two-step process: set_device_state or run_routine returns status PENDING "
    "and a command_id immediately. You MUST then call get_command_status with that command_id before "
    "telling the user the result. Only VERIFIED means the device itself reported the new value. "
    "PENDING means keep waiting (call again after retry_after_ms). PARTIAL or FAILED means something "
    "did not work: say so plainly, using the explanation field. Never claim success while PENDING. "
    "Use get_home_pulse when the user asks how the home is doing or what needs attention. "
    "Use get_outages when the user asks whether the internet, router or any watched device went offline."
)

_TOOLS = []


def _tool(fn):
    """Collect a tool function; build_server() registers them on a fresh server."""
    _TOOLS.append(fn)
    return fn


def build_server():
    """Make a new MCP server with all the tools. (One server object can only be started once,
    so the app builds its own, and the tests build one per test.)"""
    server = MCPServer("HomePulse", instructions=INSTRUCTIONS, version="1.0.0")
    for fn in _TOOLS:
        server.add_tool(fn)
    return server

RETRY_AFTER_MS = 500


def _pending(command_id, what):
    return {
        "status": commands.PENDING, "command_id": command_id, "requested_action": what,
        "next_action": f"Call get_command_status with command_id '{command_id}' to verify execution.",
        "retry_after_ms": RETRY_AFTER_MS,
    }


def _rejected(message, **extra):
    return {"status": "REJECTED", "reason": message, **extra}


def _device_view(d):
    view = {"device_id": d["id"], "name": d["name"], "room": d.get("room", ""), "category": d["category"],
            "capabilities": d["capabilities"], "reported_state": d["state"],
            "kind": "live (really reached over the network)" if d.get("behavior") == "live" else "simulated"}
    if d.get("adapter"):
        view["plug_protocol"] = d["adapter"]
    return view


@_tool
def list_devices(room: str = "", category: str = "") -> dict:
    """List the devices in the home with their last reported state. Optionally filter by room or category."""
    devices = core.load_home()["devices"].values()
    out = [_device_view(d) for d in devices
           if (not room or d.get("room", "").lower() == room.lower())
           and (not category or d["category"] == category.lower())]
    return {"count": len(out), "devices": out}


@_tool
def get_device_state(device_id: str) -> dict:
    """Get what one device last reported. This is the last verified state, not a live reading."""
    device = core.load_home()["devices"].get(device_id)
    if device is None:
        return _rejected(f"No device with id '{device_id}'.", hint="Call list_devices to see valid ids.")
    return _device_view(device)


@_tool
def set_device_state(device_id: str, capability: str, value: str) -> dict:
    """Ask a device to change, e.g. device_id 'front_lock', capability 'lock', value 'locked'.

    Returns immediately with status PENDING and a command_id. You must then call
    get_command_status to learn whether the device really did it."""
    home = core.load_home()
    device = home["devices"].get(device_id)
    if device is None:
        return _rejected(f"No device with id '{device_id}'.", hint="Call list_devices to see valid ids.")
    if capability not in device["capabilities"]:
        return _rejected(f"{device['name']} cannot do '{capability}'.", valid_capabilities=device["capabilities"])
    try:
        clean = core.clean_value(capability, value)
    except ValueError as error:
        return _rejected(str(error), capability=capability, spec=core.CAPABILITIES[capability])
    action = {"target": {"type": "device", "id": device_id}, "capability": capability, "value": clean}
    command_id = commands.submit([action], label=f"{device['name']}: {capability} -> {clean}")
    return {**_pending(command_id, action), "target_device": device["name"]}


@_tool
def check_device(device_id: str) -> dict:
    """Really check whether a live device (one with a network address) is reachable right now.

    Returns PENDING and a command_id; call get_command_status for the verified answer."""
    device = core.load_home()["devices"].get(device_id)
    if device is None:
        return _rejected(f"No device with id '{device_id}'.", hint="Call list_devices to see valid ids.")
    if device.get("behavior") != "live":
        return _rejected(f"{device['name']} is a simulated device with no network address to check.",
                         hint="Use set_device_state for simulated devices.")
    action = {"target": {"type": "device", "id": device_id}, "capability": "reachable", "value": "online"}
    command_id = commands.submit([action], label=f"{device['name']}: reachable check")
    return {**_pending(command_id, action), "target_device": device["name"]}


@_tool
def run_routine(routine_name: str) -> dict:
    """Run a saved routine (a group of changes, like 'secure_house'). Returns PENDING and a command_id;
    call get_command_status to learn what really happened on every device."""
    home = core.load_home()
    routine = home["routines"].get(routine_name)
    if routine is None:
        return _rejected(f"No routine called '{routine_name}'.", available=sorted(home["routines"]))
    command_id = commands.submit(routine["actions"], label=routine_name)
    return {**_pending(command_id, {"routine": routine_name, "steps": len(routine["actions"])}),
            "target_device": f"routine '{routine_name}'"}


@_tool
def get_command_status(command_id: str) -> dict:
    """Get the verified result of set_device_state or run_routine.

    status is PENDING (call again after retry_after_ms), VERIFIED (every device reported the new value),
    PARTIAL (some did, some did not) or FAILED (none did). Read 'explanation' to tell the user why."""
    record = commands.status(command_id)
    if record is None:
        return _rejected(f"Unknown command_id '{command_id}'.")
    if record["status"] == commands.PENDING:
        return {"status": commands.PENDING, "command_id": command_id, "retry_after_ms": RETRY_AFTER_MS,
                "next_action": f"Still checking. Call get_command_status again with '{command_id}'."}
    steps = [{"device": s["device"], "device_id": s["device_id"], "capability": s["capability"],
              "desired": s["wanted"], "reported": s["reported"], "verified": s["verified"],
              "result": s["outcome"], "attempts": len(s["attempts"]),
              "routes_tried": [a["route"] for a in s["attempts"]]} for s in record["steps"]]
    return {"status": record["status"], "command_id": command_id, "how": record["how"],
            "summary": record["summary"], "explanation": record["explanation"],
            "elapsed_ms": record["elapsed_ms"], "steps": steps,
            "unmatched_steps": record.get("unmatched_steps", 0)}


@_tool
def list_routines() -> dict:
    """List the saved routines and how many steps each has."""
    routines = core.load_home()["routines"]
    return {"routines": [{"name": n, "steps": len(r["actions"])} for n, r in routines.items()]}


@_tool
def get_home_pulse() -> dict:
    """Get the health of the whole home: a 0-100 score, which devices need attention and why,
    and groups of devices failing together (which hints at a shared cause, like a room's Wi-Fi)."""
    report = core.pulse(core.load_home())
    return {"score": report["score"], "headline": report["headline"], "attention": report["attention"],
            "patterns": report["patterns"], "commands_saved_by_recovery": report["saved_by_recovery"],
            "total_checks": report["total_checks"]}


@_tool
def get_device_history(device_id: str) -> dict:
    """Get one device's track record: how often its commands worked first time, needed a retry or
    the backup route, or never worked."""
    home = core.load_home()
    if device_id not in home["devices"]:
        return _rejected(f"No device with id '{device_id}'.", hint="Call list_devices to see valid ids.")
    row = next(r for r in core.pulse(home)["devices"] if r["device_id"] == device_id)
    return row


@_tool
def get_outages(hours: int = 24) -> dict:
    """Get what went offline in the last few hours and what is offline right now. HomePulse keeps checking
    its real (live) devices in the background, so this answers "did my internet drop today?"."""
    report = watcher.outages(hours)
    return {**report, "summary": watcher.sentence(report)}
