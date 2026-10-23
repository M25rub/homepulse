"""A simulated Alexa+ that talks to HomePulse the way the real one would: over MCP.

Nothing here reaches into HomePulse directly. It opens a real MCP connection (same URL and token as any
outside assistant), calls a tool, and follows the two-step contract: a change returns PENDING at once, and
only get_command_status can say VERIFIED. What it "says" is built ONLY from the final tool answer, so it
can never claim success while a command is still PENDING.
"""
import asyncio
import json
import time

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

TOOLS = {"set_device_state", "check_device", "run_routine", "get_home_pulse", "list_devices", "list_routines", "get_outages"}
MAX_POLLS = 20


def says(tool, final):
    """The sentence Alexa+ would speak, based only on the last answer HomePulse gave."""
    status = final.get("status")
    if status == "REJECTED":
        hint = final.get("hint") or ""
        if final.get("valid_capabilities"):
            hint = "That device can do: " + ", ".join(final["valid_capabilities"]) + "."
        if final.get("available"):
            hint = "Routines I know: " + ", ".join(final["available"]) + "."
        return ("I can't do that. " + final.get("reason", "") + " " + hint).strip()
    if status == "PENDING":
        return "I'm still checking. I won't say it's done until the device confirms it."
    if status == "VERIFIED":
        return "Done, and the device confirmed it. " + final.get("summary", "")
    if status in ("PARTIAL", "FAILED"):
        why = " ".join(final.get("explanation", [])[:3])
        lead = "Only some of that worked." if status == "PARTIAL" else "That did not work."
        return f"{lead} {final.get('summary', '')} {why}".strip()
    if tool == "get_home_pulse":
        return f"Your home's health score is {final.get('score')}. {final.get('headline', '')}".strip()
    if tool == "get_outages":
        return final.get("summary", "I could not read the outage log.")
    if tool == "list_devices":
        return f"I found {final.get('count', 0)} devices."
    if tool == "list_routines":
        names = [r["name"] for r in final.get("routines", [])]
        return "Your routines are: " + (", ".join(names) if names else "none yet") + "."
    return "Done."


def _data(result):
    if result.structured_content:
        return result.structured_content
    return json.loads(result.content[0].text)


async def run(url, token, tool, arguments):
    """Call one MCP tool, then keep asking get_command_status until the answer is final.
    Returns {"trace": [every real MCP call and answer], "says": ..., "final_status": ...}."""
    if tool not in TOOLS:
        raise ValueError("Unknown tool. Choose one of: " + ", ".join(sorted(TOOLS)))
    trace = []
    async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=20) as http:
        async with streamable_http_client(url, http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()

                async def call(name, args):
                    started = time.perf_counter()
                    result = await session.call_tool(name, args)
                    data = _data(result)
                    trace.append({"tool": name, "arguments": args, "response": data,
                                  "ms": round((time.perf_counter() - started) * 1000)})
                    return data

                final = await call(tool, arguments or {})
                if final.get("status") == "PENDING" and final.get("command_id"):
                    for _ in range(MAX_POLLS):
                        await asyncio.sleep(max(final.get("retry_after_ms", 500), 100) / 1000)
                        final = await call("get_command_status", {"command_id": trace[0]["response"]["command_id"]})
                        if final.get("status") != "PENDING":
                            break
    return {"trace": trace, "says": says(tool, final), "final_status": final.get("status", "OK")}
