"""
Low-level Win32 ctypes helpers for Legacy PSCam Sensor camera discovery.
Isolates CfgMgr32 PnP snapshots (<3ms), SetupAPI camera enumeration (~3ms),
Toolhelp32 process scanning, and UAC ShellExecuteW elevation fallback.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Optional


def is_process_running_win32(name_substring: str) -> Optional[bool]:
    """
    Fast, zero-overhead process check via Win32 Toolhelp32 API.
    Returns True/False on Windows when snapshot succeeds, or None if unavailable.
    """
    if os.name != "nt":
        return None
    try:
        import ctypes
        import ctypes.wintypes

        TH32CS_SNAPPROCESS = 0x00000002

        class PROCESSENTRY32(ctypes.Structure):
            _fields_ = [
                ("dwSize", ctypes.wintypes.DWORD),
                ("cntUsage", ctypes.wintypes.DWORD),
                ("th32ProcessID", ctypes.wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", ctypes.wintypes.DWORD),
                ("cntThreads", ctypes.wintypes.DWORD),
                ("th32ParentProcessID", ctypes.wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", ctypes.wintypes.DWORD),
                ("szExeFile", ctypes.c_char * 260),
            ]

        h_snapshot = ctypes.windll.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if not h_snapshot or h_snapshot == -1:
            return None

        pe = PROCESSENTRY32()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32)
        needle = name_substring.lower()
        found = False
        try:
            if ctypes.windll.kernel32.Process32First(h_snapshot, ctypes.byref(pe)):
                while True:
                    proc_name = pe.szExeFile.decode("utf-8", errors="ignore").lower()
                    if needle in proc_name:
                        found = True
                        break
                    if not ctypes.windll.kernel32.Process32Next(h_snapshot, ctypes.byref(pe)):
                        break
        finally:
            ctypes.windll.kernel32.CloseHandle(h_snapshot)
        return found
    except Exception:
        return None


def get_hardware_snapshot() -> tuple[str, ...]:
    """
    Returns a sorted tuple of all currently present USB and Virtual Camera device instance IDs.
    Executes in < 3ms using Win32 CfgMgr32 without spawning processes or freezing the UI.
    """
    if os.name != "nt":
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
        devs = tuple(
            sorted(
                d.upper()
                for d in raw_bytes.decode("utf-16-le", errors="ignore").split("\x00")
                if d and ("USB\\" in d.upper() or "VCAM" in d.upper() or "CAMERA" in d.upper())
            )
        )
        return devs
    except Exception:
        return ()


def get_windows_camera_names_win32() -> list[str]:
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


def launch_elevated_win32(exe_path: Path) -> tuple[bool, str]:
    """Launches a Windows executable with UAC elevation via ShellExecuteW('runas')."""
    if os.name != "nt":
        return False, "Failed to initialize PlayStation 4 Camera driver."
    try:
        import ctypes

        ret = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            str(exe_path),
            None,
            str(exe_path.parent),
            1,
        )
        if ret > 32:
            time.sleep(1.0)
            return True, "PSCam4Win Tray started successfully!"
        if ret == 5:
            return False, "Launch cancelled: Administrator elevation was denied in Windows UAC."
        return False, f"Failed to start driver (ShellExecute code {ret})."
    except Exception as e:
        return False, f"Failed to start driver: {e}"
