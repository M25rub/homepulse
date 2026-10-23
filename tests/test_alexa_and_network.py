"""The simulated Alexa+ (real MCP calls), ping checks, router finding and the one-click network check."""
import socket
import stat
import threading
import time

import httpx
import pytest
import uvicorn

import core
import main
import netinfo


@pytest.fixture
def server(sample_home):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(main.create_app(), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    thread.join(timeout=5)


def ask(server, tool, **arguments):
    r = httpx.post(server + "/alexa/run", json={"tool": tool, "arguments": arguments}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- simulated Alexa+

def test_alexa_follows_pending_to_verified_over_real_mcp(server):
    out = ask(server, "set_device_state", device_id="front_lock", capability="lock", value="locked")
    tools = [step["tool"] for step in out["trace"]]
    assert tools[0] == "set_device_state" and tools[-1] == "get_command_status"
    assert out["trace"][0]["response"]["status"] == "PENDING"
    assert out["final_status"] == "VERIFIED"
    assert out["says"].startswith("Done")


def test_alexa_never_claims_success_for_an_offline_device(server):
    out = ask(server, "set_device_state", device_id="garage", capability="openclose", value="closed")
    assert out["final_status"] in ("FAILED", "PARTIAL")
    assert "Done" not in out["says"]
    assert "did not work" in out["says"]


def test_alexa_reports_a_rejection_with_the_reason(server):
    out = ask(server, "set_device_state", device_id="front_lock", capability="lock", value="banana")
    assert out["final_status"] == "REJECTED"
    assert out["says"].startswith("I can't do that")
    out = ask(server, "set_device_state", device_id="nope", capability="lock", value="locked")
    assert out["final_status"] == "REJECTED"


def test_alexa_runs_a_routine_and_reads_the_pulse(server):
    out = ask(server, "run_routine", routine_name="secure_house")
    assert out["final_status"] in ("VERIFIED", "PARTIAL", "FAILED")
    pulse = ask(server, "get_home_pulse")
    assert "health score" in pulse["says"]


def test_alexa_rejects_unknown_tools(server):
    r = httpx.post(server + "/alexa/run", json={"tool": "delete_everything", "arguments": {}})
    assert r.status_code == 400


def test_says_is_built_only_from_the_final_answer():
    import alexa_sim
    assert "still checking" in alexa_sim.says("set_device_state", {"status": "PENDING"})
    assert alexa_sim.says("run_routine", {"status": "FAILED", "summary": "S.", "explanation": ["why"]}).startswith("That did not work")


# ---------------------------------------------------------------- ping

def fake_ping(tmp_path, monkeypatch, body):
    script = tmp_path / "ping"
    script.write_text("#!/bin/sh\n" + body + "\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(tmp_path) + ":/usr/bin:/bin")


def test_ping_address_is_validated():
    assert core.valid_address("ping://192.168.1.1") == "ping://192.168.1.1"
    for bad in ("ping://", "ping://-c 5 x", "ping://a b", "ping://;ls"):
        with pytest.raises(ValueError):
            core.valid_address(bad)


def test_ping_counts_only_a_real_reply(tmp_path, monkeypatch):
    fake_ping(tmp_path, monkeypatch, 'echo "64 bytes from 10.0.0.1: icmp_seq=1 ttl=64 time=1.2 ms"')
    assert core.probe("ping://10.0.0.1") is True
    fake_ping(tmp_path, monkeypatch, 'echo "From 10.0.0.9 icmp_seq=1 Destination Host Unreachable"; exit 0')
    assert core.probe("ping://10.0.0.1") is False          # success code but no TTL: not a real reply
    fake_ping(tmp_path, monkeypatch, "exit 1")
    assert core.probe("ping://10.0.0.1") is False


def test_a_ping_device_works_in_a_routine(tmp_path, monkeypatch):
    fake_ping(tmp_path, monkeypatch, 'echo "reply ttl=60"')
    home = core.load_home()
    core.new_device(home, "Router", "network", address="ping://10.0.0.1")
    results, _ = core.run_actions(home, [{"target": {"type": "device", "id": "router"}, "capability": "reachable", "value": "online"}])
    assert results[0]["verified"] is True
    fake_ping(tmp_path, monkeypatch, "exit 1")
    results, _ = core.run_actions(home, [{"target": {"type": "device", "id": "router"}, "capability": "reachable", "value": "online"}])
    assert results[0]["verified"] is False


# ---------------------------------------------------------------- finding the router

def test_gateway_is_read_from_each_platform_format():
    windows = """IPv4 Route Table
Active Routes:
Network Destination        Netmask          Gateway       Interface  Metric
          0.0.0.0          0.0.0.0        10.54.0.1      10.54.15.31     50
          0.0.0.0          0.0.0.0        192.168.0.1    192.168.0.7    600
        127.0.0.0        255.0.0.0         On-link         127.0.0.1    331"""
    assert netinfo._from_windows(windows) == "10.54.0.1"          # the lowest metric wins
    linux = "Iface\tDestination\tGateway\tFlags\nwlan0\t00000000\t0100360A\t0003\nwlan0\t0000360A\t00000000\t0001"
    assert netinfo._from_linux_route_table(linux) == "10.54.0.1"
    assert netinfo._from_mac("route to: default\n    gateway: 192.168.1.1\n  interface: en0") == "192.168.1.1"
    assert netinfo._from_windows("nothing useful") is None


# ---------------------------------------------------------------- one-click network check

def test_quickstart_adds_router_and_internet_and_checks_them(monkeypatch, sample_home):
    monkeypatch.setattr(netinfo, "default_gateway", lambda: "10.0.0.1")
    answering = {"ping://10.0.0.1", "https://www.google.com"}
    monkeypatch.setattr(core, "probe", lambda address, timeout=1.5: address in answering)
    from starlette.testclient import TestClient
    client = TestClient(main.create_app())
    out = client.post("/devices/quickstart").json()
    assert out["added"] == ["My router", "The internet"]
    assert [r["verified"] for r in out["results"]] == [True, True]
    assert "check_my_network" in client.get("/routines").json()
    again = client.post("/devices/quickstart").json()              # a second click does not duplicate anything
    assert again["added"] == []
    assert len([d for d in client.get("/devices").json().values() if d["behavior"] == "live"]) == 2


def test_quickstart_is_honest_when_the_router_stays_silent(monkeypatch, sample_home):
    monkeypatch.setattr(netinfo, "default_gateway", lambda: "10.0.0.1")
    monkeypatch.setattr(core, "probe", lambda address, timeout=1.5: address.startswith("https://www.google"))
    from starlette.testclient import TestClient
    out = TestClient(main.create_app()).post("/devices/quickstart").json()
    assert "did not answer" in out["note"]
    assert [r["verified"] for r in out["results"]] == [False, True]


def test_quickstart_without_a_router_still_checks_the_internet(monkeypatch, sample_home):
    monkeypatch.setattr(netinfo, "default_gateway", lambda: None)
    monkeypatch.setattr(core, "probe", lambda address, timeout=1.5: True)
    from starlette.testclient import TestClient
    out = TestClient(main.create_app()).post("/devices/quickstart").json()
    assert out["added"] == ["The internet"] and "could not find your router" in out["note"].lower()
