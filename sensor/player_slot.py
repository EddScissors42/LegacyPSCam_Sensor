"""
Multi-Player Slot State and Player Index Mask Compositor for Legacy PSCam Sensor.

Re-ID, plausibility filtering, duplicate pose suppression (NMS), and multi-player
association live in `sensor/player_reid.py` and are re-exported here for 100%
backwards compatibility.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Callable, Dict, List, Optional, Tuple
import cv2
import numpy as np

from sensor.pose_filters import (
    NOSE, LEFT_EAR, RIGHT_EAR,
    LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_ELBOW, RIGHT_ELBOW,
    LEFT_WRIST, RIGHT_WRIST, LEFT_PINKY, RIGHT_PINKY, LEFT_INDEX, RIGHT_INDEX,
    LEFT_HIP, RIGHT_HIP, LEFT_KNEE, RIGHT_KNEE,
    LEFT_ANKLE, RIGHT_ANKLE, LEFT_FOOT_INDEX, RIGHT_FOOT_INDEX,
    avg, lerp,
    HandAnchorFilter, AdaptiveSmoother, SkeletonCalibrator,
    CameraSpaceXTracker, CameraSpaceYTracker,
    apply_camera_space_translation, apply_camera_space_y_translation, apply_slot_snap,
)
from sensor.person_lock import PersonLockController
from sensor.stereo_matcher import STEREO_MODE_DISABLED
from sensor.player_reid import (
    AppearanceSignature,
    _compare_hist_01,
    compute_signature_similarity,
    is_plausible_human_dancer,
    explain_plausibility_rejection,
    _pose_torso_geometry,
    suppress_duplicate_poses,
    extract_detection_features,
    compute_bbox_iou,
    LongTermIdentityProfile,
    MultiPlayerAssociator,
)


@dataclass
class PlayerFrame:
    """Tracking output for an individual player slot on a single video frame."""
    slot_index: int
    tracked: bool
    coasting: bool = False
    kinect_joints: Optional[List[Tuple[float, float, float, float]]] = None
    pixel_joints: Optional[List[Tuple[int, int, float]]] = None
    body_mask: Optional[np.ndarray] = None
    norm_landmarks: Any = None
    calibration_tier: str = "none"
    is_calibrated: bool = False
    center_z: float = 2.0


@dataclass
class MultiPoseFrame:
    """Unified multi-player tracking result for 1P and 2P modes."""
    players: List[Optional[PlayerFrame]] = field(default_factory=list)
    tracked_mask: int = 0
    player_index_mask: Optional[np.ndarray] = None
    active_count: int = 0

    @property
    def any_tracked(self) -> bool:
        return self.tracked_mask > 0

    @property
    def primary_player(self) -> Optional[PlayerFrame]:
        for p in self.players:
            if p is not None and p.tracked and p.kinect_joints:
                return p
        return None


class PlayerSlotState:
    """
    Independent per-player tracking pipeline state (Slot 0 = Player 1, Slot 1 = Player 2).
    Owns its own HandAnchorFilter, AdaptiveSmoother, SkeletonCalibrator, CameraSpaceXTracker,
    PersonLockController, temporal segmentation EMA, and LongTermIdentityProfile.
    """
    MASK_INTERNAL_W = 320
    MASK_INTERNAL_H = 240
    # Torso joints used for robust stereo baseline Z grounding (avoids fast-limb patch mismatches & cuts stereo CPU ~75%)
    _STEREO_TORSO_JOINTS = (0, 1, 2, 3, 4, 8, 12, 16)

    def __init__(
        self,
        slot_index: int,
        smoothing_alpha: float = 0.75,
        target_height_m: float = 1.75,
        cfg: Optional[Dict[str, Any]] = None,
    ):
        self.slot_index = int(slot_index)
        self.cfg = dict(cfg) if cfg else {}
        self.hand_filter = HandAnchorFilter(hand_length=0.12)
        self.smoother = AdaptiveSmoother(base_alpha=smoothing_alpha)
        self.calibrator = SkeletonCalibrator(target_height_m=target_height_m, cfg=self.cfg)
        self.camera_x_tracker = CameraSpaceXTracker(cfg=self.cfg)
        self.camera_y_tracker = CameraSpaceYTracker(cfg=self.cfg)
        self.person_lock = PersonLockController(cfg=self.cfg)
        self.identity_profile = LongTermIdentityProfile(slot_index=self.slot_index)
        self._seg_prob_ema: Optional[np.ndarray] = None
        self.last_norm_landmarks: Any = None
        self._warned_stereo_err: bool = False
        self._warned_seg_err: bool = False

    def reset(self, reset_identity: bool = True) -> None:
        self.calibrator.reset()
        self.smoother.reset()
        self.camera_x_tracker.reset()
        self.camera_y_tracker.reset()
        self.person_lock.reset()
        self._seg_prob_ema = None
        self.last_norm_landmarks = None
        if reset_identity:
            self.identity_profile.reset()

    def reset_transient(self) -> None:
        """Resets kinematic filters after dropout expiration while preserving long-term identity memory."""
        self.smoother.reset()
        self.camera_x_tracker.reset()
        self.camera_y_tracker.reset()
        self.person_lock.reset(preserve_identity=True)
        self._seg_prob_ema = None
        self.last_norm_landmarks = None
        self.identity_profile.mark_missing()

    def update_config(
        self,
        smoothing_alpha: Optional[float] = None,
        target_height_m: Optional[float] = None,
        cfg: Optional[Dict[str, Any]] = None,
    ) -> None:
        if cfg is not None:
            self.cfg.update(cfg)
            self.calibrator.cfg = self.cfg
            self.camera_x_tracker.cfg = self.cfg
            self.camera_y_tracker.cfg = self.cfg
            self.person_lock.update_config(self.cfg)
        if smoothing_alpha is not None:
            self.smoother.update_base_alpha(smoothing_alpha)
        if target_height_m is not None:
            self.calibrator.target_height_m = float(target_height_m)
            self.calibrator.reset()

    def handle_missing(
        self,
        dt: Optional[float],
        frame_w: int,
        frame_h: int,
        is_crowded: bool = False,
    ) -> Optional[PlayerFrame]:
        """
        Attempts inertial coasting during transient dropouts.
        During 2-player close overlap occlusions (`is_crowded=True`), extends coasting up to
        650 ms with stronger velocity damping (0.65) so a brief arm crossover never blinks a dancer out.
        """
        if is_crowded:
            is_coasting, c_3d, c_2d, c_mask = self.person_lock.coast(
                dt=dt,
                frame_w=frame_w,
                frame_h=frame_h,
                max_ms_override=650.0,
                damping_override=0.65,
            )
        else:
            is_coasting, c_3d, c_2d, c_mask = self.person_lock.coast(
                dt=dt, frame_w=frame_w, frame_h=frame_h
            )
        if is_coasting and c_3d and c_2d:
            cz = float(c_3d[0][2]) if len(c_3d) > 0 else 2.0
            return PlayerFrame(
                slot_index=self.slot_index,
                tracked=True,
                coasting=True,
                kinect_joints=c_3d,
                pixel_joints=c_2d,
                body_mask=c_mask,
                norm_landmarks=self.last_norm_landmarks,
                calibration_tier=self.calibrator.calibration_tier,
                is_calibrated=self.calibrator.is_calibrated,
                center_z=cz,
            )
        self.reset_transient()
        return None

    def process_detection(
        self,
        world_lm: Any,
        norm_lm: Any,
        seg_mask_obj: Any,
        frame_bgr: np.ndarray,
        frame_left: Optional[np.ndarray],
        stereo_engine: Any,
        stereo_mode: str,
        extract_joints_2d_fn: Callable,
        build_body_mask_fn: Callable,
        dt_infer: Optional[float],
        w: int,
        h: int,
        enforce_single_person_gate: bool = False,
        sample_bgr: Optional[np.ndarray] = None,
        primary_eye: str = "right",
        other_norm_lm: Any = None,
        is_crowded: bool = False,
    ) -> Optional[PlayerFrame]:
        """Runs the full 20-joint kinematic, calibration, smoothing, and mask pipeline for this slot."""
        if enforce_single_person_gate:
            gate_img = sample_bgr if sample_bgr is not None else frame_bgr
            if not self.person_lock.validate_candidate(gate_img, norm_lm, dt=dt_infer):
                return self.handle_missing(dt=dt_infer, frame_w=w, frame_h=h)

        self.last_norm_landmarks = norm_lm

        def get_joint(idx: int) -> Tuple[float, float, float, float]:
            wl = world_lm[idx]
            nl = norm_lm[idx]
            vis = getattr(nl, "visibility", 1.0)
            pres = getattr(nl, "presence", 1.0)
            conf = min(1.0, max(0.0, min(vis, pres)))
            return (float(wl.x), float(wl.y), float(wl.z), conf)

        def get_pixel(idx: int) -> Tuple[int, int, float]:
            nl = norm_lm[idx]
            px = int(nl.x * w)
            py = int(nl.y * h)
            vis = getattr(nl, "visibility", 1.0)
            pres = getattr(nl, "presence", 1.0)
            conf = min(1.0, max(0.0, min(vis, pres)))
            return (px, py, conf)

        # 1. Build Raw 20-Joint Kinect skeleton in world coordinates with Partial-Body Synthesis
        sh_l = get_joint(LEFT_SHOULDER)
        sh_r = get_joint(RIGHT_SHOULDER)
        sh_c = avg(sh_l, sh_r)
        sh_w = math.sqrt((sh_r[0] - sh_l[0]) ** 2 + (sh_r[1] - sh_l[1]) ** 2 + (sh_r[2] - sh_l[2]) ** 2)
        sh_w = max(0.28, min(0.65, sh_w))

        ear_center = avg(get_joint(LEFT_EAR), get_joint(RIGHT_EAR))
        nose = get_joint(NOSE)
        head = avg(ear_center, nose)

        raw_hip_l = get_joint(LEFT_HIP)
        raw_hip_r = get_joint(RIGHT_HIP)
        hips_visible = (raw_hip_l[3] >= 0.25 and raw_hip_r[3] >= 0.25)
        torso_len = max(0.38, sh_w * 1.35)

        if hips_visible:
            hip_l = raw_hip_l
            hip_r = raw_hip_r
            hip_center = avg(hip_l, hip_r)
        else:
            syn_hip_y = sh_c[1] + torso_len
            syn_conf = max(0.48, min(sh_l[3], sh_r[3]) * 0.85)
            hip_center = (sh_c[0], syn_hip_y, sh_c[2], syn_conf)
            lat_sign = 1.0 if (sh_l[0] - sh_r[0]) >= 0.0 else -1.0
            hip_half_w = sh_w * 0.38
            hip_l = (hip_center[0] + lat_sign * hip_half_w, syn_hip_y, hip_center[2], syn_conf)
            hip_r = (hip_center[0] - lat_sign * hip_half_w, syn_hip_y, hip_center[2], syn_conf)

        spine = lerp(hip_center, sh_c, 0.52)

        def get_palm_joint(idx_index: int, idx_pinky: int) -> Tuple[float, float, float, float]:
            """Synthesizes Kinect-aligned palm center from INDEX + PINKY landmarks (cuts hand jitter ~30%)."""
            j_idx = get_joint(idx_index)
            if idx_pinky < len(world_lm) and idx_pinky < len(norm_lm):
                j_pnk = get_joint(idx_pinky)
                if j_idx[3] >= 0.25 and j_pnk[3] >= 0.25:
                    w_sum = j_idx[3] + j_pnk[3]
                    wi = j_idx[3] / w_sum
                    wp = j_pnk[3] / w_sum
                    return (
                        j_idx[0] * wi + j_pnk[0] * wp,
                        j_idx[1] * wi + j_pnk[1] * wp,
                        j_idx[2] * wi + j_pnk[2] * wp,
                        max(j_idx[3], j_pnk[3]),
                    )
                if j_pnk[3] > j_idx[3]:
                    return j_pnk
            return j_idx

        def get_palm_pixel(idx_index: int, idx_pinky: int) -> Tuple[int, int, float]:
            p_idx = get_pixel(idx_index)
            if idx_pinky < len(norm_lm):
                p_pnk = get_pixel(idx_pinky)
                if p_idx[2] >= 0.25 and p_pnk[2] >= 0.25:
                    w_sum = p_idx[2] + p_pnk[2]
                    wi = p_idx[2] / w_sum
                    wp = p_pnk[2] / w_sum
                    return (
                        int(round(p_idx[0] * wi + p_pnk[0] * wp)),
                        int(round(p_idx[1] * wi + p_pnk[1] * wp)),
                        max(p_idx[2], p_pnk[2]),
                    )
                if p_pnk[2] > p_idx[2]:
                    return p_pnk
            return p_idx

        raw_ank_l = get_joint(LEFT_ANKLE)
        raw_ank_r = get_joint(RIGHT_ANKLE)
        raw_knee_l = get_joint(LEFT_KNEE)
        raw_knee_r = get_joint(RIGHT_KNEE)
        left_leg_visible = raw_ank_l[3] >= 0.25
        right_leg_visible = raw_ank_r[3] >= 0.25
        legs_visible = left_leg_visible and right_leg_visible

        thigh_len = torso_len * 1.05
        calf_len = torso_len * 1.00
        syn_leg_conf = 0.35

        # Independent per-leg & per-segment synthesis: a single occluded ankle (e.g., kick or turn)
        # never wipes out the opposite visible leg or a visible knee.
        if left_leg_visible:
            knee_l = raw_knee_l
            ank_l = raw_ank_l
            foot_l = get_joint(LEFT_FOOT_INDEX)
        elif raw_knee_l[3] >= 0.25:
            knee_l = raw_knee_l
            ank_l = (knee_l[0], knee_l[1] + calf_len, knee_l[2], syn_leg_conf)
            foot_l = (knee_l[0], knee_l[1] + calf_len + 0.05, knee_l[2] - 0.12, syn_leg_conf)
        else:
            knee_l = (hip_l[0], hip_l[1] + thigh_len, hip_l[2], syn_leg_conf)
            ank_l = (hip_l[0], hip_l[1] + thigh_len + calf_len, hip_l[2], syn_leg_conf)
            foot_l = (hip_l[0], hip_l[1] + thigh_len + calf_len + 0.05, hip_l[2] - 0.12, syn_leg_conf)

        if right_leg_visible:
            knee_r = raw_knee_r
            ank_r = raw_ank_r
            foot_r = get_joint(RIGHT_FOOT_INDEX)
        elif raw_knee_r[3] >= 0.25:
            knee_r = raw_knee_r
            ank_r = (knee_r[0], knee_r[1] + calf_len, knee_r[2], syn_leg_conf)
            foot_r = (knee_r[0], knee_r[1] + calf_len + 0.05, knee_r[2] - 0.12, syn_leg_conf)
        else:
            knee_r = (hip_r[0], hip_r[1] + thigh_len, hip_r[2], syn_leg_conf)
            ank_r = (hip_r[0], hip_r[1] + thigh_len + calf_len, hip_r[2], syn_leg_conf)
            foot_r = (hip_r[0], hip_r[1] + thigh_len + calf_len + 0.05, hip_r[2] - 0.12, syn_leg_conf)

        raw_kinect = [
            hip_center,
            spine,
            sh_c,
            head,
            sh_l,
            get_joint(LEFT_ELBOW),
            get_joint(LEFT_WRIST),
            get_palm_joint(LEFT_INDEX, LEFT_PINKY),
            sh_r,
            get_joint(RIGHT_ELBOW),
            get_joint(RIGHT_WRIST),
            get_palm_joint(RIGHT_INDEX, RIGHT_PINKY),
            hip_l,
            knee_l,
            ank_l,
            foot_l,
            hip_r,
            knee_r,
            ank_r,
            foot_r,
        ]

        # 2. Hand Anchor Filter
        anchored = self.hand_filter.apply(raw_kinect)

        # 3. Auto-calibrate height and origin (+ gentle upright scale refinement over first ~30 frames)
        ankles_in_frame = (
            legs_visible
            and raw_ank_l[3] >= 0.50
            and raw_ank_r[3] >= 0.50
            and float(norm_lm[LEFT_ANKLE].y) <= 0.96
            and float(norm_lm[RIGHT_ANKLE].y) <= 0.96
        )
        if not self.calibrator.is_calibrated or (self.calibrator.calibration_tier != "full_body" and ankles_in_frame):
            self.calibrator.calibrate(anchored, legs_visible=ankles_in_frame, hips_visible=hips_visible)
        elif ankles_in_frame:
            self.calibrator.refine_full_body_scale(anchored)

        # 3.1 Stereo Triangulation (automatic on PS4 Camera dual sensor; torso-only for robust room Z & 4x less CPU)
        stereo_depths = None
        if stereo_mode != STEREO_MODE_DISABLED and frame_left is not None and stereo_engine is not None:
            try:
                mono_pri = frame_bgr[:, :, 1] if (frame_left.ndim == 2 and frame_bgr.ndim == 3) else frame_bgr
                if str(primary_eye or "right").strip().lower() == "left":
                    rect_left_frame, rect_right_frame = stereo_engine.calibrator.rectify(mono_pri, frame_left)
                else:
                    rect_left_frame, rect_right_frame = stereo_engine.calibrator.rectify(frame_left, mono_pri)
                joints_2d_all = extract_joints_2d_fn(norm_lm, w, h)
                joints_2d_torso = {
                    j_id: joints_2d_all[j_id]
                    for j_id in self._STEREO_TORSO_JOINTS
                    if j_id in joints_2d_all
                }
                stereo_depths = stereo_engine.triangulate_sparse_joints(
                    rect_left_frame, rect_right_frame, joints_2d_torso, primary_eye=primary_eye
                )
            except Exception as exc:
                if not self._warned_stereo_err:
                    print(f"[WARN] Stereo triangulation fallback to mono: {exc}")
                    self._warned_stereo_err = True
                stereo_depths = None

        # 4. Transform to Kinect v1 camera coordinate space
        kinect_space = self.calibrator.transform(anchored, stereo_depths=stereo_depths)

        # 4.1 Smooth anatomical gestures
        smoothed_kinect = self.smoother.apply(kinect_space, dt=dt_infer)

        # 4.2 Apply lateral camera-space translation for dancer slot selection
        translated = apply_camera_space_translation(
            smoothed_kinect, norm_lm, self.camera_x_tracker, self.cfg, dt=dt_infer
        )

        # 4.3 Apply C0-continuous slot snap
        snapped = apply_slot_snap(translated, self.cfg)

        # 4.4 Apply vertical squat/bounce/jump camera-space translation
        snapped = apply_camera_space_y_translation(
            snapped, norm_lm, self.camera_y_tracker, self.cfg, dt=dt_infer
        )

        # 5. Build 2D pixel coordinates for preview drawing
        px_sh_l = get_pixel(LEFT_SHOULDER)
        px_sh_r = get_pixel(RIGHT_SHOULDER)
        px_sh_c = (
            int((px_sh_l[0] + px_sh_r[0]) * 0.5),
            int((px_sh_l[1] + px_sh_r[1]) * 0.5),
            min(px_sh_l[2], px_sh_r[2]),
        )
        sh_w_px = max(20, int(math.hypot(px_sh_r[0] - px_sh_l[0], px_sh_r[1] - px_sh_l[1])))

        if hips_visible:
            px_hip_l = get_pixel(LEFT_HIP)
            px_hip_r = get_pixel(RIGHT_HIP)
            px_hip_c = (
                int((px_hip_l[0] + px_hip_r[0]) * 0.5),
                int((px_hip_l[1] + px_hip_r[1]) * 0.5),
                min(px_hip_l[2], px_hip_r[2]),
            )
        else:
            syn_px_y = min(h - 2, int(px_sh_c[1] + sh_w_px * 1.35))
            px_hip_c = (px_sh_c[0], syn_px_y, px_sh_c[2])
            px_lat_sign = 1 if (px_sh_l[0] - px_sh_r[0]) >= 0 else -1
            px_hip_half = int(sh_w_px * 0.38)
            px_hip_l = (max(0, min(w - 1, px_hip_c[0] + px_lat_sign * px_hip_half)), syn_px_y, px_sh_c[2])
            px_hip_r = (max(0, min(w - 1, px_hip_c[0] - px_lat_sign * px_hip_half)), syn_px_y, px_sh_c[2])

        px_spine = (
            int(px_hip_c[0] + 0.52 * (px_sh_c[0] - px_hip_c[0])),
            int(px_hip_c[1] + 0.52 * (px_sh_c[1] - px_hip_c[1])),
            px_sh_c[2],
        )
        px_nose = get_pixel(NOSE)

        thigh_px = int(sh_w_px * 1.4)
        calf_px = int(sh_w_px * 1.3)
        if left_leg_visible:
            px_knee_l = get_pixel(LEFT_KNEE)
            px_ank_l = get_pixel(LEFT_ANKLE)
            px_foot_l = get_pixel(LEFT_FOOT_INDEX)
        elif raw_knee_l[3] >= 0.25:
            px_knee_l = get_pixel(LEFT_KNEE)
            px_ank_l = (px_knee_l[0], min(h - 2, px_knee_l[1] + calf_px), 0.35)
            px_foot_l = (px_knee_l[0], min(h - 2, px_knee_l[1] + calf_px + 10), 0.35)
        else:
            px_knee_l = (px_hip_l[0], min(h - 2, px_hip_l[1] + thigh_px), 0.35)
            px_ank_l = (px_hip_l[0], min(h - 2, px_hip_l[1] + thigh_px + calf_px), 0.35)
            px_foot_l = (px_hip_l[0], min(h - 2, px_hip_l[1] + thigh_px + calf_px + 10), 0.35)

        if right_leg_visible:
            px_knee_r = get_pixel(RIGHT_KNEE)
            px_ank_r = get_pixel(RIGHT_ANKLE)
            px_foot_r = get_pixel(RIGHT_FOOT_INDEX)
        elif raw_knee_r[3] >= 0.25:
            px_knee_r = get_pixel(RIGHT_KNEE)
            px_ank_r = (px_knee_r[0], min(h - 2, px_knee_r[1] + calf_px), 0.35)
            px_foot_r = (px_knee_r[0], min(h - 2, px_knee_r[1] + calf_px + 10), 0.35)
        else:
            px_knee_r = (px_hip_r[0], min(h - 2, px_hip_r[1] + thigh_px), 0.35)
            px_ank_r = (px_hip_r[0], min(h - 2, px_hip_r[1] + thigh_px + calf_px), 0.35)
            px_foot_r = (px_hip_r[0], min(h - 2, px_hip_r[1] + thigh_px + calf_px + 10), 0.35)

        pixel_joints = [
            px_hip_c,
            px_spine,
            px_sh_c,
            px_nose,
            px_sh_l,
            get_pixel(LEFT_ELBOW),
            get_pixel(LEFT_WRIST),
            get_palm_pixel(LEFT_INDEX, LEFT_PINKY),
            px_sh_r,
            get_pixel(RIGHT_ELBOW),
            get_pixel(RIGHT_WRIST),
            get_palm_pixel(RIGHT_INDEX, RIGHT_PINKY),
            px_hip_l,
            px_knee_l,
            px_ank_l,
            px_foot_l,
            px_hip_r,
            px_knee_r,
            px_ank_r,
            px_foot_r,
        ]

        pixel_joints = self.hand_filter.apply_pixel(pixel_joints)
        pixel_joints = self.smoother.apply_pixel(pixel_joints, frame_w=w, frame_h=h, dt=dt_infer)

        # 6. Build 320x240 player silhouette mask (Exact Neural Cutout; Anatomical fallback only if neural missing)
        mw, mh = self.MASK_INTERNAL_W, self.MASK_INTERNAL_H
        body_mask = self._build_exact_player_mask(
            seg_mask_obj=seg_mask_obj,
            norm_lm=norm_lm,
            mw=mw,
            mh=mh,
            build_body_mask_fn=build_body_mask_fn,
            other_norm_lm=other_norm_lm,
            is_crowded=is_crowded,
        )

        snapped, pixel_joints, body_mask = self.person_lock.record_valid_frame(
            snapped, pixel_joints, body_mask, norm_landmarks=norm_lm, dt=dt_infer
        )

        cz = float(snapped[0][2]) if len(snapped) > 0 else 2.0
        return PlayerFrame(
            slot_index=self.slot_index,
            tracked=True,
            coasting=False,
            kinect_joints=snapped,
            pixel_joints=pixel_joints,
            body_mask=body_mask,
            norm_landmarks=norm_lm,
            calibration_tier=self.calibrator.calibration_tier,
            is_calibrated=self.calibrator.is_calibrated,
            center_z=cz,
        )

    _ELLIPSE_3X3 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    _ELLIPSE_15X15 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))

    def _build_exact_player_mask(
        self,
        seg_mask_obj: Any,
        norm_lm: Any,
        mw: int,
        mh: int,
        build_body_mask_fn: Callable,
        other_norm_lm: Any = None,
        is_crowded: bool = False,
    ) -> np.ndarray:
        """
        Produces a tight, true-to-life 320x240 player silhouette directly from MediaPipe's
        neural segmentation tensor:
          1. Squeezes (H, W, 1) -> (H, W) float32 and resizes linearly to 320x240.
          2. Applies fast light temporal EMA (0.80 new / 0.20 prev) to suppress single-frame grain
             without creating motion ghost trails behind fast-moving arms.
          3. Applies a light 3x3 Gaussian blur on the probability map and thresholds at 0.36
             to keep hair, clothes, and limbs crisp without bloated edges.
          4. Keeps only connected components anchored to this dancer's visible landmarks so stray
             background objects are removed without clipping hair, clothes, or outstretched hands.
          5. In 2-player crowded mode (`is_crowded` and `other_norm_lm` present), isolates merged
             neural segmentation blobs so one player's silhouette never swallows the other dancer.
          6. Only falls back to `build_body_mask_fn` when neural segmentation is unavailable/empty.
        """
        neural_mask = None
        if seg_mask_obj is not None:
            try:
                seg_view = seg_mask_obj.numpy_view()
                if seg_view.ndim == 3:
                    seg_view = seg_view[:, :, 0]
                if seg_view.shape[0] != mh or seg_view.shape[1] != mw:
                    prob_small = cv2.resize(seg_view, (mw, mh), interpolation=cv2.INTER_LINEAR)
                else:
                    prob_small = seg_view.astype(np.float32, copy=False)

                if self._seg_prob_ema is None or self._seg_prob_ema.shape != prob_small.shape:
                    self._seg_prob_ema = prob_small.astype(np.float32, copy=True)
                else:
                    cv2.addWeighted(prob_small, 0.80, self._seg_prob_ema, 0.20, 0.0, dst=self._seg_prob_ema)

                smooth_prob = cv2.GaussianBlur(self._seg_prob_ema, (3, 3), 0)
                raw_bin = (smooth_prob >= 0.36).astype(np.uint8) * 255

                raw_bin = cv2.morphologyEx(raw_bin, cv2.MORPH_OPEN, self._ELLIPSE_3X3)
                raw_bin = cv2.morphologyEx(raw_bin, cv2.MORPH_CLOSE, self._ELLIPSE_3X3)

                num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(raw_bin, connectivity=8)
                if num_labels > 1:
                    anchor_labels = set()
                    if norm_lm is not None:
                        for lm in norm_lm:
                            vis = float(getattr(lm, "visibility", 1.0))
                            pres = float(getattr(lm, "presence", 1.0))
                            if min(vis, pres) < 0.25:
                                continue
                            lx = int(round(float(lm.x) * (mw - 1)))
                            ly = int(round(float(lm.y) * (mh - 1)))
                            if 0 <= lx < mw and 0 <= ly < mh:
                                y0, y1 = max(0, ly - 4), min(mh, ly + 5)
                                x0, x1 = max(0, lx - 4), min(mw, lx + 5)
                                patch = labels[y0:y1, x0:x1]
                                for lbl in np.unique(patch):
                                    if lbl > 0 and stats[lbl, cv2.CC_STAT_AREA] >= 12:
                                        anchor_labels.add(int(lbl))

                    if anchor_labels:
                        filtered = np.zeros((mh, mw), dtype=np.uint8)
                        for lbl in anchor_labels:
                            filtered[labels == lbl] = 255
                        neural_mask = filtered
                    else:
                        areas = stats[1:, cv2.CC_STAT_AREA]
                        best_lbl = int(np.argmax(areas)) + 1
                        if int(areas[best_lbl - 1]) >= 60:
                            neural_mask = np.where(labels == best_lbl, np.uint8(255), np.uint8(0))

                my_anat_cache = None
                if neural_mask is not None and norm_lm is not None:
                    nz_ys = np.nonzero(neural_mask)[0]
                    if nz_ys.size >= 60:
                        ny_min = int(nz_ys.min())
                        ny_max = int(nz_ys.max())
                        ext_ys = []
                        for j_idx in (
                            NOSE, LEFT_ELBOW, RIGHT_ELBOW, LEFT_WRIST, RIGHT_WRIST,
                            LEFT_INDEX, RIGHT_INDEX, LEFT_KNEE, RIGHT_KNEE,
                            LEFT_ANKLE, RIGHT_ANKLE, LEFT_FOOT_INDEX, RIGHT_FOOT_INDEX,
                        ):
                            if j_idx < len(norm_lm):
                                lm = norm_lm[j_idx]
                                if float(getattr(lm, "visibility", 1.0)) >= 0.30:
                                    ly_f = float(lm.y)
                                    if 0.0 <= ly_f <= 1.0:
                                        ext_ys.append(int(round(ly_f * (mh - 1))))
                        if ext_ys:
                            nose_lm = norm_lm[NOSE] if len(norm_lm) > NOSE else None
                            lm_top = min(ext_ys)
                            if nose_lm is not None and float(getattr(nose_lm, "visibility", 1.0)) >= 0.30:
                                sh_l_lm = norm_lm[LEFT_SHOULDER]
                                sh_r_lm = norm_lm[RIGHT_SHOULDER]
                                sh_px = max(12.0, math.hypot(
                                    (float(sh_r_lm.x) - float(sh_l_lm.x)) * mw,
                                    (float(sh_r_lm.y) - float(sh_l_lm.y)) * mh,
                                ))
                                head_top = max(0, int(round(float(nose_lm.y) * (mh - 1) - sh_px * 0.42)))
                                lm_top = min(lm_top, head_top)
                            lm_bot = max(ext_ys)

                            need_top = (ny_min > 1 and lm_top < ny_min - 2)
                            need_bot = (ny_max < mh - 2 and lm_bot > ny_max + 2)
                            if need_top or need_bot:
                                my_anat_cache = build_body_mask_fn(norm_lm, mw, mh)
                                if my_anat_cache is not None:
                                    if need_top:
                                        cut_top = min(mh, ny_min + 3)
                                        neural_mask[:cut_top, :] = cv2.bitwise_or(
                                            neural_mask[:cut_top, :], my_anat_cache[:cut_top, :]
                                        )
                                    if need_bot:
                                        cut_bot = max(0, ny_max - 3)
                                        neural_mask[cut_bot:, :] = cv2.bitwise_or(
                                            neural_mask[cut_bot:, :], my_anat_cache[cut_bot:, :]
                                        )

                # 2P Anti-Swallow Isolation: when two dancers touch/overlap (is_crowded=True), MediaPipe's
                # neural segmentation can merge both bodies into one connected component. Carve out pixels
                # that belong exclusively to the other player's anatomical envelope and lie outside ours.
                if is_crowded and neural_mask is not None and other_norm_lm is not None and norm_lm is not None:
                    my_anat = my_anat_cache if my_anat_cache is not None else build_body_mask_fn(norm_lm, mw, mh)
                    other_anat = build_body_mask_fn(other_norm_lm, mw, mh)
                    if my_anat is not None and other_anat is not None:
                        my_keep = cv2.dilate(my_anat, self._ELLIPSE_15X15, iterations=1)
                        stolen = (other_anat >= 64) & (my_keep < 64)
                        if np.any(stolen):
                            neural_mask[stolen] = 0
            except Exception as exc:
                if not self._warned_seg_err:
                    print(f"[WARN] Neural segmentation mask fallback to anatomical mask: {exc}")
                    self._warned_seg_err = True
                neural_mask = None

        if neural_mask is not None and int(np.count_nonzero(neural_mask)) >= 60:
            return neural_mask

        return build_body_mask_fn(norm_lm, mw, mh)


def compose_player_index_mask(
    players: List[Optional[PlayerFrame]],
    width: int = 320,
    height: int = 240,
) -> Optional[np.ndarray]:
    """
    Composes a single 320x240 uint8 player index mask for Kinect JMI2 shared memory:
      - 0 = Background
      - 1 = Player 1 (Slot 0)
      - 2 = Player 2 (Slot 1)
    When both players overlap, the player closer to the camera (smaller `center_z`) overwrites the farther one.
    """
    active = [p for p in players if p is not None and p.tracked and p.body_mask is not None]
    if not active:
        return None

    combined = np.zeros((height, width), dtype=np.uint8)
    ordered = sorted(active, key=lambda p: float(p.center_z), reverse=True)
    for p in ordered:
        p_idx = int(p.slot_index) + 1  # 1 for Slot 0, 2 for Slot 1
        m = p.body_mask
        if m.shape[0] != height or m.shape[1] != width:
            m = cv2.resize(m, (width, height), interpolation=cv2.INTER_NEAREST)
        combined[m >= 64] = p_idx

    return combined


__all__ = [
    "AppearanceSignature",
    "_compare_hist_01",
    "compute_signature_similarity",
    "is_plausible_human_dancer",
    "explain_plausibility_rejection",
    "_pose_torso_geometry",
    "suppress_duplicate_poses",
    "extract_detection_features",
    "compute_bbox_iou",
    "LongTermIdentityProfile",
    "MultiPlayerAssociator",
    "PlayerFrame",
    "MultiPoseFrame",
    "PlayerSlotState",
    "compose_player_index_mask",
]
