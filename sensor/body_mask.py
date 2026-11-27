"""
Anatomical Body Silhouette Mask & 2D Kinect Joint Projection.
Pure geometric utilities decoupled from MediaPipe runtime state so they can be
tested independently and reused across 1P/2P tracking pipelines at 60 FPS.
"""
from __future__ import annotations

import math
import cv2
import numpy as np

from sensor.pose_filters import (
    NOSE,
    LEFT_SHOULDER,
    RIGHT_SHOULDER,
    LEFT_ELBOW,
    RIGHT_ELBOW,
    LEFT_WRIST,
    RIGHT_WRIST,
    LEFT_INDEX,
    RIGHT_INDEX,
    LEFT_HIP,
    RIGHT_HIP,
    LEFT_KNEE,
    RIGHT_KNEE,
    LEFT_ANKLE,
    RIGHT_ANKLE,
    LEFT_FOOT_INDEX,
    RIGHT_FOOT_INDEX,
)

MORPH_KERNEL_SMALL = np.ones((3, 3), np.uint8)
MORPH_KERNEL_LARGE = np.ones((7, 7), np.uint8)


def extract_joints_2d(norm_lm, w: int, h: int) -> dict[int, tuple[float, float, float]]:
    """Extracts 2D pixel coordinates and confidence for all 20 Kinect v1 joints."""

    def pt(idx: int) -> tuple[float, float, float]:
        lm = norm_lm[idx]
        vis = getattr(lm, "visibility", 1.0)
        pres = getattr(lm, "presence", 1.0)
        return (float(lm.x * w), float(lm.y * h), min(1.0, max(0.0, min(vis, pres))))

    hip_l = pt(LEFT_HIP)
    hip_r = pt(RIGHT_HIP)
    hip_c = ((hip_l[0] + hip_r[0]) * 0.5, (hip_l[1] + hip_r[1]) * 0.5, min(hip_l[2], hip_r[2]))

    sh_l = pt(LEFT_SHOULDER)
    sh_r = pt(RIGHT_SHOULDER)
    sh_c = ((sh_l[0] + sh_r[0]) * 0.5, (sh_l[1] + sh_r[1]) * 0.5, min(sh_l[2], sh_r[2]))

    spine = (hip_c[0] * 0.48 + sh_c[0] * 0.52, hip_c[1] * 0.48 + sh_c[1] * 0.52, min(hip_c[2], sh_c[2]))

    return {
        0: hip_c,
        1: spine,
        2: sh_c,
        3: pt(NOSE),
        4: sh_l,
        5: pt(LEFT_ELBOW),
        6: pt(LEFT_WRIST),
        7: pt(LEFT_INDEX),
        8: sh_r,
        9: pt(RIGHT_ELBOW),
        10: pt(RIGHT_WRIST),
        11: pt(RIGHT_INDEX),
        12: hip_l,
        13: pt(LEFT_KNEE),
        14: pt(LEFT_ANKLE),
        15: pt(LEFT_FOOT_INDEX),
        16: hip_r,
        17: pt(RIGHT_KNEE),
        18: pt(RIGHT_ANKLE),
        19: pt(RIGHT_FOOT_INDEX),
    }


def _draw_torso_polygon(mask: np.ndarray, ls, rs, lh, rh, width: int, height: int, scale_factor: float):
    """Fills torso polygon, synthesizing hips down to frame bottom for desk/partial framing."""
    if not (ls and rs):
        return
    sh_w = max(10.0 * scale_factor, math.hypot(rs[0] - ls[0], rs[1] - ls[1]))
    torso_h = int(sh_w * 1.45)
    bottom_y = min(height - 1, int(max(ls[1], rs[1]) + torso_h))

    if not lh or lh[1] >= height - 2:
        lh = (max(0, int(ls[0] - 0.10 * (rs[0] - ls[0]))), bottom_y)
    if not rh or rh[1] >= height - 2:
        rh = (min(width - 1, int(rs[0] + 0.10 * (rs[0] - ls[0]))), bottom_y)

    torso_pts = np.array([ls, rs, rh, lh], dtype=np.int32)
    cv2.fillConvexPoly(mask, torso_pts, 255)

    pad_x = max(8, int(15 * scale_factor))
    if bottom_y >= height - max(3, int(6 * scale_factor)):
        bot_poly = np.array(
            [lh, rh, (min(width - 1, rh[0] + pad_x), height - 1), (max(0, lh[0] - pad_x), height - 1)],
            dtype=np.int32,
        )
        cv2.fillConvexPoly(mask, bot_poly, 255)


def _draw_head_jaw_neck(mask: np.ndarray, ls, rs, pt, scale_factor: float):
    """Draws tilted cranial ellipse, jaw trapezoid, and neck connecting to mid-shoulder."""
    nose = pt(0)
    ear_l, ear_r = pt(7), pt(8)
    eye_l, eye_r = pt(2), pt(5)
    mouth_l, mouth_r = pt(9), pt(10)

    if ls and rs:
        shoulder_dist = max(10.0 * scale_factor, math.hypot(rs[0] - ls[0], rs[1] - ls[1]))
        mid_shoulder = ((ls[0] + rs[0]) // 2, (ls[1] + rs[1]) // 2)

        ref_head = None
        if ear_l and ear_r:
            ref_head = ((ear_l[0] + ear_r[0]) // 2, (ear_l[1] + ear_r[1]) // 2)
        elif eye_l and eye_r:
            ref_head = ((eye_l[0] + eye_r[0]) // 2, (eye_l[1] + eye_r[1]) // 2)
        elif nose:
            ref_head = nose

        if ref_head:
            dx = ref_head[0] - mid_shoulder[0]
            dy = ref_head[1] - mid_shoulder[1]
            dist = math.hypot(dx, dy)
            if dist > 1e-3:
                ux, uy = dx / dist, dy / dist
            else:
                ux, uy = 0.0, -1.0
        else:
            ux, uy = 0.0, -1.0

        px, py = -uy, ux

        if ear_l and ear_r:
            cranial_center = ((ear_l[0] + ear_r[0]) // 2, (ear_l[1] + ear_r[1]) // 2)
        elif eye_l and eye_r:
            eye_mid = ((eye_l[0] + eye_r[0]) // 2, (eye_l[1] + eye_r[1]) // 2)
            cranial_center = (
                int(round(eye_mid[0] + ux * (shoulder_dist * 0.05))),
                int(round(eye_mid[1] + uy * (shoulder_dist * 0.05))),
            )
        elif nose:
            cranial_center = (
                int(round(nose[0] + ux * (shoulder_dist * 0.14))),
                int(round(nose[1] + uy * (shoulder_dist * 0.14))),
            )
        else:
            cranial_center = (
                int(round(mid_shoulder[0] + ux * (shoulder_dist * 0.45))),
                int(round(mid_shoulder[1] + uy * (shoulder_dist * 0.45))),
            )

        axis_x = max(5, int(shoulder_dist * 0.18))
        axis_y = max(7, int(shoulder_dist * 0.24))
        tilt_deg = math.degrees(math.atan2(uy, ux)) + 90.0

        cv2.ellipse(mask, cranial_center, (axis_x, axis_y), tilt_deg, 0, 360, 255, -1)

        if mouth_l and mouth_r:
            mid_mouth = ((mouth_l[0] + mouth_r[0]) // 2, (mouth_l[1] + mouth_r[1]) // 2)
            chin = (
                int(round(mid_mouth[0] - ux * (shoulder_dist * 0.05))),
                int(round(mid_mouth[1] - uy * (shoulder_dist * 0.05))),
            )
        elif nose:
            chin = (
                int(round(nose[0] - ux * (shoulder_dist * 0.12))),
                int(round(nose[1] - uy * (shoulder_dist * 0.12))),
            )
        else:
            chin = (
                int(round(cranial_center[0] - ux * (axis_y * 1.10))),
                int(round(cranial_center[1] - uy * (axis_y * 1.10))),
            )

        jaw_l = (
            int(round(cranial_center[0] - px * (axis_x * 0.85) - ux * (axis_y * 0.15))),
            int(round(cranial_center[1] - py * (axis_x * 0.85) - uy * (axis_y * 0.15))),
        )
        jaw_r = (
            int(round(cranial_center[0] + px * (axis_x * 0.85) - ux * (axis_y * 0.15))),
            int(round(cranial_center[1] + py * (axis_x * 0.85) - uy * (axis_y * 0.15))),
        )

        chin_w = max(3, int(axis_x * 0.35))
        chin_l = (int(round(chin[0] - px * chin_w)), int(round(chin[1] - py * chin_w)))
        chin_r = (int(round(chin[0] + px * chin_w)), int(round(chin[1] + py * chin_w)))

        jaw_poly = np.array([jaw_l, jaw_r, chin_r, chin_l], dtype=np.int32)
        cv2.fillConvexPoly(mask, jaw_poly, 255)

        neck_top = (
            int(round(chin[0] + ux * (axis_y * 0.20))),
            int(round(chin[1] + uy * (axis_y * 0.20))),
        )
        neck_thick = max(4, int(shoulder_dist * 0.15))
        cv2.line(mask, mid_shoulder, neck_top, 255, neck_thick, cv2.LINE_AA)
    elif nose:
        r = max(7, int(20.0 * scale_factor))
        cran_y = max(0, int(nose[1] - r * 0.4))
        cv2.ellipse(mask, (nose[0], cran_y), (int(r * 0.8), r), 0, 0, 360, 255, -1)


def _draw_limb_capsules(mask: np.ndarray, ls, rs, pt, scale_factor: float):
    """Draws proportional anatomical limb capsules for arms, hands, thighs, calves, and feet."""
    if ls and rs:
        sh_w = max(10.0 * scale_factor, math.hypot(rs[0] - ls[0], rs[1] - ls[1]))
        thick_arm = max(6, int(sh_w * 0.22))
        thick_forearm = max(5, int(sh_w * 0.18))
        thick_hand = max(4, int(sh_w * 0.15))
        thick_thigh = max(8, int(sh_w * 0.28))
        thick_calf = max(7, int(sh_w * 0.22))
        thick_foot = max(6, int(sh_w * 0.18))
    else:
        thick_arm = max(8, int(18 * scale_factor))
        thick_forearm = max(6, int(14 * scale_factor))
        thick_hand = max(5, int(12 * scale_factor))
        thick_thigh = max(10, int(22 * scale_factor))
        thick_calf = max(8, int(18 * scale_factor))
        thick_foot = max(6, int(14 * scale_factor))

    limbs = (
        (11, 13, thick_arm),
        (13, 15, thick_forearm),
        (15, 19, thick_hand),
        (12, 14, thick_arm),
        (14, 16, thick_forearm),
        (16, 20, thick_hand),
        (23, 25, thick_thigh),
        (25, 27, thick_calf),
        (27, 31, thick_foot),
        (24, 26, thick_thigh),
        (26, 28, thick_calf),
        (28, 32, thick_foot),
    )

    for idx_a, idx_b, thick in limbs:
        pa, pb = pt(idx_a), pt(idx_b)
        if pa and pb:
            cv2.line(mask, pa, pb, 255, thick, cv2.LINE_AA)
            cv2.circle(mask, pa, max(2, thick // 2), 255, -1)
            cv2.circle(mask, pb, max(2, thick // 2), 255, -1)


def build_body_mask(norm_landmarks, width: int, height: int) -> np.ndarray:
    """
    Builds an anatomical silhouette mask from 33 MediaPipe pose landmarks.
    Connects torso polygon, head circle, neck, and limb capsules.
    Resilient to partial body / desk framing by synthesizing torso down to bottom frame.
    """
    mask = np.zeros((height, width), dtype=np.uint8)
    scale_factor = min(width, height) / 480.0

    def pt(idx: int):
        if idx < len(norm_landmarks):
            lm = norm_landmarks[idx]
            vis = getattr(lm, "visibility", 1.0)
            pres = getattr(lm, "presence", 1.0)
            if min(vis, pres) >= 0.15:
                return (int(round(lm.x * width)), int(round(lm.y * height)))
        return None

    ls, rs = pt(11), pt(12)
    lh, rh = pt(23), pt(24)

    _draw_torso_polygon(mask, ls, rs, lh, rh, width, height, scale_factor)
    _draw_head_jaw_neck(mask, ls, rs, pt, scale_factor)
    _draw_limb_capsules(mask, ls, rs, pt, scale_factor)

    # Smooth and fuse into a continuous player contour
    kernel = MORPH_KERNEL_SMALL if width <= 360 else MORPH_KERNEL_LARGE
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.dilate(mask, kernel, iterations=1)
    return mask


__all__ = [
    "MORPH_KERNEL_SMALL",
    "MORPH_KERNEL_LARGE",
    "extract_joints_2d",
    "build_body_mask",
]
