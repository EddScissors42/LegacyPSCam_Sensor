"""
Pose Tracking Engine for Legacy PSCam Sensor.
Uses MediaPipe Pose Tasks API with custom Hand Anchor Filtering,
Adaptive Dynamic EMA Smoothing, Height Normalization, 20-joint Kinect v1 mapping,
and Multi-Player (1P/2P) Long-Term Identity Memory (Anti-Swap Re-ID).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import List, Optional
import numpy as np
import cv2

# Lightweight matplotlib mock for MediaPipe drawing_utils when excluded in binary
if "matplotlib" not in sys.modules:
    import types

    _m = types.ModuleType("matplotlib")
    _plt = types.ModuleType("matplotlib.pyplot")
    _m.pyplot = _plt
    sys.modules["matplotlib"] = _m
    sys.modules["matplotlib.pyplot"] = _plt

import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

from sensor.body_mask import (
    MORPH_KERNEL_SMALL,
    MORPH_KERNEL_LARGE,
    extract_joints_2d,
    build_body_mask as _build_body_mask_geom,
)
from sensor.pose_filters import (
    NOSE, LEFT_EYE_INNER, LEFT_EYE, LEFT_EYE_OUTER,
    RIGHT_EYE_INNER, RIGHT_EYE, RIGHT_EYE_OUTER,
    LEFT_EAR, RIGHT_EAR, MOUTH_LEFT, MOUTH_RIGHT,
    LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_ELBOW, RIGHT_ELBOW,
    LEFT_WRIST, RIGHT_WRIST, LEFT_PINKY, RIGHT_PINKY,
    LEFT_INDEX, RIGHT_INDEX, LEFT_THUMB, RIGHT_THUMB,
    LEFT_HIP, RIGHT_HIP, LEFT_KNEE, RIGHT_KNEE,
    LEFT_ANKLE, RIGHT_ANKLE, LEFT_HEEL, RIGHT_HEEL,
    LEFT_FOOT_INDEX, RIGHT_FOOT_INDEX,
    KINECT_CONNECTIONS, EXTREMITY_JOINTS, avg, lerp,
    HandAnchorFilter, AdaptiveSmoother, SkeletonCalibrator,
    CameraSpaceXTracker, apply_camera_space_translation,
    apply_slot_snap, FaceFollowPTZ,
)
from sensor.stereo_matcher import (
    StereoDepthEngine,
    STEREO_MODE_DISABLED,
    STEREO_MODE_SPARSE_METRIC,
    STEREO_MODE_FULL_DEPTH,
    PS4_STEREO_BASELINE_M,
)
from sensor.person_lock import (
    InertialCoastingFilter,
    DancerIdentityLock,
    PersonLockController,
)
from sensor.player_slot import (
    PlayerFrame,
    MultiPoseFrame,
    PlayerSlotState,
    MultiPlayerAssociator,
    compose_player_index_mask,
    is_plausible_human_dancer,
    explain_plausibility_rejection,
    suppress_duplicate_poses,
)
from sensor.session_logger import get_session_logger
from sensor.model_manager import ModelManager, MODEL_FILENAMES


def _resolve_model_path(model_variant: str = "lite", auto_download: bool = True) -> Path:
    """
    Resolves a MediaPipe Pose Landmarker `.task` file using ModelManager:
    checks `%APPDATA%\\LegacyPSCam_Sensor\\models`, bundled `_MEIPASS/models` (Lite),
    and local `models/`, downloading Full AI on demand when needed.
    """
    return ModelManager.ensure_model(model_variant, auto_download=auto_download)


DEFAULT_MODEL_PATH = ModelManager.locate_model("lite") or ModelManager.get_cached_model_path("lite")


class PoseTracker:
    """
    High-level Pose Tracking Engine wrapping MediaPipe Pose Tasks API,
    supporting 1 or 2 simultaneous players with per-slot kinematic filters
    and long-term visual re-identification across crossovers and waltz turns.
    """

    # Native Kinect player segmentation mask resolution (320x240)
    MASK_INTERNAL_W = 320
    MASK_INTERNAL_H = 240
    # Maximum width fed into MediaPipe RGB conversion & segmentation tensor (aspect-preserving)
    INFER_MAX_W = 640
    INFER_MAX_W_2P = 640
    _MORPH_KERNEL_SMALL = MORPH_KERNEL_SMALL
    _MORPH_KERNEL_LARGE = MORPH_KERNEL_LARGE

    _extract_joints_2d = staticmethod(extract_joints_2d)

    def __init__(
        self,
        model_path=None,
        detection_confidence=0.45,
        smoothing_alpha=0.75,
        target_height_m=1.75,
        cfg=None,
        model_variant=None,
        max_players=None,
    ):
        self.cfg = dict(cfg) if cfg else {}
        variant = str(model_variant or self.cfg.get("pose_model", "lite")).strip().lower()
        if variant == "heavy":
            variant = "full"
        if variant not in MODEL_FILENAMES:
            variant = "lite"
        self.model_variant = variant
        self.model_path = Path(model_path) if model_path else _resolve_model_path(variant)
        if not self.model_path.exists():
            raise FileNotFoundError(f"Modelo do MediaPipe não encontrado: {self.model_path}")

        raw_mp = max_players if max_players is not None else self.cfg.get("max_players", 1)
        self.max_players = max(1, min(2, int(raw_mp)))
        self.detection_confidence = float(detection_confidence)
        self.smoothing_alpha = float(smoothing_alpha)
        self.target_height_m = float(target_height_m)

        self.detector = None
        self._init_detector()

        self.slots = [
            PlayerSlotState(
                slot_index=i,
                smoothing_alpha=self.smoothing_alpha,
                target_height_m=self.target_height_m,
                cfg=self.cfg,
            )
            for i in range(2)
        ]
        self.associator = MultiPlayerAssociator(max_players=self.max_players)
        self.face_ptz = FaceFollowPTZ(cfg=self.cfg)
        self.stereo_mode = str(self.cfg.get("stereo_mode", STEREO_MODE_SPARSE_METRIC)).strip().lower()
        self.stereo_engine = StereoDepthEngine(baseline_m=PS4_STEREO_BASELINE_M)

        self.start_time = time.time()
        self._start_perf = time.perf_counter()
        self.frame_index = 0
        self.last_timestamp_ms = 0
        self.last_infer_perf = None
        self._infer_bgr = None
        self._infer_rgb = None

    # --- Backwards-compatible properties delegating to Slot 0 (Player 1) ---
    @property
    def hand_filter(self) -> HandAnchorFilter:
        return self.slots[0].hand_filter

    @property
    def smoother(self) -> AdaptiveSmoother:
        return self.slots[0].smoother

    @property
    def calibrator(self) -> SkeletonCalibrator:
        return self.slots[0].calibrator

    @property
    def camera_x_tracker(self) -> CameraSpaceXTracker:
        return self.slots[0].camera_x_tracker

    @property
    def person_lock(self) -> PersonLockController:
        return self.slots[0].person_lock

    @property
    def coasting_filter(self) -> InertialCoastingFilter:
        return self.slots[0].person_lock.coasting

    @property
    def identity_lock(self) -> DancerIdentityLock:
        return self.slots[0].person_lock.identity

    @property
    def last_norm_landmarks(self):
        return self.slots[0].last_norm_landmarks

    @last_norm_landmarks.setter
    def last_norm_landmarks(self, val):
        self.slots[0].last_norm_landmarks = val

    def _init_detector(self):
        base_options = python.BaseOptions(model_asset_path=str(self.model_path))
        if self.max_players >= 2:
            # 2-Player mode: slightly more forgiving detection/presence/tracking thresholds so
            # overlapping arms/shoulders during duo interactions don't drop a dancer instantaneously,
            # while num_poses=3 (2 players + 1 spare for Pose NMS) trims ~25% worst-case CPU cost vs 4.
            det_c = max(0.40, min(0.65, float(self.detection_confidence)))
            pres_c = max(0.28, min(0.50, det_c * 0.72))
            track_c = max(0.22, min(0.42, det_c * 0.58))
            detector_num_poses = 3
        else:
            # 1-Player mode: keep detection clean (avoids background hallucinations) and presence/tracking
            # balanced so low-confidence twisted limb artifacts never corrupt Just Dance beat scoring.
            det_c = max(0.45, min(0.68, float(self.detection_confidence)))
            pres_c = max(0.32, min(0.54, det_c * 0.72))
            track_c = max(0.25, min(0.46, det_c * 0.56))
            detector_num_poses = 1
        options = vision.PoseLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.VIDEO,
            num_poses=detector_num_poses,
            min_pose_detection_confidence=det_c,
            min_pose_presence_confidence=pres_c,
            min_tracking_confidence=track_c,
            output_segmentation_masks=True,
        )
        self.detector = vision.PoseLandmarker.create_from_options(options)
        print(
            f"[TRACKER] MediaPipe Pose Landmarker ({self.model_variant}) initialized "
            f"(model={self.model_path.name}, num_poses={detector_num_poses}, det={det_c:.2f}, pres={pres_c:.2f}, track={track_c:.2f})."
        )

    def update_settings(
        self,
        smoothing_alpha=None,
        detection_confidence=None,
        target_height_m=None,
        cfg=None,
        max_players=None,
    ):
        reinit_needed = False
        if cfg is not None:
            self.cfg.update(cfg)
            self.face_ptz.cfg = self.cfg
            if "stereo_mode" in self.cfg:
                self.stereo_mode = str(self.cfg.get("stereo_mode", STEREO_MODE_SPARSE_METRIC)).strip().lower()
            if max_players is None and "max_players" in cfg:
                max_players = cfg["max_players"]

        if max_players is not None:
            new_mp = max(1, min(2, int(max_players)))
            if new_mp != self.max_players:
                self.max_players = new_mp
                self.associator.max_players = new_mp
                reinit_needed = True

        if smoothing_alpha is not None:
            self.smoothing_alpha = float(smoothing_alpha)
        if target_height_m is not None:
            self.target_height_m = float(target_height_m)

        for slot in self.slots:
            slot.update_config(
                smoothing_alpha=smoothing_alpha,
                target_height_m=target_height_m,
                cfg=self.cfg if cfg is not None else None,
            )

        if detection_confidence is not None and abs(self.detection_confidence - detection_confidence) > 0.02:
            self.detection_confidence = float(detection_confidence)
            reinit_needed = True

        if reinit_needed:
            self.close()
            self._init_detector()

    def recalibrate(self):
        for slot in self.slots:
            slot.reset(reset_identity=True)
        self.associator.reset()
        self.face_ptz.reset()
        self.stereo_engine.reset_calibration()

    def build_body_mask(self, norm_landmarks, width: int, height: int) -> np.ndarray:
        """Builds an anatomical silhouette mask from 33 MediaPipe pose landmarks."""
        return _build_body_mask_geom(norm_landmarks, width, height)

    # ------------------------------------------------------------------
    # Frame Pipeline Helpers (called per frame in process_frame_multi)
    # ------------------------------------------------------------------
    @staticmethod
    def _unpack_frame_input(frame_bgr, frame_left):
        """Normalizes dict/tuple/ndarray stereo inputs into (frame_bgr, frame_left)."""
        if isinstance(frame_bgr, dict):
            if frame_left is None:
                frame_left = frame_bgr.get("left_bgr")
            frame_bgr = frame_bgr.get("right_bgr")
        elif isinstance(frame_bgr, (tuple, list)) and len(frame_bgr) == 2:
            if frame_left is None:
                frame_left = frame_bgr[1]
            frame_bgr = frame_bgr[0]
        return frame_bgr, frame_left

    def _prepare_inference_buffer(self, frame_bgr):
        """
        Pre-downscales raw (un-mirrored) BGR frame into pre-allocated RGB buffer for MediaPipe
        and applies peripheral ROI attenuation in 1P mode. Returns sample_bgr for appearance sampling.
        """
        h, w = frame_bgr.shape[:2]
        max_infer_w = (
            int(self.cfg.get("infer_max_w_2p", self.INFER_MAX_W_2P))
            if self.max_players >= 2
            else self.INFER_MAX_W
        )

        if w > max_infer_w:
            infer_w = max_infer_w
            infer_h = max(180, (int(round(h * (infer_w / float(w)))) // 2) * 2)
            if self._infer_bgr is None or self._infer_bgr.shape[:2] != (infer_h, infer_w):
                self._infer_bgr = np.empty((infer_h, infer_w, 3), dtype=np.uint8)
                self._infer_rgb = np.empty((infer_h, infer_w, 3), dtype=np.uint8)
            cv2.resize(frame_bgr, (infer_w, infer_h), dst=self._infer_bgr, interpolation=cv2.INTER_LINEAR)
            cv2.cvtColor(self._infer_bgr, cv2.COLOR_BGR2RGB, dst=self._infer_rgb)
            sample_bgr = self._infer_bgr
        else:
            if self._infer_rgb is None or self._infer_rgb.shape[:2] != (h, w):
                self._infer_rgb = np.empty((h, w, 3), dtype=np.uint8)
            cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB, dst=self._infer_rgb)
            sample_bgr = frame_bgr

        # Peripheral ROI attenuation is ONLY applied in 1-Player mode so Player 2 is never darkened
        if self.max_players == 1:
            self.slots[0].person_lock.apply_pre_inference_roi(self._infer_rgb)

        return sample_bgr

    def _next_monotonic_timestamp(self) -> tuple[int, Optional[float], float]:
        """Advances strictly monotonic VIDEO-mode timestamp in ms and returns (ts_ms, dt_infer, now_perf)."""
        self.frame_index += 1
        now_perf = time.perf_counter()
        dt_infer = (now_perf - self.last_infer_perf) if self.last_infer_perf is not None else None
        self.last_infer_perf = now_perf

        now_ms = int((now_perf - self._start_perf) * 1000)
        timestamp_ms = max(now_ms, self.frame_index)
        if timestamp_ms <= self.last_timestamp_ms:
            timestamp_ms = self.last_timestamp_ms + 1
        self.last_timestamp_ms = timestamp_ms
        return timestamp_ms, dt_infer, now_perf

    def _extract_valid_candidates(self, result, w: int, h: int):
        """Filters MediaPipe detections through plausibility gate and 2P Pose NMS."""
        world_list = list(result.pose_world_landmarks) if getattr(result, "pose_world_landmarks", None) else []
        norm_list = list(result.pose_landmarks) if getattr(result, "pose_landmarks", None) else []
        seg_list = list(result.segmentation_masks) if getattr(result, "segmentation_masks", None) else []

        candidates = []
        raw_pose_count = min(len(world_list), len(norm_list))
        for idx in range(raw_pose_count):
            w_lm = world_list[idx]
            n_lm = norm_list[idx]
            if w_lm and n_lm:
                # Never fall back to another player's segmentation mask (seg_list[0]); use None to
                # trigger clean per-player anatomical mask fallback if MediaPipe omitted a mask.
                seg_obj = seg_list[idx] if idx < len(seg_list) else None
                is_plausible, score = is_plausible_human_dancer(n_lm, w, h)
                if is_plausible:
                    candidates.append((score, (w_lm, n_lm, seg_obj)))

        candidates.sort(key=lambda c: c[0], reverse=True)
        if self.max_players >= 2 and len(candidates) > 1:
            candidates, nms_suppressed = suppress_duplicate_poses(candidates, max_players=self.max_players)
            if nms_suppressed > 0:
                get_session_logger().log_throttled(
                    "2p_nms_dup",
                    "INFO",
                    "TRACKING_2P",
                    f"Pose NMS suppressed {nms_suppressed} duplicate detection(s) (raw={raw_pose_count}, kept={len(candidates)}).",
                    interval_s=3.0,
                )

        # In 1P mode take top 1; in 2P mode pass ALL NMS-filtered candidates to MultiPlayerAssociator
        valid_dets = [c[1] for c in (candidates[:1] if self.max_players == 1 else candidates)]
        return valid_dets, raw_pose_count, norm_list

    def _handle_no_detections(
        self, active_slots, raw_pose_count: int, norm_list, dt_infer: Optional[float], w: int, h: int
    ) -> List[Optional[PlayerFrame]]:
        """Handles coasting and drop diagnostics when no plausible detections are present."""
        players_out: List[Optional[PlayerFrame]] = [None] * self.max_players
        if self.max_players == 1 and raw_pose_count > 0:
            reason = explain_plausibility_rejection(norm_list[0], w, h) if norm_list else "empty"
            get_session_logger().log_throttled(
                "1p_plaus_reject",
                "INFO",
                "TRACKING_1P",
                f"Pose detected by MediaPipe (raw={raw_pose_count}) rejected by plausibility gate ({reason}).",
                interval_s=3.0,
            )

        crowded_fallback = self.max_players >= 2 and self.associator.was_crowded
        for s_idx, slot in enumerate(active_slots):
            was_tracked_1p = (
                self.max_players == 1
                and slot.person_lock.coasting.last_joints_3d is not None
            )
            pf_miss = slot.handle_missing(
                dt=dt_infer, frame_w=w, frame_h=h, is_crowded=crowded_fallback
            )
            players_out[s_idx] = pf_miss
            if was_tracked_1p and pf_miss is None:
                dt_ms = round((dt_infer or 0.0) * 1000.0, 1)
                get_session_logger().log_throttled(
                    "1p_drop",
                    "WARN",
                    "TRACKING_1P",
                    f"1P tracking dropped after coasting (raw_poses={raw_pose_count}, dt={dt_ms}ms).",
                    interval_s=2.5,
                )
        return players_out

    def _dispatch_two_players(
        self,
        active_slots,
        valid_dets,
        raw_pose_count: int,
        frame_bgr,
        frame_left,
        sample_bgr,
        dt_infer: Optional[float],
        now_perf: float,
        w: int,
        h: int,
        primary_eye: str,
    ) -> List[Optional[PlayerFrame]]:
        """Associates detections to persistent P1/P2 slots with Long-Term Identity Memory."""
        players_out: List[Optional[PlayerFrame]] = [None] * self.max_players
        assignments, is_crowded = self.associator.match(
            slots=active_slots,
            detections_norm_lm=[d[1] for d in valid_dets],
            sample_bgr=sample_bgr,
            dt=dt_infer,
            now=now_perf,
        )
        if self.associator.last_swap_audit_triggered:
            get_session_logger().log_throttled(
                "2p_swap_audit",
                "INFO",
                "TRACKING_2P",
                "Post-Separation Re-ID Audit corrected a P1/P2 identity swap.",
                interval_s=2.0,
            )

        for s_idx, slot in enumerate(active_slots):
            if s_idx in assignments:
                d_idx = assignments[s_idx]
                w_lm, n_lm, seg_obj = valid_dets[d_idx]
                other_idx = 1 - s_idx
                other_nlm = (
                    valid_dets[assignments[other_idx]][1]
                    if other_idx in assignments
                    else active_slots[other_idx].last_norm_landmarks
                )
                players_out[s_idx] = slot.process_detection(
                    world_lm=w_lm,
                    norm_lm=n_lm,
                    seg_mask_obj=seg_obj,
                    frame_bgr=frame_bgr,
                    frame_left=frame_left,
                    stereo_engine=self.stereo_engine,
                    stereo_mode=self.stereo_mode,
                    extract_joints_2d_fn=self._extract_joints_2d,
                    build_body_mask_fn=self.build_body_mask,
                    dt_infer=dt_infer,
                    w=w,
                    h=h,
                    enforce_single_person_gate=False,
                    sample_bgr=sample_bgr,
                    primary_eye=primary_eye,
                    other_norm_lm=other_nlm,
                    is_crowded=is_crowded,
                )
            else:
                was_active = slot.identity_profile.active
                pf_miss = slot.handle_missing(
                    dt=dt_infer, frame_w=w, frame_h=h, is_crowded=is_crowded
                )
                players_out[s_idx] = pf_miss
                if pf_miss is not None and pf_miss.coasting and is_crowded:
                    get_session_logger().log_throttled(
                        f"2p_crowd_coast_p{s_idx + 1}",
                        "INFO",
                        "TRACKING_2P",
                        f"Player {s_idx + 1} entered overlap coasting (raw_poses={raw_pose_count}, kept={len(valid_dets)}, crowded={is_crowded}).",
                        interval_s=2.5,
                    )
                elif was_active and pf_miss is None:
                    get_session_logger().log_throttled(
                        f"2p_drop_p{s_idx + 1}",
                        "WARN",
                        "TRACKING_2P",
                        f"Player {s_idx + 1} tracking dropped after coasting (raw_poses={raw_pose_count}, kept={len(valid_dets)}, crowded={is_crowded}).",
                        interval_s=2.5,
                    )
        return players_out

    def process_frame_multi(self, frame_bgr, frame_left=None, primary_eye: str = "right") -> MultiPoseFrame:
        """
        Processes a BGR camera frame (or stereo pair) for 1 or 2 simultaneous players.
        Returns a MultiPoseFrame containing per-slot PlayerFrames, tracked_mask bitmask (bit 0 = P1, bit 1 = P2),
        and a combined 320x240 player_index_mask (0=bg, 1=P1, 2=P2).
        """
        frame_bgr, frame_left = self._unpack_frame_input(frame_bgr, frame_left)
        h, w = frame_bgr.shape[:2]

        sample_bgr = self._prepare_inference_buffer(frame_bgr)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=self._infer_rgb)
        timestamp_ms, dt_infer, now_perf = self._next_monotonic_timestamp()

        result = self.detector.detect_for_video(mp_image, timestamp_ms)
        valid_dets, raw_pose_count, norm_list = self._extract_valid_candidates(result, w, h)

        active_slots = self.slots[: self.max_players]
        if not valid_dets:
            players_out = self._handle_no_detections(active_slots, raw_pose_count, norm_list, dt_infer, w, h)
        elif self.max_players == 1:
            w_lm, n_lm, seg_obj = valid_dets[0]
            pf0 = active_slots[0].process_detection(
                world_lm=w_lm,
                norm_lm=n_lm,
                seg_mask_obj=seg_obj,
                frame_bgr=frame_bgr,
                frame_left=frame_left,
                stereo_engine=self.stereo_engine,
                stereo_mode=self.stereo_mode,
                extract_joints_2d_fn=self._extract_joints_2d,
                build_body_mask_fn=self.build_body_mask,
                dt_infer=dt_infer,
                w=w,
                h=h,
                enforce_single_person_gate=True,
                sample_bgr=sample_bgr,
                primary_eye=primary_eye,
            )
            players_out = [pf0]
            if pf0 is None or pf0.coasting:
                get_session_logger().log_throttled(
                    "1p_impostor_gate",
                    "INFO",
                    "TRACKING_1P",
                    f"DancerIdentityLock gated candidate (coasting={bool(pf0 and pf0.coasting)}, streak={active_slots[0].person_lock.identity.rejected_streak}).",
                    interval_s=2.5,
                )
        else:
            players_out = self._dispatch_two_players(
                active_slots, valid_dets, raw_pose_count, frame_bgr, frame_left,
                sample_bgr, dt_infer, now_perf, w, h, primary_eye,
            )

        tracked_mask = sum(
            (1 << i)
            for i, pf in enumerate(players_out)
            if pf is not None and pf.tracked and pf.kinect_joints is not None
        )
        active_count = sum(
            1
            for pf in players_out
            if pf is not None and pf.tracked and pf.kinect_joints is not None
        )
        index_mask = compose_player_index_mask(
            players_out, width=self.MASK_INTERNAL_W, height=self.MASK_INTERNAL_H
        )

        return MultiPoseFrame(
            players=players_out,
            tracked_mask=tracked_mask,
            player_index_mask=index_mask,
            active_count=active_count,
        )

    def process_frame(self, frame_bgr, frame_left=None, primary_eye: str = "right"):
        """
        Backwards-compatible single-player API.
        Returns:
            tracked (bool): True if primary pose detected.
            kinect_joints (list): 20 joints in Kinect 3D space (x, y, z, conf).
            pixel_joints (list): 20 joints in pixel coordinates (px, py, conf) for HUD drawing.
            body_mask (np.ndarray): Binary silhouette mask (320x240) with 255 for player.
        """
        multi = self.process_frame_multi(frame_bgr, frame_left=frame_left, primary_eye=primary_eye)
        p0 = multi.primary_player
        if p0 is None or not p0.tracked or p0.kinect_joints is None:
            return False, None, None, None
        return True, p0.kinect_joints, p0.pixel_joints, p0.body_mask

    def close(self):
        if self.detector:
            try:
                self.detector.close()
            except Exception:
                pass
            self.detector = None
            print("[TRACKER] MediaPipe Pose Landmarker terminated.")
