"""
Legacy PSCam Sensor — Virtual Phone Controller (UbiArt Smartphone Protocol)
Emulates the official Just Dance Controller App over local WebSocket (/smartphone)
and converts 3D hand tracking from the camera into 3-axis accelerometer (G-force)
data + menu navigation commands.

Protocol primitives (`HandAccelerometer`, `_MinimalWebSocketClient`,
`AdaptiveCalibrationTuner`, `find_just_dance_pids`, `detect_active_song_from_game_process`)
live in `sensor/vphone_protocol.py` and are re-exported here for backwards compatibility.
"""

from __future__ import annotations

import json
import math
import os
import queue
import re
import socket
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from sensor.vphone_protocol import (
    WS_SUBPROTOCOL_V2,
    WS_SUBPROTOCOL_V1,
    WS_SUBPROTOCOL,
    WS_ENDPOINT,
    UDP_DISCOVERY_PORT_TX,
    UDP_DISCOVERY_PORT_RX,
    UDP_DISCOVERY_MAGIC,
    PHONE_INPUT_HASHES,
    JOINT_SHOULDER_LEFT,
    JOINT_ELBOW_LEFT,
    JOINT_WRIST_LEFT,
    JOINT_HAND_LEFT,
    JOINT_SHOULDER_RIGHT,
    JOINT_ELBOW_RIGHT,
    JOINT_WRIST_RIGHT,
    JOINT_HAND_RIGHT,
    HandAccelerometer,
    _MinimalWebSocketClient,
    AdaptiveCalibrationTuner,
    find_just_dance_pids,
    detect_active_song_from_game_process,
)


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
        self._detected_protocol: str = ""
        self._status_text: str = "Disabled"
        self._last_error: str = ""

        # Coach selection state (for songs with multiple coaches/NPCs)
        self.current_coach_id: int = 0
        self.total_coaches: int = 4

        # Dynamic command overrides supplied by JD_InputCollectionPhoneData
        self._available_inputs: Dict[str, str] = {}

        self._latest_accel: Tuple[float, float, float] = (0.08, 0.38, 0.75)
        self._last_joint_update_ts: float = 0.0
        self._shake_until_ts: float = 0.0
        self._ftue_until_ts: float = 0.0

        # Telemetry CSV logging (for dance diagnostic and mobile phone comparison)
        self._logging_enabled = False
        self._log_file = None
        self._log_path = ""
        self._log_lock = threading.Lock()

        # Song and scoring telemetry state
        self.current_map_name: str = ""
        self.current_song_name: str = ""
        self.is_dancing: bool = False
        self.auto_record_enabled: bool = False
        self.adaptive_tuner = AdaptiveCalibrationTuner(base_sensitivity=self.accelerometer.sensitivity)
        self._last_source: str = "camera"
        self._last_feedback: str = ""
        self.on_song_change: Optional[Callable[[str], None]] = None
        self.on_dance_state_change: Optional[Callable[[bool, str], None]] = None
        self._last_song_query_ts: float = 0.0

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

    @property
    def current_song(self) -> str:
        # Only fall back to external process memory inspection when telemetry recording or
        # auto-record benchmark is explicitly active, throttled to 2.5s intervals.
        if (
            not self.current_map_name
            and self.connected
            and (self.auto_record_enabled or self._logging_enabled)
        ):
            now = time.perf_counter()
            if (now - self._last_song_query_ts) >= 2.5:
                self._last_song_query_ts = now
                detected = detect_active_song_from_game_process()
                if detected:
                    with self._lock:
                        self.current_map_name = detected
                        self.current_song_name = detected
                    if self.on_song_change:
                        try:
                            self.on_song_change(detected)
                        except Exception:
                            pass
        return self.current_map_name or self.current_song_name

    @property
    def auto_record(self) -> bool:
        return self.auto_record_enabled

    @property
    def adaptive_enabled(self) -> bool:
        return self.adaptive_tuner.enabled

    def set_auto_record(self, enabled: bool) -> None:
        self.auto_record_enabled = bool(enabled)

    def set_adaptive_calibration(self, enabled: bool) -> None:
        self.adaptive_tuner.enabled = bool(enabled)

    def set_logging(
        self,
        enabled: bool,
        custom_path: Optional[str] = None,
        source: Optional[str] = None,
        map_name: Optional[str] = None,
    ) -> str:
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
                src = (source or self._last_source or "camera").lower()
                song = map_name or self.current_map_name or "DanceSession"
                clean_song = re.sub(r"[^a-zA-Z0-9_\-]", "", song) or "DanceSession"

                if custom_path:
                    path = custom_path
                else:
                    from sensor.config_manager import get_logs_dir
                    logs_dir = str(get_logs_dir())
                    path = os.path.join(logs_dir, f"{clean_song}_{src}_{int(time.time())}.csv")

                self._log_path = path
                self._log_file = open(path, "w", encoding="utf-8")
                self._log_file.write(
                    "timestamp_ms,ax,ay,az,speed_mps,alpha,hand_x,hand_y,hand_z,is_tracked,source,map_name,feedback\n"
                )
                print(f"[VPHONE] Telemetry recording started: {path}")
                return path
            else:
                old_path = self._log_path
                self._log_path = ""
                if old_path:
                    print(f"[VPHONE] Telemetry recording finished: {old_path}")
                return ""

    def configure(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        hand: Optional[str] = None,
        sensitivity: Optional[float] = None,
        phone_name: Optional[str] = None,
        auto_record: Optional[bool] = None,
        adaptive: Optional[bool] = None,
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
                sens_val = max(0.2, min(4.0, float(sensitivity)))
                self.accelerometer.sensitivity = sens_val
                self.adaptive_tuner.base_sensitivity = sens_val
            if phone_name is not None and phone_name.strip():
                self.phone_name = phone_name.strip()
            if auto_record is not None:
                self.auto_record_enabled = bool(auto_record)
            if adaptive is not None:
                self.adaptive_tuner.enabled = bool(adaptive)

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
        self._last_source = "camera"

        # Apply real-time adaptive sensitivity multiplier if active
        if self.adaptive_tuner.enabled:
            self.accelerometer.sensitivity = self.adaptive_tuner.current_sensitivity

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
                        fb = self._last_feedback
                        self._last_feedback = ""
                        self._log_file.write(
                            f"{ts_ms},{ax:.4f},{ay:.4f},{az:.4f},{spd:.3f},{alp:.2f},{hx:.3f},{hy:.3f},{hz:.3f},{int(is_tracked)},camera,{self.current_map_name},{fb}\n"
                        )
                    except OSError:
                        pass

        return accel

    def update_from_hardware_accel(self, ax: float, ay: float, az: float) -> Tuple[float, float, float]:
        """
        Updates the 3D accelerometer readings directly from a physical hardware IMU
        (e.g. Sony DualShock 4 connected via Bluetooth or USB).
        """
        now = time.perf_counter()
        self._last_source = "ds4"
        accel = (float(ax), float(ay), float(az))
        self._latest_accel = accel
        self._last_joint_update_ts = now

        # Write to CSV log if active
        if self._logging_enabled and self._log_file is not None:
            with self._log_lock:
                if self._log_file is not None:
                    try:
                        ts_ms = int(now * 1000)
                        fb = self._last_feedback
                        self._last_feedback = ""
                        self._log_file.write(
                            f"{ts_ms},{ax:.4f},{ay:.4f},{az:.4f},0.000,1.00,0.000,0.000,0.000,1,ds4,{self.current_map_name},{fb}\n"
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

    def change_coach(self, delta: int = 1) -> int:
        """
        Cycles the selected coach/NPC index in the Just Dance lobby.
        Sends JD_ChangeCoach_PhoneCommandData to the game.
        """
        with self._lock:
            max_c = max(1, self.total_coaches)
            if max_c <= 1:
                print(f"[VPHONE] Solo song (1 coach) — coach change skipped.")
                return 0
            self.current_coach_id = (self.current_coach_id + delta) % max_c
            coach_id = self.current_coach_id

        cmd = self.build_root_packet("JD_ChangeCoach_PhoneCommandData", coachId=coach_id)
        self._cmd_queue.put(cmd)
        print(f"[VPHONE] Switched Coach to: {coach_id + 1} / {self.total_coaches}")
        return coach_id

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

        if act == "VALID":
            if "VALID" in self._available_inputs:
                if "TOUCH_ON" in self._available_inputs:
                    self._cmd_queue.put(self._available_inputs["TOUCH_ON"])
                self._cmd_queue.put(self._available_inputs["VALID"])
                if "TOUCH_OFF" in self._available_inputs:
                    self._cmd_queue.put(self._available_inputs["TOUCH_OFF"])
            elif self._detected_protocol == WS_SUBPROTOCOL_V1:
                # Just Dance 2017/2018 Legacy lobby confirmation is JD_StartGame_PhoneCommandData
                self._cmd_queue.put(self.build_root_packet("JD_StartGame_PhoneCommandData"))
            else:
                self._cmd_queue.put(
                    self.build_root_packet("JD_Input_PhoneCommandData", input=PHONE_INPUT_HASHES["VALID"])
                )
        elif act in PHONE_INPUT_HASHES:
            # Only send TOUCH_ON / TOUCH_OFF if explicitly supplied in availableInput (v2/JD2022)
            # Avoids 1002 CLOSE_PROTOCOL_ERROR on JD2017/2018 Legacy (v1) which lacks touch feedback class
            if "TOUCH_ON" in self._available_inputs:
                self._cmd_queue.put(self._available_inputs["TOUCH_ON"])

            input_cmd = self._available_inputs.get(
                act,
                self.build_root_packet("JD_Input_PhoneCommandData", input=PHONE_INPUT_HASHES[act]),
            )
            self._cmd_queue.put(input_cmd)

            if "TOUCH_OFF" in self._available_inputs:
                self._cmd_queue.put(self._available_inputs["TOUCH_OFF"])
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
                with self._lock:
                    self.current_coach_id = coach_id
                self._cmd_queue.put(self.build_root_packet("JD_ChangeCoach_PhoneCommandData", coachId=coach_id))
            except ValueError:
                pass

    # ------------------------------------------------------------------
    # Game Auto-Discovery (UDP Broadcast for Just Dance)
    # ------------------------------------------------------------------
    @staticmethod
    def discover_server_info(timeout: float = 1.2) -> Optional[Dict[str, Any]]:
        """
        Broadcasts "phonescoring.jd.ubisoft.com" on UDP port 6000 and listens on UDP 7000
        (or ephemeral port) for the game's discovery reply.
        Returns a dict containing ip, port, pairing_code, and protocol, or None.
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

            # Check localhost first (low latency, avoids adapter/VPN IP conflicts)
            tx_sock.sendto(UDP_DISCOVERY_MAGIC, ("127.0.0.1", UDP_DISCOVERY_PORT_TX))
            try:
                rx_sock.settimeout(0.06)
                data, addr = rx_sock.recvfrom(2048)
            except (socket.timeout, OSError):
                # Fallback to local subnet broadcast
                rx_sock.settimeout(timeout)
                tx_sock.sendto(UDP_DISCOVERY_MAGIC, ("255.255.255.255", UDP_DISCOVERY_PORT_TX))
                data, addr = rx_sock.recvfrom(2048)
            info = json.loads(data.decode("utf-8", errors="replace"))
            pairing_code = str(info.get("pairingCode", ""))
            ws_port = int(info.get("port", 8080))
            proto = str(info.get("protocol", "")).strip()
            return {
                "ip": addr[0],
                "port": ws_port,
                "pairing_code": pairing_code,
                "protocol": proto,
            }
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

    @classmethod
    def discover_server(cls, timeout: float = 1.2) -> Optional[Tuple[str, int, str]]:
        """
        Discovers the running Just Dance server.
        Broadcasts "phonescoring.jd.ubisoft.com" on UDP port 6000 and listens on UDP 7000.
        Returns (ip, ws_port, pairing_code) if found, or None.
        """
        info = cls.discover_server_info(timeout=timeout)
        if info is None:
            return None
        return (info["ip"], info["port"], info["pairing_code"])

    # ------------------------------------------------------------------
    # Background WebSocket Worker & Handshake State Machine
    # ------------------------------------------------------------------
    def _worker_loop(self) -> None:
        last_failed_protocol: str = ""
        while not self._stop_event.is_set() and self._enabled:
            self._reconnect_event.clear()

            # Quick UDP discovery check to refresh pairing code / IP / protocol
            disc = self.discover_server_info(timeout=0.35)
            if disc is not None:
                self._pairing_code = disc.get("pairing_code", "")
                disc_proto = disc.get("protocol", "")
                if disc_proto:
                    self._detected_protocol = disc_proto
                if self.host in ("127.0.0.1", "localhost", ""):
                    self.port = disc.get("port", self.port)

            # Determine candidates:
            # - Just Dance 2020-2022 uses v2 with TLS (WSS) and exact subprotocol v2.phonescoring.jd.ubisoft.com
            # - Just Dance 2017-2018 Legacy uses v1 with plain TCP (WS) and subprotocol v1.phonescoring.jd.ubisoft.com
            if self._detected_protocol == WS_SUBPROTOCOL_V1:
                candidate_configs = [
                    (WS_SUBPROTOCOL_V1, False),
                    (WS_SUBPROTOCOL_V2, True),
                ]
            elif self._detected_protocol == WS_SUBPROTOCOL_V2:
                candidate_configs = [
                    (WS_SUBPROTOCOL_V2, True),
                    (WS_SUBPROTOCOL_V1, False),
                ]
            else:
                # If last attempt failed on v2, alternate to v1 first, and vice-versa
                if last_failed_protocol == WS_SUBPROTOCOL_V2:
                    candidate_configs = [
                        (WS_SUBPROTOCOL_V1, False),
                        (WS_SUBPROTOCOL_V2, True),
                    ]
                else:
                    candidate_configs = [
                        (WS_SUBPROTOCOL_V2, True),
                        (WS_SUBPROTOCOL_V1, False),
                    ]

            ws: Optional[_MinimalWebSocketClient] = None
            active_subproto = ""
            for subproto, prefer_tls in candidate_configs:
                candidate_ws = _MinimalWebSocketClient(self.host, self.port, WS_ENDPOINT, subproto)
                try:
                    candidate_ws.connect(timeout=1.5, prefer_tls=prefer_tls)
                    ws = candidate_ws
                    active_subproto = subproto
                    break
                except Exception:
                    candidate_ws.close()
                    continue

            if ws is None or not ws.connected:
                self._connected = False
                self._handshake_complete = False
                code_suffix = f" (Game active • Code: {self._pairing_code})" if self._pairing_code else ""
                self._status_text = f"Checking game on {self.host}:{self.port}{code_suffix}..."
                if self._enabled and not self._stop_event.is_set() and not self._reconnect_event.is_set():
                    self._reconnect_event.wait(timeout=1.0)
                continue

            try:
                self._connected = True
                self._handshake_complete = False
                self._player_name = ""
                proto_tag = "WSS/TLS" if ws.is_tls else "WS"
                code_tag = f" • Code: {self._pairing_code}" if self._pairing_code else ""
                self._status_text = f"Connected ({proto_tag}{code_tag}) — Awaiting Handshake..."

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
                        if self._handshake_complete:
                            self._detected_protocol = active_subproto
                            last_failed_protocol = ""

                    now = time.perf_counter()

                    # If the game window is unfocused (AFK/paused main loop), CivetWeb accepts the TLS
                    # WebSocket upgrade immediately, but JD_SmartphoneManager::Update only processes
                    # HandshakeHello once the game window regains focus. Keep waiting patiently!
                    if not self._handshake_complete:
                        wait_secs = now - hello_sent_ts
                        if wait_secs >= 1.2:
                            self._status_text = (
                                f"Connected ({proto_tag}{code_tag}) — Focus game window to activate!"
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

                    # Yield CPU briefly (1.5ms) for responsive non-blocking loop
                    time.sleep(0.0015)

            except Exception as exc:
                self._connected = False
                self._handshake_complete = False
                self._last_error = str(exc)
                last_failed_protocol = active_subproto
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
            # Generate a strong sinusoidal dance swing across X/Y/Z centered on resting posture
            phase = now * 28.0
            sx = round(math.sin(phase) * 2.8 + 0.08, 4)
            sy = round(math.cos(phase * 1.3) * 2.5 + 0.38, 4)
            sz = round(math.sin(phase * 0.7) * 2.0 + 0.75, 4)
            self._latest_accel = (sx, sy, sz)
            return self._latest_accel

        if (now - self._last_joint_update_ts) <= 0.25:
            return self._latest_accel

        # Idle phone resting upright/tilted in hand (matching DS4 resting IMU baseline)
        self._latest_accel = (0.08, 0.38, 0.75)
        return self._latest_accel

    def _format_connected_status(self) -> str:
        player_slot = f"Player {self._player_id + 1}"
        player_part = f" • {self._player_name} ({player_slot})" if self._player_name else f" • {player_slot}"
        mode_part = "Scoring Active" if self._scoring_enabled else "Connected to Game"
        return f"{mode_part}{player_part}"

    def _handle_incoming_message(self, ws: _MinimalWebSocketClient, raw_msg: str) -> None:
        try:
            parsed = json.loads(raw_msg)
        except Exception as e:
            try:
                from sensor.session_logger import get_session_logger
                get_session_logger().log_throttled(
                    "vphone_json_err", "WARN", "VPHONE", f"Malformed JSON packet from game: {e}"
                )
            except Exception:
                pass
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

            try:
                from sensor.session_logger import get_session_logger
                get_session_logger().log_ipc_event(
                    "VPHONE",
                    "PAIRED",
                    f"Virtual Phone handshake complete (ID: {self._phone_id}, Player: '{self._player_name}')",
                )
                get_session_logger().map_active_controller(
                    "vphone",
                    self.phone_name,
                    details=f"WebSocket paired, Hand: {self.accelerometer.hand}",
                )
            except Exception:
                pass

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

        elif cls_name in (
            "JD_EnableScoringPhoneData",
            "JD_SmartphoneEvent_ScoringActivationChanged",
            "JD_EnableAccelValuesSending_ConsoleCommandData",
            "JD_DisableAccelValuesSending_ConsoleCommandData",
        ):
            if cls_name == "JD_DisableAccelValuesSending_ConsoleCommandData":
                new_scoring = False
            elif cls_name == "JD_EnableAccelValuesSending_ConsoleCommandData":
                new_scoring = True
            else:
                new_scoring = bool(msg.get("enable", msg.get("enabled", True)))

            scoring_changed = (new_scoring != self.is_dancing)
            self._scoring_enabled = new_scoring
            self.is_dancing = new_scoring
            self._status_text = self._format_connected_status()

            if scoring_changed:
                if new_scoring:
                    if not self.current_map_name:
                        detected = detect_active_song_from_game_process()
                        if detected:
                            self.current_map_name = detected
                            self.current_song_name = detected
                    print(f"[VPHONE] Dance scoring STARTED for song: '{self.current_map_name or 'Unknown'}'")
                    if self.adaptive_tuner.enabled:
                        self.adaptive_tuner.reset_song(self.current_map_name)
                    if self.auto_record_enabled and not self.is_logging:
                        self.set_logging(True, source=self._last_source, map_name=self.current_map_name)
                else:
                    print(f"[VPHONE] Dance scoring ENDED for song: '{self.current_map_name or 'Unknown'}'")
                    if self.auto_record_enabled and self.is_logging:
                        self.set_logging(False)

                if self.on_dance_state_change:
                    try:
                        self.on_dance_state_change(new_scoring, self.current_map_name)
                    except Exception:
                        pass

        elif cls_name in (
            "JD_PhoneUiData",
            "JD_PhoneUiSetupData",
            "JD_PhoneUiShortcutData",
            "JD_TriggerTransition_ConsoleCommandData",
            "JD_PhoneUiLobby",
        ):
            if not self._handshake_complete:
                self._handshake_complete = True

            sdata = msg.get("setupData") if isinstance(msg.get("setupData"), dict) else {}

            # Detect gameplay vs lobby state from PhoneUi
            if "gameplaySetup" in sdata or "gameplaySetup" in msg:
                if not self.is_dancing:
                    self.is_dancing = True
                    self._scoring_enabled = True
                    if not self.current_map_name:
                        detected = detect_active_song_from_game_process()
                        if detected:
                            self.current_map_name = detected
                            self.current_song_name = detected
                    if self.adaptive_tuner.enabled:
                        self.adaptive_tuner.reset_song(self.current_map_name)
                    if self.auto_record_enabled and not self.is_logging:
                        self.set_logging(True, source=self._last_source, map_name=self.current_map_name)
                    if self.on_dance_state_change:
                        try:
                            self.on_dance_state_change(True, self.current_map_name)
                        except Exception:
                            pass
            elif "lobbySetup" in sdata or "lobbySetup" in msg or cls_name == "JD_PhoneUiLobby":
                if self.is_dancing:
                    self.is_dancing = False
                    if self.auto_record_enabled and self.is_logging:
                        self.set_logging(False)
                    if self.on_dance_state_change:
                        try:
                            self.on_dance_state_change(False, self.current_map_name)
                        except Exception:
                            pass

            # Extract song map name across Just Dance versions
            detected_song = ""
            if "mapName" in sdata:
                detected_song = str(sdata["mapName"])
            elif "songName" in sdata:
                detected_song = str(sdata["songName"])
            elif "mapName" in msg:
                detected_song = str(msg["mapName"])
            elif "songName" in msg:
                detected_song = str(msg["songName"])

            # If still empty, query active song from game process memory
            if not detected_song:
                detected_song = detect_active_song_from_game_process()

            if detected_song and detected_song.strip():
                clean_name = detected_song.strip()
                if clean_name != self.current_map_name:
                    with self._lock:
                        self.current_map_name = clean_name
                        self.current_song_name = clean_name
                    print(f"[VPHONE] Detected active song map: '{self.current_map_name}'")
                    try:
                        from sensor.session_logger import get_session_logger
                        get_session_logger().update_active_song(self.current_map_name)
                    except Exception:
                        pass
                    if self.on_song_change:
                        try:
                            self.on_song_change(self.current_map_name)
                        except Exception:
                            pass

            # Extract move scoring feedback (PERFECT, SUPER, GOOD, OK, MISS, YEAH)
            fb_val = ""
            for key in ("feedback", "rating", "feedbackText", "action", "moveFeedback"):
                if key in msg and isinstance(msg[key], str) and msg[key].strip():
                    fb_val = msg[key].strip().upper()
                    break
            if not fb_val and "setupData" in msg and isinstance(msg["setupData"], dict):
                for key in ("feedback", "rating", "moveFeedback"):
                    v = msg["setupData"].get(key)
                    if isinstance(v, str) and v.strip():
                        fb_val = v.strip().upper()
                        break

            if fb_val in ("PERFECT", "SUPER", "GOOD", "OK", "MISS", "YEAH", "GOLD"):
                self._last_feedback = fb_val
                if self.is_dancing and self.adaptive_tuner.enabled:
                    self.adaptive_tuner.on_feedback(
                        fb_val,
                        current_speed=self.accelerometer.latest_speed,
                        current_accel=self._latest_accel,
                    )

            # Extract song coaches/NPCs across all Just Dance versions:
            # - Just Dance 2017/2018 Legacy: sends JD_PhoneUiLobby with "coaches" directly
            # - Just Dance 2020-2022: sends JD_PhoneUiSetupData with "setupData": {"lobbySetup": {"coaches": [...]}}
            coaches_list = None
            if "coaches" in msg and isinstance(msg["coaches"], list):
                coaches_list = msg["coaches"]
            elif "setupData" in msg and isinstance(msg["setupData"], dict):
                lobby = msg["setupData"].get("lobbySetup")
                if isinstance(lobby, dict) and "coaches" in lobby:
                    coaches_list = lobby.get("coaches")
            elif "lobbySetup" in msg and isinstance(msg["lobbySetup"], dict):
                coaches_list = msg["lobbySetup"].get("coaches")

            if isinstance(coaches_list, list) and coaches_list:
                with self._lock:
                    self.total_coaches = max(1, len(coaches_list))
                    for idx, c in enumerate(coaches_list):
                        if isinstance(c, dict) and c.get("selectedOnEnter"):
                            self.current_coach_id = idx
                            break
                    self.current_coach_id = max(0, min(self.total_coaches - 1, self.current_coach_id))
                print(f"[VPHONE] Detected {self.total_coaches} coaches in song lobby (Active: {self.current_coach_id + 1}).")

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
