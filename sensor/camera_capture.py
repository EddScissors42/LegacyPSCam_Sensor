"""
Zero-Latency Threaded Camera Capture for Legacy PSCam Sensor.
Supports Phone Camera (Wi-Fi WebApp), PlayStation 4 Camera (Native WinUSB Backend),
legacy FrameBus IPC fallback, and standard DirectShow UVC webcams.
Always delivers pristine, un-mirrored frames to the pose tracker.
"""
from __future__ import annotations

import os
import threading
import time
import cv2

from .framebus_reader import FrameBusReader
from .ps4_backend import (
    PS4CameraBackend,
    DEFAULT_EYE,
    EYE_LEFT,
)

# Global lock to serialize DirectShow / Camera hardware access across warmup and tracking threads
_CAMERA_HW_LOCK = threading.RLock()


class LatestFrameCamera:
    """
    Zero-latency threaded camera grabber.
    Continually reads from Native PS4CameraBackend (for PlayStation 4 Camera) or OpenCV VideoCapture
    on a background thread so the internal frame queue never buffers stale frames.
    Handles black-frame recovery, eye selection (Right Eye default), and orientation rotation.
    Always delivers pristine, un-mirrored frames to the pose tracker.
    """

    def __init__(
        self,
        camera_index,
        target_w=640,
        target_h=480,
        target_fps=30,
        mirror=True,
        is_pscam=False,
        orientation=0,
        ps4_eye=DEFAULT_EYE,
        ps4_backend_mode="native",
        is_phone_cam=False,
        phone_cam_server=None,
        is_prewarming: bool = False,
    ):
        self.camera_index = camera_index
        self.target_w = target_w
        self.target_h = target_h
        self.target_fps = target_fps
        self.mirror = mirror
        self.is_pscam = is_pscam
        self.is_phone_cam = bool(is_phone_cam)
        self.phone_cam_server = phone_cam_server
        self.orientation = int(orientation)
        self.ps4_eye = str(ps4_eye or DEFAULT_EYE).strip().lower()
        self.ps4_backend_mode = str(ps4_backend_mode or "native").strip().lower()
        self.is_prewarming = bool(is_prewarming)

        self.cap = None
        self.ps4_backend = None
        self.fb_reader = None
        self.running = False
        self.thread = None
        self.lock = threading.Lock()
        self._stop_event = threading.Event()

        self.latest_frame = None
        self.latest_ret = False
        self.frame_seq = 0
        self.last_consumed_seq = 0
        self.actual_w = target_w
        self.actual_h = target_h
        self.actual_fps = target_fps

        self.fps_counter = 0
        self.fps_last_time = time.time()
        self.measured_fps = float(target_fps)

        self._open_and_negotiate()

    def _start_capture_thread(self):
        self.running = True
        self.thread = threading.Thread(
            target=self._capture_loop, daemon=True, name="CameraCaptureThread"
        )
        self.thread.start()

    def _open_phone_camera(self) -> bool:
        """Opens the Wi-Fi Smartphone WebApp camera backend."""
        from sensor.phone_camera import get_phone_camera_server

        srv = self.phone_cam_server or get_phone_camera_server()
        if not srv.running:
            srv.start()
        srv.configure_stream(
            width=self.target_w,
            height=self.target_h,
            fps=self.target_fps,
            streaming_active=True,
        )
        self.phone_cam_server = srv
        self.actual_w = srv.actual_w or self.target_w
        self.actual_h = srv.actual_h or self.target_h
        self.actual_fps = float(self.target_fps)
        print(
            f"[CAMERA] Phone Camera [Wi-Fi WebApp] inicializada: "
            f"{self.actual_w}x{self.actual_h}@{self.actual_fps:.0f}fps"
        )
        self._start_capture_thread()
        return True

    def _open_ps4_native(self) -> bool:
        """Opens the Native WinUSB user-space backend for PlayStation 4 Camera."""
        backend = PS4CameraBackend(
            target_w=self.target_w,
            target_h=self.target_h,
            target_fps=self.target_fps,
            eye=self.ps4_eye,
            auto_reconnect=True,
        )
        if backend.start():
            self.ps4_backend = backend
            self.actual_w = backend.actual_width
            self.actual_h = backend.actual_height
            self.actual_fps = float(backend.actual_fps)
            print(
                f"[CAMERA] PlayStation 4 Camera [Native WinUSB] inicializada: "
                f"{self.actual_w}x{self.actual_h}@{self.actual_fps:.0f}fps (Olho: {self.ps4_eye})"
            )
            self._start_capture_thread()
            return True
        print("[CAMERA] Native WinUSB PS4 backend unavailable; attempting fallback...")
        return False

    def _open_directshow_or_framebus(self):
        """Opens DirectShow / OpenCV VideoCapture (and FrameBus fallback for legacy PS4 driver)."""
        if self.is_pscam and os.name == "nt":
            self.fb_reader = FrameBusReader()

        # Prefer CAP_DSHOW on Windows for fast startup and mode control
        with _CAMERA_HW_LOCK:
            self.cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
            if not self.cap.isOpened():
                self.cap = cv2.VideoCapture(self.camera_index)

            if not self.cap.isOpened():
                if self.fb_reader and self.fb_reader.is_connected:
                    self.actual_w = self.target_w
                    self.actual_h = self.target_h
                    self.actual_fps = float(self.target_fps)
                else:
                    raise RuntimeError(f"Não foi possível abrir a câmera índice {self.camera_index}.")
            else:
                # Request resolution & FPS
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.target_w)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.target_h)
                self.cap.set(cv2.CAP_PROP_FPS, self.target_fps)

                # For USB webcams needing MJPG for high FPS (PSCam MUST preserve native YUY2/NV12)
                if not self.is_pscam and self.target_fps >= 50:
                    self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))

                # Minimize buffer size to 1 frame to eliminate latency
                try:
                    self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                except Exception:
                    pass

                self.actual_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or self.target_w
                self.actual_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or self.target_h
                prop_fps = self.cap.get(cv2.CAP_PROP_FPS)
                self.actual_fps = prop_fps if prop_fps and prop_fps > 0 else self.target_fps

        print(
            f"[CAMERA] Aberta câmera {self.camera_index}: Solicitado {self.target_w}x{self.target_h}@{self.target_fps}fps | "
            f"Obtido: {self.actual_w}x{self.actual_h}@{self.actual_fps:.1f}fps"
        )
        self._start_capture_thread()

    def _open_and_negotiate(self):
        # 0. Smartphone WebApp Camera Backend (Wi-Fi HTTPS/WSS)
        if self.is_phone_cam:
            self._open_phone_camera()
            return

        # 1. Native WinUSB Backend for PlayStation 4 Camera (Primary Path)
        if self.is_pscam and os.name == "nt" and self.ps4_backend_mode != "pscam4win":
            if self._open_ps4_native():
                return

        # 2. Legacy FrameBus / DirectShow Path
        self._open_directshow_or_framebus()

    @staticmethod
    def _is_black_frame(frame) -> bool:
        """Fast strided luminance check (~250x faster than full-frame mean)."""
        if frame is None or frame.size == 0:
            return True
        return float(frame[::16, ::16].mean()) < 1.0

    def _capture_loop(self):
        while self.running:
            ret = False
            frame = None

            # 0. Smartphone WebApp Camera Backend
            if self.is_phone_cam and self.phone_cam_server is not None:
                ph_frame = self.phone_cam_server.read_frame(only_new=True)
                if ph_frame is not None and not self._is_black_frame(ph_frame):
                    frame = ph_frame
                    ret = True
                else:
                    time.sleep(0.002)
                    continue

            # 1. Native WinUSB PS4 Camera Backend (Primary Path)
            elif self.ps4_backend is not None:
                ps_frame = self.ps4_backend.read_frame(only_new=True)
                if ps_frame is not None and not self._is_black_frame(ps_frame):
                    frame = ps_frame
                    ret = True
                else:
                    time.sleep(0.0015)
                    continue

            # 2. Legacy FrameBus IPC reader fallback
            elif self.is_pscam and self.fb_reader is not None:
                fb_frame = self.fb_reader.read_frame(only_new=True)
                if fb_frame is not None and not self._is_black_frame(fb_frame):
                    frame = fb_frame
                    ret = True
                elif self.fb_reader.is_connected and (time.perf_counter() - self.fb_reader.last_frame_time) < 0.15:
                    time.sleep(0.0015)
                    continue

            # 3. Standard DirectShow Path
            if not ret or frame is None:
                if self.cap and self.cap.isOpened():
                    ret, frame = self.cap.read()
                    if self.is_pscam and (not ret or self._is_black_frame(frame)) and self.fb_reader is not None:
                        fb_frame = self.fb_reader.read_frame(only_new=False)
                        if fb_frame is not None and not self._is_black_frame(fb_frame):
                            frame = fb_frame
                            ret = True
                else:
                    time.sleep(0.003)
                    continue

            if not ret or frame is None:
                time.sleep(0.003)
                continue

            # Auto-crop Side-by-Side stereo mode if coming from a legacy SBS source
            h, w = frame.shape[:2]
            if w >= int(1.8 * h):
                if self.ps4_eye == EYE_LEFT:
                    frame = frame[:, : w // 2]
                else:
                    frame = frame[:, w // 2 :]

            # Apply camera orientation rotation if configured
            frame = self._apply_orientation(frame)

            with self.lock:
                self.latest_frame = frame
                self.latest_ret = True
                self.frame_seq += 1
                self.actual_w = frame.shape[1]
                self.actual_h = frame.shape[0]
                self.fps_counter += 1
                now = time.time()
                elapsed = now - self.fps_last_time
                if elapsed >= 1.0:
                    self.measured_fps = self.fps_counter / elapsed
                    self.fps_counter = 0
                    self.fps_last_time = now

            # Low-CPU standby throttling while pre-warming in menu (< 0.4% CPU)
            if self.is_prewarming:
                self._stop_event.wait(0.08)

    def read(self, only_new=False):
        """
        Returns (ret, frame, measured_fps).
        When only_new=True, returns (False, None, measured_fps) if no new hardware frame
        has arrived since the previous consumed read, preventing duplicate inference.
        """
        with self.lock:
            if self.latest_frame is not None:
                if only_new and self.frame_seq == self.last_consumed_seq:
                    return False, None, self.measured_fps
                self.last_consumed_seq = self.frame_seq
                return self.latest_ret, self.latest_frame, self.measured_fps
            return False, None, 0.0

    def _apply_orientation(self, frame):
        if frame is None or self.orientation == 0:
            return frame
        if self.orientation == 90:
            return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        if self.orientation == 180:
            return cv2.rotate(frame, cv2.ROTATE_180)
        if self.orientation == 270:
            return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
        return frame

    def read_left_mono(self):
        """
        Returns the synchronized Left Eye 8-bit single-channel luminance frame (H, W)
        when running on Native PS4CameraBackend without redundant YUY2->BGR conversion (<0.08 ms).
        """
        if self.ps4_backend is not None:
            left_mono = self.ps4_backend.read_left_mono()
            return self._apply_orientation(left_mono)
        return None

    def read_right_mono(self):
        """
        Returns the synchronized Right Eye 8-bit single-channel luminance frame (H, W)
        when running on Native PS4CameraBackend without redundant YUY2->BGR conversion (<0.08 ms).
        """
        if self.ps4_backend is not None and hasattr(self.ps4_backend, "read_right_mono"):
            right_mono = self.ps4_backend.read_right_mono()
            return self._apply_orientation(right_mono)
        return None

    def read_left_eye(self, mono: bool = False):
        """
        Returns the synchronized Left Eye frame when running on Native PS4CameraBackend,
        avoiding redundant conversion of the Right Eye in Stereo Vision mode.
        If mono=True, returns 8-bit luminance plane directly without BGR conversion.
        """
        if self.ps4_backend is not None:
            if mono:
                return self.read_left_mono()
            left_bgr = self.ps4_backend.read_left_frame()
            return self._apply_orientation(left_bgr)
        return None

    def read_stereo(self, only_new=False):
        """
        Returns dual-sensor (Left + Right eye) frame dictionary when running on Native PS4CameraBackend.
        """
        if self.ps4_backend is not None:
            st = self.ps4_backend.read_stereo_frames(only_new=only_new)
            if st is not None and self.orientation != 0:
                st["left_bgr"] = self._apply_orientation(st.get("left_bgr"))
                st["right_bgr"] = self._apply_orientation(st.get("right_bgr"))
            return st
        return None

    def read_edge_metrics(self, only_new: bool = True):
        """Returns pre-computed edge metrics from the smartphone when running in phone_edge mode."""
        if self.is_phone_cam and self.phone_cam_server is not None:
            return self.phone_cam_server.read_edge_metrics(only_new=only_new)
        return None

    def set_eye(self, eye: str):
        """Switches the active PS4 Camera eye ('right' or 'left') live."""
        self.ps4_eye = str(eye or DEFAULT_EYE).strip().lower()
        if self.ps4_backend is not None:
            self.ps4_backend.set_eye(self.ps4_eye)

    def set_mirror(self, mirror):
        self.mirror = mirror

    def set_orientation(self, orientation: int):
        with self.lock:
            self.orientation = int(orientation)

    def activate_live(self):
        """
        Transitions camera from low-CPU standby pre-warming (<0.4% CPU) to full-speed live tracking.
        """
        with self.lock:
            self.is_prewarming = False
            self.fps_counter = 0
            self.fps_last_time = time.time()

    def is_compatible(
        self,
        camera_index: int,
        target_w: int,
        target_h: int,
        target_fps: int,
        mirror: bool = True,
        is_pscam: bool = False,
        orientation: int = 0,
        ps4_eye: str = DEFAULT_EYE,
        ps4_backend_mode: str = "native",
        is_phone_cam: bool = False,
    ) -> bool:
        """
        Checks whether this running camera instance matches target requirements and can be adopted immediately.
        """
        if not self.running:
            return False
        if bool(self.is_phone_cam) != bool(is_phone_cam):
            return False
        if bool(self.is_pscam) != bool(is_pscam):
            return False
        if not self.is_phone_cam and int(self.camera_index) != int(camera_index):
            return False
        if self.target_w != target_w or self.target_h != target_h or self.target_fps != target_fps:
            return False
        if int(self.orientation) != int(orientation):
            return False
        if self.is_pscam:
            if str(self.ps4_eye).lower() != str(ps4_eye or DEFAULT_EYE).lower():
                return False
            if str(self.ps4_backend_mode).lower() != str(ps4_backend_mode or "native").lower():
                return False
        return True

    def release(self):
        self.running = False
        self._stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.5)
        if self.is_phone_cam and self.phone_cam_server is not None:
            try:
                self.phone_cam_server.set_streaming_active(False)
            except Exception:
                pass
        if self.ps4_backend:
            try:
                self.ps4_backend.stop()
            except Exception:
                pass
            self.ps4_backend = None
        if self.fb_reader:
            try:
                self.fb_reader.close()
            except Exception:
                pass
            self.fb_reader = None
        with _CAMERA_HW_LOCK:
            if self.cap:
                try:
                    self.cap.release()
                except Exception:
                    pass
                self.cap = None
        print("[CAMERA] Câmera liberada com sucesso.")
