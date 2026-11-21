"""
Legacy PSCam Sensor — DualShock 4 Bluetooth HID Driver (Native Windows HID)
Enables using the Sony DualShock 4 (CUH-ZCT1 / CUH-ZCT2) as a physical hand
controller for Just Dance PC.

Features:
  1. Zero external dependencies: Uses native Windows SetupAPI & hid.dll via ctypes.
  2. Automatic Bluetooth HID device enumeration (VID 0x054C, PID 0x05C4 / 0x09CC).
  3. Extended Report 0x11 handshake: Activates 6-axis IMU (gyro + accel) and lightbar.
  4. Hardware Accelerometer scaling: Translates raw 8192 LSB/1G into calibrated G-forces.
  5. High-frequency streaming: Up to 500+ Hz polling rate with low CPU overhead.
  6. Haptic rumble feedback and customizable RGB lightbar (default: PlayStation Blue).
  7. Live battery percentage and charging state detection.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field
import math
import struct
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple
import zlib

from sensor.virtual_phone import get_virtual_phone

# Windows API constants
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3

DIGCF_PRESENT = 0x00000002
DIGCF_DEVICEINTERFACE = 0x00000010

# Sony Vendor and Product IDs
SONY_VID = 0x054C
DS4_PID_V1 = 0x05C4
DS4_PID_V2 = 0x09CC

# Target Vendor and Product IDs for Official Sony DS4, Licensed Third-Party & Known Clone Chips
KNOWN_DS4_TARGETS: Dict[str, Tuple[str, ...]] = {
    "054c": ("05c4", "09cc", "0ba0", "0ce6", "0df2"),  # Official Sony DS4 v1, v2, USB Wireless Adapter, DualSense
    "0f0d": ("0055", "0066", "0084", "00a0", "00ee", "011c", "00c1"),  # Hori (Onyx, Mini, Fighting Commander)
    "146b": ("0601", "0602", "0603", "0604", "0605", "0606", "0609", "0d01", "0d02", "0d08"),  # Nacon (Revolution Pro, Compact)
    "1532": ("1000", "1004", "1007", "1008", "1009", "100a"),  # Razer Raiju series (Ultimate, Tournament)
    "9886": ("0025",),  # Astro Gaming C40 TR
    "2e95": ("7725", "9925"),  # Scuf Gaming (Vantage / Impact)
    "2c22": ("2000", "2300", "2500"),  # Qanba PS4 controllers
    "0738": ("5252", "8250", "8384"),  # Mad Catz PS4
    "2563": ("0575", "0555", "0523", "0588", "0590", "0526"),  # ShanWan clone chips commonly found in generic wireless DS4 replicas
    "0079": ("181b", "181c", "181d", "181e", "1843", "1844", "1845", "0006"),  # DragonRise / Generic wireless clones
    "057e": ("2009", "2006", "2007"),  # Switch Pro / Multi-protocol clones
    "11ff": ("3331", "0511"),  # Generic PC/PS4 Gamepads
    "0e8f": ("0003", "1008"),  # GreenAsia / PS4 clones
    "0810": ("0001", "0003"),  # Personal Communication Systems
    "12bd": ("d015", "c010"),  # Generic PS4 clones
    "20bc": ("5500", "5510"),  # Generic PS4 replicas
    "3288": ("0001", "0002"),  # Generic clone boards
}

# Blacklisted devices that should NEVER be treated as a DS4 clone (e.g. Xbox controllers without motion IMU)
BLACKLISTED_DEVICE_VENDORS = ("045e",)  # Microsoft Xbox controllers (no accelerometer)


def detect_controller_name(path: str) -> str:
    """Returns a friendly vendor / controller name based on device path identifiers."""
    p_lower = path.lower()
    if "1532" in p_lower:
        return "Razer Raiju (PS4)"
    elif "146b" in p_lower:
        return "Nacon Revolution (PS4)"
    elif "0f0d" in p_lower:
        return "Hori Controller (PS4)"
    elif "9886" in p_lower:
        return "Astro C40 TR (PS4)"
    elif "2e95" in p_lower:
        return "Scuf Controller (PS4)"
    elif "2c22" in p_lower:
        return "Qanba Controller (PS4)"
    elif "0738" in p_lower:
        return "Mad Catz (PS4)"
    elif "2563" in p_lower:
        return "ShanWan DS4 Clone"
    elif "0079" in p_lower:
        return "DragonRise DS4 Clone"
    elif "054c" in p_lower:
        return "Sony DualShock 4"
    return "Generic / Clone DS4"


def is_known_ds4_target(path: str) -> bool:
    """Returns True if the path matches an explicit VID/PID pair in KNOWN_DS4_TARGETS."""
    path_lower = path.lower()
    for vid, pids in KNOWN_DS4_TARGETS.items():
        if f"vid_{vid}" in path_lower or f"vid&{vid}" in path_lower or vid in path_lower:
            if any(f"pid_{pid}" in path_lower or f"pid&{pid}" in path_lower or pid in path_lower for pid in pids):
                return True
    return False


def is_compatible_ds4_path(path: str, permissive: bool = True) -> bool:
    """
    Checks if a Windows HID device path belongs to an official Sony DS4,
    a licensed third-party controller (Hori, Nacon, Razer, Astro, Scuf),
    a known clone chip (ShanWan, DragonRise), or matches permissive mode criteria.
    """
    path_lower = path.lower()

    if any(bvid in path_lower for bvid in BLACKLISTED_DEVICE_VENDORS):
        return False

    # 1. Check known vendor & product ID pairs
    if is_known_ds4_target(path_lower):
        return True

    # 2. Permissive mode: allow unknown USB/Bluetooth HID devices with VID/PID that are not blacklisted
    if permissive:
        if "kbd" in path_lower or "mou" in path_lower or "mouse" in path_lower or "keyboard" in path_lower:
            return False
        if ("vid" in path_lower and "pid" in path_lower) or "00001124" in path_lower or "bth" in path_lower or "bluetooth" in path_lower:
            return True

    return False

# Win32 Structures
class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_byte * 8),
    ]

class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("InterfaceClassGuid", GUID),
        ("Flags", wintypes.DWORD),
        ("Reserved", ctypes.POINTER(ctypes.c_ulong)),
    ]


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [
        ("Usage", wintypes.USHORT),
        ("UsagePage", wintypes.USHORT),
        ("InputReportByteLength", wintypes.USHORT),
        ("OutputReportByteLength", wintypes.USHORT),
        ("FeatureReportByteLength", wintypes.USHORT),
        ("Reserved", wintypes.USHORT * 17),
        ("NumberLinkCollectionNodes", wintypes.USHORT),
        ("NumberInputButtonCaps", wintypes.USHORT),
        ("NumberInputValueCaps", wintypes.USHORT),
        ("NumberInputDataIndices", wintypes.USHORT),
        ("NumberOutputButtonCaps", wintypes.USHORT),
        ("NumberOutputValueCaps", wintypes.USHORT),
        ("NumberOutputDataIndices", wintypes.USHORT),
        ("NumberFeatureButtonCaps", wintypes.USHORT),
        ("NumberFeatureValueCaps", wintypes.USHORT),
        ("NumberFeatureDataIndices", wintypes.USHORT),
    ]


def _init_win32_apis():
    setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
    hid = ctypes.WinDLL("hid", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    hid.HidD_GetPreparsedData.restype = wintypes.BOOL
    hid.HidD_GetPreparsedData.argtypes = [wintypes.HANDLE, ctypes.c_void_p]

    hid.HidP_GetCaps.restype = wintypes.LONG
    hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

    hid.HidD_FreePreparsedData.restype = wintypes.BOOL
    hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]

    hid.HidD_SetOutputReport.restype = wintypes.BOOL
    hid.HidD_SetOutputReport.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.ULONG,
    ]

    hid.HidD_GetFeature.restype = wintypes.BOOL
    hid.HidD_GetFeature.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.ULONG,
    ]

    hid.HidD_SetFeature.restype = wintypes.BOOL
    hid.HidD_SetFeature.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.ULONG,
    ]

    kernel32.CancelIoEx.restype = wintypes.BOOL
    kernel32.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p]

    setupapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE
    setupapi.SetupDiGetClassDevsW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        wintypes.HWND,
        wintypes.DWORD,
    ]

    setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
    setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]

    setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
    setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]

    setupapi.SetupDiDestroyDeviceInfoList.restype = wintypes.BOOL
    setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]

    return setupapi, hid, kernel32


_setupapi, _hid, _kernel32 = _init_win32_apis()


def _inspect_hid_caps(path: str) -> Optional[Tuple[int, int, int, int, int]]:
    """
    Returns (usage_page, usage, in_len, out_len, feat_len) for a Windows HID path,
    or None if inaccessible.
    """
    h = _kernel32.CreateFileW(
        path,
        GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        0,
        None,
    )
    if h == -1 or h == wintypes.HANDLE(-1).value:
        h = _kernel32.CreateFileW(
            path,
            GENERIC_READ,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None,
            OPEN_EXISTING,
            0,
            None,
        )
    if h == -1 or h == wintypes.HANDLE(-1).value:
        h = _kernel32.CreateFileW(
            path,
            0,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None,
            OPEN_EXISTING,
            0,
            None,
        )
    if h == -1 or h == wintypes.HANDLE(-1).value:
        return None

    info = None
    try:
        prep = ctypes.c_void_p()
        if _hid.HidD_GetPreparsedData(h, ctypes.byref(prep)):
            caps = HIDP_CAPS()
            if _hid.HidP_GetCaps(prep, ctypes.byref(caps)):
                info = (
                    int(caps.UsagePage),
                    int(caps.Usage),
                    int(caps.InputReportByteLength),
                    int(caps.OutputReportByteLength),
                    int(caps.FeatureReportByteLength),
                )
            _hid.HidD_FreePreparsedData(prep)
    except Exception:
        pass
    finally:
        _kernel32.CloseHandle(h)
    return info


def _score_hid_interface(usage_page: int, usage: int, in_len: int) -> int:
    """
    Scores an interface to ensure Gamepad / Joystick collections are preferred
    over vendor, audio, digitizer, keyboard, or mouse collections.
    """
    if usage_page != 0x01:  # Not Generic Desktop Controls (e.g. Consumer 0x0C, Touch 0x0D)
        return -1
    # Gamepad (Usage 0x05)
    if usage == 0x05:
        return 100 if in_len >= 64 else 85
    # Joystick (Usage 0x04) or Multi-axis controller (Usage 0x08)
    if usage in (0x04, 0x08):
        return 90 if in_len >= 64 else 75
    # Pointer / Generic desktop device
    if usage == 0x01:
        return 60 if in_len >= 8 else -1
    # Any other Generic Desktop with valid report length
    return 40 if in_len >= 8 else -1


def _probe_hid_gamepad_caps(path: str, is_known_target: bool = False) -> bool:
    """
    Verifies via HidD_GetPreparsedData / HidP_GetCaps whether a live Windows HID path
    is a valid Gamepad/Joystick interface.
    """
    info = _inspect_hid_caps(path)
    if not info:
        return False
    upage, usage, in_len, _, _ = info
    score = _score_hid_interface(upage, usage, in_len)
    if score > 0:
        return True
    if is_known_target and in_len >= 8 and upage == 0x01:
        return True
    return False


def find_ds4_devices(permissive: bool = True) -> List[str]:
    """
    Scans Windows PnP device interfaces for connected Sony DualShock 4 controllers,
    compatible third-party controllers (Nacon, Razer, Hori, Astro, Scuf) or clone chips.
    Returns a list of device interface paths prioritized with Gamepad interfaces first.
    """
    hid_guid = GUID()
    _hid.HidD_GetHidGuid(ctypes.byref(hid_guid))

    hdev = _setupapi.SetupDiGetClassDevsW(
        ctypes.byref(hid_guid),
        None,
        None,
        DIGCF_PRESENT | DIGCF_DEVICEINTERFACE,
    )
    if hdev == -1 or hdev == wintypes.HANDLE(-1).value:
        return []

    scored_paths: List[Tuple[int, str]] = []
    index = 0

    try:
        while True:
            idata = SP_DEVICE_INTERFACE_DATA()
            idata.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
            if not _setupapi.SetupDiEnumDeviceInterfaces(
                hdev, None, ctypes.byref(hid_guid), index, ctypes.byref(idata)
            ):
                break
            index += 1

            req_size = wintypes.DWORD()
            _setupapi.SetupDiGetDeviceInterfaceDetailW(
                hdev, ctypes.byref(idata), None, 0, ctypes.byref(req_size), None
            )

            class SP_DEVICE_INTERFACE_DETAIL_DATA(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("DevicePath", wintypes.WCHAR * (req_size.value // 2)),
                ]

            detail = SP_DEVICE_INTERFACE_DETAIL_DATA()
            detail.cbSize = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 5

            if _setupapi.SetupDiGetDeviceInterfaceDetailW(
                hdev, ctypes.byref(idata), ctypes.byref(detail), req_size, None, None
            ):
                path = detail.DevicePath
                if is_compatible_ds4_path(path, permissive=permissive):
                    known = is_known_ds4_target(path)
                    info = _inspect_hid_caps(path)
                    if info:
                        upage, usage, in_len, _, _ = info
                        score = _score_hid_interface(upage, usage, in_len)
                        if score <= 0 and known and in_len >= 8 and upage == 0x01:
                            score = 30
                        if score > 0:
                            # Prioritize known Sony / licensed hardware slightly
                            if known:
                                score += 5
                            scored_paths.append((score, path))
    finally:
        _setupapi.SetupDiDestroyDeviceInfoList(hdev)

    # Sort descending by score so actual Gamepad interfaces are tried first
    scored_paths.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in scored_paths]


@dataclass
class DS4State:
    connected: bool = False
    is_usb: bool = False
    battery_pct: int = 0
    is_charging: bool = False
    accel_g: Tuple[float, float, float] = (0.0, 1.0, 0.0)
    gyro: Tuple[int, int, int] = (0, 0, 0)
    buttons: Dict[str, bool] = field(default_factory=dict)
    sample_rate_hz: float = 0.0
    last_update_ts: float = 0.0
    imu_frozen: bool = False
    controller_name: str = "DualShock 4"


class DS4Controller:
    """
    Manages low-level Bluetooth and USB HID communication with a Sony DualShock 4 controller.
    Runs a dedicated background thread to read Report 0x01 (USB/BT) or Report 0x11 (BT Extended),
    unpacks motion sensors, and dispatches button events and G-force samples to the Just Dance
    Virtual Phone bridge.
    """

    DPAD_MAP = {
        0: {"up": True, "right": False, "down": False, "left": False},
        1: {"up": True, "right": True, "down": False, "left": False},
        2: {"up": False, "right": True, "down": False, "left": False},
        3: {"up": False, "right": True, "down": True, "left": False},
        4: {"up": False, "right": False, "down": True, "left": False},
        5: {"up": False, "right": False, "down": True, "left": True},
        6: {"up": False, "right": False, "down": False, "left": True},
        7: {"up": True, "right": False, "down": False, "left": True},
        8: {"up": False, "right": False, "down": False, "left": False},
    }

    def __init__(self) -> None:
        self._handle: Optional[wintypes.HANDLE] = None
        self._device_path: str = ""
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._input_len: int = 64
        self._output_len: int = 32
        self._feature_len: int = 64
        self.is_usb: bool = False

        # Configurable attributes
        self.hand: str = "right"
        self.sensitivity: float = 1.0
        self.permissive_mode: bool = True

        # State snapshot
        self.state = DS4State()

        # Lightbar color (R, G, B) — Default: PlayStation Blue
        self.led_r: int = 0
        self.led_g: int = 67
        self.led_b: int = 156

        # Previous button state for edge triggering
        self._prev_buttons: Dict[str, bool] = {}

        # Callbacks
        self.on_state_update: Optional[Callable[[DS4State], None]] = None
        self.on_button_press: Optional[Callable[[str], None]] = None

    @property
    def is_connected(self) -> bool:
        return self._handle is not None and self.state.connected

    def connect(self, device_path: Optional[str] = None, permissive: Optional[bool] = None) -> bool:
        """
        Connects to the DualShock 4 or compatible controller (via USB or Bluetooth),
        performs handshake, and starts high-frequency HID polling.
        """
        with self._lock:
            if self.is_connected:
                return True

            perm = self.permissive_mode if permissive is None else permissive
            paths = [device_path] if device_path else find_ds4_devices(permissive=perm)
            if not paths:
                self.state.connected = False
                self.state.is_usb = False
                self.is_usb = False
                return False

            chosen_handle = None
            chosen_path = None
            in_len = 64
            out_len = 32

            for cand_path in paths:
                # Attempt Read/Write access first
                h = _kernel32.CreateFileW(
                    cand_path,
                    GENERIC_READ | GENERIC_WRITE,
                    FILE_SHARE_READ | FILE_SHARE_WRITE,
                    None,
                    OPEN_EXISTING,
                    0,
                    None,
                )
                # Fallback to Read-only if access denied (common for certain Windows USB collections)
                if h == -1 or h == wintypes.HANDLE(-1).value:
                    h = _kernel32.CreateFileW(
                        cand_path,
                        GENERIC_READ,
                        FILE_SHARE_READ | FILE_SHARE_WRITE,
                        None,
                        OPEN_EXISTING,
                        0,
                        None,
                    )

                if h == -1 or h == wintypes.HANDLE(-1).value:
                    continue

                # Query report lengths via HID capabilities to ensure this is the Gamepad/Motion interface
                cand_in = 64
                cand_out = 32
                cand_feat = 64
                valid_interface = False
                try:
                    prep = ctypes.c_void_p()
                    if _hid.HidD_GetPreparsedData(h, ctypes.byref(prep)):
                        caps = HIDP_CAPS()
                        if _hid.HidP_GetCaps(prep, ctypes.byref(caps)):
                            cand_in = int(caps.InputReportByteLength)
                            cand_out = int(caps.OutputReportByteLength)
                            cand_feat = int(caps.FeatureReportByteLength)
                            usage_page = int(caps.UsagePage)
                            usage = int(caps.Usage)
                            is_gamepad = (usage_page == 0x01 and usage in (0x01, 0x04, 0x05, 0x08))
                            if cand_in >= 8 and (cand_in >= 64 or is_gamepad or is_known_ds4_target(cand_path)):
                                valid_interface = True
                        _hid.HidD_FreePreparsedData(prep)
                except Exception:
                    pass

                if valid_interface:
                    chosen_handle = h
                    chosen_path = cand_path
                    in_len = cand_in
                    out_len = cand_out
                    feat_len = cand_feat
                    break
                else:
                    _kernel32.CloseHandle(h)

            if chosen_handle is None:
                self.state.connected = False
                self.state.is_usb = False
                self.is_usb = False
                return False

            self._handle = chosen_handle
            self._device_path = chosen_path
            self._input_len = in_len
            self._output_len = out_len
            self._feature_len = max(feat_len, 64)
            self._stop_event.clear()

            # Detect USB vs Bluetooth connection & friendly controller name
            path_lower = chosen_path.lower()
            self.is_usb = (
                "bth" not in path_lower
                and "bluetooth" not in path_lower
                and "00001124" not in path_lower
            )
            self.state.is_usb = self.is_usb
            self.state.connected = True
            self.state.controller_name = detect_controller_name(chosen_path)
            self.state.imu_frozen = False

            try:
                from sensor.session_logger import get_session_logger
                get_session_logger().log_controller_state(
                    "ds4",
                    self.state.controller_name,
                    {
                        "connection": "USB" if self.is_usb else "Bluetooth",
                        "device_path": chosen_path,
                        "input_len": in_len,
                        "output_len": out_len,
                    },
                )
                get_session_logger().map_active_controller(
                    "ds4",
                    self.state.controller_name,
                    details=f"{'USB' if self.is_usb else 'Bluetooth'}, Hand: {self.hand}",
                )
            except Exception:
                pass

            # Trigger operational mode handshake (Feature Reports 0x02, 0x05, 0x04)
            # Crucial for clone DualShock 4 and official controllers to unlock Report 0x11
            # and activate the 6-axis IMU (gyroscope + accelerometer) on Bluetooth/USB.
            self._activate_operational_mode()

            # Perform handshake + welcome rumble buzz
            self._send_output_report(
                r=self.led_r,
                g=self.led_g,
                b=self.led_b,
                rumble_small=160,
                rumble_large=100,
            )

            # Start worker thread
            thread_name = "DS4-USB-Reader" if self.is_usb else "DS4-Bluetooth-Reader"
            self._thread = threading.Thread(
                target=self._worker_loop,
                name=thread_name,
                daemon=True,
            )
            self._thread.start()

            # Schedule quiet rumble stop after 180ms
            def _stop_initial_rumble():
                time.sleep(0.18)
                with self._lock:
                    if self._handle:
                        self._send_output_report(
                            r=self.led_r,
                            g=self.led_g,
                            b=self.led_b,
                            rumble_small=0,
                            rumble_large=0,
                        )

            threading.Thread(target=_stop_initial_rumble, daemon=True).start()
            return True

    def disconnect(self) -> None:
        """Safely shuts down HID polling, turns off the lightbar, and closes the handle."""
        self._stop_event.set()
        with self._lock:
            if self._handle:
                try:
                    # Turn off lightbar and rumble
                    self._send_output_report(r=0, g=0, b=0, rumble_small=0, rumble_large=0)
                except Exception:
                    pass
                try:
                    # Cancel any pending synchronous ReadFile calls
                    _kernel32.CancelIoEx(self._handle, None)
                except Exception:
                    pass
                try:
                    _kernel32.CloseHandle(self._handle)
                except Exception:
                    pass
                self._handle = None

            self.state.connected = False
            self.state.is_usb = False
            self.state.sample_rate_hz = 0.0
            self.state.imu_frozen = False
            self.state.controller_name = "DualShock 4"
            self.is_usb = False

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.6)
            self._thread = None

    def set_lightbar(self, r: int, g: int, b: int) -> None:
        """Updates the lightbar RGB color on the controller."""
        self.led_r = max(0, min(255, int(r)))
        self.led_g = max(0, min(255, int(g)))
        self.led_b = max(0, min(255, int(b)))
        with self._lock:
            if self._handle:
                self._send_output_report(r=self.led_r, g=self.led_g, b=self.led_b)

    def trigger_rumble(self, small: int = 150, large: int = 120, duration_sec: float = 0.25) -> None:
        """Triggers a non-blocking haptic rumble vibration pulse."""
        def _rumble_task():
            with self._lock:
                if self._handle:
                    self._send_output_report(
                        r=self.led_r,
                        g=self.led_g,
                        b=self.led_b,
                        rumble_small=small,
                        rumble_large=large,
                    )
            time.sleep(max(0.05, float(duration_sec)))
            with self._lock:
                if self._handle:
                    self._send_output_report(
                        r=self.led_r,
                        g=self.led_g,
                        b=self.led_b,
                        rumble_small=0,
                        rumble_large=0,
                    )

        threading.Thread(target=_rumble_task, daemon=True).start()

    def _activate_operational_mode(self) -> None:
        """
        Sends Feature Reports 0x02 and 0x05 (and 0x04) via HidD_GetFeature / HidD_SetFeature.
        This is the standard Linux kernel / WebHID / DS4Windows handshake that commands
        the DualShock 4 (both official Sony and clones/replicas) to transition from
        power-saving basic mode (Report 0x01, no IMU) into full operational mode
        (Report 0x11, high-frequency 6-axis IMU gyro + accel).
        """
        if not self._handle:
            return

        feat_len = max(getattr(self, "_feature_len", 64), 64)

        # 1. Feature Report 0x02: Unlock full operational mode
        try:
            buf_feat2 = (ctypes.c_ubyte * feat_len)()
            buf_feat2[0] = 0x02
            _hid.HidD_GetFeature(self._handle, ctypes.byref(buf_feat2), feat_len)
            _hid.HidD_SetFeature(self._handle, ctypes.byref(buf_feat2), feat_len)
        except Exception:
            pass

        # 2. Feature Report 0x05: Query gyro/accel calibration
        try:
            buf_feat5 = (ctypes.c_ubyte * feat_len)()
            buf_feat5[0] = 0x05
            _hid.HidD_GetFeature(self._handle, ctypes.byref(buf_feat5), feat_len)
            _hid.HidD_SetFeature(self._handle, ctypes.byref(buf_feat5), feat_len)
        except Exception:
            pass

        # 3. Feature Report 0x04: Alternative handshake for certain clone chips
        try:
            buf_feat4 = (ctypes.c_ubyte * feat_len)()
            buf_feat4[0] = 0x04
            _hid.HidD_GetFeature(self._handle, ctypes.byref(buf_feat4), feat_len)
            _hid.HidD_SetFeature(self._handle, ctypes.byref(buf_feat4), feat_len)
        except Exception:
            pass

    def _send_output_report(
        self,
        r: int,
        g: int,
        b: int,
        rumble_small: int = 0,
        rumble_large: int = 0,
    ) -> bool:
        """Constructs and sends Output Report (Report 0x05 for USB/BT or Report 0x11 for BT Extended)."""
        if not self._handle:
            return False

        # DS4 over USB exclusively uses 32-byte Output Report 0x05.
        # Bluetooth DS4 uses either 32-byte Report 0x05 or 78-byte Report 0x11.
        use_report_05 = self.is_usb or (self._output_len == 32)

        if use_report_05:
            # 32-byte Output Report 0x05 (Standard USB and Windows Bluetooth DS4 driver)
            out_rep = bytearray(32)
            out_rep[0] = 0x05
            out_rep[1] = 0x07  # Enable rumble motors and RGB lightbar
            out_rep[4] = max(0, min(255, int(rumble_small)))
            out_rep[5] = max(0, min(255, int(rumble_large)))
            out_rep[6] = max(0, min(255, int(r)))
            out_rep[7] = max(0, min(255, int(g)))
            out_rep[8] = max(0, min(255, int(b)))

            c_buf = (ctypes.c_ubyte * 32)(*out_rep)
            written = wintypes.DWORD()
            res = _kernel32.WriteFile(
                self._handle, ctypes.byref(c_buf), 32, ctypes.byref(written), None
            )
            # Crucial for USB on Windows: USB DS4 has no interrupt OUT endpoint,
            # so WriteFile fails and HidD_SetOutputReport is required.
            if not res or written.value == 0:
                res = _hid.HidD_SetOutputReport(self._handle, ctypes.byref(c_buf), 32)
            return bool(res)
        else:
            # 78-byte Extended Output Report 0x11 with IEEE 802.3 CRC-32
            out_rep = bytearray(78)
            out_rep[0] = 0x11
            out_rep[1] = 0xC0  # Polling rate & streaming flags
            out_rep[2] = 0x20
            out_rep[3] = 0x07  # Enable rumble small/large and lightbar
            out_rep[6] = max(0, min(255, int(rumble_small)))
            out_rep[7] = max(0, min(255, int(rumble_large)))
            out_rep[8] = max(0, min(255, int(r)))
            out_rep[9] = max(0, min(255, int(g)))
            out_rep[10] = max(0, min(255, int(b)))

            crc = zlib.crc32(bytes([0xA2]) + bytes(out_rep[:74])) & 0xFFFFFFFF
            out_rep[74:78] = struct.pack("<I", crc)

            c_buf = (ctypes.c_ubyte * 78)(*out_rep)
            written = wintypes.DWORD()
            res = _kernel32.WriteFile(
                self._handle, ctypes.byref(c_buf), 78, ctypes.byref(written), None
            )
            if not res or written.value == 0:
                res = _hid.HidD_SetOutputReport(self._handle, ctypes.byref(c_buf), 78)

            # If 78-byte Output Report failed on Bluetooth (typical for clones),
            # fall back to 32-byte Output Report 0x05 which clones accept!
            if not res:
                out_rep_05 = bytearray(32)
                out_rep_05[0] = 0x05
                out_rep_05[1] = 0x07
                out_rep_05[4] = max(0, min(255, int(rumble_small)))
                out_rep_05[5] = max(0, min(255, int(rumble_large)))
                out_rep_05[6] = max(0, min(255, int(r)))
                out_rep_05[7] = max(0, min(255, int(g)))
                out_rep_05[8] = max(0, min(255, int(b)))
                c_buf_05 = (ctypes.c_ubyte * 32)(*out_rep_05)
                res = _hid.HidD_SetOutputReport(self._handle, ctypes.byref(c_buf_05), 32)

            return bool(res)

    def _worker_loop(self) -> None:
        """
        High-frequency background reader supporting Report 0x01, Report 0x11..0x19,
        Report 0x31, and clone reports with adaptive IMU offset & scale detection.
        """
        buf_len = max(64, self._input_len)
        buf = (ctypes.c_ubyte * buf_len)()
        bytes_read = wintypes.DWORD()

        vphone = get_virtual_phone()
        last_out_refresh = time.perf_counter()
        last_wake_poke = time.perf_counter()

        samples_count = 0
        samples_time_start = time.perf_counter()
        consecutive_zero_accel = 0

        # Dynamic IMU offset & LSB scale detector for clones
        detected_imu_offset: Optional[int] = None
        detected_accel_is_block_a: bool = False
        detected_scale_lsb: float = 8192.0

        self.state.connected = True
        self.state.is_usb = self.is_usb

        while not self._stop_event.is_set():
            res = _kernel32.ReadFile(
                self._handle, ctypes.byref(buf), buf_len, ctypes.byref(bytes_read), None
            )
            if not res or bytes_read.value == 0:
                # Device disconnected or error
                break

            data = bytes(buf[: bytes_read.value])
            if len(data) < 8:
                continue

            now = time.perf_counter()
            rep_id = data[0]

            # Determine button offsets and default motion offset based on report ID
            if rep_id == 0x01:
                # Standard USB / Bluetooth basic report
                dpad_byte = data[5] if len(data) > 5 else 0x08
                btn_byte1 = data[6] if len(data) > 6 else 0
                btn_byte2 = data[7] if len(data) > 7 else 0
                batt_byte = data[30] if len(data) > 30 else 0
                default_offset = 13
            elif rep_id in range(0x11, 0x20):
                # Extended Bluetooth reports (0x11 through 0x19)
                dpad_byte = data[7] if len(data) > 7 else 0x08
                btn_byte1 = data[8] if len(data) > 8 else 0
                btn_byte2 = data[9] if len(data) > 9 else 0
                batt_byte = data[32] if len(data) > 32 else 0
                default_offset = 15
            elif rep_id == 0x31:
                # DualSense / modern PS protocol
                dpad_byte = data[8] if len(data) > 8 else 0x08
                btn_byte1 = data[9] if len(data) > 9 else 0
                btn_byte2 = data[10] if len(data) > 10 else 0
                batt_byte = data[53] if len(data) > 53 else 0
                default_offset = 16
            elif len(data) >= 64:
                # Raw report without Report ID (data[0] is Stick X)
                dpad_byte = data[4] if len(data) > 4 else 0x08
                btn_byte1 = data[5] if len(data) > 5 else 0
                btn_byte2 = data[6] if len(data) > 6 else 0
                batt_byte = data[29] if len(data) > 29 else 0
                default_offset = 12
            else:
                # Truncated basic Bluetooth report (e.g. 9 or 10 bytes)
                dpad_byte = data[5] if len(data) > 5 else 0x08
                btn_byte1 = data[6] if len(data) > 6 else 0
                btn_byte2 = data[7] if len(data) > 7 else 0
                batt_byte = 0
                default_offset = -1

            dpad_val = dpad_byte & 0x0F
            dpad_dict = self.DPAD_MAP.get(dpad_val, self.DPAD_MAP[8])

            btn_square = bool(dpad_byte & 0x10)
            btn_cross = bool(dpad_byte & 0x20)
            btn_circle = bool(dpad_byte & 0x40)
            btn_triangle = bool(dpad_byte & 0x80)

            btn_l1 = bool(btn_byte1 & 0x01)
            btn_r1 = bool(btn_byte1 & 0x02)
            btn_l2 = bool(btn_byte1 & 0x04)
            btn_r2 = bool(btn_byte1 & 0x08)
            btn_share = bool(btn_byte1 & 0x10)
            btn_options = bool(btn_byte1 & 0x20)
            btn_l3 = bool(btn_byte1 & 0x40)
            btn_r3 = bool(btn_byte1 & 0x80)

            btn_ps = bool(btn_byte2 & 0x01)
            btn_touch = bool(btn_byte2 & 0x02)

            gyro_x = gyro_y = gyro_z = 0
            acc_x = acc_y = acc_z = 0
            active_offset = detected_imu_offset if detected_imu_offset is not None else default_offset

            if active_offset >= 0 and len(data) >= active_offset + 12:
                s1, s2, s3, s4, s5, s6 = struct.unpack_from("<hhhhhh", data, active_offset)
                if detected_accel_is_block_a:
                    acc_x, acc_y, acc_z = s1, s2, s3
                    gyro_x, gyro_y, gyro_z = s4, s5, s6
                else:
                    gyro_x, gyro_y, gyro_z = s1, s2, s3
                    acc_x, acc_y, acc_z = s4, s5, s6

            # Smart offset & LSB scale detector for clones
            raw_mag = math.sqrt(float(acc_x * acc_x + acc_y * acc_y + acc_z * acc_z))
            if raw_mag < 200.0:
                # Active offset gave near-zero readings; search candidate offsets
                candidate_offsets = [13, 15, 12, 14, 16, 17, 19, 21, 23]
                found_candidate = False
                for c_off in candidate_offsets:
                    if len(data) >= c_off + 12:
                        cs1, cs2, cs3, cs4, cs5, cs6 = struct.unpack_from("<hhhhhh", data, c_off)
                        mag_a = math.sqrt(float(cs1 * cs1 + cs2 * cs2 + cs3 * cs3))
                        mag_b = math.sqrt(float(cs4 * cs4 + cs5 * cs5 + cs6 * cs6))
                        # Check Block B first (standard Sony DS4 layout)
                        if 1500.0 <= mag_b <= 35000.0 and mag_b >= mag_a * 0.7:
                            detected_imu_offset = c_off
                            detected_accel_is_block_a = False
                            active_offset = c_off
                            gyro_x, gyro_y, gyro_z = cs1, cs2, cs3
                            acc_x, acc_y, acc_z = cs4, cs5, cs6
                            raw_mag = mag_b
                            found_candidate = True
                            target_mag = mag_b
                        # Check Block A (Clone InvenSense / ShanWan register layout)
                        elif 1500.0 <= mag_a <= 35000.0:
                            detected_imu_offset = c_off
                            detected_accel_is_block_a = True
                            active_offset = c_off
                            acc_x, acc_y, acc_z = cs1, cs2, cs3
                            gyro_x, gyro_y, gyro_z = cs4, cs5, cs6
                            raw_mag = mag_a
                            found_candidate = True
                            target_mag = mag_a

                        if found_candidate:
                            if target_mag > 12000.0:
                                detected_scale_lsb = 16384.0
                            elif target_mag > 6000.0:
                                detected_scale_lsb = 8192.0
                            elif target_mag > 3000.0:
                                detected_scale_lsb = 4096.0
                            else:
                                detected_scale_lsb = 2048.0
                            break

                if not found_candidate:
                    consecutive_zero_accel += 1
                else:
                    consecutive_zero_accel = 0
            else:
                consecutive_zero_accel = 0
                if detected_imu_offset is None and default_offset >= 0:
                    detected_imu_offset = default_offset
                if 1500.0 <= raw_mag <= 35000.0:
                    if raw_mag > 12000.0:
                        detected_scale_lsb = 16384.0
                    elif raw_mag > 6000.0:
                        detected_scale_lsb = 8192.0
                    elif raw_mag > 3000.0:
                        detected_scale_lsb = 4096.0
                    else:
                        detected_scale_lsb = 2048.0

            # If controller is streaming zeroes (sleeping IMU on BT clone),
            # trigger Feature Report 0x02 and output report poke every 0.8s to wake it up!
            if consecutive_zero_accel >= 15:
                if now - last_wake_poke > 0.8:
                    last_wake_poke = now
                    def _wake_poke():
                        self._activate_operational_mode()
                        self._send_output_report(self.led_r, self.led_g, self.led_b)
                    threading.Thread(target=_wake_poke, daemon=True).start()

            # Hardware scaling into calibrated G-forces
            raw_ax = (acc_x / detected_scale_lsb) * self.sensitivity
            raw_ay = (acc_y / detected_scale_lsb) * self.sensitivity
            raw_az = (acc_z / detected_scale_lsb) * self.sensitivity

            phone_ax = round(raw_ax, 4)
            phone_ay = round(raw_ay, 4)
            phone_az = round(raw_az, 4)

            accel_mag = math.sqrt(phone_ax * phone_ax + phone_ay * phone_ay + phone_az * phone_az)
            if accel_mag < 0.05:
                if consecutive_zero_accel >= 40 and not self.state.imu_frozen:
                    self.state.imu_frozen = True
            else:
                if self.state.imu_frozen:
                    self.state.imu_frozen = False

            # Feed to Virtual Phone scoring bridge if enabled
            if vphone.enabled:
                vphone.update_from_hardware_accel(phone_ax, phone_ay, phone_az)

            curr_buttons = {
                "cross": btn_cross,
                "circle": btn_circle,
                "square": btn_square,
                "triangle": btn_triangle,
                "dpad_up": dpad_dict["up"],
                "dpad_down": dpad_dict["down"],
                "dpad_left": dpad_dict["left"],
                "dpad_right": dpad_dict["right"],
                "l1": btn_l1,
                "r1": btn_r1,
                "l2": btn_l2,
                "r2": btn_r2,
                "share": btn_share,
                "options": btn_options,
                "ps": btn_ps,
                "touchpad": btn_touch,
            }

            # Edge triggering for button actions (send once per press)
            for btn_name, is_pressed in curr_buttons.items():
                was_pressed = self._prev_buttons.get(btn_name, False)
                if is_pressed and not was_pressed:
                    self._handle_button_press(btn_name, vphone)

            self._prev_buttons = curr_buttons

            # Battery level parsing
            batt_level = min(100, (batt_byte & 0x0F) * 10)
            is_charging = bool(batt_byte & 0x10)

            # Update sample rate counter
            samples_count += 1
            elapsed = now - samples_time_start
            if elapsed >= 0.5:
                self.state.sample_rate_hz = round(samples_count / elapsed, 1)
                samples_count = 0
                samples_time_start = now

            # Update state snapshot
            self.state.accel_g = (phone_ax, phone_ay, phone_az)
            self.state.gyro = (gyro_x, gyro_y, gyro_z)
            self.state.buttons = curr_buttons
            self.state.battery_pct = batt_level
            self.state.is_charging = is_charging
            self.state.last_update_ts = now

            if self.on_state_update is not None:
                self.on_state_update(self.state)

            # Periodic heartbeat (every 4s) to keep lightbar/rumble alive
            if now - last_out_refresh > 4.0:
                last_out_refresh = now
                self._send_output_report(self.led_r, self.led_g, self.led_b)

        self.state.connected = False
        self.state.is_usb = False
        self.state.sample_rate_hz = 0.0
        self.state.imu_frozen = False

    def _handle_button_press(self, btn: str, vphone) -> None:
        """
        Handles physical button presses on the DualShock 4:
          - L1: Previous Coach (cycle backward)
          - R1: Next Coach (cycle forward)
        Face buttons (Cross/X, Circle, Triangle, Square) remain intentionally unmapped
        to prevent accidental inputs/missclicks when holding or gripping the controller
        firmly during dance moves.
        """
        if self.on_button_press is not None:
            self.on_button_press(btn)

        try:
            from sensor.session_logger import get_session_logger
            coach_id = getattr(vphone, "current_coach_id", 0) if vphone else 0
            get_session_logger().log_controller_button(btn.upper(), coach_id=coach_id, action="press")
        except Exception:
            pass

        if not vphone or not vphone.enabled:
            return

        if btn == "l1":
            vphone.change_coach(-1)
            self.trigger_rumble(small=120, large=0, duration_sec=0.08)
        elif btn == "r1":
            vphone.change_coach(+1)
            self.trigger_rumble(small=120, large=0, duration_sec=0.08)


_global_ds4_controller: Optional[DS4Controller] = None


def get_ds4_controller() -> DS4Controller:
    """Returns the process-wide singleton DS4Controller instance."""
    global _global_ds4_controller
    if _global_ds4_controller is None:
        _global_ds4_controller = DS4Controller()
    return _global_ds4_controller
