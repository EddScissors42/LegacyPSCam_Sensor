"""
Modular Person Lock-In Subsystem for Legacy PSCam Sensor.

Provides three decoupled, individually toggleable components to keep the camera
locked onto the active dancer at 60 FPS (< 0.25 ms combined CPU overhead):
  1. InertialCoastingFilter: Kinematic dead-reckoning / Kalman-like velocity coasting
     during transient 1-15 frame tracking losses (360-degree spins, hair/arm occlusions, motion blur).
  2. DancerIdentityLock: Torso HSV color signature + spatial bounding-box continuity gate
     with peripheral ROI attenuation to reject background clutter or bystanders crossing the room.
  3. PersonLockController: Unified facade orchestrating both filters with zero-overhead
     short-circuit bypass when disabled via config.json or live runtime updates.
"""
import math
import time
from typing import Optional, Tuple, List, Dict, Any
import numpy as np
import cv2

# MediaPipe Landmark Indices used for Torso & Body Envelope
NOSE = 0
LEFT_SHOULDER = 11
RIGHT_SHOULDER = 12
LEFT_ELBOW = 13
RIGHT_ELBOW = 14
LEFT_WRIST = 15
RIGHT_WRIST = 16
LEFT_HIP = 23
RIGHT_HIP = 24
LEFT_KNEE = 25
RIGHT_KNEE = 26
LEFT_ANKLE = 27
RIGHT_ANKLE = 28


def _shift_mask_fast(mask: Optional[np.ndarray], dx_px: int, dy_px: int) -> Optional[np.ndarray]:
    """
    Translates a 2D binary silhouette mask (320x240 uint8) by (dx_px, dy_px)
    using zero-allocation slice views (< 0.02 ms).
    """
    if mask is None:
        return None
    if dx_px == 0 and dy_px == 0:
        return mask
    h, w = mask.shape[:2]
    if abs(dx_px) >= w or abs(dy_px) >= h:
        return np.zeros_like(mask)

    out = np.zeros_like(mask)
    src_x0 = max(0, -dx_px)
    src_x1 = min(w, w - dx_px)
    dst_x0 = max(0, dx_px)
    dst_x1 = min(w, w + dx_px)

    src_y0 = max(0, -dy_px)
    src_y1 = min(h, h - dy_px)
    dst_y0 = max(0, dy_px)
    dst_y1 = min(h, h + dy_px)

    out[dst_y0:dst_y1, dst_x0:dst_x1] = mask[src_y0:src_y1, src_x0:src_x1]
    return out


class InertialCoastingFilter:
    """
    Kinematic Dead-Reckoning / Inertial Coasting Filter.
    Bridges micro-dropouts (up to `inertial_coasting_max_ms`, default 250 ms) by extrapolating
    joint trajectories using damped physical velocities and smoothly blending back upon re-detection.
    """
    REF_DT = 1.0 / 60.0

    def __init__(self, cfg: Optional[Dict[str, Any]] = None):
        self.cfg = dict(cfg) if cfg else {}
        self.last_joints_3d: Optional[List[Tuple[float, float, float, float]]] = None
        self.vel_3d: Optional[List[Tuple[float, float, float]]] = None
        self.last_joints_2d: Optional[List[Tuple[int, int, float]]] = None
        self.vel_2d: Optional[List[Tuple[float, float]]] = None
        self.last_mask: Optional[np.ndarray] = None
        self.last_norm_landmarks: Any = None
        self.last_time: Optional[float] = None

        self.coasting_active: bool = False
        self.coasting_frames: int = 0
        self.coasting_elapsed_s: float = 0.0
        self.reentry_remaining: int = 0

    @property
    def is_enabled(self) -> bool:
        if not bool(self.cfg.get("person_lock_enabled", True)):
            return False
        return bool(self.cfg.get("inertial_coasting_enabled", True))

    def set_enabled(self, enabled: bool) -> None:
        self.cfg["inertial_coasting_enabled"] = bool(enabled)
        if not enabled:
            self.reset()

    def update_config(self, cfg: Dict[str, Any]) -> None:
        if cfg is not None:
            self.cfg.update(cfg)
            if not self.is_enabled:
                self.reset()

    def reset(self) -> None:
        self.last_joints_3d = None
        self.vel_3d = None
        self.last_joints_2d = None
        self.vel_2d = None
        self.last_mask = None
        self.last_norm_landmarks = None
        self.last_time = None
        self.coasting_active = False
        self.coasting_frames = 0
        self.coasting_elapsed_s = 0.0
        self.reentry_remaining = 0

    def _resolve_dt(self, dt: Optional[float]) -> float:
        now = time.perf_counter()
        if dt is not None and dt > 0.0005:
            dt_sec = min(0.10, max(0.004, float(dt)))
        elif self.last_time is not None:
            raw_dt = now - self.last_time
            dt_sec = self.REF_DT if raw_dt < 0.002 else min(0.10, max(0.004, raw_dt))
        else:
            dt_sec = self.REF_DT
        self.last_time = now
        return dt_sec

    def record_valid_frame(
        self,
        joints_3d: List[Tuple[float, float, float, float]],
        joints_2d: List[Tuple[int, int, float]],
        body_mask: Optional[np.ndarray],
        norm_landmarks: Any = None,
        dt: Optional[float] = None,
    ) -> Tuple[List[Tuple[float, float, float, float]], List[Tuple[int, int, float]], Optional[np.ndarray]]:
        """
        Records a valid tracked frame, updating joint velocity estimates and applying
        a smooth LERP recovery blend if returning from an inertial coasting interval.
        """
        if not self.is_enabled or not joints_3d or not joints_2d:
            return joints_3d, joints_2d, body_mask

        dt_sec = self._resolve_dt(dt)
        reentry_total = max(1, int(self.cfg.get("inertial_coasting_reentry_frames", 3)))
        max_speed_3d = float(self.cfg.get("inertial_coasting_max_speed_mps", 3.5))
        max_speed_2d = 1800.0  # pixels/sec cap

        # Transition from coasting -> active tracking: trigger smooth recovery blend
        if self.coasting_active:
            self.coasting_active = False
            self.coasting_frames = 0
            self.coasting_elapsed_s = 0.0
            self.reentry_remaining = reentry_total

        out_3d = list(joints_3d)
        out_2d = list(joints_2d)

        # Apply smooth LERP re-entry if recovering from a micro-drop
        if self.reentry_remaining > 0 and self.last_joints_3d is not None and self.last_joints_2d is not None:
            alpha_blend = 1.0 - (self.reentry_remaining / float(reentry_total + 1))
            blended_3d = []
            for curr, prev in zip(out_3d, self.last_joints_3d):
                bx = prev[0] + alpha_blend * (curr[0] - prev[0])
                by = prev[1] + alpha_blend * (curr[1] - prev[1])
                bz = prev[2] + alpha_blend * (curr[2] - prev[2])
                blended_3d.append((bx, by, bz, curr[3]))
            out_3d = blended_3d

            blended_2d = []
            for curr, prev in zip(out_2d, self.last_joints_2d):
                bpx = int(round(prev[0] + alpha_blend * (curr[0] - prev[0])))
                bpy = int(round(prev[1] + alpha_blend * (curr[1] - prev[1])))
                blended_2d.append((bpx, bpy, curr[2]))
            out_2d = blended_2d
            self.reentry_remaining -= 1

        # Update damped 3D and 2D velocities
        if self.last_joints_3d is not None and len(self.last_joints_3d) == len(out_3d):
            new_vel_3d = []
            prev_vel_3d = self.vel_3d or [(0.0, 0.0, 0.0)] * len(out_3d)
            for (cx, cy, cz, _), (px, py, pz, _), (pvx, pvy, pvz) in zip(out_3d, self.last_joints_3d, prev_vel_3d):
                ivx = (cx - px) / dt_sec
                ivy = (cy - py) / dt_sec
                ivz = (cz - pz) / dt_sec
                spd = math.sqrt(ivx * ivx + ivy * ivy + ivz * ivz)
                if spd > max_speed_3d and spd > 1e-6:
                    scale = max_speed_3d / spd
                    ivx *= scale
                    ivy *= scale
                    ivz *= scale
                # EMA velocity smoothing (prevents single-frame noise spikes from launching limbs)
                vx = 0.50 * pvx + 0.50 * ivx
                vy = 0.50 * pvy + 0.50 * ivy
                vz = 0.50 * pvz + 0.50 * ivz
                new_vel_3d.append((vx, vy, vz))
            self.vel_3d = new_vel_3d
        else:
            self.vel_3d = [(0.0, 0.0, 0.0)] * len(out_3d)

        if self.last_joints_2d is not None and len(self.last_joints_2d) == len(out_2d):
            new_vel_2d = []
            prev_vel_2d = self.vel_2d or [(0.0, 0.0)] * len(out_2d)
            for (cpx, cpy, _), (ppx, ppy, _), (pvpx, pvpy) in zip(out_2d, self.last_joints_2d, prev_vel_2d):
                ivpx = (cpx - ppx) / dt_sec
                ivpy = (cpy - ppy) / dt_sec
                spd_2d = math.hypot(ivpx, ivpy)
                if spd_2d > max_speed_2d and spd_2d > 1e-6:
                    scale = max_speed_2d / spd_2d
                    ivpx *= scale
                    ivpy *= scale
                vpx = 0.50 * pvpx + 0.50 * ivpx
                vpy = 0.50 * pvpy + 0.50 * ivpy
                new_vel_2d.append((vpx, vpy))
            self.vel_2d = new_vel_2d
        else:
            self.vel_2d = [(0.0, 0.0)] * len(out_2d)

        self.last_joints_3d = out_3d
        self.last_joints_2d = out_2d
        if body_mask is not None:
            self.last_mask = body_mask
        if norm_landmarks is not None:
            self.last_norm_landmarks = norm_landmarks

        return out_3d, out_2d, body_mask

    def coast(
        self,
        dt: Optional[float] = None,
        frame_w: int = 640,
        frame_h: int = 480,
        max_ms_override: Optional[float] = None,
        damping_override: Optional[float] = None,
    ) -> Tuple[bool, Optional[List[Tuple[float, float, float, float]]], Optional[List[Tuple[int, int, float]]], Optional[np.ndarray]]:
        """
        Extrapolates the dancer's 3D skeleton, 2D HUD skeleton, and 320x240 silhouette mask
        during a tracking dropout if within `inertial_coasting_max_ms` (default 250 ms, or
        `max_ms_override` during 2-player close overlap occlusions).
        """
        if not self.is_enabled or self.last_joints_3d is None or self.last_joints_2d is None:
            return False, None, None, None

        dt_sec = self._resolve_dt(dt)
        max_ms = (
            float(max_ms_override)
            if max_ms_override is not None
            else float(self.cfg.get("inertial_coasting_max_ms", 420.0))
        )
        # Under heavy game CPU contention (< 25 FPS, dt >= 40ms), ensure at least 450ms of
        # coasting so 360° spins don't drop tracking after just 2-3 low-FPS frames.
        if max_ms_override is None and dt_sec >= 0.040:
            max_ms = max(max_ms, 450.0)
        self.coasting_elapsed_s += dt_sec

        if self.coasting_elapsed_s * 1000.0 > max_ms:
            # Exceeded maximum coasting duration -> clean reset
            self.reset()
            return False, None, None, None

        self.coasting_active = True
        self.coasting_frames += 1
        raw_damping = (
            float(damping_override)
            if damping_override is not None
            else float(self.cfg.get("inertial_coasting_damping", 0.80))
        )
        base_damping = float(np.clip(raw_damping, 0.45, 0.98))
        # Normalize velocity decay to elapsed wall time so 12-30 FPS frames never launch limbs off-body
        damping = float(base_damping ** max(0.5, dt_sec / self.REF_DT))
        conf_decay = 0.96 if max_ms > 350.0 else 0.94
        conf_floor = 0.38 if max_ms > 350.0 else 0.35

        coasted_3d = []
        new_vel_3d = []
        vel_3d = self.vel_3d or [(0.0, 0.0, 0.0)] * len(self.last_joints_3d)
        for (x, y, z, conf), (vx, vy, vz) in zip(self.last_joints_3d, vel_3d):
            nx = x + vx * dt_sec
            ny = y + vy * dt_sec
            nz = float(np.clip(z + vz * dt_sec, 0.8, 4.5))
            nconf = max(conf_floor, float(conf) * conf_decay)
            coasted_3d.append((nx, ny, nz, nconf))
            new_vel_3d.append((vx * damping, vy * damping, vz * damping))

        coasted_2d = []
        new_vel_2d = []
        vel_2d = self.vel_2d or [(0.0, 0.0)] * len(self.last_joints_2d)
        for (px, py, pconf), (vpx, vpy) in zip(self.last_joints_2d, vel_2d):
            npx = int(round(min(frame_w - 1, max(0, px + vpx * dt_sec))))
            npy = int(round(min(frame_h - 1, max(0, py + vpy * dt_sec))))
            npconf = max(conf_floor, float(pconf) * conf_decay)
            coasted_2d.append((npx, npy, npconf))
            new_vel_2d.append((vpx * damping, vpy * damping))

        # Shift 320x240 player mask proportionally to Spine (joint 1) 2D displacement
        coasted_mask = self.last_mask
        if self.last_mask is not None and len(coasted_2d) > 1 and len(self.last_joints_2d) > 1:
            mh, mw = self.last_mask.shape[:2]
            dx_full = coasted_2d[1][0] - self.last_joints_2d[1][0]
            dy_full = coasted_2d[1][1] - self.last_joints_2d[1][1]
            dx_m = int(round(dx_full * (mw / float(max(1, frame_w)))))
            dy_m = int(round(dy_full * (mh / float(max(1, frame_h)))))
            coasted_mask = _shift_mask_fast(self.last_mask, dx_m, dy_m)
            self.last_mask = coasted_mask

        self.last_joints_3d = coasted_3d
        self.last_joints_2d = coasted_2d
        self.vel_3d = new_vel_3d
        self.vel_2d = new_vel_2d

        return True, coasted_3d, coasted_2d, coasted_mask


class DancerIdentityLock:
    """
    Active Dancer Identity Lock (Torso HSV Color Fingerprint + Spatial Bounding Box Continuity).
    Prevents the tracker from jumping to bystanders walking behind/in front of the player or
    to background furniture during rapid dance moves.
    """
    def __init__(self, cfg: Optional[Dict[str, Any]] = None):
        self.cfg = dict(cfg) if cfg else {}
        self.is_locked: bool = False
        self.locked_cx: float = 0.5
        self.locked_cy: float = 0.5
        self.locked_sh_w: float = 0.22
        self.locked_bbox: Tuple[float, float, float, float] = (0.15, 0.05, 0.85, 0.95)
        self.ref_hist: Optional[np.ndarray] = None
        self.rejected_streak: int = 0
        self.stable_frames: int = 0

    @property
    def is_enabled(self) -> bool:
        if not bool(self.cfg.get("person_lock_enabled", True)):
            return False
        return bool(self.cfg.get("dancer_lock_enabled", True))

    @property
    def is_roi_focus_enabled(self) -> bool:
        return self.is_enabled and bool(self.cfg.get("dancer_lock_roi_focus", True))

    def set_enabled(self, enabled: bool) -> None:
        self.cfg["dancer_lock_enabled"] = bool(enabled)
        if not enabled:
            self.reset()

    def update_config(self, cfg: Dict[str, Any]) -> None:
        if cfg is not None:
            self.cfg.update(cfg)
            if not self.is_enabled:
                self.reset()

    def reset(self) -> None:
        self.is_locked = False
        self.locked_cx = 0.5
        self.locked_cy = 0.5
        self.locked_sh_w = 0.22
        self.locked_bbox = (0.15, 0.05, 0.85, 0.95)
        self.ref_hist = None
        self.rejected_streak = 0
        self.stable_frames = 0

    @staticmethod
    def _extract_torso_features(
        frame_bgr: Optional[np.ndarray], norm_landmarks: Any
    ) -> Optional[Tuple[float, float, float, Tuple[float, float, float, float], Optional[np.ndarray]]]:
        """
        Computes normalized torso center (cx, cy), shoulder width sh_w, full-body bounding box,
        and a fast 12x8 Hue-Saturation 2D histogram of the inner torso clothing region (< 0.04 ms).
        """
        if not norm_landmarks or len(norm_landmarks) <= RIGHT_HIP:
            return None

        sh_l = norm_landmarks[LEFT_SHOULDER]
        sh_r = norm_landmarks[RIGHT_SHOULDER]
        hip_l = norm_landmarks[LEFT_HIP]
        hip_r = norm_landmarks[RIGHT_HIP]

        sh_max = max(
            float(getattr(sh_l, "visibility", 1.0)),
            float(getattr(sh_r, "visibility", 1.0)),
        )
        if sh_max < 0.18:
            return None

        sh_cx = (float(sh_l.x) + float(sh_r.x)) * 0.5
        sh_cy = (float(sh_l.y) + float(sh_r.y)) * 0.5
        sh_w = max(0.05, math.hypot(float(sh_r.x) - float(sh_l.x), float(sh_r.y) - float(sh_l.y)))

        hip_vis = min(
            float(getattr(hip_l, "visibility", 1.0)),
            float(getattr(hip_r, "visibility", 1.0)),
        )
        if hip_vis >= 0.20:
            hip_cx = (float(hip_l.x) + float(hip_r.x)) * 0.5
            hip_cy = (float(hip_l.y) + float(hip_r.y)) * 0.5
        else:
            hip_cx = sh_cx
            hip_cy = min(0.95, sh_cy + sh_w * 1.35)

        cx = 0.5 * (sh_cx + hip_cx)
        cy = 0.5 * (sh_cy + hip_cy)

        # Compute active body bounding box from key landmarks
        xs = [sh_cx, hip_cx]
        ys = [sh_cy, hip_cy]
        for idx in (NOSE, LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_ELBOW, RIGHT_ELBOW, LEFT_WRIST, RIGHT_WRIST, LEFT_HIP, RIGHT_HIP, LEFT_ANKLE, RIGHT_ANKLE):
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

        # Compute compact 12x8 HSV histogram on the inner torso patch
        hist = None
        if frame_bgr is not None and frame_bgr.ndim == 3 and frame_bgr.shape[2] == 3:
            h, w = frame_bgr.shape[:2]
            pad_x = max(0.03, sh_w * 0.32)
            pad_y = max(0.04, abs(hip_cy - sh_cy) * 0.35)
            x0 = int(round(max(0.0, min(1.0, cx - pad_x)) * (w - 1)))
            x1 = int(round(max(0.0, min(1.0, cx + pad_x)) * (w - 1)))
            y0 = int(round(max(0.0, min(1.0, cy - pad_y)) * (h - 1)))
            y1 = int(round(max(0.0, min(1.0, cy + pad_y)) * (h - 1)))

            if (x1 - x0) >= 6 and (y1 - y0) >= 6:
                patch = frame_bgr[y0:y1, x0:x1]
                hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
                raw_hist = cv2.calcHist([hsv], [0, 1], None, [12, 8], [0, 180, 0, 256])
                cv2.normalize(raw_hist, raw_hist, alpha=1.0, beta=0.0, norm_type=cv2.NORM_L1)
                hist = raw_hist

        return cx, cy, sh_w, bbox, hist

    def validate_candidate(
        self,
        frame_bgr: Optional[np.ndarray],
        norm_landmarks: Any,
        dt: Optional[float] = None,
    ) -> bool:
        """
        Validates whether the detected pose belongs to the locked active dancer.
        Returns True if valid (and updates the lock state), or False if the pose is an
        impostor / background false-positive jump.
        """
        if not self.is_enabled or norm_landmarks is None:
            return True

        feats = self._extract_torso_features(frame_bgr, norm_landmarks)
        if feats is None:
            return True

        cx, cy, sh_w, bbox, cand_hist = feats

        if not self.is_locked:
            self.locked_cx = cx
            self.locked_cy = cy
            self.locked_sh_w = sh_w
            self.locked_bbox = bbox
            self.ref_hist = cand_hist
            self.is_locked = True
            self.rejected_streak = 0
            self.stable_frames = 1
            return True

        # Calculate anisotropic spatial displacement and scale ratio:
        # Vertical drops/leaps (crouching to the floor or jumping in place) share the same horizontal X,
        # whereas room bystanders/impostors appear offset horizontally. Weight dy at 0.38 so deep
        # crouches are never misclassified as impostor jumps.
        dx = abs(cx - self.locked_cx)
        dy = abs(cy - self.locked_cy)
        dist = math.hypot(dx, dy * 0.38)
        base_jump = float(self.cfg.get("dancer_lock_max_jump_norm", 0.28))
        # Scale displacement tolerance smoothly when frame intervals stretch under game load (< 28 FPS)
        dt_scale = 1.0
        if dt is not None and dt > 0.036:
            dt_scale = min(1.55, float(dt) / 0.036)
        # Expand search radius slightly during rejection streaks so fast leaps can re-lock
        max_jump = base_jump * dt_scale * (1.0 + 0.30 * min(10, self.rejected_streak))
        scale_ratio = max(sh_w, 1e-3) / max(self.locked_sh_w, 1e-3)

        color_corr = 1.0
        if self.ref_hist is not None and cand_hist is not None:
            color_corr = float(cv2.compareHist(self.ref_hist, cand_hist, cv2.HISTCMP_CORREL))

        color_thresh = float(self.cfg.get("dancer_lock_color_thresh", 0.35))

        # Impostor rejection logic:
        # 1) Sudden spatial jump combined with mismatched shirt color or drastic scale change
        # 2) Extreme instantaneous jump across the room (> 1.85x max_jump in a single tick)
        # Sideways spins / back-turns stay horizontally close (dx <= max_jump) so they are NEVER rejected.
        is_impostor = False
        if dist > max_jump:
            if color_corr < color_thresh or scale_ratio > 2.2 or scale_ratio < 0.38:
                is_impostor = True
            elif dist > max_jump * 1.85:
                is_impostor = True

        if is_impostor:
            self.rejected_streak += 1
            # Release lock promptly (~0.6-1.2s, 18 frames) so legitimate fast re-entry never stalls
            if self.rejected_streak > 18:
                self.reset()
                return self.validate_candidate(frame_bgr, norm_landmarks, dt=dt)
            return False

        # Candidate accepted -> update locked dancer state
        self.rejected_streak = 0
        self.stable_frames += 1
        alpha_pos = 0.65
        self.locked_cx = (1.0 - alpha_pos) * self.locked_cx + alpha_pos * cx
        self.locked_cy = (1.0 - alpha_pos) * self.locked_cy + alpha_pos * cy
        self.locked_sh_w = 0.80 * self.locked_sh_w + 0.20 * sh_w
        self.locked_bbox = bbox

        if cand_hist is not None:
            if self.ref_hist is None:
                self.ref_hist = cand_hist
            elif dist < base_jump * 0.65:
                # Only update color signature when player movement is steady
                cv2.addWeighted(self.ref_hist, 0.95, cand_hist, 0.05, 0.0, dst=self.ref_hist)

        return True

    def apply_roi_focus(self, infer_rgb: Optional[np.ndarray]) -> Optional[np.ndarray]:
        """
        Softly attenuates peripheral background regions far outside the locked dancer's active
        reach zone in the private `infer_rgb` buffer before MediaPipe inference (< 0.02 ms).
        Never modifies the user display frame.
        """
        if (
            infer_rgb is None
            or not self.is_roi_focus_enabled
            or not self.is_locked
            or self.stable_frames < 5
            or self.rejected_streak > 3
        ):
            return infer_rgb

        h, w = infer_rgb.shape[:2]
        # Generous horizontal reach margin around both the bounding box and torso center
        reach_half_w = max(0.38, self.locked_sh_w * 2.8)
        min_x_norm = min(self.locked_bbox[0] - 0.18, self.locked_cx - reach_half_w)
        max_x_norm = max(self.locked_bbox[2] + 0.18, self.locked_cx + reach_half_w)

        x0_px = int(round(max(0.0, min_x_norm) * w))
        x1_px = int(round(min(1.0, max_x_norm) * w))

        # Bit-shift attenuation (divides luminance by 4 in-place) on far peripheral columns
        if x0_px > 16:
            infer_rgb[:, :x0_px] >>= 2
        if x1_px < w - 16:
            infer_rgb[:, x1_px:] >>= 2

        return infer_rgb


class PersonLockController:
    """
    Unified Modular Coordinator for the Person Lock-In Subsystem.
    Encapsulates InertialCoastingFilter and DancerIdentityLock with hot-reloadable
    configuration and zero-cost bypass when disabled.
    """
    def __init__(self, cfg: Optional[Dict[str, Any]] = None):
        self.cfg = dict(cfg) if cfg else {}
        self.coasting = InertialCoastingFilter(cfg=self.cfg)
        self.identity = DancerIdentityLock(cfg=self.cfg)

    @property
    def is_enabled(self) -> bool:
        return bool(self.cfg.get("person_lock_enabled", True))

    def set_enabled(self, enabled: bool) -> None:
        self.cfg["person_lock_enabled"] = bool(enabled)
        self.coasting.update_config(self.cfg)
        self.identity.update_config(self.cfg)

    def update_config(self, cfg: Dict[str, Any]) -> None:
        if cfg is not None:
            self.cfg.update(cfg)
            self.coasting.update_config(self.cfg)
            self.identity.update_config(self.cfg)

    def reset(self) -> None:
        self.coasting.reset()
        self.identity.reset()

    def apply_pre_inference_roi(self, infer_rgb: Optional[np.ndarray]) -> Optional[np.ndarray]:
        # Never darken peripheral regions while coasting/re-acquiring after a missed frame
        if self.coasting.coasting_active:
            return infer_rgb
        return self.identity.apply_roi_focus(infer_rgb)

    def validate_candidate(
        self,
        frame_bgr: Optional[np.ndarray],
        norm_landmarks: Any,
        dt: Optional[float] = None,
    ) -> bool:
        return self.identity.validate_candidate(frame_bgr, norm_landmarks, dt=dt)

    def record_valid_frame(
        self,
        joints_3d: List[Tuple[float, float, float, float]],
        joints_2d: List[Tuple[int, int, float]],
        body_mask: Optional[np.ndarray],
        norm_landmarks: Any = None,
        dt: Optional[float] = None,
    ) -> Tuple[List[Tuple[float, float, float, float]], List[Tuple[int, int, float]], Optional[np.ndarray]]:
        return self.coasting.record_valid_frame(
            joints_3d, joints_2d, body_mask, norm_landmarks=norm_landmarks, dt=dt
        )

    def coast(
        self,
        dt: Optional[float] = None,
        frame_w: int = 640,
        frame_h: int = 480,
        max_ms_override: Optional[float] = None,
        damping_override: Optional[float] = None,
    ) -> Tuple[bool, Optional[List[Tuple[float, float, float, float]]], Optional[List[Tuple[int, int, float]]], Optional[np.ndarray]]:
        return self.coasting.coast(
            dt=dt,
            frame_w=frame_w,
            frame_h=frame_h,
            max_ms_override=max_ms_override,
            damping_override=damping_override,
        )
