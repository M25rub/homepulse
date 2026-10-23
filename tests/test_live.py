"""Live devices: HomePulse really reaches out over the network. The 'device' here is a real little web server."""
import asyncio
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from starlette.testclient import TestClient

import commands
import core
import main


class Quiet(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


class RealDevice:
    """A real HTTP server on a free port that we can switch off, like unplugging a smart plug."""

    def __init__(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}/"
        self.server = None

    def start(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), Quiet)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None


@pytest.fixture
def device():
    d = RealDevice().start()
    yield d
    d.stop()


def add_live(home, address, fallback=""):
    return core.new_device(home, "Test plug", "network", "Study", address=address, fallback_address=fallback)


def test_address_validation():
    assert core.valid_address("http://192.168.1.20/status") == "http://192.168.1.20/status"
    assert core.valid_address("192.168.1.20:80") == "192.168.1.20:80"
    for bad in ["", "hello", "http://", "192.168.1.20", "host:abc", "host:99999", "ftp://x"]:
        with pytest.raises(ValueError):
            core.valid_address(bad)


def test_a_running_device_is_confirmed_for_real(device):
    home = core.load_home()
    d = add_live(home, device.url)
    detail = core.verify_detailed(d, "reachable", "online")
    assert detail["outcome"] == "confirmed" and d["state"]["reachable"] == "online"


def test_a_stopped_device_is_reported_failed_never_confirmed(device):
    home = core.load_home()
    d = add_live(home, device.url)
    device.stop()                                                   # unplug it
    detail = core.verify_detailed(d, "reachable", "online")
    assert detail["outcome"] == core.FAILED_OUTCOME and not detail["verified"]
    assert d["state"]["reachable"] == "offline" and len(detail["attempts"]) == 2


def test_backup_address_recovers_a_dead_main_address(device):
    home = core.load_home()
    dead = RealDevice()                                             # nothing is listening here
    d = add_live(home, dead.url, fallback=device.url)
    detail = core.verify_detailed(d, "reachable", "online")
    assert detail["outcome"] == "recovered by local fallback" and detail["attempts"][-1]["route"] == "local"


def test_tcp_host_port_address_works(device):
    d = add_live(core.load_home(), f"127.0.0.1:{device.port}")
    assert core.verify_detailed(d, "reachable", "online")["verified"]


def test_full_flow_unplug_it_and_the_pulse_flags_it(device):
    home = core.load_home()
    add_live(home, device.url)
    core.save_home(home)
    action = [{"target": {"type": "category", "id": "network"}, "capability": "reachable", "value": "online"}]

    first = commands.wait(commands.submit(action, "check"))
    assert first["status"] == commands.VERIFIED

    device.stop()
    second = commands.wait(commands.submit(action, "check"), timeout=10)
    assert second["status"] == commands.FAILED and "did not answer" in second["explanation"][0]

    saved = core.load_home()
    assert saved["devices"]["test_plug"]["state"]["reachable"] == "offline"      # the truth is remembered
    pulse = core.pulse(saved)
    assert [a["name"] for a in pulse["attention"]] == ["Test plug"] and pulse["attention"][0]["level"] == "urgent"


def test_api_adds_a_live_device_and_rejects_a_bad_address():
    with TestClient(main.create_app()) as c:
        bad = c.post("/devices", json={"name": "X", "category": "network", "address": "nonsense"})
        assert bad.status_code == 400
        ok = c.post("/devices", json={"name": "Router", "category": "network", "address": "192.168.1.1:80"})
        assert ok.status_code == 200 and ok.json()["behavior"] == "live"


def test_check_device_tool_rejects_simulated_devices(sample_home):
    import mcp_server
    result = mcp_server.check_device("front_lock")
    assert result["status"] == "REJECTED" and "simulated" in result["reason"]
    live = core.load_home()
    add_live(live, "127.0.0.1:9")
    core.save_home(live)
    started = mcp_server.check_device("test_plug")
    assert started["status"] == "PENDING" and started["command_id"].startswith("cmd_")
