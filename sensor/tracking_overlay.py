"""
Tracking HUD, Player Silhouette & Skeleton Visualizer for Legacy PSCam Sensor.
Renders player silhouette shadow & contour, skeleton tracking overlay,
performance metrics, and IPC connection status on OpenCV frames.
Supports 1-Player and 2-Player modes:
  - Player 1 (P1): Blue Palette
  - Player 2 (P2): Light Orange Palette
"""
import cv2
import numpy as np
from sensor.pose_filters import KINECT_CONNECTIONS

# Color Palette (BGR) — Player 1 (Blue) & Player 2 (Light Orange)
COLOR_P1_SILHOUETTE = (255, 150, 30)   # Vibrant Blue (#1E96FF)
COLOR_P1_SPINE = (255, 210, 90)        # Sky Blue
COLOR_P1_LEFT = (240, 120, 20)         # Royal Blue
COLOR_P1_RIGHT = (255, 185, 50)        # Cyan-Blue
COLOR_P1_HAND_L = (255, 225, 120)      # Bright Ice Blue
COLOR_P1_HAND_R = (255, 205, 90)       # Glowing Cyan-Blue

COLOR_P2_SILHOUETTE = (95, 185, 255)   # Light Orange (#FFB95F)
COLOR_P2_SPINE = (140, 220, 255)       # Soft Amber Gold
COLOR_P2_LEFT = (65, 160, 255)         # Warm Orange
COLOR_P2_RIGHT = (120, 195, 255)       # Light Peach Orange
COLOR_P2_HAND_L = (160, 225, 255)      # Glowing Light Orange
COLOR_P2_HAND_R = (140, 210, 255)      # Glowing Amber

PLAYER_PALETTES = {
    0: {
        "label": "P1",
        "silhouette": COLOR_P1_SILHOUETTE,
        "spine": COLOR_P1_SPINE,
        "left": COLOR_P1_LEFT,
        "right": COLOR_P1_RIGHT,
        "hand_l": COLOR_P1_HAND_L,
        "hand_r": COLOR_P1_HAND_R,
    },
    1: {
        "label": "P2",
        "silhouette": COLOR_P2_SILHOUETTE,
        "spine": COLOR_P2_SPINE,
        "left": COLOR_P2_LEFT,
        "right": COLOR_P2_RIGHT,
        "hand_l": COLOR_P2_HAND_L,
        "hand_r": COLOR_P2_HAND_R,
    },
}

# Backwards-compatible module constants (defaulting to Player 1 Blue)
COLOR_SPINE = COLOR_P1_SPINE
COLOR_LEFT = COLOR_P1_LEFT
COLOR_RIGHT = COLOR_P1_RIGHT
COLOR_HEAD = (255, 255, 255)      # White
COLOR_HAND_L = COLOR_P1_HAND_L
COLOR_HAND_R = COLOR_P1_HAND_R
COLOR_BG_DARK = (18, 19, 22)      # Dark background
COLOR_TEXT_DIM = (180, 180, 185)  # Soft gray
COLOR_BADGE_OK = (40, 200, 80)    # Green
COLOR_BADGE_WAIT = (40, 150, 240) # Amber
COLOR_SILHOUETTE = COLOR_P1_SILHOUETTE


class TrackingOverlay:
    def __init__(self, show_hud=True):
        self.show_hud = show_hud
        self._warned_silhouette_err = False

    def toggle_hud(self):
        self.show_hud = not self.show_hud
        return self.show_hud

    def draw_player_silhouette(self, frame, mask, color=COLOR_P1_SILHOUETTE, alpha=0.30):
        """
        Renders the player silhouette shadow ("sombrinha") and neon contour border.
        frame: BGR image (mirrored if preview is mirrored).
        mask: binary uint8 mask (may be 320x240 native Kinect resolution or full frame size).
        Uses low-res contour extraction and ROI-bounded blending to eliminate full-frame copies.
        """
        if mask is None or not np.any(mask):
            return frame

        try:
            fh, fw = frame.shape[:2]
            mh, mw = mask.shape[:2]

            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not contours:
                return frame

            # Scale contours to frame resolution if mask is at 320x240 native resolution
            if mh != fh or mw != fw:
                sx = fw / float(mw)
                sy = fh / float(mh)
                scaled_contours = []
                for c in contours:
                    sc = np.empty_like(c, dtype=np.int32)
                    sc[:, 0, 0] = np.clip(np.rint(c[:, 0, 0] * sx), 0, fw - 1).astype(np.int32)
                    sc[:, 0, 1] = np.clip(np.rint(c[:, 0, 1] * sy), 0, fh - 1).astype(np.int32)
                    scaled_contours.append(sc)
                contours = scaled_contours

            # Compute tight bounding box across all player contours to blend only the active ROI
            x0, y0, x1, y1 = fw, fh, 0, 0
            for c in contours:
                bx, by, bw, bh = cv2.boundingRect(c)
                if bx < x0:
                    x0 = bx
                if by < y0:
                    y0 = by
                if bx + bw > x1:
                    x1 = bx + bw
                if by + bh > y1:
                    y1 = by + bh

            x0 = max(0, x0)
            y0 = max(0, y0)
            x1 = min(fw, x1)
            y1 = min(fh, y1)

            if x1 > x0 and y1 > y0:
                roi = frame[y0:y1, x0:x1]
                shadow_roi = roi.copy()
                offset_contours = [c - np.array([[[x0, y0]]], dtype=np.int32) for c in contours]
                cv2.drawContours(shadow_roi, offset_contours, -1, color, thickness=cv2.FILLED)
                cv2.addWeighted(shadow_roi, alpha, roi, 1.0 - alpha, 0, roi)

            cv2.drawContours(frame, contours, -1, color, 2, cv2.LINE_AA)
        except Exception as exc:
            if not self._warned_silhouette_err:
                print(f"[WARN] Silhouette overlay rendering error: {exc}")
                self._warned_silhouette_err = True
        return frame

    def draw_multi_player_silhouettes(self, frame, player_index_mask, alpha=0.30):
        """
        Renders silhouettes for Player 1 (Blue, index 1) and Player 2 (Light Orange, index 2)
        from a combined 320x240 player_index_mask (or legacy binary mask).
        """
        if player_index_mask is None or not np.any(player_index_mask):
            return frame

        max_val = int(np.max(player_index_mask))
        if max_val > 6:
            # Legacy binary mask (255) -> draw as Player 1 (Blue)
            return self.draw_player_silhouette(frame, player_index_mask, color=COLOR_P1_SILHOUETTE, alpha=alpha)

        for slot_idx in (0, 1):
            p_idx = slot_idx + 1
            p_mask = ((player_index_mask == p_idx).astype(np.uint8)) * 255
            if np.any(p_mask):
                pal = PLAYER_PALETTES[slot_idx]
                frame = self.draw_player_silhouette(frame, p_mask, color=pal["silhouette"], alpha=alpha)
        return frame

    def draw_skeleton(self, frame, pixel_joints, player_idx: int = 0, show_badge: bool = False):
        if not pixel_joints or len(pixel_joints) < 20:
            return frame

        h, w = frame.shape[:2]
        pal = PLAYER_PALETTES.get(int(player_idx), PLAYER_PALETTES[0])

        # Draw bones
        for start_idx, end_idx in KINECT_CONNECTIONS:
            p1 = pixel_joints[start_idx]
            p2 = pixel_joints[end_idx]

            if not (0 <= p1[0] < w and 0 <= p1[1] < h and 0 <= p2[0] < w and 0 <= p2[1] < h):
                continue

            if end_idx in (1, 2, 3):
                color = pal["spine"]
                thickness = 4
            elif end_idx in (4, 5, 6, 7, 12, 13, 14, 15):
                color = pal["left"]
                thickness = 3
            else:
                color = pal["right"]
                thickness = 3

            cv2.line(frame, (p1[0], p1[1]), (p2[0], p2[1]), color, thickness, lineType=cv2.LINE_AA)

        # Draw joints
        for i, (px, py, conf) in enumerate(pixel_joints):
            if not (0 <= px < w and 0 <= py < h):
                continue

            if i == 3:  # Head
                cv2.circle(frame, (px, py), 12, COLOR_HEAD, -1, lineType=cv2.LINE_AA)
                cv2.circle(frame, (px, py), 14, pal["silhouette"], 2, lineType=cv2.LINE_AA)
                if show_badge:
                    tag = pal["label"]
                    bx = max(8, min(w - 42, px - 16))
                    by = max(24, py - 20)
                    cv2.rectangle(frame, (bx, by - 16), (bx + 32, by + 4), pal["silhouette"], -1)
                    cv2.rectangle(frame, (bx, by - 16), (bx + 32, by + 4), (255, 255, 255), 1, cv2.LINE_AA)
                    cv2.putText(
                        frame, tag, (bx + 5, by - 1),
                        cv2.FONT_HERSHEY_DUPLEX, 0.45, (15, 15, 20), 1, cv2.LINE_AA
                    )
            elif i == 7:  # Left Hand
                cv2.circle(frame, (px, py), 10, pal["hand_l"], -1, lineType=cv2.LINE_AA)
                cv2.circle(frame, (px, py), 13, (255, 255, 255), 2, lineType=cv2.LINE_AA)
            elif i == 11:  # Right Hand
                cv2.circle(frame, (px, py), 10, pal["hand_r"], -1, lineType=cv2.LINE_AA)
                cv2.circle(frame, (px, py), 13, (255, 255, 255), 2, lineType=cv2.LINE_AA)
            else:
                color = pal["left"] if i in (4, 5, 6, 12, 13, 14, 15) else pal["right"]
                cv2.circle(frame, (px, py), 5, color, -1, lineType=cv2.LINE_AA)
                cv2.circle(frame, (px, py), 6, (0, 0, 0), 1, lineType=cv2.LINE_AA)

        return frame

    def draw_hud(
        self,
        frame,
        camera_info_str,
        is_tracked,
        cam_fps,
        track_fps,
        is_calibrated,
        is_mirrored,
        calibration_tier="full_body",
        max_players: int = 1,
        tracked_mask: Optional[int] = None,
    ):
        if not self.show_hud:
            return frame

        h, w = frame.shape[:2]
        if tracked_mask is None:
            tracked_mask = 1 if is_tracked else 0

        # Top HUD Banner (semi-transparent ROI slice - avoids full-frame copy)
        top_h = min(52, h)
        top_roi = frame[:top_h, :]
        top_bg = np.full_like(top_roi, COLOR_BG_DARK)
        cv2.addWeighted(top_bg, 0.78, top_roi, 0.22, 0, top_roi)

        # Bottom Controls Banner (semi-transparent ROI slice)
        if h > 52:
            bot_y0 = max(top_h, h - 34)
            bot_roi = frame[bot_y0:h, :]
            bot_bg = np.full_like(bot_roi, COLOR_BG_DARK)
            cv2.addWeighted(bot_bg, 0.78, bot_roi, 0.22, 0, bot_roi)

        # 1. Top Left: Title & Mode
        cv2.putText(frame, "LEGACY PSCAM SENSOR", (14, 24),
                    cv2.FONT_HERSHEY_DUPLEX, 0.65, (255, 255, 255), 1, cv2.LINE_AA)
        mode_tag = "[2P DUO]" if max_players >= 2 else "[1P SOLO]"
        cam_sub = f"{camera_info_str} {mode_tag} {'[MIRRORED]' if is_mirrored else ''}"
        cv2.putText(frame, cam_sub, (14, 43),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, COLOR_TEXT_DIM, 1, cv2.LINE_AA)

        # 2. Top Center: Status Badge
        if max_players >= 2:
            p1_on = bool(tracked_mask & 1)
            p2_on = bool(tracked_mask & 2)
            if p1_on and p2_on:
                badge_text = "2P: P1 + P2 ACTIVE"
                badge_color = COLOR_BADGE_OK
            elif p1_on:
                badge_text = "2P: P1 ACTIVE (WAIT P2)"
                badge_color = COLOR_P1_SILHOUETTE
            elif p2_on:
                badge_text = "2P: P2 ACTIVE (WAIT P1)"
                badge_color = COLOR_P2_SILHOUETTE
            else:
                badge_text = "SEARCHING P1 & P2..."
                badge_color = COLOR_BADGE_WAIT
        else:
            if is_tracked:
                if calibration_tier == "full_body":
                    badge_text = "FULL BODY (ACTIVE)"
                elif calibration_tier == "flexible_torso":
                    badge_text = "HALF BODY (ACTIVE)"
                elif calibration_tier == "upper_body":
                    badge_text = "DESK FRAMING (ACTIVE)"
                else:
                    badge_text = "TRACKING ACTIVE"
                badge_color = COLOR_BADGE_OK
            else:
                badge_text = "SEARCHING FOR PLAYER..."
                badge_color = COLOR_BADGE_WAIT

        badge_w = 240
        badge_x = max(240, (w - badge_w) // 2)
        cv2.rectangle(frame, (badge_x, 10), (badge_x + badge_w, 40), badge_color, 2, cv2.LINE_AA)
        cv2.putText(frame, badge_text, (badge_x + 10, 30),
                    cv2.FONT_HERSHEY_DUPLEX, 0.44, badge_color, 1, cv2.LINE_AA)

        # 3. Top Right: FPS and Bridge Status
        fps_text = f"CAM: {cam_fps:.1f} FPS | TRACK: {track_fps:.1f} FPS"
        bridge_text = "IPC: JDP2 & JMI2 [2P Active]" if max_players >= 2 else "IPC: JDP1/2 & JMI1/2 [Active]"
        t_size = cv2.getTextSize(fps_text, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)[0]
        cv2.putText(frame, fps_text, (w - t_size[0] - 14, 23),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 220), 1, cv2.LINE_AA)
        b_size = cv2.getTextSize(bridge_text, cv2.FONT_HERSHEY_SIMPLEX, 0.40, 1)[0]
        cv2.putText(frame, bridge_text, (w - b_size[0] - 14, 42),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.40, (140, 240, 140), 1, cv2.LINE_AA)

        # 4. Bottom Controls Banner
        controls_text = "[C] Recalibrate  |  [M] Mirror  |  [O] Rotate  |  [H] HUD  |  [Q / ESC] Exit"
        cv2.putText(frame, controls_text, (16, h - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.44, (220, 220, 225), 1, cv2.LINE_AA)

        if is_tracked:
            if is_calibrated:
                tier_desc = "Full Body" if calibration_tier == "full_body" else "Half Body / Desk"
                calib_msg = f"Auto-Calibration: {tier_desc}"
            else:
                calib_msg = "Auto-adjusting height..."
            cv2.putText(frame, calib_msg, (w - 290, h - 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.40, (0, 255, 220), 1, cv2.LINE_AA)

        return frame
