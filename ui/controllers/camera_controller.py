"""
Camera Controller for Legacy PSCam Sensor.
Handles PnP device discovery, PlayStation 4 Camera state machine,
DirectShow/WinUSB negotiation, and background warm-up lifecycle with standby throttling.
Decoupled from Qt UI presentation.
"""
import os
import time
import threading
from typing import List, Optional, Tuple, Callable

from PySide6.QtCore import QObject, QTimer, Signal

from sensor.config_manager import ConfigManager, parse_preset, PRESETS_PSCAM, PRESETS_WEBCAM
from sensor.camera_manager import CameraManager, CameraInfo, LatestFrameCamera


class CameraController(QObject):
    """
    Coordinates camera hardware discovery, PS4 Camera state management,
    and instant-start background pre-warming.
    """
    cameras_refreshed = Signal(list)
    pscam_state_changed = Signal(dict)

    def __init__(self, config_manager: Optional[ConfigManager] = None, parent=None):
        super().__init__(parent)
        self.cfg_mgr = config_manager or ConfigManager()
        self.cfg = self.cfg_mgr.config

        self.camera_list: List[CameraInfo] = []
        self._is_refreshing_cams = False
        self._last_hw_snapshot = ()
        self._last_pscam_state = None

        # Camera pre-warming state (instant 0s startup for START TRACKING)
        self._prewarmed_camera: Optional[LatestFrameCamera] = None
        self._warmup_thread: Optional[threading.Thread] = None
        self._warmup_lock = threading.Lock()
        self._warmup_timer = QTimer(self)
        self._warmup_timer.setSingleShot(True)
        self._warmup_timer.timeout.connect(self._warmup_timer_fired)

        self._is_closing = False
        self._is_tracking_active = False

    def set_tracking_active(self, active: bool):
        self._is_tracking_active = bool(active)

    def set_closing(self, closing: bool):
        self._is_closing = bool(closing)
        if closing:
            self.cancel_warmup()

    # =========================================================================
    # HARDWARE & PNP DISCOVERY
    # =========================================================================
    def get_hardware_snapshot(self) -> tuple:
        """Returns PnP hardware device instance tuple (<3ms via Win32 CfgMgr32)."""
        return CameraManager.get_hardware_snapshot()

    def check_hardware_changes(self) -> bool:
        """Checks if USB camera hardware was plugged/unplugged."""
        current_snapshot = self.get_hardware_snapshot()
        if current_snapshot != self._last_hw_snapshot:
            self._last_hw_snapshot = current_snapshot
            try:
                from sensor.ps4_backend import PS4DriverInstaller
                PS4DriverInstaller.invalidate_cache()
            except Exception:
                pass
            return True
        return False

    def refresh_cameras(self, probe_hardware: bool = False) -> List[CameraInfo]:
        """Synchronously enumerates present cameras and updates internal cache."""
        try:
            cams = CameraManager.enumerate_cameras(probe_hardware=probe_hardware)
        except Exception:
            cams = []
        self.camera_list = cams
        return cams

    def refresh_cameras_async(self, callback: Optional[Callable[[List[CameraInfo]], None]] = None):
        """Asynchronously enumerates cameras on a background thread without blocking UI."""
        if self._is_refreshing_cams or self._is_tracking_active:
            return
        self._is_refreshing_cams = True

        def worker():
            if self._is_tracking_active or self._is_closing:
                self._is_refreshing_cams = False
                return
            try:
                cams = CameraManager.enumerate_cameras()
            except Exception:
                cams = []
            if not self._is_closing and not self._is_tracking_active:
                self.camera_list = cams
                try:
                    self.cameras_refreshed.emit(cams)
                except RuntimeError:
                    pass
                if callback:
                    callback(cams)
            self._is_refreshing_cams = False

        threading.Thread(target=worker, daemon=True, name="CameraRefreshThread").start()

    # =========================================================================
    # PLAYSTATION 4 CAMERA STATE MACHINE
    # =========================================================================
    def get_ps4_state(self) -> dict:
        """Returns lifecycle dictionary for PlayStation 4 Camera."""
        return CameraManager.get_ps4_camera_state()

    def check_ps4_state_changed(self) -> Tuple[bool, dict]:
        """Checks if PS4 Camera state transitioned (e.g. from Bootloader to Ready)."""
        info = self.get_ps4_state()
        state_key = (info.get("state"), info.get("running"))
        if self._last_pscam_state != state_key:
            self._last_pscam_state = state_key
            self.pscam_state_changed.emit(info)
            return True, info
        return False, info

    def is_pscam_connected(self) -> bool:
        """Returns True if a PlayStation 4 Camera is ready or present on USB."""
        if CameraManager.is_ps4_hardware_connected():
            return True
        return any(c.is_pscam for c in self.camera_list)

    def initialize_ps4_camera(self) -> Tuple[bool, str]:
        """Ensures firmware upload and WinUSB association for PS4 Camera."""
        return CameraManager.initialize_ps4_camera()

    def launch_pscam_tray(self) -> bool:
        """Launches legacy PSCam4Win tray if installed."""
        return CameraManager.launch_pscam_tray()

    def is_camera_accessible(self, mode: Optional[str] = None) -> bool:
        """Returns True if the current mode has a valid, connected camera."""
        m = mode or self.cfg.get("camera_mode", "pscam")
        if m == "ds4":
            return True
        elif m == "pscam":
            st = self.get_ps4_state().get("state", "DISCONNECTED")
            return st == "READY"
        elif m == "phone_cam":
            try:
                import sensor
                return bool(sensor.get_phone_camera_server().is_client_connected)
            except Exception:
                return False
        else:
            webcams = [c for c in self.camera_list if not c.is_pscam]
            if not webcams and not any(c.is_pscam for c in self.camera_list):
                webcams = self.camera_list
            return len(webcams) > 0

    # =========================================================================
    # BACKGROUND CAMERA PRE-WARMING (INSTANT START)
    # =========================================================================
    def schedule_warmup(self, delay_ms: int = 350):
        """Schedules camera pre-warming with debounce so UI remains ultra-responsive."""
        if self._is_closing or self._is_tracking_active:
            return
        self._warmup_timer.start(delay_ms)

    def _warmup_timer_fired(self):
        self.start_warmup_async()

    def cancel_warmup(self, sync: bool = False):
        """Cancels any pending warm-up (invalidating in-flight workers) and releases pre-warmed camera."""
        if self._warmup_timer.isActive():
            self._warmup_timer.stop()
        with self._warmup_lock:
            self._warmup_gen = getattr(self, "_warmup_gen", 0) + 1
            cam = self._prewarmed_camera
            self._prewarmed_camera = None
            th = self._warmup_thread
            self._warmup_thread = None

        if sync and th is not None and th.is_alive():
            try:
                th.join(timeout=1.5)
            except Exception:
                pass

        if cam is not None:
            if sync:
                try:
                    cam.release()
                except Exception:
                    pass
            else:
                def _close_cam():
                    try:
                        cam.release()
                    except Exception:
                        pass
                threading.Thread(target=_close_cam, daemon=True, name="CameraPrewarmCloser").start()

    def start_warmup_async(self):
        """Asynchronously pre-negotiates camera in low-CPU standby mode (<0.4% CPU)."""
        if self._is_closing or self._is_tracking_active:
            return
        mode = self.cfg.get("camera_mode", "pscam")
        if mode not in ("pscam", "webcam"):
            return

        with self._warmup_lock:
            # If a warmup worker thread is already in flight, do not spawn duplicate threads
            if self._warmup_thread is not None and self._warmup_thread.is_alive():
                return
            my_gen = getattr(self, "_warmup_gen", 0)

        def _warmup_worker():
            try:
                if self._is_closing or self._is_tracking_active or my_gen != getattr(self, "_warmup_gen", 0):
                    return

                cam_idx = self.cfg.get("camera_index", 0)
                if mode == "pscam":
                    ps_cams = [c for c in self.camera_list if c.is_pscam]
                    if ps_cams:
                        cam_idx = ps_cams[0].index
                    preset_str = self.cfg.get("pscam_preset", "1280x800 @ 60 FPS")
                else:
                    preset_str = self.cfg.get("webcam_preset", "640x480 @ 30 FPS")

                w, h, target_fps = parse_preset(preset_str)
                camera_orientation = int(self.cfg.get("camera_orientation", 0))
                ps4_eye = str(self.cfg.get("ps4_eye", "right")).strip().lower()
                ps4_backend_mode = str(self.cfg.get("ps4_camera_backend", "native")).strip().lower()

                with self._warmup_lock:
                    if self._is_closing or self._is_tracking_active or my_gen != getattr(self, "_warmup_gen", 0):
                        return

                    # If already running and compatible, preserve it
                    if (
                        self._prewarmed_camera is not None
                        and getattr(self._prewarmed_camera, "running", False)
                        and getattr(self._prewarmed_camera, "is_compatible", lambda **k: True)(
                            camera_index=cam_idx,
                            target_w=w,
                            target_h=h,
                            target_fps=target_fps,
                            is_pscam=(mode == "pscam"),
                            orientation=camera_orientation,
                            ps4_eye=ps4_eye,
                            ps4_backend_mode=ps4_backend_mode,
                            is_phone_cam=False,
                        )
                    ):
                        return

                    # Release stale instance if settings changed
                    old_cam = self._prewarmed_camera
                    self._prewarmed_camera = None

                if old_cam is not None:
                    try:
                        old_cam.release()
                    except Exception:
                        pass

                if self._is_closing or self._is_tracking_active or my_gen != getattr(self, "_warmup_gen", 0):
                    return

                # If PS4 Camera, ensure driver is ready before DirectShow/WinUSB connect
                if mode == "pscam" and ps4_backend_mode != "pscam4win":
                    CameraManager.initialize_ps4_camera()

                if self._is_closing or self._is_tracking_active or my_gen != getattr(self, "_warmup_gen", 0):
                    return

                try:
                    cam = LatestFrameCamera(
                        camera_index=cam_idx,
                        target_w=w,
                        target_h=h,
                        target_fps=target_fps,
                        is_pscam=(mode == "pscam"),
                        orientation=camera_orientation,
                        ps4_eye=ps4_eye,
                        ps4_backend_mode=ps4_backend_mode,
                        is_phone_cam=False,
                        is_prewarming=True,
                    )
                    with self._warmup_lock:
                        if self._is_closing or self._is_tracking_active or my_gen != getattr(self, "_warmup_gen", 0):
                            cam.release()
                        else:
                            self._prewarmed_camera = cam
                            print(f"[WARMUP] Câmera pré-aquecida pronta em standby: {w}x{h}@{target_fps}fps")
                except Exception as e:
                    with self._warmup_lock:
                        self._prewarmed_camera = None
            finally:
                with self._warmup_lock:
                    if self._warmup_thread is threading.current_thread():
                        self._warmup_thread = None

        t = threading.Thread(target=_warmup_worker, daemon=True, name="CameraWarmupThread")
        with self._warmup_lock:
            self._warmup_thread = t
        t.start()

    def take_prewarmed_camera(self) -> Optional[LatestFrameCamera]:
        """Atomically extracts the pre-warmed camera instance for handoff to tracking session."""
        with self._warmup_lock:
            th = self._warmup_thread
        if th is not None and th.is_alive():
            try:
                th.join(timeout=1.5)
            except Exception:
                pass

        with self._warmup_lock:
            cam = self._prewarmed_camera
            self._prewarmed_camera = None
            self._warmup_thread = None
            return cam

    # =========================================================================
    # PRESETS & UTILITIES
    # =========================================================================
    @staticmethod
    def get_presets_for_mode(mode: str) -> List[str]:
        if mode == "pscam":
            return PRESETS_PSCAM
        elif mode == "webcam":
            return PRESETS_WEBCAM
        return PRESETS_WEBCAM

    @staticmethod
    def parse_preset(preset_str: str) -> Tuple[int, int, int]:
        return parse_preset(preset_str)
