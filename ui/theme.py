"""
Theme Palette, Typography, and Calibration Presets for Legacy PSCam Sensor UI.
Features:
- Crisp White & PlayStation Blue (#00439C) aesthetic.
- Bundled Custom Typography:
  * 'Kanit' for the brand title ("Legacy PSCam Sensor")
  * 'National Park' for headings, tabs, card titles, and interactive controls
  * 'Inter Tight' for body text, descriptions, status messages, and metadata
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
FONTS_DIR = BASE_DIR / "assets" / "fonts"

FONT_TITLE = "Kanit"
FONT_HEADING = "National Park"
FONT_BODY = "Inter Tight"

# --- Modern PlayStation Blue & Crisp White Palette ---
PALETTE = {
    # Brand Accents — Official PlayStation Blue Theme
    "ps_blue": "#00439C",          # Iconic PlayStation dark blue
    "ps_blue_hover": "#00367A",    # Deeper blue hover state
    "ps_blue_active": "#00295C",   # Clicked / pressed state
    "ps_blue_tint": "#E8F0FE",     # Soft light blue tint
    "blue_pastel": "#DDF0F7",      # Soft baby blue secondary accent
    "blue_pastel_hover": "#CEEAF5",# Hover for blue elements
    "blue_dark": "#1D3557",        # Deep navy blue for headings & icons

    # Surfaces & Backgrounds (Crisp White Theme)
    "bg_window": "#F8F9FC",        # Near-white clean canvas
    "bg_sidebar": "#FFFFFF",       # Crisp white sidebar
    "bg_card": "#FFFFFF",          # Crisp white card surfaces
    "border_subtle": "#E2E8F0",    # Clean 1px structural borders
    "border_active": "#00439C",    # Active PlayStation blue border
    "input_bg": "#F1F5F9",         # Light field / balloon background
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
        "tag": "",
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
        "tag": "",
        "subtitle": "Maximum Filtering",
        "desc": "Intensive filtering against visual noise. Recommended for dimly lit rooms.",
        "smoothing_alpha": 0.35,
        "detection_confidence": 0.40,
        "specs": "EMA 0.35 • Conf 0.40",
    },
}


def load_custom_fonts_win32() -> None:
    """Registers bundled TTF fonts in Windows GDI process memory (no admin required)."""
    if os.name != "nt" or not FONTS_DIR.exists():
        return
    try:
        import ctypes
        for ttf_path in sorted(FONTS_DIR.glob("*.ttf")):
            ctypes.windll.gdi32.AddFontResourceExW(str(ttf_path.resolve()), 0x10, 0)
    except Exception:
        pass


def load_custom_fonts_qt() -> dict:
    """Registers bundled TTF fonts in Qt's QFontDatabase and returns resolved family names."""
    load_custom_fonts_win32()
    families = {
        "title": FONT_TITLE,
        "heading": FONT_HEADING,
        "body": FONT_BODY,
    }
    if not FONTS_DIR.exists():
        return families
    try:
        from PySide6.QtGui import QFontDatabase
        loaded = []
        for ttf_path in sorted(FONTS_DIR.glob("*.ttf")):
            fid = QFontDatabase.addApplicationFont(str(ttf_path.resolve()))
            if fid >= 0:
                loaded.extend(QFontDatabase.applicationFontFamilies(fid))
        for fam in loaded:
            low = fam.lower()
            if "kanit" in low:
                families["title"] = fam
            elif "national park" in low:
                families["heading"] = fam
            elif "inter tight" in low:
                families["body"] = fam
    except Exception:
        pass
    return families


def get_font_family() -> str:
    """Detects available modern sans-serif fonts for Tkinter."""
    load_custom_fonts_win32()
    try:
        import tkinter.font as tkfont
        families = [f.lower() for f in tkfont.families()]
        for pref in ("inter tight", "national park", "kanit", "montserrat", "poppins", "segoe ui", "helvetica", "arial"):
            for f in families:
                if pref in f:
                    if pref == "inter tight":
                        return "Inter Tight"
                    if pref == "national park":
                        return "National Park"
                    if pref == "kanit":
                        return "Kanit"
                    return "Segoe UI" if pref == "segoe ui" else pref.title()
    except Exception:
        pass
    return "Segoe UI"
