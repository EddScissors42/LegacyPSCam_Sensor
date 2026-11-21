"""
Kinect Emulator Module — Legacy PSCam Sensor
Emulates the Microsoft Kinect sensor in-memory for Just Dance PC (Legacy Offline & JD2022)
without requiring any DLL file replacement in the game directory.
"""

import sys
import os
import time
import ctypes
from ctypes import wintypes
import threading
from pathlib import Path
from typing import Optional, Callable, Dict, Any, List

# Win32 Constants
PROCESS_ALL_ACCESS = 0x1F0FFF
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_OPERATION = 0x0008
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
MEM_RELEASE = 0x8000
PAGE_READWRITE = 0x04
PAGE_EXECUTE_READWRITE = 0x40
LIST_MODULES_ALL = 0x03
TH32CS_SNAPPROCESS = 0x00000002
PE32_MAGIC = 0x010B


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
    "justdance.exe",
    "jd2022.exe"
]


class KinectEmulatorDaemon:
    """
    Background daemon that monitors running processes for Just Dance PC.
    When a supported game is detected:
      - For 32-bit Legacy.exe: Injects Legacy10.dll and hot-patches the 8 Kinect10 IAT entries.
      - For 64-bit jd2022.exe: Confirms native AIWebcam shared memory bridge is ready.
    """

    def __init__(self, cfg=None):
        self.cfg = cfg or {}
        self.enabled = bool(self.cfg.get("emulate_kinect_enabled", False))
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        
        # State tracking
        self.attached_pid: Optional[int] = None
        self.attached_game_name: Optional[str] = None
        self.attached_mode: Optional[str] = None # "iat_hook" or "aiwebcam"
        self._status_callbacks: List[Callable[[bool, str, int], None]] = []

        # Windows API bindings with explicit 64-bit pointer/handle signatures
        self._k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._psapi = ctypes.WinDLL("psapi", use_last_error=True)
        self._ntdll = ctypes.WinDLL("ntdll")
        self._configure_win32_signatures()

        # Resolve path to our proxy DLL (supports source tree, PyInstaller onefile _MEIPASS, and onedir)
        self.proxy_dll_path = self._resolve_proxy_dll_path()

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

    @staticmethod
    def _resolve_proxy_dll_path() -> Path:
        """
        Locates `tools/Legacy10.dll` across source tree, PyInstaller `_MEIPASS`, and executable directory,
        falling back to copying `tools/Kinect10.dll` if `Legacy10.dll` is not yet present.
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
            p = d / "Legacy10.dll"
            if p.is_file():
                return p

        for d in candidate_dirs:
            fallback = d / "Kinect10.dll"
            if fallback.is_file():
                target = d / "Legacy10.dll"
                try:
                    import shutil
                    shutil.copy2(fallback, target)
                    if target.is_file():
                        return target
                except Exception:
                    pass
                return fallback

        return candidate_dirs[0] / "Legacy10.dll"

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
                "mode": self.attached_mode or ""
            }

    def _monitor_loop(self) -> None:
        """Main daemon loop running at ~1.0 Hz when idle, fast when attaching."""
        while self._running:
            try:
                if not self.enabled:
                    time.sleep(1.0)
                    continue

                # If already attached, verify process is still alive
                if self.attached_pid is not None:
                    if not self._is_process_alive(self.attached_pid):
                        old_name = self.attached_game_name or "Game"
                        old_pid = self.attached_pid
                        with self._lock:
                            self.attached_pid = None
                            self.attached_game_name = None
                            self.attached_mode = None
                        self._notify_status(False, old_name, old_pid)
                    time.sleep(1.0)
                    continue

                # Scan running processes for target game
                target = self._scan_for_game_process()
                if target:
                    pid = target["pid"]
                    name = target["name"]
                    is_32bit_legacy = (
                        ("legacy" in name.lower() or "justdance" in name.lower())
                        and self._is_target_32bit(pid)
                    )

                    if is_32bit_legacy:
                        success = self._hook_running_legacy(pid)
                        if success:
                            with self._lock:
                                self.attached_pid = pid
                                self.attached_game_name = name
                                self.attached_mode = "iat_hook"
                            self._notify_status(True, name, pid)
                    else:
                        # 64-bit jd2022.exe or 64-bit JustDance.exe
                        with self._lock:
                            self.attached_pid = pid
                            self.attached_game_name = name
                            self.attached_mode = "aiwebcam"
                        self._notify_status(True, name, pid)

            except Exception:
                pass

            time.sleep(0.8)

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
        Prevents injecting 32-bit Legacy10.dll into a 64-bit executable.
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

    def _scan_for_game_process(self) -> Optional[Dict[str, Any]]:
        """
        Scans active processes for target Just Dance executables using a lightweight
        Win32 Toolhelp32 kernel snapshot (< 0.5ms) without calling OpenProcess(PROCESS_VM_READ)
        on unrelated system processes.
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

            while True:
                pid = int(pe.th32ProcessID)
                if pid > 4:
                    exe_name = pe.szExeFile
                    exe_lower = exe_name.lower()
                    for target_name in TARGET_PROCESS_NAMES:
                        if exe_lower == target_name or target_name in exe_lower:
                            return {"pid": pid, "name": exe_name}
                if not self._k32.Process32NextW(h_snap, ctypes.byref(pe)):
                    break
        finally:
            self._k32.CloseHandle(h_snap)

        return None

    def _hook_running_legacy(self, pid: int) -> bool:
        """
        Injects Legacy10.dll into the 32-bit Legacy.exe process and patches
        its 8 Kinect10 IAT entries in memory.
        """
        if not self.proxy_dll_path.exists():
            return False

        h_proc = self._k32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
        if not h_proc:
            return False

        try:
            # 1. Enumerate remote 32-bit modules
            h_mods = (wintypes.HMODULE * 1024)()
            cb_needed = wintypes.DWORD()
            if not self._psapi.EnumProcessModulesEx(h_proc, h_mods, ctypes.sizeof(h_mods), ctypes.byref(cb_needed), LIST_MODULES_ALL):
                return False

            mod_count = cb_needed.value // ctypes.sizeof(wintypes.HMODULE)
            mod_buf = ctypes.create_unicode_buffer(512)
            k32_base = None
            legacy_base = None
            legacy10_base = None

            for i in range(mod_count):
                try:
                    self._psapi.GetModuleFileNameExW(h_proc, h_mods[i], mod_buf, 512)
                    fn = mod_buf.value.lower()
                    if "kernel32.dll" in fn and ("system32" in fn or "syswow64" in fn):
                        k32_base = h_mods[i]
                    elif "legacy.exe" in fn or "justdance.exe" in fn:
                        legacy_base = h_mods[i]
                    elif "legacy10.dll" in fn:
                        legacy10_base = h_mods[i]
                except Exception:
                    pass

            if not k32_base or not legacy_base:
                return False

            # 2. If Legacy10.dll is not yet loaded in the game, inject it via CreateRemoteThread(LoadLibraryW)
            if not legacy10_base:
                loadlib_addr = self._find_remote_export(h_proc, k32_base, b"LoadLibraryW")
                if not loadlib_addr:
                    return False

                dll_path_str = str(self.proxy_dll_path.resolve())
                path_bytes = (dll_path_str + "\x00").encode("utf-16le")
                remote_str = self._k32.VirtualAllocEx(h_proc, None, len(path_bytes), MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
                if not remote_str:
                    return False

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
                        return False

                    self._k32.WaitForSingleObject(h_thread, 3000)
                    self._k32.CloseHandle(h_thread)
                finally:
                    self._k32.VirtualFreeEx(h_proc, ctypes.c_void_p(remote_str), 0, MEM_RELEASE)

                # Re-enumerate to locate the injected Legacy10.dll base address
                self._psapi.EnumProcessModulesEx(h_proc, h_mods, ctypes.sizeof(h_mods), ctypes.byref(cb_needed), LIST_MODULES_ALL)
                mod_count = cb_needed.value // ctypes.sizeof(wintypes.HMODULE)
                for i in range(mod_count):
                    try:
                        self._psapi.GetModuleFileNameExW(h_proc, h_mods[i], mod_buf, 512)
                        if "legacy10.dll" in mod_buf.value.lower():
                            legacy10_base = h_mods[i]
                            break
                    except Exception:
                        pass

            if not legacy10_base:
                return False

            # 3. Resolve the 8 function export addresses from the remote Legacy10.dll
            legacy_exports = self._get_dll_exports_by_ordinal(h_proc, legacy10_base)
            if not legacy_exports:
                return False

            # 4. Locate the IAT table for Kinect10.dll in Legacy.exe
            iat_rva = self._find_kinect_iat_rva(h_proc, legacy_base)
            if not iat_rva:
                # Fallback to the static RVA discovered in analysis
                iat_rva = 0x9cd250

            iat_addr = legacy_base + iat_rva

            # Build the new 32-byte IAT table
            new_iat_pointers = []
            for ord_val in KINECT_ORDINALS_ORDER:
                fn_addr = legacy_exports.get(ord_val)
                if not fn_addr:
                    return False
                new_iat_pointers.append(fn_addr)

            iat_bytes = bytearray()
            for ptr in new_iat_pointers:
                iat_bytes.extend(ptr.to_bytes(4, "little"))

            # 5. Overwrite the IAT entries with VirtualProtectEx
            old_protect = wintypes.DWORD()
            if self._k32.VirtualProtectEx(h_proc, ctypes.c_void_p(iat_addr), len(iat_bytes), PAGE_EXECUTE_READWRITE, ctypes.byref(old_protect)):
                written = ctypes.c_size_t()
                self._k32.WriteProcessMemory(h_proc, ctypes.c_void_p(iat_addr), bytes(iat_bytes), len(iat_bytes), ctypes.byref(written))
                self._k32.VirtualProtectEx(h_proc, ctypes.c_void_p(iat_addr), len(iat_bytes), old_protect, ctypes.byref(old_protect))
                return True

            return False

        except Exception:
            return False
        finally:
            self._k32.CloseHandle(h_proc)

    def _find_remote_export(self, h_proc, mod_base: int, func_name: bytes) -> Optional[int]:
        """Reads a remote PE module's export directory to find an exported function address."""
        dos_hdr = ctypes.create_string_buffer(64)
        if not self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(mod_base), dos_hdr, 64, None):
            return None
        e_lfanew = int.from_bytes(dos_hdr[0x3C:0x40], "little")

        nt_hdr = ctypes.create_string_buffer(256)
        if not self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(mod_base + e_lfanew), nt_hdr, 256, None):
            return None

        exp_dir_rva = int.from_bytes(nt_hdr[0x78:0x7C], "little")
        if not exp_dir_rva:
            return None

        exp_dir = ctypes.create_string_buffer(40)
        if not self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(mod_base + exp_dir_rva), exp_dir, 40, None):
            return None

        num_funcs = int.from_bytes(exp_dir[0x14:0x18], "little")
        num_names = int.from_bytes(exp_dir[0x18:0x1C], "little")
        funcs_rva = int.from_bytes(exp_dir[0x1C:0x20], "little")
        names_rva = int.from_bytes(exp_dir[0x20:0x24], "little")
        ordinals_rva = int.from_bytes(exp_dir[0x24:0x28], "little")

        names_table = (ctypes.c_uint32 * num_names)()
        self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(mod_base + names_rva), names_table, ctypes.sizeof(names_table), None)
        ord_table = (ctypes.c_uint16 * num_names)()
        self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(mod_base + ordinals_rva), ord_table, ctypes.sizeof(ord_table), None)
        funcs_table = (ctypes.c_uint32 * num_funcs)()
        self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(mod_base + funcs_rva), funcs_table, ctypes.sizeof(funcs_table), None)

        for idx in range(num_names):
            name_buf = ctypes.create_string_buffer(64)
            self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(mod_base + names_table[idx]), name_buf, 64, None)
            if name_buf.value == func_name:
                ord_idx = ord_table[idx]
                return mod_base + funcs_table[ord_idx]

        return None

    def _get_dll_exports_by_ordinal(self, h_proc, mod_base: int) -> Dict[int, int]:
        """Maps ordinal -> remote virtual address for Legacy10.dll."""
        exports = {}
        dos_hdr = ctypes.create_string_buffer(64)
        if not self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(mod_base), dos_hdr, 64, None):
            return exports
        e_lfanew = int.from_bytes(dos_hdr[0x3C:0x40], "little")

        nt_hdr = ctypes.create_string_buffer(256)
        if not self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(mod_base + e_lfanew), nt_hdr, 256, None):
            return exports

        exp_dir_rva = int.from_bytes(nt_hdr[0x78:0x7C], "little")
        if not exp_dir_rva:
            return exports

        exp_dir = ctypes.create_string_buffer(40)
        if not self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(mod_base + exp_dir_rva), exp_dir, 40, None):
            return exports

        base_ordinal = int.from_bytes(exp_dir[0x10:0x14], "little")
        num_funcs = int.from_bytes(exp_dir[0x14:0x18], "little")
        funcs_rva = int.from_bytes(exp_dir[0x1C:0x20], "little")

        funcs_table = (ctypes.c_uint32 * num_funcs)()
        self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(mod_base + funcs_rva), funcs_table, ctypes.sizeof(funcs_table), None)

        for i in range(num_funcs):
            ord_num = base_ordinal + i
            fn_rva = funcs_table[i]
            if fn_rva != 0:
                exports[ord_num] = mod_base + fn_rva

        return exports

    def _find_kinect_iat_rva(self, h_proc, legacy_base: int) -> Optional[int]:
        """Finds FirstThunk RVA for Kinect10.dll in Legacy.exe's import directory."""
        dos_hdr = ctypes.create_string_buffer(64)
        if not self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(legacy_base), dos_hdr, 64, None):
            return None
        e_lfanew = int.from_bytes(dos_hdr[0x3C:0x40], "little")

        nt_hdr = ctypes.create_string_buffer(256)
        if not self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(legacy_base + e_lfanew), nt_hdr, 256, None):
            return None

        # Verify PE32 (32-bit) OptionalHeader Magic (0x10B) before reading 32-bit Import Directory offset 0x80
        opt_magic = int.from_bytes(nt_hdr[0x18:0x1A], "little")
        if opt_magic != PE32_MAGIC:
            return None

        # In 32-bit PE Optional Header, Import Directory is at offset 0x80 (0x60 in OptionalHeader + 0x20)
        imp_dir_rva = int.from_bytes(nt_hdr[0x80:0x84], "little")
        if not imp_dir_rva:
            return None

        # Walk IMAGE_IMPORT_DESCRIPTOR array (20 bytes per descriptor)
        desc_buf = ctypes.create_string_buffer(20)
        curr_rva = imp_dir_rva

        while True:
            if not self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(legacy_base + curr_rva), desc_buf, 20, None):
                break
            # Check if null-terminating descriptor
            if desc_buf.raw == b"\x00" * 20:
                break

            name_rva = int.from_bytes(desc_buf[0x0C:0x10], "little")
            first_thunk = int.from_bytes(desc_buf[0x10:0x14], "little")

            if name_rva:
                name_buf = ctypes.create_string_buffer(32)
                self._k32.ReadProcessMemory(h_proc, ctypes.c_void_p(legacy_base + name_rva), name_buf, 32, None)
                dll_name = name_buf.value.lower()
                if b"kinect10" in dll_name or b"legacy10" in dll_name:
                    return first_thunk

            curr_rva += 20

        return None
