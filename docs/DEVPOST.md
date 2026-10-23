# Devpost text (copy into the form, then edit in your own words)

**Project name:** HomePulse

**Tagline:** Smart-home commands that are checked, not just sent, and a pulse that shows which devices keep letting you down.

## Inspiration
Smart devices sometimes fail quietly: a plug that ignored a command, a lock that never turned. You find out later by accident, and nothing tells you which devices keep failing. For people who rely on locks, heating or caregiving routines, "probably worked" is not good enough.

## What it does
HomePulse sits between an assistant and your devices. It sends a command over the network, asks the device what it now reports, retries, tries a backup address, and explains the result in plain words. It remembers every check, so a Pulse shows a health score, which devices need attention, and which ones fail together (a hint of a shared cause like one room's Wi-Fi).
An MCP server lets an assistant use it. Changing a device returns PENDING immediately (under 500 ms; measured about 12 ms locally) and a second call returns the verified result, so the assistant cannot claim success before it is checked.

## How we built it
Python, FastAPI and the official MCP Python SDK (Streamable HTTP, bearer-token auth). A real check loop (send, read back, retry, backup route) works over real network connections, with adapters for Shelly and Tasmota plug protocols, a network scan (SSDP), one-click real checks of your own router and internet, a background live watch that logs real outages (with false-alarm protection), a simulated Alexa+ that makes real MCP calls, and a protocol-accurate demo plug. The website is plain HTML, CSS and JavaScript in six languages (including right-to-left) with accessibility settings. 70 automated tests, including ones that unplug real local servers, and an axe-core accessibility audit with no violations.

## Challenges
Assistants may forget to ask for a result, so the tool contract guards against it: next-step text in every PENDING answer, server instructions, and helpful REJECTED answers. We also wanted honest demos: the failures you see in the real-device demo are real, not scripted.

## Accomplishments
A working MCP server verified with the official MCP Inspector; real network checks and plug control through documented protocols; a Pulse that turns single checks into a track record; accessibility checked automatically.

## What we learned
Tools that act in the physical world should return PENDING first and a verified answer second. We also learned how fast the MCP SDK is changing (FastMCP became MCPServer in 2.x), and logged it in FEEDBACK.md.

## What is real and what is simulated (please read)
Real: the check/retry/backup logic, the MCP server, the Pulse, live network checks, plug protocol adapters (tested against our demo plug), and the network scan. Simulated: the sample-home devices and the plug hardware. Not done: connection to a real Alexa+ account (not available to participants) and testing on real Shelly/Tasmota hardware.

## What's next
Test the adapters on real plugs; add adapters for more brands (or Home Assistant / Matter); phone and email alerts; a database for many homes.

## Built with
Python, FastAPI, uvicorn, Model Context Protocol (Python SDK), pytest, axe-core, vanilla JavaScript, Jost and Josefin Sans fonts.

## Links to add
GitHub repository (public, MIT licence) | Demo video (YouTube/Vimeo, public, captions) | Product feedback: FEEDBACK.md in the repo

## Product feedback (required)
Answer the form's questions from FEEDBACK.md. Add your own notes about VS Code, Python, FastAPI/Uvicorn, and any Amazon or AWS tool you actually used.
