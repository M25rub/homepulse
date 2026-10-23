# Product feedback (HomePulse)

This covers every tool, API and SDK actually used to build HomePulse. HomePulse was built with the help of an AI coding assistant (Claude Code); where a note describes something that happened on my Windows laptop, I ran it myself, and where it describes tests or audits, they were run in a Linux sandbox by the assistant and I checked the results.

**Not used (so no feedback to give):** Alexa+, the Alexa Developer Console, and AWS services. Alexa+ tools were not available to me. The "Alexa+" page in HomePulse is a simulated assistant that makes real MCP calls. See the feature request at the end.

---

## MCP Python SDK (`mcp` 2.3.0)
1. **Used for:** the HomePulse MCP server (Streamable HTTP, 9 tools) and, in tests and the simulated Alexa+ page, the MCP client.
2. **Worked well:** a tool is a typed Python function, and the input schemas and structured output came out correctly with no extra code. Real-server tests with the official client were short to write.
3. **Needs work:**
   - `pip install mcp` now installs 2.x, where `FastMCP` was renamed `MCPServer` (`from mcp.server.mcpserver import MCPServer`). Most tutorials still use `FastMCP`, so a beginner's first result is a `ModuleNotFoundError`. The error does explain the rename.
   - A `StreamableHTTPSessionManager` can only be run once per instance. Mounting the MCP app inside FastAPI and starting the app in more than one test failed with a ".run() can only be called once" error until I built a fresh server per app. A sentence in the docs would save time.
   - Unknown Host headers get `421 Invalid Host header` (DNS-rebinding protection). A good default, but `TransportSecuritySettings` is easy to miss.
   - There was no short example of a static bearer token on a Streamable HTTP server, so I wrote a small wrapper around the endpoint.
   - The 2.x client takes an `httpx2` client (`streamable_http_client(url, http_client=httpx2.AsyncClient(...))`), while many examples use `httpx`.
4. **Onboarding:** about 20 minutes to a working server, most of it the rename and the FastAPI mount lifespan.
5. **Build with it again?** Yes. The tool and schema model is a good fit for "ask, then verify" workflows.

## MCP Inspector (`@modelcontextprotocol/inspector`, CLI and v2.12.0 browser UI)
1. **Used for:** listing tools and calling them against the running server, to prove the MCP server works with an independent client.
2. **Worked well:** `--cli` mode is scriptable, so the proof run could be repeated. Once configured, the browser UI showed the tools list and results clearly.
3. **Needs work:**
   - On Windows PowerShell, `npx` was blocked by the script execution policy (`npx.ps1 cannot be loaded`). Using `npx.cmd` fixed it, but a beginner would not know that.
   - In v2.12.0 the first screen is a server list. Adding my own server needed **Add Servers > Add manually**, and the bearer-token header was only reachable under **Settings > Custom Headers**. Neither is obvious.
   - In CLI mode the header must be passed as exactly `--header "Authorization: Bearer ..."`, which took a few tries.
   - It needs Node.js, an extra install for a Python project.
4. **Onboarding:** a few minutes for the CLI once Node.js was installed; about 20 minutes for the browser UI because of the two points above.
5. **Build with it again?** Yes. It is the quickest independent check that a server speaks MCP.

## FastAPI and Uvicorn
1. **Used for:** the web API and the static website, with the MCP endpoint mounted inside the same app.
2. **Worked well:** typed request models and automatic validation; `uvicorn` starts with one line; the app factory pattern made tests easy.
3. **Needs work:** combining a FastAPI lifespan with another app's lifespan (the MCP session manager) is not obvious and needed trial and error.
4. **Onboarding:** minutes for a hello-world; about an hour for the lifespan and mounting details.
5. **Build with it again?** Yes.

## Python (3.13 in the sandbox, 3.14 on my Windows laptop) and pytest
1. **Used for:** the whole backend (checks, retries, network watch, router discovery) and 70 automated tests.
2. **Worked well:** the standard library was enough for HTTP checks, TCP checks, SSDP and subprocess pings, so the project has only three runtime packages. pytest fixtures made it easy to give each test its own home file and to start real local servers and unplug them.
3. **Needs work:** `pip` warns that it is out of date and on some systems needs `--break-system-packages`, which confuses beginners.
4. **Onboarding:** quick. Installing the requirements and starting with `python run.py` worked on the first try on Windows.
5. **Build with it again?** Yes.

## Visual Studio Code
1. **Used for:** editing and running the project on Windows.
2. **Worked well:** the integrated terminal made running the server and the scripts simple.
3. **Needs work:** many terminals pile up quickly, and it is easy to lose track of which one is running the server (I had to close them all at one point).
4. **Onboarding:** minutes.
5. **Build with it again?** Yes.

## axe-core and Playwright
1. **Used for:** an automated accessibility audit (axe-core in a Chromium browser driven by Playwright) and screenshots at desktop and phone widths.
2. **Worked well:** axe found real problems I had missed (low-contrast text, a skipped heading level), each with the exact element, and re-running confirmed the fix.
3. **Needs work:** an automated audit cannot test with a real screen reader or real users, so the README says so rather than claiming full accessibility.
4. **Onboarding:** a few minutes once the browser was available.
5. **Build with it again?** Yes.

## Shelly and Tasmota public device documentation
1. **Used for:** writing the smart-plug adapters (Shelly Gen1, Gen2 and newer, Tasmota) from the manufacturers' published HTTP APIs.
2. **Worked well:** the local HTTP APIs are simple, and a pretend plug could speak the same protocol for testing.
3. **Needs work:** Gen1 and Gen2 use different APIs (REST `/relay/0` versus RPC `/rpc/Switch.Set`), and the docs for each live in separate places, so it is easy to read the wrong one. I corrected my own first version against the docs. The adapters are **not tested on real hardware**.
4. **Onboarding:** about an hour for three adapters.
5. **Build with it again?** Yes, but I would test on a real plug first.

---

## Friction log (optional entries)
1. **FastMCP renamed to MCPServer in `mcp` 2.x** (`ModuleNotFoundError`). Cause: tutorials target 1.x. Fix: `from mcp.server.mcpserver import MCPServer`.
2. **"`.run()` can only be called once per instance"** when an app that includes the MCP app was started twice (tests). Fix: build a new server for each app.
3. **`421 Invalid Host header`** from the transport security check when calling through a host name not on the allowlist. Fix: `TransportSecuritySettings(allowed_hosts=[...])`.
4. **`npx.ps1 cannot be loaded because running scripts is disabled`** on Windows PowerShell. Fix: run `npx.cmd`.
5. **Inspector v2.12.0:** no obvious way to add a server with a custom auth header. Fix: Add Servers > Add manually, then Settings > Custom Headers.
6. **`httpx` versus `httpx2`** for the 2.x client: examples using `httpx` failed until I passed an `httpx2` client.

## Feature request
A local Alexa+ simulator or sandbox that can call an MCP server over HTTP would let participants test the full assistant-to-tool flow before access to real Alexa+ is available. I built a small simulator for HomePulse (`alexa_sim.py`) because none was available.
