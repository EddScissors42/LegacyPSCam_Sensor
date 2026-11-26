"""
Modular unit tests for tracking math, gesture state machine, and Re-ID subsystem:
- AdaptiveSmoother continuous-time dt compensation across 30 / 60 / 120 FPS (3D & 2D)
- ArmRaiseGestureDetector 2P timer isolation (P1 -> P2 switch resets timer) & consistent `hand_pos`
- sensor.player_reid plausibility filtering, NMS duplicate suppression, and player_slot re-exports
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sensor.pose_filters import AdaptiveSmoother
from sensor.gesture_detector import ArmRaiseGestureDetector
from sensor import player_reid, player_slot


class _LM:
    def __init__(self, x: float, y: float, z: float = 0.0, visibility: float = 0.95, presence: float = 0.95):
        self.x = x
        self.y = y
        self.z = z
        self.visibility = visibility
        self.presence = presence


def _make_standing_pose(cx: float = 0.5) -> list:
    lms = [_LM(cx, 0.50, 0.0) for _ in range(33)]
    lms[0] = _LM(cx, 0.20)             # NOSE
    lms[11] = _LM(cx + 0.08, 0.34)     # LEFT_SHOULDER
    lms[12] = _LM(cx - 0.08, 0.34)     # RIGHT_SHOULDER
    lms[13] = _LM(cx + 0.12, 0.48)     # LEFT_ELBOW
    lms[14] = _LM(cx - 0.12, 0.48)     # RIGHT_ELBOW
    lms[15] = _LM(cx + 0.14, 0.60)     # LEFT_WRIST
    lms[16] = _LM(cx - 0.14, 0.60)     # RIGHT_WRIST
    lms[23] = _LM(cx + 0.06, 0.58)     # LEFT_HIP
    lms[24] = _LM(cx - 0.06, 0.58)     # RIGHT_HIP
    lms[25] = _LM(cx + 0.06, 0.74)     # LEFT_KNEE
    lms[26] = _LM(cx - 0.06, 0.74)     # RIGHT_KNEE
    lms[27] = _LM(cx + 0.06, 0.90)     # LEFT_ANKLE
    lms[28] = _LM(cx - 0.06, 0.90)     # RIGHT_ANKLE
    return lms


class TestTrackingMath(unittest.TestCase):
    def test_adaptive_smoother_dt_time_constant_30_60_120fps(self):
        origin = [(0.0, 0.0, 2.0, 1.0)] * 20
        target = [(0.002, 0.0, 2.0, 1.0)] * 20

        s30 = AdaptiveSmoother(base_alpha=0.50, alpha_fast=0.90, speed_threshold=0.15)
        s60 = AdaptiveSmoother(base_alpha=0.50, alpha_fast=0.90, speed_threshold=0.15)
        s120 = AdaptiveSmoother(base_alpha=0.50, alpha_fast=0.90, speed_threshold=0.15)

        s30.apply(origin)
        s60.apply(origin)
        s120.apply(origin)

        y30 = s30.apply(target, dt=1.0 / 30.0)[0][0]
        for _ in range(2):
            y60 = s60.apply(target, dt=1.0 / 60.0)[0][0]
        for _ in range(4):
            y120 = s120.apply(target, dt=1.0 / 120.0)[0][0]

        self.assertAlmostEqual(y30, y60, delta=1e-4)
        self.assertAlmostEqual(y30, y120, delta=1e-4)

    def test_adaptive_smoother_pixel_dt_compensation(self):
        px_origin = [(320, 240, 0.95)] * 20
        px_target = [(324, 240, 0.95)] * 20

        s30 = AdaptiveSmoother(base_alpha=0.50, alpha_fast=0.90, speed_threshold=0.15)
        s60 = AdaptiveSmoother(base_alpha=0.50, alpha_fast=0.90, speed_threshold=0.15)
        s30.apply_pixel(px_origin, 640, 480, dt=1.0 / 30.0)
        s60.apply_pixel(px_origin, 640, 480, dt=1.0 / 60.0)

        out30 = s30.apply_pixel(px_target, 640, 480, dt=1.0 / 30.0)[0][0]
        s60.apply_pixel(px_target, 640, 480, dt=1.0 / 60.0)
        out60 = s60.apply_pixel(px_target, 640, 480, dt=1.0 / 60.0)[0][0]
        self.assertLessEqual(abs(out30 - out60), 1)

    def test_arm_raise_2p_player_switch_resets_timer_and_has_hand_pos(self):
        det = ArmRaiseGestureDetector(enabled=True, hold_seconds=2.0, cooldown_seconds=2.0, dispatch_keystroke=False)

        # Early return schema must include "hand_pos"
        empty_state = det.update_multi([], is_tracked=False, now=10.0)
        self.assertIn("hand_pos", empty_state)
        self.assertIsNone(empty_state["hand_pos"])

        p_down = [(200, 200, 0.9)] * 20
        p_down[3] = (200, 120, 0.9)
        p_down[7] = (170, 260, 0.9)
        p_down[11] = (230, 260, 0.9)

        p1_up = list(p_down)
        p1_up[11] = (230, 60, 0.95)

        p2_up = [(440, 200, 0.9)] * 20
        p2_up[3] = (440, 120, 0.9)
        p2_up[7] = (410, 260, 0.9)
        p2_up[11] = (470, 65, 0.95)

        # P1 holds arm up for 1.8s (just short of 2.0s)
        det.update_multi([p1_up, p_down], is_tracked=True, now=100.0)
        st_p1 = det.update_multi([p1_up, p_down], is_tracked=True, now=101.8)
        self.assertFalse(st_p1["triggered"])
        self.assertEqual(st_p1["player_idx"], 0)

        # On the very next frame P1 drops and P2 raises -> timer MUST reset (no instant trigger at t=102.1!)
        st_switch = det.update_multi([p_down, p2_up], is_tracked=True, now=102.1)
        self.assertFalse(st_switch["triggered"])
        self.assertEqual(st_switch["player_idx"], 1)
        self.assertEqual(st_switch["elapsed"], 0.0)

        # P2 completes a full 2.0s hold starting at 102.1 -> triggers at 104.2
        st_p2_done = det.update_multi([p_down, p2_up], is_tracked=True, now=104.2)
        self.assertTrue(st_p2_done["triggered"])
        self.assertEqual(st_p2_done["player_idx"], 1)

    def test_player_reid_extraction_and_backwards_compat(self):
        # Re-exports must point to the exact same symbols
        self.assertIs(player_slot.AppearanceSignature, player_reid.AppearanceSignature)
        self.assertIs(player_slot.LongTermIdentityProfile, player_reid.LongTermIdentityProfile)
        self.assertIs(player_slot.MultiPlayerAssociator, player_reid.MultiPlayerAssociator)
        self.assertIs(player_slot.suppress_duplicate_poses, player_reid.suppress_duplicate_poses)

        pose_a = _make_standing_pose(0.30)
        pose_b = _make_standing_pose(0.70)
        ok, score = player_reid.is_plausible_human_dancer(pose_a, w=640, h=480)
        self.assertTrue(ok)
        self.assertGreater(score, 5.0)
        self.assertEqual(player_reid.explain_plausibility_rejection(pose_a, w=640, h=480), "ok")

        # Duplicate suppression keeps distinct dancers and removes near-identical duplicate
        pose_a_dup = _make_standing_pose(0.305)
        cands = [
            (10.0, (None, pose_a, None)),
            (9.5, (None, pose_b, None)),
            (8.0, (None, pose_a_dup, None)),
        ]
        kept, suppressed = player_reid.suppress_duplicate_poses(cands, max_players=2)
        self.assertEqual(len(kept), 2)
        self.assertEqual(suppressed, 1)


if __name__ == "__main__":
    unittest.main()
