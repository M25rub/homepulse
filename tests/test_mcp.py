"""Talks to a REAL running server with the official MCP client, the same way Alexa+ or the MCP Inspector would."""
import asyncio
import socket
import threading
import time

import httpx
import httpx2
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

import main

TOKEN = "homepulse-demo-token"


@pytest.fixture
def server(sample_home):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    config = uvicorn.Config(main.create_app(), host="127.0.0.1", port=port, log_level="warning")
    srv = uvicorn.Server(config)
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    thread.join(timeout=5)


def run_with_session(url, work, token=TOKEN):
    async def go():
        async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}) as http:
            async with streamable_http_client(url + "/mcp", http_client=http) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    return await work(session)
    return asyncio.run(go())


def data(result):
    assert not result.is_error, result
    return result.structured_content or __import__("json").loads(result.content[0].text)


def test_missing_or_wrong_token_gets_401(server):
    assert httpx.post(server + "/mcp", json={}).status_code == 401
    assert httpx.post(server + "/mcp", json={}, headers={"Authorization": "Bearer nope"}).status_code == 401


def test_tools_are_listed(server):
    async def work(s):
        return {t.name for t in (await s.list_tools()).tools}
    names = run_with_session(server, work)
    assert {"set_device_state", "run_routine", "get_command_status", "get_home_pulse", "list_devices"} <= names


def test_set_state_returns_pending_fast_then_verified(server):
    async def work(s):
        t0 = time.perf_counter()
        first = data(await s.call_tool("set_device_state", {"device_id": "front_lock", "capability": "lock", "value": "locked"}))
        ms = (time.perf_counter() - t0) * 1000
        assert first["status"] == "PENDING" and first["command_id"].startswith("cmd_")
        assert "get_command_status" in first["next_action"]
        for _ in range(100):
            final = data(await s.call_tool("get_command_status", {"command_id": first["command_id"]}))
            if final["status"] != "PENDING":
                return ms, final
            await asyncio.sleep(0.05)
        raise AssertionError("never finished")
    ms, final = run_with_session(server, work)
    assert ms < 500, f"PENDING answer took {ms:.0f} ms"
    assert final["status"] == "VERIFIED" and final["steps"][0]["reported"] == "locked"


def test_offline_device_is_never_called_verified(server):
    async def work(s):
        start = data(await s.call_tool("set_device_state", {"device_id": "garage", "capability": "openclose", "value": "closed"}))
        for _ in range(100):
            final = data(await s.call_tool("get_command_status", {"command_id": start["command_id"]}))
            if final["status"] != "PENDING":
                return final
            await asyncio.sleep(0.05)
    final = run_with_session(server, work)
    assert final["status"] == "FAILED" and "unreachable" in final["explanation"][0]


def test_routine_partial_then_pulse_and_state_persist(server):
    async def work(s):
        start = data(await s.call_tool("run_routine", {"routine_name": "secure_house"}))
        for _ in range(100):
            final = data(await s.call_tool("get_command_status", {"command_id": start["command_id"]}))
            if final["status"] != "PENDING":
                break
            await asyncio.sleep(0.05)
        pulse = data(await s.call_tool("get_home_pulse", {}))
        back_lock = data(await s.call_tool("get_device_state", {"device_id": "back_lock"}))
        return final, pulse, back_lock
    final, pulse, back_lock = run_with_session(server, work)
    assert final["status"] == "PARTIAL"
    assert any(a["name"] == "Garage door" for a in pulse["attention"])
    assert back_lock["reported_state"]["lock"] == "locked"          # recovered by the backup route, and remembered


def test_bad_input_is_rejected_with_help_not_an_error(server):
    async def work(s):
        a = data(await s.call_tool("set_device_state", {"device_id": "nope", "capability": "lock", "value": "locked"}))
        b = data(await s.call_tool("set_device_state", {"device_id": "front_lock", "capability": "lock", "value": "ajar"}))
        c = data(await s.call_tool("get_command_status", {"command_id": "cmd_missing"}))
        return a, b, c
    a, b, c = run_with_session(server, work)
    assert a["status"] == b["status"] == c["status"] == "REJECTED"
    assert "list_devices" in a["hint"]
