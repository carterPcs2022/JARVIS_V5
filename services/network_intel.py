"""
services/network_intel.py — JARVIS Network Intelligence.

Scans the local network for devices, identifies vendors via MAC OUI,
baselines trusted devices, watches for intruders, and measures internet health.
Uses python-nmap when available, falls back to socket-based scanning.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import psutil
except ImportError:
    psutil = None  # type: ignore

try:
    import nmap  # python-nmap
except ImportError:
    nmap = None  # type: ignore

from core.event_bus import bus
from services.notifications import notify, Priority

log = logging.getLogger(__name__)

_MEMORY_FILE = Path(__file__).parent.parent / "memory" / "network.json"

# Common ports to probe in socket-based scan
_COMMON_PORTS = [22, 80, 443, 3000, 5000, 8000, 8080, 8443]

# OUI Map: first 8 chars of MAC (OUI prefix, upper-cased, colon-separated) → vendor
OUI_MAP: dict[str, str] = {
    # Apple
    "00:03:93": "Apple",
    "00:0A:95": "Apple",
    "00:17:F2": "Apple",
    "00:1C:B3": "Apple",
    "00:23:12": "Apple",
    "00:26:BB": "Apple",
    "3C:07:54": "Apple",
    "A4:B1:97": "Apple",
    "F0:18:98": "Apple",
    # Samsung
    "00:07:AB": "Samsung",
    "00:12:FB": "Samsung",
    "00:15:B9": "Samsung",
    "00:1D:25": "Samsung",
    "04:18:D6": "Samsung",
    "50:85:69": "Samsung",
    # Google
    "00:1A:11": "Google",
    "54:60:09": "Google",
    "F4:F5:D8": "Google",
    "94:EB:2C": "Google",
    # Amazon
    "00:FC:8B": "Amazon",
    "40:B4:CD": "Amazon",
    "44:65:0D": "Amazon",
    "68:37:E9": "Amazon",
    "74:75:48": "Amazon",
    "A0:02:DC": "Amazon",
    "F0:D2:F1": "Amazon",
    # Netgear
    "00:09:5B": "Netgear",
    "00:14:6C": "Netgear",
    "00:1B:2F": "Netgear",
    "20:4E:7F": "Netgear",
    "C0:3F:0E": "Netgear",
    # Cisco
    "00:00:0C": "Cisco",
    "00:01:42": "Cisco",
    "00:0A:B8": "Cisco",
    "00:17:94": "Cisco",
    "58:AC:78": "Cisco",
    "E8:1C:BA": "Cisco",
    # Dell
    "00:06:5B": "Dell",
    "00:14:22": "Dell",
    "18:03:73": "Dell",
    "B0:83:FE": "Dell",
    "F8:DB:88": "Dell",
    # Intel
    "00:02:B3": "Intel",
    "00:AA:00": "Intel",
    "8C:8D:28": "Intel",
    "A0:36:9F": "Intel",
    # Microsoft
    "00:03:FF": "Microsoft",
    "00:12:5A": "Microsoft",
    "28:18:78": "Microsoft",
    "54:27:1E": "Microsoft",
    # Sony
    "00:13:A9": "Sony",
    "00:1A:80": "Sony",
    "30:17:C8": "Sony",
    # LG
    "00:1C:62": "LG",
    "00:1E:75": "LG",
    "88:36:6C": "LG",
    "A8:1B:5A": "LG",
    # Huawei
    "00:18:82": "Huawei",
    "00:E0:FC": "Huawei",
    "28:6E:D4": "Huawei",
    "54:89:98": "Huawei",
    # TP-Link
    "00:27:19": "TP-Link",
    "14:CC:20": "TP-Link",
    "50:C7:BF": "TP-Link",
    "64:70:02": "TP-Link",
    # ASUS
    "00:08:A1": "ASUS",
    "00:E0:18": "ASUS",
    "04:92:26": "ASUS",
    "10:BF:48": "ASUS",
    "50:46:5D": "ASUS",
    # Xiaomi
    "00:9E:C8": "Xiaomi",
    "28:6C:07": "Xiaomi",
    "58:44:98": "Xiaomi",
    "64:09:80": "Xiaomi",
    # Philips
    "00:17:88": "Philips",
    "EC:B5:FA": "Philips",
    # Belkin
    "00:17:3F": "Belkin",
    "00:30:BD": "Belkin",
    "94:10:3E": "Belkin",
    # D-Link
    "00:05:5D": "D-Link",
    "00:17:9A": "D-Link",
    "1C:7E:E5": "D-Link",
    "C8:D3:A3": "D-Link",
    # Ubiquiti
    "00:27:22": "Ubiquiti",
    "04:18:D6": "Ubiquiti",
    "68:72:51": "Ubiquiti",
    "F4:92:BF": "Ubiquiti",
    # Raspberry Pi Foundation
    "B8:27:EB": "Raspberry Pi",
    "DC:A6:32": "Raspberry Pi",
    "E4:5F:01": "Raspberry Pi",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path, default: Any = None) -> Any:
    if default is None:
        default = {}
    if not path.exists():
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)
    except OSError as exc:
        log.error("Failed to save %s: %s", path, exc)


def _local_subnet() -> str:
    """Determine the local /24 subnet (e.g. '192.168.1.0/24')."""
    try:
        # Connect to an external address to find the local IP without actually sending
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
        # Build /24
        parts = local_ip.split(".")
        return f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"
    except Exception:
        return "192.168.1.0/24"


class NetworkIntelligence:
    """Network scanning, device identification, baseline management, and intrusion detection."""

    def __init__(self) -> None:
        _MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._watcher_running = False

    # ── Vendor lookup ─────────────────────────────────────────────────────────

    def identify_device(self, mac: str) -> str:
        """Look up vendor name from MAC address using OUI_MAP."""
        if not mac:
            return "Unknown"
        mac_upper = mac.upper().replace("-", ":").strip()
        # Try full OUI (first 3 octets)
        oui = ":".join(mac_upper.split(":")[:3])
        return OUI_MAP.get(oui, "Unknown")

    # ── Port scan ─────────────────────────────────────────────────────────────

    def port_scan(self, target_ip: str) -> list[int]:
        """
        Socket-based scan of common ports on target_ip.
        Returns list of open port numbers.
        """
        open_ports: list[int] = []
        for port in _COMMON_PORTS:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.5)
                    result = s.connect_ex((target_ip, port))
                    if result == 0:
                        open_ports.append(port)
            except (socket.error, OSError):
                pass
        return open_ports

    # ── Network scan ─────────────────────────────────────────────────────────

    def scan_network(self) -> list[dict]:
        """
        Scan the local /24 subnet.
        Tries python-nmap first, falls back to socket-based host detection.
        Returns list of device dicts.
        """
        devices: list[dict] = []
        subnet = _local_subnet()
        log.info("Scanning network: %s", subnet)

        if nmap:
            try:
                devices = self._nmap_scan(subnet)
                log.info("nmap scan complete: %d devices", len(devices))
                return devices
            except Exception as exc:
                log.warning("nmap failed, falling back to socket scan: %s", exc)

        devices = self._socket_scan(subnet)
        log.info("Socket scan complete: %d devices", len(devices))
        return devices

    def _nmap_scan(self, subnet: str) -> list[dict]:
        nm = nmap.PortScanner()
        nm.scan(hosts=subnet, arguments="-sn --host-timeout 5s")
        devices = []
        existing = self._load_known()
        now = _now()

        for host in nm.all_hosts():
            try:
                hostname = socket.getfqdn(host)
            except Exception:
                hostname = host

            mac = ""
            vendor = "Unknown"
            try:
                if "mac" in nm[host].get("addresses", {}):
                    mac = nm[host]["addresses"]["mac"]
                    vendor = self.identify_device(mac)
                    if vendor == "Unknown":
                        vendor = nm[host].get("vendor", {}).get(mac, "Unknown")
            except (KeyError, AttributeError):
                pass

            open_ports = self.port_scan(host)
            device_type = self._guess_device_type(vendor, open_ports)

            known = existing.get(host, {})
            device = {
                "ip":          host,
                "mac":         mac or known.get("mac", ""),
                "hostname":    hostname,
                "vendor":      vendor,
                "open_ports":  open_ports,
                "device_type": device_type,
                "first_seen":  known.get("first_seen", now),
                "last_seen":   now,
                "trusted":     known.get("trusted", False),
            }
            devices.append(device)

        return devices

    def _socket_scan(self, subnet: str) -> list[dict]:
        """Socket-based fallback: try port 80 on each host in the /24."""
        network = ipaddress.IPv4Network(subnet, strict=False)
        existing = self._load_known()
        now = _now()
        devices = []

        def _probe(ip_str: str) -> dict | None:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.1)
                    if s.connect_ex((ip_str, 80)) == 0 or s.connect_ex((ip_str, 443)) == 0:
                        try:
                            hostname = socket.getfqdn(ip_str)
                        except Exception:
                            hostname = ip_str
                        known = existing.get(ip_str, {})
                        open_ports = self.port_scan(ip_str)
                        return {
                            "ip":          ip_str,
                            "mac":         known.get("mac", ""),
                            "hostname":    hostname,
                            "vendor":      known.get("vendor", "Unknown"),
                            "open_ports":  open_ports,
                            "device_type": self._guess_device_type("Unknown", open_ports),
                            "first_seen":  known.get("first_seen", now),
                            "last_seen":   now,
                            "trusted":     known.get("trusted", False),
                        }
            except (socket.error, OSError):
                pass
            return None

        threads = []
        results: list[dict | None] = [None] * 254

        def worker(idx: int, ip_str: str):
            results[idx] = _probe(ip_str)

        for i, host in enumerate(list(network.hosts())[:254]):
            t = threading.Thread(target=worker, args=(i, str(host)), daemon=True)
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=2)

        devices = [r for r in results if r is not None]

        # Always include current host if missed
        try:
            local_ip = socket.gethostbyname(socket.gethostname())
            if not any(d["ip"] == local_ip for d in devices):
                known = existing.get(local_ip, {})
                devices.append({
                    "ip":          local_ip,
                    "mac":         known.get("mac", ""),
                    "hostname":    socket.gethostname(),
                    "vendor":      "Local",
                    "open_ports":  self.port_scan(local_ip),
                    "device_type": "this-host",
                    "first_seen":  known.get("first_seen", now),
                    "last_seen":   now,
                    "trusted":     True,
                })
        except Exception:
            pass

        return devices

    def _guess_device_type(self, vendor: str, open_ports: list[int]) -> str:
        vendor_l = vendor.lower()
        if any(v in vendor_l for v in ("apple",)):
            return "Apple device"
        if any(v in vendor_l for v in ("raspberry",)):
            return "Raspberry Pi"
        if any(v in vendor_l for v in ("cisco", "ubiquiti", "netgear", "d-link", "tp-link", "asus", "belkin")):
            return "network-equipment"
        if any(v in vendor_l for v in ("amazon",)):
            return "Amazon device"
        if any(v in vendor_l for v in ("samsung", "lg", "sony", "philips")):
            return "consumer-electronics"
        if 22 in open_ports:
            return "server/linux-host"
        if 80 in open_ports or 443 in open_ports:
            return "web-enabled"
        return "unknown"

    # ── Baseline ─────────────────────────────────────────────────────────────

    def _load_known(self) -> dict:
        data = _load_json(_MEMORY_FILE, default={})
        # Support both {devices: [...]} and dict-by-ip formats
        if isinstance(data, dict) and "devices" in data:
            return {d["ip"]: d for d in data.get("devices", []) if "ip" in d}
        if isinstance(data, dict):
            return data
        return {}

    def baseline_network(self) -> dict:
        """Scan and save current network as trusted baseline."""
        devices = self.scan_network()
        for d in devices:
            d["trusted"] = True
        payload = {
            "devices":    devices,
            "baselined":  _now(),
            "subnet":     _local_subnet(),
        }
        _save_json(_MEMORY_FILE, payload)
        bus.publish("network_baselined", {"device_count": len(devices)}, severity="info")
        log.info("Network baseline saved: %d trusted devices", len(devices))
        return payload

    def get_known_devices(self) -> list[dict]:
        """Return devices from the saved network baseline."""
        data = _load_json(_MEMORY_FILE, default={})
        if isinstance(data, dict):
            return data.get("devices", [])
        return []

    # ── Intruder watch ────────────────────────────────────────────────────────

    def watch_for_intruders(self) -> threading.Thread:
        """Start background thread scanning every 5 minutes for new devices."""
        if self._watcher_running:
            log.info("Intruder watcher already running.")
            return threading.current_thread()  # type: ignore

        def _watch():
            self._watcher_running = True
            log.info("Network intruder watcher started.")
            while self._watcher_running:
                try:
                    self._check_for_intruders()
                except Exception as exc:
                    log.error("Intruder watcher error: %s", exc)
                time.sleep(300)

        t = threading.Thread(target=_watch, daemon=True, name="network-watcher")
        t.start()
        return t

    def _check_for_intruders(self) -> list[dict]:
        known_ips  = {d["ip"] for d in self.get_known_devices()}
        known_macs = {d["mac"] for d in self.get_known_devices() if d.get("mac")}
        current    = self.scan_network()
        intruders  = []

        for device in current:
            ip  = device.get("ip", "")
            mac = device.get("mac", "")
            if ip not in known_ips and (not mac or mac not in known_macs):
                intruders.append(device)
                log.warning("Unknown device detected: %s (%s)", ip, mac or "no MAC")
                bus.publish(
                    "threat_detected",
                    {"threat_type": "new_unknown_device", "ip": ip, "mac": mac, "vendor": device.get("vendor")},
                    severity="warning",
                )
                notify(
                    "Unknown Device Detected",
                    f"IP: {ip} | Vendor: {device.get('vendor', 'Unknown')}",
                    Priority.HIGH,
                )

        return intruders

    # ── Internet health ───────────────────────────────────────────────────────

    def internet_health(self) -> dict:
        """
        Open a raw TCP connection to 8.8.8.8 and 1.1.1.1 (port 53, DNS) to
        check connectivity and measure round-trip latency. Not an actual
        `ping` (ICMP) — that binary isn't installed on Render's containers,
        so subprocess.run(["ping", ...]) reliably 500'd there. A TCP connect
        needs no external binary and gives an equally valid reachability +
        latency signal.
        Returns {"online": bool, "latency_ms": float, "targets": {...}}.
        """
        targets = {"8.8.8.8": None, "1.1.1.1": None}
        latencies: list[float] = []

        for host in targets:
            try:
                start = time.time()
                with socket.create_connection((host, 53), timeout=2):
                    pass
                latency_ms = round((time.time() - start) * 1000, 2)
                targets[host] = {"reachable": True, "latency_ms": latency_ms}
                latencies.append(latency_ms)
            except OSError as exc:
                log.warning("Connectivity check to %s failed: %s", host, exc)
                targets[host] = {"reachable": False, "latency_ms": None, "error": str(exc)}

        online = any(v and v.get("reachable") for v in targets.values())
        avg_latency = round(sum(latencies) / len(latencies), 2) if latencies else None

        return {
            "online":     online,
            "latency_ms": avg_latency,
            "targets":    targets,
            "checked_at": _now(),
        }

    # ── Full map ──────────────────────────────────────────────────────────────

    def network_map(self) -> dict:
        """Return a full dict with all devices, internet health, and last
        scan time. scan_network()/internet_health()/_local_subnet() are
        each already internally guarded, but wrap them here too — Render's
        sandboxed network namespace can behave unexpectedly in ways a
        single component's try/except might not anticipate, and this
        endpoint backs the HUD's network map, which should never just
        500 with no data."""
        try:
            devices = self.scan_network()
        except Exception:
            devices = []
        try:
            health = self.internet_health()
        except Exception:
            health = {"online": False, "latency_ms": None, "targets": {}}
        try:
            subnet = _local_subnet()
        except Exception:
            subnet = "unknown"

        return {
            "devices":        devices,
            "device_count":   len(devices),
            "internet":       health,
            "subnet":         subnet,
            "last_scanned":   _now(),
        }


# ── Module-level singleton ────────────────────────────────────────────────────
network = NetworkIntelligence()


def analyze_own_network_security() -> dict:
    """JARVIS analyzes YOUR network for vulnerabilities. Own network only —
    ethical security audit, not offensive scanning. Uses psutil directly
    rather than shelling out to netstat/ps (neither is in core/tools/system.py's
    shell command allowlist, and psutil is already a dependency here)."""
    try:
        conns = psutil.net_connections(kind="inet")
        listening = [f"{c.laddr.ip}:{c.laddr.port}" for c in conns if c.status == "LISTEN" and c.laddr]
        established = [f"{c.laddr.ip}:{c.laddr.port} -> {c.raddr.ip}:{c.raddr.port}"
                       for c in conns if c.status == "ESTABLISHED" and c.laddr and c.raddr]
    except Exception as e:
        listening, established = [], [f"error: {e}"]

    try:
        procs = [f"{p.info['pid']} {p.info['name']}" for p in
                 list(psutil.process_iter(["pid", "name"]))[:20]]
    except Exception as e:
        procs = [f"error: {e}"]

    results = {
        "open_ports": "\n".join(listening),
        "active_connections": "\n".join(established[:30]),
        "processes": "\n".join(procs),
    }

    from core.llm.router import think
    analysis = think(
        f"Analyze this network security data for potential vulnerabilities or concerns:\n"
        f"{json.dumps(results, indent=2)[:1000]}\n\nReply as a JARVIS security brief.",
        force_model="standard",
    )
    results["jarvis_analysis"] = analysis
    return results
