"""
Camera Manager for Legacy Sensor Lite.
Handles device discovery (Webcams & PlayStation Camera via PSCam4Win),
preset negotiation, buffer control, and zero-latency frame streaming.
"""
import json
import os
import re
import struct
import subprocess
import threading
import time
from pathlib import Path
import cv2

PSCAM_TRAY_PATH = Path(r"C:\Program Files\PSCam4Win\PSCam4WinTray.exe")

class CameraInfo:
    def __init__(self, index, name="Câmera", is_pscam=False):
        self.index = index
        self.name = name
        self.is_pscam = is_pscam

    def __str__(self):
        ps_tag = " [PS Camera]" if self.is_pscam else ""
        return f"[{self.index}] {self.name}{ps_tag}"

class CameraManager:
    @staticmethod
    def is_pscam_installed():
        return PSCAM_TRAY_PATH.exists()

    @staticmethod
    def is_pscam_running():
        """
        Fast, zero-overhead process check via Win32 Toolhelp API.
        Detects PSCam4WinTray.exe or any pscam background process.
        Falls back to tasklist if ctypes snapshot fails.
        """
        if os.name == 'nt':
            try:
                import ctypes
                import ctypes.wintypes
                TH32CS_SNAPPROCESS = 0x00000002
                class PROCESSENTRY32(ctypes.Structure):
                    _fields_ = [
                        ('dwSize', ctypes.wintypes.DWORD),
                        ('cntUsage', ctypes.wintypes.DWORD),
                        ('th32ProcessID', ctypes.wintypes.DWORD),
                        ('th32DefaultHeapID', ctypes.c_void_p),
                        ('th32ModuleID', ctypes.wintypes.DWORD),
                        ('cntThreads', ctypes.wintypes.DWORD),
                        ('th32ParentProcessID', ctypes.wintypes.DWORD),
                        ('pcPriClassBase', ctypes.c_long),
                        ('dwFlags', ctypes.wintypes.DWORD),
                        ('szExeFile', ctypes.c_char * 260)
                    ]
                h_snapshot = ctypes.windll.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
                if h_snapshot and h_snapshot != -1:
                    pe = PROCESSENTRY32()
                    pe.dwSize = ctypes.sizeof(PROCESSENTRY32)
                    found = False
                    if ctypes.windll.kernel32.Process32First(h_snapshot, ctypes.byref(pe)):
                        while True:
                            proc_name = pe.szExeFile.decode('utf-8', errors='ignore').lower()
                            if 'pscam' in proc_name:
                                found = True
                                break
                            if not ctypes.windll.kernel32.Process32Next(h_snapshot, ctypes.byref(pe)):
                                break
                    ctypes.windll.kernel32.CloseHandle(h_snapshot)
                    if found:
                        return True
            except Exception:
                pass

        # Fallback via tasklist
        try:
            output = subprocess.check_output(
                ['tasklist', '/FI', 'IMAGENAME eq PSCam4WinTray.exe'],
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                encoding='utf-8',
                errors='ignore'
            )
            return "pscam" in output.lower()
        except Exception:
            return False

    @staticmethod
    def get_hardware_snapshot():
        """
        Returns a sorted tuple of all currently present USB and Virtual Camera device instance IDs.
        Executes in < 3ms using Win32 CfgMgr32 without spawning processes or freezing the UI.
        """
        if os.name != 'nt':
            return ()
        try:
            import ctypes
            from ctypes import wintypes
            cfgmgr = ctypes.windll.cfgmgr32
            CM_GETIDLIST_FILTER_PRESENT = 0x00000100
            buf_len = wintypes.ULONG(0)
            res = cfgmgr.CM_Get_Device_ID_List_SizeW(ctypes.byref(buf_len), None, CM_GETIDLIST_FILTER_PRESENT)
            if res != 0 or buf_len.value == 0:
                return ()

            buf = ctypes.create_unicode_buffer(buf_len.value)
            res2 = cfgmgr.CM_Get_Device_ID_ListW(None, buf, buf_len.value, CM_GETIDLIST_FILTER_PRESENT)
            if res2 != 0:
                return ()

            raw_bytes = ctypes.string_at(ctypes.byref(buf), buf_len.value * 2)
            devs = tuple(sorted(
                d.upper() for d in raw_bytes.decode('utf-16-le', errors='ignore').split('\x00')
                if d and ('USB\\' in d.upper() or 'VCAM' in d.upper() or 'CAMERA' in d.upper())
            ))
            return devs
        except Exception:
            return ()

    @staticmethod
    def get_ps4_camera_state():
        """
        Evaluates the multi-stage hardware and driver lifecycle of the PS4 Camera.
        Returns dict with:
        - 'state': 'NOT_INSTALLED' | 'DISCONNECTED' | 'DRIVER_STOPPED' | 'BOOTLOADER_UPLOADING' | 'WAITING_VCAM' | 'READY'
        - 'installed': bool
        - 'running': bool
        - 'bootloader': bool (VID_05A9&PID_0580 detected)
        - 'active_hw': bool (VID_05A9&PID_058B detected)
        - 'vcam_count': int (SWD\\VCAMDEVAPI instances present)
        """
        installed = CameraManager.is_pscam_installed()
        running = CameraManager.is_pscam_running()
        snapshot = CameraManager.get_hardware_snapshot()

        bootloader = any('05A9&PID_0580' in d for d in snapshot)
        active_hw = any('05A9&PID_058B' in d for d in snapshot) or any('OV580' in d for d in snapshot)
        vcam_count = sum(1 for d in snapshot if 'VCAMDEVAPI' in d)

        if not installed:
            state = "NOT_INSTALLED"
        elif not active_hw and not bootloader:
            state = "DISCONNECTED"
        elif not running:
            state = "DRIVER_STOPPED"
        elif bootloader:
            state = "BOOTLOADER_UPLOADING"
        elif active_hw and vcam_count == 0:
            state = "WAITING_VCAM"
        else:
            state = "READY"

        return {
            'state': state,
            'installed': installed,
            'running': running,
            'bootloader': bootloader,
            'active_hw': active_hw,
            'vcam_count': vcam_count
        }

    @staticmethod
    def is_ps4_hardware_connected():
        """
        Checks if the physical PlayStation 4 Camera (Sony / OmniVision OV580)
        is plugged into an active USB port (either active PID 058B or bootloader PID 0580).
        """
        st = CameraManager.get_ps4_camera_state()
        return st['active_hw'] or st['bootloader']

    @staticmethod
    def launch_pscam_tray():
        if not CameraManager.is_pscam_installed():
            return False, "PSCam4Win is not installed in C:\\Program Files\\PSCam4Win."
        if CameraManager.is_pscam_running():
            return True, "PSCam4Win is already running."
        try:
            subprocess.Popen(
                [str(PSCAM_TRAY_PATH)],
                creationflags=subprocess.DETACHED_PROCESS if os.name == 'nt' else 0
            )
            time.sleep(1.0)
            return True, "PSCam4Win Tray started successfully!"
        except Exception as e:
            return False, f"Failed to start PSCam4Win: {e}"

    @staticmethod
    def get_windows_camera_names():
        """Retrieves camera friendly names using WinRT get_cameras.ps1 or PnP fallback."""
        names = []
        # Method 1: WinRT DeviceInformation helper script (detects Virtual Cameras & UVC)
        base = Path(__file__).resolve().parent
        candidates = [base / "tools" / "get_cameras.ps1", base.parent / "tools" / "get_cameras.ps1"]
        ps1_path = next((c for c in candidates if c.exists()), base.parent / "tools" / "get_cameras.ps1")
        if ps1_path.exists():
            try:
                res = subprocess.run(
                    ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(ps1_path)],
                    capture_output=True, text=True, encoding='utf-8', errors='ignore',
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                    timeout=4
                )
                if res.returncode == 0:
                    lines = [re.sub(r'[\s\xa0]+', ' ', l).strip() for l in res.stdout.strip().splitlines() if l.strip()]
                    if lines:
                        return lines
            except Exception:
                pass

        # Method 2: Fallback to PnP
        try:
            cmd = [
                'powershell', '-NoProfile', '-Command',
                '[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; Get-PnpDevice -Class Camera -Status OK | Select-Object -Property FriendlyName | ConvertTo-Json'
            ]
            res = subprocess.run(
                cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore',
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                timeout=4
            )
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
                if isinstance(data, dict):
                    data = [data]
                for item in data:
                    fn = item.get("FriendlyName")
                    if fn:
                        clean_fn = re.sub(r'[\s\xa0]+', ' ', fn).strip()
                        names.append(clean_fn)
        except Exception:
            pass
        return names

    @staticmethod
    def enumerate_cameras(max_probe=None):
        """
        Probes video capture devices and matches with Windows friendly names.
        Returns list of CameraInfo.
        """
        cameras = []
        pnp_names = CameraManager.get_windows_camera_names()
        limit = max_probe if max_probe is not None else max(len(pnp_names), 2)

        for idx in range(limit):
            cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap = cv2.VideoCapture(idx)

            if cap.isOpened():
                ret, _ = cap.read()
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                cap.release()

                if ret or w > 0:
                    name = pnp_names[idx] if idx < len(pnp_names) else f"Video Device #{idx}"
                    name = re.sub(r'[\s\xa0]+', ' ', name).strip()
                    is_ps = any(k in name.lower() for k in ["ps4", "playstation", "ov580", "pscam"]) or (w == 1280 and h in (400, 800) and CameraManager.is_pscam_running())
                    if is_ps and "ps4" not in name.lower() and "playstation" not in name.lower():
                        name = f"PlayStation 4 Camera ({name})"
                    display_res = "1280x800" if is_ps else f"{w}x{h}"
                    cameras.append(CameraInfo(idx, f"{name} ({display_res})", is_pscam=is_ps))

        if not cameras:
            cameras.append(CameraInfo(0, "Default Camera (Index 0)", False))

        return cameras

class FrameBusReader:
    """
    Direct Shared Memory Frame Reader for PSCam4Win (FrameBus IPC).
    Bypasses Windows Camera Frame Server media type caching and DirectShow
    format negotiation mismatches by reading pristine uncompressed YUY2 frames
    directly from Global\\PSCam4Win{slot}.FrameBus.
    """
    def __init__(self):
        self.h_map = None
        self.view_ptr = None
        self.slot = -1
        self.last_frame_id = -1
        self.last_frame_time = 0.0
        self._connect()

    @property
    def is_connected(self) -> bool:
        return self.view_ptr is not None

    def _connect(self):
        if os.name != 'nt':
            return
        try:
            import ctypes
            from ctypes import wintypes
            FILE_MAP_READ = 0x0004
            OpenFileMappingW = ctypes.windll.kernel32.OpenFileMappingW
            OpenFileMappingW.restype = wintypes.HANDLE
            OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]

            MapViewOfFile = ctypes.windll.kernel32.MapViewOfFile
            MapViewOfFile.restype = ctypes.c_void_p
            MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]

            CloseHandle = ctypes.windll.kernel32.CloseHandle

            # PS4 cameras are assigned top-down: slot 7 first (or 6 for split), PS3 cameras to 0..5
            for s in [7, 6, 0, 1, 2, 3, 4, 5]:
                name = f"Global\\PSCam4Win{s}.FrameBus"
                h = OpenFileMappingW(FILE_MAP_READ, False, name)
                if h:
                    ptr = MapViewOfFile(h, FILE_MAP_READ, 0, 0, 4096 + 2560 * 800 * 2)
                    if ptr:
                        raw = ctypes.string_at(ptr, 64)
                        magic, ver, fmt, w, h_dim = struct.unpack('<IIIII', raw[:20])
                        if magic == 0x50533345 and w > 0 and h_dim > 0:
                            self.h_map = h
                            self.view_ptr = ptr
                            self.slot = s
                            return
                    CloseHandle(h)
        except Exception:
            pass

    def read_frame(self, only_new: bool = False):
        """
        Reads and decodes a YUY2 frame from the PSCam4Win FrameBus shared memory.
        If only_new=True, skips YUY2->BGR conversion when frame_id has not advanced.
        """
        if not self.view_ptr:
            self._connect()
            if not self.view_ptr:
                return None
        try:
            import ctypes
            import numpy as np

            raw_hdr = ctypes.string_at(self.view_ptr, 64)
            magic, ver, fmt, w, h_dim, fpsNum, fpsDen, jpegLen, regionBytes, seq, frame_id, qpc = struct.unpack(
                '<IIIIIIIIIxxxxqqq', raw_hdr
            )

            # Seqlock check: even sequence number indicates consistent frame data
            if magic == 0x50533345 and (seq % 2 == 0) and w > 0 and h_dim > 0:
                if only_new and frame_id == self.last_frame_id and self.last_frame_id != -1:
                    return None
                raw_pixels = ctypes.string_at(self.view_ptr + 4096, w * h_dim * 2)
                yuy2 = np.frombuffer(raw_pixels, dtype=np.uint8).reshape((h_dim, w, 2))
                bgr = cv2.cvtColor(yuy2, cv2.COLOR_YUV2BGR_YUY2)
                self.last_frame_id = frame_id
                self.last_frame_time = time.perf_counter()
                return bgr
        except Exception:
            pass
        return None

    def close(self):
        if self.h_map:
            try:
                import ctypes
                from ctypes import wintypes
                UnmapViewOfFile = ctypes.windll.kernel32.UnmapViewOfFile
                UnmapViewOfFile.argtypes = [ctypes.c_void_p]
                CloseHandle = ctypes.windll.kernel32.CloseHandle
                CloseHandle.argtypes = [wintypes.HANDLE]

                if self.view_ptr:
                    UnmapViewOfFile(self.view_ptr)
                    self.view_ptr = None
                CloseHandle(self.h_map)
            except Exception:
                pass
            self.h_map = None
            self.slot = -1

class LatestFrameCamera:
    """
    Zero-latency threaded camera grabber.
    Continually reads from OpenCV VideoCapture (or directly from PSCam4Win FrameBus)
    on a background thread so the internal OpenCV frame queue never buffers stale frames.
    Handles black-frame recovery and automatic Side-by-Side stereo cropping.
    Always delivers pristine, un-mirrored frames to the pose tracker.
    """
    def __init__(self, camera_index, target_w=640, target_h=480, target_fps=30, mirror=True, is_pscam=False):
        self.camera_index = camera_index
        self.target_w = target_w
        self.target_h = target_h
        self.target_fps = target_fps
        self.mirror = mirror
        self.is_pscam = is_pscam

        self.cap = None
        self.fb_reader = FrameBusReader() if (self.is_pscam and os.name == 'nt') else None
        self.running = False
        self.thread = None
        self.lock = threading.Lock()

        self.latest_frame = None
        self.latest_ret = False
        self.actual_w = target_w
        self.actual_h = target_h
        self.actual_fps = target_fps

        self.fps_counter = 0
        self.fps_last_time = time.time()
        self.measured_fps = float(target_fps)

        self._open_and_negotiate()

    def _open_and_negotiate(self):
        # Prefer CAP_DSHOW on Windows for fast startup and mode control
        self.cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
        if not self.cap.isOpened():
            self.cap = cv2.VideoCapture(self.camera_index)

        if not self.cap.isOpened():
            raise RuntimeError(f"Não foi possível abrir a câmera índice {self.camera_index}.")

        # Request resolution & FPS
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.target_w)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.target_h)
        self.cap.set(cv2.CAP_PROP_FPS, self.target_fps)

        # For USB webcams needing MJPG for high FPS (PSCam uses native YUY2/NV12)
        if not self.is_pscam and self.target_fps >= 50:
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))

        # Minimize buffer size to 1 frame to eliminate latency
        try:
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

        self.actual_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or self.target_w
        self.actual_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or self.target_h
        prop_fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.actual_fps = prop_fps if prop_fps and prop_fps > 0 else self.target_fps

        print(f"[CAMERA] Aberta câmera {self.camera_index}: Solicitado {self.target_w}x{self.target_h}@{self.target_fps}fps | "
              f"Obtido: {self.actual_w}x{self.actual_h}@{self.actual_fps:.1f}fps")

        self.running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True, name="CameraCaptureThread")
        self.thread.start()

    @staticmethod
    def _is_black_frame(frame) -> bool:
        """Fast strided luminance check (~250x faster than full-frame mean)."""
        if frame is None or frame.size == 0:
            return True
        return float(frame[::16, ::16].mean()) < 1.0

    def _capture_loop(self):
        while self.running and self.cap and self.cap.isOpened():
            ret = False
            frame = None

            # 1. PS Camera Primary Path: Zero-latency direct FrameBus IPC reader
            # Reads directly from PSCam4Win shared memory without blocking on DirectShow
            # or re-converting unchanged frames.
            if self.is_pscam and self.fb_reader is not None:
                fb_frame = self.fb_reader.read_frame(only_new=True)
                if fb_frame is not None and not self._is_black_frame(fb_frame):
                    frame = fb_frame
                    ret = True
                elif self.fb_reader.is_connected and (time.perf_counter() - self.fb_reader.last_frame_time) < 0.15:
                    # FrameBus is actively streaming; wait briefly for the next 60 Hz hardware tick
                    time.sleep(0.0015)
                    continue

            # 2. Standard DirectShow Path (or fallback if FrameBus is inactive)
            if not ret or frame is None:
                ret, frame = self.cap.read()
                if self.is_pscam and (not ret or self._is_black_frame(frame)) and self.fb_reader is not None:
                    fb_frame = self.fb_reader.read_frame(only_new=False)
                    if fb_frame is not None and not self._is_black_frame(fb_frame):
                        frame = fb_frame
                        ret = True

            if not ret or frame is None:
                time.sleep(0.003)
                continue

            # Auto-crop Side-by-Side stereo mode to Left Sensor (primary dancer view)
            # PS4 camera defaults to 2560x800 or 1280x400 stereo on first initialization
            h, w = frame.shape[:2]
            if w >= int(1.8 * h):
                frame = frame[:, :w // 2]

            with self.lock:
                self.latest_frame = frame
                self.latest_ret = True
                self.actual_w = frame.shape[1]
                self.actual_h = frame.shape[0]
                self.fps_counter += 1
                now = time.time()
                elapsed = now - self.fps_last_time
                if elapsed >= 1.0:
                    self.measured_fps = self.fps_counter / elapsed
                    self.fps_counter = 0
                    self.fps_last_time = now

    def read(self):
        """Returns (ret, frame, measured_fps)."""
        with self.lock:
            if self.latest_frame is not None:
                return self.latest_ret, self.latest_frame, self.measured_fps
            return False, None, 0.0

    def set_mirror(self, mirror):
        self.mirror = mirror

    def release(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
        if self.fb_reader:
            try:
                self.fb_reader.close()
            except Exception:
                pass
            self.fb_reader = None
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
        print("[CAMERA] Câmera liberada com sucesso.")
