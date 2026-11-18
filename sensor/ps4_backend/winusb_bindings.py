"""
Low-level ctypes bindings for Windows native WinUSB (winusb.dll), Configuration Manager
(cfgmgr32.dll), and Kernel32 Overlapped I/O APIs.
"""
import ctypes
from ctypes import wintypes
import os
from typing import Optional
import uuid

from .constants import (
    VID_OMNIVISION,
    PID_BOOTLOADER,
    PID_STREAM_FINAL,
    PID_STREAM_LEGACY,
    PS4_DEVICE_INTERFACE_GUID,
    USB_DEVICE_INTERFACE_GUID,
)

# Win32 Constants
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

ERROR_IO_PENDING = 997
WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102

CM_GETIDLIST_FILTER_PRESENT = 0x00000100
CM_GET_DEVICE_INTERFACE_LIST_PRESENT = 0x00000000

USB_DEVICE_DESCRIPTOR_TYPE = 0x01
USB_CONFIGURATION_DESCRIPTOR_TYPE = 0x02
USB_STRING_DESCRIPTOR_TYPE = 0x03
USB_INTERFACE_DESCRIPTOR_TYPE = 0x04
USB_ENDPOINT_DESCRIPTOR_TYPE = 0x05

# Pipe Policy Constants
PIPE_TRANSFER_TIMEOUT = 0x03
RAW_IO = 0x07


# =============================================================================
# Ctypes Structures
# =============================================================================
class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_uint8 * 8),
    ]

    @classmethod
    def from_string(cls, guid_str: str) -> "GUID":
        u = uuid.UUID(guid_str)
        return cls.from_buffer_copy(u.bytes_le)


class WINUSB_SETUP_PACKET(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("RequestType", ctypes.c_uint8),
        ("Request", ctypes.c_uint8),
        ("Value", ctypes.c_uint16),
        ("Index", ctypes.c_uint16),
        ("Length", ctypes.c_uint16),
    ]


class USB_INTERFACE_DESCRIPTOR(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("bLength", ctypes.c_uint8),
        ("bDescriptorType", ctypes.c_uint8),
        ("bInterfaceNumber", ctypes.c_uint8),
        ("bAlternateSetting", ctypes.c_uint8),
        ("bNumEndpoints", ctypes.c_uint8),
        ("bInterfaceClass", ctypes.c_uint8),
        ("bInterfaceSubClass", ctypes.c_uint8),
        ("bInterfaceProtocol", ctypes.c_uint8),
        ("iInterface", ctypes.c_uint8),
    ]


class USB_DEVICE_DESCRIPTOR(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("bLength", ctypes.c_uint8),
        ("bDescriptorType", ctypes.c_uint8),
        ("bcdUSB", ctypes.c_uint16),
        ("bDeviceClass", ctypes.c_uint8),
        ("bDeviceSubClass", ctypes.c_uint8),
        ("bDeviceProtocol", ctypes.c_uint8),
        ("bMaxPacketSize0", ctypes.c_uint8),
        ("idVendor", ctypes.c_uint16),
        ("idProduct", ctypes.c_uint16),
        ("bcdDevice", ctypes.c_uint16),
        ("iManufacturer", ctypes.c_uint8),
        ("iProduct", ctypes.c_uint8),
        ("iSerialNumber", ctypes.c_uint8),
        ("bNumConfigurations", ctypes.c_uint8),
    ]


class WINUSB_PIPE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PipeType", ctypes.c_int),
        ("PipeId", ctypes.c_uint8),
        ("MaximumPacketSize", ctypes.c_uint16),
        ("Interval", ctypes.c_uint8),
    ]


class WINUSB_PIPE_INFORMATION_EX(ctypes.Structure):
    _fields_ = [
        ("PipeType", ctypes.c_int),
        ("PipeId", ctypes.c_uint8),
        ("MaximumPacketSize", ctypes.c_uint16),
        ("Interval", ctypes.c_uint8),
        ("MaximumBytesPerInterval", wintypes.ULONG),
    ]


class USBD_ISO_PACKET_DESCRIPTOR(ctypes.Structure):
    _fields_ = [
        ("Offset", wintypes.ULONG),
        ("Length", wintypes.ULONG),
        ("Status", wintypes.LONG),
    ]


class OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_size_t),
        ("InternalHigh", ctypes.c_size_t),
        ("Offset", wintypes.DWORD),
        ("OffsetHigh", wintypes.DWORD),
        ("hEvent", wintypes.HANDLE),
    ]


# =============================================================================
# DLL Loaders & Function Signatures
# =============================================================================
class WinUsbApi:
    """Thread-safe wrapper around Windows kernel32, cfgmgr32, and winusb DLLs."""

    def __init__(self):
        self.available = (os.name == "nt")
        if not self.available:
            self.kernel32 = None
            self.winusb = None
            self.cfgmgr32 = None
            return

        self.kernel32 = ctypes.windll.kernel32
        self.cfgmgr32 = ctypes.windll.cfgmgr32
        self.winusb = ctypes.windll.winusb
        self._setup_signatures()

    def _setup_signatures(self):
        k32 = self.kernel32
        k32.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        k32.CreateFileW.restype = wintypes.HANDLE

        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        k32.CloseHandle.restype = wintypes.BOOL

        k32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        k32.CreateEventW.restype = wintypes.HANDLE

        k32.ResetEvent.argtypes = [wintypes.HANDLE]
        k32.ResetEvent.restype = wintypes.BOOL

        k32.SetEvent.argtypes = [wintypes.HANDLE]
        k32.SetEvent.restype = wintypes.BOOL

        k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k32.WaitForSingleObject.restype = wintypes.DWORD

        k32.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
        k32.CancelIoEx.restype = wintypes.BOOL

        w = self.winusb
        w.WinUsb_Initialize.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.HANDLE)]
        w.WinUsb_Initialize.restype = wintypes.BOOL

        w.WinUsb_Free.argtypes = [wintypes.HANDLE]
        w.WinUsb_Free.restype = wintypes.BOOL

        w.WinUsb_GetAssociatedInterface.argtypes = [
            wintypes.HANDLE,
            ctypes.c_uint8,
            ctypes.POINTER(wintypes.HANDLE),
        ]
        w.WinUsb_GetAssociatedInterface.restype = wintypes.BOOL

        w.WinUsb_GetDescriptor.argtypes = [
            wintypes.HANDLE,
            ctypes.c_uint8,
            ctypes.c_uint8,
            wintypes.USHORT,
            ctypes.c_void_p,
            wintypes.ULONG,
            ctypes.POINTER(wintypes.ULONG),
        ]
        w.WinUsb_GetDescriptor.restype = wintypes.BOOL

        w.WinUsb_QueryInterfaceSettings.argtypes = [
            wintypes.HANDLE,
            ctypes.c_uint8,
            ctypes.POINTER(USB_INTERFACE_DESCRIPTOR),
        ]
        w.WinUsb_QueryInterfaceSettings.restype = wintypes.BOOL

        w.WinUsb_SetCurrentAlternateSetting.argtypes = [wintypes.HANDLE, ctypes.c_uint8]
        w.WinUsb_SetCurrentAlternateSetting.restype = wintypes.BOOL

        w.WinUsb_QueryPipe.argtypes = [
            wintypes.HANDLE,
            ctypes.c_uint8,
            ctypes.c_uint8,
            ctypes.POINTER(WINUSB_PIPE_INFORMATION),
        ]
        w.WinUsb_QueryPipe.restype = wintypes.BOOL

        w.WinUsb_QueryPipeEx.argtypes = [
            wintypes.HANDLE,
            ctypes.c_uint8,
            ctypes.c_uint8,
            ctypes.POINTER(WINUSB_PIPE_INFORMATION_EX),
        ]
        w.WinUsb_QueryPipeEx.restype = wintypes.BOOL

        w.WinUsb_SetPipePolicy.argtypes = [
            wintypes.HANDLE,
            ctypes.c_uint8,
            wintypes.ULONG,
            wintypes.ULONG,
            ctypes.c_void_p,
        ]
        w.WinUsb_SetPipePolicy.restype = wintypes.BOOL

        w.WinUsb_ResetPipe.argtypes = [wintypes.HANDLE, ctypes.c_uint8]
        w.WinUsb_ResetPipe.restype = wintypes.BOOL

        w.WinUsb_ControlTransfer.argtypes = [
            wintypes.HANDLE,
            WINUSB_SETUP_PACKET,
            ctypes.c_void_p,
            wintypes.ULONG,
            ctypes.POINTER(wintypes.ULONG),
            ctypes.c_void_p,
        ]
        w.WinUsb_ControlTransfer.restype = wintypes.BOOL

        w.WinUsb_RegisterIsochBuffer.argtypes = [
            wintypes.HANDLE,
            ctypes.c_uint8,
            ctypes.c_void_p,
            wintypes.ULONG,
            ctypes.POINTER(wintypes.HANDLE),
        ]
        w.WinUsb_RegisterIsochBuffer.restype = wintypes.BOOL

        w.WinUsb_UnregisterIsochBuffer.argtypes = [wintypes.HANDLE]
        w.WinUsb_UnregisterIsochBuffer.restype = wintypes.BOOL

        w.WinUsb_ReadIsochPipeAsap.argtypes = [
            wintypes.HANDLE,
            wintypes.ULONG,
            wintypes.ULONG,
            wintypes.BOOL,
            wintypes.ULONG,
            ctypes.POINTER(USBD_ISO_PACKET_DESCRIPTOR),
            ctypes.POINTER(OVERLAPPED),
        ]
        w.WinUsb_ReadIsochPipeAsap.restype = wintypes.BOOL

        w.WinUsb_GetOverlappedResult.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(OVERLAPPED),
            ctypes.POINTER(wintypes.ULONG),
            wintypes.BOOL,
        ]
        w.WinUsb_GetOverlappedResult.restype = wintypes.BOOL


_WINUSB_API_INSTANCE: Optional[WinUsbApi] = None


def get_winusb_api() -> WinUsbApi:
    global _WINUSB_API_INSTANCE
    if _WINUSB_API_INSTANCE is None:
        _WINUSB_API_INSTANCE = WinUsbApi()
    return _WINUSB_API_INSTANCE


# =============================================================================
# Device Interface & PnP Enumeration Helpers
# =============================================================================
def enumerate_present_device_ids() -> tuple[str, ...]:
    """
    Fast (< 2ms) query of all currently present USB device instance IDs via CfgMgr32.
    """
    api = get_winusb_api()
    if not api.available:
        return ()
    try:
        buf_len = wintypes.ULONG(0)
        res = api.cfgmgr32.CM_Get_Device_ID_List_SizeW(
            ctypes.byref(buf_len), None, CM_GETIDLIST_FILTER_PRESENT
        )
        if res != 0 or buf_len.value == 0:
            return ()

        buf = ctypes.create_unicode_buffer(buf_len.value)
        res2 = api.cfgmgr32.CM_Get_Device_ID_ListW(
            None, buf, buf_len.value, CM_GETIDLIST_FILTER_PRESENT
        )
        if res2 != 0:
            return ()

        raw = ctypes.string_at(ctypes.byref(buf), buf_len.value * 2)
        return tuple(
            d.upper()
            for d in raw.decode("utf-16-le", errors="ignore").split("\x00")
            if d and "USB\\" in d.upper()
        )
    except Exception:
        return ()


def enumerate_interface_paths(guid_str: str) -> list[str]:
    """
    Returns all active Windows device interface paths (\\?\\USB#...) for a given GUID.
    """
    api = get_winusb_api()
    if not api.available:
        return []
    try:
        g = GUID.from_string(guid_str)
        buf_len = wintypes.ULONG(0)
        res = api.cfgmgr32.CM_Get_Device_Interface_List_SizeW(
            ctypes.byref(buf_len),
            ctypes.byref(g),
            None,
            CM_GET_DEVICE_INTERFACE_LIST_PRESENT,
        )
        if res != 0 or buf_len.value <= 1:
            return []

        buf = ctypes.create_unicode_buffer(buf_len.value)
        res2 = api.cfgmgr32.CM_Get_Device_Interface_ListW(
            ctypes.byref(g),
            None,
            buf,
            buf_len.value,
            CM_GET_DEVICE_INTERFACE_LIST_PRESENT,
        )
        if res2 != 0:
            return []

        raw = ctypes.string_at(ctypes.byref(buf), buf_len.value * 2)
        return [
            p
            for p in raw.decode("utf-16-le", errors="ignore").split("\x00")
            if p.strip()
        ]
    except Exception:
        return []


def find_ps4_device_paths(target_pids: tuple[int, ...] = (PID_STREAM_FINAL, PID_STREAM_LEGACY, PID_BOOTLOADER)) -> list[tuple[int, str]]:
    """
    Searches for present PlayStation 4 Camera WinUSB device interface paths matching `target_pids`.
    Returns a list of (pid, device_interface_path) tuples ordered by `target_pids` priority.
    """
    all_paths: list[str] = []
    for guid_str in (PS4_DEVICE_INTERFACE_GUID, USB_DEVICE_INTERFACE_GUID):
        for p in enumerate_interface_paths(guid_str):
            if p not in all_paths:
                all_paths.append(p)

    results: list[tuple[int, str]] = []
    vid_token = f"VID_{VID_OMNIVISION:04X}".upper()

    for pid in target_pids:
        pid_token = f"PID_{pid:04X}".upper()
        for path in all_paths:
            up = path.upper()
            if vid_token in up and pid_token in up:
                results.append((pid, path))

    return results
