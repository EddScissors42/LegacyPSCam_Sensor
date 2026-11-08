"""
Tracking HUD, Player Silhouette & Skeleton Visualizer for Legacy PSCam Sensor.
Renders player silhouette shadow & contour, skeleton tracking overlay,
performance metrics, and IPC connection status on OpenCV frames.
"""
import cv2
import numpy as np
from sensor.pose_filters import KINECT_CONNECTIONS

# Color Palette (BGR)
COLOR_SPINE = (0, 230, 255)       # Yellow/Gold
COLOR_LEFT = (255, 200, 0)        # Bright Cyan
COLOR_RIGHT = (50, 255, 120)      # Neon Green
COLOR_HEAD = (255, 255, 255)      # White
COLOR_HAND_L = (255, 230, 80)     # Glowing Cyan
COLOR_HAND_R = (80, 255, 160)     # Glowing Neon Green
COLOR_BG_DARK = (18, 19, 22)      # Dark background
COLOR_TEXT_DIM = (180, 180, 185)  # Soft gray
COLOR_BADGE_OK = (40, 200, 80)    # Green
COLOR_BADGE_WAIT = (40, 150, 240) # Amber
COLOR_SILHOUETTE = (70, 235, 90)  # Neon Lime (Player 1 Silhouette & Contour)

class TrackingOverlay:
    def __init__(self, show_hud=True):
        self.show_hud = show_hud

    def toggle_hud(self):
        self.show_hud = not self.show_hud
        return self.show_hud

    def draw_player_silhouette(self, frame, mask, color=COLOR_SILHOUETTE, alpha=0.30):
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
                # 1. Semi-transparent filled glowing shadow ("sombrinha") inside player ROI only
                cv2.drawContours(shadow_roi, offset_contours, -1, color, thickness=cv2.FILLED)
                cv2.addWeighted(shadow_roi, alpha, roi, 1.0 - alpha, 0, roi)

            # 2. Crisp neon outline contour around the player
            cv2.drawContours(frame, contours, -1, color, 2, cv2.LINE_AA)
        except Exception:
            pass
        return frame

    def draw_skeleton(self, frame, pixel_joints):
        if not pixel_joints or len(pixel_joints) < 20:
            return frame

        h, w = frame.shape[:2]

        # Draw bones
        for start_idx, end_idx in KINECT_CONNECTIONS:
            p1 = pixel_joints[start_idx]
            p2 = pixel_joints[end_idx]

            # Check if coordinates are within reasonable bounds
            if not (0 <= p1[0] < w and 0 <= p1[1] < h and 0 <= p2[0] < w and 0 <= p2[1] < h):
                continue

            # Select color based on body part
            if end_idx in (1, 2, 3):
                color = COLOR_SPINE
                thickness = 4
            elif end_idx in (4, 5, 6, 7, 12, 13, 14, 15):
                color = COLOR_LEFT
                thickness = 3
            else:
                color = COLOR_RIGHT
                thickness = 3

            cv2.line(frame, (p1[0], p1[1]), (p2[0], p2[1]), color, thickness, lineType=cv2.LINE_AA)

        # Draw joints
        for i, (px, py, conf) in enumerate(pixel_joints):
            if not (0 <= px < w and 0 <= py < h):
                continue

            if i == 3:  # Head
                cv2.circle(frame, (px, py), 12, COLOR_HEAD, -1, lineType=cv2.LINE_AA)
                cv2.circle(frame, (px, py), 14, COLOR_SPINE, 2, lineType=cv2.LINE_AA)
            elif i == 7:  # Left Hand
                cv2.circle(frame, (px, py), 10, COLOR_HAND_L, -1, lineType=cv2.LINE_AA)
                cv2.circle(frame, (px, py), 13, (255, 255, 255), 2, lineType=cv2.LINE_AA)
            elif i == 11: # Right Hand
                cv2.circle(frame, (px, py), 10, COLOR_HAND_R, -1, lineType=cv2.LINE_AA)
                cv2.circle(frame, (px, py), 13, (255, 255, 255), 2, lineType=cv2.LINE_AA)
            else:
                color = COLOR_LEFT if i in (4, 5, 6, 12, 13, 14, 15) else COLOR_RIGHT
                cv2.circle(frame, (px, py), 5, color, -1, lineType=cv2.LINE_AA)
                cv2.circle(frame, (px, py), 6, (0, 0, 0), 1, lineType=cv2.LINE_AA)

        return frame

    def draw_hud(self, frame, camera_info_str, is_tracked, cam_fps, track_fps, is_calibrated, is_mirrored, calibration_tier="full_body"):
        if not self.show_hud:
            return frame

        h, w = frame.shape[:2]

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
        cam_sub = f"{camera_info_str} {'[MIRRORED]' if is_mirrored else ''}"
        cv2.putText(frame, cam_sub, (14, 43),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, COLOR_TEXT_DIM, 1, cv2.LINE_AA)

        # 2. Top Center: Status Badge (Full-body vs Partial-body / Desk framing)
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
        bridge_text = "IPC: JDP1 & JMI1 [Active]"
        t_size = cv2.getTextSize(fps_text, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)[0]
        cv2.putText(frame, fps_text, (w - t_size[0] - 14, 23),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 220), 1, cv2.LINE_AA)
        b_size = cv2.getTextSize(bridge_text, cv2.FONT_HERSHEY_SIMPLEX, 0.40, 1)[0]
        cv2.putText(frame, bridge_text, (w - b_size[0] - 14, 42),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.40, (140, 240, 140), 1, cv2.LINE_AA)

        # 4. Bottom Controls Banner
        controls_text = "[C] Recalibrate  |  [M] Mirror  |  [H] Toggle HUD  |  [Q / ESC] Exit"
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
