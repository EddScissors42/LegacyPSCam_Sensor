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


def find_ds4_devices() -> List[str]:
    """
    Scans Windows PnP device interfaces for connected Sony DualShock 4 controllers.
    Returns a list of device interface paths.
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

    ds4_paths: List[str] = []
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
                path_lower = path.lower()
                # Check for Sony VID and DS4 PIDs
                if "054c" in path_lower and ("09cc" in path_lower or "05c4" in path_lower):
                    ds4_paths.append(path)
    finally:
        _setupapi.SetupDiDestroyDeviceInfoList(hdev)

    return ds4_paths


@dataclass
class DS4State:
    connected: bool = False
    battery_pct: int = 0
    is_charging: bool = False
    accel_g: Tuple[float, float, float] = (0.0, 1.0, 0.0)
    gyro: Tuple[int, int, int] = (0, 0, 0)
    buttons: Dict[str, bool] = field(default_factory=dict)
    sample_rate_hz: float = 0.0
    last_update_ts: float = 0.0


class DS4Controller:
    """
    Manages low-level Bluetooth HID communication with a Sony DualShock 4 controller.
    Runs a dedicated background thread to read Report 0x11, unpack motion sensors,
    and dispatch button events and G-force samples to the Just Dance Virtual Phone bridge.
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

        # Configurable attributes
        self.hand: str = "right"
        self.sensitivity: float = 1.0

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

    def connect(self, device_path: Optional[str] = None) -> bool:
        """
        Connects to the DualShock 4 controller, performs the 0x11 handshake,
        and starts high-frequency HID polling.
        """
        with self._lock:
            if self.is_connected:
                return True

            paths = [device_path] if device_path else find_ds4_devices()
            if not paths:
                self.state.connected = False
                return False

            target_path = paths[0]
            handle = _kernel32.CreateFileW(
                target_path,
                GENERIC_READ | GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                None,
                OPEN_EXISTING,
                0,
                None,
            )

            if handle == -1 or handle == wintypes.HANDLE(-1).value:
                self.state.connected = False
                return False

            self._handle = handle
            self._device_path = target_path
            self._stop_event.clear()

            # Query report lengths via HID capabilities
            self._input_len = 64
            self._output_len = 32
            try:
                prep = ctypes.c_void_p()
                if _hid.HidD_GetPreparsedData(handle, ctypes.byref(prep)):
                    caps = HIDP_CAPS()
                    if _hid.HidP_GetCaps(prep, ctypes.byref(caps)):
                        self._input_len = int(caps.InputReportByteLength)
                        self._output_len = int(caps.OutputReportByteLength)
                    _hid.HidD_FreePreparsedData(prep)
            except Exception:
                pass

            # Perform Extended Report handshake + Welcome rumble buzz
            self._send_output_report(
                r=self.led_r,
                g=self.led_g,
                b=self.led_b,
                rumble_small=160,
                rumble_large=100,
            )

            # Start worker thread
            self._thread = threading.Thread(
                target=self._worker_loop,
                name="DS4-Bluetooth-Reader",
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
                    _kernel32.CloseHandle(self._handle)
                except Exception:
                    pass
                self._handle = None

            self.state.connected = False
            self.state.sample_rate_hz = 0.0

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

    def _send_output_report(
        self,
        r: int,
        g: int,
        b: int,
        rumble_small: int = 0,
        rumble_large: int = 0,
    ) -> bool:
        """Constructs and writes Bluetooth Output Report (32-byte report 0x05 or 78-byte report 0x11)."""
        if not self._handle:
            return False

        if self._output_len == 32:
            # 32-byte Output Report 0x05 (Standard Windows Bluetooth DS4 driver)
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
            res = _kernel32.WriteFile(self._handle, ctypes.byref(c_buf), 32, ctypes.byref(written), None)
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
            res = _kernel32.WriteFile(self._handle, ctypes.byref(c_buf), 78, ctypes.byref(written), None)
            return bool(res)

    def _worker_loop(self) -> None:
        """High-frequency background reader supporting Report 0x01 and Report 0x11."""
        buf_len = max(64, self._input_len)
        buf = (ctypes.c_ubyte * buf_len)()
        bytes_read = wintypes.DWORD()

        vphone = get_virtual_phone()
        last_out_refresh = time.perf_counter()

        samples_count = 0
        samples_time_start = time.perf_counter()

        self.state.connected = True

        while not self._stop_event.is_set():
            res = _kernel32.ReadFile(
                self._handle, ctypes.byref(buf), buf_len, ctypes.byref(bytes_read), None
            )
            if not res:
                # Device disconnected or error
                break

            data = bytes(buf[: bytes_read.value])
            if len(data) < 30:
                continue

            now = time.perf_counter()
            rep_id = data[0]

            if rep_id == 0x01:
                # Standard Report 0x01 (Windows Bluetooth default / USB)
                gyro_x, gyro_y, gyro_z, acc_x, acc_y, acc_z = struct.unpack_from("<hhhhhh", data, 13)

                dpad_val = data[5] & 0x0F
                dpad_dict = self.DPAD_MAP.get(dpad_val, self.DPAD_MAP[8])

                btn_square = bool(data[5] & 0x10)
                btn_cross = bool(data[5] & 0x20)
                btn_circle = bool(data[5] & 0x40)
                btn_triangle = bool(data[5] & 0x80)

                btn_l1 = bool(data[6] & 0x01)
                btn_r1 = bool(data[6] & 0x02)
                btn_l2 = bool(data[6] & 0x04)
                btn_r2 = bool(data[6] & 0x08)
                btn_share = bool(data[6] & 0x10)
                btn_options = bool(data[6] & 0x20)
                btn_l3 = bool(data[6] & 0x40)
                btn_r3 = bool(data[6] & 0x80)

                btn_ps = bool(data[7] & 0x01)
                btn_touch = bool(data[7] & 0x02)

                batt_byte = data[30] if len(data) > 30 else 0
            elif rep_id == 0x11 and len(data) >= 33:
                # Extended Report 0x11
                gyro_x, gyro_y, gyro_z, acc_x, acc_y, acc_z = struct.unpack_from("<hhhhhh", data, 15)

                dpad_val = data[7] & 0x0F
                dpad_dict = self.DPAD_MAP.get(dpad_val, self.DPAD_MAP[8])

                btn_square = bool(data[7] & 0x10)
                btn_cross = bool(data[7] & 0x20)
                btn_circle = bool(data[7] & 0x40)
                btn_triangle = bool(data[7] & 0x80)

                btn_l1 = bool(data[8] & 0x01)
                btn_r1 = bool(data[8] & 0x02)
                btn_l2 = bool(data[8] & 0x04)
                btn_r2 = bool(data[8] & 0x08)
                btn_share = bool(data[8] & 0x10)
                btn_options = bool(data[8] & 0x20)
                btn_l3 = bool(data[8] & 0x40)
                btn_r3 = bool(data[8] & 0x80)

                btn_ps = bool(data[9] & 0x01)
                btn_touch = bool(data[9] & 0x02)

                batt_byte = data[32] if len(data) > 32 else 0
            else:
                continue

            # Hardware scaling: 8192 LSB = 1.0 G
            raw_ax = (acc_x / 8192.0) * self.sensitivity
            raw_ay = (acc_y / 8192.0) * self.sensitivity
            raw_az = (acc_z / 8192.0) * self.sensitivity

            # Just Dance Smartphone coordinate mapping:
            phone_ax = round(raw_ax, 4)
            phone_ay = round(raw_ay, 4)
            phone_az = round(raw_az, 4)

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
        self.state.sample_rate_hz = 0.0

    def _handle_button_press(self, btn: str, vphone) -> None:
        """
        Handles physical button presses on the DualShock 4:
          - L1: Previous Coach / NPC (cycle backward)
          - R1: Next Coach / NPC (cycle forward)
          - Cross (✕): Enter / Confirm (VALID)
        Other buttons remain unmapped to avoid accidental pauses/missclicks during dance.
        """
        if self.on_button_press is not None:
            self.on_button_press(btn)

        if not vphone or not vphone.enabled:
            return

        if btn == "l1":
            vphone.change_coach(-1)
            self.trigger_rumble(small=120, large=0, duration_sec=0.08)
        elif btn == "r1":
            vphone.change_coach(+1)
            self.trigger_rumble(small=120, large=0, duration_sec=0.08)
        elif btn == "cross":
            vphone.send_input("VALID")
            self.trigger_rumble(small=160, large=80, duration_sec=0.10)


_global_ds4_controller: Optional[DS4Controller] = None


def get_ds4_controller() -> DS4Controller:
    """Returns the process-wide singleton DS4Controller instance."""
    global _global_ds4_controller
    if _global_ds4_controller is None:
        _global_ds4_controller = DS4Controller()
    return _global_ds4_controller
