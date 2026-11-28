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

    def test_body_mask_extraction_and_desk_framing(self):
        import numpy as np
        from sensor import body_mask, pose_tracker

        # PoseTracker staticmethod must point directly to sensor.body_mask.extract_joints_2d
        self.assertIs(pose_tracker.PoseTracker._extract_joints_2d, body_mask.extract_joints_2d)

        pose_full = _make_standing_pose(0.50)
        j2d = body_mask.extract_joints_2d(pose_full, 640, 480)
        self.assertEqual(len(j2d), 20)
        self.assertAlmostEqual(j2d[3][0], 320.0, delta=1e-3)  # Head/Nose X

        mask_full = body_mask.build_body_mask(pose_full, 320, 240)
        self.assertEqual(mask_full.shape, (240, 320))
        self.assertEqual(mask_full.dtype, np.uint8)
        self.assertGreater(int(np.count_nonzero(mask_full)), 500)

        # Desk framing: hips & legs invisible -> torso polygon must still synthesize down to bottom
        pose_desk = _make_standing_pose(0.50)
        for idx in (23, 24, 25, 26, 27, 28, 31, 32):
            pose_desk[idx] = _LM(0.50, 0.99, visibility=0.0, presence=0.0)
        mask_desk = body_mask.build_body_mask(pose_desk, 320, 240)
        self.assertEqual(mask_desk.shape, (240, 320))
        self.assertGreater(int(np.count_nonzero(mask_desk)), 300)

    def test_camera_submodules_backwards_compat_and_helpers(self):
        import numpy as np
        from sensor import camera_manager, camera_capture, framebus_reader, camera_win32

        self.assertIs(camera_manager.LatestFrameCamera, camera_capture.LatestFrameCamera)
        self.assertIs(camera_manager.FrameBusReader, framebus_reader.FrameBusReader)
        self.assertIs(camera_manager._CAMERA_HW_LOCK, camera_capture._CAMERA_HW_LOCK)
        self.assertIs(
            camera_manager.CameraManager._get_windows_camera_names_win32,
            camera_win32.get_windows_camera_names_win32,
        )

        # Fast strided black-frame check
        self.assertTrue(camera_capture.LatestFrameCamera._is_black_frame(None))
        self.assertTrue(camera_capture.LatestFrameCamera._is_black_frame(np.zeros((48, 64, 3), dtype=np.uint8)))
        self.assertFalse(camera_capture.LatestFrameCamera._is_black_frame(np.full((48, 64, 3), 120, dtype=np.uint8)))

        # Orientation helper across 0 / 90 / 180 / 270 degrees without opening hardware
        cam = camera_capture.LatestFrameCamera.__new__(camera_capture.LatestFrameCamera)
        img = np.zeros((40, 60, 3), dtype=np.uint8)
        img[0, 0] = (10, 20, 30)
        cam.orientation = 0
        self.assertEqual(cam._apply_orientation(img).shape, (40, 60, 3))
        cam.orientation = 90
        self.assertEqual(cam._apply_orientation(img).shape, (60, 40, 3))
        cam.orientation = 180
        rot180 = cam._apply_orientation(img)
        self.assertEqual(rot180.shape, (40, 60, 3))
        self.assertEqual(tuple(rot180[-1, -1]), (10, 20, 30))
        cam.orientation = 270
        self.assertEqual(cam._apply_orientation(img).shape, (60, 40, 3))

    def test_plausibility_gate_desk_wide_arms_and_profile_spin(self):
        # Desk / upper-body pose with wide arms (score=2.06 in [1.75, 2.2), aspect=0.266 in [0.22, 0.28)) MUST pass
        lms_desk = [_LM(0.50, 0.50, visibility=0.0, presence=0.0) for _ in range(33)]
        lms_desk[0] = _LM(0.50, 0.25, visibility=0.68, presence=0.68)   # NOSE
        lms_desk[11] = _LM(0.62, 0.45, visibility=0.52, presence=0.52)  # LEFT_SHOULDER
        lms_desk[12] = _LM(0.38, 0.45, visibility=0.52, presence=0.52)  # RIGHT_SHOULDER
        lms_desk[13] = _LM(0.76, 0.49, visibility=0.18, presence=0.0)   # LEFT_ELBOW
        lms_desk[14] = _LM(0.24, 0.49, visibility=0.18, presence=0.0)   # RIGHT_ELBOW
        lms_desk[15] = _LM(0.88, 0.52, visibility=0.16, presence=0.0)   # LEFT_WRIST
        lms_desk[16] = _LM(0.12, 0.52, visibility=0.16, presence=0.0)   # RIGHT_WRIST
        ok_desk, score_desk = player_reid.is_plausible_human_dancer(lms_desk, w=640, h=480)
        self.assertTrue(ok_desk, f"Valid desk/wide-arms dancer rejected: {player_reid.explain_plausibility_rejection(lms_desk, 640, 480)}")
        self.assertGreaterEqual(score_desk, 1.75)
        self.assertLess(score_desk, 2.2)

        # Tall sideways/back-facing 360° spin (face occluded, score=2.90 in [2.6, 3.2)) MUST pass
        lms_spin = [_LM(0.50, 0.50, visibility=0.0, presence=0.0) for _ in range(33)]
        lms_spin[0] = _LM(0.50, 0.18, visibility=0.10, presence=0.10)   # NOSE (occluded during spin)
        lms_spin[11] = _LM(0.535, 0.28, visibility=0.45, presence=0.45) # LEFT_SHOULDER
        lms_spin[12] = _LM(0.465, 0.28, visibility=0.40, presence=0.40) # RIGHT_SHOULDER
        lms_spin[13] = _LM(0.55, 0.44, visibility=0.35, presence=0.35)  # LEFT_ELBOW
        lms_spin[14] = _LM(0.45, 0.44, visibility=0.30, presence=0.30)  # RIGHT_ELBOW
        lms_spin[23] = _LM(0.53, 0.56, visibility=0.45, presence=0.45)  # LEFT_HIP
        lms_spin[24] = _LM(0.47, 0.56, visibility=0.40, presence=0.40)  # RIGHT_HIP
        lms_spin[25] = _LM(0.53, 0.76, visibility=0.25, presence=0.25)  # LEFT_KNEE
        lms_spin[26] = _LM(0.47, 0.76, visibility=0.20, presence=0.20)  # RIGHT_KNEE
        ok_spin, score_spin = player_reid.is_plausible_human_dancer(lms_spin, w=640, h=480)
        self.assertTrue(ok_spin, f"Valid tall profile spin rejected: {player_reid.explain_plausibility_rejection(lms_spin, 640, 480)}")
        self.assertGreaterEqual(score_spin, 2.6)
        self.assertLess(score_spin, 3.2)

        # Flat horizontal furniture artifact without strong face+shoulders MUST remain rejected
        lms_flat = [_LM(0.50, 0.50, visibility=0.0, presence=0.0) for _ in range(33)]
        lms_flat[0] = _LM(0.50, 0.45, visibility=0.20, presence=0.20)
        lms_flat[11] = _LM(0.75, 0.50, visibility=0.35, presence=0.35)
        lms_flat[12] = _LM(0.25, 0.50, visibility=0.35, presence=0.35)
        lms_flat[13] = _LM(0.85, 0.51, visibility=0.30, presence=0.30)
        lms_flat[14] = _LM(0.15, 0.51, visibility=0.30, presence=0.30)
        lms_flat[23] = _LM(0.70, 0.58, visibility=0.30, presence=0.30)
        lms_flat[24] = _LM(0.30, 0.58, visibility=0.30, presence=0.30)
        ok_flat, _ = player_reid.is_plausible_human_dancer(lms_flat, w=640, h=480)
        self.assertFalse(ok_flat)

    def test_pose_tracker_adaptive_infer_width_hysteresis(self):
        from sensor.pose_tracker import PoseTracker

        pt = PoseTracker.__new__(PoseTracker)
        pt.max_players = 1
        pt._adaptive_infer_enabled = True
        pt._adaptive_tier_idx = 0
        pt._infer_ms_ema = None
        pt._slow_streak = 0
        pt._fast_streak = 0

        # Fast PC (15ms = 66 FPS) stays locked at 640px
        for _ in range(30):
            w = pt._update_adaptive_infer_width(15.0)
        self.assertEqual(w, 640)

        # Overloaded CPU (110ms = ~9 FPS) steps down 640 -> 384 -> 320
        for _ in range(45):
            w = pt._update_adaptive_infer_width(110.0)
        self.assertEqual(w, 320)

        # Recovered CPU (14ms) steps back up 320 -> 384 -> 640 cleanly with hysteresis
        for _ in range(120):
            w = pt._update_adaptive_infer_width(14.0)
        self.assertEqual(w, 640)

    def test_pose_tracker_quality_settings_modes(self):
        from sensor.pose_tracker import PoseTracker

        pt = PoseTracker.__new__(PoseTracker)
        pt.segmentation_mode = "accurate"

        # Performance: Low (320p fixed) + Fast (geometric, requires detector reinit)
        reinit = pt._apply_quality_settings({"infer_quality_mode": "low", "segmentation_mode": "fast"})
        self.assertTrue(reinit)
        self.assertEqual(pt.segmentation_mode, "fast")
        self.assertEqual(pt.infer_quality_mode, "low")
        self.assertFalse(pt._adaptive_infer_enabled)
        self.assertEqual(pt._fixed_infer_max_w, 320)

        # Balanced: Auto adaptive + Accurate (AI neural mask)
        reinit2 = pt._apply_quality_settings({"infer_quality_mode": "auto", "segmentation_mode": "accurate"})
        self.assertTrue(reinit2)
        self.assertEqual(pt.segmentation_mode, "accurate")
        self.assertTrue(pt._adaptive_infer_enabled)
        self.assertEqual(pt._fixed_infer_max_w, 640)

        # High: 640p fixed + Accurate (no detector reinit needed when seg unchanged)
        reinit3 = pt._apply_quality_settings({"infer_quality_mode": "high", "segmentation_mode": "accurate"})
        self.assertFalse(reinit3)
        self.assertFalse(pt._adaptive_infer_enabled)
        self.assertEqual(pt._fixed_infer_max_w, 640)

    def test_calibrator_stereo_z_persistence_and_scale_clamp(self):
        from sensor.pose_filters import SkeletonCalibrator

        calib = SkeletonCalibrator(target_height_m=1.75, cfg={"baseline_z_m": 2.2, "hip_height_m": 1.0})
        # Narrow sideways Tier 3 pose (raw_height = 0.42m) MUST clamp scale <= 1.42 (no 3.7m giant hands)
        joints = [(0.0, 0.0, 0.0, 0.9) for _ in range(20)]
        joints[3] = (0.0, -0.10, 0.0, 0.9)   # Head close to shoulders (sideways/lean)
        joints[4] = (0.04, -0.05, 0.0, 0.9)  # ShL narrow
        joints[8] = (-0.04, -0.05, 0.0, 0.9) # ShR narrow
        joints[14] = (0.0, 0.0, 0.0, 0.0)    # Ankles hidden
        joints[18] = (0.0, 0.0, 0.0, 0.0)
        joints[0] = (0.0, 0.0, 0.0, 0.0)     # Hip hidden -> Tier 3
        self.assertTrue(calib.calibrate(joints, legs_visible=False, hips_visible=False))
        self.assertLessEqual(calib.scale, 1.30)
        self.assertGreaterEqual(calib.scale, 0.85)

        # Close-room stereo Z (1.20m) MUST clamp into Kinect v1's lobby play-zone (>= 1.75m)
        joints[0] = (0.0, 0.0, 0.0, 0.9)
        t_close = calib.transform(joints, stereo_depths={0: (0.0, 0.0, 1.20, 0.9), 2: (0.0, 0.4, 1.20, 0.9)})
        self.assertGreaterEqual(t_close[0][2], 1.74)

        # Stereo baseline Z (2.50m) MUST persist on frames where stereo_depths is None / empty
        calib.reset()
        calib.calibrate(joints)
        t1 = calib.transform(joints, stereo_depths={0: (0.0, 0.0, 2.50, 0.9), 2: (0.0, 0.4, 2.50, 0.9)})
        self.assertAlmostEqual(t1[0][2], 2.50, delta=0.05)
        t2 = calib.transform(joints, stereo_depths=None)
        self.assertAlmostEqual(t2[0][2], 2.50, delta=0.05)
        t3 = calib.transform(joints, stereo_depths={})
        self.assertAlmostEqual(t3[0][2], 2.50, delta=0.05)

    def test_adaptive_smoother_damps_single_frame_hand_teleport(self):
        s = AdaptiveSmoother(base_alpha=0.75, alpha_fast=0.92, speed_threshold=0.15)
        base = [(0.0, 1.0, 2.0, 0.95) for _ in range(20)]
        base[11] = (0.25, 1.20, 2.0, 0.95)  # HandRight
        s.apply(base, dt=1.0 / 30.0)

        # 1-frame MediaPipe L/R swap glitch: HandRight jumps -1.10m while HipCenter stays put
        glitch = list(base)
        glitch[11] = (-0.85, 1.20, 2.0, 0.95)
        out_glitch = s.apply(glitch, dt=1.0 / 30.0)
        # Displacement must be heavily damped (<0.30m instead of 1.05m teleport!)
        self.assertLess(abs(out_glitch[11][0] - 0.25), 0.30)

        # Also catch moderate 0.40m single-frame limb glitches (previously bypassed 0.55m threshold)
        s.reset()
        s.apply(base, dt=1.0 / 30.0)
        glitch_med = list(base)
        glitch_med[11] = (0.65, 1.20, 2.0, 0.95)
        out_med = s.apply(glitch_med, dt=1.0 / 30.0)
        self.assertLess(abs(out_med[11][0] - 0.25), 0.14)

    def test_adaptive_smoother_decoupled_xy_z_and_calm_stationary_extremities(self):
        s = AdaptiveSmoother(base_alpha=0.75, alpha_fast=0.92, speed_threshold=0.15)
        base = [(0.0, 1.0, 2.0, 0.95) for _ in range(20)]
        base[11] = (0.25, 1.20, 2.0, 0.95)
        s.apply(base, dt=1.0 / 30.0)

        # Stationary micro-jitter on HandRight (+8mm XY, +8mm Z) must stay calm (<=0.56 alpha, not 0.94!)
        jitter = list(base)
        jitter[11] = (0.258, 1.200, 2.008, 0.95)
        out_j = s.apply(jitter, dt=1.0 / 30.0)
        self.assertLessEqual(out_j[11][0] - 0.25, 0.008 * 0.60)
        self.assertLessEqual(out_j[11][2] - 2.0, 0.008 * 0.55)

        # Pure Z noise spike (+0.12m Z, +0.005m XY) must NOT inflate XY smoothing alpha
        s.reset()
        s.apply(base, dt=1.0 / 30.0)
        z_spike = list(base)
        z_spike[11] = (0.255, 1.200, 2.120, 0.95)
        out_zs = s.apply(z_spike, dt=1.0 / 30.0)
        self.assertLessEqual(out_zs[11][0] - 0.25, 0.005 * 0.60)

        # Fast real XY swing (+0.20m) still responds instantaneously (> 0.88)
        s.reset()
        s.apply(base, dt=1.0 / 30.0)
        fast_xy = list(base)
        fast_xy[11] = (0.45, 1.20, 2.0, 0.95)
        out_fast = s.apply(fast_xy, dt=1.0 / 30.0)
        self.assertGreater(out_fast[11][0] - 0.25, 0.20 * 0.88)

    def test_skeleton_calibrator_zero_limb_stereo_popping_and_scale_refinement(self):
        from sensor.pose_filters import SkeletonCalibrator

        calib = SkeletonCalibrator(target_height_m=1.75, cfg={"baseline_z_m": 2.2, "hip_height_m": 1.0})
        joints = [(0.0, 0.0, 0.0, 0.95) for _ in range(20)]
        joints[0] = (0.0, 0.0, 0.0, 0.95)     # HipCenter
        joints[2] = (0.0, -0.48, 0.0, 0.95)   # ShoulderCenter
        joints[3] = (0.0, -0.75, 0.0, 0.95)   # Head
        joints[4] = (0.20, -0.48, 0.0, 0.95)  # ShoulderLeft
        joints[8] = (-0.20, -0.48, 0.0, 0.95) # ShoulderRight
        joints[10] = (-0.25, -0.25, -0.15, 0.95) # WristRight
        joints[11] = (-0.27, -0.18, -0.20, 0.95) # HandRight
        joints[14] = (0.10, 0.85, 0.0, 0.95)  # AnkleLeft
        joints[18] = (-0.10, 0.85, 0.0, 0.95) # AnkleRight
        calib.calibrate(joints)

        # Simulate stereo match popping on/off on WristRight(10) and HandRight(11) while torso Z is steady at 2.10m
        wrist_zs, hand_zs = [], []
        for tick in range(10):
            stereo = {0: (0.0, 0.0, 2.10, 0.92), 2: (0.0, 0.48, 2.10, 0.92)}
            if tick % 2 == 0:
                stereo[10] = (-0.25, 0.25, 1.45, 0.85)
                stereo[11] = (-0.27, 0.18, 2.95, 0.85)
            out = calib.transform(joints, stereo_depths=stereo)
            wrist_zs.append(out[10][2])
            hand_zs.append(out[11][2])
        self.assertLess(max(wrist_zs) - min(wrist_zs), 0.005, "Limb stereo mismatches must not pop Wrist Z")
        self.assertLess(max(hand_zs) - min(hand_zs), 0.005, "Limb stereo mismatches must not pop Hand Z")

        # Progressive upright scale refinement converges smoothly from skewed initial scale
        calib.scale = 1.35
        calib._scale_samples = 0
        for _ in range(25):
            calib.refine_full_body_scale(joints)
        expected_scale = 1.75 / 1.60  # head -0.75 to ankle +0.85 => 1.60m
        self.assertLess(abs(calib.scale - expected_scale), 0.04)

    def test_hand_anchor_anatomical_stretch_and_backward_fold_guard(self):
        import math
        from sensor.pose_filters import HandAnchorFilter

        haf = HandAnchorFilter(hand_length=0.12)
        joints = [(0.0, 0.0, 0.0, 0.95) for _ in range(20)]
        joints[9] = (0.20, 0.20, 0.0, 0.95)   # ElbowRight
        joints[10] = (0.20, 0.00, 0.0, 0.95)  # WristRight (forearm vector = (0, -1, 0))

        # 1) Over-stretched hand (0.35m past wrist) must be clamped <= 0.165m
        joints[11] = (0.20, -0.35, 0.0, 0.92)
        out_stretch = haf.apply(joints)
        d_stretch = math.dist(out_stretch[11][:3], out_stretch[10][:3])
        self.assertLessEqual(d_stretch, 0.165)

        # 2) Impossibly backward-folded hand (pointing straight back toward elbow along +Y) must pull forward
        joints[11] = (0.20, 0.12, 0.0, 0.92)
        out_fold = haf.apply(joints)
        self.assertLess(out_fold[11][1], out_fold[10][1], "Backward-folded hand must pull toward forearm direction")

    def test_slot_snap_c0_continuous_across_deadzone(self):
        from sensor.pose_filters import apply_slot_snap

        cfg = {"slot_snap_enabled": True, "slot_snap_gain": 1.30, "slot_snap_deadzone": 0.06}
        below = [(0.0599, 1.0, 2.0, 0.95)] * 20
        above = [(0.0601, 1.0, 2.0, 0.95)] * 20
        out_below = apply_slot_snap(below, cfg=cfg)
        out_above = apply_slot_snap(above, cfg=cfg)
        self.assertLess(abs(out_above[0][0] - out_below[0][0]), 0.001, "Slot snap must be continuous across deadzone")

    def test_camera_space_y_tracker_squat_jump_and_desk_stability(self):
        from sensor.pose_filters import CameraSpaceYTracker, apply_camera_space_y_translation

        tracker_y = CameraSpaceYTracker(cfg={"camera_y_bounce_tracking": True})
        standing = _make_standing_pose(0.50)
        # Initialize standing baseline (sh_y=0.34, hip_y=0.58 => torso=0.24)
        dy_init = tracker_y.update(standing, dt=1.0 / 30.0)
        self.assertAlmostEqual(dy_init, 0.0, delta=1e-4)

        # Squat down: hips drop from 0.58 to 0.72 (+0.14 norm => ~-0.29m)
        squat = _make_standing_pose(0.50)
        squat[11] = _LM(0.58, 0.48)
        squat[12] = _LM(0.42, 0.48)
        squat[23] = _LM(0.56, 0.72)
        squat[24] = _LM(0.44, 0.72)
        for _ in range(5):
            dy_squat = tracker_y.update(squat, dt=1.0 / 30.0)
        self.assertLess(dy_squat, -0.18, f"Squat must drop skeleton Y cleanly, got {dy_squat}")

        # Jump up: hips rise from 0.58 to 0.46 (-0.12 norm => ~+0.25m)
        jump = _make_standing_pose(0.50)
        jump[11] = _LM(0.58, 0.22)
        jump[12] = _LM(0.42, 0.22)
        jump[23] = _LM(0.56, 0.46)
        jump[24] = _LM(0.44, 0.46)
        for _ in range(8):
            dy_jump = tracker_y.update(jump, dt=1.0 / 30.0)
        self.assertGreater(dy_jump, 0.12, f"Jump must lift skeleton Y cleanly, got {dy_jump}")

        # Desk mode (hips invisible): offset decays back toward 0 and relative geometry stays intact
        base_j = [(0.0, 1.0, 2.0, 0.95) for _ in range(20)]
        base_j[3] = (0.0, 1.75, 2.0, 0.95)
        shifted = apply_camera_space_y_translation(base_j, jump, tracker_y, dt=1.0 / 30.0)
        self.assertAlmostEqual(shifted[3][1] - shifted[0][1], 0.75, delta=1e-4)

    def test_player_slot_palm_center_and_per_leg_independent_synthesis(self):
        import numpy as np
        from sensor.body_mask import extract_joints_2d, build_body_mask
        from sensor.player_slot import PlayerSlotState

        slot = PlayerSlotState(slot_index=0, cfg={"person_lock_enabled": False})
        norm = _make_standing_pose(0.50)
        # Set INDEX & PINKY symmetrically around palm center on Right hand
        norm[18] = _LM(0.32, 0.64)  # RIGHT_PINKY
        norm[20] = _LM(0.36, 0.66)  # RIGHT_INDEX
        # Occlude ONLY Right ankle (28) while Left leg (25, 27, 31) remains fully visible
        norm[28] = _LM(0.44, 0.95, visibility=0.05, presence=0.05)

        world = [_LM(0.0, 0.0, 0.0) for _ in range(33)]
        world[0] = _LM(0.0, -0.75, 0.0)
        world[7] = _LM(0.08, -0.75, 0.0)
        world[8] = _LM(-0.08, -0.75, 0.0)
        world[11] = _LM(0.20, -0.45, 0.0)
        world[12] = _LM(-0.20, -0.45, 0.0)
        world[13] = _LM(0.24, -0.20, 0.0)
        world[14] = _LM(-0.24, -0.20, 0.0)
        world[15] = _LM(0.26, 0.00, 0.0)
        world[16] = _LM(-0.26, 0.00, 0.0)
        world[18] = _LM(-0.30, 0.08, 0.0)  # RIGHT_PINKY
        world[20] = _LM(-0.22, 0.12, 0.0)  # RIGHT_INDEX (midpoint = (-0.26, 0.10))
        world[23] = _LM(0.10, 0.0, 0.0)
        world[24] = _LM(-0.10, 0.0, 0.0)
        world[25] = _LM(0.18, 0.42, -0.10)  # Left knee raised/forward
        world[26] = _LM(-0.10, 0.45, 0.0)   # Right knee visible
        world[27] = _LM(0.22, 0.80, -0.05)  # Left ankle clearly visible
        world[31] = _LM(0.24, 0.85, -0.15)  # Left foot

        dummy_bgr = np.zeros((480, 640, 3), dtype=np.uint8)
        pf = slot.process_detection(
            world_lm=world,
            norm_lm=norm,
            seg_mask_obj=None,
            frame_bgr=dummy_bgr,
            frame_left=None,
            stereo_engine=None,
            stereo_mode="disabled",
            extract_joints_2d_fn=extract_joints_2d,
            build_body_mask_fn=build_body_mask,
            dt_infer=1.0 / 30.0,
            w=640,
            h=480,
        )
        self.assertIsNotNone(pf)
        self.assertTrue(pf.tracked)
        # Left ankle (joint 14) must remain TRACKED (high conf >= 0.9), NOT wiped to synthesized 0.35!
        self.assertGreater(pf.kinect_joints[14][3], 0.80)
        # Right knee (joint 17) was visible so it must remain TRACKED, while only occluded right ankle (18) is inferred
        self.assertGreater(pf.kinect_joints[17][3], 0.80)
        self.assertAlmostEqual(pf.kinect_joints[18][3], 0.35, delta=0.05)

    def test_phone_camera_webapp_prevents_standby_fps_lock_and_hidden_video_throttle(self):
        html_path = ROOT_DIR / "assets" / "webapp" / "mobile_webapp.html"
        html = html_path.read_text(encoding="utf-8")
        # Auto-dim eco video surface must stay >= 64x48 (never 2x2) so mobile browsers don't throttle rVFC to 12-15 FPS
        self.assertIn("width: 64px !important;", html)
        self.assertNotIn("width: 2px !important;", html)
        # Standby wake must verify actual track frameRate and reopen camera if stuck below target FPS
        self.assertIn("actualFps", html)
        self.assertIn("applyStandbyFpsThrottle(false).then", html)


if __name__ == "__main__":
    unittest.main()
