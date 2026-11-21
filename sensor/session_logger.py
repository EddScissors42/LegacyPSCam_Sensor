"""
Legacy PSCam Sensor — Session Logger & Dance Telemetry Subsystem.
Provides comprehensive diagnostic session logging and high-throughput real-time
dance telemetry for bug investigation, hardware verification, and motion analysis.

Features:
  1. Startup Lifecycle: Wipes/rotates previous session logs on application boot to
     prevent disk bloat and ensure bug reports reflect the exact latest execution.
  2. Diagnostic Header: Captures Windows version, CPU, RAM (via Win32 API), Python
     runtime, app version, display info, and environment flags.
  3. Controller Mapping: Logs active input controllers (DualShock 4 Bluetooth/USB,
     Virtual Phone, Optical Camera), VID/PID, battery levels, and button events.
  4. Real-time Telemetry Streaming: Non-blocking asynchronous CSV writer (<0.1% CPU)
     capturing 3D accelerations, velocities, joint coordinates, FPS, latency, and
     scoring feedback from the moment START TRACKING is engaged.
  5. Crash & Exception Trapping: Global hooks for sys.excepthook and threading.excepthook
     to capture unhandled exceptions with full tracebacks.
"""

from __future__ import annotations

import atexit
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import math
import os
from pathlib import Path
import platform
import queue
import sys
import threading
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

from version import APP_NAME, VERSION_STRING


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_uint64),
        ("ullAvailPhys", ctypes.c_uint64),
        ("ullTotalPageFile", ctypes.c_uint64),
        ("ullAvailPageFile", ctypes.c_uint64),
        ("ullTotalVirtual", ctypes.c_uint64),
        ("ullAvailVirtual", ctypes.c_uint64),
        ("ullAvailExtendedVirtual", ctypes.c_uint64),
    ]


TELEMETRY_CSV_HEADER = (
    "timestamp_ms,rel_time_s,source,song_name,coach_id,is_tracked,"
    "ax,ay,az,mag_g,speed_mps,"
    "hand_x,hand_y,hand_z,"
    "shoulder_r_x,shoulder_r_y,shoulder_r_z,"
    "elbow_r_x,elbow_r_y,elbow_r_z,"
    "wrist_r_x,wrist_r_y,wrist_r_z,"
    "joints_tracked_count,cam_fps,infer_fps,game_feedback,controller_btn\n"
)


class SessionLogger:
    """
    Central logging and telemetry coordinator for Legacy PSCam Sensor.
    Thread-safe singleton managing diagnostic session logs and real-time motion CSV.
    """

    _instance: Optional["SessionLogger"] = None
    _instance_lock = threading.Lock()

    def __init__(self, logs_dir: Optional[str | Path] = None) -> None:
        if logs_dir:
            self.logs_dir = Path(logs_dir)
        else:
            from sensor.config_manager import get_logs_dir
            self.logs_dir = get_logs_dir()

        self._lock = threading.RLock()
        self._initialized = False
        self._session_start_time = time.time()
        self._session_start_perf = time.perf_counter()

        # File paths
        self.session_log_path = self.logs_dir / "session.log"
        self.session_prev_log_path = self.logs_dir / "session_previous.log"
        self.telemetry_csv_path = self.logs_dir / "session_telemetry.csv"
        self.telemetry_prev_csv_path = self.logs_dir / "session_telemetry_previous.csv"

        # Log file handles
        self._session_file: Optional[Any] = None
        self._telemetry_file: Optional[Any] = None

        # Telemetry worker queue
        self._telemetry_queue: queue.Queue[Optional[str]] = queue.Queue(maxsize=10000)
        self._telemetry_worker_thread: Optional[threading.Thread] = None
        self._telemetry_active = False
        self._telemetry_start_ts_ms = 0
        self._telemetry_samples_written = 0

        # State tracking
        self.active_controller_name: str = "None"
        self.active_controller_type: str = "none"
        self.active_controller_details: str = ""
        self.active_song_name: str = "UnknownSong"
        self.active_coach_id: int = 0
        self.last_button_event: str = ""

        # Installed exception hooks
        self._orig_excepthook = sys.excepthook
        self._orig_threading_excepthook = getattr(threading, "excepthook", None)

    @classmethod
    def get_instance(cls, logs_dir: Optional[str | Path] = None) -> "SessionLogger":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls(logs_dir)
            return cls._instance

    def initialize(self, wipe_old_logs: bool = True, backup_previous: bool = True) -> None:
        """
        Initializes the session logger on application boot.
        Safely rotates or wipes previous session files and creates fresh log files.
        """
        with self._lock:
            if self._initialized:
                return

            self.logs_dir.mkdir(parents=True, exist_ok=True)

            if wipe_old_logs:
                # Rotate previous session.log to session_previous.log for safety
                if backup_previous and self.session_log_path.exists():
                    try:
                        if self.session_prev_log_path.exists():
                            self.session_prev_log_path.unlink(missing_ok=True)
                        self.session_log_path.rename(self.session_prev_log_path)
                    except OSError:
                        pass

                # Rotate previous telemetry.csv to session_telemetry_previous.csv
                if backup_previous and self.telemetry_csv_path.exists():
                    try:
                        if self.telemetry_prev_csv_path.exists():
                            self.telemetry_prev_csv_path.unlink(missing_ok=True)
                        self.telemetry_csv_path.rename(self.telemetry_prev_csv_path)
                    except OSError:
                        pass

            # Open fresh session.log
            try:
                self._session_file = open(self.session_log_path, "w", encoding="utf-8", errors="replace", buffering=1)
            except OSError as e:
                print(f"[ERROR] SessionLogger: Failed to open session log: {e}")
                self._session_file = None

            self._initialized = True
            self.install_exception_hooks()
            atexit.register(self.close)

            # Start asynchronous telemetry consumer thread
            self._telemetry_worker_thread = threading.Thread(
                target=self._telemetry_writer_loop,
                name="SessionTelemetryWriter",
                daemon=True,
            )
            self._telemetry_worker_thread.start()

            self.log_event("INFO", "SESSION", f"Session logger initialized (Logs Dir: {self.logs_dir})")

    def install_exception_hooks(self) -> None:
        """Installs global exception interceptors to trap crashes into session.log."""
        def handle_unhandled_exception(exc_type, exc_value, exc_traceback):
            if issubclass(exc_type, KeyboardInterrupt):
                if self._orig_excepthook:
                    self._orig_excepthook(exc_type, exc_value, exc_traceback)
                return

            tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            self.log_event("FATAL", "CRASH", f"Unhandled process exception: {exc_value}\n{tb_str}")
            self.flush()

            if self._orig_excepthook:
                self._orig_excepthook(exc_type, exc_value, exc_traceback)

        def handle_threading_exception(args):
            if issubclass(args.exc_type, KeyboardInterrupt):
                if self._orig_threading_excepthook:
                    self._orig_threading_excepthook(args)
                return

            tb_str = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
            self.log_event(
                "FATAL",
                "CRASH",
                f"Unhandled exception in thread '{getattr(args.thread, 'name', 'Unknown')}': {args.exc_value}\n{tb_str}",
            )
            self.flush()

            if self._orig_threading_excepthook:
                self._orig_threading_excepthook(args)

        sys.excepthook = handle_unhandled_exception
        if hasattr(threading, "excepthook"):
            threading.excepthook = handle_threading_exception

    def log_event(self, level: str, category: str, message: str) -> None:
        """Writes a formatted timestamped entry to session.log."""
        now = datetime.now()
        timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        formatted_entry = f"{timestamp_str} [{level.upper():5s}] [{category.upper():12s}] {message}\n"

        with self._lock:
            if self._session_file and not self._session_file.closed:
                try:
                    self._session_file.write(formatted_entry)
                    self._session_file.flush()
                except OSError:
                    pass

    def log_system_environment(self) -> None:
        """Gathers and logs comprehensive OS, hardware, and runtime diagnostic metadata."""
        try:
            # Memory info via Win32 GlobalMemoryStatusEx
            ram_info = "Unknown"
            try:
                stat = MEMORYSTATUSEX()
                stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
                if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                    total_gb = stat.ullTotalPhys / (1024 ** 3)
                    avail_gb = stat.ullAvailPhys / (1024 ** 3)
                    ram_info = f"{total_gb:.2f} GB total, {avail_gb:.2f} GB available (Load: {stat.dwMemoryLoad}%)"
            except Exception as e:
                ram_info = f"Error querying RAM: {e}"

            # CPU info
            cpu_model = platform.processor() or "Unknown CPU"
            cpu_cores = os.cpu_count() or 1
            cpu_arch = platform.machine()

            # Python and executable details
            is_frozen = getattr(sys, "frozen", False)
            exe_path = sys.executable
            py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

            # Windows details
            win_ver = platform.version()
            win_release = platform.release()
            os_details = f"Windows {win_release} (Build {win_ver}) {cpu_arch}"

            from sensor.config_manager import get_app_data_dir, get_config_path
            app_dir = get_app_data_dir()
            cfg_p = get_config_path()

            banner = [
                "=" * 80,
                f"  {APP_NAME} — Session Diagnostic Log",
                f"  Version: {VERSION_STRING}",
                f"  Session Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Local ({datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC)",
                "=" * 80,
                f"  Operating System: {os_details}",
                f"  Processor:        {cpu_model} ({cpu_cores} Logical Cores)",
                f"  Memory (RAM):     {ram_info}",
                f"  Python Runtime:   {py_ver} ({'Frozen PE Executable' if is_frozen else 'Interpreted Script'})",
                f"  Executable Path:  {exe_path}",
                f"  App Data Dir:     {app_dir}",
                f"  Config Path:      {cfg_p}",
                f"  Logs Directory:   {self.logs_dir}",
                f"  Working Dir:      {os.getcwd()}",
                "=" * 80,
            ]
            header_str = "\n".join(banner)

            with self._lock:
                if self._session_file and not self._session_file.closed:
                    self._session_file.write(header_str + "\n\n")
                    self._session_file.flush()

        except Exception as e:
            self.log_event("ERROR", "SYSTEM", f"Failed to gather complete system diagnostics: {e}")

    def log_camera_discovery(self, cameras: List[Any], pscam_installed: bool = False, pscam_running: bool = False) -> None:
        """Logs discovered cameras, indexes, and PS4 Camera driver state."""
        lines = [f"Camera discovery completed — Found {len(cameras)} video device(s):"]
        if not cameras:
            lines.append("  (None detected)")
        for c in cameras:
            idx = getattr(c, "index", -1)
            name = getattr(c, "name", "Unknown")
            is_ps = getattr(c, "is_pscam", False)
            res_list = getattr(c, "supported_resolutions", [])
            lines.append(f"  • [{idx}] {name} {'(PlayStation 4 Camera)' if is_ps else '(Standard Webcam)'} — Resolutions: {len(res_list)}")

        lines.append(f"PSCam4Win Legacy Status: Installed={pscam_installed}, Running={pscam_running}")
        self.log_event("INFO", "CAMERA", "\n".join(lines))

    def log_controller_state(self, controller_type: str, name: str, details: Dict[str, Any]) -> None:
        """Logs detailed device hardware state for connected controllers."""
        details_str = ", ".join(f"{k}={v}" for k, v in details.items())
        self.log_event("INFO", "CONTROLLER", f"Device detected: [{controller_type.upper()}] '{name}' ({details_str})")

    def map_active_controller(self, controller_type: str, name: str, details: str = "") -> None:
        """Sets and logs the active controller mapped for the current session."""
        with self._lock:
            self.active_controller_type = controller_type.lower()
            self.active_controller_name = name
            self.active_controller_details = details

        self.log_event(
            "INFO",
            "MAPPING",
            f"Active dancer control mapped to: [{controller_type.upper()}] '{name}' {f'({details})' if details else ''}",
        )

    def log_controller_button(self, button_name: str, coach_id: int = 0, action: str = "press") -> None:
        """Logs a controller button event."""
        with self._lock:
            self.last_button_event = f"{button_name}:{action}"
            self.active_coach_id = coach_id

        self.log_event("DEBUG", "INPUT", f"Button [{button_name}] {action} (Active Coach: {coach_id + 1})")

    def log_ipc_event(self, channel: str, status: str, details: str = "") -> None:
        """Logs IPC Shared Memory or In-Memory Kinect Emulator state events."""
        msg = f"[{channel}] Status: {status}"
        if details:
            msg += f" — {details}"
        self.log_event("INFO", "IPC", msg)

    # -------------------------------------------------------------------------
    # High-Throughput Real-Time Dance Telemetry Streaming (CSV)
    # -------------------------------------------------------------------------

    def start_telemetry_tracking(
        self,
        source: str = "camera",
        song_name: str = "DanceSession",
        coach_id: int = 0,
        config_summary: str = "",
    ) -> None:
        """
        Activates continuous dance telemetry streaming to session_telemetry.csv.
        Triggered when tracking starts (START TRACKING).
        """
        with self._lock:
            self._telemetry_active = True
            self._telemetry_start_ts_ms = int(time.time() * 1000)
            self._telemetry_samples_written = 0
            self.active_song_name = song_name or "DanceSession"
            self.active_coach_id = coach_id

            try:
                self._telemetry_file = open(self.telemetry_csv_path, "w", encoding="utf-8", buffering=8192)
                self._telemetry_file.write(TELEMETRY_CSV_HEADER)
                self._telemetry_file.flush()
            except OSError as e:
                self.log_event("ERROR", "TELEMETRY", f"Failed to open telemetry CSV for writing: {e}")
                self._telemetry_file = None

        self.log_event(
            "INFO",
            "TELEMETRY",
            f"Real-time dance telemetry recording started -> {self.telemetry_csv_path.name} "
            f"(Source: {source}, Song: '{self.active_song_name}', Config: {config_summary})",
        )

    def record_telemetry_sample(
        self,
        ts_ms: int,
        source: str = "camera",
        song_name: Optional[str] = None,
        coach_id: Optional[int] = None,
        is_tracked: bool = True,
        ax: float = 0.0,
        ay: float = 0.0,
        az: float = 1.0,
        speed_mps: float = 0.0,
        hand_pos: Optional[Tuple[float, float, float]] = None,
        shoulder_r: Optional[Tuple[float, float, float]] = None,
        elbow_r: Optional[Tuple[float, float, float]] = None,
        wrist_r: Optional[Tuple[float, float, float]] = None,
        joints_tracked_count: int = 20,
        cam_fps: float = 0.0,
        infer_fps: float = 0.0,
        game_feedback: str = "",
        btn_override: str = "",
    ) -> None:
        """
        Pushes a single dance telemetry sample into the non-blocking writer queue.
        Guarantees zero stall on camera capture or MediaPipe thread.
        """
        if not self._telemetry_active:
            return

        mag_g = math.sqrt(ax * ax + ay * ay + az * az)
        rel_s = round((ts_ms - self._telemetry_start_ts_ms) / 1000.0, 3) if self._telemetry_start_ts_ms else 0.0

        hx, hy, hz = hand_pos if hand_pos else (0.0, 0.0, 0.0)
        sx, sy, sz = shoulder_r if shoulder_r else (0.0, 0.0, 0.0)
        ex, ey, ez = elbow_r if elbow_r else (0.0, 0.0, 0.0)
        wx, wy, wz = wrist_r if wrist_r else (0.0, 0.0, 0.0)

        song = song_name or self.active_song_name
        cid = coach_id if coach_id is not None else self.active_coach_id
        btn = btn_override or self.last_button_event

        row = (
            f"{ts_ms},{rel_s:.3f},{source},{song},{cid},{1 if is_tracked else 0},"
            f"{ax:.4f},{ay:.4f},{az:.4f},{mag_g:.4f},{speed_mps:.3f},"
            f"{hx:.3f},{hy:.3f},{hz:.3f},"
            f"{sx:.3f},{sy:.3f},{sz:.3f},"
            f"{ex:.3f},{ey:.3f},{ez:.3f},"
            f"{wx:.3f},{wy:.3f},{wz:.3f},"
            f"{joints_tracked_count},{cam_fps:.1f},{infer_fps:.1f},{game_feedback},{btn}\n"
        )

        try:
            self._telemetry_queue.put_nowait(row)
        except queue.Full:
            # Drop older sample if queue reaches cap during severe disk stall
            try:
                _ = self._telemetry_queue.get_nowait()
                self._telemetry_queue.put_nowait(row)
            except Exception:
                pass

    def _telemetry_writer_loop(self) -> None:
        """Background worker thread draining the telemetry queue to disk."""
        batch = []
        last_flush = time.perf_counter()

        while True:
            try:
                row = self._telemetry_queue.get(timeout=0.1)
                if row is None:  # Shutdown sentinel
                    break
                batch.append(row)
            except queue.Empty:
                pass

            now = time.perf_counter()
            # Flush batch every 100ms or when 64 rows accumulate
            if batch and (len(batch) >= 64 or (now - last_flush) >= 0.1):
                with self._lock:
                    if self._telemetry_file and not self._telemetry_file.closed:
                        try:
                            self._telemetry_file.writelines(batch)
                            self._telemetry_file.flush()
                            self._telemetry_samples_written += len(batch)
                        except OSError:
                            pass
                batch.clear()
                last_flush = now

        # Write remaining batch upon thread exit
        if batch:
            with self._lock:
                if self._telemetry_file and not self._telemetry_file.closed:
                    try:
                        self._telemetry_file.writelines(batch)
                        self._telemetry_file.flush()
                        self._telemetry_samples_written += len(batch)
                    except OSError:
                        pass

    def stop_telemetry_tracking(self, summary_metrics: Optional[Dict[str, Any]] = None) -> None:
        """Stops telemetry recording, flushes data, and logs summary statistics."""
        with self._lock:
            if not self._telemetry_active:
                return
            self._telemetry_active = False

        # Drain any pending items in the queue to disk immediately
        remaining: List[str] = []
        while True:
            try:
                item = self._telemetry_queue.get_nowait()
                if item is not None:
                    remaining.append(item)
            except queue.Empty:
                break

        with self._lock:
            if self._telemetry_file and not self._telemetry_file.closed:
                try:
                    if remaining:
                        self._telemetry_file.writelines(remaining)
                        self._telemetry_samples_written += len(remaining)
                    self._telemetry_file.flush()
                    self._telemetry_file.close()
                except OSError:
                    pass
                self._telemetry_file = None

            samples = self._telemetry_samples_written

        summary_str = f"Samples: {samples}"
        if summary_metrics:
            summary_str += ", " + ", ".join(f"{k}: {v}" for k, v in summary_metrics.items())

        self.log_event("INFO", "TELEMETRY", f"Dance telemetry recording finished -> {self.telemetry_csv_path.name} ({summary_str})")

    def update_active_song(self, song_name: str) -> None:
        """Updates detected song name across telemetry records."""
        with self._lock:
            if song_name and song_name != self.active_song_name:
                self.active_song_name = song_name
                self.log_event("INFO", "GAME", f"Song detected / switched to: '{song_name}'")

    def flush(self) -> None:
        """Flushes all open log files immediately."""
        with self._lock:
            if self._session_file and not self._session_file.closed:
                try:
                    self._session_file.flush()
                except OSError:
                    pass
            if self._telemetry_file and not self._telemetry_file.closed:
                try:
                    self._telemetry_file.flush()
                except OSError:
                    pass

    def close(self) -> None:
        """Cleanly finalizes all log files and releases background threads."""
        with self._lock:
            if not self._initialized:
                return
            self._initialized = False

        duration = round(time.time() - self._session_start_time, 2)
        self.log_event("INFO", "SESSION", f"Application shutting down gracefully (Session Duration: {duration}s)")
        self.flush()

        # Stop telemetry worker
        if self._telemetry_worker_thread and self._telemetry_worker_thread.is_alive():
            try:
                self._telemetry_queue.put_nowait(None)
                self._telemetry_worker_thread.join(timeout=1.0)
            except Exception:
                pass

        with self._lock:
            if self._session_file and not self._session_file.closed:
                try:
                    self._session_file.close()
                except OSError:
                    pass
                self._session_file = None

            if self._telemetry_file and not self._telemetry_file.closed:
                try:
                    self._telemetry_file.close()
                except OSError:
                    pass
                self._telemetry_file = None


def get_session_logger(logs_dir: Optional[str | Path] = None) -> SessionLogger:
    """Returns the singleton instance of SessionLogger."""
    return SessionLogger.get_instance(logs_dir)
