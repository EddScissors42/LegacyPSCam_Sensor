"""
Multi-Player Slot State, Long-Term Identity Memory (Anti-Swap Re-ID),
and Player Index Mask Compositor for Legacy PSCam Sensor.

Solves the classic 2-player crossover / waltz identity swap problem using:
1. Multi-region appearance signatures (Torso HSV 16x8 + Value 8-bin profile + Lower-body Pants HSV 12x6 + Anthropometric ratio).
2. Frozen Permanent Anchor Signature (`anchor_sig`) vs. Slowly-Adapting Live Signature (`live_sig`).
3. Proximity / Waltz Guard (`is_crowded`): freezes appearance updates whenever bounding boxes overlap or torsos approach.
4. Kinematic Velocity Prediction during fast crossovers.
5. Post-Separation Re-Identification Audit: automatically restores P1 and P2 to their true slots if a swap occurred during occlusion.
6. Temporary Exit Re-Entry Memory (up to 15s).
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
import cv2
import numpy as np

from sensor.pose_filters import (
    NOSE, LEFT_EAR, RIGHT_EAR,
    LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_ELBOW, RIGHT_ELBOW,
    LEFT_WRIST, RIGHT_WRIST, LEFT_INDEX, RIGHT_INDEX,
    LEFT_HIP, RIGHT_HIP, LEFT_KNEE, RIGHT_KNEE,
    LEFT_ANKLE, RIGHT_ANKLE, LEFT_FOOT_INDEX, RIGHT_FOOT_INDEX,
    avg, lerp,
    HandAnchorFilter, AdaptiveSmoother, SkeletonCalibrator,
    CameraSpaceXTracker, apply_camera_space_translation, apply_slot_snap,
)
from sensor.person_lock import PersonLockController
from sensor.stereo_matcher import STEREO_MODE_DISABLED


@dataclass
class AppearanceSignature:
    """Multi-region visual and anthropometric signature of a dancer."""
    torso_hs_hist: Optional[np.ndarray] = None
    torso_v_hist: Optional[np.ndarray] = None
    lower_hs_hist: Optional[np.ndarray] = None
    lower_v_hist: Optional[np.ndarray] = None
    torso_aspect: float = 1.35
    sh_w: float = 0.20
    body_height: float = 0.60
    contrast_ratio: float = 1.0

    def copy(self) -> "AppearanceSignature":
        return AppearanceSignature(
            torso_hs_hist=self.torso_hs_hist.copy() if self.torso_hs_hist is not None else None,
            torso_v_hist=self.torso_v_hist.copy() if self.torso_v_hist is not None else None,
            lower_hs_hist=self.lower_hs_hist.copy() if self.lower_hs_hist is not None else None,
            lower_v_hist=self.lower_v_hist.copy() if self.lower_v_hist is not None else None,
            torso_aspect=float(self.torso_aspect),
            sh_w=float(self.sh_w),
            body_height=float(self.body_height),
            contrast_ratio=float(self.contrast_ratio),
        )


def _compare_hist_01(h1: Optional[np.ndarray], h2: Optional[np.ndarray]) -> Optional[float]:
    """Compares two normalized histograms and maps correlation [-1..1] to similarity [0..1]."""
    if h1 is None or h2 is None:
        return None
    try:
        corr = float(cv2.compareHist(h1, h2, cv2.HISTCMP_CORREL))
        if math.isnan(corr):
            return None
        return float(np.clip((corr + 1.0) * 0.5, 0.0, 1.0))
    except Exception:
        return None


def compute_signature_similarity(sig_a: Optional[AppearanceSignature], sig_b: Optional[AppearanceSignature]) -> float:
    """
    Computes weighted similarity in [0.0, 1.0] between two AppearanceSignatures.
    Combines shirt Hue-Sat (35%), shirt brightness V (20%), pants Hue-Sat (15%),
    pants brightness V (10%), upper-to-lower contrast ratio (10%), and relative height (10%).
    """
    if sig_a is None or sig_b is None:
        return 0.5

    total_w = 0.0
    score = 0.0

    sim_torso_hs = _compare_hist_01(sig_a.torso_hs_hist, sig_b.torso_hs_hist)
    if sim_torso_hs is not None:
        score += 0.35 * sim_torso_hs
        total_w += 0.35

    sim_torso_v = _compare_hist_01(sig_a.torso_v_hist, sig_b.torso_v_hist)
    if sim_torso_v is not None:
        score += 0.20 * sim_torso_v
        total_w += 0.20

    sim_lower_hs = _compare_hist_01(sig_a.lower_hs_hist, sig_b.lower_hs_hist)
    if sim_lower_hs is not None:
        score += 0.15 * sim_lower_hs
        total_w += 0.15

    sim_lower_v = _compare_hist_01(sig_a.lower_v_hist, sig_b.lower_v_hist)
    if sim_lower_v is not None:
        score += 0.10 * sim_lower_v
        total_w += 0.10

    if sig_a.contrast_ratio > 0.05 and sig_b.contrast_ratio > 0.05:
        c_ratio = max(sig_a.contrast_ratio, 0.05) / max(sig_b.contrast_ratio, 0.05)
        contrast_sim = math.exp(-abs(math.log(max(0.2, min(5.0, c_ratio)))) * 1.8)
        score += 0.10 * contrast_sim
        total_w += 0.10

    if sig_a.body_height > 0.10 and sig_b.body_height > 0.10:
        h_ratio = max(sig_a.body_height, 0.10) / max(sig_b.body_height, 0.10)
        h_sim = math.exp(-abs(math.log(max(0.3, min(3.0, h_ratio)))) * 2.2)
        score += 0.10 * h_sim
        total_w += 0.10

    if total_w <= 1e-5:
        return 0.5
    return float(np.clip(score / total_w, 0.0, 1.0))


def is_plausible_human_dancer(norm_landmarks: Any, w: Optional[int] = None, h: Optional[int] = None) -> Tuple[bool, float]:
    """
    Validates whether a detected MediaPipe pose corresponds to a plausible human dancer,
    rejecting inanimate background objects (flat horizontal chairs, coats, cushions, reflections)
    while fully supporting deep crouches, floor drops, forward bends, wide arm extensions,
    and transient single-shoulder occlusions during 2-player close contact.
    Returns (is_valid: bool, score: float).
    """
    if not norm_landmarks or len(norm_landmarks) < 25:
        return False, 0.0

    sh_l = norm_landmarks[LEFT_SHOULDER]
    sh_r = norm_landmarks[RIGHT_SHOULDER]
    sh_l_vis = float(getattr(sh_l, "visibility", 1.0))
    sh_r_vis = float(getattr(sh_r, "visibility", 1.0))
    sh_min = min(sh_l_vis, sh_r_vis)
    sh_max = max(sh_l_vis, sh_r_vis)
    if sh_max < 0.25:
        return False, 0.0

    hip_l = norm_landmarks[LEFT_HIP]
    hip_r = norm_landmarks[RIGHT_HIP]
    hip_vis = max(float(getattr(hip_l, "visibility", 1.0)), float(getattr(hip_r, "visibility", 1.0)))
    nose_vis = float(getattr(norm_landmarks[NOSE], "visibility", 1.0)) if len(norm_landmarks) > NOSE else 0.0

    # Allow temporary single-shoulder occlusion (e.g., 360° spins, sideways turns, or 2P arm contact)
    # as long as the other shoulder plus either hips or head remain visible.
    if sh_min < 0.18:
        if not (sh_min >= 0.04 and (hip_vis >= 0.25 or nose_vis >= 0.25)):
            return False, 0.0

    sh_y = (float(sh_l.y) + float(sh_r.y)) * 0.5
    sh_w = math.hypot(float(sh_r.x) - float(sh_l.x), float(sh_r.y) - float(sh_l.y))

    # Reject absurdly wide shoulder artifacts; narrow sh_w is allowed during 90° sideways profile spins
    # as long as the full body height confirms a real upright dancer (checked below).
    if sh_w > 0.80:
        return False, 0.0

    # Allow deep crouches & forward torso bends where shoulders approach hip level;
    # only reject clearly inverted non-human artifacts where hips are far above shoulders AND head.
    if hip_vis >= 0.30:
        hip_y = (float(hip_l.y) + float(hip_r.y)) * 0.5
        nose_y = float(norm_landmarks[NOSE].y) if len(norm_landmarks) > NOSE else sh_y
        if hip_y < sh_y - 0.14 and hip_y < nose_y - 0.10:
            return False, 0.0

    # Check bounding box
    xs = [float(lm.x) for lm in norm_landmarks if float(getattr(lm, "visibility", 1.0)) >= 0.15]
    ys = [float(lm.y) for lm in norm_landmarks if float(getattr(lm, "visibility", 1.0)) >= 0.15]
    if len(xs) < 6:
        return False, 0.0

    bbox_w = max(xs) - min(xs)
    bbox_h = max(ys) - min(ys)

    # A crouching dancer still occupies at least 12% frame height; a tall 90° sideways profile spin
    # (pirouette with arms tucked) can narrow to ~0.8% width while maintaining >= 24% height.
    min_bbox_w = 0.008 if bbox_h >= 0.24 else 0.05
    if bbox_h < 0.12 or bbox_w < min_bbox_w:
        return False, 0.0

    if sh_w < 0.028 and bbox_h < 0.24:
        return False, 0.0

    # Aspect ratio check in physical pixels (accounts for 16:10 PS4 Camera 1280x800).
    # Deep crouches with outstretched arms can reach ~0.35..0.55 aspect ratio, while flat
    # horizontal furniture/artifacts sit near 0.0..0.22.
    px_w = bbox_w * float(w) if (w and h) else bbox_w
    px_h = bbox_h * float(h) if (w and h) else bbox_h
    aspect = px_h / max(1e-3, px_w)
    if aspect < 0.28:
        return False, 0.0

    # Calculate anatomical completeness score across core joints
    core_joints = (
        NOSE, LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_ELBOW, RIGHT_ELBOW,
        LEFT_WRIST, RIGHT_WRIST, LEFT_HIP, RIGHT_HIP, LEFT_KNEE, RIGHT_KNEE,
        LEFT_ANKLE, RIGHT_ANKLE
    )
    score = 0.0
    for j_idx in core_joints:
        if j_idx < len(norm_landmarks):
            lm = norm_landmarks[j_idx]
            v = min(1.0, max(0.0, float(getattr(lm, "visibility", 1.0))))
            p = min(1.0, max(0.0, float(getattr(lm, "presence", 1.0))))
            score += 0.5 * (v + p)

    if score < 3.2:
        return False, score

    return True, score


def _pose_torso_geometry(norm_landmarks: Any) -> Optional[Dict[str, Any]]:
    """Extracts lightweight torso geometry for Pose NMS duplicate suppression."""
    if not norm_landmarks or len(norm_landmarks) <= RIGHT_HIP:
        return None
    sh_l = norm_landmarks[LEFT_SHOULDER]
    sh_r = norm_landmarks[RIGHT_SHOULDER]
    hip_l = norm_landmarks[LEFT_HIP]
    hip_r = norm_landmarks[RIGHT_HIP]

    sh_cx = 0.5 * (float(sh_l.x) + float(sh_r.x))
    sh_cy = 0.5 * (float(sh_l.y) + float(sh_r.y))
    sh_w = max(0.04, math.hypot(float(sh_r.x) - float(sh_l.x), float(sh_r.y) - float(sh_l.y)))

    hip_vis = max(float(getattr(hip_l, "visibility", 1.0)), float(getattr(hip_r, "visibility", 1.0)))
    if hip_vis >= 0.20:
        hip_cx = 0.5 * (float(hip_l.x) + float(hip_r.x))
        hip_cy = 0.5 * (float(hip_l.y) + float(hip_r.y))
        txs = [float(sh_l.x), float(sh_r.x), float(hip_l.x), float(hip_r.x)]
        tys = [float(sh_l.y), float(sh_r.y), float(hip_l.y), float(hip_r.y)]
    else:
        hip_cx = sh_cx
        hip_cy = min(0.95, sh_cy + sh_w * 1.35)
        txs = [float(sh_l.x), float(sh_r.x)]
        tys = [float(sh_l.y), float(sh_r.y), hip_cy]

    pad_x = max(0.02, sh_w * 0.15)
    torso_bbox = (
        max(0.0, min(txs) - pad_x),
        max(0.0, min(tys) - 0.02),
        min(1.0, max(txs) + pad_x),
        min(1.0, max(tys) + 0.02),
    )

    core_pts: Dict[int, Tuple[float, float]] = {}
    for idx in (NOSE, LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP):
        if idx < len(norm_landmarks):
            lm = norm_landmarks[idx]
            if float(getattr(lm, "visibility", 1.0)) >= 0.15:
                core_pts[idx] = (float(lm.x), float(lm.y))

    limb_pts: Dict[int, Tuple[float, float]] = dict(core_pts)
    for idx in (LEFT_ELBOW, RIGHT_ELBOW, LEFT_WRIST, RIGHT_WRIST):
        if idx < len(norm_landmarks):
            lm = norm_landmarks[idx]
            if float(getattr(lm, "visibility", 1.0)) >= 0.20:
                limb_pts[idx] = (float(lm.x), float(lm.y))

    return {
        "cx": 0.5 * (sh_cx + hip_cx),
        "cy": 0.5 * (sh_cy + hip_cy),
        "sh_cx": sh_cx,
        "sh_cy": sh_cy,
        "sh_w": sh_w,
        "torso_bbox": torso_bbox,
        "core_pts": core_pts,
        "limb_pts": limb_pts,
    }


def suppress_duplicate_poses(
    candidates: List[Tuple[float, Tuple[Any, Any, Any]]],
    max_players: int = 2,
) -> Tuple[List[Tuple[float, Tuple[Any, Any, Any]]], int]:
    """
    Pose-level Non-Maximum Suppression (NMS) using torso geometry & core landmark overlap.
    Prevents MediaPipe from emitting two overlapping detections on the same dancer (e.g., when
    Player 1 places an arm onto Player 2) and stealing the other player's slot.
    Expects `candidates` as `[(score, (world_lm, norm_lm, seg_obj)), ...]` sorted by score desc.
    Returns `(kept_candidates, suppressed_count)`.
    """
    if len(candidates) <= 1:
        return list(candidates), 0

    ordered = sorted(candidates, key=lambda c: c[0], reverse=True)
    extra_candidates = len(ordered) > max_players
    kept: List[Tuple[float, Tuple[Any, Any, Any]]] = []
    kept_geoms: List[Optional[Dict[str, Any]]] = []
    suppressed = 0

    for cand in ordered:
        _, (_, n_lm, _) = cand
        g_cur = _pose_torso_geometry(n_lm)
        if g_cur is None:
            kept.append(cand)
            kept_geoms.append(None)
            continue

        is_dup = False
        for g_ref in kept_geoms:
            if g_ref is None:
                continue
            avg_sh_w = max(0.06, 0.5 * (g_cur["sh_w"] + g_ref["sh_w"]))
            torso_dist = math.hypot(g_cur["cx"] - g_ref["cx"], g_cur["cy"] - g_ref["cy"])
            sh_dist = math.hypot(g_cur["sh_cx"] - g_ref["sh_cx"], g_cur["sh_cy"] - g_ref["sh_cy"])
            torso_iou = compute_bbox_iou(g_cur["torso_bbox"], g_ref["torso_bbox"])

            shared_core = [
                math.hypot(g_cur["core_pts"][k][0] - g_ref["core_pts"][k][0],
                           g_cur["core_pts"][k][1] - g_ref["core_pts"][k][1])
                for k in g_cur["core_pts"]
                if k in g_ref["core_pts"]
            ]
            core_med = float(np.median(shared_core)) if shared_core else torso_dist

            if extra_candidates:
                # 3+ detections for 2 players: suppress any secondary proposal sitting on the same torso
                if (
                    (torso_dist < max(0.060, 0.45 * avg_sh_w) and sh_dist < max(0.065, 0.50 * avg_sh_w))
                    or (torso_iou > 0.55 and core_med < max(0.065, 0.48 * avg_sh_w))
                ):
                    is_dup = True
                    break
            else:
                # Only 2 detections total: only suppress true near-identical duplicates so real close
                # waltz crossovers (distinct people passing in front of each other) are never merged.
                shared_limbs = [
                    math.hypot(g_cur["limb_pts"][k][0] - g_ref["limb_pts"][k][0],
                               g_cur["limb_pts"][k][1] - g_ref["limb_pts"][k][1])
                    for k in g_cur["limb_pts"]
                    if k in g_ref["limb_pts"]
                ]
                limb_med = float(np.median(shared_limbs)) if shared_limbs else core_med
                if (
                    torso_dist < 0.032
                    and sh_dist < 0.032
                    and torso_iou > 0.72
                    and limb_med < 0.042
                ):
                    is_dup = True
                    break

        if is_dup:
            suppressed += 1
        else:
            kept.append(cand)
            kept_geoms.append(g_cur)

    return kept, suppressed


def extract_detection_features(
    frame_bgr: Optional[np.ndarray], norm_landmarks: Any
) -> Optional[Tuple[float, float, float, Tuple[float, float, float, float], AppearanceSignature]]:
    """
    Extracts normalized center (cx, cy), shoulder width sh_w, full bounding box (x0, y0, x1, y1),
    and multi-region AppearanceSignature from a detected pose (< 0.08 ms).
    """
    if not norm_landmarks or len(norm_landmarks) <= RIGHT_HIP:
        return None

    sh_l = norm_landmarks[LEFT_SHOULDER]
    sh_r = norm_landmarks[RIGHT_SHOULDER]
    hip_l = norm_landmarks[LEFT_HIP]
    hip_r = norm_landmarks[RIGHT_HIP]

    sh_max = max(float(getattr(sh_l, "visibility", 1.0)), float(getattr(sh_r, "visibility", 1.0)))
    if sh_max < 0.18:
        return None

    sh_cx = (float(sh_l.x) + float(sh_r.x)) * 0.5
    sh_cy = (float(sh_l.y) + float(sh_r.y)) * 0.5
    sh_w = max(0.05, math.hypot(float(sh_r.x) - float(sh_l.x), float(sh_r.y) - float(sh_l.y)))

    hip_vis = min(float(getattr(hip_l, "visibility", 1.0)), float(getattr(hip_r, "visibility", 1.0)))
    if hip_vis >= 0.20:
        hip_cx = (float(hip_l.x) + float(hip_r.x)) * 0.5
        hip_cy = (float(hip_l.y) + float(hip_r.y)) * 0.5
    else:
        hip_cx = sh_cx
        hip_cy = min(0.95, sh_cy + sh_w * 1.35)

    cx = 0.5 * (sh_cx + hip_cx)
    cy = 0.5 * (sh_cy + hip_cy)
    torso_h = max(0.05, abs(hip_cy - sh_cy))
    torso_aspect = float(np.clip(torso_h / max(0.04, sh_w), 0.5, 3.0))

    xs = [sh_cx, hip_cx]
    ys = [sh_cy, hip_cy]
    for idx in (
        NOSE, LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_ELBOW, RIGHT_ELBOW,
        LEFT_WRIST, RIGHT_WRIST, LEFT_HIP, RIGHT_HIP, LEFT_ANKLE, RIGHT_ANKLE
    ):
        if idx < len(norm_landmarks):
            lm = norm_landmarks[idx]
            if float(getattr(lm, "visibility", 1.0)) >= 0.20:
                xs.append(float(lm.x))
                ys.append(float(lm.y))

    bbox = (
        float(np.clip(min(xs), 0.0, 1.0)),
        float(np.clip(min(ys), 0.0, 1.0)),
        float(np.clip(max(xs), 0.0, 1.0)),
        float(np.clip(max(ys), 0.0, 1.0)),
    )

    torso_hs_hist = None
    torso_v_hist = None
    lower_hs_hist = None
    lower_v_hist = None
    body_height = max(0.20, float(bbox[3] - bbox[1]))
    contrast_ratio = 1.0
    t_hsv = None
    l_hsv = None

    if frame_bgr is not None and frame_bgr.ndim == 3 and frame_bgr.shape[2] == 3:
        fh, fw = frame_bgr.shape[:2]
        # 1. Inner torso patch (shirt color & brightness)
        pad_x = max(0.03, sh_w * 0.32)
        pad_y = max(0.04, torso_h * 0.35)
        tx0 = int(round(max(0.0, min(1.0, cx - pad_x)) * (fw - 1)))
        tx1 = int(round(max(0.0, min(1.0, cx + pad_x)) * (fw - 1)))
        ty0 = int(round(max(0.0, min(1.0, cy - pad_y)) * (fh - 1)))
        ty1 = int(round(max(0.0, min(1.0, cy + pad_y)) * (fh - 1)))

        if (tx1 - tx0) >= 6 and (ty1 - ty0) >= 6:
            t_patch = frame_bgr[ty0:ty1, tx0:tx1]
            t_hsv = cv2.cvtColor(t_patch, cv2.COLOR_BGR2HSV)
            hs = cv2.calcHist([t_hsv], [0, 1], None, [16, 8], [0, 180, 0, 256])
            cv2.normalize(hs, hs, alpha=1.0, beta=0.0, norm_type=cv2.NORM_L1)
            torso_hs_hist = hs

            vh = cv2.calcHist([t_hsv], [2], None, [8], [0, 256])
            cv2.normalize(vh, vh, alpha=1.0, beta=0.0, norm_type=cv2.NORM_L1)
            torso_v_hist = vh

        # 2. Lower body patch (hips to knees — pants/skirt color)
        if len(norm_landmarks) > RIGHT_KNEE and hip_vis >= 0.25:
            kl = norm_landmarks[LEFT_KNEE]
            kr = norm_landmarks[RIGHT_KNEE]
            k_vis = min(float(getattr(kl, "visibility", 1.0)), float(getattr(kr, "visibility", 1.0)))
            if k_vis >= 0.20:
                k_cx = (float(kl.x) + float(kr.x)) * 0.5
                k_cy = (float(kl.y) + float(kr.y)) * 0.5
                lcx = 0.5 * (hip_cx + k_cx)
                lcy = 0.5 * (hip_cy + k_cy)
                l_pad_x = max(0.03, sh_w * 0.28)
                l_pad_y = max(0.03, abs(k_cy - hip_cy) * 0.30)
                lx0 = int(round(max(0.0, min(1.0, lcx - l_pad_x)) * (fw - 1)))
                lx1 = int(round(max(0.0, min(1.0, lcx + l_pad_x)) * (fw - 1)))
                ly0 = int(round(max(0.0, min(1.0, lcy - l_pad_y)) * (fh - 1)))
                ly1 = int(round(max(0.0, min(1.0, lcy + l_pad_y)) * (fh - 1)))
                if (lx1 - lx0) >= 6 and (ly1 - ly0) >= 6:
                    l_patch = frame_bgr[ly0:ly1, lx0:lx1]
                    l_hsv = cv2.cvtColor(l_patch, cv2.COLOR_BGR2HSV)
                    lhs = cv2.calcHist([l_hsv], [0, 1], None, [12, 6], [0, 180, 0, 256])
                    cv2.normalize(lhs, lhs, alpha=1.0, beta=0.0, norm_type=cv2.NORM_L1)
                    lower_hs_hist = lhs

                    lvh = cv2.calcHist([l_hsv], [2], None, [8], [0, 256])
                    cv2.normalize(lvh, lvh, alpha=1.0, beta=0.0, norm_type=cv2.NORM_L1)
                    lower_v_hist = lvh

        torso_mean_v = float(np.mean(t_hsv[:, :, 2])) if t_hsv is not None and t_hsv.size > 0 else 128.0
        lower_mean_v = float(np.mean(l_hsv[:, :, 2])) if l_hsv is not None and l_hsv.size > 0 else 128.0
        contrast_ratio = float(np.clip(torso_mean_v / max(10.0, lower_mean_v), 0.1, 10.0))

    sig = AppearanceSignature(
        torso_hs_hist=torso_hs_hist,
        torso_v_hist=torso_v_hist,
        lower_hs_hist=lower_hs_hist,
        lower_v_hist=lower_v_hist,
        torso_aspect=torso_aspect,
        sh_w=sh_w,
        body_height=body_height,
        contrast_ratio=contrast_ratio,
    )
    return cx, cy, sh_w, bbox, sig


def compute_bbox_iou(b1: Tuple[float, float, float, float], b2: Tuple[float, float, float, float]) -> float:
    """Computes 2D Intersection-over-Union (IoU) between two normalized bounding boxes."""
    ix0 = max(b1[0], b2[0])
    iy0 = max(b1[1], b2[1])
    ix1 = min(b1[2], b2[2])
    iy1 = min(b1[3], b2[3])
    iw = max(0.0, ix1 - ix0)
    ih = max(0.0, iy1 - iy0)
    inter = iw * ih
    if inter <= 0.0:
        return 0.0
    a1 = max(1e-5, (b1[2] - b1[0]) * (b1[3] - b1[1]))
    a2 = max(1e-5, (b2[2] - b2[0]) * (b2[3] - b2[1]))
    return float(inter / (a1 + a2 - inter))


class LongTermIdentityProfile:
    """
    Long-Term Identity Memory for a Player Slot.
    Maintains a frozen/consolidated `anchor_sig` learned during clean separated frames
    and a slowly adapting `live_sig`, plus damped 2D velocity for crossover trajectory prediction.
    """
    ANCHOR_CONSOLIDATION_FRAMES = 25
    REENTRY_MEMORY_TTL_S = 15.0

    def __init__(self, slot_index: int):
        self.slot_index = int(slot_index)
        self.reset()

    def reset(self) -> None:
        self.is_enrolled: bool = False
        self.active: bool = False
        self.cx: float = 0.35 if self.slot_index == 0 else 0.65
        self.cy: float = 0.50
        self.vx: float = 0.0
        self.vy: float = 0.0
        self.sh_w: float = 0.20
        self.bbox: Tuple[float, float, float, float] = (0.1, 0.1, 0.9, 0.9)
        self.anchor_sig: Optional[AppearanceSignature] = None
        self.live_sig: Optional[AppearanceSignature] = None
        self.clean_frames: int = 0
        self.last_seen_time: float = 0.0

    def has_valid_memory(self, now: Optional[float] = None) -> bool:
        if not self.is_enrolled or self.anchor_sig is None:
            return False
        if self.active:
            return True
        now_t = time.perf_counter() if now is None else now
        return (now_t - self.last_seen_time) <= self.REENTRY_MEMORY_TTL_S

    def predict_position(self, dt: Optional[float] = None) -> Tuple[float, float]:
        if not self.active:
            return self.cx, self.cy
        dt_s = min(0.10, max(0.0, float(dt))) if dt is not None else (1.0 / 30.0)
        px = float(np.clip(self.cx + self.vx * dt_s, 0.0, 1.0))
        py = float(np.clip(self.cy + self.vy * dt_s, 0.0, 1.0))
        return px, py

    def update(
        self,
        cx: float,
        cy: float,
        sh_w: float,
        bbox: Tuple[float, float, float, float],
        sig: AppearanceSignature,
        is_crowded: bool,
        dt: Optional[float] = None,
        now: Optional[float] = None,
    ) -> None:
        now_t = time.perf_counter() if now is None else now
        dt_s = min(0.10, max(0.004, float(dt))) if (dt is not None and dt > 0.0005) else (1.0 / 30.0)

        if self.active:
            inst_vx = (cx - self.cx) / dt_s
            inst_vy = (cy - self.cy) / dt_s
            max_v = 2.8  # normalized screen units/sec
            spd = math.hypot(inst_vx, inst_vy)
            if spd > max_v and spd > 1e-5:
                inst_vx *= max_v / spd
                inst_vy *= max_v / spd
            self.vx = 0.55 * self.vx + 0.45 * inst_vx
            self.vy = 0.55 * self.vy + 0.45 * inst_vy
            self.cx = 0.30 * self.cx + 0.70 * cx
            self.cy = 0.30 * self.cy + 0.70 * cy
            self.sh_w = 0.80 * self.sh_w + 0.20 * sh_w
        else:
            self.cx = cx
            self.cy = cy
            self.vx = 0.0
            self.vy = 0.0
            self.sh_w = sh_w

        self.bbox = bbox
        self.active = True
        self.last_seen_time = now_t

        if not self.is_enrolled or self.anchor_sig is None:
            self.anchor_sig = sig.copy()
            self.live_sig = sig.copy()
            self.is_enrolled = True
            self.clean_frames = 1 if not is_crowded else 0
            return

        # Freeze appearance updates during waltz / crossover / overlap so P2 never contaminates P1
        if is_crowded:
            return

        self.clean_frames += 1
        # Consolidate permanent anchor signature during first ANCHOR_CONSOLIDATION_FRAMES clean frames
        if self.clean_frames <= self.ANCHOR_CONSOLIDATION_FRAMES:
            self._blend_signature(self.anchor_sig, sig, alpha=0.15)
        self._blend_signature(self.live_sig, sig, alpha=0.04)

    @staticmethod
    def _blend_signature(target: Optional[AppearanceSignature], src: AppearanceSignature, alpha: float) -> None:
        if target is None:
            return
        if src.torso_hs_hist is not None:
            if target.torso_hs_hist is None:
                target.torso_hs_hist = src.torso_hs_hist.copy()
            else:
                cv2.addWeighted(target.torso_hs_hist, 1.0 - alpha, src.torso_hs_hist, alpha, 0.0, dst=target.torso_hs_hist)
        if src.torso_v_hist is not None:
            if target.torso_v_hist is None:
                target.torso_v_hist = src.torso_v_hist.copy()
            else:
                cv2.addWeighted(target.torso_v_hist, 1.0 - alpha, src.torso_v_hist, alpha, 0.0, dst=target.torso_v_hist)
        if src.lower_hs_hist is not None:
            if target.lower_hs_hist is None:
                target.lower_hs_hist = src.lower_hs_hist.copy()
            else:
                cv2.addWeighted(target.lower_hs_hist, 1.0 - alpha, src.lower_hs_hist, alpha, 0.0, dst=target.lower_hs_hist)
        if src.lower_v_hist is not None:
            if target.lower_v_hist is None:
                target.lower_v_hist = src.lower_v_hist.copy()
            else:
                cv2.addWeighted(target.lower_v_hist, 1.0 - alpha, src.lower_v_hist, alpha, 0.0, dst=target.lower_v_hist)
        target.torso_aspect = (1.0 - alpha) * target.torso_aspect + alpha * src.torso_aspect
        target.sh_w = (1.0 - alpha) * target.sh_w + alpha * src.sh_w
        target.body_height = (1.0 - alpha) * target.body_height + alpha * src.body_height
        target.contrast_ratio = (1.0 - alpha) * target.contrast_ratio + alpha * src.contrast_ratio

    def mark_missing(self) -> None:
        self.active = False
        self.vx *= 0.7
        self.vy *= 0.7

    def similarity_to(self, sig: AppearanceSignature) -> float:
        """Evaluates visual similarity against both permanent anchor (70%) and live signature (30%)."""
        if not self.is_enrolled or self.anchor_sig is None:
            return 0.5
        s_anc = compute_signature_similarity(self.anchor_sig, sig)
        s_liv = compute_signature_similarity(self.live_sig, sig) if self.live_sig is not None else s_anc
        return 0.70 * s_anc + 0.30 * s_liv


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
        self.person_lock.reset()
        self._seg_prob_ema = None
        self.last_norm_landmarks = None
        if reset_identity:
            self.identity_profile.reset()

    def reset_transient(self) -> None:
        """Resets kinematic filters after dropout expiration while preserving long-term identity memory."""
        self.smoother.reset()
        self.camera_x_tracker.reset()
        self.person_lock.reset()
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
            hip_l = (hip_center[0] - sh_w * 0.38, syn_hip_y, hip_center[2], syn_conf)
            hip_r = (hip_center[0] + sh_w * 0.38, syn_hip_y, hip_center[2], syn_conf)

        spine = lerp(hip_center, sh_c, 0.52)

        raw_ank_l = get_joint(LEFT_ANKLE)
        raw_ank_r = get_joint(RIGHT_ANKLE)
        legs_visible = (raw_ank_l[3] >= 0.25 and raw_ank_r[3] >= 0.25)

        if legs_visible:
            knee_l = get_joint(LEFT_KNEE)
            ank_l = raw_ank_l
            foot_l = get_joint(LEFT_FOOT_INDEX)
            knee_r = get_joint(RIGHT_KNEE)
            ank_r = raw_ank_r
            foot_r = get_joint(RIGHT_FOOT_INDEX)
        else:
            thigh_len = torso_len * 1.05
            calf_len = torso_len * 1.00
            syn_leg_conf = 0.35
            knee_l = (hip_l[0], hip_l[1] + thigh_len, hip_l[2], syn_leg_conf)
            knee_r = (hip_r[0], hip_r[1] + thigh_len, hip_r[2], syn_leg_conf)
            ank_l = (hip_l[0], hip_l[1] + thigh_len + calf_len, hip_l[2], syn_leg_conf)
            ank_r = (hip_r[0], hip_r[1] + thigh_len + calf_len, hip_r[2], syn_leg_conf)
            foot_l = (hip_l[0], hip_l[1] + thigh_len + calf_len + 0.05, hip_l[2] - 0.12, syn_leg_conf)
            foot_r = (hip_r[0], hip_r[1] + thigh_len + calf_len + 0.05, hip_r[2] - 0.12, syn_leg_conf)

        raw_kinect = [
            hip_center,
            spine,
            sh_c,
            head,
            sh_l,
            get_joint(LEFT_ELBOW),
            get_joint(LEFT_WRIST),
            get_joint(LEFT_INDEX),
            sh_r,
            get_joint(RIGHT_ELBOW),
            get_joint(RIGHT_WRIST),
            get_joint(RIGHT_INDEX),
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

        # 3. Auto-calibrate height and origin
        ankles_in_frame = (
            legs_visible
            and raw_ank_l[3] >= 0.50
            and raw_ank_r[3] >= 0.50
            and float(norm_lm[LEFT_ANKLE].y) <= 0.96
            and float(norm_lm[RIGHT_ANKLE].y) <= 0.96
        )
        if not self.calibrator.is_calibrated or (self.calibrator.calibration_tier != "full_body" and ankles_in_frame):
            self.calibrator.calibrate(anchored, legs_visible=ankles_in_frame, hips_visible=hips_visible)

        # 3.1 Stereo Triangulation (automatic on PS4 Camera dual sensor)
        stereo_depths = None
        if stereo_mode != STEREO_MODE_DISABLED and frame_left is not None and stereo_engine is not None:
            try:
                mono_pri = frame_bgr[:, :, 1] if (frame_left.ndim == 2 and frame_bgr.ndim == 3) else frame_bgr
                if str(primary_eye or "right").strip().lower() == "left":
                    rect_left_frame, rect_right_frame = stereo_engine.calibrator.rectify(mono_pri, frame_left)
                else:
                    rect_left_frame, rect_right_frame = stereo_engine.calibrator.rectify(frame_left, mono_pri)
                joints_2d = extract_joints_2d_fn(norm_lm, w, h)
                stereo_depths = stereo_engine.triangulate_sparse_joints(
                    rect_left_frame, rect_right_frame, joints_2d, primary_eye=primary_eye
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
        translated = apply_camera_space_translation(smoothed_kinect, norm_lm, self.camera_x_tracker, self.cfg)

        # 4.3 Apply slot snap
        snapped = apply_slot_snap(translated, self.cfg)

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
            px_hip_l = (max(0, px_hip_c[0] - int(sh_w_px * 0.38)), syn_px_y, px_sh_c[2])
            px_hip_r = (min(w - 1, px_hip_c[0] + int(sh_w_px * 0.38)), syn_px_y, px_sh_c[2])

        px_spine = (
            int(px_hip_c[0] + 0.52 * (px_sh_c[0] - px_hip_c[0])),
            int(px_hip_c[1] + 0.52 * (px_sh_c[1] - px_hip_c[1])),
            px_sh_c[2],
        )
        px_nose = get_pixel(NOSE)

        if legs_visible:
            px_knee_l = get_pixel(LEFT_KNEE)
            px_ank_l = get_pixel(LEFT_ANKLE)
            px_foot_l = get_pixel(LEFT_FOOT_INDEX)
            px_knee_r = get_pixel(RIGHT_KNEE)
            px_ank_r = get_pixel(RIGHT_ANKLE)
            px_foot_r = get_pixel(RIGHT_FOOT_INDEX)
        else:
            thigh_px = int(sh_w_px * 1.4)
            calf_px = int(sh_w_px * 1.3)
            px_knee_l = (px_hip_l[0], min(h - 2, px_hip_l[1] + thigh_px), 0.35)
            px_knee_r = (px_hip_r[0], min(h - 2, px_hip_r[1] + thigh_px), 0.35)
            px_ank_l = (px_hip_l[0], min(h - 2, px_hip_l[1] + thigh_px + calf_px), 0.35)
            px_ank_r = (px_hip_r[0], min(h - 2, px_hip_r[1] + thigh_px + calf_px), 0.35)
            px_foot_l = (px_hip_l[0], min(h - 2, px_hip_l[1] + thigh_px + calf_px + 10), 0.35)
            px_foot_r = (px_hip_r[0], min(h - 2, px_hip_r[1] + thigh_px + calf_px + 10), 0.35)

        pixel_joints = [
            px_hip_c,
            px_spine,
            px_sh_c,
            px_nose,
            px_sh_l,
            get_pixel(LEFT_ELBOW),
            get_pixel(LEFT_WRIST),
            get_pixel(LEFT_INDEX),
            px_sh_r,
            get_pixel(RIGHT_ELBOW),
            get_pixel(RIGHT_WRIST),
            get_pixel(RIGHT_INDEX),
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
          3. Applies a light 3x3 Gaussian blur on the probability map and thresholds at 0.48
             (true semantic human boundary) instead of bloated low thresholds.
          4. Keeps only connected components anchored to this dancer's visible landmarks so stray
             background objects are removed without clipping hair, clothes, or outstretched hands.
          5. In 2-player mode (`other_norm_lm` present), isolates merged neural segmentation blobs
             so one player's silhouette never swallows the other dancer's torso/body when arms touch.
          6. Never overlays the geometric `anatomical_mask` on top of a valid neural silhouette;
             only falls back to `build_body_mask_fn` when neural segmentation is unavailable/empty.
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
                raw_bin = (smooth_prob >= 0.48).astype(np.uint8) * 255

                # Remove tiny isolated background specks and fill 1px clothing pinholes
                raw_bin = cv2.morphologyEx(raw_bin, cv2.MORPH_OPEN, self._ELLIPSE_3X3)
                raw_bin = cv2.morphologyEx(raw_bin, cv2.MORPH_CLOSE, self._ELLIPSE_3X3)

                # Filter connected components to keep only components belonging to this dancer
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
                                # Sample a small neighborhood around each landmark to catch hands/feet
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
                        # Fallback to largest foreground blob if landmarks fell slightly off-mask
                        areas = stats[1:, cv2.CC_STAT_AREA]
                        best_lbl = int(np.argmax(areas)) + 1
                        if int(areas[best_lbl - 1]) >= 60:
                            neural_mask = np.where(labels == best_lbl, np.uint8(255), np.uint8(0))

                # MediaPipe PoseLandmarker computes segmentation inside a square pose ROI box that can
                # hard-clip raised hands/head at the top or legs/feet at the bottom. Restore ONLY the
                # clipped top/bottom bands from landmarks while preserving 100% crisp neural torso cutout.
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
                            # Include cranial margin above nose so top of head isn't shaved off
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
                                    neural_mask = neural_mask.copy()
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

                # 2P Anti-Swallow Isolation: when two dancers touch (e.g., arm on shoulder), MediaPipe's
                # neural segmentation can merge both bodies into one connected component. Carve out pixels
                # that belong exclusively to the other player's anatomical envelope and lie outside ours.
                if neural_mask is not None and other_norm_lm is not None and norm_lm is not None:
                    my_anat = my_anat_cache if my_anat_cache is not None else build_body_mask_fn(norm_lm, mw, mh)
                    other_anat = build_body_mask_fn(other_norm_lm, mw, mh)
                    if my_anat is not None and other_anat is not None:
                        my_keep = cv2.dilate(my_anat, self._ELLIPSE_15X15, iterations=1)
                        stolen = (other_anat >= 64) & (my_keep < 64)
                        if np.any(stolen):
                            neural_mask = neural_mask.copy()
                            neural_mask[stolen] = 0
            except Exception as exc:
                if not self._warned_seg_err:
                    print(f"[WARN] Neural segmentation mask fallback to anatomical mask: {exc}")
                    self._warned_seg_err = True
                neural_mask = None

        if neural_mask is not None and int(np.count_nonzero(neural_mask)) >= 60:
            return neural_mask

        return build_body_mask_fn(norm_lm, mw, mh)


class MultiPlayerAssociator:
    """
    Matches 1..N MediaPipe Pose detections to persistent Player Slots (Slot 0 = P1, Slot 1 = P2)
    with Long-Term Identity Memory, Proximity/Waltz Freeze, Velocity Prediction, Multi-Candidate
    Optimal Pairing, and Post-Separation Re-ID Audit.
    """
    CROWD_DIST_THRESH = 0.22
    CROWD_IOU_THRESH = 0.08
    AUDIT_SWAP_MARGIN = 0.10
    AUDIT_CONFIRM_FRAMES = 2
    CURRENT_SLOT_INERTIA_BONUS = 0.22

    def __init__(self, max_players: int = 2):
        self.max_players = max(1, min(2, int(max_players)))
        self.was_crowded: bool = False
        self.swap_audit_streak: int = 0
        self.last_assignments: Dict[int, int] = {}
        self.last_swap_audit_triggered: bool = False

    def reset(self) -> None:
        self.was_crowded = False
        self.swap_audit_streak = 0
        self.last_assignments = {}
        self.last_swap_audit_triggered = False

    @staticmethod
    def _swap_slot_kinematics(slot_a: PlayerSlotState, slot_b: PlayerSlotState) -> None:
        """
        Swaps transient kinematic state (position, velocity, smoother, calibrator, camera_x_tracker, coasting)
        between two slots when the Post-Separation Re-ID Audit detects that P1 and P2 were inverted
        during a heavy waltz/crossover occlusion, while keeping each slot's permanent `anchor_sig` intact.
        """
        pa, pb = slot_a.identity_profile, slot_b.identity_profile
        pa.cx, pb.cx = pb.cx, pa.cx
        pa.cy, pb.cy = pb.cy, pa.cy
        pa.vx, pb.vx = pb.vx, pa.vx
        pa.vy, pb.vy = pb.vy, pa.vy
        pa.sh_w, pb.sh_w = pb.sh_w, pa.sh_w
        pa.bbox, pb.bbox = pb.bbox, pa.bbox
        pa.live_sig, pb.live_sig = pb.live_sig, pa.live_sig

        slot_a.smoother, slot_b.smoother = slot_b.smoother, slot_a.smoother
        slot_a.calibrator, slot_b.calibrator = slot_b.calibrator, slot_a.calibrator
        slot_a.camera_x_tracker, slot_b.camera_x_tracker = slot_b.camera_x_tracker, slot_a.camera_x_tracker
        slot_a.person_lock, slot_b.person_lock = slot_b.person_lock, slot_a.person_lock
        slot_a._seg_prob_ema, slot_b._seg_prob_ema = slot_b._seg_prob_ema, slot_a._seg_prob_ema
        slot_a.last_norm_landmarks, slot_b.last_norm_landmarks = slot_b.last_norm_landmarks, slot_a.last_norm_landmarks

    def match(
        self,
        slots: List[PlayerSlotState],
        detections_norm_lm: List[Any],
        sample_bgr: Optional[np.ndarray],
        dt: Optional[float] = None,
        now: Optional[float] = None,
    ) -> Tuple[Dict[int, int], bool]:
        """
        Assigns each slot_index in `0..len(slots)-1` to at most one detection index in `0..len(detections)-1`.
        Evaluates all NMS-filtered candidate detections (up to 4) against both slots' enrolled
        long-term identity memory so a noisy/background candidate never displaces an occluded dancer.
        Returns:
            assignments: dict mapping `slot_index -> detection_index`
            is_crowded: True if the two dancers are in close waltz/crossover/overlap proximity
        """
        self.last_swap_audit_triggered = False
        now_t = time.perf_counter() if now is None else now
        num_dets = len(detections_norm_lm)
        if num_dets == 0 or not slots:
            self.last_assignments = {}
            return {}, self.was_crowded

        if len(slots) == 1:
            self.last_assignments = {0: 0}
            return {0: 0}, False

        # Extract features for ALL plausible candidate detections (not prematurely sliced to 2)
        det_feats = []
        for d_idx, nlm in enumerate(detections_norm_lm[:4]):
            feats = extract_detection_features(sample_bgr, nlm)
            if feats is not None:
                det_feats.append((d_idx, feats))

        if not det_feats:
            self.last_assignments = {}
            return {}, self.was_crowded

        p0 = slots[0].identity_profile
        p1 = slots[1].identity_profile
        p0_mem = p0.has_valid_memory(now=now_t)
        p1_mem = p1.has_valid_memory(now=now_t)

        assignments: Dict[int, int] = {}

        def _pair_is_crowded(f_a, f_b) -> bool:
            p_dist = math.hypot(f_b[0] - f_a[0], f_b[1] - f_a[1])
            p_iou = compute_bbox_iou(f_a[3], f_b[3])
            return (p_dist < self.CROWD_DIST_THRESH) or (p_iou > self.CROWD_IOU_THRESH)

        # Case 1: Neither slot has been enrolled yet -> deterministic screen order
        if not p0_mem and not p1_mem:
            sorted_dets = sorted(det_feats[:2], key=lambda item: item[1][0])
            is_crowded = _pair_is_crowded(sorted_dets[0][1], sorted_dets[1][1]) if len(sorted_dets) >= 2 else False
            for s_idx, (d_idx, (cx, cy, sh_w, bbox, sig)) in enumerate(sorted_dets[:2]):
                assignments[s_idx] = d_idx
                slots[s_idx].identity_profile.update(cx, cy, sh_w, bbox, sig, is_crowded=is_crowded, dt=dt, now=now_t)
            self.was_crowded = is_crowded
            self.last_assignments = dict(assignments)
            return assignments, is_crowded

        # Helper cost function combining kinematic trajectory distance + long-term appearance dissimilarity + velocity alignment
        def pair_cost(
            slot_idx: int,
            feat_tuple: Tuple[float, float, float, Tuple[float, float, float, float], AppearanceSignature],
            crowded: bool = False,
        ) -> float:
            prof = slots[slot_idx].identity_profile
            cx, cy, sh_w, _, sig = feat_tuple
            if not prof.has_valid_memory(now=now_t):
                return 0.65  # Neutral unassigned slot cost

            pred_x, pred_y = prof.predict_position(dt=dt)
            dist = math.hypot(cx - pred_x, cy - pred_y)
            sim = prof.similarity_to(sig)
            app_cost = 1.0 - sim
            scale_cost = abs(math.log(max(0.25, min(4.0, max(sh_w, 1e-3) / max(prof.sh_w, 1e-3)))))

            if prof.active:
                vel_len = math.hypot(prof.vx, prof.vy)
                disp_x = cx - prof.cx
                disp_y = cy - prof.cy
                disp_len = math.hypot(disp_x, disp_y)
                vel_align_bonus = 0.0
                if vel_len > 0.08 and disp_len > 0.02:
                    cos_theta = (prof.vx * disp_x + prof.vy * disp_y) / (vel_len * disp_len)
                    vel_align_bonus = -0.25 * float(cos_theta)
                if crowded:
                    # During close arm/body overlap, shirt color patches are partially occluded ->
                    # rely slightly more on predicted spatial trajectory and momentum.
                    return max(0.0, 1.25 * dist + 0.60 * app_cost + 0.20 * scale_cost + vel_align_bonus)
                return max(0.0, 1.05 * dist + 0.85 * app_cost + 0.20 * scale_cost + vel_align_bonus)
            else:
                # Re-entry after temporary exit: rely primarily on long-term visual appearance memory!
                return 0.25 * dist + 1.35 * app_cost + 0.30 * scale_cost

        # Case 2: Only 1 detection present in frame
        if len(det_feats) == 1:
            d_idx, feat = det_feats[0]
            cx, cy, sh_w, bbox, sig = feat
            if p0_mem and not p1_mem:
                dist0 = math.hypot(cx - p0.cx, cy - p0.cy)
                sim0 = p0.similarity_to(sig)
                if p0.active and dist0 > 0.38 and sim0 < 0.42:
                    chosen_slot = 1
                else:
                    chosen_slot = 0
            elif p1_mem and not p0_mem:
                dist1 = math.hypot(cx - p1.cx, cy - p1.cy)
                sim1 = p1.similarity_to(sig)
                if p1.active and dist1 > 0.38 and sim1 < 0.42:
                    chosen_slot = 0
                else:
                    chosen_slot = 1
            else:
                c0 = pair_cost(0, feat, crowded=self.was_crowded)
                c1 = pair_cost(1, feat, crowded=self.was_crowded)
                chosen_slot = 0 if c0 <= c1 else 1

            # Check if the missing slot was just overlapping with this surviving detection
            # (e.g., P1 placed an arm across P2 and MediaPipe momentarily collapsed to 1 pose).
            other_slot = 1 - chosen_slot
            other_prof = slots[other_slot].identity_profile
            is_crowded = False
            if other_prof.is_enrolled and (other_prof.active or (now_t - other_prof.last_seen_time) <= 0.85):
                d_other = math.hypot(cx - other_prof.cx, cy - other_prof.cy)
                iou_other = compute_bbox_iou(bbox, other_prof.bbox)
                if self.was_crowded or d_other < self.CROWD_DIST_THRESH * 1.35 or iou_other > 0.02:
                    is_crowded = True

            assignments[chosen_slot] = d_idx
            slots[chosen_slot].identity_profile.update(
                cx, cy, sh_w, bbox, sig, is_crowded=is_crowded, dt=dt, now=now_t
            )
            self.was_crowded = is_crowded
            self.swap_audit_streak = 0
            self.last_assignments = dict(assignments)
            return assignments, is_crowded

        # Case 3: 2+ detections present in frame -> evaluate all ordered pairs (i != j)
        # Uses spatial continuity against each slot's predicted position (never raw array index)
        # so re-sorting candidates by MediaPipe plausibility score never induces a false swap.
        p0_pred = p0.predict_position(dt=dt) if p0.active else (p0.cx, p0.cy)
        p1_pred = p1.predict_position(dt=dt) if p1.active else (p1.cx, p1.cy)
        both_active = bool(p0.active and p1.active)

        best_cost = float("inf")
        best_pair: Optional[Tuple[int, int, Any, Any, bool]] = None

        n_cands = len(det_feats)
        for i in range(n_cands):
            di, fi = det_feats[i]
            for j in range(n_cands):
                if i == j:
                    continue
                dj, fj = det_feats[j]
                pair_crowded = _pair_is_crowded(fi, fj)
                cost = pair_cost(0, fi, crowded=pair_crowded) + pair_cost(1, fj, crowded=pair_crowded)

                # Spatial-continuity inertia: gently favor keeping each active slot on the closer body
                if both_active:
                    d_direct = (
                        math.hypot(fi[0] - p0_pred[0], fi[1] - p0_pred[1])
                        + math.hypot(fj[0] - p1_pred[0], fj[1] - p1_pred[1])
                    )
                    d_swapped = (
                        math.hypot(fj[0] - p0_pred[0], fj[1] - p0_pred[1])
                        + math.hypot(fi[0] - p1_pred[0], fi[1] - p1_pred[1])
                    )
                    if d_direct + 0.015 < d_swapped:
                        bonus_scale = 1.25 if pair_crowded else 0.55
                        cost -= self.CURRENT_SLOT_INERTIA_BONUS * bonus_scale

                if cost < best_cost:
                    best_cost = cost
                    best_pair = (di, dj, fi, fj, pair_crowded)

        if best_pair is None:
            self.last_assignments = {}
            return {}, False

        d_s0, d_s1, f_s0, f_s1, is_crowded = best_pair
        assignments[0] = d_s0
        assignments[1] = d_s1

        # Post-Separation Re-Identification Audit:
        # When both dancers are clearly separated (not crowded) and both have consolidated permanent anchors,
        # verify that their current appearance matches their permanent anchor better than the swapped pairing.
        if (
            not is_crowded
            and p0.is_enrolled
            and p1.is_enrolled
            and p0.anchor_sig is not None
            and p1.anchor_sig is not None
        ):
            sig_s0 = f_s0[4]
            sig_s1 = f_s1[4]
            sim_direct = compute_signature_similarity(p0.anchor_sig, sig_s0) + compute_signature_similarity(p1.anchor_sig, sig_s1)
            sim_swapped = compute_signature_similarity(p0.anchor_sig, sig_s1) + compute_signature_similarity(p1.anchor_sig, sig_s0)

            if (sim_swapped - sim_direct) >= self.AUDIT_SWAP_MARGIN:
                self.swap_audit_streak += 1
                if self.swap_audit_streak >= self.AUDIT_CONFIRM_FRAMES:
                    # Confirmed identity inversion after waltz/occlusion -> restore true identities!
                    self._swap_slot_kinematics(slots[0], slots[1])
                    assignments[0], assignments[1] = assignments[1], assignments[0]
                    f_s0, f_s1 = f_s1, f_s0
                    self.swap_audit_streak = 0
                    self.last_swap_audit_triggered = True
            else:
                self.swap_audit_streak = 0
        else:
            self.swap_audit_streak = 0

        slots[0].identity_profile.update(*f_s0, is_crowded=is_crowded, dt=dt, now=now_t)
        slots[1].identity_profile.update(*f_s1, is_crowded=is_crowded, dt=dt, now=now_t)
        self.was_crowded = is_crowded
        self.last_assignments = dict(assignments)
        return assignments, is_crowded


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
    # Paint farthest player first so the closer player (smaller center_z) overwrites overlap pixels
    ordered = sorted(active, key=lambda p: float(p.center_z), reverse=True)
    for p in ordered:
        p_idx = int(p.slot_index) + 1  # 1 for Slot 0, 2 for Slot 1
        m = p.body_mask
        if m.shape[0] != height or m.shape[1] != width:
            m = cv2.resize(m, (width, height), interpolation=cv2.INTER_NEAREST)
        combined[m >= 64] = p_idx

    return combined
