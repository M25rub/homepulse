"""The live watch: real checks in the background, with protection against false alarms and edge cases."""
import socket
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from starlette.testclient import TestClient

import core
import main
import watcher


class Quiet(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *a): pass


class Real:
    def __init__(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0)); self.port = s.getsockname()[1]
        self.server = None
        self.up()
    def up(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), Quiet)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
    def down(self):
        self.server.shutdown(); self.server.server_close()
    @property
    def url(self): return f"http://127.0.0.1:{self.port}"


@pytest.fixture
def device():
    d = Real()
    yield d
    try: d.down()
    except Exception: pass


def watch_home(address, **kw):
    home = core.load_home()
    core.new_device(home, "Printer", "network", address=address, **kw)
    core.save_home(home)


T0 = datetime(2026, 10, 23, 21, 0, 0)
def at(minutes): return T0 + timedelta(minutes=minutes)


def test_up_device_makes_no_events(device):
    watch_home(device.url)
    assert watcher.tick(at(0)) == [] and watcher.tick(at(1)) == []
    row = watcher.status()["devices"][0]
    assert row["status"] == "up" and core.load_home()["devices"]["printer"]["state"]["reachable"] == "online"


def test_one_missed_check_is_not_an_outage(device):
    watch_home(device.url)
    watcher.tick(at(0))
    device.down(); assert watcher.tick(at(1)) == []            # one miss: no alarm
    device.up();   assert watcher.tick(at(2)) == []            # it came back: still nothing to report
    assert watcher.status()["events"] == []


def test_outage_is_dated_from_first_miss_and_recovery_reports_duration(device):
    watch_home(device.url)
    watcher.tick(at(0))
    device.down()
    watcher.tick(at(1))
    events = watcher.tick(at(2))
    assert [e["type"] for e in events] == ["went_down"] and events[0]["at"] == at(1).isoformat(timespec="seconds")
    assert core.load_home()["devices"]["printer"]["state"]["reachable"] == "offline"
    assert watcher.tick(at(3)) == []                           # still down: no repeat alarm
    device.up()
    back = watcher.tick(at(6))
    assert back[0]["type"] == "back_up" and back[0]["down_for_seconds"] == 5 * 60
    assert [e["type"] for e in watcher.status()["events"]] == ["back_up", "went_down"]      # newest first


def test_backup_address_keeps_a_device_up(device):
    watch_home("http://127.0.0.1:9", fallback_address=device.url)
    watcher.tick(at(0)); watcher.tick(at(1))
    assert watcher.status()["devices"][0]["status"] == "up"


def test_no_live_devices_is_calm(sample_home):
    assert watcher.tick(at(0)) == []
    assert watcher.status()["devices"] == []
    assert "Nothing is being watched" in watcher.sentence(watcher.outages(24))


def test_device_removed_while_down_does_not_crash(device):
    watch_home(device.url)
    watcher.tick(at(0)); device.down(); watcher.tick(at(1))
    home = core.load_home(); del home["devices"]["printer"]; core.save_home(home)
    assert watcher.tick(at(2)) == []
    assert watcher.status()["devices"] == []


def test_a_check_that_blows_up_counts_as_no_answer(monkeypatch, device):
    watch_home(device.url)
    monkeypatch.setattr(core, "probe", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    watcher.tick(at(0)); events = watcher.tick(at(1))
    assert events and events[0]["type"] == "went_down"


def test_many_devices_one_dead_does_not_hide_the_others(device):
    home = core.load_home()
    core.new_device(home, "Alive", "network", address=device.url)
    core.new_device(home, "Dead", "network", address="http://127.0.0.1:9")
    core.new_device(home, "Dead too", "network", address="127.0.0.1:9")
    core.save_home(home)
    watcher.tick(at(0)); events = watcher.tick(at(1))
    assert sorted(e["name"] for e in events) == ["Dead", "Dead too"]
    assert {d["name"]: d["status"] for d in watcher.status()["devices"]}["Alive"] == "up"


def test_event_log_is_capped(monkeypatch, device):
    monkeypatch.setattr(watcher, "MAX_EVENTS", 5)
    watch_home(device.url)
    for i in range(12):                                         # flap up and down repeatedly
        (device.down if i % 2 == 0 else device.up)()
        watcher.tick(at(i * 2)); watcher.tick(at(i * 2 + 1))
    assert len(core.load_home()["events"]) <= 5


def test_outage_window_only_counts_recent_events(device):
    watch_home(device.url)
    watcher.tick(at(0)); device.down(); watcher.tick(at(1)); watcher.tick(at(2))
    now = at(2)
    assert watcher.outages(24, now=now)["went_down_count"] == 1
    assert watcher.outages(24, now=now + timedelta(hours=30))["went_down_count"] == 0
    assert "Right now Printer is offline" in watcher.sentence(watcher.outages(24, now=now))


def test_damaged_event_log_is_repaired():
    core.FILE.write_text('{"devices": {}, "routines": {}, "history": [], "events": "oops"}')
    assert core.load_home()["events"] == []


def test_endpoint_helper_and_mcp_tool(device, sample_home):
    watch_home(device.url)
    watcher.tick(at(0)); device.down(); watcher.tick(at(1)); watcher.tick(at(2))
    client = TestClient(main.create_app())
    assert client.get("/watch").json()["devices"][0]["status"] == "down"
    reply = client.post("/assistant", json={"message": "did my printer go offline? has anything gone offline"}).json()["reply"]
    assert "Printer" in reply
    import mcp_server
    out = mcp_server.get_outages(24)
    assert out["currently_down"] == ["Printer"] and "Printer" in out["summary"]


def test_watch_starts_and_stops_with_the_app(monkeypatch):
    monkeypatch.setattr(watcher, "INTERVAL", 3600)
    assert watcher.start() is True and watcher.running()
    watcher.stop()
    monkeypatch.setattr(watcher, "INTERVAL", 0)
    assert watcher.start() is False
