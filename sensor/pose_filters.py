"""
Kinematic & Geometric Filters for Legacy PSCam Sensor.
Provides Hand Anchor Extrapolation, Adaptive Dynamic EMA Smoothing,
Multi-Tier Skeleton Height Calibration, Lateral Slot Selection, and FaceFollow PTZ.
"""
import math
import time
import numpy as np
import cv2

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
    Dynamic Exponential Moving Average (EMA) filter with delta-time (dt) normalization.
    Higher smoothing (lower alpha) on stationary poses to eliminate jitter;
    Lower smoothing (higher alpha) on fast dance gestures for zero latency.
    Normalized to a 30 Hz reference tick (dt_ref = 1/30s) so 60 FPS cameras
    and 30 FPS webcams exhibit identical physical velocity response (m/s).
    """
    REF_DT = 1.0 / 30.0

    def __init__(self, base_alpha=0.55, alpha_fast=0.92, speed_threshold=0.15):
        self.base_alpha = float(base_alpha)
        self.alpha_fast = float(alpha_fast)
        self.speed_threshold = float(speed_threshold)
        self.prev_joints = None
        self.last_time = None
        self.prev_pixel_joints = None
        self.last_pixel_time = None

    def reset(self):
        self.prev_joints = None
        self.last_time = None
        self.prev_pixel_joints = None
        self.last_pixel_time = None

    def update_base_alpha(self, alpha):
        self.base_alpha = float(alpha)

    def apply(self, joints, dt=None):
        now = time.perf_counter()
        if self.prev_joints is None or len(self.prev_joints) != len(joints):
            self.prev_joints = [tuple(j) for j in joints]
            self.last_time = now
            return self.prev_joints

        if dt is None:
            if self.last_time is not None:
                raw_dt = now - self.last_time
                # If called in a tight synthetic burst (< 2ms), treat as reference tick
                dt_sec = self.REF_DT if raw_dt < 0.002 else min(0.10, max(0.004, raw_dt))
            else:
                dt_sec = self.REF_DT
        else:
            dt_sec = min(0.10, max(0.004, float(dt)))
        self.last_time = now

        # Velocity scaling factor relative to 30 FPS reference (at 60 FPS, dt_scale ~ 2.0)
        dt_scale = self.REF_DT / dt_sec

        smoothed = []
        for i, (curr, prev) in enumerate(zip(joints, self.prev_joints)):
            # Calculate 3D displacement normalized to reference frame rate (physical velocity)
            dx = curr[0] - prev[0]
            dy = curr[1] - prev[1]
            dz = curr[2] - prev[2]
            disp = math.sqrt(dx * dx + dy * dy + dz * dz)
            norm_speed = disp * dt_scale

            # Ratio of physical speed over threshold
            ratio = min(1.0, max(0.0, norm_speed / self.speed_threshold))
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

    def apply_pixel(self, pixel_joints, frame_w=640, frame_h=480, dt=None):
        """
        Dynamic 2D pixel EMA smoothing for HUD preview skeleton rendering.
        Eliminates visual jitter on stationary poses while keeping fast dance swings instant.
        Normalized both by frame resolution diagonal and delta-time (dt).
        """
        if not pixel_joints:
            return pixel_joints

        now = time.perf_counter()
        if self.prev_pixel_joints is None or len(self.prev_pixel_joints) != len(pixel_joints):
            self.prev_pixel_joints = [(float(p[0]), float(p[1]), float(p[2])) for p in pixel_joints]
            self.last_pixel_time = now
            return [(int(round(p[0])), int(round(p[1])), float(p[2])) for p in pixel_joints]

        if dt is None:
            if self.last_pixel_time is not None:
                raw_dt = now - self.last_pixel_time
                dt_sec = self.REF_DT if raw_dt < 0.002 else min(0.10, max(0.004, raw_dt))
            else:
                dt_sec = self.REF_DT
        else:
            dt_sec = min(0.10, max(0.004, float(dt)))
        self.last_pixel_time = now

        dt_scale = self.REF_DT / dt_sec
        diag = max(320.0, math.hypot(frame_w, frame_h))
        # Speed threshold in normalized screen diagonal units (~5% of screen diagonal per 30Hz tick)
        px_threshold = max(0.025, self.speed_threshold * 0.35)

        smoothed_float = []
        smoothed_int = []
        for i, (curr, prev) in enumerate(zip(pixel_joints, self.prev_pixel_joints)):
            dx = (curr[0] - prev[0]) / diag
            dy = (curr[1] - prev[1]) / diag
            norm_speed = math.hypot(dx, dy) * dt_scale

            ratio = min(1.0, max(0.0, norm_speed / px_threshold))
            alpha = self.base_alpha + ratio * (self.alpha_fast - self.base_alpha)

            if i in EXTREMITY_JOINTS:
                alpha = min(0.96, alpha * 1.25)

            nx = prev[0] + alpha * (curr[0] - prev[0])
            ny = prev[1] + alpha * (curr[1] - prev[1])
            nconf = float(curr[2])
            smoothed_float.append((nx, ny, nconf))
            smoothed_int.append((int(round(nx)), int(round(ny)), nconf))

        self.prev_pixel_joints = smoothed_float
        return smoothed_int


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
        self.stereo_baseline_z = None   # Smoothed metric baseline Z from stereo triangulation
        self._head_z_ema = None         # Stabilized monocular Head Z (prevents Just Dance face box zoom breathing)

    def reset(self):
        self.is_calibrated = False
        self.calibration_tier = "none"
        self.scale = 1.15
        self.origin = [0.0, 0.0, 0.0]
        self.stereo_baseline_z = None
        self._head_z_ema = None

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
            if 1.05 <= raw_height <= 2.8:
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

    def transform(self, joints, stereo_depths=None):
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

        # Ground baseline Z to true physical stereo depth using robust torso median + slew-rate clamp
        # Prevents single-joint stereo outliers (walls/plain shirts) from causing whole-body Z jumps.
        if stereo_depths:
            torso_zs = []
            for j_cand in (0, 1, 2, 3, 4, 8, 12, 16):
                if j_cand in stereo_depths:
                    _, _, cand_z, cand_conf = stereo_depths[j_cand]
                    if cand_conf >= 0.55 and 0.8 <= cand_z <= 4.5:
                        torso_zs.append(float(cand_z))
            if torso_zs:
                ref_z = float(np.median(torso_zs))
                if self.stereo_baseline_z is None:
                    self.stereo_baseline_z = ref_z
                else:
                    # Physical human walk speed clamp (~2.1 m/s at 60 FPS -> max 0.035m per frame)
                    dz = max(-0.035, min(0.035, ref_z - self.stereo_baseline_z))
                    self.stereo_baseline_z = self.stereo_baseline_z + 0.12 * dz
                baseline_z = self.stereo_baseline_z
            elif self.stereo_baseline_z is not None:
                baseline_z = self.stereo_baseline_z

        for idx, j in enumerate(joints):
            x, y, z, conf = j
            # Invert X: MediaPipe world X (positive to person's left) -> Kinect camera X (positive to sensor right)
            # Invert Y: MediaPipe Y down -> Kinect Y up + human hip height baseline
            k_x = -(x - origin_x) * scale
            k_y = -(y - origin_y) * scale + hip_h
            k_z = baseline_z + (z - origin_z) * scale * depth_gain

            # Optional limb-level metric grounding (clamped to anatomical reach ±0.55m around torso)
            if idx != 3 and stereo_depths and idx in stereo_depths:
                s_x, s_y, s_z, s_conf = stereo_depths[idx]
                if s_conf >= 0.60 and 0.8 <= s_z <= 4.5:
                    s_z_clamped = float(np.clip(s_z, baseline_z - 0.55, baseline_z + 0.55))
                    blend_w = min(0.30, s_conf * 0.35)
                    k_z = (1.0 - blend_w) * k_z + blend_w * s_z_clamped

            # ALWAYS stabilize Head(3) Z depth (both monocular AND Stereo Vision):
            # Just Dance PC sizes its built-in face-framing avatar box inversely to Head.z.
            # Unfiltered stereo disparity or monocular breathing causes constant face zoom-in/zoom-out.
            if idx == 3:
                raw_head_dz = float(np.clip((z - origin_z) * scale * (depth_gain * 0.15), -0.08, 0.08))
                target_head_z = baseline_z + raw_head_dz
                if self._head_z_ema is None:
                    self._head_z_ema = target_head_z
                else:
                    diff_h = target_head_z - self._head_z_ema
                    if abs(diff_h) > 0.025:
                        clamped_step = max(-0.015, min(0.015, diff_h))
                        self._head_z_ema = self._head_z_ema + 0.08 * clamped_step
                k_z = self._head_z_ema

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
    Software Pan-Tilt-Zoom (PTZ) auto-framing & Frustum-Aligned Face/Body Follower.
    Smoothly tracks the player's face and full-body envelope, featuring:
      - 360-degree spin fallback (`face_follow_spin_fallback`): extrapolates head position
        from the torso vector (HipCenter -> ShoulderCenter) when face landmarks are occluded.
      - Dynamic Adaptive Full-Body Zoom (`face_follow_adaptive_zoom`): automatically widens
        the framing toward 1.0x when arms/legs stretch near crop edges so the 320x240
        silhouette mask is never clipped, returning to `face_follow_zoom` on standard stances.
      - Center stability deadzone to prevent micro-bobbing jitter.
    """
    def __init__(self, cfg=None):
        self.cfg = cfg or {}
        self.cx = 0.5
        self.cy = 0.38
        self.target_u = 0.5
        self.target_v = 0.25
        self.current_zoom = float(self.cfg.get('face_follow_zoom', 1.22))
        self._zoom_hold_frames = 0
        self.valid = False

    def reset(self):
        self.cx = 0.5
        self.cy = 0.38
        self.target_u = 0.5
        self.target_v = 0.25
        self.current_zoom = float(self.cfg.get('face_follow_zoom', 1.22))
        self._zoom_hold_frames = 0
        self.valid = False

    def update_from_norm(self, norm_landmarks, mirrored=True, kinect_joints=None):
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

        # 360-degree Spin Anatomical Fallback: when player turns their back to the camera
        # and face landmarks drop below visibility, extrapolate head above ShoulderCenter
        if not candidates and bool(self.cfg.get('face_follow_spin_fallback', True)):
            if len(norm_landmarks) > RIGHT_SHOULDER:
                sh_l = norm_landmarks[LEFT_SHOULDER]
                sh_r = norm_landmarks[RIGHT_SHOULDER]
                vis_l = min(float(getattr(sh_l, 'visibility', 1.0)), float(getattr(sh_l, 'presence', 1.0)))
                vis_r = min(float(getattr(sh_r, 'visibility', 1.0)), float(getattr(sh_r, 'presence', 1.0)))
                if min(vis_l, vis_r) >= 0.15:
                    lx = 1.0 - float(sh_l.x) if mirrored else float(sh_l.x)
                    rx = 1.0 - float(sh_r.x) if mirrored else float(sh_r.x)
                    ly, ry = float(sh_l.y), float(sh_r.y)
                    sh_cx = (lx + rx) * 0.5
                    sh_cy = (ly + ry) * 0.5
                    sh_w = max(0.08, math.hypot(rx - lx, ry - ly))

                    # Use torso vector (Hip -> Shoulder) if hips are visible, else vertical offset
                    if len(norm_landmarks) > RIGHT_HIP:
                        hl = norm_landmarks[LEFT_HIP]
                        hr = norm_landmarks[RIGHT_HIP]
                        if min(float(getattr(hl, 'visibility', 1.0)), float(getattr(hr, 'visibility', 1.0))) >= 0.20:
                            hx = ((1.0 - float(hl.x) if mirrored else float(hl.x)) + (1.0 - float(hr.x) if mirrored else float(hr.x))) * 0.5
                            hy = (float(hl.y) + float(hr.y)) * 0.5
                            vx = sh_cx - hx
                            vy = sh_cy - hy
                            candidates.append((sh_cx + vx * 0.42, sh_cy + vy * 0.42))
                    if not candidates:
                        candidates.append((sh_cx, max(0.05, sh_cy - sh_w * 0.55)))

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
                self.current_zoom = max(1.0, float(self.cfg.get('face_follow_zoom', 1.22)))
                self.valid = True
            else:
                # Apply soft central deadzone to suppress micro-bobbing jitter while dancing
                deadzone = float(self.cfg.get('face_follow_deadzone', 0.018))
                disp = math.hypot(tx - self.cx, ty - self.cy)
                eff_a = a * 0.20 if disp < deadzone else a
                self.cx = self.cx * (1.0 - eff_a) + tx * eff_a
                self.cy = self.cy * (1.0 - eff_a) + ty * eff_a

        # Dynamic Adaptive Full-Body Zoom (opt-in; disabled by default to keep framing rock-steady)
        # Uses strict in-frame high-confidence landmarks + hysteresis + hold timer so seated/occluded
        # limbs never cause zoom-in/zoom-out pumping.
        base_zoom = max(1.0, float(self.cfg.get('face_follow_zoom', 1.22)))
        if bool(self.cfg.get('face_follow_adaptive_zoom', False)) and base_zoom > 1.01:
            xs, ys = [], []
            for idx in (NOSE, LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_ELBOW, RIGHT_ELBOW, LEFT_WRIST, RIGHT_WRIST, LEFT_HIP, RIGHT_HIP, LEFT_ANKLE, RIGHT_ANKLE):
                if idx < len(norm_landmarks):
                    lm = norm_landmarks[idx]
                    if min(float(getattr(lm, 'visibility', 1.0)), float(getattr(lm, 'presence', 1.0))) >= 0.55:
                        lx = 1.0 - float(lm.x) if mirrored else float(lm.x)
                        ly = float(lm.y)
                        if 0.0 <= lx <= 1.0 and 0.0 <= ly <= 1.0:
                            xs.append(lx)
                            ys.append(ly)
            if len(xs) >= 3:
                span_x = (max(xs) - min(xs)) + 0.18  # safety breathing margin
                span_y = (max(ys) - min(ys)) + 0.16
                max_span = max(span_x, span_y)
                if max_span > (1.0 / base_zoom):
                    desired_zoom = float(np.clip(1.0 / max(0.5, max_span), 1.0, base_zoom))
                else:
                    desired_zoom = base_zoom

                zoom_diff = desired_zoom - self.current_zoom
                if zoom_diff < -0.025:
                    # Widen promptly when limbs genuinely approach frame edges, and hold
                    self.current_zoom = 0.86 * self.current_zoom + 0.14 * desired_zoom
                    self._zoom_hold_frames = 35
                elif zoom_diff > 0.040:
                    # Return very slowly only after hold cooldown expires (prevents pumping)
                    if self._zoom_hold_frames > 0:
                        self._zoom_hold_frames -= 1
                    else:
                        self.current_zoom = 0.97 * self.current_zoom + 0.03 * desired_zoom
                elif self._zoom_hold_frames > 0:
                    self._zoom_hold_frames -= 1
            else:
                if self._zoom_hold_frames > 0:
                    self._zoom_hold_frames -= 1
                elif abs(base_zoom - self.current_zoom) > 0.040:
                    self.current_zoom = 0.97 * self.current_zoom + 0.03 * base_zoom
        else:
            self.current_zoom = base_zoom

        # Compute exact 2D frustum UV coordinate where Just Dance PC samples the 3D Head(3) joint
        # NuiTransformSkeletonToDepthImage (320x240):
        #   u = 0.5 + (285.63 / 320.0) * (X / Z)
        #   v = 0.5 - (285.63 / 240.0) * (Y_frustum / Z)
        # Just Dance Legacy lowers skeleton Y by the adaptive floor offset (~0.97m) so Head Y_frustum ~ 0.565m.
        if kinect_joints and len(kinect_joints) > 3:
            hx, hy, hz, _ = kinect_joints[3]
            hip_y = float(kinect_joints[0][1])
            z_safe = max(0.8, float(hz))
            # Relative head height above hip in calibrated skeleton (~0.56m..0.72m),
            # matching Just Dance Legacy's internal floor-relative frustum projection
            y_frustum = max(0.15, min(0.75, float(hy) - max(0.0, hip_y - 0.05)))
            tu = 0.5 + (285.63 / 320.0) * (float(hx) / z_safe)
            tv = 0.5 - (285.63 / 240.0) * (y_frustum / z_safe)
            tu = float(np.clip(tu, 0.15, 0.85))
            tv = float(np.clip(tv, 0.14, 0.65))
            deadzone = float(self.cfg.get('face_follow_deadzone', 0.018))
            a_t = float(np.clip(float(self.cfg.get('face_follow_smoothing', 0.20)), 0.05, 1.0))
            disp_t = math.hypot(tu - self.target_u, tv - self.target_v)
            eff_at = a_t * 0.15 if disp_t < deadzone else a_t
            self.target_u = self.target_u * (1.0 - eff_at) + tu * eff_at
            self.target_v = self.target_v * (1.0 - eff_at) + tv * eff_at
        else:
            self.target_u = 0.5
            self.target_v = 0.25

    def apply(self, frame, mask=None):
        if not self.cfg.get('face_follow_enabled', True):
            return frame, mask
        if not self.valid or frame is None:
            return frame, mask
        h, w = frame.shape[:2]
        zoom = max(1.0, float(self.current_zoom))

        # Place detected face (self.cx, self.cy) at the exact frustum UV (self.target_u, self.target_v)
        # where Just Dance PC crops the player avatar square ("quadradinho").
        # Using warpAffine with BORDER_REPLICATE guarantees exact alignment even near frame edges.
        M = np.array([
            [zoom, 0.0, (self.target_u - zoom * self.cx) * w],
            [0.0, zoom, (self.target_v - zoom * self.cy) * h],
        ], dtype=np.float32)
        out_frame = cv2.warpAffine(
            frame, M, (w, h),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE
        )
        out_mask = None
        if mask is not None:
            mh, mw = mask.shape[:2]
            M_mask = np.array([
                [zoom, 0.0, (self.target_u - zoom * self.cx) * mw],
                [0.0, zoom, (self.target_v - zoom * self.cy) * mh],
            ], dtype=np.float32)
            out_mask = cv2.warpAffine(
                mask, M_mask, (mw, mh),
                flags=cv2.INTER_NEAREST,
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=0
            )
        return out_frame, out_mask
