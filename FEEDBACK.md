# Product feedback log (HomePulse)

Devpost requires structured feedback for EVERY tool, API or SDK we use.
For each one, answer these five things in your own words. Be specific and
name the exact tool. "The docs were confusing" helps nobody; "the Alexa
Developer Console did not say where to find X" does.

Write notes the moment something happens. It is much easier than remembering later.

1. What I used it for
2. What worked well
3. What needs work
4. Onboarding: how long from zero to "hello world", and what slowed me down
5. Would I build with it again, and why

---

## Visual Studio Code
1. Used for: editing the HomePulse code.
2. Worked well:
3. Needs work:
4. Onboarding (zero to hello world):
5. Build with it again?

## Python
1. Used for: the reliability engine (sending commands, checking results, retrying).
2. Worked well:
3. Needs work:
4. Onboarding (zero to hello world):
5. Build with it again?

## FastAPI and Uvicorn
1. Used for: the local server behind the website.
2. Worked well:
3. Needs work:
4. Onboarding (zero to hello world):
5. Build with it again?

## AWS (account creation so far)
1. Used for: (fill in as we add services: hosting, database, alerts)
2. Worked well:
3. Needs work:
4. Onboarding (zero to hello world):
5. Build with it again?

## Amazon Developer account / Alexa Developer Console
1. Used for: (fill in when we build the Alexa+ connection)
2. Worked well:
3. Needs work:
4. Onboarding (zero to hello world):
5. Build with it again?

## Alexa+ (the track tool): add its own section the day we start using it
1. Used for:
2. Worked well:
3. Needs work:
4. Onboarding (zero to hello world):
5. Build with it again?

---

## MCP Python SDK (`mcp` 2.3.0)  [notes written while building]
1. Used for: the HomePulse MCP server (Streamable HTTP) with 8 tools.
2. Worked well: adding a tool is just a typed Python function; input schemas and structured output came out correctly without extra code. The in-process client made real-server tests short. The Inspector CLI connected on the first try.
3. Needs work:
   - `pip install mcp` now installs 2.x, where `FastMCP` was renamed `MCPServer` (`from mcp.server.mcpserver import MCPServer`). Almost every tutorial and example online still uses `from mcp.server.fastmcp import FastMCP`, and the first thing a beginner sees is a `ModuleNotFoundError`. The error message does explain the rename, which helped.
   - A `StreamableHTTPSessionManager` can only be run once per instance, and `streamable_http_app()` creates it. Mounting the MCP app inside FastAPI and writing tests that start the app more than once failed with "`.run()` can only be called once per instance" until I built a fresh server for every app. A sentence in the docs about this would save time.
   - A request with an unknown Host header gets `421 Invalid Host header` (DNS-rebinding protection). It is the right default, but the way to allow your own host names (`TransportSecuritySettings`) is easy to miss.
   - Bearer-token auth: I wrote a small wrapper around the endpoint. A short example of "static bearer token on a Streamable HTTP server" would help people who are not building a full OAuth server.
4. Onboarding (zero to hello world): about 20 minutes, most of it the FastMCP/MCPServer rename and the mount-inside-FastAPI lifespan.
5. Build with it again? Yes.

## MCP Inspector (`@modelcontextprotocol/inspector`)
1. Used for: checking the tool list and calling tools against the running server, and capturing proof.
2. Worked well: `--cli` mode is scriptable, so the proof run can be repeated.
3. Needs work: passing a header in CLI mode needs the exact `--header "Authorization: Bearer ..."` form, which took a try or two to find. It needs Node.js, which is an extra install for a Python project.
4. Onboarding: a few minutes once Node.js is installed.
5. Build with it again? Yes.

## Python: pytest, FastAPI/Starlette test client, uvicorn
1. Used for: tests, including one that starts a real uvicorn server on a free port and talks to it with the MCP client.
2. Worked well: `TestClient` for the REST API; running `uvicorn.Server` in a thread for the real-server test.
3. Needs work: `TestClient` starts the app's lifespan each time, which is what triggered the MCP session-manager error above.
