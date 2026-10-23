"""Start HomePulse with one command:  python run.py   (on Windows you can also double-click start.bat)

Opens your browser by itself and needs no accounts or keys. Everything runs on your own computer.
If the usual port is busy, it quietly uses the next free one and tells you.
"""
import os
import socket
import sys
import threading
import webbrowser

HOST = os.environ.get("HOMEPULSE_HOST", "127.0.0.1")
WANTED_PORT = int(os.environ.get("HOMEPULSE_PORT", "8000"))
TOKEN = os.environ.get("HOMEPULSE_MCP_TOKEN", "homepulse-demo-token")


def port_is_free(port):
    with socket.socket() as probe:
        try:
            probe.bind((HOST, port))
            return True
        except OSError:
            return False


def pick_port(wanted):
    for port in range(wanted, wanted + 20):
        if port_is_free(port):
            return port
    return None


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import uvicorn
        import main                                   # fails early, with a clear message, if something is not installed
    except ImportError as error:
        print(f"\n  HomePulse needs a few packages first ({error}).")
        print("  Run this once, then start again:   python -m pip install -r requirements.txt\n")
        sys.exit(1)

    port = pick_port(WANTED_PORT)
    if port is None:
        print(f"\n  Ports {WANTED_PORT} to {WANTED_PORT + 19} are all busy. Close other programs, or set HOMEPULSE_PORT.\n")
        sys.exit(1)
    os.environ["HOMEPULSE_PORT"] = str(port)
    print()
    print("  HomePulse is starting.")
    if port != WANTED_PORT:
        print(f"  (Port {WANTED_PORT} was busy, so it is using {port}.)")
    print(f"  Website:     http://{HOST}:{port}")
    print(f"  MCP server:  http://{HOST}:{port}/mcp")
    print(f"  MCP token:   {TOKEN}   (send as: Authorization: Bearer {TOKEN})")
    if TOKEN == "homepulse-demo-token":
        print("  This is the public demo token. Set HOMEPULSE_MCP_TOKEN to use your own.")
    print("  Your browser will open by itself. Stop HomePulse with Ctrl+C.")
    print()
    if os.environ.get("HOMEPULSE_NO_BROWSER") != "1":
        threading.Timer(1.5, lambda: webbrowser.open(f"http://{HOST}:{port}")).start()
    try:
        uvicorn.run(main.app, host=HOST, port=port, log_level="warning")
    except KeyboardInterrupt:
        pass
    print("\n  HomePulse stopped.\n")
