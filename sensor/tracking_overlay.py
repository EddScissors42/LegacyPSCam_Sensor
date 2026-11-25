"""
Tracking HUD, Player Silhouette & Skeleton Visualizer for Legacy PSCam Sensor.
Features:
- Modern PlayStation / Just Dance floating "Glass Pills" with rounded corners.
- Neon contour silhouette rendering ("sombrinha") with dual-pass edge glow.
- Scoring Hand Aura: dynamic pulsing glow on the scoring hand reacting to movement speed.
- Radial Progress Ring for arm-raised gesture ([ENTER]) centered directly on the dancer's hand.
- 3 HUD display tiers: Full HUD (0), Minimalist Clean Dance (1), and Immersive Mirror (2).
- Full 1-Player (Solo Blue) and 2-Player (Duo Light Orange) support.
"""
import time
import math
import cv2
import numpy as np
from typing import Optional, List, Tuple, Dict, Any
from sensor.pose_filters import KINECT_CONNECTIONS

# Color Palette (BGR) — Player 1 (PlayStation Blue) & Player 2 (Light Orange / Amber)
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

# General UI Colors (BGR)
COLOR_SPINE = COLOR_P1_SPINE
COLOR_LEFT = COLOR_P1_LEFT
COLOR_RIGHT = COLOR_P1_RIGHT
COLOR_HEAD = (255, 255, 255)          # White
COLOR_HAND_L = COLOR_P1_HAND_L
COLOR_HAND_R = COLOR_P1_HAND_R
COLOR_GLASS_BG = (18, 20, 26)         # Deep Obsidian Glass
COLOR_GLASS_BORDER = (60, 70, 85)     # Frosted Outline
COLOR_TEXT_WHITE = (255, 255, 255)
COLOR_TEXT_DIM = (185, 190, 200)      # Soft Silver
COLOR_STATUS_OK = (80, 220, 110)      # Neon Emerald (#10B981)
COLOR_STATUS_WAIT = (40, 170, 250)    # Warm Amber Gold
COLOR_NEON_CYAN = (245, 225, 30)      # Vibrant Cyan
COLOR_SILHOUETTE = COLOR_P1_SILHOUETTE


def draw_rounded_glass_pill(
    frame: np.ndarray,
    x: int,
    y: int,
    w: int,
    h: int,
    radius: int = 10,
    bg_color: Tuple[int, int, int] = COLOR_GLASS_BG,
    alpha: float = 0.74,
    border_color: Optional[Tuple[int, int, int]] = COLOR_GLASS_BORDER,
    border_thickness: int = 1,
) -> None:
    """Renders a hardware-accelerated rounded glass pill with semi-transparent background."""
    fh, fw = frame.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(fw, x + w), min(fh, y + h)
    rw, rh = x1 - x0, y1 - y0
    if rw <= 0 or rh <= 0:
        return

    roi = frame[y0:y1, x0:x1]
    r = min(radius, rw // 2, rh // 2)

    # Local mask generation in tight ROI bounding box (< 0.05ms)
    mask = np.zeros((rh, rw), dtype=np.uint8)
    cv2.rectangle(mask, (r, 0), (rw - r, rh), 255, -1)
    cv2.rectangle(mask, (0, r), (rw, rh - r), 255, -1)
    cv2.circle(mask, (r, r), r, 255, -1)
    cv2.circle(mask, (rw - r, r), r, 255, -1)
    cv2.circle(mask, (r, rh - r), r, 255, -1)
    cv2.circle(mask, (rw - r, rh - r), r, 255, -1)

    bg = np.full((rh, rw, 3), bg_color, dtype=np.uint8)
    blended = cv2.addWeighted(bg, alpha, roi, 1.0 - alpha, 0)
    np.copyto(roi, blended, where=(mask[:, :, None] == 255))

    if border_color:
        cv2.line(roi, (r, 0), (rw - r, 0), border_color, border_thickness, cv2.LINE_AA)
        cv2.line(roi, (r, rh - 1), (rw - r, rh - 1), border_color, border_thickness, cv2.LINE_AA)
        cv2.line(roi, (0, r), (0, rh - r), border_color, border_thickness, cv2.LINE_AA)
        cv2.line(roi, (rw - 1, r), (rw - 1, rh - r), border_color, border_thickness, cv2.LINE_AA)
        cv2.ellipse(roi, (r, r), (r, r), 180, 0, 90, border_color, border_thickness, cv2.LINE_AA)
        cv2.ellipse(roi, (rw - r, r), (r, r), 270, 0, 90, border_color, border_thickness, cv2.LINE_AA)
        cv2.ellipse(roi, (rw - r, rh - r), (r, r), 0, 0, 90, border_color, border_thickness, cv2.LINE_AA)
        cv2.ellipse(roi, (r, rh - r), (r, r), 90, 0, 90, border_color, border_thickness, cv2.LINE_AA)


class TrackingOverlay:
    """Modern PlayStation & Just Dance visual overlay engine."""

    def __init__(self, show_hud: bool = True):
        self.show_hud = show_hud
        self.hud_mode = 0 if show_hud else 2  # 0: Full HUD, 1: Minimalist, 2: Off
        self.pip_mode = False
        self._warned_silhouette_err = False
        self._last_mode_switch_time = 0.0
        self._mode_switch_text = ""

    def toggle_pip(self) -> bool:
        """Toggles Picture-in-Picture (PiP) mode (compact always-on-top window without HUD pills)."""
        self.pip_mode = not self.pip_mode
        return self.pip_mode

    def toggle_hud(self) -> bool:
        """Cycles between Full HUD -> Minimalist Clean -> Off -> Full HUD."""
        self.hud_mode = (self.hud_mode + 1) % 3
        self.show_hud = (self.hud_mode < 2)

        mode_names = {
            0: "HUD: Full (All Metrics)",
            1: "HUD: Minimal (Clean Dance)",
            2: "HUD: Off (Immersive Mirror)",
        }
        self._mode_switch_text = mode_names.get(self.hud_mode, "")
        self._last_mode_switch_time = time.time()
        return self.show_hud

    def set_hud_mode(self, mode: int) -> None:
        """Explicitly set HUD mode (0: Full, 1: Minimalist, 2: Off)."""
        self.hud_mode = max(0, min(2, int(mode)))
        self.show_hud = (self.hud_mode < 2)

    def draw_player_silhouette(
        self,
        frame: np.ndarray,
        mask: np.ndarray,
        color: Tuple[int, int, int] = COLOR_P1_SILHOUETTE,
        alpha: float = 0.28,
    ) -> np.ndarray:
        """
        Renders a smooth, true-to-life player silhouette shadow ("sombrinha") and crisp
        anti-aliased contour directly from the segmentation mask, preserving interior gaps
        (e.g., between arms and waist or between legs) without stair-stepping artifacts.
        frame: BGR image (mirrored if preview is mirrored).
        mask: binary uint8 mask (native 320x240 or full frame).
        """
        if mask is None or not np.any(mask):
            return frame

        try:
            fh, fw = frame.shape[:2]
            mh, mw = mask.shape[:2]

            # Find tight bounding box in mask space to restrict upscaling/blending to the player ROI
            ys, xs = np.nonzero(mask)
            if ys.size == 0:
                return frame
            pad_m = 4
            mx0 = max(0, int(xs.min()) - pad_m)
            my0 = max(0, int(ys.min()) - pad_m)
            mx1 = min(mw, int(xs.max()) + 1 + pad_m)
            my1 = min(mh, int(ys.max()) + 1 + pad_m)

            # Map tight ROI to frame coordinates
            sx = fw / float(mw)
            sy = fh / float(mh)
            x0 = max(0, int(math.floor(mx0 * sx)))
            y0 = max(0, int(math.floor(my0 * sy)))
            x1 = min(fw, int(math.ceil(mx1 * sx)))
            y1 = min(fh, int(math.ceil(my1 * sy)))
            rw, rh = x1 - x0, y1 - y0
            if rw <= 0 or rh <= 0:
                return frame

            mask_roi = mask[my0:my1, mx0:mx1]
            if mask_roi.shape[0] != rh or mask_roi.shape[1] != rw:
                # Blur on small native ROI (<= 320x240) BEFORE linear upscaling: same smooth
                # anti-aliased edge as full-res GaussianBlur at ~5x lower CPU cost!
                smooth_small = cv2.GaussianBlur(mask_roi, (3, 3), 0)
                up_mask = cv2.resize(smooth_small, (rw, rh), interpolation=cv2.INTER_LINEAR)
                _, bin_roi = cv2.threshold(up_mask, 127, 255, cv2.THRESH_BINARY)
            else:
                _, bin_roi = cv2.threshold(mask_roi, 127, 255, cv2.THRESH_BINARY)

            if not np.any(bin_roi):
                return frame

            # 1. Exact pixel-accurate translucent tint ("sombrinha") preserving interior gaps (arms/legs)
            # Uses pure OpenCV C++ SIMD uint8 ops (addWeighted + masked copyTo) for <1 ms latency.
            roi = frame[y0:y1, x0:x1]
            tinted = np.empty_like(roi)
            tinted[:, :] = color
            blended = cv2.addWeighted(tinted, alpha, roi, 1.0 - alpha, 0)
            cv2.copyTo(blended, bin_roi, roi)

            # 2. Smooth anti-aliased contour (CHAIN_APPROX_SIMPLE cuts contour vertex overhead by ~6x)
            contours, _ = cv2.findContours(bin_roi, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
            if contours:
                cv2.drawContours(roi, contours, -1, color, 2, cv2.LINE_AA)
        except Exception as exc:
            if not self._warned_silhouette_err:
                print(f"[WARN] Silhouette overlay rendering error: {exc}")
                self._warned_silhouette_err = True
        return frame

    def draw_multi_player_silhouettes(
        self,
        frame: np.ndarray,
        player_index_mask: np.ndarray,
        alpha: float = 0.28,
    ) -> np.ndarray:
        """
        Renders silhouettes for Player 1 (Blue, index 1) and Player 2 (Light Orange, index 2).
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

    def draw_skeleton(
        self,
        frame: np.ndarray,
        pixel_joints: List[Tuple[float, float, float]],
        player_idx: int = 0,
        show_badge: bool = False,
        scoring_hand: str = "right",
        hand_speed: float = 0.0,
    ) -> np.ndarray:
        """
        Renders console-style skeleton lines with antialiasing and Scoring Hand Aura.
        """
        if not pixel_joints or len(pixel_joints) < 20:
            return frame

        h, w = frame.shape[:2]
        pal = PLAYER_PALETTES.get(int(player_idx), PLAYER_PALETTES[0])
        now = time.time()

        # 1. Draw bones with antialiasing
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

        # Determine scoring hand index (Right hand by default: 11, Left: 7)
        scoring_idx = 7 if str(scoring_hand).lower() == "left" else 11

        # 2. Draw joints
        for i, (px, py, conf) in enumerate(pixel_joints):
            if not (0 <= px < w and 0 <= py < h):
                continue

            if i == 3:  # Head
                cv2.circle(frame, (px, py), 12, COLOR_HEAD, -1, lineType=cv2.LINE_AA)
                cv2.circle(frame, (px, py), 15, pal["silhouette"], 2, lineType=cv2.LINE_AA)
                if show_badge:
                    tag = pal["label"]
                    bx = max(8, min(w - 42, px - 16))
                    by = max(24, py - 20)
                    draw_rounded_glass_pill(frame, bx - 2, by - 18, 36, 22, radius=6, bg_color=(15, 18, 26), alpha=0.85, border_color=pal["silhouette"])
                    cv2.putText(
                        frame, tag, (bx + 5, by - 2),
                        cv2.FONT_HERSHEY_DUPLEX, 0.46, pal["silhouette"], 1, cv2.LINE_AA
                    )
            elif i in (7, 11):  # Hands
                is_scoring = (i == scoring_idx)
                hand_color = pal["hand_l"] if i == 7 else pal["hand_r"]

                if is_scoring:
                    # Scoring Hand Aura: pulsing aura reacting to dance speed
                    pulse_r = int(14 + (math.sin(now * 5.0) + 1.0) * 2.5)
                    speed_boost = min(12, int(hand_speed * 4.5))
                    total_r = pulse_r + speed_boost
                    aura_color = (40, 210, 255) if hand_speed > 1.2 else pal["silhouette"]

                    # Translucent halo ring
                    cv2.circle(frame, (px, py), total_r, aura_color, 2, lineType=cv2.LINE_AA)
                    cv2.circle(frame, (px, py), max(8, total_r - 4), (255, 255, 255), 1, lineType=cv2.LINE_AA)

                cv2.circle(frame, (px, py), 9, hand_color, -1, lineType=cv2.LINE_AA)
                cv2.circle(frame, (px, py), 11, (255, 255, 255), 2, lineType=cv2.LINE_AA)
            else:
                color = pal["left"] if i in (4, 5, 6, 12, 13, 14, 15) else pal["right"]
                cv2.circle(frame, (px, py), 5, color, -1, lineType=cv2.LINE_AA)
                cv2.circle(frame, (px, py), 6, (0, 0, 0), 1, lineType=cv2.LINE_AA)

        return frame

    def draw_gesture_feedback(
        self,
        frame: np.ndarray,
        gesture_info: Dict[str, Any],
        max_players: int = 1,
    ) -> np.ndarray:
        """
        Renders glowing radial progress ring directly around the dancer's raised hand.
        """
        if not gesture_info:
            return frame

        fh, fw = frame.shape[:2]
        holding = gesture_info.get("holding", False)
        feedback_active = gesture_info.get("feedback_active", False)
        progress = float(gesture_info.get("progress", 0.0))
        target_s = float(gesture_info.get("target", 2.0))
        elapsed = min(target_s, float(gesture_info.get("elapsed", 0.0)))
        p_idx = gesture_info.get("player_idx")
        hand_pos = gesture_info.get("hand_pos")

        if not holding and not feedback_active:
            return frame

        p_tag = f"P{p_idx + 1} " if (p_idx is not None and max_players >= 2) else ""

        if hand_pos is not None:
            hx, hy = int(hand_pos[0]), int(hand_pos[1])
            hx = max(50, min(fw - 50, hx))
            hy = max(50, min(fh - 50, hy))
            r = 34

            if feedback_active:
                # Success pulse: expanding neon green ripple waves
                pulse_phase = int((time.time() * 9) % 3)
                for pr, pa in [(r + 4, 2), (r + 10 + pulse_phase * 3, 1)]:
                    cv2.circle(frame, (hx, hy), pr, COLOR_STATUS_OK, pa, cv2.LINE_AA)
                cv2.circle(frame, (hx, hy), r, (15, 25, 20), -1)
                cv2.circle(frame, (hx, hy), r, COLOR_STATUS_OK, 2, cv2.LINE_AA)

                # Floating pill label
                pill_w, pill_h = 170, 32
                px = max(10, min(fw - pill_w - 10, hx - pill_w // 2))
                py = max(10, hy - r - 38) if hy - r - 38 > 10 else hy + r + 10
                draw_rounded_glass_pill(frame, px, py, pill_w, pill_h, radius=8, bg_color=(10, 24, 16), alpha=0.85, border_color=COLOR_STATUS_OK)
                cv2.putText(frame, f"{p_tag}ENTER SENT! \u2713", (px + 16, py + 21), cv2.FONT_HERSHEY_DUPLEX, 0.44, COLOR_STATUS_OK, 1, cv2.LINE_AA)
            else:
                # Radial progress ring with glowing tip
                draw_rounded_glass_pill(frame, hx - r - 6, hy - r - 6, (r + 6) * 2, (r + 6) * 2, radius=r + 6, bg_color=(15, 18, 24), alpha=0.62, border_color=(50, 60, 75))
                cv2.circle(frame, (hx, hy), r, (40, 48, 62), 3, cv2.LINE_AA)

                deg = int(360.0 * min(1.0, max(0.0, progress)))
                if deg > 0:
                    cv2.ellipse(frame, (hx, hy), (r, r), -90, 0, deg, (0, 235, 255), 4, cv2.LINE_AA)
                    rad = math.radians(-90 + deg)
                    tip_x = int(hx + r * math.cos(rad))
                    tip_y = int(hy + r * math.sin(rad))
                    cv2.circle(frame, (tip_x, tip_y), 5, (255, 255, 255), -1, cv2.LINE_AA)
                    cv2.circle(frame, (tip_x, tip_y), 6, (0, 235, 255), 1, cv2.LINE_AA)

                # Floating countdown badge
                pill_w, pill_h = 176, 30
                px = max(10, min(fw - pill_w - 10, hx - pill_w // 2))
                py = max(10, hy - r - 36) if hy - r - 36 > 10 else hy + r + 10
                draw_rounded_glass_pill(frame, px, py, pill_w, pill_h, radius=8, bg_color=(18, 22, 30), alpha=0.82, border_color=(0, 235, 255))
                pct = int(progress * 100)
                txt = f"{p_tag}HOLD {elapsed:.1f}s ({pct}%)"
                cv2.putText(frame, txt, (px + 14, py + 20), cv2.FONT_HERSHEY_DUPLEX, 0.42, (255, 255, 255), 1, cv2.LINE_AA)
        else:
            # Fallback floating banner
            pill_w, pill_h = 320, 38
            px = (fw - pill_w) // 2
            py = max(68, fh - 64)
            if feedback_active:
                draw_rounded_glass_pill(frame, px, py, pill_w, pill_h, radius=10, bg_color=(10, 25, 18), alpha=0.85, border_color=COLOR_STATUS_OK)
                cv2.putText(frame, f"{p_tag}ENTER COMMAND SENT! \u2713", (px + 36, py + 25), cv2.FONT_HERSHEY_DUPLEX, 0.52, COLOR_STATUS_OK, 1, cv2.LINE_AA)
            else:
                draw_rounded_glass_pill(frame, px, py, pill_w, pill_h, radius=10, bg_color=(18, 22, 30), alpha=0.85, border_color=(0, 235, 255))
                pct = int(progress * 100)
                txt = f"{p_tag}HOLD ARM UP: {elapsed:.1f}s / {target_s:.1f}s ({pct}%)"
                cv2.putText(frame, txt, (px + 22, py + 24), cv2.FONT_HERSHEY_DUPLEX, 0.44, (0, 240, 255), 1, cv2.LINE_AA)

        return frame

    @staticmethod
    def _draw_rotate_phone_icon(frame: np.ndarray, cx: int, cy: int, now: float) -> None:
        """
        Draws a crisp anti-aliased vector icon showing a smartphone rotating from
        vertical (portrait) to horizontal (landscape) with a curved arrow.
        """
        # 1. Vertical phone (starting ghost outline on the left)
        vx0, vy0 = cx - 15, cy - 11
        vx1, vy1 = cx - 3, cy + 10
        ghost_col = (155, 168, 185)
        cv2.rectangle(frame, (vx0, vy0), (vx1, vy1), ghost_col, 1, cv2.LINE_AA)
        # Small home bar / indicator on bottom of vertical phone
        cv2.line(frame, (vx0 + 4, vy1 - 3), (vx1 - 4, vy1 - 3), ghost_col, 1, cv2.LINE_AA)

        # 2. Target horizontal phone (bright highlighted landscape outline on the right-bottom)
        hx0, hy0 = cx - 6, cy - 1
        hx1, hy1 = cx + 16, cy + 11
        # Subtle dark fill so it stands out cleanly over the ghost outline
        cv2.rectangle(frame, (hx0 + 1, hy0 + 1), (hx1 - 1, hy1 - 1), (28, 36, 48), -1)
        cv2.rectangle(frame, (hx0, hy0), (hx1, hy1), COLOR_TEXT_WHITE, 2, cv2.LINE_AA)
        # Landscape side home/camera bar
        cv2.line(frame, (hx1 - 3, hy0 + 3), (hx1 - 3, hy1 - 3), COLOR_STATUS_WAIT, 1, cv2.LINE_AA)

        # 3. Curved clockwise rotation arrow from vertical top to horizontal top
        pulse = 0.75 + 0.25 * math.sin(now * 4.5)
        arrow_col = (
            int(40 * pulse + 20),
            int(175 * pulse + 40),
            min(255, int(235 * pulse + 20)),
        )
        arc_cx, arc_cy = cx + 1, cy - 2
        cv2.ellipse(
            frame,
            (arc_cx, arc_cy),
            (10, 8),
            0,
            255,
            345,
            arrow_col,
            2,
            cv2.LINE_AA,
        )
        # Arrowhead pointing clockwise onto the horizontal phone
        tip_x, tip_y = cx + 11, cy - 4
        cv2.line(frame, (tip_x, tip_y), (tip_x - 4, tip_y - 2), arrow_col, 2, cv2.LINE_AA)
        cv2.line(frame, (tip_x, tip_y), (tip_x + 1, tip_y - 5), arrow_col, 2, cv2.LINE_AA)

    def _draw_phone_orientation_pill(self, frame: np.ndarray, bot_y: int, now: float) -> None:
        """
        Renders a floating notification pill above the controls bar prompting the user
        to rotate their smartphone horizontally when portrait orientation is detected.
        """
        fh, fw = frame.shape[:2]
        notif_h = 44
        notif_w = min(fw - 24, 344)
        notif_x = (fw - notif_w) // 2
        notif_y = max(66, bot_y - notif_h - 8)

        draw_rounded_glass_pill(
            frame,
            notif_x,
            notif_y,
            notif_w,
            notif_h,
            radius=12,
            bg_color=(20, 24, 34),
            alpha=0.86,
            border_color=COLOR_STATUS_WAIT,
            border_thickness=1,
        )

        # Left icon: vertical -> horizontal phone rotation
        icon_cx = notif_x + 28
        icon_cy = notif_y + notif_h // 2
        self._draw_rotate_phone_icon(frame, icon_cx, icon_cy, now)

        # Right notification text (English)
        text_x = notif_x + 54
        title_scale = 0.42 if notif_w >= 300 else 0.36
        sub_scale = 0.31 if notif_w >= 300 else 0.27
        cv2.putText(
            frame,
            "Rotate your phone horizontally",
            (text_x, notif_y + 19),
            cv2.FONT_HERSHEY_DUPLEX,
            title_scale,
            COLOR_TEXT_WHITE,
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            "Landscape mode recommended for tracking",
            (text_x, notif_y + 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            sub_scale,
            COLOR_TEXT_DIM,
            1,
            cv2.LINE_AA,
        )

    def draw_hud(
        self,
        frame: np.ndarray,
        camera_info_str: str,
        is_tracked: bool,
        cam_fps: float,
        track_fps: float,
        is_calibrated: bool,
        is_mirrored: bool,
        calibration_tier: str = "full_body",
        max_players: int = 1,
        tracked_mask: Optional[int] = None,
        phone_portrait_warning: bool = False,
        kinect_emu_status: Optional[Dict[str, Any]] = None,
    ) -> np.ndarray:
        """
        Renders the modern PlayStation-inspired floating glass pill HUD.
        """
        now = time.time()
        fh, fw = frame.shape[:2]

        # Draw temporary mode switch toast notification if active
        if now - self._last_mode_switch_time < 1.6 and self._mode_switch_text:
            toast_w, toast_h = 290, 34
            tx = (fw - toast_w) // 2
            ty = max(70, fh // 2 - 17)
            draw_rounded_glass_pill(frame, tx, ty, toast_w, toast_h, radius=8, bg_color=(15, 20, 30), alpha=0.88, border_color=(0, 220, 255))
            cv2.putText(frame, self._mode_switch_text, (tx + 18, ty + 23), cv2.FONT_HERSHEY_DUPLEX, 0.44, (255, 255, 255), 1, cv2.LINE_AA)

        # Mode 2: Immersive off (returns clean camera frame)
        if self.hud_mode == 2:
            return frame

        if tracked_mask is None:
            tracked_mask = 1 if is_tracked else 0

        # =====================================================================
        # TOP RIGHT PILL: FPS & IPC BRIDGE TELEMETRY (Only in Full HUD)
        # =====================================================================
        right_w, right_h = 236, 44
        right_x, right_y = fw - right_w - 16, 14
        if self.hud_mode == 0:
            draw_rounded_glass_pill(frame, right_x, right_y, right_w, right_h, radius=12, bg_color=COLOR_GLASS_BG, alpha=0.74, border_color=COLOR_GLASS_BORDER)

            # IPC / Game Hook diagnostic status in Top-Right Pill
            emu_err = str((kinect_emu_status or {}).get("last_error_code") or "")
            emu_conn = bool((kinect_emu_status or {}).get("connected", False))
            if emu_err == "ACCESS_DENIED":
                ipc_dot_color = COLOR_STATUS_WAIT
                bridge_text = "GAME: Run as Administrator!"
            elif emu_err in ("LOADLIB_RETURNED_NULL", "PROXY_NOT_LOADED", "REMOTE_THREAD_FAIL"):
                ipc_dot_color = COLOR_STATUS_WAIT
                bridge_text = "GAME: Check Antivirus/AV!"
            elif emu_conn:
                ipc_dot_color = COLOR_STATUS_OK
                bridge_text = "IPC: 2P Active • Game OK" if max_players >= 2 else "IPC: Active • Game Linked"
            else:
                ipc_dot_color = COLOR_STATUS_OK
                bridge_text = "IPC: JDP2 & JMI2 Active" if max_players >= 2 else "IPC: JDP1 & JMI1 Active"

            ipc_dot_x, ipc_dot_y = right_x + 18, right_y + 22
            cv2.circle(frame, (ipc_dot_x, ipc_dot_y), 4, ipc_dot_color, -1, cv2.LINE_AA)
            cv2.circle(frame, (ipc_dot_x, ipc_dot_y), 6, ipc_dot_color, 1, cv2.LINE_AA)

            fps_text = f"CAM: {cam_fps:.0f} FPS  |  AI: {track_fps:.0f} FPS"
            cv2.putText(frame, fps_text, (right_x + 32, right_y + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.40, COLOR_NEON_CYAN, 1, cv2.LINE_AA)
            cv2.putText(frame, bridge_text, (right_x + 32, right_y + 36), cv2.FONT_HERSHEY_SIMPLEX, 0.35, ipc_dot_color, 1, cv2.LINE_AA)

        # =====================================================================
        # RIGHT PILL (BELOW FPS): DANCER TRACKING STATUS (Visible in Full & Minimalist)
        # =====================================================================
        if max_players >= 2:
            p1_on = bool(tracked_mask & 1)
            p2_on = bool(tracked_mask & 2)
            if p1_on and p2_on:
                status_text = "2P: P1 + P2 ACTIVE"
                status_sub = "Full Duo Tracking"
                badge_color = COLOR_STATUS_OK
            elif p1_on:
                status_text = "2P: P1 ACTIVE"
                status_sub = "Waiting for Player 2"
                badge_color = COLOR_P1_SILHOUETTE
            elif p2_on:
                status_text = "2P: P2 ACTIVE"
                status_sub = "Waiting for Player 1"
                badge_color = COLOR_P2_SILHOUETTE
            else:
                status_text = "SEARCHING PLAYERS..."
                status_sub = "Step into camera frame"
                badge_color = COLOR_STATUS_WAIT
        else:
            if is_tracked:
                tier_desc = "Full Body Calibrated" if calibration_tier == "full_body" else "Flexible Half Body / Desk"
                status_text = "DANCER ACTIVE"
                status_sub = tier_desc
                badge_color = COLOR_STATUS_OK
            else:
                status_text = "SEARCHING DANCER..."
                status_sub = "Step into camera frame"
                badge_color = COLOR_STATUS_WAIT

        status_w, status_h = 236, 44
        status_x = fw - status_w - 16
        # In Minimalist mode, place at top right (y=14); in Full HUD, stack directly below FPS pill (y=66)
        status_y = 14 if self.hud_mode == 1 else (right_y + right_h + 8)
        draw_rounded_glass_pill(frame, status_x, status_y, status_w, status_h, radius=12, bg_color=COLOR_GLASS_BG, alpha=0.78, border_color=badge_color)

        # Pulsing status dot
        pulse_r = int(5 + (math.sin(now * 4.0) + 1.0) * 1.5)
        dot_x, dot_y = status_x + 18, status_y + 22
        cv2.circle(frame, (dot_x, dot_y), pulse_r + 2, badge_color, 1, cv2.LINE_AA)
        cv2.circle(frame, (dot_x, dot_y), 4, badge_color, -1, cv2.LINE_AA)

        cv2.putText(frame, status_text, (status_x + 34, status_y + 20), cv2.FONT_HERSHEY_DUPLEX, 0.42, COLOR_TEXT_WHITE, 1, cv2.LINE_AA)
        cv2.putText(frame, status_sub, (status_x + 34, status_y + 36), cv2.FONT_HERSHEY_SIMPLEX, 0.33, COLOR_TEXT_DIM, 1, cv2.LINE_AA)

        # In Minimalist Mode (hud_mode == 1), only the status badge (and phone rotate alert if portrait) is shown
        if self.hud_mode == 1:
            if phone_portrait_warning:
                self._draw_phone_orientation_pill(frame, fh - 6, now)
            return frame

        # =====================================================================
        # TOP LEFT PILL: BRANDING & CAMERA PROFILE
        # =====================================================================
        left_w, left_h = min(260, max(200, fw - right_w - 48)), 44
        left_x, left_y = 16, 14
        draw_rounded_glass_pill(frame, left_x, left_y, left_w, left_h, radius=12, bg_color=COLOR_GLASS_BG, alpha=0.74, border_color=COLOR_GLASS_BORDER)

        # PlayStation Blue accent orb
        orb_x, orb_y = left_x + 18, left_y + 22
        cv2.circle(frame, (orb_x, orb_y), 7, (255, 120, 20), -1, cv2.LINE_AA)
        cv2.circle(frame, (orb_x, orb_y), 9, (255, 255, 255), 1, cv2.LINE_AA)

        cv2.putText(frame, "LEGACY PSCAM SENSOR", (left_x + 36, left_y + 20), cv2.FONT_HERSHEY_DUPLEX, 0.44, COLOR_TEXT_WHITE, 1, cv2.LINE_AA)
        mode_tag = "[2P DUO]" if max_players >= 2 else "[1P SOLO]"
        cam_sub = f"{camera_info_str} {mode_tag} {'[MIRROR]' if is_mirrored else ''}"
        if len(cam_sub) > 30 and left_w < 260:
            cam_sub = cam_sub[:28] + ".."
        cv2.putText(frame, cam_sub, (left_x + 36, left_y + 36), cv2.FONT_HERSHEY_SIMPLEX, 0.34, COLOR_TEXT_DIM, 1, cv2.LINE_AA)

        # =====================================================================
        # BOTTOM CENTER PILL: CONSOLE SHORTCUT BADGES
        # =====================================================================
        bot_w, bot_h = min(fw - 24, 520), 32
        bot_x = (fw - bot_w) // 2
        bot_y = max(60, fh - bot_h - 12)
        draw_rounded_glass_pill(frame, bot_x, bot_y, bot_w, bot_h, radius=10, bg_color=COLOR_GLASS_BG, alpha=0.78, border_color=COLOR_GLASS_BORDER)

        controls_text = "[C] Calibrate  •  [M] Mirror  •  [H] HUD  •  [P] PiP  •  [Q/ESC] Exit"
        t_sz = cv2.getTextSize(controls_text, cv2.FONT_HERSHEY_SIMPLEX, 0.36, 1)[0]
        tx = bot_x + (bot_w - t_sz[0]) // 2
        cv2.putText(frame, controls_text, (tx, bot_y + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (225, 230, 240), 1, cv2.LINE_AA)

        # =====================================================================
        # PHONE CAMERA PORTRAIT NOTIFICATION PILL (Directly above controls bar)
        # =====================================================================
        if phone_portrait_warning:
            self._draw_phone_orientation_pill(frame, bot_y, now)

        return frame

    def draw_controller_hud(
        self,
        frame: np.ndarray,
        controller_name: str = "DualShock 4",
        conn_type: str = "Bluetooth",
        hand: str = "right",
        sens: float = 1.0,
        sample_rate_hz: float = 0.0,
        battery_pct: int = 0,
        is_charging: bool = False,
        is_connected: bool = True,
        imu_frozen: bool = False,
        vphone_status: str = "Connected",
        vphone_connected: bool = False,
        tot_g: float = 1.0,
        current_coach: int = 0,
        total_coaches: int = 4,
        song_name: Optional[str] = None,
        action_toast: Optional[str] = None,
        accel_axes: Tuple[float, float, float] = (0.0, 1.0, 0.0),
        gyro_axes: Optional[Tuple[int, int, int]] = None,
    ) -> np.ndarray:
        """
        Renders the modern PlayStation floating glass pill HUD for the controller tracking session.
        Matches the layout, typography, glass pill badges, and aesthetic of the webcam tracking UI.
        Features sleek 6-axis IMU/gyro telemetry bars and non-pulsating motion force indicator.
        """
        now = time.time()
        fh, fw = frame.shape[:2]

        # Draw temporary mode switch toast notification if active
        if now - self._last_mode_switch_time < 1.6 and self._mode_switch_text:
            toast_w, toast_h = 290, 34
            tx = (fw - toast_w) // 2
            ty = max(70, fh // 2 - 17)
            draw_rounded_glass_pill(frame, tx, ty, toast_w, toast_h, radius=8, bg_color=(15, 20, 30), alpha=0.88, border_color=(0, 220, 255))
            cv2.putText(frame, self._mode_switch_text, (tx + 18, ty + 23), cv2.FONT_HERSHEY_DUPLEX, 0.44, (255, 255, 255), 1, cv2.LINE_AA)

        # Mode 2: Off / clean canvas
        if self.hud_mode == 2:
            return frame

        # =====================================================================
        # TOP RIGHT PILL: POLLING RATE & BATTERY TELEMETRY (Only in Full HUD)
        # =====================================================================
        right_w, right_h = 246, 44
        right_x, right_y = fw - right_w - 16, 14
        if self.hud_mode == 0:
            draw_rounded_glass_pill(
                frame, right_x, right_y, right_w, right_h,
                radius=12, bg_color=COLOR_GLASS_BG, alpha=0.74, border_color=COLOR_GLASS_BORDER
            )

            # Polling status dot
            dot_color = COLOR_STATUS_OK if (is_connected and not imu_frozen) else COLOR_STATUS_WAIT
            ipc_dot_x, ipc_dot_y = right_x + 18, right_y + 22
            cv2.circle(frame, (ipc_dot_x, ipc_dot_y), 4, dot_color, -1, cv2.LINE_AA)
            cv2.circle(frame, (ipc_dot_x, ipc_dot_y), 6, dot_color, 1, cv2.LINE_AA)

            if is_connected:
                chg_str = " [CHG]" if is_charging else ""
                telemetry_text = f"POLL: {sample_rate_hz:.0f} HZ  |  BATT: {battery_pct}%{chg_str}"
            else:
                telemetry_text = "POLL: -- HZ  |  BATT: --"
            cv2.putText(frame, telemetry_text, (right_x + 32, right_y + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.38, COLOR_NEON_CYAN, 1, cv2.LINE_AA)

            vphone_text = f"VPHONE: {vphone_status}"
            v_color = COLOR_STATUS_OK if vphone_connected else COLOR_TEXT_DIM
            cv2.putText(frame, vphone_text, (right_x + 32, right_y + 36), cv2.FONT_HERSHEY_SIMPLEX, 0.34, v_color, 1, cv2.LINE_AA)

        # =====================================================================
        # RIGHT PILL (BELOW TELEMETRY): CONTROLLER TRACKING STATUS
        # =====================================================================
        if is_connected and not imu_frozen:
            status_text = "CONTROLLER ACTIVE"
            status_sub = f"Ready to Dance • Sens {sens:.2f}x"
            badge_color = COLOR_STATUS_OK
        elif is_connected and imu_frozen:
            status_text = "SENSOR IMU FROZEN"
            status_sub = "Connect via USB Cable"
            badge_color = (0, 140, 255)
        else:
            status_text = "SEARCHING CONTROLLER..."
            status_sub = "Press [R] to Reconnect"
            badge_color = COLOR_STATUS_WAIT

        status_w, status_h = 246, 44
        status_x = fw - status_w - 16
        status_y = 14 if self.hud_mode == 1 else (right_y + right_h + 8)
        draw_rounded_glass_pill(
            frame, status_x, status_y, status_w, status_h,
            radius=12, bg_color=COLOR_GLASS_BG, alpha=0.78, border_color=badge_color
        )

        pulse_r = int(5 + (math.sin(now * 4.0) + 1.0) * 1.5)
        dot_x, dot_y = status_x + 18, status_y + 22
        cv2.circle(frame, (dot_x, dot_y), pulse_r + 2, badge_color, 1, cv2.LINE_AA)
        cv2.circle(frame, (dot_x, dot_y), 4, badge_color, -1, cv2.LINE_AA)

        cv2.putText(frame, status_text, (status_x + 34, status_y + 20), cv2.FONT_HERSHEY_DUPLEX, 0.42, COLOR_TEXT_WHITE, 1, cv2.LINE_AA)
        cv2.putText(frame, status_sub, (status_x + 34, status_y + 36), cv2.FONT_HERSHEY_SIMPLEX, 0.33, COLOR_TEXT_DIM, 1, cv2.LINE_AA)

        # In Minimalist Mode (hud_mode == 1), top left pill and bottom pill are hidden
        if self.hud_mode == 0:
            # =====================================================================
            # TOP LEFT PILL: BRANDING & CONTROLLER PROFILE
            # =====================================================================
            left_w, left_h = min(280, max(210, fw - right_w - 48)), 44
            left_x, left_y = 16, 14
            draw_rounded_glass_pill(
                frame, left_x, left_y, left_w, left_h,
                radius=12, bg_color=COLOR_GLASS_BG, alpha=0.74, border_color=COLOR_GLASS_BORDER
            )

            # PlayStation Blue accent orb
            orb_x, orb_y = left_x + 18, left_y + 22
            cv2.circle(frame, (orb_x, orb_y), 7, (255, 120, 20), -1, cv2.LINE_AA)
            cv2.circle(frame, (orb_x, orb_y), 9, (255, 255, 255), 1, cv2.LINE_AA)

            cv2.putText(frame, "LEGACY PSCAM SENSOR", (left_x + 36, left_y + 20), cv2.FONT_HERSHEY_DUPLEX, 0.44, COLOR_TEXT_WHITE, 1, cv2.LINE_AA)
            c_tag = f"{controller_name.upper()} [{conn_type.upper()}] • {hand.upper()} HAND"
            if len(c_tag) > 32 and left_w < 280:
                c_tag = c_tag[:30] + ".."
            cv2.putText(frame, c_tag, (left_x + 36, left_y + 36), cv2.FONT_HERSHEY_SIMPLEX, 0.34, COLOR_TEXT_DIM, 1, cv2.LINE_AA)

        # =====================================================================
        # CENTER STAGE: MOTION FORCE (CLEAN & NON-PULSATING) & GYROSCOPE BARS
        # =====================================================================
        cx = fw // 2
        cy = 168

        if not is_connected:
            warn_w, warn_h = min(460, fw - 40), 62
            wx = (fw - warn_w) // 2
            wy = cy - warn_h // 2
            draw_rounded_glass_pill(
                frame, wx, wy, warn_w, warn_h,
                radius=12, bg_color=(24, 16, 20), alpha=0.88, border_color=COLOR_STATUS_WAIT
            )
            cv2.putText(frame, "[!] CONTROLLER NOT CONNECTED", (wx + 24, wy + 26), cv2.FONT_HERSHEY_DUPLEX, 0.48, COLOR_TEXT_WHITE, 1, cv2.LINE_AA)
            cv2.putText(frame, "Turn on controller or press [R] to search and reconnect", (wx + 24, wy + 48), cv2.FONT_HERSHEY_SIMPLEX, 0.36, COLOR_TEXT_DIM, 1, cv2.LINE_AA)
        elif imu_frozen:
            warn_w, warn_h = min(480, fw - 40), 62
            wx = (fw - warn_w) // 2
            wy = cy - warn_h // 2
            draw_rounded_glass_pill(
                frame, wx, wy, warn_w, warn_h,
                radius=12, bg_color=(16, 20, 28), alpha=0.88, border_color=(0, 140, 255)
            )
            cv2.putText(frame, "[!] SENSOR IMU BLOCKED / FROZEN (0G)", (wx + 24, wy + 26), cv2.FONT_HERSHEY_DUPLEX, 0.46, COLOR_TEXT_WHITE, 1, cv2.LINE_AA)
            cv2.putText(frame, "Generic Bluetooth driver blocked motion. Connect via USB cable!", (wx + 24, wy + 48), cv2.FONT_HERSHEY_SIMPLEX, 0.35, COLOR_TEXT_DIM, 1, cv2.LINE_AA)
        else:
            # Clean Non-Pulsating Motion Force Circle (stable frosted glass disc)
            base_r = 44
            disc_w = base_r * 2
            cv2.circle(frame, (cx, cy), base_r + 3, (45, 55, 70), 1, cv2.LINE_AA)
            draw_rounded_glass_pill(
                frame, cx - base_r, cy - base_r, disc_w, disc_w,
                radius=base_r, bg_color=(16, 20, 28), alpha=0.74, border_color=(60, 75, 95)
            )

            g_str = f"{tot_g:.2f} G"
            t_sz = cv2.getTextSize(g_str, cv2.FONT_HERSHEY_DUPLEX, 0.58, 1)[0]
            gx = cx - t_sz[0] // 2
            gy = cy + 4
            cv2.putText(frame, g_str, (gx, gy), cv2.FONT_HERSHEY_DUPLEX, 0.58, COLOR_TEXT_WHITE, 1, cv2.LINE_AA)

            lbl_str = "MOTION FORCE"
            l_sz = cv2.getTextSize(lbl_str, cv2.FONT_HERSHEY_SIMPLEX, 0.28, 1)[0]
            cv2.putText(frame, lbl_str, (cx - l_sz[0] // 2, cy + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.28, COLOR_TEXT_DIM, 1, cv2.LINE_AA)

            # Modern Gyroscope & Accelerometer Telemetry Card (X, Y, Z bars)
            card_w = min(fw - 40, 470)
            card_h = 136
            card_x = (fw - card_w) // 2
            card_y = 224
            draw_rounded_glass_pill(
                frame, card_x, card_y, card_w, card_h,
                radius=12, bg_color=(15, 18, 25), alpha=0.76, border_color=(50, 60, 75)
            )

            # Card Header
            cv2.circle(frame, (card_x + 18, card_y + 16), 3, (0, 220, 255), -1, cv2.LINE_AA)
            cv2.putText(frame, "GYROSCOPE & ACCELEROMETER TELEMETRY", (card_x + 28, card_y + 20), cv2.FONT_HERSHEY_DUPLEX, 0.35, (215, 225, 240), 1, cv2.LINE_AA)
            sens_txt = f"SENS: {sens:.2f}x"
            st_w = cv2.getTextSize(sens_txt, cv2.FONT_HERSHEY_SIMPLEX, 0.31, 1)[0][0]
            cv2.putText(frame, sens_txt, (card_x + card_w - st_w - 18, card_y + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.31, COLOR_TEXT_DIM, 1, cv2.LINE_AA)
            cv2.line(frame, (card_x + 14, card_y + 27), (card_x + card_w - 14, card_y + 27), (35, 42, 54), 1, cv2.LINE_AA)

            # 3 Axis Bars (X, Y, Z)
            ax_val, ay_val, az_val = accel_axes
            axes_data = [
                ("X: LATERAL", ax_val, (245, 225, 30)),   # Electric Cyan
                ("Y: VERTICAL", ay_val, (60, 195, 255)),  # PlayStation Warm Amber
                ("Z: FORWARD", az_val, (80, 220, 110)),   # Neon Emerald
            ]

            bx = card_x + 235
            hw = 110  # half-width for 220px total bar width

            for idx, (axis_lbl, val, col) in enumerate(axes_data):
                row_y = card_y + 38 + idx * 31

                # Axis label
                cv2.putText(frame, axis_lbl, (card_x + 18, row_y + 12), cv2.FONT_HERSHEY_SIMPLEX, 0.31, COLOR_TEXT_DIM, 1, cv2.LINE_AA)

                # Track background with center 0G tick
                cv2.rectangle(frame, (bx - hw, row_y + 3), (bx + hw, row_y + 13), (24, 28, 36), -1)
                cv2.rectangle(frame, (bx - hw, row_y + 3), (bx + hw, row_y + 13), (48, 56, 70), 1, cv2.LINE_AA)
                cv2.line(frame, (bx, row_y + 1), (bx, row_y + 15), (110, 120, 135), 1, cv2.LINE_AA)

                # Active bar fill (scaled to +/- 3.0 G)
                fill_len = int(max(-hw, min(hw, (val / 3.0) * hw)))
                if fill_len > 0:
                    cv2.rectangle(frame, (bx, row_y + 4), (bx + fill_len, row_y + 12), col, -1)
                elif fill_len < 0:
                    cv2.rectangle(frame, (bx + fill_len, row_y + 4), (bx, row_y + 12), col, -1)

                # Value readout on the right
                val_str = f"{val:+.2f} G"
                cv2.putText(frame, val_str, (card_x + card_w - 74, row_y + 12), cv2.FONT_HERSHEY_SIMPLEX, 0.33, (240, 240, 245), 1, cv2.LINE_AA)

        # =====================================================================
        # BOTTOM CENTER PILL: SHORTCUTS BAR
        # =====================================================================
        bot_w, bot_h = min(fw - 32, 510), 32
        bot_x = (fw - bot_w) // 2
        bot_y = max(60, fh - bot_h - 12)
        if self.hud_mode == 0:
            draw_rounded_glass_pill(
                frame, bot_x, bot_y, bot_w, bot_h,
                radius=10, bg_color=COLOR_GLASS_BG, alpha=0.78, border_color=COLOR_GLASS_BORDER
            )

            controls_text = "[Q/ESC] Exit  •  [R] Reconnect  •  [L1/R1] Coach  •  [H] Cycle HUD"
            t_sz = cv2.getTextSize(controls_text, cv2.FONT_HERSHEY_SIMPLEX, 0.38, 1)[0]
            tx = bot_x + (bot_w - t_sz[0]) // 2
            cv2.putText(frame, controls_text, (tx, bot_y + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (225, 230, 240), 1, cv2.LINE_AA)

        # =====================================================================
        # COACH SELECTION PILL (Directly above keyboard commands bar)
        # =====================================================================
        coach_w, coach_h = min(fw - 40, 360), 34
        coach_x = (fw - coach_w) // 2
        coach_y = bot_y - coach_h - 8
        draw_rounded_glass_pill(
            frame, coach_x, coach_y, coach_w, coach_h,
            radius=10, bg_color=COLOR_GLASS_BG, alpha=0.82, border_color=COLOR_GLASS_BORDER
        )

        cv2.putText(frame, "[L1]", (coach_x + 16, coach_y + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 220, 255), 1, cv2.LINE_AA)
        c_text = f"COACH {current_coach + 1} OF {total_coaches}"
        ct_sz = cv2.getTextSize(c_text, cv2.FONT_HERSHEY_DUPLEX, 0.42, 1)[0]
        cv2.putText(frame, c_text, (coach_x + (coach_w - ct_sz[0]) // 2, coach_y + 22), cv2.FONT_HERSHEY_DUPLEX, 0.42, COLOR_TEXT_WHITE, 1, cv2.LINE_AA)
        cv2.putText(frame, "[R1]", (coach_x + coach_w - 50, coach_y + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 220, 255), 1, cv2.LINE_AA)

        # Song name above coach pill if active
        if song_name and song_name not in ("DanceSession", "None", ""):
            s_text = f"SONG: {song_name}"
            st_sz = cv2.getTextSize(s_text, cv2.FONT_HERSHEY_SIMPLEX, 0.31, 1)[0]
            cv2.putText(frame, s_text, ((fw - st_sz[0]) // 2, coach_y - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.31, COLOR_TEXT_DIM, 1, cv2.LINE_AA)

        # =====================================================================
        # ACTION TOAST (E.G. RECONNECTING, COACH SWITCH, CONFIRM)
        # =====================================================================
        if action_toast:
            toast_w, toast_h = 340, 36
            tx = (fw - toast_w) // 2
            ty = max(68, cy - 88)
            draw_rounded_glass_pill(frame, tx, ty, toast_w, toast_h, radius=8, bg_color=(15, 24, 34), alpha=0.92, border_color=(0, 225, 255))
            tt_sz = cv2.getTextSize(action_toast, cv2.FONT_HERSHEY_DUPLEX, 0.42, 1)[0]
            cv2.putText(frame, action_toast, (tx + (toast_w - tt_sz[0]) // 2, ty + 23), cv2.FONT_HERSHEY_DUPLEX, 0.42, (0, 235, 255), 1, cv2.LINE_AA)

        return frame
