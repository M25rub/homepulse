# HomePulse

**Smart-home commands that are checked, not just sent, and a pulse that shows which devices keep letting you down.**

When an assistant (such as Alexa+) asks HomePulse to do something, HomePulse:

1. sends the command **over the network**,
2. **asks the device what it now reports** (it never trusts "sent"),
3. retries, then tries a backup address if the first one fails,
4. tells you plainly what happened, and
5. **remembers**, so the Pulse can show a health score, which devices need attention, and which ones fail together (a hint of a shared cause such as one room's Wi-Fi).

It ships as a website (6 languages, including right-to-left, with accessibility settings) **and an MCP server** that an assistant can call.

![The Pulse section](docs/pulse.png)

## Run it (about 2 minutes, no accounts, no API keys)

You need Python 3.10 or newer.

    pip install -r requirements.txt
    python run.py

Open <http://127.0.0.1:8000>. Press **Load a sample home** for a quick look (simulated devices that fail in set ways), then open **Routines**, run **secure_house** a few times, and watch the Pulse on the home page.

## Easy start (no terminal skills needed)

- **Windows:** double-click `start.bat`. It installs what it needs the first time, starts HomePulse and opens your browser.
- **Mac or Linux:** run `start.command`, or `python3 run.py`.
- If the usual port is busy, HomePulse quietly uses the next free one and prints the address. If a package is missing, it says exactly what to run.
- `start.bat` and `start.command` are short scripts that have not been tested on every Windows or Mac setup. `python run.py` is the tested route.

## Live watch: it keeps checking, even when you are not

Once a real device is added (for example by **Check my real network**), HomePulse checks it in the background every 60 seconds and keeps a log of when it stopped answering and when it came back. The Home page shows it under **Live watch**, and an assistant can ask the MCP tool `get_outages` ("did my internet drop today?").

Built to avoid false alarms and survive edge cases: one missed check is not an outage (two in a row are), an outage is dated from the first miss, devices are checked side by side with short timeouts so one dead device cannot slow the rest, a device removed mid-check is handled, a check that errors counts as "no answer", the log is capped and repaired if damaged, and a crash in the watch never takes the app down. Change the timing with `HOMEPULSE_WATCH_SECONDS` (0 turns it off) and `HOMEPULSE_WATCH_CONFIRMS`.

## Real checks in one click (no hardware needed)

On the **Devices** page press **Check my real network**. HomePulse finds your router's address by itself, adds your router and the internet as live devices, and checks both right now over your real network, using a real ping and real connections. Switch your Wi-Fi off, press the button again, and it reports **Needs attention**. Nothing is scripted. If a router blocks ping and every common port, HomePulse says so and shows it as needing attention rather than guessing.

## A simulated Alexa+ that talks over real MCP

Real Alexa+ is not available to participants, so the **Alexa+** page is a simulated assistant. It does not reach into HomePulse's code. It opens a real MCP connection with the same URL and token as any outside assistant, calls a tool, receives **PENDING**, keeps calling `get_command_status`, and only then speaks. What it says is built only from the final answer, so it cannot claim success while a command is pending. The page shows every real MCP call and answer underneath.

## Try it with a real device (no hardware needed)

`demo_plug.py` is a pretend smart plug that speaks the **real Shelly and Tasmota local HTTP protocols**. The hardware is imaginary, but every command HomePulse sends travels over a real network connection, and HomePulse trusts only what the plug answers.

1. Terminal 2: `python demo_plug.py` (add `--flaky` for a plug that ignores every other command)
2. Website, **Devices** > **Add a device**: type **Real device or website**, kind **Shelly plug (Gen1)**, address `http://127.0.0.1:9100`
3. **Routines**: make a routine with that device, **Power on**, and run it. It reports **Confirmed**, and the plug really switched.
4. Press **Ctrl+C** in terminal 2 (you just unplugged it) and run the routine again. HomePulse retries for real, reports **Needs attention**, and the Pulse flags the plug. Nothing here is scripted.

The same adapters (Shelly Gen1, Shelly Gen2 and newer, Tasmota) are written from the manufacturers' public documentation, so they should work with real plugs on your network. **They have not been tested on real hardware.**

Other real addresses work too: choose "Just check that it answers" and enter any web address, `host:port`, or `ping://address` (a router, a Raspberry Pi, a web page). HomePulse checks it for real and the Pulse tracks it.

**Scan my network** (Devices page) really asks your network who is there, using SSDP/UPnP, and lets you add what answers. It only finds devices that speak UPnP on your own network, and a firewall or guest Wi-Fi can block it.

## The MCP server

Endpoint: `http://127.0.0.1:8000/mcp` (Streamable HTTP)
Auth: `Authorization: Bearer homepulse-demo-token` (set your own with `HOMEPULSE_MCP_TOKEN`). Requests without it get **401**.

| Tool | What it does |
|---|---|
| `get_outages` | what went offline in the last hours and what is offline now (from the live watch) |
| `list_devices`, `get_device_state` | what is in the home, what each device last reported, and whether it is live or simulated |
| `set_device_state` | ask for a change. Returns **PENDING + `command_id` immediately** |
| `check_device` | really check whether a live device answers on the network. Also PENDING + `command_id` |
| `run_routine` | run a saved group of changes. Also PENDING + `command_id` |
| `get_command_status` | the verified answer: `PENDING`, `VERIFIED`, `PARTIAL` or `FAILED`, with a plain-language explanation and every attempt |
| `list_routines` | saved routines |
| `get_home_pulse` | 0-100 health score, devices needing attention and why, groups failing together |
| `get_device_history` | one device's track record |

**Why two steps?** Checking a device takes longer than the half second an assistant will wait. So the change runs in the background and the assistant asks for the result. Language models can forget to ask, so the server tells them: every PENDING answer carries a `next_action` sentence, the server `instructions` say "never claim success while PENDING", and bad input returns a `REJECTED` answer with a hint instead of an error.

**Try it with the official MCP Inspector** (needs Node.js):

    npx @modelcontextprotocol/inspector

Choose **Add Servers > Add manually**, Transport **Streamable HTTP**, URL `http://127.0.0.1:8000/mcp`. In the server's **Settings > Custom Headers** add `Authorization` = `Bearer homepulse-demo-token`, then connect. A captured run is in [docs/mcp-inspector-proof.md](docs/mcp-inspector-proof.md).

**Measured response times** (localhost, 40 calls each, `python tests/measure_latency.py`): median about 11-13 ms and worst case under 50 ms for every tool. Over the internet you add your network time.

## What is real and what is simulated

| | Status |
|---|---|
| Check, retry, backup-address and verification logic | Real, and covered by tests |
| MCP server (Streamable HTTP, bearer auth, async contract) | Real, tested with the official MCP client and the Inspector |
| The Pulse (score, attention list, grouping) | Real, computed from recorded checks |
| Safe saving (atomic write, backup, recovery from a damaged file) | Real, tested |
| Live reachability checks of any network address | **Real** network connections |
| Plug control and status (Shelly, Tasmota protocols) | **Real protocol over real network connections**, tested against the included demo plug. **Not tested on real plugs** |
| "Check my real network" (router and internet) | **Real** ping and connections from your computer. The router is found from your computer's routing table |
| Live watch (background checks, outage log) | **Real** checks of real addresses. Simulated sample devices are not watched |
| The Alexa+ page | A **simulated assistant**, but every request is a **real MCP call** to this server |
| Network scan (SSDP/UPnP) | **Real**, tested against a fake responder on localhost. Results depend on your network |
| The sample-home devices | **Simulated**: each one misbehaves in a set way so you can watch recovery |
| Connection to a real Alexa+ account | **Not done.** Alexa+ tools are not available to participants. The server follows the MCP spec, so any MCP client can use it |
| Alexa device-discovery import (Devices page, "For developers") | Reads Alexa's discovery JSON format; tested only with sample JSON |

## Accessibility

- Settings page: text size (4 levels), high-contrast mode, reduced motion, read-aloud and voice input (browser speech features; quality depends on the browser and installed voices).
- Full keyboard use, visible focus, skip link, live-region announcements, touch targets of 44 px or more.
- Six languages: English, Urdu, Arabic, Hindi, Spanish and French, with right-to-left layout for Urdu and Arabic.
- **Checked** with the axe-core automated audit (WCAG 2.0/2.1 A and AA plus best practices): no violations on any of the 7 pages, in normal and high-contrast modes, on desktop and phone widths.
- **Not checked:** testing with a real screen reader (NVDA, VoiceOver) or with real users. Automated tools find only part of the problems, so treat this as a good start, not a guarantee. Translations were written by an AI model and have not been reviewed by native speakers.

## Honest limits

- HomePulse reads on/off from plugs that speak the Shelly or Tasmota protocols. For other devices it can only check that they answer. Other brands each need their own adapter.
- A live reachability check says an address answers. It does not know whether a light is lit.
- Live checks reach out from the machine running HomePulse, so only add addresses you are happy for it to contact.
- Device states change only through the MCP tools and the live-device checks. The website's "Run" buttons on the simulated sample home are a demo and do not keep their states.
- The built-in helper on the website is a keyword helper, not an AI model. It does read the real Pulse.
- One process owns `home.json`. Many users or many servers would need a real database.
- The demo token is public. Do not expose this server to the internet with it.
- Tested on Python 3.13 (Linux) and run by hand on Python 3.14 (Windows). Dependency versions are pinned in `requirements.txt`.

## Project layout

    core.py          the brain: devices, verification, retry/backup route, the pulse, safe saving
    adapters.py      how HomePulse talks to Shelly and Tasmota plugs
    discovery.py     real network scan (SSDP)
    netinfo.py       finds your router and sets up the real network check
    watcher.py       the live watch: background checks and the outage log
    alexa_sim.py     the simulated Alexa+ (a real MCP client)
    demo_plug.py     a pretend plug that speaks the real protocols
    commands.py      runs commands in the background and remembers answers (PENDING -> final)
    mcp_server.py    the MCP tools
    main.py          the website's API, the /mcp endpoint and its bearer-token check
    run.py           one-command start (opens the browser, handles a busy port)
    start.bat        Windows: double-click to start
    web/             the website (plain HTML, CSS and JavaScript, 6 languages, self-hosted fonts)
    tests/           pytest suite (70 tests), including ones that unplug real local servers

## Tests

    pip install -r requirements-dev.txt
    python -m pytest -q

Settings you can change: `HOMEPULSE_MCP_TOKEN`, `HOMEPULSE_PORT`, `HOMEPULSE_DATA` (where the home file lives), `HOMEPULSE_ALLOWED_HOSTS` (host names allowed when you expose it through a tunnel), `HOMEPULSE_LATENCY_MS` (simulated network delay per attempt on the sample home, default 150).

## Licence

MIT, see [LICENSE](LICENSE). Fonts (Jost, Josefin Sans) are under the SIL Open Font License, see `web/fonts/`. Product feedback on the tools used is in [FEEDBACK.md](FEEDBACK.md).
