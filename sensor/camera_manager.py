"""
Camera Manager for Legacy Sensor Lite.
Handles device discovery (Webcams & PlayStation Camera via PSCam4Win),
preset negotiation, buffer control, and zero-latency frame streaming.
"""
import json
import os
import re
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
                    cameras.append(CameraInfo(idx, f"{name} ({w}x{h})", is_pscam=is_ps))

        if not cameras:
            cameras.append(CameraInfo(0, "Default Camera (Index 0)", False))

        return cameras

class LatestFrameCamera:
    """
    Zero-latency threaded camera grabber.
    Continually reads from OpenCV VideoCapture on a background thread
    so the internal OpenCV frame queue never buffers stale frames.
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

    def _capture_loop(self):
        while self.running and self.cap and self.cap.isOpened():
            ret, frame = self.cap.read()
            if not ret or frame is None:
                time.sleep(0.003)
                continue

            with self.lock:
                self.latest_frame = frame
                self.latest_ret = True
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
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
        print("[CAMERA] Câmera liberada com sucesso.")
