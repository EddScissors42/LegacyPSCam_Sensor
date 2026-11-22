"""
WinUSB Driver Association Verifier & Administrative Helper for PlayStation 4 Camera.
Uses official Windows PnPUtil and CfgMgr32 APIs without running the main application elevated.

Security Compliance:
- Never modifies Secure Boot, Driver Signature Enforcement, or Test Signing policies.
- Never installs root certificates silently into system certificate stores.
- Never removes WinUSB.sys or third-party device drivers.
- Requests UAC elevation ONLY when installing, repairing, or removing `legacy_pscam_device.inf`.
"""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from typing import Optional

from .constants import (
    VID_OMNIVISION,
    PID_BOOTLOADER,
    PID_STREAM_FINAL,
    PID_STREAM_LEGACY,
)
from .winusb_bindings import (
    enumerate_present_device_ids,
    find_ps4_device_paths,
)

OWN_INF_FILENAME = "legacy_pscam_device.inf"
COMPATIBLE_INF_FILENAMES = ("legacy_pscam_device.inf", "ps4cam_device.inf")


class _WIN32_FIND_DATAW(ctypes.Structure):
    _fields_ = [
        ("dwFileAttributes", wintypes.DWORD),
        ("ftCreationTime", wintypes.FILETIME),
        ("ftLastAccessTime", wintypes.FILETIME),
        ("ftLastWriteTime", wintypes.FILETIME),
        ("nFileSizeHigh", wintypes.DWORD),
        ("nFileSizeLow", wintypes.DWORD),
        ("dwReserved0", wintypes.DWORD),
        ("dwReserved1", wintypes.DWORD),
        ("cFileName", wintypes.WCHAR * 260),
        ("cAlternateFileName", wintypes.WCHAR * 14),
    ]


class PS4DriverInstaller:
    """
    Inspects, installs, repairs, and uninstalls the PlayStation 4 Camera WinUSB INF package.
    Includes fast Win32 DriverStore B-tree lookups (~1ms) and thread-safe in-memory caching
    to eliminate synchronous `pnputil.exe` subprocess overhead on the UI thread.
    """

    _cache_lock = threading.Lock()
    _CACHE_TTL_S: float = 30.0
    _fast_store_cached: Optional[bool] = None
    _fast_store_ts: float = 0.0
    _inf_cache_data: Optional[list[dict]] = None
    _inf_cache_ts: float = 0.0

    @classmethod
    def invalidate_cache(cls) -> None:
        """Invalidates cached DriverStore and PnPUtil package lookups."""
        with cls._cache_lock:
            cls._fast_store_cached = None
            cls._fast_store_ts = 0.0
            cls._inf_cache_data = None
            cls._inf_cache_ts = 0.0

    @classmethod
    def has_driver_store_package_fast(cls, use_cache: bool = True) -> bool:
        """
        Checks if a compatible PS4 Camera WinUSB INF package is staged in
        `System32\\DriverStore\\FileRepository` using Win32 `FindFirstFileW` NTFS B-tree prefix seek.
        Executes in ~1.0ms on cold check and ~0.001ms when cached, avoiding `pnputil.exe` (~125ms).
        """
        if os.name != "nt":
            return False

        now = time.monotonic()
        if use_cache:
            with cls._cache_lock:
                if cls._fast_store_cached is not None and (now - cls._fast_store_ts) < cls._CACHE_TTL_S:
                    return cls._fast_store_cached

        sys_root = os.environ.get("SystemRoot", r"C:\Windows")
        repo_dir = f"{sys_root}\\System32\\DriverStore\\FileRepository"
        found = False
        try:
            k32 = ctypes.windll.kernel32
            k32.FindFirstFileW.restype = wintypes.HANDLE
            k32.FindFirstFileW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p]
            k32.FindClose.restype = wintypes.BOOL
            k32.FindClose.argtypes = [wintypes.HANDLE]

            fd = _WIN32_FIND_DATAW()
            invalid_handle = wintypes.HANDLE(-1).value
            for inf_name in COMPATIBLE_INF_FILENAMES:
                pattern = f"{repo_dir}\\{inf_name}_*"
                h_find = k32.FindFirstFileW(pattern, ctypes.byref(fd))
                if h_find and h_find != invalid_handle and h_find != 0 and h_find != -1:
                    k32.FindClose(h_find)
                    found = True
                    break
        except Exception:
            # If FileRepository check fails for any reason, fall back to pnputil query
            pkgs = cls.query_published_inf_packages(use_cache=False)
            found = len(pkgs) > 0

        with cls._cache_lock:
            cls._fast_store_cached = found
            cls._fast_store_ts = now
        return found

    @staticmethod
    def get_inf_path() -> Path:
        """
        Locates `driver/legacy_pscam_device.inf` in either frozen executable or source tree.
        """
        candidates: list[Path] = []
        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).resolve().parent
            candidates.append(exe_dir / "driver" / OWN_INF_FILENAME)
            if hasattr(sys, "_MEIPASS"):
                candidates.append(Path(sys._MEIPASS) / "driver" / OWN_INF_FILENAME)

        pkg_root = Path(__file__).resolve().parent.parent.parent
        candidates.append(pkg_root / "driver" / OWN_INF_FILENAME)

        for c in candidates:
            if c.is_file():
                return c
        return candidates[-1]

    @staticmethod
    def get_fallback_installer_path() -> Optional[Path]:
        """
        Locates the signed fallback driver installer (`tools/PSCam4Win-Setup.exe`)
        in case Windows Driver Signature Enforcement rejects an unsigned INF catalog.
        """
        candidates: list[Path] = []
        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).resolve().parent
            candidates.append(exe_dir / "tools" / "PSCam4Win-Setup.exe")
            if hasattr(sys, "_MEIPASS"):
                candidates.append(Path(sys._MEIPASS) / "tools" / "PSCam4Win-Setup.exe")

        pkg_root = Path(__file__).resolve().parent.parent.parent
        candidates.append(pkg_root / "tools" / "PSCam4Win-Setup.exe")
        candidates.append(pkg_root.parent / "tools" / "PSCam4Win-Setup.exe")

        for c in candidates:
            if c.is_file():
                return c
        return None

    @staticmethod
    def query_published_inf_packages(use_cache: bool = True) -> list[dict]:
        """
        Queries `pnputil.exe /enum-drivers` (non-elevated) and returns matching published
        driver packages for PlayStation 4 Camera WinUSB association.
        Caches results in memory to avoid redundant subprocess creation.
        """
        if os.name != "nt":
            return []

        now = time.monotonic()
        if use_cache:
            with PS4DriverInstaller._cache_lock:
                if (
                    PS4DriverInstaller._inf_cache_data is not None
                    and (now - PS4DriverInstaller._inf_cache_ts) < PS4DriverInstaller._CACHE_TTL_S
                ):
                    return list(PS4DriverInstaller._inf_cache_data)

            # Fast negative path (~1ms): if FileRepository has no matching package folder, skip pnputil.exe
            if not PS4DriverInstaller.has_driver_store_package_fast(use_cache=True):
                with PS4DriverInstaller._cache_lock:
                    PS4DriverInstaller._inf_cache_data = []
                    PS4DriverInstaller._inf_cache_ts = now
                return []

        sys_root = os.environ.get("SystemRoot", r"C:\Windows")
        pnputil_exe = Path(sys_root) / "System32" / "pnputil.exe"
        if not pnputil_exe.exists():
            pnputil_exe = Path("pnputil.exe")

        try:
            res = subprocess.run(
                [str(pnputil_exe), "/enum-drivers"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=6,
            )
            output = res.stdout or ""
        except Exception:
            return []

        matches: list[dict] = []
        current_oem: Optional[str] = None
        current_orig: Optional[str] = None
        current_provider: Optional[str] = None

        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line:
                if current_oem and current_orig:
                    orig_lower = current_orig.lower()
                    if any(k in orig_lower for k in COMPATIBLE_INF_FILENAMES):
                        matches.append(
                            {
                                "published_name": current_oem,
                                "original_name": current_orig,
                                "provider": current_provider or "",
                                "is_own": orig_lower == OWN_INF_FILENAME,
                            }
                        )
                current_oem = None
                current_orig = None
                current_provider = None
                continue

            # Match oemXX.inf regardless of Windows display language
            m_oem = re.search(r"\b(oem\d+\.inf)\b", line, re.IGNORECASE)
            if m_oem and current_oem is None:
                current_oem = m_oem.group(1).lower()
                continue

            for inf_name in COMPATIBLE_INF_FILENAMES:
                if inf_name in line.lower():
                    current_orig = inf_name
                    break

            if "Legacy PSCam Sensor" in line or "PSCam4Win" in line:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    current_provider = parts[1].strip()

        if current_oem and current_orig:
            orig_lower = current_orig.lower()
            if any(k in orig_lower for k in COMPATIBLE_INF_FILENAMES):
                matches.append(
                    {
                        "published_name": current_oem,
                        "original_name": current_orig,
                        "provider": current_provider or "",
                        "is_own": orig_lower == OWN_INF_FILENAME,
                    }
                )

        with PS4DriverInstaller._cache_lock:
            PS4DriverInstaller._inf_cache_data = list(matches)
            PS4DriverInstaller._inf_cache_ts = time.monotonic()
            PS4DriverInstaller._fast_store_cached = len(matches) > 0
            PS4DriverInstaller._fast_store_ts = PS4DriverInstaller._inf_cache_ts

        return matches

    @staticmethod
    def is_driver_installed(use_cache: bool = True) -> bool:
        """
        Returns True if either:
        1. A connected PS4 Camera already exposes a WinUSB device interface, or
        2. A compatible PS4 Camera WinUSB INF package is staged in the Windows Driver Store.
        Uses fast Win32 B-tree DriverStore lookup (~1ms) to avoid spawning `pnputil.exe`.
        """
        if os.name != "nt":
            return False
        if find_ps4_device_paths():
            return True
        return PS4DriverInstaller.has_driver_store_package_fast(use_cache=use_cache)

    @staticmethod
    def verify_driver_status() -> dict:
        """
        Comprehensive non-elevated diagnostic of the PS4 Camera WinUSB driver status.
        """
        pnp_devs = enumerate_present_device_ids()
        vid_prefix = f"USB\\VID_{VID_OMNIVISION:04X}"
        hw_present = any(
            f"{vid_prefix}&PID_{pid:04X}" in d
            for d in pnp_devs
            for pid in (PID_BOOTLOADER, PID_STREAM_FINAL, PID_STREAM_LEGACY)
        )
        winusb_paths = find_ps4_device_paths()
        packages = PS4DriverInstaller.query_published_inf_packages()
        inf_path = PS4DriverInstaller.get_inf_path()
        fallback_installer = PS4DriverInstaller.get_fallback_installer_path()

        return {
            "hardware_connected": hw_present,
            "winusb_interface_active": len(winusb_paths) > 0,
            "driver_store_staged": len(packages) > 0,
            "published_packages": packages,
            "inf_file_present": inf_path.is_file(),
            "inf_path": str(inf_path),
            "fallback_installer_present": fallback_installer is not None,
            "fallback_installer_path": str(fallback_installer) if fallback_installer else "",
            "needs_install": hw_present and not winusb_paths and not packages,
        }

    @staticmethod
    def _run_pnputil_elevated(args_str: str, timeout_s: float = 30.0) -> tuple[bool, str]:
        """
        Executes `pnputil.exe <args_str>` via a single UAC elevation prompt (ShellExecuteExW 'runas')
        and waits for completion. Never elevates the main LegacySensor process.
        """
        if os.name != "nt":
            return False, "PnPUtil is only supported on Windows."

        sys_root = os.environ.get("SystemRoot", r"C:\Windows")
        pnputil_exe = str(Path(sys_root) / "System32" / "pnputil.exe")

        class SHELLEXECUTEINFOW(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.wintypes.DWORD),
                ("fMask", ctypes.wintypes.ULONG),
                ("hwnd", ctypes.wintypes.HWND),
                ("lpVerb", ctypes.wintypes.LPCWSTR),
                ("lpFile", ctypes.wintypes.LPCWSTR),
                ("lpParameters", ctypes.wintypes.LPCWSTR),
                ("lpDirectory", ctypes.wintypes.LPCWSTR),
                ("nShow", ctypes.c_int),
                ("hInstApp", ctypes.wintypes.HINSTANCE),
                ("lpIDList", ctypes.c_void_p),
                ("lpClass", ctypes.wintypes.LPCWSTR),
                ("hkeyClass", ctypes.wintypes.HKEY),
                ("dwHotKey", ctypes.wintypes.DWORD),
                ("hIconOrMonitor", ctypes.wintypes.HANDLE),
                ("hProcess", ctypes.wintypes.HANDLE),
            ]

        SEE_MASK_NOCLOSEPROCESS = 0x00000040
        SW_HIDE = 0

        sei = SHELLEXECUTEINFOW()
        sei.cbSize = ctypes.sizeof(SHELLEXECUTEINFOW)
        sei.fMask = SEE_MASK_NOCLOSEPROCESS
        sei.hwnd = None
        sei.lpVerb = "runas"
        sei.lpFile = pnputil_exe
        sei.lpParameters = args_str
        sei.lpDirectory = str(Path(sys_root) / "System32")
        sei.nShow = SW_HIDE

        shell32 = ctypes.windll.shell32
        kernel32 = ctypes.windll.kernel32

        if not shell32.ShellExecuteExW(ctypes.byref(sei)):
            err = kernel32.GetLastError()
            if err == 1223:  # ERROR_CANCELLED
                return False, "Administrator UAC prompt was cancelled by the user."
            return False, f"Failed to launch administrative helper (Win32 error {err})."

        if sei.hProcess:
            try:
                kernel32.WaitForSingleObject(sei.hProcess, int(timeout_s * 1000))
                exit_code = ctypes.wintypes.DWORD(0)
                kernel32.GetExitCodeProcess(sei.hProcess, ctypes.byref(exit_code))
                code = exit_code.value
                # pnputil exit code 0 = installed, 259 = staged (device not currently plugged), 3010 = reboot needed
                if code in (0, 259, 3010):
                    return True, f"WinUSB driver package staged successfully (code {code})."
                return False, f"PnPUtil returned exit code {code} (package may require catalog signature in production builds)."
            finally:
                kernel32.CloseHandle(sei.hProcess)

        return True, "Administrative helper executed."

    @staticmethod
    def install_or_repair_driver(
        force_reinstall: bool = False,
        allow_fallback_installer: bool = True,
    ) -> tuple[bool, str]:
        """
        Ensures WinUSB is associated with the PlayStation 4 Camera.
        If already active and `force_reinstall=False`, returns immediately without UAC prompt.
        If `pnputil` fails due to Windows Driver Signature Enforcement on an unsigned INF catalog,
        automatically falls back to `tools/PSCam4Win-Setup.exe` when available.
        """
        status = PS4DriverInstaller.verify_driver_status()
        if not force_reinstall and (status["winusb_interface_active"] or status["driver_store_staged"]):
            return True, "PlayStation 4 Camera WinUSB driver is already installed and verified."

        inf_path = PS4DriverInstaller.get_inf_path()
        if not inf_path.is_file():
            return False, f"Driver INF file not found at {inf_path}."

        args = f'/add-driver "{inf_path}" /install'
        ok, msg = PS4DriverInstaller._run_pnputil_elevated(args)
        PS4DriverInstaller.invalidate_cache()
        if ok or PS4DriverInstaller.is_driver_installed(use_cache=False):
            return True, msg

        # Fallback to signed PSCam4Win-Setup.exe installer if pnputil rejected unsigned catalog
        if allow_fallback_installer and "cancelled" not in msg.lower():
            fallback_exe = PS4DriverInstaller.get_fallback_installer_path()
            if fallback_exe is not None and fallback_exe.is_file():
                try:
                    os.startfile(str(fallback_exe))
                    return (
                        False,
                        f"{msg}\n\nLaunched signed fallback driver installer ({fallback_exe.name}). "
                        "Complete the setup wizard and click Start Tracking again.",
                    )
                except Exception as exc:
                    return False, f"{msg} (Fallback installer launch failed: {exc})"

        return ok, msg

    @staticmethod
    def uninstall_own_driver() -> tuple[bool, str]:
        """
        Removes ONLY `legacy_pscam_device.inf` packages published by Legacy PSCam Sensor.
        Never removes `WinUSB.sys` or packages belonging to other applications.
        """
        packages = PS4DriverInstaller.query_published_inf_packages(use_cache=False)
        own_pkgs = [p for p in packages if p.get("is_own")]
        if not own_pkgs:
            return True, "No Legacy PSCam Sensor driver package found to remove."

        for pkg in own_pkgs:
            oem = pkg["published_name"]
            ok, msg = PS4DriverInstaller._run_pnputil_elevated(f"/delete-driver {oem} /uninstall")
            if not ok:
                PS4DriverInstaller.invalidate_cache()
                return False, msg

        PS4DriverInstaller.invalidate_cache()
        return True, "Legacy PSCam Sensor driver package removed cleanly."
