"""
PlayStation Move (ZCM2) Shared Memory IPC Bridge — Legacy PSCam Sensor

Bridges DualShock 4 6-axis IMU + buttons to `tools/LegacyMove.dll` (32-bit) and
`tools/LegacyMove_x64.dll` (64-bit) via a lockless 128-byte Windows shared memory
channel (`Local\\LegacyPSMoveState`, magic 'PSM1').

Binary Contract (128 bytes total, packed little-endian):
  Offsets 0..63   (Sensor -> Game, seqlock guarded by `seq`):
    - magic          (uint32): 0x314D5350 ('PSM1')
    - version        (uint32): 1
    - seq            (uint32): Seqlock counter (odd during write, even when consistent)
    - active         (uint32): 1 = virtual PS Move active/visible, 0 = hidden
    - timestamp_ms   (uint64): Unix timestamp in milliseconds
    - buttons_mask   (uint32): Packed ZCM2 button bits (bytes 1..4)
    - trigger_analog (uint8) : 0..255 analog trigger (R2)
    - battery_code   (uint8) : 0..5 bars, 0xEE charging, 0xEF full on charger
    - reserved0      (uint16): 0
    - accel_x/y/z    (int16x3): ZCM2 raw accel counts (4400 counts = 1.0 G)
    - gyro_x/y/z     (int16x3): ZCM2 raw gyro counts  (1015 counts = 1.0 rad/s)
    - reserved1      (20 B)  : zero padding to offset 64

  Offsets 64..127 (Game -> Sensor Feedback, written by LegacyMove.dll):
    - fb_seq         (uint32): Incremented on output report / connect / disconnect
    - game_connected (uint32): 1 = game opened streaming virtual handle, 0 = closed
    - led_r/g/b      (uint8x3): Requested PS Move sphere RGB color (0..255)
    - rumble         (uint8) : Requested rumble intensity (0..255)
    - game_pid       (uint32): Attached game process PID
    - input_reports  (uint32): Delivered 0x01 input report count
    - output_reports (uint32): Received 0x06/0x02 output report count
    - reserved2      (40 B)  : zero padding to 128 bytes
"""

from __future__ import annotations

import math
import mmap
import struct
import threading
import time
from typing import Any, Dict, Optional, Tuple

PSMOVE_SHARED_NAME = "Local\\LegacyPSMoveState"
PSMOVE_SHARED_SIZE = 128
PSMOVE_MAGIC = 0x314D5350  # 'PSM1'
PSMOVE_VERSION = 1

# Verified ZCM2 default scales inside Legacy.exe, Legacy Lab.exe, and LegacyLab_Offline.exe
PSMOVE_ACCEL_COUNTS_PER_G = 4400.0
PSMOVE_GYRO_COUNTS_PER_RAD_S = 1015.0

# Sony DualShock 4 BMI055 gyroscope sensitivity: 16.384 LSB/(deg/s) = 938.734 LSB/(rad/s)
DS4_GYRO_LSB_PER_RAD_S = 16.384 * (180.0 / math.pi)

# Packed ZCM2 button bitmask (bytes 1..4 little-endian)
PSMOVE_BTN_SELECT   = 0x00000001  # byte[1] bit 0
PSMOVE_BTN_START    = 0x00000008  # byte[1] bit 3
PSMOVE_BTN_TRIANGLE = 0x00001000  # byte[2] bit 4
PSMOVE_BTN_CIRCLE   = 0x00002000  # byte[2] bit 5
PSMOVE_BTN_CROSS    = 0x00004000  # byte[2] bit 6
PSMOVE_BTN_SQUARE   = 0x00008000  # byte[2] bit 7
PSMOVE_BTN_PS       = 0x00010000  # byte[3] bit 0
PSMOVE_BTN_MOVE     = 0x40000000  # byte[4] bit 6 (Move center button)
PSMOVE_BTN_TRIGGER  = 0x80000000  # byte[4] bit 7 (T trigger digital)

_SENSOR_FMT = "<IIIIQIBBHhhhhhh20s"
_FEEDBACK_FMT = "<IIBBBBIII40s"
_SEQ_OFFSET = 8
_FEEDBACK_OFFSET = 64

assert struct.calcsize(_SENSOR_FMT) == 64
assert struct.calcsize(_FEEDBACK_FMT) == 64
assert struct.calcsize(_SENSOR_FMT) + struct.calcsize(_FEEDBACK_FMT) == PSMOVE_SHARED_SIZE


def _clamp_i16(val: float) -> int:
    iv = int(round(val))
    if iv > 32767:
        return 32767
    if iv < -32767:
        return -32767
    return iv


def encode_psmove_battery(battery_pct: int, is_charging: bool = False) -> int:
    """Maps DS4 battery percentage & charging flag to PS Move ZCM2 byte[12] code."""
    pct = max(0, min(100, int(battery_pct)))
    if is_charging:
        return 0xEF if pct >= 95 else 0xEE
    return max(0, min(5, int(round(pct / 20.0))))


def buttons_dict_to_psmove_mask(
    buttons: Optional[Dict[str, bool]],
    trigger_analog: int = 0,
) -> int:
    """
    Maps DualShock 4 buttons 1:1 to PlayStation Move ZCM2 button bitmask:
      - R2 (or analog trigger >= 80) -> Trigger (T)
      - Cross / R1                   -> Move / Cross (Confirm)
      - Circle                       -> Circle (Back)
      - Square / Triangle            -> Square / Triangle
      - Options / Share              -> Start / Select
      - PS                           -> PS
    """
    b = buttons or {}
    mask = 0
    if b.get("share"):
        mask |= PSMOVE_BTN_SELECT
    if b.get("options"):
        mask |= PSMOVE_BTN_START
    if b.get("triangle"):
        mask |= PSMOVE_BTN_TRIANGLE
    if b.get("circle"):
        mask |= PSMOVE_BTN_CIRCLE
    if b.get("cross"):
        mask |= PSMOVE_BTN_CROSS | PSMOVE_BTN_MOVE
    if b.get("r1"):
        mask |= PSMOVE_BTN_MOVE
    if b.get("square"):
        mask |= PSMOVE_BTN_SQUARE
    if b.get("ps"):
        mask |= PSMOVE_BTN_PS
    if b.get("r2") or int(trigger_analog) >= 80:
        mask |= PSMOVE_BTN_TRIGGER
    return mask


def ds4_to_psmove_imu(
    accel_g: Tuple[float, float, float],
    gyro_rad_s: Tuple[float, float, float],
    grip: str = "vertical",
) -> Tuple[Tuple[int, int, int], Tuple[int, int, int]]:
    """
    Rotates calibrated DualShock 4 6-axis IMU readings (G and rad/s) into PlayStation Move
    ZCM2 hardware sensor coordinates and quantizes them to signed 16-bit counts
    (4400 counts/G for accelerometer, 1015 counts/(rad/s) for gyroscope).

    Default grip ('vertical' — thumbs-up vertical hold):
      - DS4 held vertically in hand (fingers resting along touchpad, thumb below right stick
        and face buttons; Light Bar pointing UP like the PS Move sphere, face/touchpad facing
        the dancer).
      - Exact proper 3D rotation (det = +1):
          move_x = +ds4_x
          move_y = -ds4_z   (Light Bar up -> PS Move +Y sphere up)
          move_z = +ds4_y   (Touchpad/face -> PS Move +Z face buttons)
    """
    ax, ay, az = float(accel_g[0]), float(accel_g[1]), float(accel_g[2])
    gx, gy, gz = float(gyro_rad_s[0]), float(gyro_rad_s[1]), float(gyro_rad_s[2])

    if str(grip).strip().lower() == "flat":
        mx, my, mz = ax, ay, az
        gmx, gmy, gmz = gx, gy, gz
    else:
        # Vertical thumbs-up hold (+90 deg pitch around X, det = +1)
        mx, my, mz = ax, -az, ay
        gmx, gmy, gmz = gx, -gz, gy

    acc_counts = (
        _clamp_i16(mx * PSMOVE_ACCEL_COUNTS_PER_G),
        _clamp_i16(my * PSMOVE_ACCEL_COUNTS_PER_G),
        _clamp_i16(mz * PSMOVE_ACCEL_COUNTS_PER_G),
    )
    gyro_counts = (
        _clamp_i16(gmx * PSMOVE_GYRO_COUNTS_PER_RAD_S),
        _clamp_i16(gmy * PSMOVE_GYRO_COUNTS_PER_RAD_S),
        _clamp_i16(gmz * PSMOVE_GYRO_COUNTS_PER_RAD_S),
    )
    return acc_counts, gyro_counts


def encode_zcm2_input_report(
    accel_counts: Tuple[int, int, int],
    gyro_counts: Tuple[int, int, int],
    buttons_mask: int = 0,
    trigger_analog: int = 0,
    battery_code: int = 5,
    seq4: int = 0,
    ts16: int = 0,
) -> bytes:
    """
    Reference Python encoder for the 49-byte ZCM2 Bluetooth HID Input Report (Report ID 0x01),
    byte-for-byte identical to `PackZcm2InputReport` inside `LegacyMove.dll`.
    """
    buf = bytearray(49)
    buf[0] = 0x01
    buf[1] = buttons_mask & 0xFF
    buf[2] = (buttons_mask >> 8) & 0xFF
    buf[3] = (buttons_mask >> 16) & 0xFF
    buf[4] = ((buttons_mask >> 24) & 0xF0) | (seq4 & 0x0F)
    buf[5] = max(0, min(255, int(trigger_analog)))
    buf[11] = (ts16 >> 8) & 0xFF
    buf[12] = battery_code & 0xFF
    struct.pack_into("<hhh", buf, 13, int(accel_counts[0]), int(accel_counts[1]), int(accel_counts[2]))
    struct.pack_into("<hhh", buf, 25, int(gyro_counts[0]), int(gyro_counts[1]), int(gyro_counts[2]))
    buf[43] = ts16 & 0xFF
    return bytes(buf)


class PSMoveSharedMemory:
    """
    Lockless seqlock IPC channel (`Local\\LegacyPSMoveState`, 128 bytes) connecting
    Python's `DS4Controller` to the injected `LegacyMove.dll` / `LegacyMove_x64.dll`.
    """

    def __init__(self, name: str = PSMOVE_SHARED_NAME) -> None:
        self.name = name
        self.seq = 0
        self._lock = threading.Lock()
        self.shm: Optional[mmap.mmap] = mmap.mmap(-1, PSMOVE_SHARED_SIZE, tagname=self.name)
        # Initialize clean inactive header while preserving any existing zeroed memory
        self.write_inactive()

    def write_state(
        self,
        active: bool,
        accel_counts: Tuple[int, int, int] = (0, 4400, 0),
        gyro_counts: Tuple[int, int, int] = (0, 0, 0),
        buttons_mask: int = 0,
        trigger_analog: int = 0,
        battery_code: int = 5,
    ) -> None:
        with self._lock:
            if self.shm is None:
                return
            ts_ms = int(time.time() * 1000)
            ax, ay, az = accel_counts
            gx, gy, gz = gyro_counts
            trig = max(0, min(255, int(trigger_analog)))
            batt = max(0, min(255, int(battery_code)))
            act_val = 1 if active else 0

            # Seqlock write: prepare payload BEFORE opening odd-seq window so C++ readers
            # see a sub-microsecond write window instead of Python packing latency.
            seq_odd = (self.seq + 1) & 0xFFFFFFFF
            if (seq_odd & 1) == 0:
                seq_odd = (seq_odd + 1) & 0xFFFFFFFF
            seq_even = (seq_odd + 1) & 0xFFFFFFFF

            payload = struct.pack(
                _SENSOR_FMT,
                PSMOVE_MAGIC,
                PSMOVE_VERSION,
                seq_odd,
                act_val,
                ts_ms,
                buttons_mask & 0xFFFFFFFF,
                trig,
                batt,
                0,
                max(-32767, min(32767, int(ax))),
                max(-32767, min(32767, int(ay))),
                max(-32767, min(32767, int(az))),
                max(-32767, min(32767, int(gx))),
                max(-32767, min(32767, int(gy))),
                max(-32767, min(32767, int(gz))),
                b"\x00" * 20,
            )
            seq_odd_bytes = struct.pack("<I", seq_odd)
            seq_even_bytes = struct.pack("<I", seq_even)

            self.shm[_SEQ_OFFSET:_SEQ_OFFSET + 4] = seq_odd_bytes
            self.shm[0:64] = payload
            self.shm[_SEQ_OFFSET:_SEQ_OFFSET + 4] = seq_even_bytes
            self.seq = seq_even

    def write_inactive(self) -> None:
        """Marks the virtual PS Move inactive so LegacyMove.dll stays 100% invisible."""
        self.write_state(
            active=False,
            accel_counts=(0, 0, 0),
            gyro_counts=(0, 0, 0),
            buttons_mask=0,
            trigger_analog=0,
            battery_code=0,
        )

    def read_sensor_state(self) -> Dict[str, Any]:
        """Reads back the Sensor -> Game 64-byte section (useful for diagnostics & tests)."""
        with self._lock:
            if self.shm is None:
                return {"active": False}
            raw = bytes(self.shm[0:64])
        (
            magic, version, seq, active, ts_ms, buttons_mask, trig, batt,
            _res0, ax, ay, az, gx, gy, gz, _res1,
        ) = struct.unpack(_SENSOR_FMT, raw)
        return {
            "magic": magic,
            "version": version,
            "seq": seq,
            "active": bool(active),
            "timestamp_ms": ts_ms,
            "buttons_mask": buttons_mask,
            "trigger_analog": trig,
            "battery_code": batt,
            "accel_counts": (ax, ay, az),
            "gyro_counts": (gx, gy, gz),
        }

    def read_feedback(self) -> Dict[str, Any]:
        """Reads the Game -> Sensor 64-byte feedback section (RGB sphere, rumble, game link)."""
        with self._lock:
            if self.shm is None:
                return {
                    "fb_seq": 0,
                    "game_connected": False,
                    "led_rgb": (0, 67, 156),
                    "rumble": 0,
                    "game_pid": 0,
                    "input_reports": 0,
                    "output_reports": 0,
                }
            raw = bytes(self.shm[_FEEDBACK_OFFSET:PSMOVE_SHARED_SIZE])
        fb_seq, game_conn, r, g, b, rumble, game_pid, in_rep, out_rep, _res2 = struct.unpack(
            _FEEDBACK_FMT, raw
        )
        return {
            "fb_seq": int(fb_seq),
            "game_connected": bool(game_conn),
            "led_rgb": (int(r), int(g), int(b)),
            "rumble": int(rumble),
            "game_pid": int(game_pid),
            "input_reports": int(in_rep),
            "output_reports": int(out_rep),
        }

    def write_feedback_for_test(
        self,
        game_connected: bool,
        led_rgb: Tuple[int, int, int],
        rumble: int = 0,
        game_pid: int = 1234,
        fb_seq: int = 1,
        input_reports: int = 10,
        output_reports: int = 1,
    ) -> None:
        """Helper for deterministic unit tests simulating LegacyMove.dll output reports."""
        with self._lock:
            if self.shm is None:
                return
            r, g, b = (max(0, min(255, int(c))) for c in led_rgb)
            buf = struct.pack(
                _FEEDBACK_FMT,
                int(fb_seq),
                1 if game_connected else 0,
                r,
                g,
                b,
                max(0, min(255, int(rumble))),
                int(game_pid),
                int(input_reports),
                int(output_reports),
                b"\x00" * 40,
            )
            self.shm[_FEEDBACK_OFFSET:PSMOVE_SHARED_SIZE] = buf

    def close(self) -> None:
        with self._lock:
            if self.shm is not None:
                try:
                    # Mark inactive before closing
                    self.shm[12:16] = b"\x00\x00\x00\x00"
                    self.shm.close()
                except Exception:
                    pass
                self.shm = None


_psmove_bridge_lock = threading.Lock()
_psmove_bridge_instance: Optional[PSMoveSharedMemory] = None


def get_psmove_bridge() -> PSMoveSharedMemory:
    """Returns the process-wide singleton PSMoveSharedMemory instance."""
    global _psmove_bridge_instance
    with _psmove_bridge_lock:
        if _psmove_bridge_instance is None or _psmove_bridge_instance.shm is None:
            _psmove_bridge_instance = PSMoveSharedMemory()
        return _psmove_bridge_instance


def close_psmove_bridge() -> None:
    """Safely marks virtual PS Move inactive and closes the shared memory bridge."""
    global _psmove_bridge_instance
    with _psmove_bridge_lock:
        if _psmove_bridge_instance is not None:
            _psmove_bridge_instance.close()
            _psmove_bridge_instance = None
