"""
Kinect Emulator Module — Legacy PSCam Sensor
Emulates the Microsoft Kinect v1 sensor in-memory for Just Dance PC (Legacy Offline 2018)
without requiring any DLL file replacement in the game directory.
"""

import sys
import os
import time
import shutil
import hashlib
import ctypes
from ctypes import wintypes
import threading
from pathlib import Path
from typing import Optional, Callable, Dict, Any, List, Set, Tuple

# Win32 Constants
PROCESS_CREATE_THREAD = 0x0002
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_INJECT_ACCESS = (
    PROCESS_CREATE_THREAD
    | PROCESS_QUERY_INFORMATION
    | PROCESS_VM_OPERATION
    | PROCESS_VM_READ
    | PROCESS_VM_WRITE
)
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
MEM_RELEASE = 0x8000
PAGE_READWRITE = 0x04
LIST_MODULES_32BIT = 0x01
LIST_MODULES_64BIT = 0x02
LIST_MODULES_ALL = 0x03
TH32CS_SNAPPROCESS = 0x00000002
PE32_MAGIC = 0x010B
PE32_PLUS_MAGIC = 0x020B
ERROR_ACCESS_DENIED = 5


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


# Ordinals mapped by Legacy.exe for Kinect10.dll:
# Ordinal 16: NuiShutdown
# Ordinal 5:  NuiGetSensorCount
# Ordinal 6:  NuiCreateSensorByIndex
# Ordinal 21: NuiCreateSensorById
# Ordinal 22: NuiSetDeviceStatusCallback
# Ordinal 9:  NuiImageGetColorPixelCoordinatesFromDepthPixel
# Ordinal 17: NuiSkeletonGetNextFrame
# Ordinal 26: NuiSkeletonSetTrackedSkeletons
KINECT_ORDINALS_ORDER = [16, 5, 6, 21, 22, 9, 17, 26]

TARGET_PROCESS_NAMES = [
    "legacy.exe",
    "legacy lab.exe",
    "justdance.exe",
]

# Additional Just Dance Legacy / 2017 / Legacy Lab executable aliases detected safely alongside TARGET_PROCESS_NAMES
TARGET_PROCESS_ALIASES = (
    "legacylab.exe",
    "justdance2017.exe",
    "legacyoffline.exe",
    "legacy_offline.exe",
    "jd2017.exe",
    "jdlegacy.exe",
)

# Never match our own sensor binaries even if named similarly
_SELF_PROCESS_EXCLUDES = (
    "legacypscam",
    "legacysensor",
)

_ALL_TARGET_PROCESS_NAMES = frozenset(TARGET_PROCESS_NAMES) | frozenset(TARGET_PROCESS_ALIASES)


class KinectEmulatorDaemon:
    """
    Background daemon that monitors running processes for Just Dance PC (Legacy 32-bit).
    When a supported 32-bit game is detected:
      - Injects tools/Legacy10.dll and hot-patches the 8 Kinect10 IAT entries purely in RAM.
    """

    def __init__(self, cfg=None):
        self.cfg = cfg or {}
        self.enabled = bool(self.cfg.get("emulate_kinect_enabled", True))
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # State tracking
        self.attached_pid: Optional[int] = None
        self.attached_game_name: Optional[str] = None
        self.attached_mode: Optional[str] = None
        self.last_error_code: str = ""
        self.last_error_message: str = ""
        self._status_callbacks: List[Callable[[bool, str, int], None]] = []
        self._warned_pids: Set[Tuple[int, str]] = set()

        # Windows API bindings with explicit 64-bit pointer/handle signatures
        self._k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._psapi = ctypes.WinDLL("psapi", use_last_error=True)
        self._ntdll = ctypes.WinDLL("ntdll")
        self._configure_win32_signatures()

        # Resolve path to 32-bit (Legacy10.dll) and 64-bit (Legacy10_x64.dll) proxy DLLs, staged outside %TEMP% when frozen
        self.proxy_dll_path = self._stage_proxy_dll(self._resolve_proxy_dll_path("Legacy10.dll"), "Legacy10.dll")
        self.proxy_dll_x64_path = self._stage_proxy_dll(self._resolve_proxy_dll_path("Legacy10_x64.dll"), "Legacy10_x64.dll")

    def _log_diag_once(self, pid: int, reason_key: str, message: str) -> None:
        """Logs an injection diagnostic message once per (pid, reason_key) to prevent log spam."""
        with self._lock:
            self.last_error_code = str(reason_key)
            self.last_error_message = str(message)
        key = (int(pid), str(reason_key))
        if key in self._warned_pids:
            return
        self._warned_pids.add(key)
        print(f"[KINECT-EMU] {message}")
        try:
            from sensor.session_logger import get_session_logger
            get_session_logger().log_ipc_event("KINECT_EMULATOR_WARN", reason_key, message)
        except Exception:
            pass

    def _configure_win32_signatures(self) -> None:
        """Declares explicit 64-bit-safe argtypes and restypes for Win32 process/memory APIs."""
        self._k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self._k32.OpenProcess.restype = wintypes.HANDLE

        self._k32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._k32.CloseHandle.restype = wintypes.BOOL

        self._k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        self._k32.GetExitCodeProcess.restype = wintypes.BOOL

        self._k32.IsWow64Process.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
        self._k32.IsWow64Process.restype = wintypes.BOOL

        self._k32.VirtualAllocEx.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD
        ]
        self._k32.VirtualAllocEx.restype = ctypes.c_void_p

        self._k32.VirtualFreeEx.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD
        ]
        self._k32.VirtualFreeEx.restype = wintypes.BOOL

        self._k32.VirtualProtectEx.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)
        ]
        self._k32.VirtualProtectEx.restype = wintypes.BOOL

        self._k32.ReadProcessMemory.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)
        ]
        self._k32.ReadProcessMemory.restype = wintypes.BOOL

        self._k32.WriteProcessMemory.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)
        ]
        self._k32.WriteProcessMemory.restype = wintypes.BOOL

        self._k32.CreateRemoteThread.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
            ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)
        ]
        self._k32.CreateRemoteThread.restype = wintypes.HANDLE

        self._k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self._k32.WaitForSingleObject.restype = wintypes.DWORD

        self._k32.GetExitCodeThread.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        self._k32.GetExitCodeThread.restype = wintypes.BOOL

        self._k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        self._k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE

        self._k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
        self._k32.Process32FirstW.restype = wintypes.BOOL

        self._k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
        self._k32.Process32NextW.restype = wintypes.BOOL

        self._psapi.EnumProcessModulesEx.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.DWORD
        ]
        self._psapi.EnumProcessModulesEx.restype = wintypes.BOOL

        self._psapi.GetModuleFileNameExW.argtypes = [
            wintypes.HANDLE, wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD
        ]
        self._psapi.GetModuleFileNameExW.restype = wintypes.DWORD

        if hasattr(self._k32, "QueryFullProcessImageNameW"):
            self._k32.QueryFullProcessImageNameW.argtypes = [
                wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
            ]
            self._k32.QueryFullProcessImageNameW.restype = wintypes.BOOL

    @staticmethod
    def _resolve_proxy_dll_path(dll_name: str = "Legacy10.dll") -> Path:
        """
        Locates `tools/Legacy10.dll` (32-bit) or `tools/Legacy10_x64.dll` (64-bit)
        across source tree, PyInstaller `_MEIPASS`, and executable directory.
        """
        candidate_dirs: List[Path] = []
        if getattr(sys, "frozen", False):
            candidate_dirs.append(Path(sys.executable).resolve().parent / "tools")
            if hasattr(sys, "_MEIPASS"):
                candidate_dirs.append(Path(sys._MEIPASS).resolve() / "tools")
        pkg_root = Path(__file__).resolve().parent.parent
        candidate_dirs.append(pkg_root / "tools")
        candidate_dirs.append(pkg_root.parent / "tools")

        for d in candidate_dirs:
            p = d / dll_name
            if p.is_file():
                return p

        return candidate_dirs[0] / dll_name

    @staticmethod
    def _stage_proxy_dll(src_path: Path, dll_name: Optional[str] = None) -> Path:
        """
        When running from a PyInstaller --onefile %TEMP%\\_MEI* extraction directory,
        stages the proxy DLL into the persistent %APPDATA%\\LegacyPSCam_Sensor\\tools\\
        folder so Windows 10 Defender does not block LoadLibraryW from %TEMP%.
        """
        if not src_path.is_file():
            return src_path

        src_lower = str(src_path).lower()
        needs_staging = getattr(sys, "frozen", False) and (
            "_mei" in src_lower or "\\temp\\" in src_lower or "/temp/" in src_lower
        )
        if not needs_staging:
            return src_path

        try:
            appdata = os.environ.get("APPDATA")
            if not appdata:
                return src_path
            target_name = dll_name or src_path.name
            dst_dir = Path(appdata) / "LegacyPSCam_Sensor" / "tools"
            dst_dir.mkdir(parents=True, exist_ok=True)
            dst_path = dst_dir / target_name

            src_bytes = src_path.read_bytes()
            src_hash = hashlib.sha256(src_bytes).hexdigest()
            if dst_path.is_file():
                try:
                    if hashlib.sha256(dst_path.read_bytes()).hexdigest() == src_hash:
                        return dst_path
                except Exception:
                    pass

            tmp_path = dst_dir / f"{dst_path.stem}.{os.getpid()}.part"
            tmp_path.write_bytes(src_bytes)
            try:
                tmp_path.replace(dst_path)
            except OSError:
                # If an already-running game locks dst_path, keep using it if size matches
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass
                if dst_path.is_file() and dst_path.stat().st_size == len(src_bytes):
                    return dst_path
                return src_path
            return dst_path
        except Exception:
            return src_path

    def _get_process_path(self, pid: int) -> Optional[str]:
        """Resolves the executable absolute path of a running process."""
        h = self._k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            h = self._k32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
        if not h:
            return None
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if hasattr(self._k32, "QueryFullProcessImageNameW"):
                if self._k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                    return buf.value
            return None
        finally:
            self._k32.CloseHandle(h)

    def register_status_callback(self, cb: Callable[[bool, str, int], None]) -> None:
        """Registers a callback fn(connected: bool, game_name: str, pid: int)."""
        with self._lock:
            if cb not in self._status_callbacks:
                self._status_callbacks.append(cb)

    def _notify_status(self, connected: bool, game_name: str, pid: int) -> None:
        try:
            from sensor.session_logger import get_session_logger
            status_text = "ATTACHED" if connected else "DETACHED"
            get_session_logger().log_ipc_event(
                "KINECT_EMULATOR",
                status_text,
                f"Target Game: {game_name} (PID: {pid})",
            )
        except Exception:
            pass

        with self._lock:
            cbs = list(self._status_callbacks)
        for cb in cbs:
            try:
                cb(connected, game_name, pid)
            except Exception:
                pass

    def start(self) -> None:
        """Starts the background monitoring thread."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="KinectEmulatorDaemon")
            self._thread.start()

    def stop(self) -> None:
        """Stops the monitoring thread."""
        with self._lock:
            self._running = False
            self.attached_pid = None
            self.attached_game_name = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self._thread = None

    def get_status(self) -> Dict[str, Any]:
        """Returns current status snapshot."""
        with self._lock:
            return {
                "enabled": self.enabled,
                "running": self._running,
                "connected": self.attached_pid is not None,
                "game_name": self.attached_game_name or "",
                "pid": self.attached_pid or 0,
                "mode": self.attached_mode or "",
                "last_error_code": self.last_error_code,
                "last_error_message": self.last_error_message,
            }

    def _monitor_loop(self) -> None:
        """Main daemon loop running at 10 Hz when searching (catches fast game boot), 1.25 Hz when attached."""
        while self._running:
            try:
                if not self.enabled:
                    time.sleep(0.8)
                    continue

                if self.attached_pid is not None:
                    if not self._is_process_alive(self.attached_pid):
                        old_name = self.attached_game_name or "Game"
                        old_pid = self.attached_pid
                        with self._lock:
                            self.attached_pid = None
                            self.attached_game_name = None
                            self.attached_mode = None
                        self._notify_status(False, old_name, old_pid)
                    time.sleep(0.8)
                    continue

                target = self._scan_for_game_process()
                if target:
                    pid = target["pid"]
                    name = target["name"]
                    if self._is_target_32bit(pid):
                        success = self._hook_running_game(pid, name)
                        hook_mode = "iat_hook_32"
                    elif ctypes.sizeof(ctypes.c_void_p) == 8:
                        success = self._hook_running_game_64(pid, name)
                        hook_mode = "iat_hook_64"
                    else:
                        self._log_diag_once(
                            pid,
                            "ARCH_MISMATCH",
                            f"Process {name} (PID {pid}) is 64-bit; run the 64-bit build of Legacy PSCam Sensor to attach.",
                        )
                        success = False
                        hook_mode = ""

                    if success:
                        with self._lock:
                            self.attached_pid = pid
                            self.attached_game_name = name
                            self.attached_mode = hook_mode
                            self.last_error_code = ""
                            self.last_error_message = ""
                        self._notify_status(True, name, pid)

            except Exception as exc:
                self._log_diag_once(0, "MONITOR_LOOP_ERR", f"Monitor loop error: {exc}")

            time.sleep(0.10)

    def _is_process_alive(self, pid: int) -> bool:
        """Checks if a process handle can be opened with query permissions."""
        h = self._k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            h = self._k32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
        if not h:
            return False
        exit_code = wintypes.DWORD()
        res = self._k32.GetExitCodeProcess(h, ctypes.byref(exit_code))
        self._k32.CloseHandle(h)
        STILL_ACTIVE = 259
        return bool(res and exit_code.value == STILL_ACTIVE)

    def _is_target_32bit(self, pid: int) -> bool:
        """
        Determines whether the target process is a 32-bit (WoW64 / PE32) process.
        """
        if ctypes.sizeof(ctypes.c_void_p) == 4:
            return True
        h = self._k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            h = self._k32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
        if not h:
            return False
        try:
            is_wow64 = wintypes.BOOL(False)
            if self._k32.IsWow64Process(h, ctypes.byref(is_wow64)):
                return bool(is_wow64.value)
            return False
        finally:
            self._k32.CloseHandle(h)

    @staticmethod
    def is_target_process_name(exe_name: str) -> bool:
        """Exact case-insensitive executable name match against supported Just Dance Legacy targets."""
        if not exe_name:
            return False
        exe_lower = exe_name.rsplit("\\", 1)[-1].rsplit("/", 1)[-1].lower()
        if exe_lower not in _ALL_TARGET_PROCESS_NAMES:
            return False
        return not any(excl in exe_lower for excl in _SELF_PROCESS_EXCLUDES)

    def _scan_for_game_process(self) -> Optional[Dict[str, Any]]:
        """
        Scans active processes for target Just Dance Legacy executables using a lightweight
        Win32 Toolhelp32 kernel snapshot (< 0.5ms) with exact executable name matching.
        """
        invalid_handle = ctypes.c_void_p(-1).value
        h_snap = self._k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if not h_snap or h_snap == -1 or h_snap == invalid_handle:
            return None

        try:
            pe = _PROCESSENTRY32W()
            pe.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
            if not self._k32.Process32FirstW(h_snap, ctypes.byref(pe)):
                return None

            self_pid = os.getpid()
            while True:
                pid = int(pe.th32ProcessID)
                if pid > 4 and pid != self_pid:
                    exe_name = pe.szExeFile
                    if self.is_target_process_name(exe_name):
                        return {"pid": pid, "name": exe_name}
                if not self._k32.Process32NextW(h_snap, ctypes.byref(pe)):
                    break
        finally:
            self._k32.CloseHandle(h_snap)

        return None

    def _hook_running_game(self, pid: int, exe_name: str) -> bool:
        """
        Injects tools/Legacy10.dll into the 32-bit Just Dance Legacy process
        and patches its Kinect10 IAT entries purely in memory (RAM).
        """
        proxy_path = self.proxy_dll_path
        if not proxy_path.exists():
            self._log_diag_once(pid, "DLL_MISSING", f"Proxy DLL not found at {proxy_path}")
            return False

        h_proc = self._k32.OpenProcess(PROCESS_INJECT_ACCESS, False, pid)
        if not h_proc:
            err_code = ctypes.get_last_error()
            if err_code == ERROR_ACCESS_DENIED:
                self._log_diag_once(
                    pid,
                    "ACCESS_DENIED",
                    f"Access denied (Error 5) opening {exe_name} (PID {pid}). Run Legacy PSCam Sensor as Administrator if the game is running elevated.",
                )
            else:
                self._log_diag_once(pid, "OPEN_PROC_FAIL", f"Failed to open {exe_name} (PID {pid}), Win32 error {err_code}.")
            return False

        try:
            h_mods = (wintypes.HMODULE * 1024)()
            cb_needed = wintypes.DWORD()
            # Prefer LIST_MODULES_32BIT (0x01) so 64-bit WoW64 system DLLs never shadow 32-bit kernel32.dll on Win10
            ok_enum = self._psapi.EnumProcessModulesEx(
                h_proc, h_mods, ctypes.sizeof(h_mods), ctypes.byref(cb_needed), LIST_MODULES_32BIT
            )
            if not ok_enum or cb_needed.value == 0:
                if not self._psapi.EnumProcessModulesEx(
                    h_proc, h_mods, ctypes.sizeof(h_mods), ctypes.byref(cb_needed), LIST_MODULES_ALL
                ):
                    return False

            mod_count = min(1024, cb_needed.value // ctypes.sizeof(wintypes.HMODULE))
            mod_buf = ctypes.create_unicode_buffer(512)
            k32_base = None
            exe_base = None
            proxy_base = None
            exe_lower = exe_name.lower()

            for i in range(mod_count):
                try:
                    mod_addr = int(h_mods[i] or 0)
                    # Strictly enforce 32-bit address space (< 4 GB) to reject 64-bit WoW64 modules
                    if mod_addr == 0 or mod_addr >= 0x100000000:
                        continue
                    self._psapi.GetModuleFileNameExW(h_proc, h_mods[i], mod_buf, 512)
                    fn = mod_buf.value.lower()
                    base_name = Path(fn).name
                    if base_name == "kernel32.dll" and ("system32" in fn or "syswow64" in fn):
                        k32_base = mod_addr
                    elif base_name == exe_lower:
                        exe_base = mod_addr
                    elif "legacy10.dll" in base_name or "legacy10" in base_name:
                        proxy_base = mod_addr
                except Exception:
                    pass

            if not k32_base or not exe_base:
                return False

            # If proxy DLL is not yet loaded in the game, inject it via CreateRemoteThread(LoadLibraryW)
            if not proxy_base:
                loadlib_addr = self._find_remote_export(h_proc, k32_base, b"LoadLibraryW")
                if not loadlib_addr:
                    self._log_diag_once(
                        pid,
                        "NO_LOADLIB",
                        f"Could not resolve 32-bit LoadLibraryW in {exe_name} (PID {pid}, k32={hex(k32_base)}).",
                    )
                    return False

                dll_path_str = str(proxy_path.resolve())
                path_bytes = (dll_path_str + "\x00").encode("utf-16le")
                remote_str = self._k32.VirtualAllocEx(h_proc, None, len(path_bytes), MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
                if not remote_str:
                    return False

                remote_hmod = 0
                thread_created = False
                thread_finished = False
                try:
                    written_path = ctypes.c_size_t(0)
                    if not self._k32.WriteProcessMemory(
                        h_proc, ctypes.c_void_p(remote_str), path_bytes, len(path_bytes), ctypes.byref(written_path)
                    ):
                        return False
                    h_thread = self._k32.CreateRemoteThread(
                        h_proc, None, 0, ctypes.c_void_p(loadlib_addr), ctypes.c_void_p(remote_str), 0, None
                    )
                    if not h_thread:
                        self._log_diag_once(
                            pid,
                            "REMOTE_THREAD_FAIL",
                            f"CreateRemoteThread failed on {exe_name} (PID {pid}), Win32 error {ctypes.get_last_error()}.",
                        )
                        return False
                    thread_created = True
                    try:
                        WAIT_OBJECT_0 = 0x00000000
                        wait_res = self._k32.WaitForSingleObject(h_thread, 4000)
                        thread_finished = (wait_res == WAIT_OBJECT_0)
                        if thread_finished:
                            exit_code = wintypes.DWORD(0)
                            if self._k32.GetExitCodeThread(h_thread, ctypes.byref(exit_code)):
                                if exit_code.value not in (0, 259):  # 259 = STILL_ACTIVE
                                    remote_hmod = int(exit_code.value)
                        else:
                            self._log_diag_once(
                                pid,
                                "LOADLIB_TIMEOUT",
                                f"LoadLibraryW remote thread timed out in {exe_name} (PID {pid}); retaining remote path string to avoid UAF.",
                            )
                    finally:
                        self._k32.CloseHandle(h_thread)
                finally:
                    # Only free remote string if thread never started or cleanly finished
                    if not thread_created or thread_finished:
                        self._k32.VirtualFreeEx(h_proc, ctypes.c_void_p(remote_str), 0, MEM_RELEASE)

                # Re-enumerate 32-bit modules to locate the injected proxy DLL base address
                if self._psapi.EnumProcessModulesEx(
                    h_proc, h_mods, ctypes.sizeof(h_mods), ctypes.byref(cb_needed), LIST_MODULES_32BIT
                ):
                    mod_count = min(1024, cb_needed.value // ctypes.sizeof(wintypes.HMODULE))
                    for i in range(mod_count):
                        try:
                            mod_addr = int(h_mods[i] or 0)
                            if mod_addr == 0 or mod_addr >= 0x100000000:
                                continue
                            self._psapi.GetModuleFileNameExW(h_proc, h_mods[i], mod_buf, 512)
                            fn = mod_buf.value.lower()
                            if "legacy10.dll" in fn or "legacy10" in fn:
                                proxy_base = mod_addr
                                break
                        except Exception:
                            pass

                # Fallback: LoadLibraryW's 32-bit return value IS the loaded HMODULE base address
                if not proxy_base and remote_hmod != 0:
                    proxy_base = remote_hmod

            if not proxy_base:
                self._log_diag_once(
                    pid,
                    "LOADLIB_RETURNED_NULL",
                    f"Legacy10.dll failed to load into {exe_name} (PID {pid}) from '{proxy_path}'. Check Windows Defender / antivirus exclusions.",
                )
                return False

            exports_by_ord, exports_by_name = self._get_dll_exports(h_proc, proxy_base)
            if not exports_by_ord:
                self._log_diag_once(pid, "NO_EXPORTS", f"Could not read exports from Legacy10.dll in {exe_name} (PID {pid}).")
                return False

            ilt_rva, iat_rva = self._find_kinect_iat_descriptor(h_proc, exe_base)
            if not iat_rva:
                fallback_rva = 0x9CD250
                fallback_bytes = len(KINECT_ORDINALS_ORDER) * 4
                if self.is_target_process_name(exe_name) and self._validate_fallback_iat_rva(
                    h_proc, exe_base, fallback_rva, fallback_bytes
                ):
                    iat_rva = fallback_rva
                    print(
                        f"[KINECT-EMU] Using validated legacy IAT fallback RVA {hex(fallback_rva)} for {exe_name} (PID {pid})"
                    )
                else:
                    self._log_diag_once(
                        pid,
                        "NO_KINECT_IAT",
                        f"Kinect10.dll import descriptor not found and legacy fallback RVA {hex(fallback_rva)} failed PE32 bounds validation in {exe_name} (PID {pid}).",
                    )
                    return False
            iat_addr = exe_base + iat_rva

            # Prefer dynamic ILT (OriginalFirstThunk) matching so any ordinal order or named import works
            new_iat_pointers: List[int] = []
            if ilt_rva:
                new_iat_pointers = self._resolve_iat_via_ilt(
                    h_proc, exe_base, ilt_rva, exports_by_ord, exports_by_name
                )

            if not new_iat_pointers:
                for ord_val in KINECT_ORDINALS_ORDER:
                    fn_addr = exports_by_ord.get(ord_val)
                    if not fn_addr:
                        return False
                    new_iat_pointers.append(fn_addr)

            iat_bytes = bytearray()
            for ptr in new_iat_pointers:
                iat_bytes.extend(ptr.to_bytes(4, "little"))

            old_protect = wintypes.DWORD()
            if self._k32.VirtualProtectEx(h_proc, ctypes.c_void_p(iat_addr), len(iat_bytes), PAGE_READWRITE, ctypes.byref(old_protect)):
                written = ctypes.c_size_t(0)
                ok_write = self._k32.WriteProcessMemory(
                    h_proc, ctypes.c_void_p(iat_addr), bytes(iat_bytes), len(iat_bytes), ctypes.byref(written)
                )
                self._k32.VirtualProtectEx(h_proc, ctypes.c_void_p(iat_addr), len(iat_bytes), old_protect, ctypes.byref(old_protect))
                if ok_write and written.value == len(iat_bytes):
                    print(
                        f"[KINECT-EMU] Attached to {exe_name} (PID {pid}): patched {len(new_iat_pointers)} Kinect10 IAT entries via {proxy_path.name}"
                    )
                    return True

            self._log_diag_once(pid, "IAT_PATCH_FAIL", f"Failed to patch Kinect10 IAT in {exe_name} (PID {pid}).")
            return False

        except Exception as exc:
            self._log_diag_once(pid, "HOOK_EXCEPTION", f"Exception hooking {exe_name} (PID {pid}): {exc}")
            return False
        finally:
            self._k32.CloseHandle(h_proc)

    def _hook_running_game_64(self, pid: int, exe_name: str) -> bool:
        """
        Injects tools/Legacy10_x64.dll into a 64-bit Just Dance process (e.g., Legacy Lab.exe)
        and patches its Kinect10.dll IAT or Delay-Import IAT entries purely in memory (RAM).
        """
        proxy_path = self.proxy_dll_x64_path
        if not proxy_path.exists():
            self._log_diag_once(pid, "DLL64_MISSING", f"64-bit proxy DLL not found at {proxy_path}")
            return False

        h_proc = self._k32.OpenProcess(PROCESS_INJECT_ACCESS, False, pid)
        if not h_proc:
            err_code = ctypes.get_last_error()
            if err_code == ERROR_ACCESS_DENIED:
                self._log_diag_once(
                    pid,
                    "ACCESS_DENIED",
                    f"Access denied (Error 5) opening {exe_name} (PID {pid}). Run Legacy PSCam Sensor as Administrator if the game is running elevated.",
                )
            else:
                self._log_diag_once(pid, "OPEN_PROC_FAIL", f"Failed to open {exe_name} (PID {pid}), Win32 error {err_code}.")
            return False

        try:
            h_mods = (wintypes.HMODULE * 1024)()
            cb_needed = wintypes.DWORD()
            ok_enum = self._psapi.EnumProcessModulesEx(
                h_proc, h_mods, ctypes.sizeof(h_mods), ctypes.byref(cb_needed), LIST_MODULES_64BIT
            )
            if not ok_enum or cb_needed.value == 0:
                if not self._psapi.EnumProcessModulesEx(
                    h_proc, h_mods, ctypes.sizeof(h_mods), ctypes.byref(cb_needed), LIST_MODULES_ALL
                ):
                    return False

            mod_count = min(1024, cb_needed.value // ctypes.sizeof(wintypes.HMODULE))
            mod_buf = ctypes.create_unicode_buffer(512)
            k32_base = None
            exe_base = None
            proxy_base = None
            exe_lower = exe_name.lower()

            for i in range(mod_count):
                try:
                    mod_addr = int(h_mods[i] or 0)
                    if mod_addr == 0:
                        continue
                    self._psapi.GetModuleFileNameExW(h_proc, h_mods[i], mod_buf, 512)
                    fn = mod_buf.value.lower()
                    base_name = Path(fn).name
                    if base_name == "kernel32.dll" and "system32" in fn:
                        k32_base = mod_addr
                    elif base_name == exe_lower:
                        exe_base = mod_addr
                    elif "legacy10_x64" in base_name:
                        proxy_base = mod_addr
                except Exception:
                    pass

            if not k32_base or not exe_base:
                return False

            # Inject tools/Legacy10_x64.dll via 64-bit CreateRemoteThread(LoadLibraryW)
            if not proxy_base:
                loadlib_addr = self._find_remote_export_64(h_proc, k32_base, b"LoadLibraryW")
                if not loadlib_addr:
                    self._log_diag_once(
                        pid,
                        "NO_LOADLIB_64",
                        f"Could not resolve 64-bit LoadLibraryW in {exe_name} (PID {pid}, k32={hex(k32_base)}).",
                    )
                    return False

                dll_path_str = str(proxy_path.resolve())
                path_bytes = (dll_path_str + "\x00").encode("utf-16le")
                remote_str = self._k32.VirtualAllocEx(h_proc, None, len(path_bytes), MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
                if not remote_str:
                    return False

                thread_created = False
                thread_finished = False
                try:
                    written_path = ctypes.c_size_t(0)
                    if not self._k32.WriteProcessMemory(
                        h_proc, ctypes.c_void_p(remote_str), path_bytes, len(path_bytes), ctypes.byref(written_path)
                    ):
                        return False
                    h_thread = self._k32.CreateRemoteThread(
                        h_proc, None, 0, ctypes.c_void_p(loadlib_addr), ctypes.c_void_p(remote_str), 0, None
                    )
                    if not h_thread:
                        self._log_diag_once(
                            pid,
                            "REMOTE_THREAD_FAIL_64",
                            f"CreateRemoteThread failed on 64-bit {exe_name} (PID {pid}), Win32 error {ctypes.get_last_error()}.",
                        )
                        return False
                    thread_created = True
                    try:
                        WAIT_OBJECT_0 = 0x00000000
                        wait_res = self._k32.WaitForSingleObject(h_thread, 4000)
                        thread_finished = (wait_res == WAIT_OBJECT_0)
                        if not thread_finished:
                            self._log_diag_once(
                                pid,
                                "LOADLIB_TIMEOUT_64",
                                f"64-bit LoadLibraryW remote thread timed out in {exe_name} (PID {pid}); retaining remote path string.",
                            )
                    finally:
                        self._k32.CloseHandle(h_thread)
                finally:
                    if not thread_created or thread_finished:
                        self._k32.VirtualFreeEx(h_proc, ctypes.c_void_p(remote_str), 0, MEM_RELEASE)

                # Re-enumerate 64-bit modules to get full 64-bit HMODULE base address
                if self._psapi.EnumProcessModulesEx(
                    h_proc, h_mods, ctypes.sizeof(h_mods), ctypes.byref(cb_needed), LIST_MODULES_64BIT
                ):
                    mod_count = min(1024, cb_needed.value // ctypes.sizeof(wintypes.HMODULE))
                    for i in range(mod_count):
                        try:
                            mod_addr = int(h_mods[i] or 0)
                            if mod_addr == 0:
                                continue
                            self._psapi.GetModuleFileNameExW(h_proc, h_mods[i], mod_buf, 512)
                            if "legacy10_x64" in mod_buf.value.lower():
                                proxy_base = mod_addr
                                break
                        except Exception:
                            pass

            if not proxy_base:
                self._log_diag_once(
                    pid,
                    "LOADLIB_RETURNED_NULL_64",
                    f"Legacy10_x64.dll failed to load into {exe_name} (PID {pid}) from '{proxy_path}'.",
                )
                return False

            exports_by_ord, exports_by_name = self._get_dll_exports_64(h_proc, proxy_base)
            if not exports_by_ord:
                self._log_diag_once(pid, "NO_EXPORTS_64", f"Could not read exports from Legacy10_x64.dll in {exe_name} (PID {pid}).")
                return False

            # Search both standard Import Table and Delay Import Table (Legacy Lab uses Delay Import for Kinect10.dll)
            targets = []
            std_ilt, std_iat = self._find_kinect_iat_descriptor_64(h_proc, exe_base)
            if std_iat:
                targets.append(("IAT", std_ilt, std_iat, None))
            dly_ilt, dly_iat, dly_hmod = self._find_kinect_delay_iat_descriptor_64(h_proc, exe_base)
            if dly_iat:
                targets.append(("Delay-IAT", dly_ilt, dly_iat, dly_hmod))

            if not targets:
                self._log_diag_once(
                    pid,
                    "NO_KINECT_IAT_64",
                    f"Kinect10.dll import/delay-import descriptor not found in 64-bit {exe_name} (PID {pid}).",
                )
                return False

            patched_total = 0
            for label, ilt_rva, iat_rva, hmod_rva in targets:
                if not ilt_rva:
                    continue
                new_ptrs = self._resolve_iat_via_ilt_64(h_proc, exe_base, ilt_rva, exports_by_ord, exports_by_name)
                if not new_ptrs:
                    continue
                iat_bytes = bytearray()
                for ptr in new_ptrs:
                    iat_bytes.extend(ptr.to_bytes(8, "little"))

                iat_addr = exe_base + iat_rva
                old_protect = wintypes.DWORD()
                if self._k32.VirtualProtectEx(h_proc, ctypes.c_void_p(iat_addr), len(iat_bytes), PAGE_READWRITE, ctypes.byref(old_protect)):
                    written = ctypes.c_size_t(0)
                    ok_write = self._k32.WriteProcessMemory(
                        h_proc, ctypes.c_void_p(iat_addr), bytes(iat_bytes), len(iat_bytes), ctypes.byref(written)
                    )
                    self._k32.VirtualProtectEx(h_proc, ctypes.c_void_p(iat_addr), len(iat_bytes), old_protect, ctypes.byref(old_protect))
                    if ok_write and written.value == len(iat_bytes):
                        patched_total += len(new_ptrs)
                        # Also update Delay-Load HMODULE cache slot so __delayLoadHelper2 never re-binds original Kinect10.dll
                        if hmod_rva:
                            hmod_addr = exe_base + hmod_rva
                            hmod_old = wintypes.DWORD()
                            hmod_bytes = proxy_base.to_bytes(8, "little")
                            if self._k32.VirtualProtectEx(h_proc, ctypes.c_void_p(hmod_addr), 8, PAGE_READWRITE, ctypes.byref(hmod_old)):
                                self._k32.WriteProcessMemory(h_proc, ctypes.c_void_p(hmod_addr), hmod_bytes, 8, None)
                                self._k32.VirtualProtectEx(h_proc, ctypes.c_void_p(hmod_addr), 8, hmod_old, ctypes.byref(hmod_old))
                        print(
                            f"[KINECT-EMU] Attached to 64-bit {exe_name} (PID {pid}): patched {len(new_ptrs)} Kinect10 {label} entries via {proxy_path.name}"
                        )

            if patched_total > 0:
                return True

            self._log_diag_once(pid, "IAT_PATCH_FAIL_64", f"Failed to patch 64-bit Kinect10 IAT in {exe_name} (PID {pid}).")
            return False

        except Exception as exc:
            self._log_diag_once(pid, "HOOK_EXCEPTION_64", f"Exception hooking 64-bit {exe_name} (PID {pid}): {exc}")
            return False
        finally:
            self._k32.CloseHandle(h_proc)

    def _read_remote_pe32_header(self, h_proc, mod_base: int) -> Optional[bytes]:
        """Reads and validates a 32-bit remote PE module's DOS + NT headers (returns 256-byte NT header)."""
        dos_hdr = ctypes.create_string_buffer(64)
        if not self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(mod_base), dos_hdr, 64, None):
            return None
        if dos_hdr.raw[:2] != b"MZ":
            return None
        e_lfanew = int.from_bytes(dos_hdr.raw[0x3C:0x40], "little")
        if e_lfanew == 0 or e_lfanew > 0x100000:
            return None

        nt_hdr = ctypes.create_string_buffer(256)
        if not self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(mod_base + e_lfanew), nt_hdr, 256, None):
            return None
        if nt_hdr.raw[:4] != b"PE\x00\x00":
            return None
        opt_magic = int.from_bytes(nt_hdr.raw[0x18:0x1A], "little")
        if opt_magic != PE32_MAGIC:
            return None
        return nt_hdr.raw

    def _validate_fallback_iat_rva(self, h_proc, exe_base: int, rva: int, byte_len: int) -> bool:
        """
        Verifies that the legacy hardcoded IAT fallback RVA lies inside a valid PE32 image's
        SizeOfImage and points to readable committed memory before patching.
        """
        if rva <= 0 or byte_len <= 0:
            return False
        nt_raw = self._read_remote_pe32_header(h_proc, exe_base)
        if nt_raw is None:
            return False
        size_of_image = int.from_bytes(nt_raw[0x50:0x54], "little")
        if size_of_image < rva + byte_len:
            return False
        probe = ctypes.create_string_buffer(byte_len)
        return bool(self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(exe_base + rva), probe, byte_len, None))

    def _find_remote_export(self, h_proc, mod_base: int, func_name: bytes) -> Optional[int]:
        """Reads a 32-bit remote PE module's export directory to find an exported function address."""
        nt_raw = self._read_remote_pe32_header(h_proc, mod_base)
        if nt_raw is None:
            return None

        exp_dir_rva = int.from_bytes(nt_raw[0x78:0x7C], "little")
        if not exp_dir_rva:
            return None

        exp_dir = ctypes.create_string_buffer(40)
        if not self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(mod_base + exp_dir_rva), exp_dir, 40, None):
            return None

        num_funcs = int.from_bytes(exp_dir.raw[0x14:0x18], "little")
        num_names = int.from_bytes(exp_dir.raw[0x18:0x1C], "little")
        funcs_rva = int.from_bytes(exp_dir.raw[0x1C:0x20], "little")
        names_rva = int.from_bytes(exp_dir.raw[0x20:0x24], "little")
        ordinals_rva = int.from_bytes(exp_dir.raw[0x24:0x28], "little")

        if num_funcs == 0 or num_funcs > 65536 or num_names == 0 or num_names > 65536:
            return None
        if not funcs_rva or not names_rva or not ordinals_rva:
            return None

        names_table = (ctypes.c_uint32 * num_names)()
        if not self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(mod_base + names_rva), names_table, ctypes.sizeof(names_table), None):
            return None
        ord_table = (ctypes.c_uint16 * num_names)()
        if not self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(mod_base + ordinals_rva), ord_table, ctypes.sizeof(ord_table), None):
            return None
        funcs_table = (ctypes.c_uint32 * num_funcs)()
        if not self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(mod_base + funcs_rva), funcs_table, ctypes.sizeof(funcs_table), None):
            return None

        name_buf = ctypes.create_string_buffer(64)
        for idx in range(num_names):
            if not self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(mod_base + names_table[idx]), name_buf, 64, None):
                continue
            if name_buf.value == func_name:
                ord_idx = ord_table[idx]
                if ord_idx < num_funcs and funcs_table[ord_idx] != 0:
                    return mod_base + funcs_table[ord_idx]
                return None

        return None

    def _get_dll_exports(self, h_proc, mod_base: int) -> Tuple[Dict[int, int], Dict[bytes, int]]:
        """Maps ordinal -> VA and export_name -> VA for 32-bit Legacy10.dll proxy."""
        by_ord: Dict[int, int] = {}
        by_name: Dict[bytes, int] = {}
        nt_raw = self._read_remote_pe32_header(h_proc, mod_base)
        if nt_raw is None:
            return by_ord, by_name

        exp_dir_rva = int.from_bytes(nt_raw[0x78:0x7C], "little")
        if not exp_dir_rva:
            return by_ord, by_name

        exp_dir = ctypes.create_string_buffer(40)
        if not self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(mod_base + exp_dir_rva), exp_dir, 40, None):
            return by_ord, by_name

        base_ordinal = int.from_bytes(exp_dir.raw[0x10:0x14], "little")
        num_funcs = int.from_bytes(exp_dir.raw[0x14:0x18], "little")
        num_names = int.from_bytes(exp_dir.raw[0x18:0x1C], "little")
        funcs_rva = int.from_bytes(exp_dir.raw[0x1C:0x20], "little")
        names_rva = int.from_bytes(exp_dir.raw[0x20:0x24], "little")
        ords_rva = int.from_bytes(exp_dir.raw[0x24:0x28], "little")

        if num_funcs == 0 or num_funcs > 4096 or not funcs_rva:
            return by_ord, by_name

        funcs_table = (ctypes.c_uint32 * num_funcs)()
        if not self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(mod_base + funcs_rva), funcs_table, ctypes.sizeof(funcs_table), None):
            return by_ord, by_name

        for i in range(num_funcs):
            ord_num = base_ordinal + i
            fn_rva = funcs_table[i]
            if fn_rva != 0:
                by_ord[ord_num] = mod_base + fn_rva

        if 0 < num_names <= 4096 and names_rva and ords_rva:
            names_table = (ctypes.c_uint32 * num_names)()
            ord_table = (ctypes.c_uint16 * num_names)()
            ok_n = self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(mod_base + names_rva), names_table, ctypes.sizeof(names_table), None)
            ok_o = self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(mod_base + ords_rva), ord_table, ctypes.sizeof(ord_table), None)
            if ok_n and ok_o:
                name_buf = ctypes.create_string_buffer(128)
                for idx in range(num_names):
                    if not self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(mod_base + names_table[idx]), name_buf, 128, None):
                        continue
                    fn_idx = ord_table[idx]
                    if fn_idx < num_funcs and funcs_table[fn_idx] != 0:
                        by_name[name_buf.value] = mod_base + funcs_table[fn_idx]

        return by_ord, by_name

    def _get_dll_exports_by_ordinal(self, h_proc, mod_base: int) -> Dict[int, int]:
        """Maps ordinal -> remote virtual address for 32-bit Legacy10.dll proxy."""
        by_ord, _ = self._get_dll_exports(h_proc, mod_base)
        return by_ord

    def _find_kinect_iat_descriptor(self, h_proc, exe_base: int) -> Tuple[Optional[int], Optional[int]]:
        """Finds (OriginalFirstThunk, FirstThunk) RVAs for Kinect10.dll in 32-bit game executable."""
        nt_raw = self._read_remote_pe32_header(h_proc, exe_base)
        if nt_raw is None:
            return None, None

        imp_dir_rva = int.from_bytes(nt_raw[0x80:0x84], "little")
        if not imp_dir_rva:
            return None, None

        desc_buf = ctypes.create_string_buffer(20)
        curr_rva = imp_dir_rva

        for _ in range(512):
            if not self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(exe_base + curr_rva), desc_buf, 20, None):
                break
            if desc_buf.raw == b"\x00" * 20:
                break

            orig_first_thunk = int.from_bytes(desc_buf.raw[0x00:0x04], "little")
            name_rva = int.from_bytes(desc_buf.raw[0x0C:0x10], "little")
            first_thunk = int.from_bytes(desc_buf.raw[0x10:0x14], "little")

            if name_rva:
                name_buf = ctypes.create_string_buffer(32)
                if self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(exe_base + name_rva), name_buf, 32, None):
                    dll_name = name_buf.value.lower()
                    if b"kinect10" in dll_name or b"legacy10" in dll_name:
                        return (orig_first_thunk or None), (first_thunk or None)

            curr_rva += 20

        return None, None

    def _find_kinect_iat_rva(self, h_proc, exe_base: int) -> Optional[int]:
        """Finds FirstThunk RVA for Kinect10.dll in 32-bit game executable import directory."""
        _, first_thunk = self._find_kinect_iat_descriptor(h_proc, exe_base)
        return first_thunk

    def _resolve_iat_via_ilt(
        self,
        h_proc,
        exe_base: int,
        ilt_rva: int,
        exports_by_ord: Dict[int, int],
        exports_by_name: Dict[bytes, int],
    ) -> List[int]:
        """Walks the 32-bit Import Lookup Table to match each Kinect10 import dynamically by ordinal or name."""
        resolved: List[int] = []
        entry_buf = ctypes.c_uint32(0)
        name_buf = ctypes.create_string_buffer(128)
        for idx in range(64):
            if not self._k32.ReadProcessMemory(
                h_proc, ctypes.c_void_p(exe_base + ilt_rva + idx * 4), ctypes.byref(entry_buf), 4, None
            ):
                return []
            val = int(entry_buf.value)
            if val == 0:
                break
            if val & 0x80000000:
                ord_num = val & 0xFFFF
                fn_addr = exports_by_ord.get(ord_num)
            else:
                # IMAGE_IMPORT_BY_NAME: 2-byte hint followed by null-terminated ASCII name
                if not self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(exe_base + val + 2), name_buf, 128, None):
                    return []
                fn_addr = exports_by_name.get(name_buf.value)
            if not fn_addr:
                return []
            resolved.append(fn_addr)
        return resolved

    # =========================================================================
    # PE32+ (64-bit) Remote Introspection & Delay-Import Helpers
    # =========================================================================
    def _read_remote_pe64_header(self, h_proc, mod_base: int) -> Optional[bytes]:
        """Reads and validates a 64-bit (PE32+) remote module's DOS + NT headers (returns 264-byte NT header)."""
        dos_hdr = ctypes.create_string_buffer(64)
        if not self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(mod_base), dos_hdr, 64, None):
            return None
        if dos_hdr.raw[:2] != b"MZ":
            return None
        e_lfanew = int.from_bytes(dos_hdr.raw[0x3C:0x40], "little")
        if e_lfanew == 0 or e_lfanew > 0x100000:
            return None

        nt_hdr = ctypes.create_string_buffer(264)
        if not self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(mod_base + e_lfanew), nt_hdr, 264, None):
            return None
        if nt_hdr.raw[:4] != b"PE\x00\x00":
            return None
        opt_magic = int.from_bytes(nt_hdr.raw[0x18:0x1A], "little")
        if opt_magic != PE32_PLUS_MAGIC:
            return None
        return nt_hdr.raw

    def _find_remote_export_64(self, h_proc, mod_base: int, func_name: bytes) -> Optional[int]:
        """Finds an exported function virtual address in a remote 64-bit PE32+ module."""
        nt_raw = self._read_remote_pe64_header(h_proc, mod_base)
        if nt_raw is None:
            return None
        exp_dir_rva = int.from_bytes(nt_raw[0x88:0x8C], "little")
        if not exp_dir_rva:
            return None
        exp_dir = ctypes.create_string_buffer(40)
        if not self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(mod_base + exp_dir_rva), exp_dir, 40, None):
            return None

        num_funcs = int.from_bytes(exp_dir.raw[0x14:0x18], "little")
        num_names = int.from_bytes(exp_dir.raw[0x18:0x1C], "little")
        funcs_rva = int.from_bytes(exp_dir.raw[0x1C:0x20], "little")
        names_rva = int.from_bytes(exp_dir.raw[0x20:0x24], "little")
        ordinals_rva = int.from_bytes(exp_dir.raw[0x24:0x28], "little")

        if num_funcs == 0 or num_funcs > 65536 or num_names == 0 or num_names > 65536:
            return None
        if not funcs_rva or not names_rva or not ordinals_rva:
            return None

        names_table = (ctypes.c_uint32 * num_names)()
        if not self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(mod_base + names_rva), names_table, ctypes.sizeof(names_table), None):
            return None
        ord_table = (ctypes.c_uint16 * num_names)()
        if not self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(mod_base + ordinals_rva), ord_table, ctypes.sizeof(ord_table), None):
            return None
        funcs_table = (ctypes.c_uint32 * num_funcs)()
        if not self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(mod_base + funcs_rva), funcs_table, ctypes.sizeof(funcs_table), None):
            return None

        name_buf = ctypes.create_string_buffer(64)
        for idx in range(num_names):
            if not self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(mod_base + names_table[idx]), name_buf, 64, None):
                continue
            if name_buf.value == func_name:
                ord_idx = ord_table[idx]
                if ord_idx < num_funcs and funcs_table[ord_idx] != 0:
                    return mod_base + funcs_table[ord_idx]
                return None
        return None

    def _get_dll_exports_64(self, h_proc, mod_base: int) -> Tuple[Dict[int, int], Dict[bytes, int]]:
        """Maps ordinal -> VA and export_name -> VA for 64-bit Legacy10_x64.dll proxy."""
        by_ord: Dict[int, int] = {}
        by_name: Dict[bytes, int] = {}
        nt_raw = self._read_remote_pe64_header(h_proc, mod_base)
        if nt_raw is None:
            return by_ord, by_name

        exp_dir_rva = int.from_bytes(nt_raw[0x88:0x8C], "little")
        if not exp_dir_rva:
            return by_ord, by_name

        exp_dir = ctypes.create_string_buffer(40)
        if not self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(mod_base + exp_dir_rva), exp_dir, 40, None):
            return by_ord, by_name

        base_ordinal = int.from_bytes(exp_dir.raw[0x10:0x14], "little")
        num_funcs = int.from_bytes(exp_dir.raw[0x14:0x18], "little")
        num_names = int.from_bytes(exp_dir.raw[0x18:0x1C], "little")
        funcs_rva = int.from_bytes(exp_dir.raw[0x1C:0x20], "little")
        names_rva = int.from_bytes(exp_dir.raw[0x20:0x24], "little")
        ords_rva = int.from_bytes(exp_dir.raw[0x24:0x28], "little")

        if num_funcs == 0 or num_funcs > 4096 or not funcs_rva:
            return by_ord, by_name

        funcs_table = (ctypes.c_uint32 * num_funcs)()
        if not self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(mod_base + funcs_rva), funcs_table, ctypes.sizeof(funcs_table), None):
            return by_ord, by_name

        for i in range(num_funcs):
            ord_num = base_ordinal + i
            fn_rva = funcs_table[i]
            if fn_rva != 0:
                by_ord[ord_num] = mod_base + fn_rva

        if 0 < num_names <= 4096 and names_rva and ords_rva:
            names_table = (ctypes.c_uint32 * num_names)()
            ord_table = (ctypes.c_uint16 * num_names)()
            ok_n = self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(mod_base + names_rva), names_table, ctypes.sizeof(names_table), None)
            ok_o = self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(mod_base + ords_rva), ord_table, ctypes.sizeof(ord_table), None)
            if ok_n and ok_o:
                name_buf = ctypes.create_string_buffer(128)
                for idx in range(num_names):
                    if not self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(mod_base + names_table[idx]), name_buf, 128, None):
                        continue
                    fn_idx = ord_table[idx]
                    if fn_idx < num_funcs and funcs_table[fn_idx] != 0:
                        by_name[name_buf.value] = mod_base + funcs_table[fn_idx]

        return by_ord, by_name

    def _find_kinect_iat_descriptor_64(self, h_proc, exe_base: int) -> Tuple[Optional[int], Optional[int]]:
        """Finds standard Import Table (OriginalFirstThunk, FirstThunk) RVAs for Kinect10.dll in PE32+ executable."""
        nt_raw = self._read_remote_pe64_header(h_proc, exe_base)
        if nt_raw is None:
            return None, None
        imp_dir_rva = int.from_bytes(nt_raw[0x90:0x94], "little")
        if not imp_dir_rva:
            return None, None

        desc_buf = ctypes.create_string_buffer(20)
        curr_rva = imp_dir_rva
        for _ in range(512):
            if not self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(exe_base + curr_rva), desc_buf, 20, None):
                break
            if desc_buf.raw == b"\x00" * 20:
                break
            orig_first_thunk = int.from_bytes(desc_buf.raw[0x00:0x04], "little")
            name_rva = int.from_bytes(desc_buf.raw[0x0C:0x10], "little")
            first_thunk = int.from_bytes(desc_buf.raw[0x10:0x14], "little")
            if name_rva:
                name_buf = ctypes.create_string_buffer(32)
                if self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(exe_base + name_rva), name_buf, 32, None):
                    dll_name = name_buf.value.lower()
                    if b"kinect10" in dll_name or b"legacy10" in dll_name:
                        return (orig_first_thunk or None), (first_thunk or None)
            curr_rva += 20
        return None, None

    def _find_kinect_delay_iat_descriptor_64(
        self, h_proc, exe_base: int
    ) -> Tuple[Optional[int], Optional[int], Optional[int]]:
        """
        Finds Delay Import Table (rvaINT, rvaIAT, rvaHmod) for Kinect10.dll in 64-bit PE32+ executable
        (DataDirectory[13] at NT header offset 0xF0).
        """
        nt_raw = self._read_remote_pe64_header(h_proc, exe_base)
        if nt_raw is None:
            return None, None, None
        delay_dir_rva = int.from_bytes(nt_raw[0xF0:0xF4], "little")
        if not delay_dir_rva:
            return None, None, None

        desc_buf = ctypes.create_string_buffer(32)
        curr_rva = delay_dir_rva
        for _ in range(256):
            if not self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(exe_base + curr_rva), desc_buf, 32, None):
                break
            if desc_buf.raw == b"\x00" * 32:
                break
            attrs = int.from_bytes(desc_buf.raw[0x00:0x04], "little")
            name_rva = int.from_bytes(desc_buf.raw[0x04:0x08], "little")
            hmod_rva = int.from_bytes(desc_buf.raw[0x08:0x0C], "little")
            iat_rva = int.from_bytes(desc_buf.raw[0x0C:0x10], "little")
            int_rva = int.from_bytes(desc_buf.raw[0x10:0x14], "little")
            if (attrs & 1) and name_rva and iat_rva:
                name_buf = ctypes.create_string_buffer(32)
                if self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(exe_base + name_rva), name_buf, 32, None):
                    dll_name = name_buf.value.lower()
                    if b"kinect10" in dll_name or b"legacy10" in dll_name:
                        return (int_rva or None), iat_rva, (hmod_rva or None)
            curr_rva += 32
        return None, None, None

    def _resolve_iat_via_ilt_64(
        self,
        h_proc,
        exe_base: int,
        ilt_rva: int,
        exports_by_ord: Dict[int, int],
        exports_by_name: Dict[bytes, int],
    ) -> List[int]:
        """Walks a 64-bit Import/Delay-Import Lookup Table (8-byte thunks) to match Kinect10 imports."""
        resolved: List[int] = []
        entry_buf = ctypes.c_uint64(0)
        name_buf = ctypes.create_string_buffer(128)
        for idx in range(64):
            if not self._k32.ReadProcessMemory(
                h_proc, ctypes.c_void_p(exe_base + ilt_rva + idx * 8), ctypes.byref(entry_buf), 8, None
            ):
                return []
            val = int(entry_buf.value)
            if val == 0:
                break
            if val & 0x8000000000000000:
                ord_num = val & 0xFFFF
                fn_addr = exports_by_ord.get(ord_num)
            else:
                if not self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(exe_base + (val & 0xFFFFFFFF) + 2), name_buf, 128, None):
                    return []
                fn_addr = exports_by_name.get(name_buf.value)
            if not fn_addr:
                return []
            resolved.append(fn_addr)
        return resolved


_emulator_instance: Optional[KinectEmulatorDaemon] = None
_emulator_lock = threading.Lock()


def get_kinect_emulator(cfg: Optional[Dict[str, Any]] = None) -> KinectEmulatorDaemon:
    """Returns the singleton KinectEmulatorDaemon instance across GUI and tracking sessions."""
    global _emulator_instance
    with _emulator_lock:
        if _emulator_instance is None:
            _emulator_instance = KinectEmulatorDaemon(cfg)
        elif cfg is not None:
            _emulator_instance.cfg = cfg
            _emulator_instance.enabled = bool(cfg.get("emulate_kinect_enabled", True))
        return _emulator_instance
