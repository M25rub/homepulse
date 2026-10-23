"""Real network discovery: ask the local network who is there, using SSDP (UPnP).

TVs, speakers, routers, media boxes, many hubs and some smart plugs answer this. It finds only devices
that answer SSDP and are on the same network as the computer running HomePulse. A firewall can block it.
"""
import socket
import time
import urllib.request
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

SSDP_ADDRESS = ("239.255.255.250", 1900)
MESSAGE = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\n"
           "MX: 1\r\nST: ssdp:all\r\n\r\n").encode()
MAX_DEVICES = 25


def _headers(data):
    lines = data.decode("utf-8", "replace").split("\r\n")
    out = {}
    for line in lines[1:]:
        if ":" in line:
            key, _, value = line.partition(":")
            out[key.strip().lower()] = value.strip()
    return out


def _describe(location, timeout=1.0):
    """Read the device's own description (name, maker, model). Best effort."""
    try:
        with urllib.request.urlopen(urllib.request.Request(location, headers={"User-Agent": "HomePulse/1.0"}), timeout=timeout) as r:
            root = ET.fromstring(r.read(100_000))
    except Exception:
        return {}
    info = {}
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag in ("friendlyName", "manufacturer", "modelName") and tag not in info and element.text:
            info[tag] = element.text.strip()[:80]
    return info


def scan(timeout=2.5, target=SSDP_ADDRESS, describe=True):
    """Returns {"devices": [...], "note": str}. Each device: name, address (a URL HomePulse can check), ip, maker, model."""
    found = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.settimeout(0.3)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        for _ in range(2):
            sock.sendto(MESSAGE, target)
        end = time.time() + timeout
        while time.time() < end:
            try:
                data, (ip, _port) = sock.recvfrom(65507)
            except socket.timeout:
                continue
            headers = _headers(data)
            location = headers.get("location", "")
            if not location.lower().startswith(("http://", "https://")):
                continue
            found.setdefault(location, {"location": location, "ip": ip, "server": headers.get("server", "")})
    except OSError as error:
        return {"devices": [], "note": f"Could not scan the network: {error}"}
    finally:
        sock.close()

    devices = []
    for item in list(found.values())[:MAX_DEVICES]:
        info = _describe(item["location"]) if describe else {}
        host = urlparse(item["location"])
        devices.append({
            "name": info.get("friendlyName") or item["server"].split(" ")[0] or item["ip"],
            "address": f"{host.scheme}://{host.netloc}/",      # the device's own web address, which HomePulse can check
            "ip": item["ip"], "maker": info.get("manufacturer", ""), "model": info.get("modelName", ""),
        })
    seen, unique = set(), []
    for d in devices:                                           # one row per device, not per service
        if d["address"] not in seen:
            seen.add(d["address"])
            unique.append(d)
    note = "" if unique else ("No devices answered. Your firewall, Wi-Fi or router may block discovery "
                              "(guest networks often do), or nothing on this network speaks UPnP.")
    return {"devices": unique, "note": note}
