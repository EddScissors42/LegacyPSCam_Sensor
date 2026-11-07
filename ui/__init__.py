"""
Legacy PSCam Sensor - Modern PlayStation-Themed Tkinter User Interface Package.
"""
from .gui import LegacySensorGUI
from .theme import PALETTE, CALIB_PRESETS, get_font_family
from .icons import make_pill_image, load_pscam_file_icon, generate_icons, generate_tab_icons

__all__ = [
    "LegacySensorGUI",
    "PALETTE",
    "CALIB_PRESETS",
    "get_font_family",
    "make_pill_image",
    "load_pscam_file_icon",
    "generate_icons",
    "generate_tab_icons",
]
