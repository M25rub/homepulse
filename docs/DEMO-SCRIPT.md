# 3-minute demo video: script and checklist

**Rules to meet:** under 3:00, English, public on YouTube or Vimeo, captions on, no third-party logos or copyrighted music. Say what is real and what is simulated.

**Before you record (5 min):** close other windows. Three terminals in the `homepulse` folder: (1) `python run.py`, (2) ready to run `python demo_plug.py`, (3) the Inspector (`npx.cmd @modelcontextprotocol/inspector`), already connected. Website open at http://127.0.0.1:8000 with a fresh `home.json` (delete the file, restart). Browser zoom 110-125% so text is readable. Do one full practice run first.

**Recording on Windows:** press `Win + Alt + R` (Xbox Game Bar) or use OBS Studio. Speak slowly. Re-record a bad part instead of editing.

| Time | On screen | Say (in your own words) |
|---|---|---|
| 0:00 | Home page hero | "Smart devices fail quietly. A plug that ignored a command, a lock that never turned. You find out later, and nothing tells you which devices keep failing. This is HomePulse." |
| 0:15 | Load a sample home, run secure_house twice from Routines, then the Pulse on the home page | "HomePulse checks that every command really happened, retries, tries a backup route, and keeps a record. This Pulse shows a health score and which devices need attention." |
| 0:45 | Terminal 2: `python demo_plug.py`. Devices > Add a device > Real device > Shelly plug (Gen1) > `http://127.0.0.1:9100` | "Now a real network device. This plug speaks the real Shelly protocol. The hardware is pretend, but everything travels over a real network connection." |
| 1:10 | Routines: new routine, Desk plug, Power on, run. Show **Confirmed** | "HomePulse sent the command, then asked the plug what it reports. Confirmed." |
| 1:25 | Terminal 2: **Ctrl+C**. Run the routine again. Show **Needs attention**, then the Pulse | "I just unplugged it. HomePulse retried, got no answer, and says so plainly. It does not pretend. The Pulse flags it." |
| 1:50 | Inspector > Tools > `set_device_state` (back_lock, lock, locked) > show PENDING, then `get_command_status` > VERIFIED | "Assistants talk to HomePulse through an MCP server. The change returns PENDING at once, within half a second, and a second call returns the verified answer." |
| 2:15 | Inspector > `get_home_pulse` | "An assistant can also ask for the home's pulse." |
| 2:25 | Settings: switch language to Urdu (right-to-left), raise text size, turn on high contrast | "It works in six languages, including right-to-left, with text size, high contrast, reduced motion and read-aloud." |
| 2:40 | README table "What is real and what is simulated" | "To be clear: the sample home and the plug hardware are simulated. The network checks, protocol and MCP server are real. It is not connected to a real Alexa+ account. Code and tests are on GitHub. Thank you." |

**Captions:** upload to YouTube, open YouTube Studio > Subtitles, and fix the auto-generated English captions.
