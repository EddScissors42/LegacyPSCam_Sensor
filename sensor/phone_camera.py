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
import hashlib
import json
import secrets
import socket
import ssl
import struct
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
    def get_local_lan_ip() -> str:
        """Detects the primary outbound LAN IPv4 address of this PC."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.settimeout(0.2)
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
                if ip and not ip.startswith("127."):
                    return ip
        except Exception:
            pass
        try:
            hostname = socket.gethostname()
            for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
                ip = info[4][0]
                if ip and not ip.startswith("127.") and not ip.startswith("169.254."):
                    return ip
        except Exception:
            pass
        return "127.0.0.1"

    def rotate_session_token(self) -> str:
        """Generates a fresh per-session pairing token, invalidating old QR/browser links."""
        with self._lock:
            self.session_token = secrets.token_urlsafe(6)
            return self.session_token

    def get_connect_url(self) -> str:
        ip = self.get_local_lan_ip()
        return f"https://{ip}:{self.actual_port}/?t={self.session_token}"

    def start(self, port: Optional[int] = None, bind_host: str = "0.0.0.0") -> bool:
        if port is not None:
            self.preferred_port = int(port)
        if self.running and self._server_sock is not None:
            return True
        self.rotate_session_token()

        lan_ip = "127.0.0.1" if bind_host == "127.0.0.1" else self.get_local_lan_ip()
        try:
            self._ssl_ctx = SelfSignedTLSManager.create_ssl_context(lan_ip)
        except Exception as e:
            print(f"[WARN] PhoneCameraServer TLS init fallback: {e}")
            self._ssl_ctx = None

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

        sock.listen(8)
        sock.settimeout(0.5)
        self._server_sock = sock
        self.running = True
        self._accept_thread = threading.Thread(
            target=self._accept_loop, daemon=True, name="PhoneCameraAcceptThread"
        )
        self._accept_thread.start()
        print(f"[PHONE-CAM] Server listening on {self.get_connect_url()}")
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
            conn.settimeout(3.0)
            try:
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except Exception:
                pass

            # Auto-detect TLS ClientHello (first byte 0x16) vs plain HTTP on the same port
            first_byte = conn.recv(1, socket.MSG_PEEK)
            if not first_byte:
                conn.close()
                return

            if first_byte[0] == 0x16 and self._ssl_ctx is not None:
                conn = self._ssl_ctx.wrap_socket(conn, server_side=True)

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
                    body = EXPIRED_SESSION_HTML.encode("utf-8")
                    status_line = "HTTP/1.1 403 Forbidden\r\n"
                else:
                    body = MOBILE_WEBAPP_HTML.encode("utf-8")
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
        except Exception:
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

                if masked and mask_key and payload:
                    # Fast vectorized XOR unmasking via numpy
                    arr = np.frombuffer(payload, dtype=np.uint8).copy()
                    mk = np.frombuffer(mask_key, dtype=np.uint8)
                    arr ^= np.resize(mk, arr.shape)
                    payload = arr.tobytes()

                if opcode == 0x08:  # Close
                    break
                elif opcode == 0x09:  # Ping -> Pong
                    self._ws_send_frame(sock, 0x0A, payload)
                elif opcode == 0x01:  # Text JSON message (hello / edge_metrics)
                    self._handle_json_message(payload.decode("utf-8", errors="replace"))
                elif opcode == 0x02:  # Binary JPEG frame
                    self._handle_binary_frame(payload)
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

    def _handle_binary_frame(self, payload: bytes) -> None:
        if len(payload) < 16:
            return
        # Optional 1-byte envelope header support: 0x01 + raw JPEG, or direct 0xFF 0xD8 JPEG
        jpeg_bytes = payload[1:] if (payload[0] == 0x01 and payload[1:3] == b"\xff\xd8") else payload
        arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
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
