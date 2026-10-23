"""Smart plugs over real HTTP (the demo plug speaks the Shelly/Tasmota protocols), network scanning, and the helper."""
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from starlette.testclient import TestClient

import adapters
import commands
import core
import demo_plug
import discovery
import main


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Plug:
    def __init__(self, flaky=False):
        self.port = free_port()
        self.server = demo_plug.make_server(self.port, flaky)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.port}"

    def unplug(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def plug():
    p = Plug()
    yield p
    try:
        p.unplug()
    except Exception:
        pass


@pytest.mark.parametrize("kind", ["shelly_gen1", "shelly_gen2", "tasmota"])
def test_each_protocol_can_read_and_switch_a_plug(plug, kind):
    assert adapters.read_power(kind, plug.url) == "off"
    assert adapters.set_power(kind, plug.url, "on")
    assert adapters.read_power(kind, plug.url) == "on"
    adapters.set_power(kind, plug.url, "off")
    assert adapters.read_power(kind, plug.url) == "off"


def test_reading_a_dead_plug_gives_none_not_a_guess():
    assert adapters.read_power("shelly_gen1", f"http://127.0.0.1:{free_port()}") is None


@pytest.mark.parametrize("kind", ["shelly_gen1", "shelly_gen2", "tasmota"])
def test_homepulse_controls_and_verifies_a_plug_for_real(plug, kind):
    home = core.load_home()
    d = core.new_device(home, "Lamp plug", address=plug.url, adapter=kind)
    assert d["category"] == "plug" and d["adapter"] == kind and "reachable" in d["capabilities"]
    detail = core.verify_detailed(d, "power", "on")
    assert detail["outcome"] == "confirmed" and plug.server.plug.on is True       # the "hardware" really switched


def test_a_flaky_plug_is_recovered_by_a_real_retry():
    p = Plug(flaky=True)
    try:
        d = core.new_device(core.load_home(), "Flaky plug", address=p.url, adapter="shelly_gen1")
        detail = core.verify_detailed(d, "power", "on")
        assert detail["outcome"] == "recovered by retry" and [a["matched"] for a in detail["attempts"]] == [False, True]
    finally:
        p.unplug()


def test_an_unplugged_plug_is_never_reported_as_switched(plug):
    d = core.new_device(core.load_home(), "Lamp plug", address=plug.url, adapter="tasmota")
    plug.unplug()
    detail = core.verify_detailed(d, "power", "on")
    assert detail["outcome"] == core.FAILED_OUTCOME and detail["attempts"][-1]["reported"] == "no answer"
    assert d["state"]["reachable"] == "offline"


def test_backup_address_takes_over_when_the_main_plug_is_dead(plug):
    dead = f"http://127.0.0.1:{free_port()}"
    d = core.new_device(core.load_home(), "Lamp plug", address=dead, fallback_address=plug.url, adapter="shelly_gen2")
    detail = core.verify_detailed(d, "power", "on")
    assert detail["outcome"] == "recovered by local fallback" and plug.server.plug.on is True


def test_whole_flow_over_the_api_and_the_pulse(plug):
    with TestClient(main.create_app()) as c:
        added = c.post("/devices", json={"name": "Desk plug", "room": "Study", "category": "network",
                                         "address": plug.url, "adapter": "shelly_gen1"})
        assert added.status_code == 200, added.text
        ok = c.post("/command", json={"target": {"type": "device", "id": "desk_plug"}, "capability": "power", "value": "on"}).json()
        assert ok["results"][0]["verified"] and plug.server.plug.on is True
        plug.unplug()
        bad = c.post("/command", json={"target": {"type": "device", "id": "desk_plug"}, "capability": "power", "value": "off"}).json()
        assert not bad["results"][0]["verified"] and bad["results"][0]["reported"] == "no answer"
        assert c.get("/devices").json()["desk_plug"]["state"]["reachable"] == "offline"     # silence is recorded, not hidden
        pulse = c.get("/pulse").json()
        assert [a["name"] for a in pulse["attention"]] == ["Desk plug"]
        assert "Desk plug" in c.post("/assistant", json={"message": "what needs attention?"}).json()["reply"]


def test_bad_adapter_requests_are_rejected():
    with TestClient(main.create_app()) as c:
        assert c.post("/devices", json={"name": "X", "category": "network", "address": "127.0.0.1:80", "adapter": "nonsense"}).status_code == 400
        assert c.post("/devices", json={"name": "X", "category": "network", "adapter": "tasmota"}).status_code == 400


def test_set_device_state_tool_really_switches_a_plug(plug):
    import mcp_server
    home = core.load_home()
    core.new_device(home, "Desk plug", address=plug.url, adapter="shelly_gen1")
    core.save_home(home)
    started = mcp_server.set_device_state("desk_plug", "power", "on")
    assert started["status"] == "PENDING"
    final = commands.wait(started["command_id"])
    assert final["status"] == commands.VERIFIED and plug.server.plug.on is True
    assert mcp_server.list_devices()["devices"][0]["kind"].startswith("live")


# ---- network scanning, tested against a fake SSDP responder on localhost

class Description(BaseHTTPRequestHandler):
    def do_GET(self):
        body = (b'<root xmlns="urn:schemas-upnp-org:device-1-0"><device><friendlyName>Living room speaker</friendlyName>'
                b'<manufacturer>Acme</manufacturer><modelName>S1</modelName></device></root>')
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def fake_ssdp_network():
    web = ThreadingHTTPServer(("127.0.0.1", 0), Description)
    threading.Thread(target=web.serve_forever, daemon=True).start()
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.bind(("127.0.0.1", 0))

    def respond():
        while True:
            try:
                data, sender = udp.recvfrom(2048)
            except OSError:
                return
            if b"M-SEARCH" in data:
                for st in ("upnp:rootdevice", "urn:schemas-upnp-org:device:MediaRenderer:1"):     # two services, one device
                    reply = (f"HTTP/1.1 200 OK\r\nLOCATION: http://127.0.0.1:{web.server_port}/desc.xml\r\n"
                             f"SERVER: Linux UPnP/1.0 Acme/1.0\r\nST: {st}\r\n\r\n").encode()
                    udp.sendto(reply, sender)

    threading.Thread(target=respond, daemon=True).start()
    return web, udp


def test_network_scan_finds_a_device_and_names_it():
    web, udp = fake_ssdp_network()
    try:
        result = discovery.scan(timeout=1.2, target=udp.getsockname())
    finally:
        udp.close()
        web.shutdown()
    assert len(result["devices"]) == 1                                  # two services collapse into one device
    d = result["devices"][0]
    assert d["name"] == "Living room speaker" and d["maker"] == "Acme" and d["address"].startswith("http://127.0.0.1:")


def test_scan_with_nothing_answering_says_why():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        result = discovery.scan(timeout=0.8, target=s.getsockname(), describe=False)
    assert result["devices"] == [] and "firewall" in result["note"]


def test_scan_endpoint_marks_devices_already_added(monkeypatch):
    monkeypatch.setattr(discovery, "scan", lambda: {"devices": [{"name": "TV", "address": "http://10.0.0.5:8080/", "ip": "10.0.0.5", "maker": "", "model": ""}], "note": ""})
    with TestClient(main.create_app()) as c:
        assert c.post("/devices/scan").json()["devices"][0]["already_added"] is False
        c.post("/devices", json={"name": "TV", "category": "network", "address": "http://10.0.0.5:8080/"})
        assert c.post("/devices/scan").json()["devices"][0]["already_added"] is True


def test_helper_answers_from_the_pulse(sample_home):
    with TestClient(main.create_app()) as c:
        assert "haven't checked" in c.post("/assistant", json={"message": "how's my home?"}).json()["reply"]
        c.post("/run/secure_house")
        reply = c.post("/assistant", json={"message": "what needs attention?"}).json()["reply"]
        assert "health score" in reply and "Garage door" in reply
