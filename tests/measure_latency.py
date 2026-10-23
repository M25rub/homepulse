"""Measure how fast each MCP tool answers over real HTTP (Alexa+ asks for under 500 ms).
Run:  python tests/measure_latency.py"""
import asyncio, os, socket, statistics, sys, tempfile, threading, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["HOMEPULSE_DATA"] = tempfile.mkdtemp() + "/home.json"
import httpx2, uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
import core, main

home = core.load_home(); core.load_sample(home); core.save_home(home)
with socket.socket() as s:
    s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
srv = uvicorn.Server(uvicorn.Config(main.create_app(), host="127.0.0.1", port=port, log_level="error"))
threading.Thread(target=srv.run, daemon=True).start()
while not srv.started: time.sleep(0.05)

async def go():
    times = {}
    async with httpx2.AsyncClient(headers={"Authorization": "Bearer homepulse-demo-token"}) as http:
        async with streamable_http_client(f"http://127.0.0.1:{port}/mcp", http_client=http) as st:
            async with ClientSession(st[0], st[1]) as s:
                await s.initialize()
                async def timed(name, args):
                    t = time.perf_counter(); r = await s.call_tool(name, args)
                    times.setdefault(name, []).append((time.perf_counter() - t) * 1000); return r
                for _ in range(40):
                    r = await timed("set_device_state", {"device_id": "kitchen_light", "capability": "power", "value": "off"})
                    cid = (r.structured_content or {}).get("command_id")
                    await timed("get_command_status", {"command_id": cid})
                    await timed("list_devices", {})
                    await timed("get_home_pulse", {})
    for name, v in times.items():
        v.sort()
        print(f"{name:20s} n={len(v):3d}  median {statistics.median(v):6.1f} ms   p95 {v[int(len(v)*.95)-1]:6.1f} ms   max {v[-1]:6.1f} ms")
asyncio.run(go())
