"""
Multi-Player Re-Identification (Anti-Swap Identity Memory), Plausibility Filtering,
and Pose-Level Duplicate Suppression (NMS) for Legacy PSCam Sensor.

Extracted from `sensor/player_slot.py` for modularity while keeping
100% backwards-compatible re-exports in `sensor/player_slot.py`.

Solves the classic 2-player crossover / waltz identity swap problem using:
1. Multi-region appearance signatures (Torso HSV 16x8 + Value 8-bin profile + Lower-body Pants HSV 12x6 + Anthropometric ratio).
2. Frozen Permanent Anchor Signature (`anchor_sig`) vs. Slowly-Adapting Live Signature (`live_sig`).
3. Proximity / Waltz Guard (`is_crowded`): freezes appearance updates whenever bounding boxes overlap or torsos approach.
4. Kinematic Velocity Prediction during fast crossovers.
5. Post-Separation Re-Identification Audit: automatically restores P1 and P2 to their true slots if a swap occurred during occlusion.
6. Temporary Exit Re-Entry Memory (up to 15s).
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple
import cv2
import numpy as np

from sensor.pose_filters import (
    NOSE,
    LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_ELBOW, RIGHT_ELBOW,
    LEFT_WRIST, RIGHT_WRIST,
    LEFT_HIP, RIGHT_HIP, LEFT_KNEE, RIGHT_KNEE,
    LEFT_ANKLE, RIGHT_ANKLE,
)

if TYPE_CHECKING:
    from sensor.player_slot import PlayerSlotState


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


def _evaluate_plausibility(
    norm_landmarks: Any,
    w: Optional[int] = None,
    h: Optional[int] = None,
) -> Tuple[bool, float, str]:
    """
    Unified plausibility validator shared by `is_plausible_human_dancer` and
    `explain_plausibility_rejection` so thresholds and diagnostic reasons never diverge.
    Returns `(is_valid, score, reason)`.
    """
    if not norm_landmarks or len(norm_landmarks) < 25:
        return False, 0.0, "too_few_landmarks"

    sh_l = norm_landmarks[LEFT_SHOULDER]
    sh_r = norm_landmarks[RIGHT_SHOULDER]
    sh_l_vis = float(getattr(sh_l, "visibility", 1.0))
    sh_r_vis = float(getattr(sh_r, "visibility", 1.0))
    sh_min = min(sh_l_vis, sh_r_vis)
    sh_max = max(sh_l_vis, sh_r_vis)
    if sh_max < 0.25:
        return False, 0.0, f"sh_max={sh_max:.2f}"

    hip_l = norm_landmarks[LEFT_HIP]
    hip_r = norm_landmarks[RIGHT_HIP]
    hip_vis = max(float(getattr(hip_l, "visibility", 1.0)), float(getattr(hip_r, "visibility", 1.0)))
    nose_vis = float(getattr(norm_landmarks[NOSE], "visibility", 1.0)) if len(norm_landmarks) > NOSE else 0.0

    # Allow temporary single-shoulder occlusion (e.g., 360° spins, sideways turns, or 2P arm contact)
    # as long as the other shoulder plus either hips or head remain visible.
    if sh_min < 0.18:
        if not (sh_min >= 0.04 and (hip_vis >= 0.25 or nose_vis >= 0.25)):
            return False, 0.0, f"sh_min={sh_min:.2f},hip={hip_vis:.2f},nose={nose_vis:.2f}"

    sh_y = (float(sh_l.y) + float(sh_r.y)) * 0.5
    sh_w = math.hypot(float(sh_r.x) - float(sh_l.x), float(sh_r.y) - float(sh_l.y))

    # Reject absurdly wide shoulder artifacts; narrow sh_w is allowed during 90° sideways profile spins
    # as long as the full body height confirms a real upright dancer (checked below).
    if sh_w > 0.80:
        return False, 0.0, f"sh_w={sh_w:.2f}>0.80"

    # Allow deep crouches & forward torso bends where shoulders approach hip level;
    # only reject clearly inverted non-human artifacts where hips are far above shoulders AND head.
    if hip_vis >= 0.30:
        hip_y = (float(hip_l.y) + float(hip_r.y)) * 0.5
        nose_y = float(norm_landmarks[NOSE].y) if len(norm_landmarks) > NOSE else sh_y
        if hip_y < sh_y - 0.14 and hip_y < nose_y - 0.10:
            return False, 0.0, f"inverted(hip_y={hip_y:.2f},sh_y={sh_y:.2f})"

    # Check bounding box
    xs = [float(lm.x) for lm in norm_landmarks if float(getattr(lm, "visibility", 1.0)) >= 0.15]
    ys = [float(lm.y) for lm in norm_landmarks if float(getattr(lm, "visibility", 1.0)) >= 0.15]
    if len(xs) < 6:
        return False, 0.0, f"vis_pts={len(xs)}<6"

    bbox_w = max(xs) - min(xs)
    bbox_h = max(ys) - min(ys)

    # A crouching dancer still occupies at least 12% frame height; a tall 90° sideways profile spin
    # (pirouette with arms tucked) can narrow to ~0.8% width while maintaining >= 24% height.
    min_bbox_w = 0.008 if bbox_h >= 0.24 else 0.05
    if bbox_h < 0.12:
        return False, 0.0, f"bbox_h={bbox_h:.2f}<0.12"
    if bbox_w < min_bbox_w:
        return False, 0.0, f"bbox_w={bbox_w:.3f}<{min_bbox_w:.3f}"

    if sh_w < 0.028 and bbox_h < 0.24:
        return False, 0.0, f"narrow(sh_w={sh_w:.3f},bh={bbox_h:.2f})"

    # Aspect ratio check in physical pixels (accounts for 16:10 PS4 Camera 1280x800).
    # Wide arm extensions / desk framing with a clear human upper body can dip to ~0.23..0.28,
    # while flat horizontal furniture/artifacts without face+shoulders sit below 0.28.
    strong_upper_body = (nose_vis >= 0.45 and sh_min >= 0.45 and sh_w >= 0.08)
    px_w = bbox_w * float(w) if (w and h) else bbox_w
    px_h = bbox_h * float(h) if (w and h) else bbox_h
    aspect = px_h / max(1e-3, px_w)
    min_aspect = 0.22 if strong_upper_body else 0.28
    if aspect < min_aspect:
        return False, 0.0, f"aspect={aspect:.2f}<{min_aspect:.2f}"

    # Calculate anatomical completeness score across core joints.
    # - Desk/half-body framing with unmistakable head + shoulders: allow score >= 1.75 (avoids 2.0-2.2 boundary drops).
    # - Tall sideways/back-facing 360° spin where face is temporarily occluded: allow score >= 2.6.
    # - Small/ambiguous candidates: keep strict 3.2 threshold to reject background clutter.
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

    tall_profile_spin = (bbox_h >= 0.35 and sh_w >= 0.045)
    if strong_upper_body:
        min_score = 1.75
    elif tall_profile_spin:
        min_score = 2.6
    else:
        min_score = 3.2
    if score < min_score:
        return False, score, f"score={score:.2f}<{min_score:.2f}(sh_w={sh_w:.2f},bw={bbox_w:.2f},bh={bbox_h:.2f},asp={aspect:.2f})"

    return True, score, "ok"


def is_plausible_human_dancer(norm_landmarks: Any, w: Optional[int] = None, h: Optional[int] = None) -> Tuple[bool, float]:
    """
    Validates whether a detected MediaPipe pose corresponds to a plausible human dancer,
    rejecting inanimate background objects (flat horizontal chairs, coats, cushions, reflections)
    while fully supporting deep crouches, floor drops, forward bends, wide arm extensions,
    and transient single-shoulder occlusions during 2-player close contact.
    Returns (is_valid: bool, score: float).
    """
    ok, score, _ = _evaluate_plausibility(norm_landmarks, w=w, h=h)
    return ok, score


def explain_plausibility_rejection(norm_landmarks: Any, w: Optional[int] = None, h: Optional[int] = None) -> str:
    """Returns a compact diagnostic reason string when `is_plausible_human_dancer` rejects a pose."""
    _, _, reason = _evaluate_plausibility(norm_landmarks, w=w, h=h)
    return reason


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
    def _swap_slot_kinematics(slot_a: "PlayerSlotState", slot_b: "PlayerSlotState") -> None:
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
        slots: List["PlayerSlotState"],
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
]
