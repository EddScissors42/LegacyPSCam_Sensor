"""
UbiArt Smartphone Protocol Primitives, Hand Accelerometer Physics,
Minimal RFC 6455 WebSocket Client, Adaptive Calibration Tuner, and
Game Process Song Detector for Legacy PSCam Sensor.

Extracted from `sensor/virtual_phone.py` for modularity while keeping
100% backwards-compatible re-exports in `sensor/virtual_phone.py`.
"""
from __future__ import annotations

import base64
import hashlib
import math
import os
import re
import socket
import ssl
import struct
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Tuple


# UbiArt Smartphone Scoring WebSocket constants
# Protocol v2: UbiArt CivetWeb with built-in TLS, requires exact subprotocol match
# Protocol v1: Just Dance 2017 / 2018 Legacy (plain TCP WebSocket)
WS_SUBPROTOCOL_V2 = "v2.phonescoring.jd.ubisoft.com"
WS_SUBPROTOCOL_V1 = "v1.phonescoring.jd.ubisoft.com"
WS_SUBPROTOCOL = WS_SUBPROTOCOL_V2
WS_ENDPOINT = "/smartphone"
UDP_DISCOVERY_PORT_TX = 6000
UDP_DISCOVERY_PORT_RX = 7000
UDP_DISCOVERY_MAGIC = b"phonescoring.jd.ubisoft.com"

# UbiArt StringID hashes for JD_Input_PhoneCommandData
PHONE_INPUT_HASHES: Dict[str, int] = {
    "VALID": 1084313942,  # 0x40A15156 (OK / Confirm)
    "UP": 3690595578,     # 0xDBFA04FA
    "DOWN": 2467711647,   # 0x93164A9F
    "RIGHT": 1099935642,  # 0x418FAF9A
    "LEFT": 3652315484,   # 0xD9B1E95C
}

# Kinect v1 joint indices in PoseTracker output (20 joints)
JOINT_SHOULDER_LEFT = 4
JOINT_ELBOW_LEFT = 5
JOINT_WRIST_LEFT = 6
JOINT_HAND_LEFT = 7

JOINT_SHOULDER_RIGHT = 8
JOINT_ELBOW_RIGHT = 9
JOINT_WRIST_RIGHT = 10
JOINT_HAND_RIGHT = 11


class HandAccelerometer:
    """
    Converts 3D Kinect joint positions of the dancer's hand/forearm into
    simulated 3-axis smartphone accelerometer readings [ax, ay, az] in G-units
    (where 1.0 G = 9.81 m/s², clamped to [-7.0, 7.0] G vector magnitude matching
    physical DualShock 4 / smartphone IMU hardware).
    """

    MAX_G: float = 7.0
    GRAVITY_MPS2: float = 9.81

    def __init__(self, hand: str = "right", sensitivity: float = 1.0) -> None:
        self.hand = hand.lower() if hand.lower() in ("left", "right") else "right"
        self.sensitivity = max(0.2, min(4.0, float(sensitivity)))

        self._prev_pos: Optional[Tuple[float, float, float]] = None
        self._smoothed_vel: List[float] = [0.0, 0.0, 0.0]
        self._prev_smoothed_vel: List[float] = [0.0, 0.0, 0.0]
        self._prev_time: Optional[float] = None
        self._smoothed_accel: Tuple[float, float, float] = (0.08, 0.38, 0.75)
        self._latest_speed: float = 0.0
        self._latest_alpha: float = 0.35

    @property
    def latest_speed(self) -> float:
        return self._latest_speed

    @property
    def latest_alpha(self) -> float:
        return self._latest_alpha

    def reset(self) -> None:
        """Resets velocity/position history."""
        self._prev_pos = None
        self._smoothed_vel = [0.0, 0.0, 0.0]
        self._prev_smoothed_vel = [0.0, 0.0, 0.0]
        self._prev_time = None
        self._smoothed_accel = (0.08, 0.38, 0.75)
        self._latest_speed = 0.0
        self._latest_alpha = 0.35

    def update(
        self,
        kinect_joints: List[Tuple[float, float, float, float]],
        is_tracked: bool,
        now: Optional[float] = None,
    ) -> Tuple[float, float, float]:
        """Computes [ax, ay, az] in G-units from the 20 Kinect joints."""
        if now is None:
            now = time.perf_counter()

        if not is_tracked or len(kinect_joints) < 12:
            self.reset()
            return self._smoothed_accel

        if self.hand == "left":
            elbow = kinect_joints[JOINT_ELBOW_LEFT]
            wrist = kinect_joints[JOINT_WRIST_LEFT]
            hand = kinect_joints[JOINT_HAND_LEFT]
        else:
            elbow = kinect_joints[JOINT_ELBOW_RIGHT]
            wrist = kinect_joints[JOINT_WRIST_RIGHT]
            hand = kinect_joints[JOINT_HAND_RIGHT]

        if hand[3] < 0.15 and wrist[3] < 0.15:
            return self._smoothed_accel

        if hand[3] >= 0.35:
            hx, hy, hz = hand[0], hand[1], hand[2]
        else:
            hx = 0.60 * hand[0] + 0.40 * wrist[0]
            hy = 0.60 * hand[1] + 0.40 * wrist[1]
            hz = 0.60 * hand[2] + 0.40 * wrist[2]

        # 1. Forearm orientation vector (elbow -> hand)
        fx = hx - elbow[0]
        fy = hy - elbow[1]
        fz = hz - elbow[2]
        flen = math.sqrt(fx * fx + fy * fy + fz * fz)
        if flen > 1e-4:
            ux, uy, uz = fx / flen, fy / flen, fz / flen
        else:
            ux, uy, uz = 0.08, 0.38, -0.75

        grav_x = ux * 0.98
        grav_y = uy * 0.98
        grav_z = (-uz) * 0.98

        # 2. Dynamic linear acceleration and centripetal force
        lin_gx, lin_gy, lin_gz = 0.0, 0.0, 0.0
        cent_gx, cent_gy, cent_gz = 0.0, 0.0, 0.0
        speed = 0.0

        if self._prev_pos is not None and self._prev_time is not None:
            dt = now - self._prev_time
            if 0.004 <= dt <= 0.25:
                raw_vx = (hx - self._prev_pos[0]) / dt
                raw_vy = (hy - self._prev_pos[1]) / dt
                raw_vz = (hz - self._prev_pos[2]) / dt

                tau_v = 0.045
                v_alpha = max(0.15, min(0.85, 1.0 - math.exp(-dt / tau_v)))
                sm_vx = v_alpha * raw_vx + (1.0 - v_alpha) * self._smoothed_vel[0]
                sm_vy = v_alpha * raw_vy + (1.0 - v_alpha) * self._smoothed_vel[1]
                sm_vz = v_alpha * raw_vz + (1.0 - v_alpha) * self._smoothed_vel[2]

                ax_mps2 = (sm_vx - self._prev_smoothed_vel[0]) / dt
                ay_mps2 = (sm_vy - self._prev_smoothed_vel[1]) / dt
                az_mps2 = (sm_vz - self._prev_smoothed_vel[2]) / dt

                speed = math.sqrt(sm_vx * sm_vx + sm_vy * sm_vy + sm_vz * sm_vz)

                lin_scale = (self.sensitivity * 0.48) / self.GRAVITY_MPS2
                lin_gx = ax_mps2 * lin_scale
                lin_gy = ay_mps2 * lin_scale
                lin_gz = -az_mps2 * lin_scale

                v_rad = sm_vx * ux + sm_vy * uy + sm_vz * uz
                v_tang_x = sm_vx - v_rad * ux
                v_tang_y = sm_vy - v_rad * uy
                v_tang_z = sm_vz - v_rad * uz
                v_tang_sq = v_tang_x * v_tang_x + v_tang_y * v_tang_y + v_tang_z * v_tang_z

                cent_mps2 = v_tang_sq / max(0.25, flen)
                cent_scale = (self.sensitivity * 0.16) / self.GRAVITY_MPS2
                cent_gx = ux * cent_mps2 * cent_scale
                cent_gy = uy * cent_mps2 * cent_scale
                cent_gz = (-uz) * cent_mps2 * cent_scale

                self._prev_smoothed_vel = [sm_vx, sm_vy, sm_vz]
                self._smoothed_vel = [sm_vx, sm_vy, sm_vz]
            elif dt > 0.25:
                self._smoothed_vel = [0.0, 0.0, 0.0]
                self._prev_smoothed_vel = [0.0, 0.0, 0.0]

        self._prev_pos = (hx, hy, hz)
        self._prev_time = now
        self._latest_speed = speed

        raw_gx = grav_x + lin_gx + cent_gx
        raw_gy = grav_y + lin_gy + cent_gy
        raw_gz = grav_z + lin_gz + cent_gz

        if speed >= 0.85:
            alpha = 0.72
        elif speed <= 0.20:
            alpha = 0.35
        else:
            ratio = (speed - 0.20) / (0.85 - 0.20)
            alpha = 0.35 + ratio * (0.72 - 0.35)
        self._latest_alpha = alpha

        sx = alpha * raw_gx + (1.0 - alpha) * self._smoothed_accel[0]
        sy = alpha * raw_gy + (1.0 - alpha) * self._smoothed_accel[1]
        sz = alpha * raw_gz + (1.0 - alpha) * self._smoothed_accel[2]

        vmag = math.sqrt(sx * sx + sy * sy + sz * sz)
        if vmag > self.MAX_G:
            scale = self.MAX_G / vmag
            sx *= scale
            sy *= scale
            sz *= scale

        sx = max(-self.MAX_G, min(self.MAX_G, sx))
        sy = max(-self.MAX_G, min(self.MAX_G, sy))
        sz = max(-self.MAX_G, min(self.MAX_G, sz))

        self._smoothed_accel = (round(sx, 4), round(sy, 4), round(sz, 4))
        return self._smoothed_accel


class _MinimalWebSocketClient:
    """
    Lightweight, zero-dependency RFC 6455 WebSocket client supporting both
    TLS/SSL (wss://, used by Just Dance 2022 CivetWeb) and plain TCP (ws://) fallback.
    """

    def __init__(self, host: str, port: int, path: str = WS_ENDPOINT, subprotocol: Optional[str] = WS_SUBPROTOCOL) -> None:
        self.host = host
        self.port = int(port)
        self.path = path
        self.subprotocol = subprotocol
        self._sock: Optional[socket.socket] = None
        self._rx_buf = bytearray()
        self._send_lock = threading.Lock()
        self.connected = False
        self.is_tls = False

    def _open_socket(self, timeout: float, use_tls: bool) -> socket.socket:
        raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw_sock.settimeout(timeout)
        raw_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        try:
            raw_sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except OSError:
            pass
        raw_sock.connect((self.host, self.port))
        if not use_tls:
            return raw_sock

        try:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            tls_sock = ctx.wrap_socket(raw_sock, server_hostname=self.host)
            tls_sock.settimeout(timeout)
            return tls_sock
        except Exception:
            try:
                raw_sock.close()
            except OSError:
                pass
            raise

    def connect(self, timeout: float = 2.5, prefer_tls: bool = True) -> None:
        self.close()
        sock: Optional[socket.socket] = None
        modes = [True, False] if prefer_tls else [False, True]
        last_err: Optional[Exception] = None

        for use_tls in modes:
            try:
                sock = self._open_socket(timeout=timeout, use_tls=use_tls)
                self._perform_ws_handshake(sock)
                self.is_tls = use_tls
                break
            except Exception as err:
                last_err = err
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass
                    sock = None

        if sock is None:
            raise ConnectionError(f"Failed to connect WebSocket on {self.host}:{self.port}: {last_err}")

        sock.settimeout(0.02)
        self._sock = sock
        self.connected = True

    def _perform_ws_handshake(self, sock: socket.socket) -> None:
        key_bytes = os.urandom(16)
        ws_key = base64.b64encode(key_bytes).decode("ascii")

        headers = [
            f"GET {self.path} HTTP/1.1",
            f"Host: {self.host}:{self.port}",
            "Upgrade: websocket",
            "Connection: Upgrade",
            f"Sec-WebSocket-Key: {ws_key}",
            "Sec-WebSocket-Version: 13",
        ]
        if self.subprotocol:
            headers.append(f"Sec-WebSocket-Protocol: {self.subprotocol}")
            headers.append("Origin: https://ubisoft.com")
        else:
            headers.append(f"Origin: http://{self.host}:{self.port}")
        headers.extend(["", ""])
        request_data = "\r\n".join(headers).encode("ascii")
        sock.sendall(request_data)

        response = b""
        while b"\r\n\r\n" not in response:
            chunk = sock.recv(1024)
            if not chunk:
                raise ConnectionError("Server closed connection during HTTP handshake.")
            response += chunk
            if len(response) > 8192:
                raise ConnectionError("WebSocket HTTP header exceeded size limit.")

        header_part, leftover = response.split(b"\r\n\r\n", 1)
        status_line = header_part.splitlines()[0].decode("latin1", errors="replace")
        if "101" not in status_line:
            raise ConnectionError(f"WebSocket handshake rejected: {status_line}")

        expected_accept = base64.b64encode(
            hashlib.sha1((ws_key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
        ).decode("ascii")
        if expected_accept.encode("ascii") not in header_part:
            raise ConnectionError("Invalid Sec-WebSocket-Accept key.")

        self._rx_buf.clear()
        if leftover:
            self._rx_buf.extend(leftover)

    def send_text(self, text: str) -> None:
        if not self.connected or self._sock is None:
            raise ConnectionError("WebSocket not connected.")
        payload = text.encode("utf-8")
        length = len(payload)

        frame = bytearray()
        frame.append(0x81)

        mask_key = os.urandom(4)
        if length <= 125:
            frame.append(0x80 | length)
        elif length <= 65535:
            frame.append(0x80 | 126)
            frame.extend(struct.pack("!H", length))
        else:
            frame.append(0x80 | 127)
            frame.extend(struct.pack("!Q", length))

        frame.extend(mask_key)
        masked_payload = bytearray(length)
        for i in range(length):
            masked_payload[i] = payload[i] ^ mask_key[i & 3]
        frame.extend(masked_payload)

        with self._send_lock:
            try:
                self._sock.sendall(frame)
            except (socket.timeout, ssl.SSLWantWriteError, BlockingIOError):
                pass

    def send_binary(self, data: bytes) -> None:
        if not self.connected or self._sock is None:
            raise ConnectionError("WebSocket not connected.")
        length = len(data)
        frame = bytearray()
        frame.append(0x82)

        mask_key = os.urandom(4)
        if length <= 125:
            frame.append(0x80 | length)
        elif length <= 65535:
            frame.append(0x80 | 126)
            frame.extend(struct.pack("!H", length))
        else:
            frame.append(0x80 | 127)
            frame.extend(struct.pack("!Q", length))

        frame.extend(mask_key)
        masked_payload = bytearray(length)
        for i in range(length):
            masked_payload[i] = data[i] ^ mask_key[i & 3]
        frame.extend(masked_payload)

        with self._send_lock:
            try:
                self._sock.sendall(frame)
            except (socket.timeout, ssl.SSLWantWriteError, BlockingIOError):
                pass

    def _recv_exact(self, n: int) -> bytes:
        assert self._sock is not None
        while len(self._rx_buf) < n:
            try:
                chunk = self._sock.recv(max(1024, n - len(self._rx_buf)))
            except (ssl.SSLWantReadError, BlockingIOError):
                time.sleep(0.005)
                continue
            if not chunk:
                raise ConnectionError("Connection closed by game.")
            self._rx_buf.extend(chunk)
        out = bytes(self._rx_buf[:n])
        del self._rx_buf[:n]
        return out

    def recv_messages(self) -> List[str]:
        """Reads any available WebSocket text frames without blocking longer than socket timeout."""
        if not self.connected or self._sock is None:
            return []

        messages: List[str] = []
        while True:
            if len(self._rx_buf) < 2:
                try:
                    chunk = self._sock.recv(2048)
                    if not chunk:
                        raise ConnectionError("WebSocket connection closed.")
                    self._rx_buf.extend(chunk)
                except (socket.timeout, ssl.SSLWantReadError, BlockingIOError):
                    break

            if len(self._rx_buf) < 2:
                break

            hdr = self._recv_exact(2)
            b0, b1 = hdr[0], hdr[1]
            opcode = b0 & 0x0F
            masked = (b1 & 0x80) != 0
            length = b1 & 0x7F

            self._sock.settimeout(1.0)
            try:
                if length == 126:
                    length = struct.unpack("!H", self._recv_exact(2))[0]
                elif length == 127:
                    length = struct.unpack("!Q", self._recv_exact(8))[0]

                mask_key = self._recv_exact(4) if masked else b""
                payload = bytearray(self._recv_exact(length)) if length > 0 else bytearray()
            finally:
                self._sock.settimeout(0.02)

            if masked and mask_key:
                for i in range(len(payload)):
                    payload[i] ^= mask_key[i & 3]

            if opcode == 0x1:
                messages.append(payload.decode("utf-8", errors="replace"))
            elif opcode == 0x8:
                self.close()
                raise ConnectionError("WebSocket server sent CLOSE frame.")
            elif opcode == 0x9:
                self._send_pong(bytes(payload))

        return messages

    def _send_pong(self, payload: bytes) -> None:
        if not self.connected or self._sock is None:
            return
        mask_key = os.urandom(4)
        frame = bytearray([0x8A, 0x80 | (len(payload) & 0x7F)])
        frame.extend(mask_key)
        for i, b in enumerate(payload[:125]):
            frame.append(b ^ mask_key[i & 3])
        with self._send_lock:
            try:
                self._sock.sendall(frame)
            except OSError:
                pass

    def _send_close_frame(self, code: int = 1000) -> None:
        if not self.connected or self._sock is None:
            return
        payload = struct.pack("!H", code)
        mask_key = os.urandom(4)
        frame = bytearray([0x88, 0x80 | 2])
        frame.extend(mask_key)
        for i, b in enumerate(payload):
            frame.append(b ^ mask_key[i & 3])
        with self._send_lock:
            try:
                self._sock.sendall(frame)
            except OSError:
                pass

    def close(self) -> None:
        if self.connected and self._sock is not None:
            try:
                self._send_close_frame(1000)
            except Exception:
                pass
        self.connected = False
        self._rx_buf.clear()
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


class AdaptiveCalibrationTuner:
    """
    Dynamically adjusts the hand acceleration sensitivity based on in-game scoring feedback
    (PERFECT, SUPER, GOOD, OK, MISS, YEAH) received from Just Dance 2022 via WebSocket.
    """

    def __init__(self, base_sensitivity: float = 1.2) -> None:
        self.base_sensitivity: float = float(base_sensitivity)
        self.multiplier: float = 1.0
        self.enabled: bool = False
        self.history: List[str] = []
        self.counts: Dict[str, int] = {
            "PERFECT": 0,
            "SUPER": 0,
            "GOOD": 0,
            "OK": 0,
            "MISS": 0,
            "YEAH": 0,
        }
        self.total_moves: int = 0
        self._last_adjust_ts: float = 0.0

    @property
    def current_sensitivity(self) -> float:
        return round(self.base_sensitivity * self.multiplier, 2)

    def reset_song(self, song_name: str = "") -> None:
        self.history.clear()
        self.counts = {
            "PERFECT": 0,
            "SUPER": 0,
            "GOOD": 0,
            "OK": 0,
            "MISS": 0,
            "YEAH": 0,
        }
        self.total_moves = 0
        self._last_adjust_ts = time.perf_counter()

    def on_feedback(
        self,
        rating: str,
        current_speed: float = 0.0,
        current_accel: Tuple[float, float, float] = (0.08, 0.38, 0.75),
    ) -> float:
        rating_up = rating.strip().upper()
        if rating_up not in self.counts:
            synonyms = {
                "GOLD": "YEAH",
                "PERFECT+": "PERFECT",
                "SUPER+": "SUPER",
                "POOR": "OK",
                "BAD": "MISS",
            }
            rating_up = synonyms.get(rating_up, "")
            if not rating_up or rating_up not in self.counts:
                return self.multiplier

        self.counts[rating_up] += 1
        self.total_moves += 1
        self.history.append(rating_up)
        now = time.perf_counter()

        if not self.enabled:
            return self.multiplier

        if now - self._last_adjust_ts < 1.5:
            return self.multiplier

        mag = math.sqrt(sum(a * a for a in current_accel))

        if rating_up in ("OK", "GOOD") and (current_speed > 0.8 or mag > 2.0):
            self.multiplier = min(2.0, self.multiplier + 0.03)
            self._last_adjust_ts = now
        elif rating_up == "MISS" and mag > 3.5:
            self.multiplier = max(0.75, self.multiplier - 0.02)
            self._last_adjust_ts = now

        return self.multiplier

    def get_summary(self) -> Dict[str, Any]:
        return {
            "total_moves": self.total_moves,
            "counts": dict(self.counts),
            "base_sensitivity": round(self.base_sensitivity, 2),
            "multiplier": round(self.multiplier, 3),
            "current_sensitivity": self.current_sensitivity,
        }


def find_just_dance_pids() -> List[int]:
    """Finds PIDs of running Just Dance PC processes (Legacy.exe, JustDance.exe)."""
    pids: List[int] = []
    if sys.platform != "win32":
        return pids
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        TH32CS_SNAPPROCESS = 0x00000002

        class PROCESSENTRY32(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_char * 260),
            ]

        hSnapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if not hSnapshot or hSnapshot == wintypes.HANDLE(-1).value:
            return pids

        pe = PROCESSENTRY32()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32)
        if kernel32.Process32First(hSnapshot, ctypes.byref(pe)):
            while True:
                name = pe.szExeFile.decode("latin1", errors="ignore").lower()
                if any(k in name for k in ("jd20", "jd21", "jd22", "justdance", "just dance")):
                    pids.append(pe.th32ProcessID)
                if not kernel32.Process32Next(hSnapshot, ctypes.byref(pe)):
                    break
        kernel32.CloseHandle(hSnapshot)
    except Exception:
        pass
    return pids


_RPM_LOCK = threading.Lock()
_RPM_CHUNK_SIZE = 1024 * 1024  # 1 MB reusable scratch buffer (zero per-scan heap allocation)
_RPM_SHARED_BUF = None


def detect_active_song_from_game_process() -> str:
    """
    Scans committed private data memory regions of any running Just Dance process
    to locate the actively loaded map video stream (/map/<MapName>/...webm).
    """
    global _RPM_SHARED_BUF
    if sys.platform != "win32":
        return ""
    pids = find_just_dance_pids()
    if not pids:
        return ""

    if not _RPM_LOCK.acquire(blocking=False):
        return ""

    try:
        import ctypes
        from ctypes import wintypes

        if _RPM_SHARED_BUF is None:
            _RPM_SHARED_BUF = ctypes.create_string_buffer(_RPM_CHUNK_SIZE)

        kernel32 = ctypes.windll.kernel32
        PROCESS_VM_READ = 0x0010
        PROCESS_QUERY_INFORMATION = 0x0400
        MEM_COMMIT = 0x1000
        MEM_IMAGE = 0x1000000
        PAGE_NOACCESS = 0x01
        PAGE_GUARD = 0x100
        PAGE_EXECUTE_MASK = 0xF0

        if ctypes.sizeof(ctypes.c_void_p) == 8:
            class MBI(ctypes.Structure):
                _fields_ = [
                    ("BaseAddress", ctypes.c_uint64),
                    ("AllocationBase", ctypes.c_uint64),
                    ("AllocationProtect", wintypes.DWORD),
                    ("Alignment1", wintypes.DWORD),
                    ("RegionSize", ctypes.c_uint64),
                    ("State", wintypes.DWORD),
                    ("Protect", wintypes.DWORD),
                    ("Type", wintypes.DWORD),
                    ("Alignment2", wintypes.DWORD),
                ]
        else:
            class MBI(ctypes.Structure):
                _fields_ = [
                    ("BaseAddress", ctypes.c_void_p),
                    ("AllocationBase", ctypes.c_void_p),
                    ("AllocationProtect", wintypes.DWORD),
                    ("RegionSize", ctypes.c_size_t),
                    ("State", wintypes.DWORD),
                    ("Protect", wintypes.DWORD),
                    ("Type", wintypes.DWORD),
                ]

        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.VirtualQueryEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(MBI), ctypes.c_size_t]
        kernel32.VirtualQueryEx.restype = ctypes.c_size_t
        kernel32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        kernel32.ReadProcessMemory.restype = wintypes.BOOL

        mbi = MBI()
        pattern_webm = re.compile(rb"/map/([A-Za-z0-9_\-]+)/\1(_(ULTRA|HIGH|MID|LOW))?\.webm")

        for pid in pids:
            h = kernel32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
            if not h:
                continue
            addr = 0
            found_map = ""
            try:
                while kernel32.VirtualQueryEx(h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
                    prot = int(mbi.Protect)
                    if (
                        mbi.State == MEM_COMMIT
                        and mbi.Type != MEM_IMAGE
                        and (prot & (PAGE_NOACCESS | PAGE_GUARD | PAGE_EXECUTE_MASK)) == 0
                    ):
                        sz = int(mbi.RegionSize)
                        if 4096 <= sz <= 8 * 1024 * 1024:
                            offset = 0
                            while offset < sz:
                                chunk_len = min(_RPM_CHUNK_SIZE, sz - offset)
                                br = ctypes.c_size_t(0)
                                if kernel32.ReadProcessMemory(
                                    h,
                                    ctypes.c_void_p(int(mbi.BaseAddress) + offset),
                                    _RPM_SHARED_BUF,
                                    chunk_len,
                                    ctypes.byref(br),
                                ):
                                    m = pattern_webm.search(_RPM_SHARED_BUF.raw[:br.value])
                                    if m:
                                        found_map = m.group(1).decode("latin1", errors="ignore")
                                        break
                                offset += chunk_len
                            if found_map:
                                break
                    addr += mbi.RegionSize
            finally:
                kernel32.CloseHandle(h)

            if found_map:
                title = re.sub(r"([a-z])([A-Z])", r"\1 \2", found_map)
                title = title.replace("ALT", " (Alternate)").replace("DLC", " (DLC)")
                return title
    except Exception:
        pass
    finally:
        _RPM_LOCK.release()
    return ""


__all__ = [
    "WS_SUBPROTOCOL_V2",
    "WS_SUBPROTOCOL_V1",
    "WS_SUBPROTOCOL",
    "WS_ENDPOINT",
    "UDP_DISCOVERY_PORT_TX",
    "UDP_DISCOVERY_PORT_RX",
    "UDP_DISCOVERY_MAGIC",
    "PHONE_INPUT_HASHES",
    "JOINT_SHOULDER_LEFT",
    "JOINT_ELBOW_LEFT",
    "JOINT_WRIST_LEFT",
    "JOINT_HAND_LEFT",
    "JOINT_SHOULDER_RIGHT",
    "JOINT_ELBOW_RIGHT",
    "JOINT_WRIST_RIGHT",
    "JOINT_HAND_RIGHT",
    "HandAccelerometer",
    "_MinimalWebSocketClient",
    "AdaptiveCalibrationTuner",
    "find_just_dance_pids",
    "detect_active_song_from_game_process",
]
