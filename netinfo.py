"""Find the things on YOUR network that are worth checking, with no typing.

default_gateway()  the address of your router (the box your Wi-Fi comes from)
quickstart_plan()  the real devices HomePulse can watch on any computer: your router and the internet
"""
import re
import subprocess
import sys

import core

IPV4 = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")

# What we try, in order, to find a way to talk to the router. Many routers answer ping but not web pages.
ROUTER_PORTS = (80, 443, 53, 8080, 22)
INTERNET_CHOICES = ("https://www.google.com", "https://www.cloudflare.com", "1.1.1.1:443")


def _run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=4).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _from_windows(text):
    """'route print' lists '0.0.0.0  0.0.0.0  <gateway>  <my address>  <metric>'. The same on every language."""
    best = None
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0] == "0.0.0.0" and parts[1] == "0.0.0.0" and IPV4.match(parts[2]):
            metric = int(parts[4]) if parts[4].isdigit() else 9999
            if best is None or metric < best[0]:
                best = (metric, parts[2])
    return best[1] if best else None


def _from_linux_route_table(text):
    """/proc/net/route: the default route has destination 00000000; the gateway is little-endian hex."""
    for line in text.splitlines()[1:]:
        cols = line.split()
        if len(cols) > 2 and cols[1] == "00000000":
            raw = bytes.fromhex(cols[2])[::-1]
            return ".".join(str(b) for b in raw)
    return None


def _from_mac(text):
    match = re.search(r"gateway:\s*(\d{1,3}(?:\.\d{1,3}){3})", text)
    return match.group(1) if match else None


def default_gateway():
    """The router's address, or None if it can't be found."""
    try:
        if sys.platform.startswith("win"):
            return _from_windows(_run(["route", "print", "-4", "0.0.0.0"]))
        if sys.platform == "darwin":
            return _from_mac(_run(["route", "-n", "get", "default"]))
        with open("/proc/net/route") as handle:
            return _from_linux_route_table(handle.read())
    except Exception:
        return None


def _first_that_answers(choices):
    for choice in choices:
        if core.probe(choice):
            return choice
    return None


def quickstart_plan():
    """What to add. Each item: {name, address, room, answers} where answers says whether it replied right now."""
    plan = []
    gateway = default_gateway()
    note = ""
    if gateway:
        ways = ["ping://" + gateway] + [f"{gateway}:{p}" for p in ROUTER_PORTS]
        found = _first_that_answers(ways)
        plan.append({"name": "My router", "address": found or ways[0], "answers": bool(found), "kind": "router"})
        if not found:
            note = ("Your router did not answer a ping or any common port just now. It may block them. "
                    "It was added anyway, so you will see it as needing attention.")
    else:
        note = "I could not find your router's address automatically. You can add it by hand with Add a device."
    found = _first_that_answers(INTERNET_CHOICES)
    plan.append({"name": "The internet", "address": found or INTERNET_CHOICES[0], "answers": bool(found), "kind": "internet"})
    return plan, note
