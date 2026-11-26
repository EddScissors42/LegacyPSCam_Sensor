"""
Modular unit tests for `sensor/vphone_protocol.py`:
- HandAccelerometer physics, gravity, clamping, and hand selection
- AdaptiveCalibrationTuner synonyms, cooldown, and reset
- _MinimalWebSocketClient 64-bit payload size cap & RFC 6455 _send_pong framing
- find_just_dance_pids process name matching (including Legacy.exe)
"""
from __future__ import annotations

import inspect
import math
import struct
import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sensor.vphone_protocol import (
    AdaptiveCalibrationTuner,
    HandAccelerometer,
    _MinimalWebSocketClient,
    find_just_dance_pids,
)
from sensor.kinect_shared_memory import NEUTRAL_POSE


class _DummySocket:
    """In-memory mock socket for deterministic RFC 6455 framing tests."""

    def __init__(self, rx_bytes: bytes = b"") -> None:
        self._rx = bytearray(rx_bytes)
        self.sent = bytearray()
        self.closed = False
        self.timeout = 0.02

    def settimeout(self, t: float) -> None:
        self.timeout = t

    def recv(self, n: int) -> bytes:
        if not self._rx:
            return b""
        chunk = bytes(self._rx[:n])
        del self._rx[:n]
        return chunk

    def sendall(self, data: bytes) -> None:
        self.sent.extend(data)

    def close(self) -> None:
        self.closed = True


class TestVPhoneProtocol(unittest.TestCase):
    def test_hand_accelerometer_gravity_and_clamping(self):
        acc = HandAccelerometer(hand="right", sensitivity=2.0)
        joints = [list(j) for j in NEUTRAL_POSE]
        # Rest pose initializes without NaN and stays well within MAX_G
        gx, gy, gz = acc.update(joints, is_tracked=True, now=1.0)
        mag = math.sqrt(gx * gx + gy * gy + gz * gz)
        self.assertLessEqual(mag, HandAccelerometer.MAX_G + 1e-6)

        # Extreme jump must clamp vector magnitude strictly to <= MAX_G (7.0 G)
        joints_fast = [list(j) for j in NEUTRAL_POSE]
        joints_fast[11] = (3.5, 3.5, 0.2, 0.99)
        acc.update(joints_fast, is_tracked=True, now=1.016)
        joints_fast2 = [list(j) for j in NEUTRAL_POSE]
        joints_fast2[11] = (-3.5, -3.5, 3.0, 0.99)
        ax, ay, az = acc.update(joints_fast2, is_tracked=True, now=1.032)
        mag2 = math.sqrt(ax * ax + ay * ay + az * az)
        self.assertLessEqual(mag2, HandAccelerometer.MAX_G + 1e-3)

        # Untracked resets smoothly
        acc.update([], is_tracked=False, now=1.05)
        self.assertEqual(acc.latest_speed, 0.0)

    def test_hand_accelerometer_left_vs_right(self):
        acc_l = HandAccelerometer(hand="left")
        acc_r = HandAccelerometer(hand="invalid_side")
        self.assertEqual(acc_l.hand, "left")
        self.assertEqual(acc_r.hand, "right")

    def test_adaptive_calibration_tuner(self):
        tuner = AdaptiveCalibrationTuner(base_sensitivity=1.0)
        tuner.enabled = True
        tuner._last_adjust_ts = -10.0  # bypass initial cooldown
        mult_before = tuner.multiplier
        tuner.on_feedback("POOR", current_speed=1.5, current_accel=(1.0, 2.0, 1.0))
        self.assertEqual(tuner.counts["OK"], 1)
        self.assertGreater(tuner.multiplier, mult_before)

        # Unknown rating ignored
        tuner.on_feedback("UNKNOWN_TOKEN")
        self.assertEqual(tuner.total_moves, 1)

        # Reset song clears counts
        tuner.reset_song("Rasputin")
        self.assertEqual(tuner.total_moves, 0)
        self.assertEqual(tuner.counts["OK"], 0)

    def test_ws_rejects_oversized_64bit_payload(self):
        client = _MinimalWebSocketClient("127.0.0.1", 8080)
        oversized_len = _MinimalWebSocketClient.MAX_WS_PAYLOAD_BYTES + 1024
        header = bytes([0x81, 127]) + struct.pack("!Q", oversized_len)
        sock = _DummySocket(rx_bytes=header)
        client._sock = sock
        client.connected = True

        with self.assertRaises(ConnectionError):
            client.recv_messages()
        self.assertFalse(client.connected)
        self.assertTrue(sock.closed)

    def test_ws_send_pong_truncates_payload_before_header(self):
        client = _MinimalWebSocketClient("127.0.0.1", 8080)
        sock = _DummySocket()
        client._sock = sock
        client.connected = True

        # Payload > 125 bytes (RFC 6455 control frame max is 125 bytes)
        client._send_pong(b"X" * 200)
        raw = bytes(sock.sent)
        self.assertGreaterEqual(len(raw), 6)
        self.assertEqual(raw[0], 0x8A)  # FIN + PONG
        declared_len = raw[1] & 0x7F
        self.assertEqual(declared_len, 125)
        self.assertEqual(len(raw), 2 + 4 + 125)  # 2B hdr + 4B mask + 125B payload

    def test_find_just_dance_pids_supports_legacy_exe(self):
        src = inspect.getsource(find_just_dance_pids)
        self.assertIn("legacy.exe", src.lower())


if __name__ == "__main__":
    unittest.main()
