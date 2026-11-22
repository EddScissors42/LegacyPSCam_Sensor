"""
Camera Manager for Legacy PSCam Sensor.
Handles device discovery (Webcams & PlayStation 4 Camera via Native WinUSB Backend),
preset negotiation, buffer control, eye selection, and zero-latency frame streaming.
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

from .ps4_backend import (
    PS4CameraBackend,
    PS4UsbDevice,
    PS4FirmwareManager,
    PS4DriverInstaller,
    DEFAULT_EYE,
    EYE_RIGHT,
    EYE_LEFT,
    find_ps4_device_paths,
)

PSCAM_TRAY_PATH = Path(r"C:\Program Files\PSCam4Win\PSCam4WinTray.exe")

# Global lock to serialize DirectShow / Camera hardware access across warmup and tracking threads
_CAMERA_HW_LOCK = threading.RLock()

class CameraInfo:
    def __init__(self, index, name="Câmera", is_pscam=False):
        self.index = index
        self.name = name
        self.is_pscam = is_pscam

    def __str__(self):
        ps_tag = " [PS Camera]" if self.is_pscam else ""
        return f"[{self.index}] {self.name}{ps_tag}"

class CameraManager:
    _fw_upload_lock = threading.Lock()
    _fw_uploading = False

    @staticmethod
    def is_legacy_pscam4win_installed():
        return PSCAM_TRAY_PATH.exists()

    @staticmethod
    def is_pscam_installed():
        """
        Returns True if the Native WinUSB driver package is installed/active
        or if the legacy PSCam4Win fallback is present.
        """
        if os.name == 'nt' and PS4DriverInstaller.is_driver_installed():
            return True
        return PSCAM_TRAY_PATH.exists()

    @staticmethod
    def is_legacy_pscam4win_running():
        """
        Fast, zero-overhead process check via Win32 Toolhelp API for legacy PSCam4WinTray.exe.
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
    def is_pscam_running():
        """
        Returns True when the Native WinUSB backend is ready or when the legacy tray is running.
        """
        if os.name == 'nt' and PS4DriverInstaller.is_driver_installed():
            return True
        return CameraManager.is_legacy_pscam4win_running()

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
    def _auto_upload_firmware_async():
        """
        Triggers a non-blocking background firmware upload when the PS4 Camera is detected
        in bootloader mode (05A9:0580) with WinUSB bound.
        """
        with CameraManager._fw_upload_lock:
            if CameraManager._fw_uploading:
                return
            CameraManager._fw_uploading = True

        def _worker():
            try:
                PS4FirmwareManager.upload_to_bootloader_device(
                    allow_download=True, wait_reenumerate_s=6.0
                )
            except Exception as e:
                print(f"[CAMERA] Auto firmware upload error: {e}")
            finally:
                with CameraManager._fw_upload_lock:
                    CameraManager._fw_uploading = False

        threading.Thread(target=_worker, daemon=True, name="PS4AutoFirmwareThread").start()

    @staticmethod
    def get_ps4_camera_state():
        """
        Evaluates the multi-stage hardware and driver lifecycle of the PS4 Camera.
        Executes in ~1.5ms using Win32 CfgMgr32 PnP snapshot and cached DriverStore lookups.
        Returns dict with:
        - 'state': 'NOT_INSTALLED' | 'DISCONNECTED' | 'DRIVER_STOPPED' | 'BOOTLOADER_UPLOADING' | 'WAITING_VCAM' | 'READY'
        - 'installed': bool
        - 'running': bool
        - 'bootloader': bool (VID_05A9&PID_0580 detected)
        - 'active_hw': bool (VID_05A9&PID_058B or 058A detected)
        - 'vcam_count': int (SWD\\VCAMDEVAPI instances present)
        - 'winusb_bound': bool
        - 'backend': 'native'
        """
        snapshot = CameraManager.get_hardware_snapshot()

        bootloader = any('05A9&PID_0580' in d for d in snapshot)
        active_hw = (
            any('05A9&PID_058B' in d for d in snapshot)
            or any('05A9&PID_058A' in d for d in snapshot)
            or any('OV580' in d for d in snapshot)
        )
        vcam_count = sum(1 for d in snapshot if 'VCAMDEVAPI' in d)
        winusb_paths = find_ps4_device_paths() if (os.name == 'nt' and (active_hw or bootloader)) else []
        winusb_bound = len(winusb_paths) > 0

        if winusb_bound:
            installed = True
            running = True
        else:
            native_installed = (
                PS4DriverInstaller.has_driver_store_package_fast()
                if os.name == 'nt'
                else False
            )
            installed = native_installed or PSCAM_TRAY_PATH.exists()
            running = native_installed or (
                CameraManager.is_legacy_pscam4win_running() if PSCAM_TRAY_PATH.exists() else False
            )

        if not installed and not winusb_bound:
            state = "NOT_INSTALLED"
        elif not active_hw and not bootloader:
            state = "DISCONNECTED"
        elif (active_hw or bootloader) and not winusb_bound and not CameraManager.is_legacy_pscam4win_running():
            state = "DRIVER_STOPPED"
        elif bootloader:
            state = "BOOTLOADER_UPLOADING"
            if winusb_bound:
                CameraManager._auto_upload_firmware_async()
        elif active_hw and winusb_bound:
            # Native WinUSB backend streams directly from the hardware without requiring a virtual camera
            state = "READY"
        elif active_hw and vcam_count == 0:
            state = "WAITING_VCAM"
        else:
            state = "READY"

        return {
            'state': state,
            'installed': bool(installed or winusb_bound),
            'running': bool(running or winusb_bound),
            'bootloader': bootloader,
            'active_hw': active_hw,
            'vcam_count': vcam_count,
            'winusb_bound': winusb_bound,
            'backend': 'native',
        }

    @staticmethod
    def is_ps4_hardware_connected():
        """
        Checks if the physical PlayStation 4 Camera (Sony / OmniVision OV580)
        is plugged into an active USB port (either active PID 058B/058A or bootloader PID 0580).
        """
        st = CameraManager.get_ps4_camera_state()
        return st['active_hw'] or st['bootloader']

    @staticmethod
    def initialize_ps4_camera():
        """
        Ensures the PlayStation 4 Camera WinUSB driver is installed and uploads OV580 firmware
        if the camera is currently in bootloader mode (05A9:0580).
        """
        if os.name != 'nt':
            return False, "PlayStation 4 Camera WinUSB backend requires Windows."

        drv_status = PS4DriverInstaller.verify_driver_status()
        if not drv_status["winusb_interface_active"] and not drv_status["driver_store_staged"]:
            ok_drv, msg_drv = PS4DriverInstaller.install_or_repair_driver()
            if not ok_drv:
                return False, msg_drv

        hw_status = PS4UsbDevice.probe_hardware_status()
        if hw_status["state"] == "READY":
            return True, "PlayStation 4 Camera (Native WinUSB) is initialized and ready!"

        if hw_status["bootloader"]:
            ok_fw, msg_fw = PS4FirmwareManager.upload_to_bootloader_device(
                allow_download=True, wait_reenumerate_s=6.5
            )
            return ok_fw, msg_fw

        if not hw_status["connected"]:
            return True, "PlayStation 4 Camera WinUSB driver is ready. Connect the camera to USB 3.0."

        return True, "PlayStation 4 Camera driver verified."

    @staticmethod
    def launch_pscam_tray():
        """
        Initializes the Native PlayStation 4 Camera WinUSB backend (driver verification + firmware upload).
        Falls back to legacy PSCam4WinTray.exe only if native driver initialization fails and legacy is present.
        """
        if os.name == 'nt':
            ok_native, msg_native = CameraManager.initialize_ps4_camera()
            if ok_native:
                return True, msg_native

        if not CameraManager.is_legacy_pscam4win_installed():
            return False, "PlayStation 4 Camera driver is not installed."
        if CameraManager.is_legacy_pscam4win_running():
            return True, "PlayStation 4 Camera driver is already active."

        # Legacy fallback strategy
        try:
            env = os.environ.copy()
            env['__COMPAT_LAYER'] = 'RunAsInvoker'
            subprocess.Popen(
                [str(PSCAM_TRAY_PATH)],
                cwd=str(PSCAM_TRAY_PATH.parent),
                env=env,
                creationflags=subprocess.DETACHED_PROCESS if os.name == 'nt' else 0
            )
            time.sleep(1.0)
            if CameraManager.is_legacy_pscam4win_running():
                return True, "PSCam4Win Tray started successfully!"
        except Exception:
            pass

        if os.name == 'nt':
            try:
                import ctypes
                ret = ctypes.windll.shell32.ShellExecuteW(
                    None,
                    "runas",
                    str(PSCAM_TRAY_PATH),
                    None,
                    str(PSCAM_TRAY_PATH.parent),
                    1
                )
                if ret > 32:
                    time.sleep(1.0)
                    return True, "PSCam4Win Tray started successfully!"
                elif ret == 5:
                    return False, "Launch cancelled: Administrator elevation was denied in Windows UAC."
                else:
                    return False, f"Failed to start driver (ShellExecute code {ret})."
            except Exception as e:
                return False, f"Failed to start driver: {e}"

        return False, "Failed to initialize PlayStation 4 Camera driver."

    @staticmethod
    def _get_windows_camera_names_win32() -> list[str]:
        """
        Enumerates active Windows video capture device friendly names directly via Win32 SetupAPI
        (`KSCATEGORY_VIDEO_CAMERA` and `GUID_DEVCLASS_CAMERA` with `DIGCF_PRESENT`).
        Executes in ~2-5ms in-process without spawning PowerShell (~645ms).
        """
        if os.name != "nt":
            return []
        try:
            import ctypes
            from ctypes import wintypes

            setupapi = ctypes.windll.setupapi

            class GUID(ctypes.Structure):
                _fields_ = [
                    ("Data1", wintypes.DWORD),
                    ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD),
                    ("Data4", wintypes.BYTE * 8),
                ]

            class SP_DEVINFO_DATA(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("ClassGuid", GUID),
                    ("DevInst", wintypes.DWORD),
                    ("Reserved", ctypes.c_void_p),
                ]

            setupapi.SetupDiGetClassDevsW.argtypes = [
                ctypes.POINTER(GUID),
                wintypes.LPCWSTR,
                wintypes.HWND,
                wintypes.DWORD,
            ]
            setupapi.SetupDiGetClassDevsW.restype = ctypes.c_void_p
            setupapi.SetupDiEnumDeviceInfo.argtypes = [
                ctypes.c_void_p,
                wintypes.DWORD,
                ctypes.POINTER(SP_DEVINFO_DATA),
            ]
            setupapi.SetupDiEnumDeviceInfo.restype = wintypes.BOOL
            setupapi.SetupDiGetDeviceRegistryPropertyW.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(SP_DEVINFO_DATA),
                wintypes.DWORD,
                ctypes.POINTER(wintypes.DWORD),
                ctypes.c_void_p,
                wintypes.DWORD,
                ctypes.POINTER(wintypes.DWORD),
            ]
            setupapi.SetupDiGetDeviceRegistryPropertyW.restype = wintypes.BOOL
            setupapi.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]

            DIGCF_PRESENT = 0x00000002
            DIGCF_DEVICEINTERFACE = 0x00000010
            SPDRP_DEVICEDESC = 0x00000000
            SPDRP_FRIENDLYNAME = 0x0000000C

            # KSCATEGORY_VIDEO_CAMERA {E5323777-F976-4F5B-9B55-B94699C46E44} (WinRT VideoCapture class)
            guid_video_cam = GUID(
                0xE5323777,
                0xF976,
                0x4F5B,
                (wintypes.BYTE * 8)(0x9B, 0x55, 0xB9, 0x46, 0x99, 0xC4, 0x6E, 0x44),
            )
            # GUID_DEVCLASS_CAMERA {CA3E7AB9-B4C3-4AE6-8251-579EF933890F}
            guid_devclass_cam = GUID(
                0xCA3E7AB9,
                0xB4C3,
                0x4AE6,
                (wintypes.BYTE * 8)(0x82, 0x51, 0x57, 0x9E, 0xF9, 0x33, 0x89, 0x0F),
            )

            names: list[str] = []
            invalid_handle = ctypes.c_void_p(-1).value
            queries = (
                (guid_video_cam, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE),
                (guid_devclass_cam, DIGCF_PRESENT),
            )
            buf = ctypes.create_unicode_buffer(512)
            req = wintypes.DWORD(0)
            reg_type = wintypes.DWORD(0)

            for guid, flags in queries:
                h_info = setupapi.SetupDiGetClassDevsW(ctypes.byref(guid), None, None, flags)
                if not h_info or h_info == -1 or h_info == invalid_handle:
                    continue
                try:
                    dev_data = SP_DEVINFO_DATA()
                    dev_data.cbSize = ctypes.sizeof(SP_DEVINFO_DATA)
                    idx = 0
                    while setupapi.SetupDiEnumDeviceInfo(h_info, idx, ctypes.byref(dev_data)):
                        idx += 1
                        val = ""
                        for prop in (SPDRP_FRIENDLYNAME, SPDRP_DEVICEDESC):
                            if setupapi.SetupDiGetDeviceRegistryPropertyW(
                                h_info,
                                ctypes.byref(dev_data),
                                prop,
                                ctypes.byref(reg_type),
                                buf,
                                ctypes.sizeof(buf),
                                ctypes.byref(req),
                            ):
                                val = re.sub(r"[\s\xa0]+", " ", buf.value).strip()
                                if val:
                                    break
                        if val and val not in names:
                            names.append(val)
                finally:
                    setupapi.SetupDiDestroyDeviceInfoList(h_info)

            return names
        except Exception:
            return []

    @staticmethod
    def get_windows_camera_names():
        """
        Retrieves camera friendly names using fast native Win32 SetupAPI (~3ms),
        falling back to WinRT get_cameras.ps1 or PnP PowerShell only if needed.
        """
        if os.name == "nt":
            win32_names = CameraManager._get_windows_camera_names_win32()
            if win32_names:
                return win32_names

        names = []
        # Fallback Method 1: WinRT DeviceInformation helper script (detects Virtual Cameras & UVC)
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

        # Fallback Method 2: PowerShell PnP
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
    def enumerate_cameras(max_probe=None, probe_hardware: bool = False):
        """
        Discovers connected video capture devices and matches with Windows PnP friendly names.
        When `probe_hardware=False` (default) and Win32 SetupAPI returns active present cameras,
        builds the camera list in ~3-5ms without blocking for 1.5s+ on physical sensor power-up.
        Returns list of CameraInfo.
        """
        cameras = []
        pnp_names = CameraManager.get_windows_camera_names()

        if os.name == "nt" and pnp_names and not probe_hardware:
            limit = min(len(pnp_names), max_probe) if max_probe is not None else len(pnp_names)
            for idx in range(limit):
                name = re.sub(r"[\s\xa0]+", " ", pnp_names[idx]).strip()
                is_ps = any(k in name.lower() for k in ("ps4", "playstation", "ov580", "pscam"))
                if is_ps and "ps4" not in name.lower() and "playstation" not in name.lower():
                    name = f"PlayStation 4 Camera ({name})"
                display_res = "1280x800" if is_ps else "640x480"
                cameras.append(CameraInfo(idx, f"{name} ({display_res})", is_pscam=is_ps))
        else:
            limit = max_probe if max_probe is not None else max(len(pnp_names), 2)
            for idx in range(limit):
                cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW) if os.name == "nt" else cv2.VideoCapture(idx)
                if not cap.isOpened() and os.name != "nt":
                    cap = cv2.VideoCapture(idx)

                if cap.isOpened():
                    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    ret = True
                    if w <= 0 or h <= 0:
                        ret, _ = cap.read()
                        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    cap.release()

                    if ret or w > 0:
                        name = pnp_names[idx] if idx < len(pnp_names) else f"Video Device #{idx}"
                        name = re.sub(r"[\s\xa0]+", " ", name).strip()
                        is_ps = any(k in name.lower() for k in ["ps4", "playstation", "ov580", "pscam"]) or (
                            w == 1280 and h in (400, 800) and CameraManager.is_pscam_running()
                        )
                        if is_ps and "ps4" not in name.lower() and "playstation" not in name.lower():
                            name = f"PlayStation 4 Camera ({name})"
                        display_res = "1280x800" if is_ps else (f"{w}x{h}" if w > 0 and h > 0 else "640x480")
                        cameras.append(CameraInfo(idx, f"{name} ({display_res})", is_pscam=is_ps))

        # Ensure PS4 Camera is listed if Native WinUSB backend (or legacy fallback) detects hardware
        if not any(c.is_pscam for c in cameras) and os.name == 'nt':
            ps4_state = CameraManager.get_ps4_camera_state()
            if ps4_state.get("state") in ("READY", "BOOTLOADER_UPLOADING", "WAITING_VCAM") and (
                ps4_state.get("winusb_bound") or ps4_state.get("running")
            ):
                cameras.append(
                    CameraInfo(len(cameras), "PlayStation 4 Camera [Native WinUSB] (1280x800)", is_pscam=True)
                )

        if not cameras:
            cameras.append(CameraInfo(0, "Default Camera (Index 0)", False))

        try:
            from sensor.session_logger import get_session_logger
            get_session_logger().log_camera_discovery(
                cameras,
                pscam_installed=CameraManager.is_legacy_pscam4win_installed(),
                pscam_running=CameraManager.is_legacy_pscam4win_running(),
            )
        except Exception:
            pass

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

            UnmapViewOfFile = ctypes.windll.kernel32.UnmapViewOfFile
            UnmapViewOfFile.argtypes = [ctypes.c_void_p]
            CloseHandle = ctypes.windll.kernel32.CloseHandle
            CloseHandle.argtypes = [wintypes.HANDLE]

            # PS4 cameras are assigned top-down: slot 7 first (or 6 for split), PS3 cameras to 0..5
            for s in [7, 6, 0, 1, 2, 3, 4, 5]:
                name = f"Global\\PSCam4Win{s}.FrameBus"
                h = OpenFileMappingW(FILE_MAP_READ, False, name)
                if h:
                    # Map entire section (dwNumberOfBytesToMap = 0) so we never exceed section size
                    ptr = MapViewOfFile(h, FILE_MAP_READ, 0, 0, 0)
                    if ptr:
                        raw = ctypes.string_at(ptr, 64)
                        magic, ver, fmt, w, h_dim = struct.unpack('<IIIII', raw[:20])
                        if magic == 0x50533345 and w > 0 and h_dim > 0:
                            self.h_map = h
                            self.view_ptr = ptr
                            self.slot = s
                            return
                        UnmapViewOfFile(ptr)
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

    def _open_and_negotiate(self):
        # 0. Smartphone WebApp Camera Backend (Wi-Fi HTTPS/WSS)
        if self.is_phone_cam:
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
            self.running = True
            self.thread = threading.Thread(
                target=self._capture_loop, daemon=True, name="CameraCaptureThread"
            )
            self.thread.start()
            return

        # 1. Native WinUSB Backend for PlayStation 4 Camera (Primary Path)
        if self.is_pscam and os.name == 'nt' and self.ps4_backend_mode != "pscam4win":
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
                self.running = True
                self.thread = threading.Thread(
                    target=self._capture_loop, daemon=True, name="CameraCaptureThread"
                )
                self.thread.start()
                return
            else:
                print("[CAMERA] Native WinUSB PS4 backend unavailable; attempting fallback...")

        # 2. Legacy FrameBus / DirectShow Fallback
        if self.is_pscam and os.name == 'nt':
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
                    frame = frame[:, :w // 2]
                else:
                    frame = frame[:, w // 2:]

            # Apply camera orientation rotation if configured
            if self.orientation == 90:
                frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
            elif self.orientation == 180:
                frame = cv2.rotate(frame, cv2.ROTATE_180)
            elif self.orientation == 270:
                frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

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
                time.sleep(0.08)

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
        """
        Switches the active PS4 Camera eye ("right" or "left") live.
        """
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
