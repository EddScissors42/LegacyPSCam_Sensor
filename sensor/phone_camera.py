"""
Smartphone Camera WebApp Server & Extensible Edge Protocol for Legacy PSCam Sensor.

Allows any Android or iOS (iPhone) smartphone on the local Wi-Fi network to act as a
low-latency 30/60 FPS motion tracking camera via its built-in mobile browser (Safari / Chrome)
without installing any APK or IPA.

Modular Architecture:
1. QRCodeGenerator (`sensor.qr_encoder`): Pure-Python ISO/IEC 18004 QR Code encoder.
2. SelfSignedTLSManager (`sensor.tls_manager`): Pure-Python ASN.1 DER X.509v3 TLS signer.
3. External HTML5/JS templates (`assets/webapp/mobile_webapp.html`, `expired_session.html`).
4. PhoneCameraServer: Single-port auto-detecting HTTP/HTTPS + WS/WSS daemon server.
"""
from __future__ import annotations

import base64
import ctypes
import hashlib
import ipaddress
import json
import secrets
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlsplit

import cv2
import numpy as np

from sensor.qr_encoder import QRCodeGenerator
from sensor.tls_manager import SelfSignedTLSManager


# =============================================================================
# 3. EXTERNAL HTML5 / JS MOBILE WEBAPP TEMPLATES (assets/webapp/*.html)
# =============================================================================

_FALLBACK_EXPIRED_HTML = (
    "<!DOCTYPE html><html lang='en'><head><meta charset='UTF-8'>"
    "<title>Legacy PSCam Sensor — Session Expired</title></head>"
    "<body><h1>Pairing Session Expired</h1>"
    "<p>Please scan the current QR Code on your PC to connect your phone camera.</p></body></html>"
)

_FALLBACK_MOBILE_HTML = (
    "<!DOCTYPE html><html lang='en'><head><meta charset='UTF-8'>"
    "<title>Legacy PSCam Sensor — Phone Camera</title></head>"
    "<body><h1>Legacy PSCam Sensor</h1><div>Standby • Waiting for PC</div>"
    "<button>Front Camera</button><button>Rear Camera</button><button>Dim Screen</button>"
    "<script>function computeScaledDimensions(w,h){return [w,h];}</script></body></html>"
)


def load_webapp_html(filename: str, fallback: str = "") -> str:
    """Loads an HTML template from assets/webapp/ (supports source tree and PyInstaller _MEIPASS)."""
    try:
        from assets import WEBAPP_DIR
        target_path = WEBAPP_DIR / filename
    except Exception:
        from pathlib import Path
        target_path = Path(__file__).resolve().parent.parent / "assets" / "webapp" / filename

    try:
        if target_path.exists():
            return target_path.read_text(encoding="utf-8")
    except Exception as e:
        try:
            from sensor.session_logger import get_session_logger
            get_session_logger().log_throttled(
                f"webapp_load_{filename}", "WARN", "PHONE_CAM", f"Failed to read {target_path}: {e}"
            )
        except Exception:
            pass
    return fallback


EXPIRED_SESSION_HTML = load_webapp_html("expired_session.html", _FALLBACK_EXPIRED_HTML)
MOBILE_WEBAPP_HTML = load_webapp_html("mobile_webapp.html", _FALLBACK_MOBILE_HTML)


# =============================================================================
# 4. PHONE CAMERA SERVER (AUTO HTTP/HTTPS + RFC 6455 WEBSOCKET + EDGE METRICS)
# =============================================================================

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_FIREWALL_RULE_NAME = "Legacy PSCam Sensor (Phone Camera)"

_VIRTUAL_ADAPTER_KEYWORDS = (
    "vpn",
    "radmin",
    "hamachi",
    "tailscale",
    "zerotier",
    "wireguard",
    "openvpn",
    "nordlynx",
    "proton",
    "warp",
    "cloudflare",
    "tap-windows",
    "wintun",
    "tunnel",
    "virtual",
    "vbox",
    "virtualbox",
    "vmware",
    "hyper-v",
    "vethernet",
    "wsl",
    "docker",
    "bluetooth",
    "loopback",
    "pseudo",
    "npcap",
    "zeroconf",
)


def _is_virtual_or_vpn_adapter(name: str, description: str, if_type: int, ip: str, has_gateway: bool) -> bool:
    """Heuristically identifies VPN tunnels and virtual VM/container network interfaces."""
    # Win32 MIB_IF_TYPE: 23=PPP, 24=Software Loopback, 53=PropVirtual (Tailscale/WireGuard/Wintun), 131=Tunnel
    if if_type in (23, 24, 53, 131):
        return True
    combined = f"{name} {description}".lower()
    if any(kw in combined for kw in _VIRTUAL_ADAPTER_KEYWORDS):
        return True
    try:
        addr = ipaddress.IPv4Address(ip)
        # CGNAT (100.64.0.0/10 — Tailscale/WireGuard), Hamachi (25/8), Radmin (26/8), VirtualBox Host-Only (192.168.56/24)
        if addr in ipaddress.IPv4Network("100.64.0.0/10"):
            return True
        if addr in ipaddress.IPv4Network("25.0.0.0/8") or addr in ipaddress.IPv4Network("26.0.0.0/8"):
            return True
        if addr in ipaddress.IPv4Network("192.168.56.0/24"):
            return True
        if addr in ipaddress.IPv4Network("198.18.0.0/15"):
            return True
        # Docker / WSL / Hyper-V commonly allocate 172.17-31.x.x without a physical LAN gateway
        if not has_gateway and addr in ipaddress.IPv4Network("172.16.0.0/12"):
            return True
    except Exception:
        pass
    return False


def _score_lan_candidate(ip: str, name: str, description: str, if_type: int, has_gateway: bool, is_virtual: bool, udp_ip: str) -> int:
    """Computes a preference score so physical Wi-Fi/Ethernet LAN IPs always outrank VPN/virtual adapters."""
    score = 0
    if not is_virtual:
        score += 100
    else:
        score -= 100

    # Wi-Fi (71) or Ethernet (6)
    if if_type == 71:
        score += 35
    elif if_type == 6:
        score += 30

    if has_gateway:
        score += 25

    try:
        addr = ipaddress.IPv4Address(ip)
        if addr in ipaddress.IPv4Network("192.168.0.0/16"):
            score += 20
        elif addr in ipaddress.IPv4Network("10.0.0.0/8"):
            score += 15
        elif addr in ipaddress.IPv4Network("172.16.0.0/12"):
            score += 12
        elif addr.is_private:
            score += 5
        else:
            score -= 20
    except Exception:
        pass

    # Prefer the OS default outbound route IP only when it belongs to a non-virtual LAN adapter
    if udp_ip and ip == udp_ip and not is_virtual:
        score += 15

    return score


def _enumerate_windows_ipv4_adapters() -> List[Dict[str, Any]]:
    """Enumerates active Windows IPv4 adapters via Win32 iphlpapi.GetAdaptersAddresses (<2ms, zero subprocess)."""
    if sys.platform != "win32":
        return []
    try:
        import ctypes.wintypes as wt

        AF_INET = 2
        GAA_FLAG_INCLUDE_GATEWAYS = 0x0080
        ERROR_BUFFER_OVERFLOW = 111

        class _SOCKADDR(ctypes.Structure):
            _fields_ = [("sa_family", ctypes.c_ushort), ("sa_data", ctypes.c_ubyte * 14)]

        class _SOCKET_ADDRESS(ctypes.Structure):
            _fields_ = [("lpSockaddr", ctypes.POINTER(_SOCKADDR)), ("iSockaddrLength", ctypes.c_int)]

        class _IP_ADAPTER_UNICAST_ADDRESS(ctypes.Structure):
            pass

        _IP_ADAPTER_UNICAST_ADDRESS._fields_ = [
            ("Length", wt.ULONG),
            ("Flags", wt.DWORD),
            ("Next", ctypes.POINTER(_IP_ADAPTER_UNICAST_ADDRESS)),
            ("Address", _SOCKET_ADDRESS),
        ]

        class _IP_ADAPTER_GATEWAY_ADDRESS(ctypes.Structure):
            pass

        _IP_ADAPTER_GATEWAY_ADDRESS._fields_ = [
            ("Length", wt.ULONG),
            ("Reserved", wt.DWORD),
            ("Next", ctypes.POINTER(_IP_ADAPTER_GATEWAY_ADDRESS)),
            ("Address", _SOCKET_ADDRESS),
        ]

        class _IP_ADAPTER_ADDRESSES(ctypes.Structure):
            pass

        _IP_ADAPTER_ADDRESSES._fields_ = [
            ("Length", wt.ULONG),
            ("IfIndex", wt.DWORD),
            ("Next", ctypes.POINTER(_IP_ADAPTER_ADDRESSES)),
            ("AdapterName", ctypes.c_char_p),
            ("FirstUnicastAddress", ctypes.POINTER(_IP_ADAPTER_UNICAST_ADDRESS)),
            ("FirstAnycastAddress", ctypes.c_void_p),
            ("FirstMulticastAddress", ctypes.c_void_p),
            ("FirstDnsServerAddress", ctypes.c_void_p),
            ("DnsSuffix", ctypes.c_wchar_p),
            ("Description", ctypes.c_wchar_p),
            ("FriendlyName", ctypes.c_wchar_p),
            ("PhysicalAddress", ctypes.c_ubyte * 8),
            ("PhysicalAddressLength", wt.DWORD),
            ("Flags", wt.DWORD),
            ("Mtu", wt.DWORD),
            ("IfType", wt.DWORD),
            ("OperStatus", ctypes.c_int),
            ("Ipv6IfIndex", wt.DWORD),
            ("ZoneIndices", wt.DWORD * 16),
            ("FirstPrefix", ctypes.c_void_p),
            ("TransmitLinkSpeed", ctypes.c_uint64),
            ("ReceiveLinkSpeed", ctypes.c_uint64),
            ("FirstWinsServerAddress", ctypes.c_void_p),
            ("FirstGatewayAddress", ctypes.POINTER(_IP_ADAPTER_GATEWAY_ADDRESS)),
        ]

        iphlpapi = ctypes.windll.iphlpapi
        size = wt.ULONG(65536)
        buf = ctypes.create_string_buffer(size.value)
        ret = iphlpapi.GetAdaptersAddresses(AF_INET, GAA_FLAG_INCLUDE_GATEWAYS, None, buf, ctypes.byref(size))
        if ret == ERROR_BUFFER_OVERFLOW and size.value > 0:
            buf = ctypes.create_string_buffer(size.value)
            ret = iphlpapi.GetAdaptersAddresses(AF_INET, GAA_FLAG_INCLUDE_GATEWAYS, None, buf, ctypes.byref(size))
        if ret != 0:
            return []

        results: List[Dict[str, Any]] = []
        ptr = ctypes.cast(buf, ctypes.POINTER(_IP_ADAPTER_ADDRESSES))
        while ptr:
            a = ptr.contents
            # IfOperStatusUp == 1
            if a.OperStatus == 1:
                friendly = str(a.FriendlyName or "Network").strip()
                desc = str(a.Description or "").strip()
                if_type = int(a.IfType)
                has_gw = bool(a.FirstGatewayAddress)
                u = a.FirstUnicastAddress
                while u:
                    sockaddr_ptr = u.contents.Address.lpSockaddr
                    if sockaddr_ptr:
                        sa = sockaddr_ptr.contents
                        if sa.sa_family == AF_INET:
                            ip_str = socket.inet_ntoa(bytes(sa.sa_data[2:6]))
                            if ip_str and not ip_str.startswith("127.") and not ip_str.startswith("169.254.") and ip_str != "0.0.0.0":
                                is_virt = _is_virtual_or_vpn_adapter(friendly, desc, if_type, ip_str, has_gw)
                                results.append({
                                    "ip": ip_str,
                                    "name": friendly,
                                    "description": desc,
                                    "if_type": if_type,
                                    "has_gateway": has_gw,
                                    "is_virtual": is_virt,
                                })
                    u = u.contents.Next
            ptr = a.Next
        return results
    except Exception:
        return []


class PhoneCameraServer:
    """
    Single-port auto-detecting HTTP/HTTPS & WebSocket daemon server for Smartphone Camera.
    - Serves the mobile WebApp HTML5 page at `GET /`.
    - Upgrades `/ws` to a low-latency RFC 6455 WebSocket stream.
    - Supports both Mode 1 (`pc_video`: binary JPEG frames decoded via OpenCV) and
      Mode 2 (`phone_edge`: structured JSON `edge_metrics` for future on-device inference).
    """

    def __init__(self, port: int = 8443) -> None:
        self.preferred_port = int(port)
        self.actual_port = int(port)
        self.selected_ip: Optional[str] = None
        self._tls_san_ips: List[str] = []
        self.running = False
        self._server_sock: Optional[socket.socket] = None
        self._accept_thread: Optional[threading.Thread] = None
        self._ssl_ctx: Optional[ssl.SSLContext] = None
        self._lock = threading.Lock()

        # Connected smartphone client state
        self.session_token: str = secrets.token_urlsafe(6)
        self.streaming_active: bool = False
        self._client_sock: Optional[socket.socket] = None
        self.is_client_connected: bool = False
        self.client_ip: str = ""
        self.client_device_name: str = "Smartphone"
        self.client_lens: str = "user"  # "user" (Front) or "environment" (Rear)
        self.client_capabilities: List[str] = ["pc_video"]
        self.processing_mode: str = "pc_video"  # "pc_video" or "phone_edge"

        # Target configuration requested by PC UI
        self.target_w: int = 640
        self.target_h: int = 480
        self.target_fps: int = 30

        # Decoded video frame buffer (Mode 1: pc_video)
        self.latest_frame: Optional[np.ndarray] = None
        self.frame_seq: int = 0
        self.last_consumed_seq: int = 0
        self.actual_w: int = 640
        self.actual_h: int = 480
        self.measured_fps: float = 0.0
        self._fps_counter: int = 0
        self._fps_last_time: float = time.time()
        self.last_frame_time: float = 0.0

        # Pre-computed edge metrics buffer (Mode 2: phone_edge future-ready slot)
        self.latest_edge_metrics: Optional[Dict[str, Any]] = None
        self.edge_metrics_seq: int = 0
        self.last_consumed_edge_seq: int = 0

    @staticmethod
    def _probe_outbound_udp_ip() -> str:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.settimeout(0.2)
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
                if ip and not ip.startswith("127.") and not ip.startswith("169.254."):
                    return ip
        except Exception:
            pass
        return ""

    @classmethod
    def list_local_lan_ips(cls) -> List[Dict[str, Any]]:
        """
        Returns ranked local IPv4 network interfaces suitable for Phone Camera pairing.
        Physical Wi-Fi/Ethernet adapters are prioritized above VPN tunnels and virtual VM adapters.
        """
        udp_ip = cls._probe_outbound_udp_ip()
        raw_adapters = _enumerate_windows_ipv4_adapters()

        by_ip: Dict[str, Dict[str, Any]] = {}
        for item in raw_adapters:
            ip = item["ip"]
            score = _score_lan_candidate(
                ip=ip,
                name=item["name"],
                description=item["description"],
                if_type=item["if_type"],
                has_gateway=item["has_gateway"],
                is_virtual=item["is_virtual"],
                udp_ip=udp_ip,
            )
            tag = f"{item['name']} (VPN/Virtual)" if item["is_virtual"] else item["name"]
            entry = {
                "ip": ip,
                "name": item["name"],
                "description": item["description"],
                "label": f"{ip} — {tag}",
                "is_virtual": bool(item["is_virtual"]),
                "has_gateway": bool(item["has_gateway"]),
                "score": score,
            }
            if ip not in by_ip or score > by_ip[ip]["score"]:
                by_ip[ip] = entry

        # Fallback / merge with UDP probe & hostname resolution (cross-platform safety)
        if udp_ip and udp_ip not in by_ip:
            is_virt = _is_virtual_or_vpn_adapter("Default Route", "", 0, udp_ip, True)
            score = _score_lan_candidate(udp_ip, "Default Route", "", 0, True, is_virt, udp_ip)
            by_ip[udp_ip] = {
                "ip": udp_ip,
                "name": "Default Network",
                "description": "",
                "label": f"{udp_ip} — {'VPN/Virtual' if is_virt else 'LAN'}",
                "is_virtual": is_virt,
                "has_gateway": True,
                "score": score,
            }

        if not by_ip:
            try:
                hostname = socket.gethostname()
                for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
                    ip = info[4][0]
                    if ip and not ip.startswith("127.") and not ip.startswith("169.254.") and ip not in by_ip:
                        is_virt = _is_virtual_or_vpn_adapter("Local Interface", "", 0, ip, False)
                        score = _score_lan_candidate(ip, "Local Interface", "", 0, False, is_virt, udp_ip)
                        by_ip[ip] = {
                            "ip": ip,
                            "name": "Local Interface",
                            "description": "",
                            "label": f"{ip} — {'VPN/Virtual' if is_virt else 'LAN'}",
                            "is_virtual": is_virt,
                            "has_gateway": False,
                            "score": score,
                        }
            except Exception:
                pass

        ranked = sorted(by_ip.values(), key=lambda x: (-x["score"], x["ip"]))
        if not ranked:
            ranked.append({
                "ip": "127.0.0.1",
                "name": "Loopback",
                "description": "",
                "label": "127.0.0.1 — No Wi-Fi/LAN detected",
                "is_virtual": True,
                "has_gateway": False,
                "score": -999,
            })
        return ranked

    @classmethod
    def get_local_lan_ip(cls) -> str:
        """Detects the best physical LAN IPv4 address of this PC (ignoring VPN/virtual tunnels when possible)."""
        ranked = cls.list_local_lan_ips()
        return ranked[0]["ip"] if ranked else "127.0.0.1"

    @staticmethod
    def check_windows_firewall_rule(port: int = 8443) -> Dict[str, Any]:
        """
        Checks Windows Defender Firewall rules via Registry (<2ms, no admin, locale-independent)
        to see whether inbound TCP traffic on `port` is explicitly allowed across Public & Private profiles.
        """
        port_str = str(int(port))
        result: Dict[str, Any] = {
            "platform": sys.platform,
            "port": int(port),
            "port_rule_allowed": False,
            "covers_public": False,
            "covers_private": False,
            "rule_name": _FIREWALL_RULE_NAME,
        }
        if sys.platform != "win32":
            result["port_rule_allowed"] = True
            result["covers_public"] = True
            result["covers_private"] = True
            return result
        try:
            import winreg

            key_path = r"SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy\FirewallRules"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                num_vals = winreg.QueryInfoKey(key)[1]
                for i in range(num_vals):
                    try:
                        _, raw_val, _ = winreg.EnumValue(key, i)
                    except OSError:
                        continue
                    val = str(raw_val)
                    if f"LPort={port_str}" not in val:
                        continue
                    # Parse pipe-delimited Windows Firewall rule string
                    fields: Dict[str, List[str]] = {}
                    for part in val.split("|"):
                        if "=" in part:
                            k, v = part.split("=", 1)
                            fields.setdefault(k.strip().lower(), []).append(v.strip())
                    action = (fields.get("action") or [""])[0].lower()
                    active = (fields.get("active") or [""])[0].lower()
                    direction = (fields.get("dir") or [""])[0].lower()
                    proto = (fields.get("protocol") or [""])[0].lower()
                    lports = [p.strip() for p in fields.get("lport", [])]
                    if action == "allow" and active == "true" and direction == "in" and proto in ("6", "tcp", "") and port_str in lports:
                        profiles = [p.lower() for p in fields.get("profile", [])]
                        if not profiles or "any" in profiles:
                            result["covers_public"] = True
                            result["covers_private"] = True
                        else:
                            if "public" in profiles:
                                result["covers_public"] = True
                            if "private" in profiles:
                                result["covers_private"] = True
                        if result["covers_public"] and result["covers_private"]:
                            result["port_rule_allowed"] = True
                            break
        except Exception:
            pass
        return result

    @classmethod
    def ensure_windows_firewall_rule(cls, port: int = 8443) -> Tuple[bool, str]:
        """
        Adds an inbound Windows Defender Firewall allow rule for TCP `port` on all profiles
        (Private, Public, Domain) so smartphones on the local Wi-Fi do not hit ERR_CONNECTION_TIMED_OUT.
        Triggers a standard Windows UAC elevation prompt only if not already running as Administrator.
        """
        port_int = int(port)
        if sys.platform != "win32":
            return True, "Firewall configuration is only required on Windows."

        cmd_str = (
            f'netsh advfirewall firewall delete rule name="{_FIREWALL_RULE_NAME}" >nul 2>&1 & '
            f'netsh advfirewall firewall add rule name="{_FIREWALL_RULE_NAME}" '
            f'dir=in action=allow protocol=TCP localport={port_int} profile=any enable=yes'
        )
        try:
            is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            is_admin = False

        if is_admin:
            try:
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                proc = subprocess.run(
                    ["cmd.exe", "/c", cmd_str],
                    capture_output=True,
                    text=True,
                    timeout=8,
                    creationflags=creationflags,
                )
                if proc.returncode == 0:
                    return True, f"Windows Firewall rule enabled for TCP port {port_int} (Private & Public Wi-Fi)."
                return False, f"Failed to add Windows Firewall rule (exit {proc.returncode})."
            except Exception as e:
                return False, f"Failed to configure Windows Firewall: {e}"

        # Request one-time UAC elevation strictly for adding the netsh inbound port rule
        try:
            ret = ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                "cmd.exe",
                f"/c {cmd_str}",
                None,
                0,  # SW_HIDE
            )
            if int(ret) <= 32:
                return False, "Firewall permission prompt was cancelled by user."
            # Poll briefly until elevated netsh finishes updating the registry
            deadline = time.time() + 4.5
            while time.time() < deadline:
                if cls.check_windows_firewall_rule(port_int).get("port_rule_allowed"):
                    return True, f"Windows Firewall rule enabled for TCP port {port_int} (Private & Public Wi-Fi)."
                time.sleep(0.25)
            return True, f"Firewall rule requested for TCP port {port_int}. Re-scan the QR code to test."
        except Exception as e:
            return False, f"Could not launch Windows Firewall elevation: {e}"

    def set_preferred_ip(self, ip: Optional[str]) -> str:
        """Selects which local IPv4 address is encoded in the pairing QR Code / URL."""
        cleaned = str(ip or "").strip()
        with self._lock:
            self.selected_ip = cleaned if cleaned else None
        active_ip = self.get_active_ip()
        # Ensure the TLS certificate SubjectAltName covers the newly chosen IP
        if self.running and active_ip and active_ip not in self._tls_san_ips:
            self._rebuild_ssl_context(active_ip)
        return active_ip

    def get_active_ip(self) -> str:
        """Returns the user-selected LAN IP if still valid, or automatically selects the best LAN IP."""
        ranked = self.list_local_lan_ips()
        available_ips = [item["ip"] for item in ranked]
        with self._lock:
            pref = self.selected_ip
        if pref and pref in available_ips:
            return pref
        return available_ips[0] if available_ips else "127.0.0.1"

    def _rebuild_ssl_context(self, primary_ip: str, extra_ips: Optional[List[str]] = None) -> None:
        all_ips: List[str] = [primary_ip]
        if extra_ips:
            for ip in extra_ips:
                if ip and ip not in all_ips:
                    all_ips.append(ip)
        try:
            ctx = SelfSignedTLSManager.create_ssl_context(primary_ip, extra_ips=all_ips)
            with self._lock:
                self._ssl_ctx = ctx
                self._tls_san_ips = all_ips
        except Exception as e:
            print(f"[WARN] PhoneCameraServer TLS init fallback: {e}")

    def rotate_session_token(self) -> str:
        """Generates a fresh per-session pairing token, invalidating old QR/browser links."""
        with self._lock:
            self.session_token = secrets.token_urlsafe(6)
            return self.session_token

    def get_connect_url(self) -> str:
        ip = self.get_active_ip()
        return f"https://{ip}:{self.actual_port}/?t={self.session_token}"

    def start(self, port: Optional[int] = None, bind_host: str = "0.0.0.0") -> bool:
        if port is not None:
            self.preferred_port = int(port)
        if self.running and self._server_sock is not None:
            return True
        self.rotate_session_token()

        if bind_host == "127.0.0.1":
            lan_ip = "127.0.0.1"
            all_lan_ips = ["127.0.0.1"]
        else:
            ranked = self.list_local_lan_ips()
            all_lan_ips = [item["ip"] for item in ranked]
            lan_ip = self.get_active_ip()
        self._rebuild_ssl_context(lan_ip, extra_ips=all_lan_ips)

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        bound = False
        for candidate_port in (self.preferred_port, 8444, 8445, 0):
            try:
                sock.bind((bind_host, candidate_port))
                self.actual_port = sock.getsockname()[1]
                bound = True
                break
            except OSError:
                continue

        if not bound:
            sock.close()
            return False

        sock.listen(16)
        sock.settimeout(0.5)
        self._server_sock = sock
        self.running = True
        self._accept_thread = threading.Thread(
            target=self._accept_loop, daemon=True, name="PhoneCameraAcceptThread"
        )
        self._accept_thread.start()
        url = self.get_connect_url()
        print(f"[PHONE-CAM] Server listening on {url} (interfaces: {', '.join(all_lan_ips)})")
        try:
            from sensor.session_logger import get_session_logger
            get_session_logger().log(
                "INFO",
                "PHONE_CAM",
                f"Server listening on {bind_host}:{self.actual_port} | URL={url} | IPs={all_lan_ips}",
            )
        except Exception:
            pass
        return True

    def stop(self) -> None:
        self.running = False
        self.disconnect_client()
        if self._server_sock is not None:
            try:
                self._server_sock.close()
            except Exception:
                pass
            self._server_sock = None

    def disconnect_client(self, rotate_token: bool = True) -> None:
        with self._lock:
            sock = self._client_sock
            self._client_sock = None
            self.is_client_connected = False
            self.streaming_active = False
            self.measured_fps = 0.0
            if rotate_token:
                self.session_token = secrets.token_urlsafe(6)
        if sock is not None:
            try:
                self._ws_send_text(sock, json.dumps({"type": "disconnect"}))
            except Exception:
                pass
            try:
                # RFC 6455 Close Frame with custom code 4001 (explicitly disconnected by PC)
                self._ws_send_frame(sock, 0x08, struct.pack("!H", 4001))
            except Exception:
                pass
            try:
                sock.close()
            except Exception:
                pass

    def set_streaming_active(self, active: bool) -> None:
        """Toggles phone between active video streaming and cool low-power Standby mode."""
        self.configure_stream(streaming_active=bool(active))

    def configure_stream(
        self,
        width: Optional[int] = None,
        height: Optional[int] = None,
        fps: Optional[int] = None,
        lens: Optional[str] = None,
        processing_mode: Optional[str] = None,
        streaming_active: Optional[bool] = None,
    ) -> None:
        """Updates target stream settings and pushes live command to connected smartphone."""
        if width is not None:
            self.target_w = int(width)
        if height is not None:
            self.target_h = int(height)
        if fps is not None:
            self.target_fps = int(fps)
        if lens in ("user", "environment"):
            self.client_lens = lens
        if processing_mode in ("pc_video", "phone_edge"):
            self.processing_mode = processing_mode
        if streaming_active is not None:
            self.streaming_active = bool(streaming_active)
            if not self.streaming_active:
                self.measured_fps = 0.0

        with self._lock:
            sock = self._client_sock
        if sock is not None and self.is_client_connected:
            msg = json.dumps({
                "type": "config",
                "width": self.target_w,
                "height": self.target_h,
                "fps": self.target_fps,
                "lens": self.client_lens,
                "processing_mode": self.processing_mode,
                "active": self.streaming_active,
            })
            try:
                self._ws_send_text(sock, msg)
            except Exception:
                pass

    def read_frame(self, only_new: bool = True) -> Optional[np.ndarray]:
        """Returns the latest decoded BGR frame from the connected smartphone."""
        with self._lock:
            if self.latest_frame is None:
                return None
            if only_new and self.frame_seq == self.last_consumed_seq:
                return None
            self.last_consumed_seq = self.frame_seq
            return self.latest_frame

    def read_edge_metrics(self, only_new: bool = True) -> Optional[Dict[str, Any]]:
        """
        Future-ready consumer for on-device smartphone edge processing (`phone_edge` mode).
        Returns pre-computed landmarks/joints/IMU metrics sent by the phone.
        """
        with self._lock:
            if self.latest_edge_metrics is None:
                return None
            if only_new and self.edge_metrics_seq == self.last_consumed_edge_seq:
                return None
            self.last_consumed_edge_seq = self.edge_metrics_seq
            return self.latest_edge_metrics

    def _accept_loop(self) -> None:
        while self.running and self._server_sock is not None:
            try:
                conn, addr = self._server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(
                target=self._handle_connection,
                args=(conn, addr),
                daemon=True,
                name="PhoneCameraClientThread",
            ).start()

    def _handle_connection(self, raw_conn: socket.socket, addr: Tuple[str, int]) -> None:
        conn = raw_conn
        try:
            conn.settimeout(10.0)
            try:
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                conn.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 262144)
            except Exception:
                pass

            # Auto-detect TLS ClientHello (first byte 0x16) vs plain HTTP on the same port
            first_byte = conn.recv(1, socket.MSG_PEEK)
            if not first_byte:
                conn.close()
                return

            with self._lock:
                ssl_ctx = self._ssl_ctx
            if first_byte[0] == 0x16 and ssl_ctx is not None:
                conn = ssl_ctx.wrap_socket(conn, server_side=True)

            req_data = b""
            while b"\r\n\r\n" not in req_data and len(req_data) < 16384:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                req_data += chunk

            if not req_data:
                conn.close()
                return

            header_text = req_data.split(b"\r\n\r\n", 1)[0].decode("latin-1", errors="replace")
            lines = header_text.split("\r\n")
            req_line = lines[0].split()
            raw_path = req_line[1] if len(req_line) >= 2 else "/"
            parsed_url = urlsplit(raw_path)
            path = parsed_url.path or "/"
            qs = parse_qs(parsed_url.query)
            req_token = qs.get("t", [""])[0]
            token_valid = bool(req_token and secrets.compare_digest(req_token, self.session_token))

            headers: Dict[str, str] = {}
            for line in lines[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip().lower()] = v.strip()

            if headers.get("upgrade", "").lower() == "websocket" or path.startswith("/ws"):
                if not token_valid:
                    resp = (
                        "HTTP/1.1 403 Forbidden\r\n"
                        "Content-Type: text/plain\r\n"
                        "Cache-Control: no-store\r\n"
                        "Connection: close\r\n\r\n"
                        "Invalid or expired pairing token"
                    )
                    conn.sendall(resp.encode("ascii"))
                    conn.close()
                    return
                ws_key = headers.get("sec-websocket-key", "")
                if not ws_key:
                    conn.close()
                    return
                accept_val = base64.b64encode(
                    hashlib.sha1((ws_key + _WS_GUID).encode("ascii")).digest()
                ).decode("ascii")
                resp = (
                    "HTTP/1.1 101 Switching Protocols\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Accept: {accept_val}\r\n\r\n"
                )
                conn.sendall(resp.encode("ascii"))
                self._run_websocket_session(conn, addr[0])
            else:
                if not token_valid:
                    body = load_webapp_html("expired_session.html", EXPIRED_SESSION_HTML).encode("utf-8")
                    status_line = "HTTP/1.1 403 Forbidden\r\n"
                else:
                    body = load_webapp_html("mobile_webapp.html", MOBILE_WEBAPP_HTML).encode("utf-8")
                    status_line = "HTTP/1.1 200 OK\r\n"
                resp_hdr = (
                    status_line
                    + "Content-Type: text/html; charset=utf-8\r\n"
                    + f"Content-Length: {len(body)}\r\n"
                    + "Cache-Control: no-cache, no-store, must-revalidate\r\n"
                    + "Pragma: no-cache\r\n"
                    + "Expires: 0\r\n"
                    + "Connection: close\r\n\r\n"
                ).encode("ascii")
                conn.sendall(resp_hdr + body)
                conn.close()
        except Exception as e:
            try:
                from sensor.session_logger import get_session_logger
                get_session_logger().log_throttled(
                    "phone_cam_conn_err",
                    "DEBUG",
                    "PHONE_CAM",
                    f"Connection error from {addr[0]}: {type(e).__name__}: {e}",
                )
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

    @staticmethod
    def _recv_exact(sock: socket.socket, n: int) -> Optional[bytes]:
        buf = bytearray()
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                return None
            buf.extend(chunk)
        return bytes(buf)

    @staticmethod
    def _ws_send_frame(sock: socket.socket, opcode: int, payload: bytes) -> None:
        length = len(payload)
        if length < 126:
            hdr = struct.pack("!BB", 0x80 | opcode, length)
        elif length < 65536:
            hdr = struct.pack("!BBH", 0x80 | opcode, 126, length)
        else:
            hdr = struct.pack("!BBQ", 0x80 | opcode, 127, length)
        sock.sendall(hdr + payload)

    @classmethod
    def _ws_send_text(cls, sock: socket.socket, text: str) -> None:
        cls._ws_send_frame(sock, 0x01, text.encode("utf-8"))

    def _run_websocket_session(self, sock: socket.socket, client_ip: str) -> None:
        sock.settimeout(5.0)
        with self._lock:
            old_sock = self._client_sock
            self._client_sock = sock
            self.is_client_connected = True
            self.client_ip = client_ip
            self._fps_counter = 0
            self._fps_last_time = time.time()

        if old_sock is not None and old_sock is not sock:
            try:
                old_sock.close()
            except Exception:
                pass

        # Push current target configuration immediately upon WebSocket connect
        self.configure_stream()

        try:
            while self.running:
                hdr2 = self._recv_exact(sock, 2)
                if not hdr2:
                    break
                b0, b1 = hdr2[0], hdr2[1]
                opcode = b0 & 0x0F
                masked = bool(b1 & 0x80)
                length = b1 & 0x7F

                if length == 126:
                    ext = self._recv_exact(sock, 2)
                    if not ext:
                        break
                    length = struct.unpack("!H", ext)[0]
                elif length == 127:
                    ext = self._recv_exact(sock, 8)
                    if not ext:
                        break
                    length = struct.unpack("!Q", ext)[0]

                if length > 4 * 1024 * 1024:
                    break

                mask_key = self._recv_exact(sock, 4) if masked else None
                if masked and not mask_key:
                    break

                payload = self._recv_exact(sock, length) if length > 0 else b""
                if payload is None:
                    break

                unmasked_arr: Optional[np.ndarray] = None
                if masked and mask_key and payload:
                    # Fast in-place 4-byte strided XOR unmasking (zero temp mask allocation)
                    arr = np.frombuffer(payload, dtype=np.uint8).copy()
                    arr[0::4] ^= mask_key[0]
                    arr[1::4] ^= mask_key[1]
                    arr[2::4] ^= mask_key[2]
                    arr[3::4] ^= mask_key[3]
                    if opcode == 0x02:
                        unmasked_arr = arr
                    else:
                        payload = arr.tobytes()

                if opcode == 0x08:  # Close
                    break
                elif opcode == 0x09:  # Ping -> Pong
                    self._ws_send_frame(sock, 0x0A, payload)
                elif opcode == 0x01:  # Text JSON message (hello / edge_metrics)
                    self._handle_json_message(payload.decode("utf-8", errors="replace"))
                elif opcode == 0x02:  # Binary JPEG frame
                    self._handle_binary_frame(unmasked_arr if unmasked_arr is not None else payload)
        except Exception as e:
            try:
                from sensor.session_logger import get_session_logger
                get_session_logger().log_throttled(
                    "phone_cam_ws_err",
                    "DEBUG",
                    "PHONE_CAM",
                    f"WebSocket session closed or interrupted for {client_ip}: {e}",
                )
            except Exception:
                pass
        finally:
            with self._lock:
                if self._client_sock is sock:
                    self._client_sock = None
                    self.is_client_connected = False
                    self.measured_fps = 0.0
            try:
                sock.close()
            except Exception:
                pass

    def _handle_json_message(self, raw_json: str) -> None:
        try:
            msg = json.loads(raw_json)
        except Exception as e:
            try:
                from sensor.session_logger import get_session_logger
                get_session_logger().log_throttled(
                    "phone_cam_json_err", "WARN", "PHONE_CAM", f"Malformed JSON from smartphone client: {e}"
                )
            except Exception:
                pass
            return
        msg_type = msg.get("type")
        if msg_type == "hello":
            with self._lock:
                self.client_device_name = str(msg.get("device") or "Smartphone")
                lens = str(msg.get("lens") or "user")
                if lens in ("user", "environment"):
                    self.client_lens = lens
                if msg.get("width") and msg.get("height"):
                    self.actual_w = int(msg["width"])
                    self.actual_h = int(msg["height"])
                caps = msg.get("capabilities")
                if isinstance(caps, list):
                    self.client_capabilities = [str(c) for c in caps]
        elif msg_type == "edge_metrics":
            with self._lock:
                self.latest_edge_metrics = msg
                self.edge_metrics_seq += 1
                self._fps_counter += 1
                now = time.time()
                self.last_frame_time = now
                elapsed = now - self._fps_last_time
                if elapsed >= 1.0:
                    self.measured_fps = self._fps_counter / elapsed
                    self._fps_counter = 0
                    self._fps_last_time = now

    def _handle_binary_frame(self, payload: Any) -> None:
        if isinstance(payload, np.ndarray):
            arr = payload
        else:
            arr = np.frombuffer(payload, dtype=np.uint8)
        if arr.size < 16:
            return
        # Optional 1-byte envelope header support: 0x01 + raw JPEG, or direct 0xFF 0xD8 JPEG
        if arr[0] == 0x01 and arr[1] == 0xFF and arr[2] == 0xD8:
            arr = arr[1:]
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None or frame.size == 0:
            return

        h, w = frame.shape[:2]
        now = time.time()
        with self._lock:
            self.latest_frame = frame
            self.frame_seq += 1
            self.actual_w = w
            self.actual_h = h
            self.last_frame_time = now
            self._fps_counter += 1
            elapsed = now - self._fps_last_time
            if elapsed >= 1.0:
                self.measured_fps = self._fps_counter / elapsed
                self._fps_counter = 0
                self._fps_last_time = now


_GLOBAL_PHONE_CAMERA_SERVER: Optional[PhoneCameraServer] = None
_GLOBAL_SERVER_LOCK = threading.Lock()


def get_phone_camera_server(port: int = 8443) -> PhoneCameraServer:
    """Returns the singleton PhoneCameraServer instance."""
    global _GLOBAL_PHONE_CAMERA_SERVER
    with _GLOBAL_SERVER_LOCK:
        if _GLOBAL_PHONE_CAMERA_SERVER is None:
            _GLOBAL_PHONE_CAMERA_SERVER = PhoneCameraServer(port=port)
        return _GLOBAL_PHONE_CAMERA_SERVER
