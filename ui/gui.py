"""
Modern PlayStation-Themed UI for Legacy Sensor Lite.
Features a horizontal split layout:
- Left Sidebar: Rounded device switcher (PlayStation 4 Camera vs Standard Webcam) with custom icons.
- Mini Credits: Bottom-left recognition for itsVexor (Legacy Sensor) & BumbleTree (PSCam4Win).
- Top Navigation: Clean tabs for 'Configuração de Vídeo' and 'Calibração'.
- Context-Aware Panels: PlayStation Camera automatically hides resolution/device pickers.
- Modern gamer aesthetic with iconic PlayStation dark blue accents (#00439C) on clean surfaces.
"""
import os
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
import tkinter.font as tkfont
from pathlib import Path
from PIL import Image, ImageDraw, ImageTk

try:
    from sensor.config_manager import ConfigManager, PRESETS_PSCAM, PRESETS_WEBCAM
    from sensor.camera_manager import CameraManager
    from sensor.kinect_shared_memory import KinectBridge
    from sensor import tracking_session
except (ImportError, ValueError):
    from config_manager import ConfigManager, PRESETS_PSCAM, PRESETS_WEBCAM
    from camera_manager import CameraManager
    from kinect_shared_memory import KinectBridge
    import tracking_session

# --- Modern PlayStation Blue Palette ---
PALETTE = {
    # Brand Accents — Official PlayStation Blue Theme
    "ps_blue": "#00439C",          # Iconic PlayStation dark blue
    "ps_blue_hover": "#00367A",    # Deeper blue hover state
    "ps_blue_active": "#00295C",   # Clicked / pressed state
    "ps_blue_tint": "#E8F0FE",     # Soft light blue tint
    "blue_pastel": "#DDF0F7",      # Soft baby blue secondary accent
    "blue_pastel_hover": "#CEEAF5",# Hover for blue elements
    "blue_dark": "#1D3557",        # Deep navy blue for headings & icons

    # Surfaces & Backgrounds
    "bg_window": "#F8F9FC",        # Near-white clean canvas
    "bg_sidebar": "#FFFFFF",       # Crisp white sidebar
    "bg_card": "#FFFFFF",          # Crisp white card surfaces
    "border_subtle": "#E2E8F0",    # Clean 1px structural borders
    "border_active": "#00439C",    # Active PlayStation blue border
    "input_bg": "#F1F5F9",         # Light field background
    "input_border": "#CBD5E1",     # Input border color
    "tab_gray_act": "#E2E8F0",     # Active gray selection tab pill
    "tab_gray_border": "#CBD5E1",  # Active gray border
    "tab_gray_hover": "#F1F5F9",   # Hover state for inactive tab

    # Typography
    "text_main": "#292929",        # Extra dark gray for high readability
    "text_muted": "#6E7787",       # Neutral medium gray for secondary info
    "text_dim": "#94A3B8",         # Slate light gray for footer/metadata
    "text_white": "#FFFFFF",       # Crisp white

    # Status Pills
    "status_ok": "#059669",        # Modern emerald green
    "status_ok_bg": "#D1FAE5",     # Soft green tint
    "status_warn": "#D97706",      # Warm amber yellow
    "status_warn_bg": "#FEF3C7",   # Soft amber tint
    "status_err": "#DC2626",       # Red
    "status_err_bg": "#FEE2E2",    # Soft red tint
}

# Simplified Game-Style Calibration Presets
CALIB_PRESETS = {
    "balanced": {
        "id": "balanced",
        "title": "Balanced",
        "icon": "★",
        "tag": "RECOMMENDED",
        "subtitle": "Smooth & Precise",
        "desc": "Ideal default balance for most songs. Smooth movement without jitters.",
        "smoothing_alpha": 0.55,
        "detection_confidence": 0.50,
        "specs": "EMA 0.55 • Conf 0.50",
    },
    "competitive": {
        "id": "competitive",
        "title": "Competitive",
        "icon": "⚡",
        "tag": "FAST RESPONSE",
        "subtitle": "Lowest Latency",
        "desc": "Instant response for fast choreographies, extreme routines, and rapid arm gestures.",
        "smoothing_alpha": 0.75,
        "detection_confidence": 0.45,
        "specs": "EMA 0.75 • Conf 0.45",
    },
    "stable": {
        "id": "stable",
        "title": "Ultra Stable",
        "icon": "🛡",
        "tag": "ANTI-JITTER",
        "subtitle": "Maximum Filtering",
        "desc": "Intensive filtering against visual noise. Recommended for dimly lit rooms.",
        "smoothing_alpha": 0.35,
        "detection_confidence": 0.40,
        "specs": "EMA 0.35 • Conf 0.40",
    },
}

def get_font_family():
    """Detects available modern geometric sans-serif fonts."""
    try:
        families = [f.lower() for f in tkfont.families()]
        for pref in ("montserrat", "poppins", "segoe ui", "helvetica", "arial"):
            for f in families:
                if pref in f:
                    return "Segoe UI" if pref == "segoe ui" else pref.title()
    except Exception:
        pass
    return "Segoe UI"

def make_pill_image(w: int, h: int, fill, outline=None, radius: int = 12):
    """Generates an anti-aliased rounded rectangle pill image."""
    scale = 4
    img = Image.new("RGBA", (w * scale, h * scale), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(
        [2 * scale, 2 * scale, w * scale - 3 * scale, h * scale - 3 * scale],
        radius=radius * scale,
        fill=fill,
        outline=outline,
        width=1 * scale
    )
    return ImageTk.PhotoImage(img.resize((w, h), Image.Resampling.LANCZOS))

def load_pscam_file_icon(png_path: Path, target_box=(38, 26), color=(255, 255, 255)):
    """
    Loads user-provided IconePSCAMERA.png, converts dark background to transparent alpha,
    recolors the icon graphic to the target color, and scales it into target_box.
    """
    if not png_path.exists():
        return None
    try:
        import numpy as np
        im = Image.open(png_path).convert("RGBA")
        arr = np.array(im)
        # Compute luminance of RGB to isolate the white camera graphic from the dark background
        lum = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
        # Smooth alpha mapping (threshold dark noise at 15, full opacity at 180)
        alpha = np.clip((lum - 15) / (180 - 15) * 255, 0, 255).astype(np.uint8)

        out_arr = np.zeros_like(arr)
        out_arr[:, :, 0] = color[0]
        out_arr[:, :, 1] = color[1]
        out_arr[:, :, 2] = color[2]
        out_arr[:, :, 3] = alpha

        colored_im = Image.fromarray(out_arr, "RGBA")
        bbox = colored_im.getbbox()
        if not bbox:
            return None
        cropped = colored_im.crop(bbox)

        # Scale proportionally to fit within target_box
        bw, bh = target_box
        scale = min(bw / cropped.width, bh / cropped.height)
        new_w = max(1, int(cropped.width * scale))
        new_h = max(1, int(cropped.height * scale))
        resized = cropped.resize((new_w, new_h), Image.Resampling.LANCZOS)

        canvas = Image.new("RGBA", target_box, (0, 0, 0, 0))
        canvas.paste(resized, ((bw - new_w) // 2, (bh - new_h) // 2))
        return canvas
    except Exception as e:
        print(f"[WARN] Failed to process IconePSCAMERA.png: {e}")
        return None

def generate_icons():
    """
    Renders supersampled icons for the sidebar navigation:
    1. PlayStation 4 Camera (loaded from IconePSCAMERA.png with vector fallback).
    2. Generic round Webcam (circular head with lens aperture and stand, perfectly centered with no clipping).
    Returns active (white) and inactive (dark blue) ImageTk.PhotoImage variants.
    """
    target_box = (38, 26)
    base_dir = Path(__file__).resolve().parent
    png_candidates = [
        base_dir.parent / "assets" / "IconePSCAMERA.png",
        base_dir / "assets" / "IconePSCAMERA.png",
        base_dir.parent / "IconePSCAMERA.png",
        base_dir / "IconePSCAMERA.png"
    ]
    png_path = next((p for p in png_candidates if p.exists()), base_dir.parent / "assets" / "IconePSCAMERA.png")

    # 1. PS4 Camera Icon (from file or vector fallback)
    ps_file_act = load_pscam_file_icon(png_path, target_box=target_box, color=(255, 255, 255))
    ps_file_inact = load_pscam_file_icon(png_path, target_box=target_box, color=(0, 67, 156))

    if ps_file_act is not None and ps_file_inact is not None:
        p_ps_act = ImageTk.PhotoImage(ps_file_act)
        p_ps_inact = ImageTk.PhotoImage(ps_file_inact)
    else:
        # Fallback vector icon
        scale = 4
        w, h = target_box[0] * scale, target_box[1] * scale
        img_ps_act = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img_ps_act)
        d.rounded_rectangle([int(w * 0.08), int(h * 0.28), int(w * 0.92), int(h * 0.54)],
                            radius=int(5 * scale), fill=(255, 255, 255, 255))
        lr = int(3.8 * scale)
        cy = int(h * 0.41)
        d.ellipse([int(w * 0.30) - lr, cy - lr, int(w * 0.30) + lr, cy + lr], fill=(0, 67, 156, 255))
        d.ellipse([int(w * 0.70) - lr, cy - lr, int(w * 0.70) + lr, cy + lr], fill=(0, 67, 156, 255))
        d.rectangle([int(w * 0.44), int(h * 0.54), int(w * 0.56), int(h * 0.76)], fill=(255, 255, 255, 255))
        d.rounded_rectangle([int(w * 0.25), int(h * 0.76), int(w * 0.75), int(h * 0.86)],
                            radius=int(2 * scale), fill=(255, 255, 255, 255))
        p_ps_act = ImageTk.PhotoImage(img_ps_act.resize(target_box, Image.Resampling.LANCZOS))

        img_ps_inact = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img_ps_inact)
        d.rounded_rectangle([int(w * 0.08), int(h * 0.28), int(w * 0.92), int(h * 0.54)],
                            radius=int(5 * scale), fill=(0, 67, 156, 255))
        d.ellipse([int(w * 0.30) - lr, cy - lr, int(w * 0.30) + lr, cy + lr], fill=(221, 240, 247, 255))
        d.ellipse([int(w * 0.70) - lr, cy - lr, int(w * 0.70) + lr, cy + lr], fill=(221, 240, 247, 255))
        d.rectangle([int(w * 0.44), int(h * 0.54), int(w * 0.56), int(h * 0.76)], fill=(0, 67, 156, 255))
        d.rounded_rectangle([int(w * 0.25), int(h * 0.76), int(w * 0.75), int(h * 0.86)],
                            radius=int(2 * scale), fill=(0, 67, 156, 255))
        p_ps_inact = ImageTk.PhotoImage(img_ps_inact.resize(target_box, Image.Resampling.LANCZOS))

    # 2. Webcam Icon (Properly padded with zero clipping at the top or bottom)
    scale = 4
    w, h = target_box[0] * scale, target_box[1] * scale
    cr = int(7 * scale)          # Radius 28
    ccx = w // 2                 # 76
    ccy = int(h * 0.38)          # 39 -> top of head is 11 > 0 (plenty of room)

    # 2.1 Active Webcam Icon (White on PlayStation Blue)
    img_web_act = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img_web_act)
    # Head circle
    d.ellipse([ccx - cr, ccy - cr, ccx + cr, ccy + cr], fill=(255, 255, 255, 255))
    # Outer lens ring
    d.ellipse([ccx - int(5 * scale), ccy - int(5 * scale), ccx + int(5 * scale), ccy + int(5 * scale)],
              fill=(221, 240, 247, 255))
    # Inner lens aperture
    d.ellipse([ccx - int(3 * scale), ccy - int(3 * scale), ccx + int(3 * scale), ccy + int(3 * scale)],
              fill=(0, 67, 156, 255))
    # Glint highlight
    d.ellipse([ccx - int(2 * scale), ccy - int(2 * scale), ccx - int(0.5 * scale), ccy - int(0.5 * scale)],
              fill=(255, 255, 255, 255))
    # Stand stem
    stem_top = ccy + cr - int(1 * scale)
    stem_bottom = int(h * 0.80)
    d.rectangle([int(w * 0.45), stem_top, int(w * 0.55), stem_bottom], fill=(255, 255, 255, 255))
    # Stand base
    d.rounded_rectangle([int(w * 0.24), stem_bottom, int(w * 0.76), int(h * 0.92)],
                        radius=int(2 * scale), fill=(255, 255, 255, 255))
    p_web_act = ImageTk.PhotoImage(img_web_act.resize(target_box, Image.Resampling.LANCZOS))

    # 2.2 Inactive Webcam Icon (PlayStation Blue on light background)
    img_web_inact = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img_web_inact)
    d.ellipse([ccx - cr, ccy - cr, ccx + cr, ccy + cr], fill=(0, 67, 156, 255))
    d.ellipse([ccx - int(5 * scale), ccy - int(5 * scale), ccx + int(5 * scale), ccy + int(5 * scale)],
              fill=(221, 240, 247, 255))
    d.ellipse([ccx - int(3 * scale), ccy - int(3 * scale), ccx + int(3 * scale), ccy + int(3 * scale)],
              fill=(0, 67, 156, 255))
    d.ellipse([ccx - int(2 * scale), ccy - int(2 * scale), ccx - int(0.5 * scale), ccy - int(0.5 * scale)],
              fill=(255, 255, 255, 255))
    d.rectangle([int(w * 0.45), stem_top, int(w * 0.55), stem_bottom], fill=(0, 67, 156, 255))
    d.rounded_rectangle([int(w * 0.24), stem_bottom, int(w * 0.76), int(h * 0.92)],
                        radius=int(2 * scale), fill=(0, 67, 156, 255))
    p_web_inact = ImageTk.PhotoImage(img_web_inact.resize(target_box, Image.Resampling.LANCZOS))

    return p_ps_act, p_ps_inact, p_web_act, p_web_inact

def generate_tab_icons():
    """
    Renders supersampled icons for the top navigation tabs:
    1. Gear icon for 'Configuração de Vídeo'
    2. Sliders icon (3 horizontal lines with adjustment knobs) for 'Calibração'
    Returns active (dark #0F172A) and inactive (muted #64748B) PhotoImage pairs.
    """
    import math
    size = (18, 18)
    scale = 4
    w, h = size[0] * scale, size[1] * scale

    def make_gear(color):
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        cx, cy = w / 2, h / 2
        r_outer = w * 0.44
        r_inner = w * 0.30
        r_hole = w * 0.15
        teeth = 8
        for i in range(teeth):
            angle = (2 * math.pi / teeth) * i
            tw = 0.22
            pts = [
                (cx + r_inner * math.cos(angle - tw), cy + r_inner * math.sin(angle - tw)),
                (cx + r_outer * math.cos(angle - tw * 0.65), cy + r_outer * math.sin(angle - tw * 0.65)),
                (cx + r_outer * math.cos(angle + tw * 0.65), cy + r_outer * math.sin(angle + tw * 0.65)),
                (cx + r_inner * math.cos(angle + tw), cy + r_inner * math.sin(angle + tw)),
            ]
            d.polygon(pts, fill=color)
        d.ellipse([cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner], fill=color)
        d.ellipse([cx - r_hole, cy - r_hole, cx + r_hole, cy + r_hole], fill=(0, 0, 0, 0))
        return ImageTk.PhotoImage(img.resize(size, Image.Resampling.LANCZOS))

    def make_sliders(color):
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        line_w = int(2.2 * scale)
        knob_r = int(3.5 * scale)
        y_coords = [int(h * 0.23), int(h * 0.50), int(h * 0.77)]
        knob_xs = [int(w * 0.34), int(w * 0.68), int(w * 0.44)]
        x_left = int(w * 0.10)
        x_right = int(w * 0.90)
        for y, kx in zip(y_coords, knob_xs):
            d.line([(x_left, y), (x_right, y)], fill=color, width=line_w)
            d.ellipse([kx - knob_r, y - knob_r, kx + knob_r, y + knob_r], fill=color)
            hole_r = int(1.6 * scale)
            d.ellipse([kx - hole_r, y - hole_r, kx + hole_r, y + hole_r], fill=(226, 232, 240, 255))
        return ImageTk.PhotoImage(img.resize(size, Image.Resampling.LANCZOS))

    col_act = (15, 23, 42, 255)       # Dark charcoal
    col_inact = (100, 116, 139, 255)  # Muted slate
    return make_gear(col_act), make_gear(col_inact), make_sliders(col_act), make_sliders(col_inact)


class LegacySensorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Legacy Sensor Lite")
        self.root.geometry("960x580")
        self.root.minsize(920, 550)
        self.root.configure(bg=PALETTE["bg_window"])

        self.font_family = get_font_family()

        # Initialize shared memory bridges immediately on startup so Just Dance connects seamlessly
        self.bridge = KinectBridge()

        self.cfg_mgr = ConfigManager()
        self.cfg = self.cfg_mgr.config
        self.is_tracking_active = False
        self._last_hw_snapshot = CameraManager.get_hardware_snapshot()
        self._last_pscam_state = None
        self._is_refreshing_cams = False
        self.camera_list = []
        self.active_tab = "video"  # "video" | "calib"
        self.current_calib_preset = self.cfg.get("tracking_preset", "balanced")
        self.is_adv_calib_open = False
        self.calib_card_widgets = {}

        self._load_icons()
        self._setup_styles()
        self._build_ui()

        # Apply persisted mode and sync camera selection
        initial_mode = self.cfg.get("camera_mode", "pscam")
        self._set_mode(initial_mode)
        self._switch_tab("video")

        # Initial fast PS Camera state reflection and asynchronous camera discovery
        self._update_pscam_status()
        self._refresh_cameras_async()

        # Schedule non-blocking periodic status update (every 1.0s)
        self._schedule_periodic_check()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close_window)

    def _load_icons(self):
        try:
            self.icon_ps_act, self.icon_ps_inact, self.icon_web_act, self.icon_web_inact = generate_icons()
        except Exception as e:
            print(f"[WARN] Failed to render Pillow icons: {e}")
            self.icon_ps_act = self.icon_ps_inact = self.icon_web_act = self.icon_web_inact = None

        try:
            self.icon_gear_act, self.icon_gear_inact, self.icon_sliders_act, self.icon_sliders_inact = generate_tab_icons()
        except Exception as e:
            print(f"[WARN] Failed to render tab icons: {e}")
            self.icon_gear_act = self.icon_gear_inact = self.icon_sliders_act = self.icon_sliders_inact = None

        # Generate rounded pill backgrounds for the menu selection cards (radius 12)
        try:
            w, h = 234, 56
            self.pill_active = make_pill_image(w, h, fill=(0, 67, 156, 255), radius=12)
            self.pill_inactive = make_pill_image(w, h, fill=(248, 250, 252, 255), outline=(226, 232, 240, 255), radius=12)
            self.pill_hover = make_pill_image(w, h, fill=(241, 245, 249, 255), outline=(203, 213, 225, 255), radius=12)
        except Exception as e:
            print(f"[WARN] Failed to render rounded pills: {e}")
            self.pill_active = self.pill_inactive = self.pill_hover = None

        # Generate rounded gray pill backgrounds for top navigation tabs (radius 10)
        try:
            w_vid, w_cal, h_tab = 224, 146, 42
            # Active (modern sleek gray selection)
            self.pill_tab_vid_act = make_pill_image(w_vid, h_tab, fill=(226, 232, 240, 255), outline=(203, 213, 225, 255), radius=10)
            self.pill_tab_cal_act = make_pill_image(w_cal, h_tab, fill=(226, 232, 240, 255), outline=(203, 213, 225, 255), radius=10)

            # Inactive (clean white with subtle border)
            self.pill_tab_vid_inact = make_pill_image(w_vid, h_tab, fill=(255, 255, 255, 255), outline=(226, 232, 240, 255), radius=10)
            self.pill_tab_cal_inact = make_pill_image(w_cal, h_tab, fill=(255, 255, 255, 255), outline=(226, 232, 240, 255), radius=10)

            # Hover
            self.pill_tab_vid_hover = make_pill_image(w_vid, h_tab, fill=(241, 245, 249, 255), outline=(203, 213, 225, 255), radius=10)
            self.pill_tab_cal_hover = make_pill_image(w_cal, h_tab, fill=(241, 245, 249, 255), outline=(203, 213, 225, 255), radius=10)
        except Exception as e:
            print(f"[WARN] Failed to render tab pills: {e}")
            self.pill_tab_vid_act = self.pill_tab_vid_inact = self.pill_tab_vid_hover = None
            self.pill_tab_cal_act = self.pill_tab_cal_inact = self.pill_tab_cal_hover = None

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')

        # Generic Frame & Cards
        style.configure("TFrame", background=PALETTE["bg_window"])
        style.configure("Sidebar.TFrame", background=PALETTE["bg_sidebar"])
        style.configure("Card.TFrame", background=PALETTE["bg_card"], relief="solid", borderwidth=1)

        # Labels
        style.configure("TLabel", background=PALETTE["bg_window"], foreground=PALETTE["text_main"],
                        font=(self.font_family, 9))
        style.configure("Card.TLabel", background=PALETTE["bg_card"], foreground=PALETTE["text_main"],
                        font=(self.font_family, 9))
        style.configure("CardTitle.TLabel", background=PALETTE["bg_card"], foreground=PALETTE["text_main"],
                        font=(self.font_family, 10, "bold"))
        style.configure("Muted.TLabel", background=PALETTE["bg_card"], foreground=PALETTE["text_muted"],
                        font=(self.font_family, 8))

        # Checkbutton
        style.configure("Modern.TCheckbutton", background=PALETTE["bg_card"], foreground=PALETTE["text_main"],
                        font=(self.font_family, 9))
        style.map("Modern.TCheckbutton",
                  background=[('active', PALETTE["bg_card"])],
                  indicatorcolor=[('selected', PALETTE["ps_blue"]), ('!selected', '#FFFFFF')])

        # Combobox
        style.configure("Modern.TCombobox",
                        fieldbackground=PALETTE["input_bg"],
                        background=PALETTE["blue_pastel"],
                        foreground=PALETTE["text_main"],
                        bordercolor=PALETTE["input_border"],
                        arrowcolor=PALETTE["blue_dark"])
        style.map("Modern.TCombobox",
                  fieldbackground=[('readonly', PALETTE["input_bg"])],
                  foreground=[('readonly', PALETTE["text_main"])])

        # Scales / Sliders
        style.configure("Modern.Horizontal.TScale",
                        background=PALETTE["bg_card"],
                        troughcolor=PALETTE["blue_pastel"],
                        sliderrelief="flat")

    def _build_ui(self):
        # Master Container with Horizontal Split (Sidebar on Left, Main Content on Right)
        master_box = tk.Frame(self.root, bg=PALETTE["bg_window"])
        master_box.pack(fill=tk.BOTH, expand=True)

        # =========================================================================
        # 1. LEFT SIDEBAR (Device Selector, Branding & Credits)
        # =========================================================================
        self.sidebar = tk.Frame(master_box, bg=PALETTE["bg_sidebar"], width=270,
                                highlightbackground=PALETTE["border_subtle"], highlightthickness=1)
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)
        self.sidebar.pack_propagate(False)

        sidebar_pad = tk.Frame(self.sidebar, bg=PALETTE["bg_sidebar"], padx=18, pady=20)
        sidebar_pad.pack(fill=tk.BOTH, expand=True)

        # 1.1 Brand Header (Removed "Just Dance PC")
        lbl_brand = tk.Label(sidebar_pad, text="Legacy PSCam Sensor", font=(self.font_family, 15, "bold"),
                             fg=PALETTE["ps_blue"], bg=PALETTE["bg_sidebar"])
        lbl_brand.pack(anchor="w")

        lbl_edition = tk.Label(sidebar_pad, text="for Legacy Offline PC", font=(self.font_family, 8, "bold"),
                               fg=PALETTE["text_muted"], bg=PALETTE["bg_sidebar"])
        lbl_edition.pack(anchor="w", pady=(2, 16))

        # Divider
        tk.Frame(sidebar_pad, height=1, bg=PALETTE["border_subtle"]).pack(fill=tk.X, pady=(0, 16))

        # 1.2 Device Navigation Section Title
        lbl_nav_title = tk.Label(sidebar_pad, text="CAPTURE DEVICE", font=(self.font_family, 8, "bold"),
                                 fg=PALETTE["blue_dark"], bg=PALETTE["bg_sidebar"])
        lbl_nav_title.pack(anchor="w", pady=(0, 10))

        # 1.3 PlayStation 4 Camera Rounded Navigation Card
        self.card_pscam = tk.Canvas(
            sidebar_pad, width=234, height=56, bg=PALETTE["bg_sidebar"],
            highlightthickness=0, cursor="hand2"
        )
        self.card_pscam.pack(fill=tk.X, pady=(0, 8))
        self.card_pscam_bg = self.card_pscam.create_image(0, 0, anchor="nw", image=self.pill_active)
        self.card_pscam_icon = self.card_pscam.create_image(25, 28, anchor="center", image=self.icon_ps_act)
        self.card_pscam_title = self.card_pscam.create_text(
            52, 19, text="PlayStation®Camera", anchor="w",
            fill=PALETTE["text_white"], font=(self.font_family, 9, "bold")
        )
        self.card_pscam_sub = self.card_pscam.create_text(
            52, 37, text="OV580 Stereo • 60 FPS", anchor="w",
            fill=PALETTE["blue_pastel"], font=(self.font_family, 8)
        )

        def on_pscam_click(e=None):
            self._set_mode("pscam")

        def on_pscam_enter(e=None):
            if self.cfg.get("camera_mode") != "pscam" and self.pill_hover:
                self.card_pscam.itemconfig(self.card_pscam_bg, image=self.pill_hover)

        def on_pscam_leave(e=None):
            if self.cfg.get("camera_mode") != "pscam" and self.pill_inactive:
                self.card_pscam.itemconfig(self.card_pscam_bg, image=self.pill_inactive)

        self.card_pscam.bind("<Button-1>", on_pscam_click)
        self.card_pscam.tag_bind("all", "<Button-1>", on_pscam_click)
        self.card_pscam.bind("<Enter>", on_pscam_enter)
        self.card_pscam.bind("<Leave>", on_pscam_leave)

        # 1.4 Standard Webcam Rounded Navigation Card
        self.card_webcam = tk.Canvas(
            sidebar_pad, width=234, height=56, bg=PALETTE["bg_sidebar"],
            highlightthickness=0, cursor="hand2"
        )
        self.card_webcam.pack(fill=tk.X, pady=(0, 16))
        self.card_webcam_bg = self.card_webcam.create_image(0, 0, anchor="nw", image=self.pill_inactive)
        self.card_webcam_icon = self.card_webcam.create_image(25, 28, anchor="center", image=self.icon_web_inact)
        self.card_webcam_title = self.card_webcam.create_text(
            52, 19, text="Standard Webcam", anchor="w",
            fill=PALETTE["text_main"], font=(self.font_family, 9, "bold")
        )
        self.card_webcam_sub = self.card_webcam.create_text(
            52, 37, text="USB or Integrated", anchor="w",
            fill=PALETTE["text_muted"], font=(self.font_family, 8)
        )

        def on_webcam_click(e=None):
            self._set_mode("webcam")

        def on_webcam_enter(e=None):
            if self.cfg.get("camera_mode") != "webcam" and self.pill_hover:
                self.card_webcam.itemconfig(self.card_webcam_bg, image=self.pill_hover)

        def on_webcam_leave(e=None):
            if self.cfg.get("camera_mode") != "webcam" and self.pill_inactive:
                self.card_webcam.itemconfig(self.card_webcam_bg, image=self.pill_inactive)

        self.card_webcam.bind("<Button-1>", on_webcam_click)
        self.card_webcam.tag_bind("all", "<Button-1>", on_webcam_click)
        self.card_webcam.bind("<Enter>", on_webcam_enter)
        self.card_webcam.bind("<Leave>", on_webcam_leave)

        # 1.5 Quick Action DLL Link
        btn_dll = tk.Button(
            sidebar_pad,
            text="Open Kinect10.dll Folder",
            font=(self.font_family, 8, "bold"),
            bg=PALETTE["blue_pastel"],
            fg=PALETTE["blue_dark"],
            activebackground=PALETTE["blue_pastel_hover"],
            activeforeground=PALETTE["blue_dark"],
            relief="flat",
            bd=0,
            cursor="hand2",
            command=self._open_dll_folder
        )
        btn_dll.pack(fill=tk.X, ipady=5, pady=(0, 6))

        lbl_dll_tip = tk.Label(
            sidebar_pad,
            text="Copy Kinect10.dll to the game\nfolder to enable motion capture.",
            font=(self.font_family, 7),
            fg=PALETTE["text_muted"],
            bg=PALETTE["bg_sidebar"],
            justify="left"
        )
        lbl_dll_tip.pack(anchor="w", pady=(0, 14))

        # Spacer
        tk.Frame(sidebar_pad, bg=PALETTE["bg_sidebar"]).pack(fill=tk.BOTH, expand=True)

        # 1.6 Mini Credits to original authors
        credits_box = tk.Frame(sidebar_pad, bg=PALETTE["bg_sidebar"])
        credits_box.pack(fill=tk.X, pady=(0, 8))

        lbl_cred1 = tk.Label(
            credits_box,
            text="Original Legacy Sensor by itsVexor",
            font=(self.font_family, 7),
            fg=PALETTE["text_muted"],
            bg=PALETTE["bg_sidebar"],
            justify="left",
            anchor="w"
        )
        lbl_cred1.pack(anchor="w")

        lbl_cred2 = tk.Label(
            credits_box,
            text="PSCam4Win by BumbleTree",
            font=(self.font_family, 7),
            fg=PALETTE["text_muted"],
            bg=PALETTE["bg_sidebar"],
            justify="left",
            anchor="w"
        )
        lbl_cred2.pack(anchor="w")

        # 1.7 Bottom Status Pill in Sidebar
        status_box = tk.Frame(sidebar_pad, bg=PALETTE["status_ok_bg"],
                              highlightbackground=PALETTE["status_ok"], highlightthickness=1, padx=8, pady=6)
        status_box.pack(fill=tk.X)

        self.lbl_ipc_badge = tk.Label(
            status_box,
            text="● IPC Bridge Ready",
            font=(self.font_family, 8, "bold"),
            fg=PALETTE["status_ok"],
            bg=PALETTE["status_ok_bg"]
        )
        self.lbl_ipc_badge.pack(anchor="w")

        lbl_ipc_detail = tk.Label(
            status_box,
            text="JDP1 (Pose) & JMI1 (Silhouette)",
            font=(self.font_family, 7),
            fg=PALETTE["text_muted"],
            bg=PALETTE["status_ok_bg"]
        )
        lbl_ipc_detail.pack(anchor="w")

        # =========================================================================
        # 2. MAIN CONTENT AREA (Right Side)
        # =========================================================================
        self.main_content = tk.Frame(master_box, bg=PALETTE["bg_window"], padx=26, pady=20)
        self.main_content.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # 2.1 Top Tab Navigation Strip (Rounded Gray Selection Cards)
        tab_strip = tk.Frame(self.main_content, bg=PALETTE["bg_window"])
        tab_strip.pack(fill=tk.X, pady=(0, 16))

        w_vid, w_cal, h_tab = 224, 146, 42

        # Tab 1: Video Config Card (Gear Icon)
        self.card_tab_video = tk.Canvas(
            tab_strip, width=w_vid, height=h_tab, bg=PALETTE["bg_window"],
            highlightthickness=0, cursor="hand2"
        )
        self.card_tab_video.pack(side=tk.LEFT, padx=(0, 10))
        self.card_tab_vid_bg = self.card_tab_video.create_image(0, 0, anchor="nw", image=self.pill_tab_vid_act)
        self.card_tab_vid_icon = self.card_tab_video.create_image(22, 21, anchor="center", image=self.icon_gear_act)
        self.card_tab_vid_txt = self.card_tab_video.create_text(
            42, 21, text="Video Settings", anchor="w",
            fill="#0F172A", font=(self.font_family, 9, "bold")
        )

        def on_tab_video_click(e=None):
            self._switch_tab("video")

        def on_tab_video_enter(e=None):
            if self.active_tab != "video" and self.pill_tab_vid_hover:
                self.card_tab_video.itemconfig(self.card_tab_vid_bg, image=self.pill_tab_vid_hover)

        def on_tab_video_leave(e=None):
            if self.active_tab != "video" and self.pill_tab_vid_inact:
                self.card_tab_video.itemconfig(self.card_tab_vid_bg, image=self.pill_tab_vid_inact)

        self.card_tab_video.bind("<Button-1>", on_tab_video_click)
        self.card_tab_video.tag_bind("all", "<Button-1>", on_tab_video_click)
        self.card_tab_video.bind("<Enter>", on_tab_video_enter)
        self.card_tab_video.bind("<Leave>", on_tab_video_leave)

        # Tab 2: Calibration Card (Sliders Icon)
        self.card_tab_calib = tk.Canvas(
            tab_strip, width=w_cal, height=h_tab, bg=PALETTE["bg_window"],
            highlightthickness=0, cursor="hand2"
        )
        self.card_tab_calib.pack(side=tk.LEFT)
        self.card_tab_cal_bg = self.card_tab_calib.create_image(0, 0, anchor="nw", image=self.pill_tab_cal_inact)
        self.card_tab_cal_icon = self.card_tab_calib.create_image(22, 21, anchor="center", image=self.icon_sliders_inact)
        self.card_tab_cal_txt = self.card_tab_calib.create_text(
            42, 21, text="Calibration", anchor="w",
            fill="#64748B", font=(self.font_family, 9, "bold")
        )

        def on_tab_calib_click(e=None):
            self._switch_tab("calib")

        def on_tab_calib_enter(e=None):
            if self.active_tab != "calib" and self.pill_tab_cal_hover:
                self.card_tab_calib.itemconfig(self.card_tab_cal_bg, image=self.pill_tab_cal_hover)

        def on_tab_calib_leave(e=None):
            if self.active_tab != "calib" and self.pill_tab_cal_inact:
                self.card_tab_calib.itemconfig(self.card_tab_cal_bg, image=self.pill_tab_cal_inact)

        self.card_tab_calib.bind("<Button-1>", on_tab_calib_click)
        self.card_tab_calib.tag_bind("all", "<Button-1>", on_tab_calib_click)
        self.card_tab_calib.bind("<Enter>", on_tab_calib_enter)
        self.card_tab_calib.bind("<Leave>", on_tab_calib_leave)

        # Full horizontal separator line under tab strip
        tk.Frame(self.main_content, height=1, bg=PALETTE["border_subtle"]).pack(fill=tk.X, pady=(0, 14))

        # 2.2 Content Container (Swapped dynamically between video and calib)
        self.view_container = tk.Frame(self.main_content, bg=PALETTE["bg_window"])
        self.view_container.pack(fill=tk.BOTH, expand=True)

        self._build_video_view()
        self._build_calib_view()

        # 2.3 Bottom Action Area (PlayStation Blue CTA & Footer)
        bottom_area = tk.Frame(self.main_content, bg=PALETTE["bg_window"])
        bottom_area.pack(fill=tk.X, pady=(10, 0))

        self.btn_start = tk.Button(
            bottom_area,
            text="START TRACKING",
            font=(self.font_family, 11, "bold"),
            bg=PALETTE["ps_blue"],
            fg="#ffffff",
            activebackground=PALETTE["ps_blue_hover"],
            activeforeground="#ffffff",
            relief="flat",
            bd=0,
            cursor="hand2",
            command=self._start_tracking
        )
        self.btn_start.pack(fill=tk.X, ipady=12)

        # Subtle Status Footer underneath button
        footer_row = tk.Frame(bottom_area, bg=PALETTE["bg_window"])
        footer_row.pack(fill=tk.X, pady=(6, 0))

        self.lbl_status = tk.Label(
            footer_row,
            text="Made by Edd <3",
            font=(self.font_family, 8),
            fg=PALETTE["text_muted"],
            bg=PALETTE["bg_window"]
        )
        self.lbl_status.pack(side=tk.LEFT)

        lbl_version = tk.Label(
            footer_row,
            text="Legacy PSCam Sensor v0.5",
            font=(self.font_family, 8),
            fg=PALETTE["text_dim"],
            bg=PALETTE["bg_window"]
        )
        lbl_version.pack(side=tk.RIGHT)

    def _build_video_view(self):
        """Constructs the view for 'Configuração de Vídeo'."""
        self.view_video = tk.Frame(self.view_container, bg=PALETTE["bg_window"])

        # ---------------------------------------------------------------------
        # Card A: PlayStation 4 Camera Status (Visible ONLY in 'pscam' mode)
        # ---------------------------------------------------------------------
        self.pscam_card = tk.Frame(self.view_video, bg=PALETTE["bg_card"],
                                   highlightbackground=PALETTE["border_subtle"], highlightthickness=1, padx=16, pady=14)

        lbl_ps_title = tk.Label(self.pscam_card, text="PlayStation®Camera integration (PSCam4Win)",
                                font=(self.font_family, 9, "bold"), fg=PALETTE["blue_dark"], bg=PALETTE["bg_card"])
        lbl_ps_title.pack(anchor="w")

        self.lbl_pscam_info = tk.Label(self.pscam_card, text="Checking driver and hardware...",
                                       font=(self.font_family, 8), fg=PALETTE["text_muted"], bg=PALETTE["bg_card"])
        self.lbl_pscam_info.pack(anchor="w", pady=(3, 10))

        # Launch Button & Spec Row
        ctrl_row = tk.Frame(self.pscam_card, bg=PALETTE["bg_card"])
        ctrl_row.pack(fill=tk.X, pady=(0, 10))

        self.btn_launch_pscam = tk.Button(
            ctrl_row, text="Start PSCam4Win Driver", font=(self.font_family, 8, "bold"),
            bg=PALETTE["ps_blue"], fg="#ffffff", activebackground=PALETTE["ps_blue_hover"],
            activeforeground="#ffffff", relief="flat", bd=0, cursor="hand2", padx=12, pady=6,
            command=self._launch_pscam_tray
        )
        self.btn_launch_pscam.pack(side=tk.LEFT)

        # Spec Badge inside PS Card
        spec_badge = tk.Frame(self.pscam_card, bg=PALETTE["blue_pastel"], padx=10, pady=8)
        spec_badge.pack(fill=tk.X)

        tk.Label(spec_badge, text="Optimized Auto Mode: 1280x800 @ 60 FPS (OV580 Stereo DirectShow)",
                 font=(self.font_family, 8, "bold"), fg=PALETTE["blue_dark"], bg=PALETTE["blue_pastel"]).pack(anchor="w")
        tk.Label(spec_badge,
                 text="Resolution picker is hidden in this tab because the PlayStation®Camera operates in the driver's native format.",
                 font=(self.font_family, 7), fg=PALETTE["text_muted"], bg=PALETTE["blue_pastel"]).pack(anchor="w")

        # ---------------------------------------------------------------------
        # Card B: Standard Webcam Picker (Visible ONLY in 'webcam' mode)
        # ---------------------------------------------------------------------
        self.webcam_card = tk.Frame(self.view_video, bg=PALETTE["bg_card"],
                                    highlightbackground=PALETTE["border_subtle"], highlightthickness=1, padx=16, pady=14)

        lbl_web_title = tk.Label(self.webcam_card, text="WEBCAM VIDEO SETTINGS",
                                 font=(self.font_family, 9, "bold"), fg=PALETTE["blue_dark"], bg=PALETTE["bg_card"])
        lbl_web_title.pack(anchor="w", pady=(0, 10))

        # Device selection row
        dev_row = tk.Frame(self.webcam_card, bg=PALETTE["bg_card"])
        dev_row.pack(fill=tk.X, pady=(0, 8))

        tk.Label(dev_row, text="Device:", font=(self.font_family, 8, "bold"),
                 fg=PALETTE["text_main"], bg=PALETTE["bg_card"], width=14, anchor="w").pack(side=tk.LEFT)

        self.cb_cameras = ttk.Combobox(dev_row, state="readonly", style="Modern.TCombobox")
        self.cb_cameras.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self.cb_cameras.bind("<<ComboboxSelected>>", self._on_camera_selected)

        btn_refresh = tk.Button(
            dev_row, text="↻", font=(self.font_family, 9, "bold"), width=3,
            bg=PALETTE["blue_pastel"], fg=PALETTE["blue_dark"],
            activebackground=PALETTE["blue_pastel_hover"], activeforeground=PALETTE["blue_dark"],
            relief="flat", bd=0, cursor="hand2", command=self._refresh_cameras
        )
        btn_refresh.pack(side=tk.RIGHT)

        # Preset selection row
        preset_row = tk.Frame(self.webcam_card, bg=PALETTE["bg_card"])
        preset_row.pack(fill=tk.X, pady=(0, 6))

        tk.Label(preset_row, text="Resolution / FPS:", font=(self.font_family, 8, "bold"),
                 fg=PALETTE["text_main"], bg=PALETTE["bg_card"], width=14, anchor="w").pack(side=tk.LEFT)

        self.cb_preset = ttk.Combobox(preset_row, state="readonly", style="Modern.TCombobox")
        self.cb_preset.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # ---------------------------------------------------------------------
        # Card C: Shared Display Preferences (Mirroring & HUD)
        # ---------------------------------------------------------------------
        self.display_card = tk.Frame(self.view_video, bg=PALETTE["bg_card"],
                                     highlightbackground=PALETTE["border_subtle"], highlightthickness=1, padx=16, pady=12)
        self.display_card.pack(fill=tk.X, pady=(10, 0))

        tk.Label(self.display_card, text="ADDITIONAL DISPLAY OPTIONS",
                 font=(self.font_family, 9, "bold"), fg=PALETTE["blue_dark"], bg=PALETTE["bg_card"]).pack(anchor="w", pady=(0, 6))

        self.var_mirror = tk.BooleanVar(value=self.cfg.get("mirror_horizontal", True))
        # Ocultado temporariamente da interface a pedido do usuário (preservado internamente como ativo)
        self.chk_mirror = ttk.Checkbutton(
            self.display_card,
            text="Mirror Image Horizontally (Dance Mirror Mode)",
            variable=self.var_mirror,
            style="Modern.TCheckbutton"
        )
        # self.chk_mirror.pack(anchor="w", pady=(2, 4))  # Oculto na UI por enquanto

        self.var_hud = tk.BooleanVar(value=self.cfg.get("show_hud", True))
        chk_hud = ttk.Checkbutton(
            self.display_card,
            text="Display HUD Overlay in Tracking Window (FPS, IPC & Shortcuts)",
            variable=self.var_hud,
            style="Modern.TCheckbutton"
        )
        chk_hud.pack(anchor="w", pady=(0, 4))

        self.var_face_follow = tk.BooleanVar(value=self.cfg.get("face_follow_enabled", True))
        chk_face = ttk.Checkbutton(
            self.display_card,
            text="[EXPERIMENTAL] Auto-Frame player's face in Just Dance",
            variable=self.var_face_follow,
            style="Modern.TCheckbutton"
        )
        chk_face.pack(anchor="w")

    def _build_calib_view(self):
        """Constructs the view for 'Calibração' with simplified game-style preset cards."""
        self.view_calib = tk.Frame(self.view_container, bg=PALETTE["bg_window"])

        calib_wrapper = tk.Frame(
            self.view_calib, bg=PALETTE["bg_card"],
            highlightbackground=PALETTE["border_subtle"], highlightthickness=1,
            padx=16, pady=14
        )
        calib_wrapper.pack(fill=tk.BOTH, expand=True)

        # 1. Header
        lbl_head = tk.Label(
            calib_wrapper,
            text="TRACKING & MOTION PROFILE",
            font=(self.font_family, 9, "bold"),
            fg=PALETTE["blue_dark"],
            bg=PALETTE["bg_card"]
        )
        lbl_head.pack(anchor="w")

        lbl_sub = tk.Label(
            calib_wrapper,
            text="Select the profile that best fits your playstyle and camera setup.",
            font=(self.font_family, 8),
            fg=PALETTE["text_muted"],
            bg=PALETTE["bg_card"]
        )
        lbl_sub.pack(anchor="w", pady=(2, 12))

        # 2. Preset Cards Container (Row with 3 side-by-side cards)
        presets_row = tk.Frame(calib_wrapper, bg=PALETTE["bg_card"])
        presets_row.pack(fill=tk.X, pady=(0, 10))

        self.calib_card_widgets = {}

        for i, (pid, pdata) in enumerate(CALIB_PRESETS.items()):
            card_frame = tk.Frame(
                presets_row,
                bg=PALETTE["bg_card"],
                highlightbackground=PALETTE["border_subtle"],
                highlightthickness=2,
                padx=12,
                pady=10,
                cursor="hand2"
            )
            card_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8 if i < len(CALIB_PRESETS) - 1 else 0))

            hdr_row = tk.Frame(card_frame, bg=PALETTE["bg_card"])
            hdr_row.pack(fill=tk.X)

            lbl_title = tk.Label(
                hdr_row,
                text=f"{pdata['icon']} {pdata['title']}",
                font=(self.font_family, 9, "bold"),
                fg=PALETTE["text_main"],
                bg=PALETTE["bg_card"]
            )
            lbl_title.pack(side=tk.LEFT)

            lbl_tag = tk.Label(
                hdr_row,
                text=pdata["tag"],
                font=(self.font_family, 6, "bold"),
                fg=PALETTE["text_muted"],
                bg=PALETTE["input_bg"],
                padx=4,
                pady=2
            )
            lbl_tag.pack(side=tk.RIGHT)

            lbl_sub_p = tk.Label(
                card_frame,
                text=pdata["subtitle"],
                font=(self.font_family, 7, "bold"),
                fg=PALETTE["blue_dark"],
                bg=PALETTE["bg_card"]
            )
            lbl_sub_p.pack(anchor="w", pady=(4, 2))

            lbl_desc = tk.Label(
                card_frame,
                text=pdata["desc"],
                font=(self.font_family, 7),
                fg=PALETTE["text_muted"],
                bg=PALETTE["bg_card"],
                wraplength=170,
                justify="left"
            )
            lbl_desc.pack(anchor="w", pady=(0, 6))

            bot_row = tk.Frame(card_frame, bg=PALETTE["bg_card"])
            bot_row.pack(fill=tk.X, side=tk.BOTTOM, pady=(4, 0))

            lbl_specs = tk.Label(
                bot_row,
                text=pdata["specs"],
                font=(self.font_family, 6),
                fg=PALETTE["text_dim"],
                bg=PALETTE["bg_card"]
            )
            lbl_specs.pack(side=tk.LEFT)

            lbl_ind = tk.Label(
                bot_row,
                text="○ Select",
                font=(self.font_family, 7, "bold"),
                fg=PALETTE["text_dim"],
                bg=PALETTE["bg_card"]
            )
            lbl_ind.pack(side=tk.RIGHT)

            widgets_dict = {
                "frame": card_frame,
                "hdr_row": hdr_row,
                "bot_row": bot_row,
                "title": lbl_title,
                "tag": lbl_tag,
                "sub": lbl_sub_p,
                "desc": lbl_desc,
                "specs": lbl_specs,
                "ind": lbl_ind,
            }
            self.calib_card_widgets[pid] = widgets_dict

            def make_handler(target_pid):
                return lambda e=None: self._select_calib_preset(target_pid)

            def make_enter_handler(target_pid):
                return lambda e=None: self._on_calib_card_hover(target_pid, True)

            def make_leave_handler(target_pid):
                return lambda e=None: self._on_calib_card_hover(target_pid, False)

            click_cb = make_handler(pid)
            enter_cb = make_enter_handler(pid)
            leave_cb = make_leave_handler(pid)

            for w in (card_frame, hdr_row, bot_row, lbl_title, lbl_tag, lbl_sub_p, lbl_desc, lbl_specs, lbl_ind):
                w.bind("<Button-1>", click_cb)
                w.bind("<Enter>", enter_cb)
                w.bind("<Leave>", leave_cb)

        # 3. Auto-Height Callout Card (Explains automatic normalization)
        auto_height_box = tk.Frame(
            calib_wrapper,
            bg=PALETTE["input_bg"],
            highlightbackground=PALETTE["border_subtle"],
            highlightthickness=1,
            padx=12,
            pady=8
        )
        auto_height_box.pack(fill=tk.X, pady=(0, 10))

        h_icon_col = tk.Label(
            auto_height_box,
            text="📏",
            font=(self.font_family, 12),
            bg=PALETTE["input_bg"]
        )
        h_icon_col.pack(side=tk.LEFT, padx=(0, 10))

        h_text_col = tk.Frame(auto_height_box, bg=PALETTE["input_bg"])
        h_text_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        lbl_auto_h_title = tk.Label(
            h_text_col,
            text="Automatic Height Calibration (1.75m default)",
            font=(self.font_family, 8, "bold"),
            fg=PALETTE["blue_dark"],
            bg=PALETTE["input_bg"]
        )
        lbl_auto_h_title.pack(anchor="w")

        lbl_auto_h_desc = tk.Label(
            h_text_col,
            text="The sensor dynamically normalizes body proportions to the Just Dance Kinect v1 metric convention. No manual adjustment needed.",
            font=(self.font_family, 7),
            fg=PALETTE["text_muted"],
            bg=PALETTE["input_bg"]
        )
        lbl_auto_h_desc.pack(anchor="w")

        # 4. Collapsible Advanced Settings (Sliders EMA and Confidence)
        self.btn_toggle_adv = tk.Button(
            calib_wrapper,
            text="Show Advanced Filter Settings ▼",
            font=(self.font_family, 8, "bold"),
            bg=PALETTE["blue_pastel"],
            fg=PALETTE["blue_dark"],
            activebackground=PALETTE["blue_pastel_hover"],
            activeforeground=PALETTE["blue_dark"],
            relief="flat",
            bd=0,
            cursor="hand2",
            padx=10,
            pady=6,
            command=self._toggle_advanced_calib
        )
        self.btn_toggle_adv.pack(fill=tk.X)

        self.adv_calib_box = tk.Frame(
            calib_wrapper,
            bg=PALETTE["bg_card"],
            highlightbackground=PALETTE["border_subtle"],
            highlightthickness=1,
            padx=14,
            pady=10
        )
        # adv_calib_box starts collapsed

        # 4.1 Smoothing Slider
        self.lbl_smooth = tk.Label(
            self.adv_calib_box, text="", font=(self.font_family, 8, "bold"),
            fg=PALETTE["text_main"], bg=PALETTE["bg_card"]
        )
        self.lbl_smooth.pack(anchor="w")

        self.scale_smooth = ttk.Scale(
            self.adv_calib_box, from_=0.20, to=0.85, value=self.cfg.get("smoothing_alpha", 0.55),
            style="Modern.Horizontal.TScale", command=self._on_smooth_changed
        )
        self.scale_smooth.pack(fill=tk.X, pady=(2, 4))
        self._update_smooth_label(self.scale_smooth.get())

        tk.Label(
            self.adv_calib_box,
            text="EMA Filter: lower values reduce jitter; higher values provide instantaneous response.",
            font=(self.font_family, 7), fg=PALETTE["text_muted"], bg=PALETTE["bg_card"]
        ).pack(anchor="w", pady=(0, 8))

        # 4.2 Confidence Slider
        self.lbl_conf = tk.Label(
            self.adv_calib_box, text="", font=(self.font_family, 8, "bold"),
            fg=PALETTE["text_main"], bg=PALETTE["bg_card"]
        )
        self.lbl_conf.pack(anchor="w")

        self.scale_conf = ttk.Scale(
            self.adv_calib_box, from_=0.30, to=0.80, value=self.cfg.get("detection_confidence", 0.50),
            style="Modern.Horizontal.TScale", command=self._on_conf_changed
        )
        self.scale_conf.pack(fill=tk.X, pady=(2, 4))
        self._update_conf_label(self.scale_conf.get())

        tk.Label(
            self.adv_calib_box,
            text="Minimum confidence threshold accepted by the MediaPipe Pose neural network.",
            font=(self.font_family, 7), fg=PALETTE["text_muted"], bg=PALETTE["bg_card"]
        ).pack(anchor="w", pady=(0, 10))

        # Advanced action row (Reset button + Custom mode badge)
        adv_actions = tk.Frame(self.adv_calib_box, bg=PALETTE["bg_card"])
        adv_actions.pack(fill=tk.X)

        btn_reset = tk.Button(
            adv_actions,
            text="↺ Reset to Recommended Profile (Balanced)",
            font=(self.font_family, 8, "bold"),
            bg=PALETTE["blue_pastel"],
            fg=PALETTE["blue_dark"],
            activebackground=PALETTE["blue_pastel_hover"],
            activeforeground=PALETTE["blue_dark"],
            relief="flat",
            bd=0,
            cursor="hand2",
            padx=10,
            pady=5,
            command=self._reset_calib_defaults
        )
        btn_reset.pack(side=tk.LEFT)

        self.lbl_calib_mode_badge = tk.Label(
            adv_actions,
            text="",
            font=(self.font_family, 7, "bold"),
            fg=PALETTE["text_muted"],
            bg=PALETTE["bg_card"]
        )
        self.lbl_calib_mode_badge.pack(side=tk.RIGHT)

        # Reflect current configuration in the UI
        self._update_calib_preset_cards()

    def _switch_tab(self, tab_id):
        """Switches between 'video' and 'calib' tabs."""
        self.active_tab = tab_id
        if tab_id == "video":
            # Video tab active (sleek modern gray selection pill, dark icon, dark bold text)
            if hasattr(self, 'pill_tab_vid_act') and self.pill_tab_vid_act:
                self.card_tab_video.itemconfig(self.card_tab_vid_bg, image=self.pill_tab_vid_act)
            if hasattr(self, 'icon_gear_act') and self.icon_gear_act:
                self.card_tab_video.itemconfig(self.card_tab_vid_icon, image=self.icon_gear_act)
            self.card_tab_video.itemconfig(self.card_tab_vid_txt, fill="#0F172A")

            # Calib tab inactive (subtle white/outline pill, muted icon, muted text)
            if hasattr(self, 'pill_tab_cal_inact') and self.pill_tab_cal_inact:
                self.card_tab_calib.itemconfig(self.card_tab_cal_bg, image=self.pill_tab_cal_inact)
            if hasattr(self, 'icon_sliders_inact') and self.icon_sliders_inact:
                self.card_tab_calib.itemconfig(self.card_tab_cal_icon, image=self.icon_sliders_inact)
            self.card_tab_calib.itemconfig(self.card_tab_cal_txt, fill="#64748B")

            self.view_calib.pack_forget()
            self.view_video.pack(fill=tk.BOTH, expand=True)
            self._update_video_view_visibility()
        else:
            # Video tab inactive
            if hasattr(self, 'pill_tab_vid_inact') and self.pill_tab_vid_inact:
                self.card_tab_video.itemconfig(self.card_tab_vid_bg, image=self.pill_tab_vid_inact)
            if hasattr(self, 'icon_gear_inact') and self.icon_gear_inact:
                self.card_tab_video.itemconfig(self.card_tab_vid_icon, image=self.icon_gear_inact)
            self.card_tab_video.itemconfig(self.card_tab_vid_txt, fill="#64748B")

            # Calib tab active (sleek modern gray selection pill, dark icon, dark bold text)
            if hasattr(self, 'pill_tab_cal_act') and self.pill_tab_cal_act:
                self.card_tab_calib.itemconfig(self.card_tab_cal_bg, image=self.pill_tab_cal_act)
            if hasattr(self, 'icon_sliders_act') and self.icon_sliders_act:
                self.card_tab_calib.itemconfig(self.card_tab_cal_icon, image=self.icon_sliders_act)
            self.card_tab_calib.itemconfig(self.card_tab_cal_txt, fill="#0F172A")

            self.view_video.pack_forget()
            self.view_calib.pack(fill=tk.BOTH, expand=True)

    def _update_video_view_visibility(self):
        """
        In 'pscam' mode: Shows pscam_card, HIDES webcam_card (resolution & camera options).
        In 'webcam' mode: Shows webcam_card, HIDES pscam_card.
        """
        mode = self.cfg.get("camera_mode", "pscam")
        if mode == "pscam":
            self.webcam_card.pack_forget()
            if not self.pscam_card.winfo_ismapped():
                self.pscam_card.pack(fill=tk.X, before=self.display_card)
        else:
            self.pscam_card.pack_forget()
            if not self.webcam_card.winfo_ismapped():
                self.webcam_card.pack(fill=tk.X, before=self.display_card)

    def _set_mode(self, mode):
        self.cfg["camera_mode"] = mode
        self._update_sidebar_buttons()
        self._refresh_presets()
        self._update_camera_dropdown_for_mode()
        self._update_pscam_status()
        self._update_video_view_visibility()
        self._save_current_settings()

    def _update_sidebar_buttons(self):
        mode = self.cfg.get("camera_mode", "pscam")
        if mode == "pscam":
            # PS Camera card is active (PlayStation Blue rounded pill)
            if self.pill_active:
                self.card_pscam.itemconfig(self.card_pscam_bg, image=self.pill_active)
            if self.icon_ps_act:
                self.card_pscam.itemconfig(self.card_pscam_icon, image=self.icon_ps_act)
            self.card_pscam.itemconfig(self.card_pscam_title, fill=PALETTE["text_white"])
            self.card_pscam.itemconfig(self.card_pscam_sub, fill=PALETTE["blue_pastel"])

            # Webcam card is inactive
            if self.pill_inactive:
                self.card_webcam.itemconfig(self.card_webcam_bg, image=self.pill_inactive)
            if self.icon_web_inact:
                self.card_webcam.itemconfig(self.card_webcam_icon, image=self.icon_web_inact)
            self.card_webcam.itemconfig(self.card_webcam_title, fill=PALETTE["text_main"])
            self.card_webcam.itemconfig(self.card_webcam_sub, fill=PALETTE["text_muted"])
        else:
            # PS Camera card is inactive
            if self.pill_inactive:
                self.card_pscam.itemconfig(self.card_pscam_bg, image=self.pill_inactive)
            if self.icon_ps_inact:
                self.card_pscam.itemconfig(self.card_pscam_icon, image=self.icon_ps_inact)
            self.card_pscam.itemconfig(self.card_pscam_title, fill=PALETTE["text_main"])
            self.card_pscam.itemconfig(self.card_pscam_sub, fill=PALETTE["text_muted"])

            # Webcam card is active (PlayStation Blue rounded pill)
            if self.pill_active:
                self.card_webcam.itemconfig(self.card_webcam_bg, image=self.pill_active)
            if self.icon_web_act:
                self.card_webcam.itemconfig(self.card_webcam_icon, image=self.icon_web_act)
            self.card_webcam.itemconfig(self.card_webcam_title, fill=PALETTE["text_white"])
            self.card_webcam.itemconfig(self.card_webcam_sub, fill=PALETTE["blue_pastel"])

    def _refresh_presets(self):
        mode = self.cfg.get("camera_mode", "pscam")
        if mode == "pscam":
            presets = PRESETS_PSCAM
            current = self.cfg.get("pscam_preset", presets[0])
        else:
            presets = PRESETS_WEBCAM
            current = self.cfg.get("webcam_preset", presets[0])

        self.cb_preset["values"] = presets
        if current in presets:
            self.cb_preset.set(current)
        else:
            self.cb_preset.set(presets[0])

    def _update_camera_dropdown_for_mode(self):
        mode = self.cfg.get("camera_mode", "pscam")
        cams = getattr(self, 'camera_list', [])

        if getattr(self, '_is_refreshing_cams', False) and not cams:
            msg = "Searching for PlayStation®Camera..." if mode == "pscam" else "Searching for webcams..."
            self.cb_cameras["values"] = [msg]
            self.cb_cameras.set(msg)
            return

        if mode == "pscam":
            ps_cams = [c for c in cams if c.is_pscam]
            if ps_cams:
                values = [str(c) for c in ps_cams]
                self.cb_cameras["values"] = values
                current_idx = self.cfg.get("camera_index", -1)
                selected = ps_cams[0]
                for c in ps_cams:
                    if c.index == current_idx:
                        selected = c
                        break
                self.cb_cameras.set(str(selected))
                self.cfg["camera_index"] = selected.index
            else:
                self.cb_cameras["values"] = ["PS Camera not connected"]
                self.cb_cameras.set("PS Camera not connected")
                self.cfg["camera_index"] = -1
        else:
            webcams = [c for c in cams if not c.is_pscam]
            if not webcams:
                webcams = cams
            if webcams:
                values = [str(c) for c in webcams]
                self.cb_cameras["values"] = values
                current_idx = self.cfg.get("camera_index", 0)
                selected = webcams[0]
                for c in webcams:
                    if c.index == current_idx:
                        selected = c
                        break
                self.cb_cameras.set(str(selected))
                self.cfg["camera_index"] = selected.index
            else:
                self.cb_cameras["values"] = ["No webcam found"]
                self.cb_cameras.set("No webcam found")
                self.cfg["camera_index"] = -1

    def _update_pscam_status(self):
        info = CameraManager.get_ps4_camera_state()
        self._apply_pscam_state(info)

    def _apply_pscam_state(self, ps4_info: dict):
        state = ps4_info.get("state", "DISCONNECTED")
        running = ps4_info.get("running", False)
        vcam_count = ps4_info.get("vcam_count", 0)

        if state == "NOT_INSTALLED":
            self.lbl_pscam_info.configure(
                text="PSCam4Win not detected in C:\\Program Files\\PSCam4Win.",
                fg=PALETTE["status_err"]
            )
            self.btn_launch_pscam.configure(
                state="disabled", text="Driver Not Installed",
                bg=PALETTE["input_bg"], fg=PALETTE["text_muted"]
            )
        elif state == "DISCONNECTED":
            self.lbl_pscam_info.configure(
                text="PlayStation®Camera disconnected from USB port.",
                fg=PALETTE["status_warn"]
            )
            if running:
                self.btn_launch_pscam.configure(
                    state="disabled", text="PSCam4Win Driver Active",
                    bg=PALETTE["blue_pastel"], fg=PALETTE["blue_dark"]
                )
            else:
                self.btn_launch_pscam.configure(
                    state="normal", text="Start PSCam4Win Driver",
                    bg=PALETTE["ps_blue"], fg="#ffffff"
                )
        elif state == "DRIVER_STOPPED":
            self.lbl_pscam_info.configure(
                text="PlayStation®Camera connected, but PSCam4Win driver is NOT running!",
                fg=PALETTE["status_warn"]
            )
            self.btn_launch_pscam.configure(
                state="normal", text="Start PSCam4Win Driver",
                bg=PALETTE["ps_blue"], fg="#ffffff"
            )
        elif state == "BOOTLOADER_UPLOADING":
            self.lbl_pscam_info.configure(
                text="PlayStation®Camera detected! PSCam4Win uploading USB firmware...",
                fg=PALETTE["ps_blue"]
            )
            self.btn_launch_pscam.configure(
                state="disabled", text="Uploading Firmware...",
                bg=PALETTE["blue_pastel"], fg=PALETTE["blue_dark"]
            )
        elif state == "WAITING_VCAM":
            self.lbl_pscam_info.configure(
                text="Hardware ready! Initializing DirectShow virtual camera (60 FPS)...",
                fg=PALETTE["ps_blue"]
            )
            self.btn_launch_pscam.configure(
                state="disabled", text="PSCam4Win Driver Active",
                bg=PALETTE["blue_pastel"], fg=PALETTE["blue_dark"]
            )
        elif state == "READY":
            cams = getattr(self, "camera_list", [])
            ps_cams = [c for c in cams if c.is_pscam]
            if ps_cams:
                cam_idx = ps_cams[0].index
                txt = f"Driver active and PlayStation®Camera connected (Index {cam_idx} • 60 FPS)"
            else:
                txt = f"Driver active and PlayStation®Camera connected ({vcam_count} virtual camera(s) active • 60 FPS)"
            self.lbl_pscam_info.configure(text=txt, fg=PALETTE["status_ok"])
            self.btn_launch_pscam.configure(
                state="disabled", text="PSCam4Win Driver Active",
                bg=PALETTE["blue_pastel"], fg=PALETTE["blue_dark"]
            )

    def _schedule_periodic_check(self):
        try:
            self._periodic_check()
        except Exception:
            pass
        self.root.after(1000, self._schedule_periodic_check)

    def _periodic_check(self):
        if self.is_tracking_active:
            return

        # 1. State machine quick evaluation (< 3ms)
        ps4_info = CameraManager.get_ps4_camera_state()
        if self._last_pscam_state != ps4_info.get("state"):
            self._last_pscam_state = ps4_info.get("state")
            self._apply_pscam_state(ps4_info)

        # 2. Hardware snapshot quick check (< 3ms) for automatic hotplug
        current_snapshot = CameraManager.get_hardware_snapshot()
        if current_snapshot != self._last_hw_snapshot:
            self._last_hw_snapshot = current_snapshot
            self._refresh_cameras_async()

    def _launch_pscam_tray(self):
        ok, msg = CameraManager.launch_pscam_tray()
        if ok:
            messagebox.showinfo("PSCam4Win", msg)
            self._refresh_cameras_async()
        else:
            messagebox.showwarning("PSCam4Win", msg)

    def _refresh_cameras(self):
        self._refresh_cameras_async()

    def _refresh_cameras_async(self):
        if self._is_refreshing_cams:
            return
        self._is_refreshing_cams = True

        def worker():
            try:
                cams = CameraManager.enumerate_cameras()
            except Exception as e:
                print(f"[WARN] Failed during asynchronous camera enumeration: {e}")
                cams = []
            try:
                if self.root.winfo_exists():
                    self.root.after(0, lambda: self._on_cameras_refreshed(cams))
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _on_cameras_refreshed(self, cams):
        self._is_refreshing_cams = False
        self.camera_list = cams
        self._update_pscam_status()
        self._update_camera_dropdown_for_mode()

    def _on_camera_selected(self, event=None):
        sel = self.cb_cameras.get()
        for c in getattr(self, 'camera_list', []):
            if str(c) == sel:
                self.cfg["camera_index"] = c.index
                if c.is_pscam and self.cfg.get("camera_mode") != "pscam":
                    self._set_mode("pscam")
                elif not c.is_pscam and self.cfg.get("camera_mode") == "pscam":
                    self._set_mode("webcam")
                break

    def _on_calib_card_hover(self, pid, is_entering):
        if not hasattr(self, 'calib_card_widgets') or pid not in self.calib_card_widgets:
            return
        w = self.calib_card_widgets[pid]
        is_active = (self.current_calib_preset == pid)
        if not is_active:
            if is_entering:
                w["frame"].configure(highlightbackground=PALETTE["input_border"])
            else:
                w["frame"].configure(highlightbackground=PALETTE["border_subtle"])

    def _select_calib_preset(self, preset_id):
        if preset_id not in CALIB_PRESETS:
            return
        preset = CALIB_PRESETS[preset_id]
        self.current_calib_preset = preset_id
        self.cfg["tracking_preset"] = preset_id
        self.cfg["smoothing_alpha"] = preset["smoothing_alpha"]
        self.cfg["detection_confidence"] = preset["detection_confidence"]

        if hasattr(self, "scale_smooth"):
            self.scale_smooth.set(preset["smoothing_alpha"])
            self._update_smooth_label(preset["smoothing_alpha"])
        if hasattr(self, "scale_conf"):
            self.scale_conf.set(preset["detection_confidence"])
            self._update_conf_label(preset["detection_confidence"])

        self._update_calib_preset_cards()
        self._save_current_settings()

    def _update_calib_preset_cards(self):
        if not hasattr(self, 'calib_card_widgets'):
            return
        for pid, w in self.calib_card_widgets.items():
            is_active = (self.current_calib_preset == pid)
            if is_active:
                bg_c = PALETTE["ps_blue_tint"]
                w["frame"].configure(bg=bg_c, highlightbackground=PALETTE["ps_blue"], highlightthickness=2)
                w["hdr_row"].configure(bg=bg_c)
                w["bot_row"].configure(bg=bg_c)
                w["title"].configure(fg=PALETTE["ps_blue"], bg=bg_c)
                w["tag"].configure(fg="#ffffff", bg=PALETTE["ps_blue"])
                w["sub"].configure(fg=PALETTE["blue_dark"], bg=bg_c)
                w["desc"].configure(fg=PALETTE["text_main"], bg=bg_c)
                w["specs"].configure(fg=PALETTE["ps_blue"], bg=bg_c)
                w["ind"].configure(text="Active", fg=PALETTE["ps_blue"], bg=bg_c)
            else:
                bg_c = PALETTE["bg_card"]
                w["frame"].configure(bg=bg_c, highlightbackground=PALETTE["border_subtle"], highlightthickness=1)
                w["hdr_row"].configure(bg=bg_c)
                w["bot_row"].configure(bg=bg_c)
                w["title"].configure(fg=PALETTE["text_main"], bg=bg_c)
                w["tag"].configure(fg=PALETTE["text_muted"], bg=PALETTE["input_bg"])
                w["sub"].configure(fg=PALETTE["blue_dark"], bg=bg_c)
                w["desc"].configure(fg=PALETTE["text_muted"], bg=bg_c)
                w["specs"].configure(fg=PALETTE["text_dim"], bg=bg_c)
                w["ind"].configure(text="○ Select", fg=PALETTE["text_dim"], bg=bg_c)

        if hasattr(self, "lbl_calib_mode_badge"):
            if self.current_calib_preset == "custom":
                self.lbl_calib_mode_badge.configure(
                    text="● Custom / Manual Mode Active",
                    fg=PALETTE["status_warn"]
                )
            else:
                self.lbl_calib_mode_badge.configure(text="")

    def _toggle_advanced_calib(self):
        self.is_adv_calib_open = not self.is_adv_calib_open
        if self.is_adv_calib_open:
            self.btn_toggle_adv.configure(text="Hide Advanced Settings ▲")
            self.adv_calib_box.pack(fill=tk.X, pady=(8, 0))
        else:
            self.btn_toggle_adv.configure(text="Show Advanced Filter Settings ▼")
            self.adv_calib_box.pack_forget()

    def _check_if_custom_preset(self):
        cur_alpha = self.cfg.get("smoothing_alpha", 0.55)
        cur_conf = self.cfg.get("detection_confidence", 0.50)
        matched_id = None
        for pid, pdata in CALIB_PRESETS.items():
            if abs(pdata["smoothing_alpha"] - cur_alpha) < 0.01 and abs(pdata["detection_confidence"] - cur_conf) < 0.01:
                matched_id = pid
                break

        if matched_id:
            self.current_calib_preset = matched_id
            self.cfg["tracking_preset"] = matched_id
        else:
            self.current_calib_preset = "custom"
            self.cfg["tracking_preset"] = "custom"

        self._update_calib_preset_cards()
        self._save_current_settings()

    def _on_smooth_changed(self, val):
        alpha = float(val)
        self._update_smooth_label(alpha)
        self.cfg["smoothing_alpha"] = round(alpha, 2)
        self._check_if_custom_preset()

    def _update_smooth_label(self, alpha):
        desc = "High Smoothing" if alpha < 0.40 else "Balanced (Default)" if alpha <= 0.70 else "Fast Response"
        self.lbl_smooth.configure(text=f"Anti-Jitter Smoothing (EMA): {alpha:.2f}  ({desc})")

    def _on_conf_changed(self, val):
        conf = float(val)
        self._update_conf_label(conf)
        self.cfg["detection_confidence"] = round(conf, 2)
        self._check_if_custom_preset()

    def _update_conf_label(self, conf):
        self.lbl_conf.configure(text=f"Minimum Detection Confidence: {conf:.2f}")

    def _reset_calib_defaults(self):
        self._select_calib_preset("balanced")

    def _open_dll_folder(self):
        base_dir = Path(__file__).resolve().parent
        dll_candidates = [
            base_dir.parent / "Kinect for Legacy DLL",
            base_dir / "Kinect for Legacy DLL",
            base_dir.parent / "dll"
        ]
        dll_dir = next((d for d in dll_candidates if d.exists()), base_dir.parent / "Kinect for Legacy DLL")
        if dll_dir.exists():
            subprocess.Popen(f'explorer "{dll_dir}"')
        else:
            messagebox.showerror("Error", f"Directory not found: {dll_dir}")

    def _save_current_settings(self):
        self.cfg["mirror_horizontal"] = self.var_mirror.get()
        self.cfg["show_hud"] = self.var_hud.get()
        if hasattr(self, 'var_face_follow'):
            self.cfg["face_follow_enabled"] = self.var_face_follow.get()
        self.cfg["tracking_preset"] = getattr(self, "current_calib_preset", "balanced")
        mode = self.cfg.get("camera_mode", "pscam")
        if mode == "pscam":
            self.cfg["pscam_preset"] = self.cb_preset.get()
        else:
            self.cfg["webcam_preset"] = self.cb_preset.get()

        if hasattr(self, 'camera_list') and self.camera_list:
            sel = self.cb_cameras.get()
            for c in self.camera_list:
                if str(c) == sel:
                    self.cfg["camera_index"] = c.index
                    break

        self.cfg_mgr.save()

    def _start_tracking(self):
        if self.is_tracking_active:
            return

        mode = self.cfg.get("camera_mode", "pscam")

        # Strict validation: Do not fall back to standard webcam in PS Camera mode
        if mode == "pscam":
            if CameraManager.is_pscam_installed() and not CameraManager.is_pscam_running():
                ok, msg = CameraManager.launch_pscam_tray()
                if not ok:
                    messagebox.showerror("Driver Launch Error", msg)
                    return
                time.sleep(1.2)
                self._refresh_cameras()

            ps_cams = [c for c in getattr(self, 'camera_list', []) if c.is_pscam]
            cam_idx = self.cfg.get("camera_index", -1)
            is_valid_pscam = any(c.index == cam_idx and c.is_pscam for c in getattr(self, 'camera_list', []))

            if not ps_cams or not is_valid_pscam or cam_idx < 0:
                messagebox.showwarning(
                    "PlayStation®Camera Not Connected",
                    "PlayStation®Camera was not detected on this computer!\n\n"
                    "• Ensure the PS4 Camera USB 3.0 Adapter is connected.\n"
                    "• Verify that the PSCam4Win driver is running in the Windows system tray.\n"
                )
                return
        else:
            cam_idx = self.cfg.get("camera_index", -1)
            if cam_idx < 0 or not getattr(self, 'camera_list', []):
                messagebox.showwarning(
                    "No Camera Connected",
                    "No webcam was detected on this computer.\n\n"
                    "Please connect a camera before starting tracking."
                )
                return

        self._save_current_settings()

        self.is_tracking_active = True
        self.btn_start.configure(
            text="TRACKING IN PROGRESS...",
            bg=PALETTE["status_err"],
            state="disabled"
        )
        self.root.iconify()  # Minimize launcher during tracking session

        def tracking_worker():
            success = False
            err_msg = ""
            try:
                success = tracking_session.run_tracking_session(self.cfg)
            except Exception as e:
                err_msg = str(e)
            finally:
                self.root.after(0, lambda: self._on_tracking_finished(success, err_msg))

        t = threading.Thread(target=tracking_worker, daemon=True)
        t.start()

    def _on_tracking_finished(self, success=True, err_msg=""):
        self.is_tracking_active = False
        self.btn_start.configure(
            text="START TRACKING",
            bg=PALETTE["ps_blue"],
            state="normal"
        )
        self.root.deiconify()  # Restore launcher window
        self._refresh_cameras()

        if not success:
            detail = f"\n\nDetails: {err_msg}" if err_msg else ""
            messagebox.showerror(
                "Tracking Initialization Failed",
                f"Could not start tracking with the selected device.{detail}\n\n"
                "• Check if camera is connected to USB.\n"
                "• Verify that PSCam4Win driver is active.\n"
                "• Make sure no other application (OBS, Discord, etc.) is locking the camera."
            )

    def _on_close_window(self):
        if hasattr(self, 'bridge') and self.bridge is not None:
            self.bridge.close()
        self.root.destroy()

def main():
    root = tk.Tk()
    app = LegacySensorGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
