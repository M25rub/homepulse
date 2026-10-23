"""A pretend smart plug that speaks the REAL Shelly (Gen1, Gen2) and Tasmota local HTTP protocols.

The hardware is imaginary, but everything HomePulse does to it travels over a real network connection,
exactly as it would to a real plug.

    python demo_plug.py                 start a plug on port 9100
    python demo_plug.py --port 9200     use another port
    python demo_plug.py --flaky         ignore every other command (shows HomePulse's retry)

Stop it with Ctrl+C: that is "unplugging" it.
"""
import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


class Plug:
    def __init__(self, flaky=False):
        self.on = False
        self.flaky = flaky
        self.commands = 0
        self.lock = threading.Lock()

    def command(self, on):
        """Apply a command. A flaky plug ignores every other one (the 1st, 3rd, 5th ...)."""
        with self.lock:
            self.commands += 1
            if self.flaky and self.commands % 2 == 1:
                return
            self.on = on


def make_server(port=9100, flaky=False, host="127.0.0.1"):
    plug = Plug(flaky)

    class Handler(BaseHTTPRequestHandler):
        def _send(self, body, status=200):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _handle(self, form=None):
            url = urlparse(self.path)
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path == "/relay/0":                                   # Shelly Gen1
                turn = (form or query).get("turn")
                if turn in ("on", "off"):
                    plug.command(turn == "on")
                return self._send({"ison": plug.on, "has_timer": False, "source": "http"})
            if url.path == "/rpc/Switch.GetStatus":                      # Shelly Gen2+
                return self._send({"id": 0, "source": "http", "output": plug.on})
            if url.path == "/rpc/Switch.Set":
                if query.get("on") in ("true", "false"):
                    plug.command(query["on"] == "true")
                return self._send({"was_on": plug.on})
            if url.path == "/cm":                                        # Tasmota
                cmnd = query.get("cmnd", "").strip().lower()
                if cmnd == "power on":
                    plug.command(True)
                elif cmnd == "power off":
                    plug.command(False)
                return self._send({"POWER": "ON" if plug.on else "OFF"})
            self._send({"error": "not found"}, 404)

        def do_GET(self):
            self._handle()

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode()).items()}
            self._handle(form)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer((host, port), Handler)
    server.plug = plug
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="A pretend smart plug that speaks real Shelly/Tasmota protocols")
    parser.add_argument("--port", type=int, default=9100)
    parser.add_argument("--flaky", action="store_true", help="ignore every other command")
    args = parser.parse_args()
    server = make_server(args.port, args.flaky)
    print(f"\n  Demo smart plug running at http://127.0.0.1:{args.port}")
    print("  In HomePulse: Devices > Add a device > Real device or website > Shelly plug (Gen1)")
    print(f"  Address: http://127.0.0.1:{args.port}   {'(flaky: ignores every other command)' if args.flaky else ''}")
    print("  Press Ctrl+C to unplug it.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("  Unplugged.")
