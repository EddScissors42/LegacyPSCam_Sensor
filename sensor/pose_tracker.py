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
    apply_slot_snap, FaceFollowPTZ
)


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
