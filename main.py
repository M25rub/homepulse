import hmac
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.responses import JSONResponse
from starlette.routing import Route

import alexa_sim
import core
import discovery
import netinfo
import watcher
from core import load_home, save_home
from mcp.server.transport_security import TransportSecuritySettings
from mcp_server import build_server

WEB_DIR = Path(__file__).parent / "web"
router = APIRouter()       # every normal endpoint hangs off this; create_app() attaches it

# ---------------- The MCP server (what Alexa+ connects to) ----------------
#
# It lives inside this same app at /mcp, so one process owns home.json.
# Every request must carry "Authorization: Bearer <token>", otherwise it gets a 401.
# No account is needed to try it: the default demo token is printed in the README.
# For anything beyond a local demo, set your own with HOMEPULSE_MCP_TOKEN.

DEMO_TOKEN = "homepulse-demo-token"

# The library refuses requests whose Host header it does not recognise (protection against
# DNS-rebinding). Localhost works out of the box. If you expose HomePulse through a tunnel or a
# server, list its host name in HOMEPULSE_ALLOWED_HOSTS, comma separated (for example "abc.ngrok.app").
def _security():
    extra = [h.strip() for h in os.environ.get("HOMEPULSE_ALLOWED_HOSTS", "").split(",") if h.strip()]
    hosts = ["127.0.0.1:*", "localhost:*", "127.0.0.1", "localhost", "testserver"] + extra + [h + ":*" for h in extra]
    origins = ["http://127.0.0.1:*", "http://localhost:*"] + ["https://" + h for h in extra]
    return TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=origins)


class BearerAuth:
    """Wraps the MCP endpoint and rejects requests without the right bearer token."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        expected = os.environ.get("HOMEPULSE_MCP_TOKEN", DEMO_TOKEN)
        header = dict(scope.get("headers", [])).get(b"authorization", b"").decode("latin-1")
        given = header[7:].strip() if header.lower().startswith("bearer ") else ""
        if not given or not hmac.compare_digest(given.encode(), expected.encode()):
            response = JSONResponse({"error": "unauthorized", "detail": "Send 'Authorization: Bearer <token>'."},
                                    status_code=401, headers={"WWW-Authenticate": 'Bearer realm="HomePulse"'})
            return await response(scope, receive, send)
        return await self.inner(scope, receive, send)


# Remembers the most recent run, so the helper can explain it.
LAST_RUN = {"routine": None, "results": []}


class NewDevice(BaseModel):
    name: str
    category: str = "other"
    room: str = ""
    behavior: str = "ok"
    address: str = ""             # for a live device: a URL or host:port that HomePulse really checks
    fallback_address: str = ""
    adapter: str = ""             # a smart plug protocol: shelly_gen1, shelly_gen2 or tasmota


class Target(BaseModel):
    type: str
    id: str = ""


class Action(BaseModel):
    target: Target
    capability: str
    value: str | int | float


class NewRoutine(BaseModel):
    name: str
    actions: list[Action]


class Question(BaseModel):
    message: str


def bad_request(error):
    return HTTPException(status_code=400, detail=str(error))


# ---------------- Catalog ----------------

@router.get("/catalog")
def get_catalog():
    return core.catalog()


# ---------------- Devices ----------------

@router.get("/devices")
def list_devices():
    return load_home()["devices"]


@router.post("/devices")
def add_device(new: NewDevice):
    if not new.name.strip():
        raise bad_request("A device needs a name")
    home = load_home()
    try:
        device = core.new_device(home, new.name, new.category, new.room, new.behavior,
                                 address=new.address, fallback_address=new.fallback_address, adapter=new.adapter)
    except ValueError as error:
        raise bad_request(error)
    save_home(home)
    return device


@router.delete("/devices/{device_id}")
def remove_device(device_id: str):
    home = load_home()
    if device_id not in home["devices"]:
        raise HTTPException(status_code=404, detail="No such device")
    del home["devices"][device_id]
    save_home(home)
    return {"removed": device_id}


@router.post("/devices/sample")
def add_sample_home():
    home = load_home()
    added = core.load_sample(home)
    save_home(home)
    return {"added": added, "devices_in_home": len(home["devices"])}


@router.post("/devices/discover")
def discover_devices():
    home = load_home()
    found = core.discover(home)
    save_home(home)
    return {"found": len(found), "devices": found, "devices_in_home": len(home["devices"])}


@router.post("/devices/scan")
def scan_network():
    """Really scan the local network (SSDP/UPnP). Returns what answered; nothing is added until you choose."""
    result = discovery.scan()
    known = {d.get("address", "").rstrip("/") for d in load_home()["devices"].values()}
    for d in result["devices"]:
        d["already_added"] = d["address"].rstrip("/") in known
    return result


@router.post("/devices/quickstart")
def quickstart():
    """One click, real checks: find the router, add it and the internet as live devices, and check them now."""
    plan, note = netinfo.quickstart_plan()
    home = load_home()
    ids, added = [], []
    for item in plan:
        existing = next((d for d in home["devices"].values()
                         if d.get("name") == item["name"] and d.get("behavior") == "live"), None)
        if existing:
            existing["address"] = core.valid_address(item["address"])
            ids.append(existing["id"])
            continue
        device = core.new_device(home, item["name"], "network", "", address=item["address"])
        ids.append(device["id"])
        added.append(device["name"])
    actions = core.clean_actions([{"target": {"type": "device", "id": i}, "capability": "reachable", "value": "online"}
                                  for i in ids])
    home["routines"]["check_my_network"] = {"name": "check_my_network", "actions": actions}
    results, unmatched = core.run_actions(home, actions)
    out = finish_run(home, "check_my_network", results, unmatched)
    out.update({"added": added, "note": note, "checked": [{"name": i["name"], "address": i["address"]} for i in plan]})
    return out


class AlexaCall(BaseModel):
    tool: str
    arguments: dict = {}


@router.post("/alexa/run")
async def alexa_run(call: AlexaCall, request: Request):
    """The simulated Alexa+: makes a REAL MCP call to this same server and follows PENDING until it is final."""
    url = str(request.base_url).rstrip("/") + "/mcp"
    token = os.environ.get("HOMEPULSE_MCP_TOKEN", DEMO_TOKEN)
    try:
        return await alexa_sim.run(url, token, call.tool, call.arguments)
    except ValueError as error:
        raise bad_request(error)
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"Could not reach the MCP server at {url}: {error}")


@router.post("/devices/import")
def import_devices(payload: Any = Body(...)):
    home = load_home()
    try:
        added, skipped, notes = core.import_alexa(home, payload)
    except ValueError as error:
        raise bad_request(error)
    save_home(home)
    return {"added": len(added), "skipped": skipped, "unsupported_interfaces": notes,
            "devices_in_home": len(home["devices"])}


# ---------------- Routines ----------------

@router.get("/routines")
def list_routines():
    return load_home()["routines"]


@router.post("/routines")
def add_routine(routine: NewRoutine):
    name = routine.name.strip()
    if not name:
        raise bad_request("A routine needs a name")
    try:
        actions = core.clean_actions([a.model_dump() for a in routine.actions])
    except ValueError as error:
        raise bad_request(error)
    if not actions:
        raise bad_request("A routine needs at least one step")
    home = load_home()
    home["routines"][name] = {"name": name, "actions": actions}
    save_home(home)
    return {"saved_routine": name}


@router.delete("/routines/{routine_name}")
def remove_routine(routine_name: str):
    home = load_home()
    if routine_name not in home["routines"]:
        raise HTTPException(status_code=404, detail="No such routine")
    del home["routines"][routine_name]
    save_home(home)
    return {"removed": routine_name}


# ---------------- Running things (the reliability engine) ----------------

def finish_run(home, label, results, unmatched):
    LAST_RUN["routine"] = label
    LAST_RUN["results"] = results
    core.record_history(home, label, results)
    save_home(home)
    return {"summary": core.summarize(label, results, unmatched), "results": results, "unmatched": unmatched}


@router.post("/run/{routine_name}")
def run_routine(routine_name: str):
    home = load_home()
    routine = home["routines"].get(routine_name)
    if routine is None:
        raise HTTPException(status_code=404, detail="No such routine")
    try:
        results, unmatched = core.run_actions(home, routine["actions"])
    except ValueError as error:
        raise bad_request(error)
    return finish_run(home, routine_name, results, unmatched)


@router.post("/command")
def run_command(action: Action):
    """One-off command, for example 'set the living room light to 30%'."""
    home = load_home()
    try:
        actions = core.clean_actions([action.model_dump()])
        results, unmatched = core.run_actions(home, actions)
    except ValueError as error:
        raise bad_request(error)
    return finish_run(home, "command", results, unmatched)


@router.get("/watch")
def get_watch():
    """The live watch: which real devices are being checked in the background, and recent outages."""
    return watcher.status()


@router.get("/pulse")
def get_pulse():
    """Health of the whole home, worked out from every command HomePulse has checked."""
    return core.pulse(load_home())


@router.get("/history")
def get_history():
    return list(reversed(load_home().get("history", [])))


@router.delete("/history")
def clear_history():
    home = load_home()
    home["history"] = []
    save_home(home)
    return {"cleared": True}


# ---------------- The built-in helper (a simple keyword version for now) ----------------
#
# Every reply is built from "parts". Each part carries a translation key, the English
# template and its values, so the website can show the reply in the visitor's language.

def part(key, en, **vars):
    return {"key": key, "en": en, "vars": vars}


def render(parts):
    return "\n\n".join(p["en"].format(**p["vars"]) for p in parts)


def has(text, *phrases):
    return any(re.search(r"\b" + re.escape(p), text) for p in phrases)


def has_word(text, *words):
    return any(re.search(r"\b" + re.escape(w) + r"\b", text) for w in words)


OUTCOME_PARTS = {
    "confirmed": ("ha_o_ok", "{name}: worked the first time."),
    "recovered by retry": ("ha_o_retry", "{name}: ignored my first message, so I asked again, and then it worked."),
    "recovered by local fallback": ("ha_o_fb", "{name}: its usual internet connection wasn't working, so I used a backup route, and then it worked."),
}
OUTCOME_BAD = ("ha_o_bad", "{name}: I couldn't reach it at all. Please check that it has power and a Wi-Fi connection.")


def outcome_part(r):
    key, en = OUTCOME_PARTS.get(r["outcome"], OUTCOME_BAD)
    return part(key, en, name=r["device"])


def assistant_parts(message):
    text = message.lower().strip()
    home = load_home()
    devices = list(home["devices"].values())
    routines = list(home["routines"].keys())
    results = LAST_RUN["results"]
    last_name = LAST_RUN["routine"]
    if not results and home.get("history"):
        last = home["history"][-1]
        results = last["results"]
        last_name = last["routine"]

    if not text:
        return [part("ha_empty", "Ask me anything about your home or this app, in your own words.")]

    if has(text, "pulse", "health", "attention", "reliab", "score", "keep failing", "keeps failing",
           "how is my home", "how's my home", "hows my home", "everything ok", "all good"):
        report = core.pulse(home)
        if not report["total_checks"]:
            return [part("ha_pulse_none", "I haven't checked anything yet, so there is no pulse to report. Run a routine or check a device and ask me again.")]
        urgent = [a["name"] for a in report["attention"] if a["level"] == "urgent"]
        watch = [a["name"] for a in report["attention"] if a["level"] == "watch"]
        out = [part("ha_pulse_score", "Your home's health score is {score} out of 100, from {n} checked commands.", score=report["score"], n=report["total_checks"])]
        if urgent:
            out.append(part("ha_pulse_urgent", "Needs attention now: {names}.", names=", ".join(urgent)))
        if watch:
            out.append(part("ha_pulse_watch", "Worth keeping an eye on: {names}.", names=", ".join(watch)))
        if not urgent and not watch:
            out.append(part("ha_pulse_fine", "Everything checked so far is healthy."))
        return out

    if has(text, "outage", "went down", "gone down", "go down", "went offline", "gone offline", "go offline", "dropped",
           "is my internet", "is my router", "is my wifi", "is my wi-fi", "internet down", "internet drop", "being watched"):
        return [part("ha_outage", "{s}", s=watcher.sentence(watcher.outages(24)))]

    if has(text, "fail", "wrong", "problem", "didn't", "did not", "not work", "doesn't work",
           "why", "broke", "error", "issue", "happened"):
        if not results:
            return [part("ha_norun", "You haven't run a routine yet. Run one and I'll explain exactly what happened.")]
        problems = [r for r in results if r["outcome"] != "confirmed"]
        if not problems:
            return [part("ha_allgood", "Nothing went wrong in your last run ({last}). Every device did what it was asked, and I double-checked each one.", last=last_name)]
        return [part("ha_prob_head", "Here's what happened in your last run ({last}):", last=last_name)] + [outcome_part(r) for r in problems]

    if has(text, "safe", "secure", "status", "how is", "how's", "everything ok", "all good"):
        if not results:
            return [part("ha_safe_none", "I haven't checked anything yet. Run a routine and I'll tell you if everything really worked.")]
        bad = [r["device"] for r in results if not r["verified"]]
        ok = len(results) - len(bad)
        if not bad:
            return [part("ha_safe_yes", "Yes. In your last run, all {ok} devices were confirmed.", ok=ok)]
        return [part("ha_safe_some", "Mostly. {ok} of {total} devices were confirmed. These need your attention: {names}.",
                     ok=ok, total=len(results), names=", ".join(sorted(set(bad))))]

    if has(text, "alert", "notification", "notify", "phone"):
        return [part("ha_alert", "Right now, problems are shown on screen only. Real phone and email alerts are coming in a later version of HomePulse.")]

    if has(text, "dim", "play", "music", "volume", "turn on", "turn off", "switch on", "switch off", "temperature", "thermostat"):
        return [part("ha_cmd", "I can't take voice commands yet. For now, make a routine on the Routines page, for example Brightness 30 for the Living room light, or Playback playing for the Speaker, and HomePulse will run it and check the result. Voice commands arrive with the Alexa+ connection.")]

    if has(text, "add", "new device", "connect", "set up", "setup"):
        return [part("ha_add", "To add a device: open the Devices page, give it a name, pick what kind of device it is, and say what it's doing right now.")]

    if has(text, "remove", "delete", "get rid"):
        return [part("ha_remove", "On the Devices page, find the device and press Remove. I'll ask you to confirm first.")]

    if has(text, "routine", "automation", "quick action"):
        names = ", ".join(routines) if routines else "-"
        return [part("ha_routine", "A routine is a list of things you want done together, like Goodnight: lock the doors and turn off the lights. You create one on the Routines page, then run it with one press. Your routines right now: {names}.", names=names)]

    if has(text, "device", "list", "what do i have", "how many", "what's in", "whats in"):
        if not devices:
            return [part("ha_nodevices", "You haven't added any devices yet.")]
        return [part("ha_devices", "You have {n} devices: {names}.", n=len(devices), names=", ".join(d["name"] for d in devices))]

    if has(text, "demo", "simulat", "pretend", "fake", "misbehave"):
        return [part("ha_demo", "The devices in this version are simulated, so we can show how HomePulse reacts when something goes wrong. In real life, the same checking would work with real smart devices.")]

    if has(text, "what is", "what does", "what's", "homepulse", "how does", "explain", "about", "help"):
        return [part("ha_about", "HomePulse double-checks your smart home. When you ask for something like securing the house, it does not settle for 'sent': it checks that each device really did it. If something didn't work, it tries again, tries a backup route, and tells you plainly what went wrong. It also keeps a record, so you can see which devices keep letting you down.")]

    if len(text.split()) <= 4 and has_word(text, "hi", "hello", "hey", "salam", "thanks", "thank"):
        return [part("ha_hello", "Hello! I can explain what HomePulse does, help you add devices or routines, or tell you what happened in your last run.")]

    return [part("ha_unknown", "I'm not sure about that one yet. I can help with: what HomePulse does, adding or removing a device, routines, and what happened in your last run.")]


@router.post("/assistant")
def assistant(q: Question):
    parts = assistant_parts(q.message)
    return {"reply": render(parts), "parts": parts}


# ---------------- Build the app (the website must be attached last) ----------------

def create_app():
    """Build the whole app. A function, so each test can have its own fresh copy."""
    mcp_app = build_server().streamable_http_app(streamable_http_path="/mcp", transport_security=_security())

    @asynccontextmanager
    async def lifespan(_app):
        watcher.start()                                           # keep checking real devices in the background
        try:
            async with mcp_app.router.lifespan_context(mcp_app):      # starts the MCP session manager
                yield
        finally:
            watcher.stop()

    application = FastAPI(title="HomePulse", lifespan=lifespan)
    application.router.routes.insert(0, Route("/mcp", endpoint=BearerAuth(mcp_app.routes[0].app)))
    application.include_router(router)
    application.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return application


app = create_app()
