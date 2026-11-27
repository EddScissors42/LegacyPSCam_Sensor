"""
Camera Manager for Legacy PSCam Sensor.
Handles device discovery (Webcams & PlayStation 4 Camera via Native WinUSB Backend),
PS4 Camera lifecycle state machine, and re-exports FrameBusReader and LatestFrameCamera.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path
import cv2

from .camera_capture import LatestFrameCamera, _CAMERA_HW_LOCK
from .camera_win32 import (
    get_hardware_snapshot,
    get_windows_camera_names_win32,
    is_process_running_win32,
    launch_elevated_win32,
)
from .framebus_reader import FrameBusReader
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

    _get_windows_camera_names_win32 = staticmethod(get_windows_camera_names_win32)

    @staticmethod
    def is_legacy_pscam4win_installed():
        return PSCAM_TRAY_PATH.exists()

    @staticmethod
    def is_pscam_installed():
        """
        Returns True if the Native WinUSB driver package is installed/active
        or if the legacy PSCam4Win fallback is present.
        """
        if os.name == "nt" and PS4DriverInstaller.is_driver_installed():
            return True
        return PSCAM_TRAY_PATH.exists()

    @staticmethod
    def is_legacy_pscam4win_running():
        """
        Fast, zero-overhead process check via Win32 Toolhelp API for legacy PSCam4WinTray.exe.
        """
        win32_found = is_process_running_win32("pscam")
        if win32_found is True:
            return True

        # Fallback via tasklist
        try:
            output = subprocess.check_output(
                ["tasklist", "/FI", "IMAGENAME eq PSCam4WinTray.exe"],
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                encoding="utf-8",
                errors="ignore",
            )
            return "pscam" in output.lower()
        except Exception:
            return False

    @staticmethod
    def is_pscam_running():
        """
        Returns True when the Native WinUSB backend is ready or when the legacy tray is running.
        """
        if os.name == "nt" and PS4DriverInstaller.is_driver_installed():
            return True
        return CameraManager.is_legacy_pscam4win_running()

    @staticmethod
    def get_hardware_snapshot():
        """
        Returns a sorted tuple of all currently present USB and Virtual Camera device instance IDs.
        Executes in < 3ms using Win32 CfgMgr32 without spawning processes or freezing the UI.
        """
        return get_hardware_snapshot()

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

        bootloader = any("05A9&PID_0580" in d for d in snapshot)
        active_hw = (
            any("05A9&PID_058B" in d for d in snapshot)
            or any("05A9&PID_058A" in d for d in snapshot)
            or any("OV580" in d for d in snapshot)
        )
        vcam_count = sum(1 for d in snapshot if "VCAMDEVAPI" in d)
        winusb_paths = find_ps4_device_paths() if (os.name == "nt" and (active_hw or bootloader)) else []
        winusb_bound = len(winusb_paths) > 0

        if winusb_bound:
            installed = True
            running = True
        else:
            native_installed = (
                PS4DriverInstaller.has_driver_store_package_fast()
                if os.name == "nt"
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
            "state": state,
            "installed": bool(installed or winusb_bound),
            "running": bool(running or winusb_bound),
            "bootloader": bootloader,
            "active_hw": active_hw,
            "vcam_count": vcam_count,
            "winusb_bound": winusb_bound,
            "backend": "native",
        }

    @staticmethod
    def is_ps4_hardware_connected():
        """
        Checks if the physical PlayStation 4 Camera (Sony / OmniVision OV580)
        is plugged into an active USB port (either active PID 058B/058A or bootloader PID 0580).
        """
        st = CameraManager.get_ps4_camera_state()
        return st["active_hw"] or st["bootloader"]

    @staticmethod
    def initialize_ps4_camera():
        """
        Ensures the PlayStation 4 Camera WinUSB driver is installed and uploads OV580 firmware
        if the camera is currently in bootloader mode (05A9:0580).
        """
        if os.name != "nt":
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
        if os.name == "nt":
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
            env["__COMPAT_LAYER"] = "RunAsInvoker"
            subprocess.Popen(
                [str(PSCAM_TRAY_PATH)],
                cwd=str(PSCAM_TRAY_PATH.parent),
                env=env,
                creationflags=subprocess.DETACHED_PROCESS if os.name == "nt" else 0,
            )
            time.sleep(1.0)
            if CameraManager.is_legacy_pscam4win_running():
                return True, "PSCam4Win Tray started successfully!"
        except Exception:
            pass

        return launch_elevated_win32(PSCAM_TRAY_PATH)

    @staticmethod
    def get_windows_camera_names():
        """
        Retrieves camera friendly names using fast native Win32 SetupAPI (~3ms),
        falling back to WinRT get_cameras.ps1 or PnP PowerShell only if needed.
        """
        if os.name == "nt":
            win32_names = get_windows_camera_names_win32()
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
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1_path)],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                    timeout=4,
                )
                if res.returncode == 0:
                    lines = [re.sub(r"[\s\xa0]+", " ", l).strip() for l in res.stdout.strip().splitlines() if l.strip()]
                    if lines:
                        return lines
            except Exception:
                pass

        # Fallback Method 2: PowerShell PnP
        try:
            cmd = [
                "powershell",
                "-NoProfile",
                "-Command",
                "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; Get-PnpDevice -Class Camera -Status OK | Select-Object -Property FriendlyName | ConvertTo-Json",
            ]
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                timeout=4,
            )
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
                if isinstance(data, dict):
                    data = [data]
                for item in data:
                    fn = item.get("FriendlyName")
                    if fn:
                        clean_fn = re.sub(r"[\s\xa0]+", " ", fn).strip()
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
        if not any(c.is_pscam for c in cameras) and os.name == "nt":
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


__all__ = [
    "PSCAM_TRAY_PATH",
    "_CAMERA_HW_LOCK",
    "CameraInfo",
    "CameraManager",
    "FrameBusReader",
    "LatestFrameCamera",
    "DEFAULT_EYE",
    "EYE_RIGHT",
    "EYE_LEFT",
]
