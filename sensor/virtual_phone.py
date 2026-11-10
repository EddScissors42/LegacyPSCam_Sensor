"""
Legacy PSCam Sensor — Virtual Phone Controller (UbiArt Smartphone Protocol)
Emulates the official Just Dance Controller App over local WebSocket (/smartphone)
and converts 3D hand tracking from the camera into 3-axis accelerometer (G-force)
data + menu navigation commands.

Uses only Python standard library modules (socket, hashlib, base64, struct, json,
threading, time, math).
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import queue
import socket
import ssl
import struct
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple


# UbiArt Smartphone Scoring WebSocket constants
# Supports both v1 (Just Dance 2017 / 2018 Legacy / Dreyn) and v2 (Just Dance 2020-2022)
WS_SUBPROTOCOL = "v1.phonescoring.jd.ubisoft.com, v2.phonescoring.jd.ubisoft.com"
WS_ENDPOINT = "/smartphone"
UDP_DISCOVERY_PORT_TX = 6000
UDP_DISCOVERY_PORT_RX = 7000
UDP_DISCOVERY_MAGIC = b"phonescoring.jd.ubisoft.com"

# UbiArt StringID hashes for JD_Input_PhoneCommandData (verified from jd2022.exe)
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
    (where 1.0 G = 9.81 m/s², clamped to [-8.0, 8.0] G).

    Features:
      1. Dynamic Adaptive EMA filter:
         - Fast gestures / snappy moves (> 0.85 m/s): alpha = 0.95 (zero lag, true peak G-force for "Perfect" score).
         - Rest / stationary (< 0.20 m/s): alpha = 0.45 (solid anti-jitter, stable gravity orientation).
      2. Centripetal / Rotational Acceleration (arm arc & windmill sweeps):
         Simulates outward centrifugal force (v_tang^2 / L) along the forearm axis.
      3. Physical Linear G-Force scaling:
         Calibrated to hit 3.5G - 5.5G peaks on fast rhythmic moves matching Just Dance's HighThreshold.
      4. Hand-grip positioning:
         Directly tracks the hand anchor where the smartphone is gripped.
    """

    MAX_G: float = 8.0
    GRAVITY_MPS2: float = 9.81

    def __init__(self, hand: str = "right", sensitivity: float = 1.2) -> None:
        self.hand = hand.lower() if hand.lower() in ("left", "right") else "right"
        self.sensitivity = max(0.2, min(4.0, float(sensitivity)))

        self._prev_pos: Optional[Tuple[float, float, float]] = None
        self._prev_vel: Tuple[float, float, float] = (0.0, 0.0, 0.0)
        self._prev_time: Optional[float] = None
        self._smoothed_accel: Tuple[float, float, float] = (0.0, -1.0, 0.0)
        self._latest_speed: float = 0.0
        self._latest_alpha: float = 0.45

    @property
    def latest_speed(self) -> float:
        return self._latest_speed

    @property
    def latest_alpha(self) -> float:
        return self._latest_alpha

    def reset(self) -> None:
        """Resets velocity/position history."""
        self._prev_pos = None
        self._prev_vel = (0.0, 0.0, 0.0)
        self._prev_time = None
        self._smoothed_accel = (0.0, -1.0, 0.0)
        self._latest_speed = 0.0
        self._latest_alpha = 0.45

    def update(
        self,
        kinect_joints: List[Tuple[float, float, float, float]],
        is_tracked: bool,
        now: Optional[float] = None,
    ) -> Tuple[float, float, float]:
        """
        Computes [ax, ay, az] in G-units from the 20 Kinect joints.
        Combines:
          1. Dynamic linear acceleration (second derivative of hand position).
          2. Centripetal / centrifugal acceleration along forearm axis during swings/rotations.
          3. Forearm orientation gravity projection (1G downward reaction force).
          4. Adaptive EMA filter matching dance velocity (alpha = 0.45 rest -> 0.95 fast move).
        """
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

        # Check joint confidence
        if hand[3] < 0.15 and wrist[3] < 0.15:
            return self._smoothed_accel

        # Hand position: use hand joint (or blend slightly with wrist if hand confidence is low)
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
            ux, uy, uz = 0.0, -1.0, 0.0

        # Project 1G static gravity onto phone local axes based on forearm orientation
        # When hand is relaxed down (uy ~ -1), ay ~ -0.98G; raised up (uy ~ +1), ay ~ +0.98G
        grav_x = ux * 0.98
        grav_y = uy * 0.98
        grav_z = uz * 0.98

        # 2. Dynamic linear acceleration and centripetal force
        lin_gx, lin_gy, lin_gz = 0.0, 0.0, 0.0
        cent_gx, cent_gy, cent_gz = 0.0, 0.0, 0.0
        speed = 0.0

        if self._prev_pos is not None and self._prev_time is not None:
            dt = now - self._prev_time
            if 0.004 <= dt <= 0.25:
                vx = (hx - self._prev_pos[0]) / dt
                vy = (hy - self._prev_pos[1]) / dt
                vz = (hz - self._prev_pos[2]) / dt
                speed = math.sqrt(vx * vx + vy * vy + vz * vz)

                # Linear acceleration (m/s²)
                ax_mps2 = (vx - self._prev_vel[0]) / dt
                ay_mps2 = (vy - self._prev_vel[1]) / dt
                az_mps2 = (vz - self._prev_vel[2]) / dt

                # Physical G-force scaling (sens=1.2 gives ~3.5G-5.5G on fast dance moves)
                lin_scale = (self.sensitivity * 0.85) / self.GRAVITY_MPS2
                lin_gx = ax_mps2 * lin_scale
                lin_gy = ay_mps2 * lin_scale
                lin_gz = az_mps2 * lin_scale

                # Centrifugal component (rotational arm swings, windmills, sweeps)
                # Adds radial outward acceleration along forearm vector: a_c = v_tang^2 / L
                v_rad = vx * ux + vy * uy + vz * uz
                v_tang_x = vx - v_rad * ux
                v_tang_y = vy - v_rad * uy
                v_tang_z = vz - v_rad * uz
                v_tang_sq = v_tang_x * v_tang_x + v_tang_y * v_tang_y + v_tang_z * v_tang_z

                cent_mps2 = v_tang_sq / max(0.20, flen)
                cent_scale = (self.sensitivity * 0.65) / self.GRAVITY_MPS2
                cent_gx = ux * cent_mps2 * cent_scale
                cent_gy = uy * cent_mps2 * cent_scale
                cent_gz = uz * cent_mps2 * cent_scale

                self._prev_vel = (vx, vy, vz)
            elif dt > 0.25:
                self._prev_vel = (0.0, 0.0, 0.0)

        self._prev_pos = (hx, hy, hz)
        self._prev_time = now
        self._latest_speed = speed

        raw_gx = grav_x + lin_gx + cent_gx
        raw_gy = grav_y + lin_gy + cent_gy
        raw_gz = grav_z + lin_gz + cent_gz

        # Clamp to [-MAX_G, +MAX_G]
        clamped_x = max(-self.MAX_G, min(self.MAX_G, raw_gx))
        clamped_y = max(-self.MAX_G, min(self.MAX_G, raw_gy))
        clamped_z = max(-self.MAX_G, min(self.MAX_G, raw_gz))

        # Dynamic Adaptive EMA filter:
        # Fast dance beats (speed >= 0.85 m/s): alpha = 0.95 (virtually zero lag, crisp peak)
        # Slow / resting (speed <= 0.20 m/s): alpha = 0.45 (smooth anti-jitter)
        if speed >= 0.85:
            alpha = 0.95
        elif speed <= 0.20:
            alpha = 0.45
        else:
            ratio = (speed - 0.20) / (0.85 - 0.20)
            alpha = 0.45 + ratio * (0.95 - 0.45)
        self._latest_alpha = alpha

        sx = alpha * clamped_x + (1.0 - alpha) * self._smoothed_accel[0]
        sy = alpha * clamped_y + (1.0 - alpha) * self._smoothed_accel[1]
        sz = alpha * clamped_z + (1.0 - alpha) * self._smoothed_accel[2]

        self._smoothed_accel = (round(sx, 4), round(sy, 4), round(sz, 4))
        return self._smoothed_accel


class _MinimalWebSocketClient:
    """
    Lightweight, zero-dependency RFC 6455 WebSocket client supporting both
    TLS/SSL (wss://, used by Just Dance 2022 CivetWeb) and plain TCP (ws://) fallback.
    Supports text frames, ping/pong, buffered reads, and clean close.
    """

    def __init__(self, host: str, port: int, path: str = WS_ENDPOINT, subprotocol: str = WS_SUBPROTOCOL) -> None:
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

        # Set a short read timeout for non-blocking polling loop
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
            f"Sec-WebSocket-Protocol: {self.subprotocol}",
            "Origin: https://ubisoft.com",
            "",
            "",
        ]
        request_data = "\r\n".join(headers).encode("ascii")
        sock.sendall(request_data)

        # Read HTTP response header until \r\n\r\n
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

        # Client-to-server frames MUST be masked per RFC 6455
        frame = bytearray()
        frame.append(0x81)  # FIN=1, opcode=1 (text)

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
                # Game window may be temporarily unfocused and its recv buffer full; ignore transient block
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

            # Temporarily increase timeout to finish reading frame body
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

            if opcode == 0x1:  # Text frame
                messages.append(payload.decode("utf-8", errors="replace"))
            elif opcode == 0x8:  # Close frame
                self.close()
                raise ConnectionError("WebSocket server sent CLOSE frame.")
            elif opcode == 0x9:  # Ping -> send Pong
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
        """Sends an RFC 6455 opcode 0x8 Close frame so the game immediately frees the player slot."""
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


class VirtualPhoneController:
    """
    Manages the background WebSocket connection to Just Dance (UbiArt Smartphone Manager),
    handles the 5-step pairing handshake over WSS/TLS (or WS), stays alive even when the
    game window is unfocused (AFK/paused main loop), streams 60Hz accelerometer samples
    from camera hand tracking, and dispatches menu navigation commands.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8080,
        hand: str = "right",
        sensitivity: float = 1.2,
        phone_name: str = "Legacy PSCam Phone",
    ) -> None:
        self.host = host
        self.port = int(port)
        self.phone_name = phone_name
        self.accelerometer = HandAccelerometer(hand=hand, sensitivity=sensitivity)

        self._enabled = False
        self._connected = False
        self._handshake_complete = False
        self._scoring_enabled = True
        self._phone_id: int = 0
        self._player_id: int = 0
        self._player_name: str = ""
        self._pairing_code: str = ""
        self._status_text: str = "Disabled"
        self._last_error: str = ""

        # Dynamic command overrides supplied by JD_InputCollectionPhoneData
        self._available_inputs: Dict[str, str] = {}

        self._latest_accel: Tuple[float, float, float] = (0.0, -1.0, 0.0)
        self._last_joint_update_ts: float = 0.0
        self._shake_until_ts: float = 0.0
        self._ftue_until_ts: float = 0.0

        # Telemetry CSV logging (for dance diagnostic and mobile phone comparison)
        self._logging_enabled = False
        self._log_file = None
        self._log_path = ""
        self._log_lock = threading.Lock()

        self._cmd_queue: "queue.Queue[str]" = queue.Queue()
        self._stop_event = threading.Event()
        self._reconnect_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public Properties & Configuration
    # ------------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def connected(self) -> bool:
        return self._connected and self._handshake_complete

    @property
    def status_text(self) -> str:
        return self._status_text

    @property
    def phone_id(self) -> int:
        return self._phone_id

    @property
    def latest_accel(self) -> Tuple[float, float, float]:
        return self._latest_accel

    @property
    def is_logging(self) -> bool:
        return self._logging_enabled

    @property
    def log_path(self) -> str:
        return self._log_path

    def set_logging(self, enabled: bool, custom_path: Optional[str] = None) -> str:
        """
        Starts or stops CSV logging of accelerometer telemetry.
        Returns the active log file path when starting, or empty string when stopping.
        """
        with self._log_lock:
            if self._log_file is not None:
                try:
                    self._log_file.flush()
                    self._log_file.close()
                except OSError:
                    pass
                self._log_file = None

            self._logging_enabled = bool(enabled)
            if self._logging_enabled:
                if custom_path:
                    path = custom_path
                else:
                    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    logs_dir = os.path.join(base_dir, "logs")
                    os.makedirs(logs_dir, exist_ok=True)
                    path = os.path.join(logs_dir, f"vphone_accel_{int(time.time())}.csv")

                self._log_path = path
                self._log_file = open(path, "w", encoding="utf-8")
                self._log_file.write("timestamp_ms,ax,ay,az,speed_mps,alpha,hand_x,hand_y,hand_z,is_tracked\n")
                return path
            else:
                self._log_path = ""
                return ""

    def configure(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        hand: Optional[str] = None,
        sensitivity: Optional[float] = None,
        phone_name: Optional[str] = None,
    ) -> None:
        reconnect_needed = False
        with self._lock:
            if host is not None and host.strip() and host.strip() != self.host:
                self.host = host.strip()
                reconnect_needed = True
            if port is not None and int(port) != self.port:
                self.port = int(port)
                reconnect_needed = True
            if hand is not None:
                self.accelerometer.hand = hand.lower() if hand.lower() in ("left", "right") else "right"
            if sensitivity is not None:
                self.accelerometer.sensitivity = max(0.2, min(4.0, float(sensitivity)))
            if phone_name is not None and phone_name.strip():
                self.phone_name = phone_name.strip()

        if reconnect_needed and self._enabled:
            self.request_reconnect()

    def set_enabled(self, enabled: bool) -> None:
        if enabled == self._enabled:
            return
        self._enabled = bool(enabled)
        if self._enabled:
            self.start()
        else:
            self.stop()

    def start(self) -> None:
        self._enabled = True
        if self._thread is not None and self._thread.is_alive():
            self._reconnect_event.set()
            return
        self._stop_event.clear()
        self._reconnect_event.clear()
        self._status_text = f"Connecting to {self.host}:{self.port}..."
        self._thread = threading.Thread(target=self._worker_loop, name="VirtualPhoneWorker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._enabled = False
        self._stop_event.set()
        self._reconnect_event.set()
        self._connected = False
        self._handshake_complete = False
        self._status_text = "Disabled"
        if self._logging_enabled:
            self.set_logging(False)

    def request_reconnect(self) -> None:
        """Forces an immediate reconnection attempt on the worker thread."""
        if not self._enabled:
            self.start()
        else:
            self._status_text = f"Reconnecting to {self.host}:{self.port}..."
            self._reconnect_event.set()

    # ------------------------------------------------------------------
    # Camera Pose Tracking Feed
    # ------------------------------------------------------------------
    def update_from_joints(
        self,
        kinect_joints: List[Tuple[float, float, float, float]],
        is_tracked: bool,
    ) -> Tuple[float, float, float]:
        """
        Called by TrackingSession every camera frame to update the 3D hand accelerometer.
        """
        now = time.perf_counter()
        accel = self.accelerometer.update(kinect_joints, is_tracked, now=now)
        self._latest_accel = accel
        self._last_joint_update_ts = now

        # Write to CSV log if active
        if self._logging_enabled and self._log_file is not None:
            with self._log_lock:
                if self._log_file is not None:
                    try:
                        hx, hy, hz = 0.0, 0.0, 0.0
                        if is_tracked and len(kinect_joints) >= 12:
                            j_idx = JOINT_HAND_LEFT if self.accelerometer.hand == "left" else JOINT_HAND_RIGHT
                            hx, hy, hz = kinect_joints[j_idx][0], kinect_joints[j_idx][1], kinect_joints[j_idx][2]
                        ts_ms = int(now * 1000)
                        ax, ay, az = accel
                        spd = self.accelerometer.latest_speed
                        alp = self.accelerometer.latest_alpha
                        self._log_file.write(
                            f"{ts_ms},{ax:.4f},{ay:.4f},{az:.4f},{spd:.3f},{alp:.2f},{hx:.3f},{hy:.3f},{hz:.3f},{int(is_tracked)}\n"
                        )
                    except OSError:
                        pass

        return accel

    def update_from_hardware_accel(self, ax: float, ay: float, az: float) -> Tuple[float, float, float]:
        """
        Updates the 3D accelerometer readings directly from a physical hardware IMU
        (e.g. Sony DualShock 4 connected via Bluetooth).
        """
        now = time.perf_counter()
        accel = (float(ax), float(ay), float(az))
        self._latest_accel = accel
        self._last_joint_update_ts = now

        # Write to CSV log if active
        if self._logging_enabled and self._log_file is not None:
            with self._log_lock:
                if self._log_file is not None:
                    try:
                        ts_ms = int(now * 1000)
                        self._log_file.write(
                            f"{ts_ms},{ax:.4f},{ay:.4f},{az:.4f},0.000,1.00,0.000,0.000,0.000,1\n"
                        )
                    except OSError:
                        pass

        return accel

    def trigger_test_shake(self, duration_sec: float = 1.2) -> None:
        """Simulates a rhythmic dance hand shake for testing scoring without camera tracking."""
        self._shake_until_ts = time.perf_counter() + max(0.2, float(duration_sec))

    # ------------------------------------------------------------------
    # Protocol Envelope Builders
    # ------------------------------------------------------------------
    @staticmethod
    def build_root_packet(class_name: str, **fields) -> str:
        """
        Builds a JSON string wrapped in the mandatory UbiArt {"root": {"__class": ...}} envelope.
        """
        inner = {"__class": class_name}
        inner.update(fields)
        return json.dumps({"root": inner}, separators=(",", ":"))

    @classmethod
    def build_scoring_packet(cls, accel_samples: List[Tuple[float, float, float]]) -> str:
        formatted = [[round(float(x), 4), round(float(y), 4), round(float(z), 4)] for x, y, z in accel_samples]
        return cls.build_root_packet("JD_PhoneScoringData", accelData=formatted)

    # ------------------------------------------------------------------
    # Menu & Action Commands
    # ------------------------------------------------------------------
    def send_input(self, action: str) -> None:
        """
        Queues a menu navigation or gameplay shortcut action to the connected game.
        Supported actions:
          - "VALID", "UP", "DOWN", "LEFT", "RIGHT"
          - "BACK" (SHORTCUT_BACK)
          - "START_GAME" (JD_StartGame_PhoneCommandData)
          - "PAUSE" (JD_Pause_PhoneCommandData)
          - "UNPAUSE" (JD_Unpause_PhoneCommandData)
          - "FTUE_FINISH" (PHONE_FTUE_FINISH)
        """
        act = action.upper().strip()
        if act in PHONE_INPUT_HASHES:
            touch_on = self._available_inputs.get(
                "TOUCH_ON",
                self.build_root_packet("JD_TouchFeedback_PhoneCommandData", touchOn=True),
            )
            input_cmd = self._available_inputs.get(
                act,
                self.build_root_packet("JD_Input_PhoneCommandData", input=PHONE_INPUT_HASHES[act]),
            )
            touch_off = self._available_inputs.get(
                "TOUCH_OFF",
                self.build_root_packet("JD_TouchFeedback_PhoneCommandData", touchOn=False),
            )
            self._cmd_queue.put(touch_on)
            self._cmd_queue.put(input_cmd)
            self._cmd_queue.put(touch_off)
        elif act == "BACK":
            self._cmd_queue.put(
                self.build_root_packet("JD_Custom_PhoneCommandData", identifier="SHORTCUT_BACK")
            )
        elif act == "SHORTCUT_VALIDATE":
            self._cmd_queue.put(
                self.build_root_packet("JD_Custom_PhoneCommandData", identifier="SHORTCUT_VALIDATE")
            )
        elif act == "FTUE_FINISH":
            self._cmd_queue.put(
                self.build_root_packet("JD_Custom_PhoneCommandData", identifier="PHONE_FTUE_FINISH")
            )
        elif act == "START_GAME":
            self._cmd_queue.put(self.build_root_packet("JD_StartGame_PhoneCommandData"))
        elif act == "PAUSE":
            self._cmd_queue.put(self.build_root_packet("JD_Pause_PhoneCommandData"))
        elif act == "UNPAUSE":
            self._cmd_queue.put(self.build_root_packet("JD_Unpause_PhoneCommandData", status=1))
        elif act.startswith("COACH_"):
            try:
                coach_id = int(act.split("_", 1)[1])
                self._cmd_queue.put(self.build_root_packet("JD_ChangeCoach_PhoneCommandData", coachId=coach_id))
            except ValueError:
                pass

    # ------------------------------------------------------------------
    # UDP Auto-Discovery (Port 6000 -> 7000)
    # ------------------------------------------------------------------
    @staticmethod
    def discover_server(timeout: float = 1.2) -> Optional[Tuple[str, int, str]]:
        """
        Broadcasts "phonescoring.jd.ubisoft.com" on UDP port 6000 and listens on UDP 7000
        (or ephemeral port) for the game's discovery reply.
        Returns (ip, ws_port, pairing_code) if found, or None.
        """
        rx_sock: Optional[socket.socket] = None
        tx_sock: Optional[socket.socket] = None
        try:
            rx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            rx_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            rx_sock.settimeout(timeout)
            try:
                rx_sock.bind(("", UDP_DISCOVERY_PORT_RX))
            except OSError:
                rx_sock.bind(("", 0))

            tx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            tx_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            tx_sock.settimeout(timeout)

            for target_ip in ("127.0.0.1", "255.255.255.255"):
                try:
                    tx_sock.sendto(UDP_DISCOVERY_MAGIC, (target_ip, UDP_DISCOVERY_PORT_TX))
                except OSError:
                    pass

            data, addr = rx_sock.recvfrom(2048)
            info = json.loads(data.decode("utf-8", errors="replace"))
            pairing_code = str(info.get("pairingCode", ""))
            ws_port = int(info.get("port", 8080))
            return (addr[0], ws_port, pairing_code)
        except Exception:
            return None
        finally:
            if rx_sock is not None:
                try:
                    rx_sock.close()
                except OSError:
                    pass
            if tx_sock is not None:
                try:
                    tx_sock.close()
                except OSError:
                    pass

    # ------------------------------------------------------------------
    # Background WebSocket Worker & Handshake State Machine
    # ------------------------------------------------------------------
    def _worker_loop(self) -> None:
        while not self._stop_event.is_set() and self._enabled:
            self._reconnect_event.clear()

            # Quick UDP discovery check to refresh pairing code / IP if needed
            disc = self.discover_server(timeout=0.35)
            if disc is not None:
                disc_ip, disc_port, disc_code = disc
                self._pairing_code = disc_code
                if self.host in ("127.0.0.1", "localhost", ""):
                    self.port = disc_port

            ws = _MinimalWebSocketClient(self.host, self.port, WS_ENDPOINT, WS_SUBPROTOCOL)
            try:
                code_suffix = f" [Code: {self._pairing_code}]" if self._pairing_code else ""
                self._status_text = f"Connecting to {self.host}:{self.port}{code_suffix}..."
                ws.connect(timeout=2.0, prefer_tls=False)
                self._connected = True
                self._handshake_complete = False
                self._player_name = ""
                proto_tag = "WSS/TLS" if ws.is_tls else "WS"
                self._status_text = f"Connected ({proto_tag}) — Awaiting Handshake..."

                # Step 1: Send JD_PhoneDataCmdHandshakeHello
                hello_pkt = self.build_root_packet(
                    "JD_PhoneDataCmdHandshakeHello",
                    clientVersion="1.0",
                    phoneName=self.phone_name,
                    accelAcquisitionLatency=0.0,
                    accelMaxRange=8.0,
                    jmcsToken="",
                )
                ws.send_text(hello_pkt)
                hello_sent_ts = time.perf_counter()

                last_accel_sent_ts = 0.0
                last_ftue_sent_ts = 0.0
                accel_interval = 1.0 / 60.0  # 60 Hz accelerometer stream

                while not self._stop_event.is_set() and self._enabled and not self._reconnect_event.is_set():
                    # 1. Process incoming messages from Just Dance
                    for raw_msg in ws.recv_messages():
                        self._handle_incoming_message(ws, raw_msg)

                    now = time.perf_counter()

                    # If the game window is unfocused (AFK/paused main loop), CivetWeb accepts the TLS
                    # WebSocket upgrade immediately, but JD_SmartphoneManager::Update only processes
                    # HandshakeHello once the game window regains focus. Keep waiting patiently!
                    if not self._handshake_complete:
                        wait_secs = now - hello_sent_ts
                        if wait_secs >= 1.2:
                            self._status_text = (
                                f"Connected ({proto_tag}{code_suffix}) — Focus game window to activate!"
                            )
                        continue

                    # 1.5 Auto-skip Phone FTUE ("Finish" tutorial steps 1..4) whenever active
                    if now < self._ftue_until_ts and (now - last_ftue_sent_ts) >= 0.40:
                        last_ftue_sent_ts = now
                        ws.send_text(
                            self.build_root_packet("JD_Custom_PhoneCommandData", identifier="PHONE_FTUE_FINISH")
                        )

                    # 2. Flush queued UI / menu commands once handshake is complete
                    while not self._cmd_queue.empty():
                        try:
                            cmd_json = self._cmd_queue.get_nowait()
                            ws.send_text(cmd_json)
                        except queue.Empty:
                            break

                    # 3. Stream accelerometer scoring data at 60 Hz once handshake is complete
                    if (now - last_accel_sent_ts) >= accel_interval:
                        last_accel_sent_ts = now
                        sample = self._compute_current_sample(now)
                        ws.send_text(self.build_scoring_packet([sample]))

            except Exception as exc:
                self._connected = False
                self._handshake_complete = False
                self._last_error = str(exc)
                if self._enabled and not self._stop_event.is_set():
                    code_suffix = f" (Game active • Code: {self._pairing_code})" if self._pairing_code else ""
                    self._status_text = f"Checking game on {self.host}:{self.port}{code_suffix}..."
            finally:
                ws.close()
                self._connected = False
                self._handshake_complete = False

            # Continuous verification every 1.0s when disconnected
            if self._enabled and not self._stop_event.is_set() and not self._reconnect_event.is_set():
                self._reconnect_event.wait(timeout=1.0)

        self._status_text = "Disabled"

    def _compute_current_sample(self, now: float) -> Tuple[float, float, float]:
        """Returns the current accelerometer sample (from test shake, live camera, or idle gravity)."""
        if now < self._shake_until_ts:
            # Generate a strong sinusoidal dance swing across X/Y/Z
            phase = now * 28.0
            sx = round(math.sin(phase) * 3.8, 4)
            sy = round(math.cos(phase * 1.3) * 3.5 - 0.8, 4)
            sz = round(math.sin(phase * 0.7) * 2.5, 4)
            self._latest_accel = (sx, sy, sz)
            return self._latest_accel

        if (now - self._last_joint_update_ts) <= 0.25:
            return self._latest_accel

        # Idle phone resting upright/tilted in hand
        self._latest_accel = (0.0, -1.0, 0.0)
        return self._latest_accel

    def _format_connected_status(self) -> str:
        player_slot = f"Player {self._player_id + 1}"
        player_part = f" • {self._player_name} ({player_slot})" if self._player_name else f" • {player_slot}"
        mode_part = "Scoring Active" if self._scoring_enabled else "Connected to Game"
        return f"{mode_part}{player_part}"

    def _handle_incoming_message(self, ws: _MinimalWebSocketClient, raw_msg: str) -> None:
        try:
            parsed = json.loads(raw_msg)
        except Exception:
            return

        if not isinstance(parsed, dict):
            return

        # Game -> Phone messages may have __class at root or inside "root"
        msg = parsed.get("root", parsed) if isinstance(parsed.get("root"), dict) else parsed
        cls_name = str(msg.get("__class", ""))

        if cls_name == "JD_PhoneDataCmdHandshakeContinue":
            # Step 2: Extract assigned phoneID and reply with JD_PhoneDataCmdSync
            self._phone_id = int(msg.get("phoneID", 0))
            sync_pkt = self.build_root_packet("JD_PhoneDataCmdSync", phoneID=self._phone_id)
            ws.send_text(sync_pkt)
            self._status_text = f"Syncing with Game (ID {self._phone_id})..."

        elif cls_name == "JD_PhoneDataCmdSyncStart":
            # Step 3: Game started sync phase
            if "phoneID" in msg:
                self._phone_id = int(msg.get("phoneID", self._phone_id))

        elif cls_name == "JD_PhoneDataCmdSyncEnd":
            # Step 4: Game finished sync -> Phone replies JD_PhoneDataCmdSyncEnd to enter Connected state
            if "phoneID" in msg:
                self._phone_id = int(msg.get("phoneID", self._phone_id))
            sync_end_pkt = self.build_root_packet("JD_PhoneDataCmdSyncEnd", phoneID=self._phone_id)
            ws.send_text(sync_end_pkt)
            self._handshake_complete = True
            self._status_text = self._format_connected_status()

        elif cls_name == "JD_ProfilePhoneUiData":
            name = str(msg.get("name", "")).strip()
            if name:
                self._player_name = name
            if "playerId" in msg:
                self._player_id = int(msg.get("playerId", 0))
            if not self._handshake_complete:
                self._handshake_complete = True
            self._status_text = self._format_connected_status()

        elif cls_name == "JD_InputCollectionPhoneData":
            avail = msg.get("availableInput")
            if isinstance(avail, dict):
                for k, v in avail.items():
                    if isinstance(k, str) and isinstance(v, str) and v.strip():
                        self._available_inputs[k.upper()] = v
            if not self._handshake_complete:
                self._handshake_complete = True
            self._status_text = self._format_connected_status()

        elif cls_name in ("JD_EnableScoringPhoneData", "JD_SmartphoneEvent_ScoringActivationChanged"):
            self._scoring_enabled = bool(msg.get("enable", msg.get("enabled", True)))
            self._status_text = self._format_connected_status()

        elif cls_name in ("JD_PhoneUiData", "JD_PhoneUiSetupData", "JD_PhoneUiShortcutData", "JD_TriggerTransition_ConsoleCommandData"):
            if not self._handshake_complete:
                self._handshake_complete = True
            if "JD_PhoneUiFTUE" in raw_msg or "PHONE_FTUE_FINISH" in raw_msg:
                self._ftue_until_ts = time.perf_counter() + 4.0
                ws.send_text(
                    self.build_root_packet("JD_Custom_PhoneCommandData", identifier="PHONE_FTUE_FINISH")
                )
            self._status_text = self._format_connected_status()


# Global singleton instance shared between GUI and TrackingSession
_GLOBAL_VIRTUAL_PHONE: Optional[VirtualPhoneController] = None
_GLOBAL_LOCK = threading.Lock()


def get_virtual_phone() -> VirtualPhoneController:
    """Returns the process-wide VirtualPhoneController singleton."""
    global _GLOBAL_VIRTUAL_PHONE
    with _GLOBAL_LOCK:
        if _GLOBAL_VIRTUAL_PHONE is None:
            _GLOBAL_VIRTUAL_PHONE = VirtualPhoneController()
        return _GLOBAL_VIRTUAL_PHONE
