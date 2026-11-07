"""
Pose Tracking Engine for Legacy Sensor Lite.
Uses MediaPipe Pose Tasks API with custom Hand Anchor Filtering,
Adaptive Dynamic EMA Smoothing, Height Normalization, and 20-joint Kinect v1 mapping.
"""
import math
import time
from pathlib import Path
import numpy as np
import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

def _resolve_model_path() -> Path:
    base = Path(__file__).resolve().parent
    candidates = [
        base / "models" / "pose_landmarker_lite.task",
        base.parent / "models" / "pose_landmarker_lite.task",
        base.parent / "assets" / "models" / "pose_landmarker_lite.task",
    ]
    for c in candidates:
        if c.exists():
            return c
    return base.parent / "models" / "pose_landmarker_lite.task"

DEFAULT_MODEL_PATH = _resolve_model_path()

# MediaPipe 33 Landmark Constants
NOSE = 0
LEFT_EYE_INNER = 1
LEFT_EYE = 2
LEFT_EYE_OUTER = 3
RIGHT_EYE_INNER = 4
RIGHT_EYE = 5
RIGHT_EYE_OUTER = 6
LEFT_EAR = 7
RIGHT_EAR = 8
MOUTH_LEFT = 9
MOUTH_RIGHT = 10
LEFT_SHOULDER = 11
RIGHT_SHOULDER = 12
LEFT_ELBOW = 13
RIGHT_ELBOW = 14
LEFT_WRIST = 15
RIGHT_WRIST = 16
LEFT_PINKY = 17
RIGHT_PINKY = 18
LEFT_INDEX = 19
RIGHT_INDEX = 20
LEFT_THUMB = 21
RIGHT_THUMB = 22
LEFT_HIP = 23
RIGHT_HIP = 24
LEFT_KNEE = 25
RIGHT_KNEE = 26
LEFT_ANKLE = 27
RIGHT_ANKLE = 28
LEFT_HEEL = 29
RIGHT_HEEL = 30
LEFT_FOOT_INDEX = 31
RIGHT_FOOT_INDEX = 32

# Kinect v1 Skeleton Connection Pairs (for drawing and kinematic checks)
KINECT_CONNECTIONS = [
    # Torso & Head
    (0, 1),   # HipCenter -> Spine
    (1, 2),   # Spine -> ShoulderCenter
    (2, 3),   # ShoulderCenter -> Head
    # Left Arm
    (2, 4),   # ShoulderCenter -> ShoulderLeft
    (4, 5),   # ShoulderLeft -> ElbowLeft
    (5, 6),   # ElbowLeft -> WristLeft
    (6, 7),   # WristLeft -> HandLeft
    # Right Arm
    (2, 8),   # ShoulderCenter -> ShoulderRight
    (8, 9),   # ShoulderRight -> ElbowRight
    (9, 10),  # ElbowRight -> WristRight
    (10, 11), # WristRight -> HandRight
    # Left Leg
    (0, 12),  # HipCenter -> HipLeft
    (12, 13), # HipLeft -> KneeLeft
    (13, 14), # KneeLeft -> AnkleLeft
    (14, 15), # AnkleLeft -> FootLeft
    # Right Leg
    (0, 16),  # HipCenter -> HipRight
    (16, 17), # HipRight -> KneeRight
    (17, 18), # KneeRight -> AnkleRight
    (18, 19), # AnkleRight -> FootRight
]

# Extremity joints get higher responsiveness
EXTREMITY_JOINTS = {6, 7, 10, 11, 14, 15, 18, 19}

def avg(a, b):
    return tuple((a[i] + b[i]) * 0.5 for i in range(4))

def lerp(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(4))

class HandAnchorFilter:
    """
    Extrapolates hand position along the forearm (elbow -> wrist) vector
    when MediaPipe finger landmark loses confidence or becomes noisy.
    """
    def __init__(self, hand_length=0.12):
        self.hand_length = hand_length

    def apply(self, joints):
        # joints is list of 20 elements: (x, y, z, conf)
        out = list(joints)
        sides = [
            (5, 6, 7),   # Left: ElbowLeft, WristLeft, HandLeft
            (9, 10, 11)  # Right: ElbowRight, WristRight, HandRight
        ]

        for ei, wi, hi in sides:
            el = out[ei]
            wr = out[wi]
            hd = out[hi]

            # Vector from elbow to wrist
            dx = wr[0] - el[0]
            dy = wr[1] - el[1]
            dz = wr[2] - el[2]
            dist = math.sqrt(dx * dx + dy * dy + dz * dz)

            if dist > 0.001:
                ux = dx / dist
                uy = dy / dist
                uz = dz / dist
                extrapolated = (
                    wr[0] + ux * self.hand_length,
                    wr[1] + uy * self.hand_length,
                    wr[2] + uz * self.hand_length,
                    wr[3]
                )

                # If original hand confidence is weak, prefer extrapolated
                hand_conf = hd[3]
                if hand_conf < 0.45:
                    out[hi] = extrapolated
                else:
                    # Blend
                    blend = min(1.0, max(0.0, (hand_conf - 0.45) / 0.35))
                    out[hi] = lerp(extrapolated, hd, blend)
        return out

    def apply_pixel(self, px_joints):
        """Extrapolates 2D pixel hand positions along the forearm vector."""
        out = list(px_joints)
        sides = [
            (5, 6, 7),   # Left: Elbow, Wrist, Hand
            (9, 10, 11)  # Right: Elbow, Wrist, Hand
        ]
        for ei, wi, hi in sides:
            el = out[ei]
            wr = out[wi]
            hd = out[hi]
            dx = wr[0] - el[0]
            dy = wr[1] - el[1]
            dist = math.hypot(dx, dy)
            if dist > 2:
                ux = dx / dist
                uy = dy / dist
                hand_len = max(10.0, dist * 0.35)
                extrap_x = int(round(wr[0] + ux * hand_len))
                extrap_y = int(round(wr[1] + uy * hand_len))
                extrapolated = (extrap_x, extrap_y, wr[2])
                hand_conf = hd[2]
                if hand_conf < 0.45:
                    out[hi] = extrapolated
                else:
                    blend = min(1.0, max(0.0, (hand_conf - 0.45) / 0.35))
                    blend_x = int(round(extrap_x + (hd[0] - extrap_x) * blend))
                    blend_y = int(round(extrap_y + (hd[1] - extrap_y) * blend))
                    out[hi] = (blend_x, blend_y, hd[2])
        return out

class AdaptiveSmoother:
    """
    Dynamic Exponential Moving Average (EMA) filter.
    Higher smoothing (lower alpha) on stationary poses to eliminate jitter;
    Lower smoothing (higher alpha) on fast dance gestures for zero latency.
    """
    def __init__(self, base_alpha=0.55, alpha_fast=0.92, speed_threshold=0.15):
        self.base_alpha = float(base_alpha)
        self.alpha_fast = float(alpha_fast)
        self.speed_threshold = float(speed_threshold)
        self.prev_joints = None

    def reset(self):
        self.prev_joints = None

    def update_base_alpha(self, alpha):
        self.base_alpha = float(alpha)

    def apply(self, joints):
        if self.prev_joints is None or len(self.prev_joints) != len(joints):
            self.prev_joints = [tuple(j) for j in joints]
            return self.prev_joints

        smoothed = []
        for i, (curr, prev) in enumerate(zip(joints, self.prev_joints)):
            # Calculate 3D velocity
            dx = curr[0] - prev[0]
            dy = curr[1] - prev[1]
            dz = curr[2] - prev[2]
            speed = math.sqrt(dx * dx + dy * dy + dz * dz)

            # Ratio of speed over threshold
            ratio = min(1.0, max(0.0, speed / self.speed_threshold))
            alpha = self.base_alpha + ratio * (self.alpha_fast - self.base_alpha)

            # Boost extremities for snappy hand & foot movements
            if i in EXTREMITY_JOINTS:
                alpha = min(0.96, alpha * 1.25)

            new_x = prev[0] + alpha * (curr[0] - prev[0])
            new_y = prev[1] + alpha * (curr[1] - prev[1])
            new_z = prev[2] + alpha * (curr[2] - prev[2])
            new_conf = curr[3]
            smoothed.append((new_x, new_y, new_z, new_conf))

        self.prev_joints = smoothed
        return smoothed

class SkeletonCalibrator:
    """
    Calibrates skeleton height and coordinate frame to match Just Dance Kinect v1 expectations.
    - MediaPipe Y is positive downwards -> Inverted to positive upwards.
    - Hip Center is mapped to Y = 0.0m.
    - Depth baseline is placed at Z = 2.0m.
    - Height normalized to target_height_m (default 1.75m).
    - Multi-Tier Calibration:
        Tier 1: Full-body (Head to Ankles)
        Tier 2: Flexible Torso (Head to Hips)
        Tier 3: Upper-Body / Desk framing (Head to Shoulders)
    """
    def __init__(self, target_height_m=1.75, cfg=None):
        self.target_height_m = float(target_height_m)
        self.cfg = cfg or {}
        self.is_calibrated = False
        self.calibration_tier = "none"  # "full_body", "flexible_torso", "upper_body"
        self.scale = 1.15               # Default human proportion scale
        self.origin = [0.0, 0.0, 0.0]

    def reset(self):
        self.is_calibrated = False
        self.calibration_tier = "none"
        self.scale = 1.15
        self.origin = [0.0, 0.0, 0.0]

    def calibrate(self, joints, legs_visible=True, hips_visible=True):
        # joints: list of 20 (x, y, z, conf)
        head = joints[3]
        hip = joints[0]
        sh_c = joints[2]
        sh_l = joints[4]
        sh_r = joints[8]
        ank_l = joints[14]
        ank_r = joints[18]

        # Synthesize shoulder center if not provided directly
        if (sh_c[3] < 0.25 or sh_c[2] > 10.0) and sh_l[3] >= 0.25 and sh_r[3] >= 0.25:
            sh_c = (
                (sh_l[0] + sh_r[0]) * 0.5,
                (sh_l[1] + sh_r[1]) * 0.5,
                (sh_l[2] + sh_r[2]) * 0.5,
                min(sh_l[3], sh_r[3])
            )

        # Tier 1: Full-body (Ankles visible & detected)
        if legs_visible and head[3] >= 0.25 and ank_l[3] >= 0.25 and ank_r[3] >= 0.25:
            ank_mid = (
                (ank_l[0] + ank_r[0]) * 0.5,
                (ank_l[1] + ank_r[1]) * 0.5,
                (ank_l[2] + ank_r[2]) * 0.5
            )
            raw_height = math.sqrt(
                (head[0] - ank_mid[0])**2 +
                (head[1] - ank_mid[1])**2 +
                (head[2] - ank_mid[2])**2
            )
            if 0.6 <= raw_height <= 2.8:
                self.scale = self.target_height_m / raw_height
                self.origin = [hip[0], hip[1], hip[2]]
                self.is_calibrated = True
                self.calibration_tier = "full_body"
                return True

        # Tier 2: Flexible Torso (Head + Hips visible, ankles occluded/out of frame)
        if hips_visible and head[3] >= 0.25 and hip[3] >= 0.25:
            torso = math.sqrt(
                (sh_c[0] - hip[0])**2 +
                (sh_c[1] - hip[1])**2 +
                (sh_c[2] - hip[2])**2
            )
            head_to_hip = math.sqrt(
                (head[0] - hip[0])**2 +
                (head[1] - hip[1])**2 +
                (head[2] - hip[2])**2
            )
            raw_height = max(torso * 3.05, head_to_hip * 1.95)
            if 0.5 <= raw_height <= 3.0:
                self.scale = self.target_height_m / raw_height
                self.origin = [hip[0], hip[1], hip[2]]
                self.is_calibrated = True
                self.calibration_tier = "flexible_torso"
                return True

        # Tier 3: Upper-Body / Desk framing (Head + Shoulders visible)
        if head[3] >= 0.25 and sh_l[3] >= 0.25 and sh_r[3] >= 0.25:
            sh_w = math.sqrt(
                (sh_r[0] - sh_l[0])**2 +
                (sh_r[1] - sh_l[1])**2 +
                (sh_r[2] - sh_l[2])**2
            )
            head_to_sh = math.sqrt(
                (head[0] - sh_c[0])**2 +
                (head[1] - sh_c[1])**2 +
                (head[2] - sh_c[2])**2
            )
            raw_height = max(sh_w * 4.6, head_to_sh * 4.0)
            if 0.4 <= raw_height <= 3.2:
                self.scale = self.target_height_m / raw_height
                if hips_visible and hip[3] >= 0.25:
                    self.origin = [hip[0], hip[1], hip[2]]
                else:
                    self.origin = [sh_c[0], sh_c[1] + 0.45 / self.scale, sh_c[2]]
                self.is_calibrated = True
                self.calibration_tier = "upper_body"
                return True

        return False

    def transform(self, joints):
        out = []
        hip = joints[0]
        if self.is_calibrated:
            origin_x, origin_y, origin_z = self.origin
            scale = self.scale
        else:
            origin_x, origin_y, origin_z = hip[0], hip[1], hip[2]
            scale = self.target_height_m / 1.55

        hip_h = float(self.cfg.get('hip_height_m', 1.0))
        baseline_z = float(self.cfg.get('baseline_z_m', 2.0))
        depth_gain = float(self.cfg.get('depth_gain', 0.65))

        for j in joints:
            x, y, z, conf = j
            # Invert X: MediaPipe world X (positive to person's left) -> Kinect camera X (positive to sensor right)
            # Invert Y: MediaPipe Y down -> Kinect Y up + human hip height baseline
            k_x = -(x - origin_x) * scale
            k_y = -(y - origin_y) * scale + hip_h
            k_z = baseline_z + (z - origin_z) * scale * depth_gain
            out.append((k_x, k_y, k_z, conf))
        return out

class CameraSpaceXTracker:
    """
    Tracks player horizontal movement in 2D camera normalized coordinates
    and computes the lateral offset (dx in meters) to translate the 3D skeleton.
    This enables dynamic dancer slot selection (Slots 1, 2, 3, 4) in Just Dance PC.
    """
    def __init__(self, cfg=None):
        self.cfg = cfg or {}
        self.offset = 0.0
        self.valid = False

    def reset(self):
        self.offset = 0.0
        self.valid = False

    def update(self, norm):
        if not self.cfg.get('camera_x_slot_tracking', True):
            return 0.0
        try:
            # MediaPipe normalized landmarks: LEFT_HIP = 23, RIGHT_HIP = 24
            # If hips are visible and within frame, use hip center
            has_hips = (
                len(norm) > RIGHT_HIP and
                getattr(norm[LEFT_HIP], 'visibility', 1.0) >= 0.25 and
                getattr(norm[RIGHT_HIP], 'visibility', 1.0) >= 0.25
            )
            if has_hips:
                cam_x = (float(norm[LEFT_HIP].x) + float(norm[RIGHT_HIP].x)) * 0.5
            elif len(norm) > RIGHT_SHOULDER:
                # Partial-body fallback: use shoulder center
                cam_x = (float(norm[LEFT_SHOULDER].x) + float(norm[RIGHT_SHOULDER].x)) * 0.5
            else:
                return self.offset if self.valid else 0.0

            # When facing the camera: stepping to player's right moves player towards left of camera frame (cam_x < 0.5).
            # In Kinect space, positive X is to player's right.
            # So (0.5 - cam_x) yields positive offset for player's right, negative for player's left.
            if self.cfg.get('camera_x_reverse_for_coach_selection', True):
                centered = 0.5 - cam_x
            else:
                centered = cam_x - 0.5

            dz = float(self.cfg.get('camera_x_deadzone', 0.025))
            if abs(centered) < dz:
                centered = 0.0
            else:
                sign = 1.0 if centered > 0 else -1.0
                centered = (abs(centered) - dz) * sign

            target = centered * float(self.cfg.get('camera_x_range_m', 2.2))

            if self.cfg.get('coach_assist_enabled', True):
                target = target * float(self.cfg.get('coach_assist_multiplier', 1.25))
                max_m = float(self.cfg.get('coach_assist_max_m', 1.20))
                target = float(np.clip(target, -max_m, max_m))

            alpha = float(np.clip(float(self.cfg.get('camera_x_smoothing', 0.42)), 0.05, 1.0))
            if not self.valid:
                self.offset = target
                self.valid = True
            else:
                self.offset = self.offset * (1.0 - alpha) + target * alpha

            return self.offset
        except Exception:
            return self.offset if self.valid else 0.0

def apply_camera_space_translation(joints, norm, tracker, cfg=None):
    """
    Translates all 20 joints in Kinect space by the lateral camera-space offset dx.
    Preserves relative internal skeleton geometry while shifting the player horizontally.
    """
    if not joints or tracker is None:
        return joints
    dx = tracker.update(norm)
    if abs(dx) < 1e-5:
        return joints
    arr = np.array(joints, dtype=np.float32)
    arr[:, 0] += dx
    return [tuple(map(float, row)) for row in arr]

def apply_slot_snap(joints, cfg=None):
    """
    Make HipCenter X more decisive for Legacy's coach-slot assignment.

    Keeps full-body relative pose intact and shifts the whole skeleton together,
    so scoring geometry remains unchanged while player selection becomes less
    ambiguous near slot boundaries.
    """
    if cfg is not None and not cfg.get('slot_snap_enabled', True):
        return joints
    if not joints:
        return joints
    arr = np.array(joints, dtype=np.float32)
    hip_x = float(arr[0, 0])
    gain = float(cfg.get('slot_snap_gain', 1.25)) if cfg else 1.25
    dead = float(cfg.get('slot_snap_deadzone', 0.06)) if cfg else 0.06
    if abs(hip_x) <= dead:
        target_x = hip_x
    else:
        target_x = hip_x * gain
    dx = target_x - hip_x
    arr[:, 0] += dx
    return [tuple(map(float, row)) for row in arr]

class FaceFollowPTZ:
    """
    Software Pan-Tilt-Zoom (PTZ) auto-framing filter.
    Smoothly tracks the player's face landmarks and centers/zooms the video frame
    and player segmentation mask sent to Just Dance via shared memory (Local\\LegacyWebcamKinectImage).
    Ensures the player's face avatar on the dancer selection screen is crisp, focused, and centered.
    """
    def __init__(self, cfg=None):
        self.cfg = cfg or {}
        self.cx = 0.5
        self.cy = 0.38
        self.valid = False

    def reset(self):
        self.cx = 0.5
        self.cy = 0.38
        self.valid = False

    def update_from_norm(self, norm_landmarks, mirrored=True):
        if not norm_landmarks:
            return
        candidates = []
        for idx in (NOSE, LEFT_EAR, RIGHT_EAR):
            if idx < len(norm_landmarks):
                lm = norm_landmarks[idx]
                vis = float(getattr(lm, 'visibility', 1.0))
                pres = float(getattr(lm, 'presence', 1.0))
                if min(vis, pres) >= 0.18:
                    x = 1.0 - float(lm.x) if mirrored else float(lm.x)
                    y = float(lm.y)
                    candidates.append((x, y))
        if candidates:
            tx = sum(c[0] for c in candidates) / len(candidates)
            ty = sum(c[1] for c in candidates) / len(candidates)
            # Apply slight vertical bias so head & hair are comfortably framed in avatar box
            ty += float(self.cfg.get('face_follow_y_bias', 0.06))
            tx = float(np.clip(tx, 0.0, 1.0))
            ty = float(np.clip(ty, 0.0, 1.0))
            a = float(np.clip(float(self.cfg.get('face_follow_smoothing', 0.20)), 0.02, 1.0))
            if not self.valid:
                self.cx = tx
                self.cy = ty
                self.valid = True
            else:
                self.cx = self.cx * (1.0 - a) + tx * a
                self.cy = self.cy * (1.0 - a) + ty * a

    def apply(self, frame, mask=None):
        if not self.cfg.get('face_follow_enabled', True):
            return frame, mask
        if not self.valid or frame is None:
            return frame, mask
        h, w = frame.shape[:2]
        zoom = max(1.0, float(self.cfg.get('face_follow_zoom', 1.22)))
        if abs(zoom - 1.0) < 0.01:
            return frame, mask
        crop_w = max(160, int(w / zoom))
        crop_h = max(120, int(h / zoom))
        center_x = int(self.cx * w)
        center_y = int(self.cy * h)
        x0 = int(np.clip(center_x - crop_w // 2, 0, w - crop_w))
        y0 = int(np.clip(center_y - crop_h // 2, 0, h - crop_h))
        x1 = x0 + crop_w
        y1 = y0 + crop_h

        out_frame = cv2.resize(frame[y0:y1, x0:x1], (w, h), interpolation=cv2.INTER_LINEAR)
        out_mask = None
        if mask is not None:
            out_mask = cv2.resize(mask[y0:y1, x0:x1], (mask.shape[1], mask.shape[0]), interpolation=cv2.INTER_NEAREST)
        return out_frame, out_mask

class PoseTracker:
    """
    High-level Pose Tracking Engine wrapping MediaPipe Pose Tasks API,
    hand anchor filtering, smoothing, and Kinect calibration.
    """
    def __init__(self, model_path=None, detection_confidence=0.5, smoothing_alpha=0.55, target_height_m=1.75, cfg=None):
        self.model_path = Path(model_path) if model_path else DEFAULT_MODEL_PATH
        if not self.model_path.exists():
            raise FileNotFoundError(f"Modelo do MediaPipe não encontrado: {self.model_path}")

        self.cfg = dict(cfg) if cfg else {}
        self.detection_confidence = float(detection_confidence)
        self.detector = None
        self._init_detector()

        self.hand_filter = HandAnchorFilter(hand_length=0.12)
        self.smoother = AdaptiveSmoother(base_alpha=smoothing_alpha)
        self.calibrator = SkeletonCalibrator(target_height_m=target_height_m, cfg=self.cfg)
        self.camera_x_tracker = CameraSpaceXTracker(cfg=self.cfg)
        self.face_ptz = FaceFollowPTZ(cfg=self.cfg)
        self.last_norm_landmarks = None
        self.start_time = time.time()
        self.frame_index = 0
        self.last_timestamp_ms = 0

    def _init_detector(self):
        base_options = python.BaseOptions(model_asset_path=str(self.model_path))
        det_c = min(0.45, self.detection_confidence)
        pres_c = min(0.35, self.detection_confidence)
        options = vision.PoseLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.VIDEO,
            num_poses=1,
            min_pose_detection_confidence=det_c,
            min_pose_presence_confidence=pres_c,
            min_tracking_confidence=pres_c,
            output_segmentation_masks=True
        )
        self.detector = vision.PoseLandmarker.create_from_options(options)
        print("[TRACKER] MediaPipe Pose Landmarker successfully initialized.")

    def update_settings(self, smoothing_alpha=None, detection_confidence=None, target_height_m=None, cfg=None):
        if cfg is not None:
            self.cfg.update(cfg)
            self.calibrator.cfg = self.cfg
            self.camera_x_tracker.cfg = self.cfg
            self.face_ptz.cfg = self.cfg
        if smoothing_alpha is not None:
            self.smoother.update_base_alpha(smoothing_alpha)
        if target_height_m is not None:
            self.calibrator.target_height_m = float(target_height_m)
            self.calibrator.reset()
        if detection_confidence is not None and abs(self.detection_confidence - detection_confidence) > 0.05:
            self.detection_confidence = float(detection_confidence)
            self.close()
            self._init_detector()

    def recalibrate(self):
        self.calibrator.reset()
        self.smoother.reset()
        self.camera_x_tracker.reset()
        self.face_ptz.reset()

    def build_body_mask(self, norm_landmarks, width, height):
        """
        Builds an anatomical silhouette mask from 33 MediaPipe pose landmarks.
        Connects torso polygon, head circle, neck, and limb capsules.
        Resilient to partial body / desk framing by synthesizing torso down to bottom frame.
        """
        mask = np.zeros((height, width), dtype=np.uint8)

        def pt(idx):
            if idx < len(norm_landmarks):
                lm = norm_landmarks[idx]
                vis = getattr(lm, 'visibility', 1.0)
                pres = getattr(lm, 'presence', 1.0)
                if min(vis, pres) >= 0.15:
                    return (int(round(lm.x * width)), int(round(lm.y * height)))
            return None

        # 1. Torso polygon (Left Shoulder 11, Right Shoulder 12, Right Hip 24, Left Hip 23)
        ls, rs = pt(11), pt(12)
        lh, rh = pt(23), pt(24)

        if ls and rs:
            sh_w = max(20.0, math.hypot(rs[0] - ls[0], rs[1] - ls[1]))
            torso_h = int(sh_w * 1.45)
            bottom_y = min(height - 1, int(max(ls[1], rs[1]) + torso_h))

            # If hips are occluded or out of frame, synthesize torso base
            if not lh or lh[1] >= height - 2:
                lh = (max(0, int(ls[0] - 0.10 * (rs[0] - ls[0]))), bottom_y)
            if not rh or rh[1] >= height - 2:
                rh = (min(width - 1, int(rs[0] + 0.10 * (rs[0] - ls[0]))), bottom_y)

            torso_pts = np.array([ls, rs, rh, lh], dtype=np.int32)
            cv2.fillConvexPoly(mask, torso_pts, 255)

            # If torso reaches near bottom, fill down to boundary for seamless HUD silhouette
            if bottom_y >= height - 6:
                bot_poly = np.array([lh, rh, (min(width - 1, rh[0] + 15), height - 1), (max(0, lh[0] - 15), height - 1)], dtype=np.int32)
                cv2.fillConvexPoly(mask, bot_poly, 255)

        # 2. Head & Neck
        nose = pt(0)
        if ls and rs:
            shoulder_dist = max(20.0, math.hypot(rs[0] - ls[0], rs[1] - ls[1]))
            head_radius = max(14, int(shoulder_dist * 0.30))
            mid_shoulder = ((ls[0] + rs[0]) // 2, (ls[1] + rs[1]) // 2)
            head_center = nose if nose else (mid_shoulder[0], max(0, mid_shoulder[1] - head_radius))
            cv2.circle(mask, head_center, head_radius, 255, -1)
            cv2.line(mask, mid_shoulder, head_center, 255, max(8, int(shoulder_dist * 0.20)), cv2.LINE_AA)

        # 3. Limbs (Capsules proportional to body size)
        if ls and rs:
            sh_w = max(20.0, math.hypot(rs[0] - ls[0], rs[1] - ls[1]))
            thick_arm = max(12, int(sh_w * 0.22))
            thick_forearm = max(10, int(sh_w * 0.18))
            thick_hand = max(8, int(sh_w * 0.15))
            thick_thigh = max(16, int(sh_w * 0.28))
            thick_calf = max(14, int(sh_w * 0.22))
            thick_foot = max(12, int(sh_w * 0.18))
        else:
            thick_arm = 18
            thick_forearm = 14
            thick_hand = 12
            thick_thigh = 22
            thick_calf = 18
            thick_foot = 14

        limbs = [
            (11, 13, thick_arm), (13, 15, thick_forearm), (15, 19, thick_hand),
            (12, 14, thick_arm), (14, 16, thick_forearm), (16, 20, thick_hand),
            (23, 25, thick_thigh), (25, 27, thick_calf), (27, 31, thick_foot),
            (24, 26, thick_thigh), (26, 28, thick_calf), (28, 32, thick_foot),
        ]

        for idx_a, idx_b, thick in limbs:
            pa, pb = pt(idx_a), pt(idx_b)
            if pa and pb:
                cv2.line(mask, pa, pb, 255, thick, cv2.LINE_AA)
                cv2.circle(mask, pa, thick // 2, 255, -1)
                cv2.circle(mask, pb, thick // 2, 255, -1)

        # 4. Smooth and fuse into a continuous player contour
        kernel = np.ones((7, 7), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        mask = cv2.dilate(mask, kernel, iterations=1)
        return mask

    def process_frame(self, frame_bgr):
        """
        Processes a BGR camera frame.
        Supports full-body and partial-body (waist-up / desk framing) with robust lower-body synthesis.
        Returns:
            tracked (bool): True if pose detected.
            kinect_joints (list): 20 joints in Kinect 3D space (x, y, z, conf).
            pixel_joints (list): 20 joints in pixel coordinates (px, py, conf) for HUD drawing.
            body_mask (np.ndarray): Binary silhouette mask (height, width) with 255 for player.
        """
        h, w = frame_bgr.shape[:2]
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)

        # Milliseconds strictly monotonic timestamp for VIDEO running mode
        self.frame_index += 1
        now_ms = int((time.time() - self.start_time) * 1000)
        timestamp_ms = max(now_ms, self.frame_index)
        if timestamp_ms <= self.last_timestamp_ms:
            timestamp_ms = self.last_timestamp_ms + 1
        self.last_timestamp_ms = timestamp_ms

        result = self.detector.detect_for_video(mp_image, timestamp_ms)

        if not result.pose_world_landmarks or not result.pose_world_landmarks[0]:
            self.smoother.reset()
            self.camera_x_tracker.reset()
            self.face_ptz.reset()
            self.last_norm_landmarks = None
            return False, None, None, None

        world_lm = result.pose_world_landmarks[0]
        norm_lm = result.pose_landmarks[0] if result.pose_landmarks else world_lm
        self.last_norm_landmarks = norm_lm

        # Helper to extract joint tuple: (x, y, z, confidence)
        def get_joint(idx):
            wl = world_lm[idx]
            nl = norm_lm[idx]
            vis = getattr(nl, 'visibility', 1.0)
            pres = getattr(nl, 'presence', 1.0)
            conf = min(1.0, max(0.0, min(vis, pres)))
            return (float(wl.x), float(wl.y), float(wl.z), conf)

        # 2D pixel helper: (px, py, conf)
        def get_pixel(idx):
            nl = norm_lm[idx]
            px = int(nl.x * w)
            py = int(nl.y * h)
            vis = getattr(nl, 'visibility', 1.0)
            pres = getattr(nl, 'presence', 1.0)
            conf = min(1.0, max(0.0, min(vis, pres)))
            return (px, py, conf)

        # 1. Build Raw 20-Joint Kinect skeleton in world coordinates with Partial-Body Synthesis
        sh_l = get_joint(LEFT_SHOULDER)
        sh_r = get_joint(RIGHT_SHOULDER)
        sh_c = avg(sh_l, sh_r)
        sh_w = math.sqrt((sh_r[0] - sh_l[0])**2 + (sh_r[1] - sh_l[1])**2 + (sh_r[2] - sh_l[2])**2)
        sh_w = max(0.28, min(0.65, sh_w))

        ear_center = avg(get_joint(LEFT_EAR), get_joint(RIGHT_EAR))
        nose = get_joint(NOSE)
        head = avg(ear_center, nose)

        # Hips: Check visibility
        raw_hip_l = get_joint(LEFT_HIP)
        raw_hip_r = get_joint(RIGHT_HIP)
        hips_visible = (raw_hip_l[3] >= 0.25 and raw_hip_r[3] >= 0.25)
        torso_len = max(0.38, sh_w * 1.35)

        if hips_visible:
            hip_l = raw_hip_l
            hip_r = raw_hip_r
            hip_center = avg(hip_l, hip_r)
        else:
            # Synthesize hips below shoulders (in MediaPipe world coordinates, Y is positive downwards)
            syn_hip_y = sh_c[1] + torso_len
            syn_conf = max(0.48, min(sh_l[3], sh_r[3]) * 0.85)
            hip_center = (sh_c[0], syn_hip_y, sh_c[2], syn_conf)
            hip_l = (hip_center[0] - sh_w * 0.38, syn_hip_y, hip_center[2], syn_conf)
            hip_r = (hip_center[0] + sh_w * 0.38, syn_hip_y, hip_center[2], syn_conf)

        spine = lerp(hip_center, sh_c, 0.52)

        # Legs: Check visibility
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
            # Synthesize natural standing legs below hips (conf = 0.35 -> Inferred in Kinect10.dll)
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
            hip_center,                     # 0 HipCenter
            spine,                          # 1 Spine
            sh_c,                           # 2 ShoulderCenter
            head,                           # 3 Head
            sh_l,                           # 4 ShoulderLeft
            get_joint(LEFT_ELBOW),          # 5 ElbowLeft
            get_joint(LEFT_WRIST),          # 6 WristLeft
            get_joint(LEFT_INDEX),          # 7 HandLeft
            sh_r,                           # 8 ShoulderRight
            get_joint(RIGHT_ELBOW),         # 9 ElbowRight
            get_joint(RIGHT_WRIST),         # 10 WristRight
            get_joint(RIGHT_INDEX),         # 11 HandRight
            hip_l,                          # 12 HipLeft
            knee_l,                         # 13 KneeLeft
            ank_l,                          # 14 AnkleLeft
            foot_l,                         # 15 FootLeft
            hip_r,                          # 16 HipRight
            knee_r,                         # 17 KneeRight
            ank_r,                          # 18 AnkleRight
            foot_r,                         # 19 FootRight
        ]

        # 2. Hand Anchor Filter (improves dance hand tracking)
        anchored = self.hand_filter.apply(raw_kinect)

        # 3. Auto-calibrate height and origin (full body, flexible torso, or upper body)
        if not self.calibrator.is_calibrated or (self.calibrator.calibration_tier != "full_body" and legs_visible):
            self.calibrator.calibrate(anchored, legs_visible=legs_visible, hips_visible=hips_visible)

        # 4. Transform to Kinect v1 camera coordinate space (with hip height +1.0m)
        kinect_space = self.calibrator.transform(anchored)

        # 4.1 Smooth anatomical gestures first (zero lag on body moves)
        smoothed_kinect = self.smoother.apply(kinect_space)

        # 4.2 Apply lateral camera-space translation for dancer slot selection
        translated = apply_camera_space_translation(smoothed_kinect, norm_lm, self.camera_x_tracker, self.cfg)

        # 4.3 Apply slot snap (decisive slot boundary assignment)
        snapped = apply_slot_snap(translated, self.cfg)

        # 6. Build 2D pixel coordinates for preview drawing
        px_sh_l = get_pixel(LEFT_SHOULDER)
        px_sh_r = get_pixel(RIGHT_SHOULDER)
        px_sh_c = (int((px_sh_l[0] + px_sh_r[0]) * 0.5), int((px_sh_l[1] + px_sh_r[1]) * 0.5), min(px_sh_l[2], px_sh_r[2]))
        sh_w_px = max(20, int(math.hypot(px_sh_r[0] - px_sh_l[0], px_sh_r[1] - px_sh_l[1])))

        if hips_visible:
            px_hip_l = get_pixel(LEFT_HIP)
            px_hip_r = get_pixel(RIGHT_HIP)
            px_hip_c = (int((px_hip_l[0] + px_hip_r[0]) * 0.5), int((px_hip_l[1] + px_hip_r[1]) * 0.5), min(px_hip_l[2], px_hip_r[2]))
        else:
            syn_px_y = min(h - 2, int(px_sh_c[1] + sh_w_px * 1.35))
            px_hip_c = (px_sh_c[0], syn_px_y, px_sh_c[2])
            px_hip_l = (max(0, px_hip_c[0] - int(sh_w_px * 0.38)), syn_px_y, px_sh_c[2])
            px_hip_r = (min(w - 1, px_hip_c[0] + int(sh_w_px * 0.38)), syn_px_y, px_sh_c[2])

        px_spine = (int(px_hip_c[0] + 0.52 * (px_sh_c[0] - px_hip_c[0])), int(px_hip_c[1] + 0.52 * (px_sh_c[1] - px_hip_c[1])), px_sh_c[2])
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

        # Apply 2D forearm anchor filter to keep hand landmarks locked during fast moves
        pixel_joints = self.hand_filter.apply_pixel(pixel_joints)

        # 7. Generate player silhouette mask (Neural mask fused with Anatomical mask)
        neural_mask = None
        if hasattr(result, 'segmentation_masks') and result.segmentation_masks:
            try:
                seg_view = result.segmentation_masks[0].numpy_view()
                neural_mask = (seg_view > 0.22).astype(np.uint8) * 255
                if neural_mask.shape[0] != h or neural_mask.shape[1] != w:
                    neural_mask = cv2.resize(neural_mask, (w, h), interpolation=cv2.INTER_LINEAR)
            except Exception:
                neural_mask = None

        anatomical_mask = self.build_body_mask(norm_lm, w, h)
        if neural_mask is not None:
            body_mask = cv2.bitwise_or(neural_mask, anatomical_mask)
        else:
            body_mask = anatomical_mask

        return True, snapped, pixel_joints, body_mask

    def close(self):
        if self.detector:
            try:
                self.detector.close()
            except Exception:
                pass
            self.detector = None
            print("[TRACKER] MediaPipe Pose Landmarker terminated.")
