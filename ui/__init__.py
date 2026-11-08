"""
Legacy PSCam Sensor - User Interface Package.
Provides the modern PlayStation-themed Qt 6 interface (PySide6).
"""
import sys

from .theme import (
    PALETTE,
    CALIB_PRESETS,
    FONT_TITLE,
    FONT_HEADING,
    FONT_BODY,
    get_font_family,
    load_custom_fonts_qt,
    load_custom_fonts_win32,
)
from .icons import (
    make_pill_image,
    load_pscam_file_icon,
    generate_icons,
    generate_icons_pil,
    generate_tab_icons,
    generate_tab_icons_pil,
    generate_mode_icons,
    generate_mode_icons_pil,
    generate_status_icons,
    generate_status_icons_pil,
)

# PySide6 modern Qt 6 GUI
try:
    from .gui_qt import LegacySensorQtGUI
    HAS_QT = True
except ImportError:
    HAS_QT = False
    LegacySensorQtGUI = None

# Default GUI class alias
LegacySensorGUI = LegacySensorQtGUI


def launch_app() -> int:
    """
    Launches the primary graphical interface using PySide6 (Qt 6).
    """
    if not HAS_QT:
        print("[ERROR] PySide6 is not installed. Please install requirements: pip install -r requirements.txt")
        return 1

    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    window = LegacySensorQtGUI()
    window.show()
    return app.exec()


__all__ = [
    "LegacySensorGUI",
    "LegacySensorQtGUI",
    "HAS_QT",
    "launch_app",
    "PALETTE",
    "CALIB_PRESETS",
    "FONT_TITLE",
    "FONT_HEADING",
    "FONT_BODY",
    "get_font_family",
    "load_custom_fonts_qt",
    "load_custom_fonts_win32",
    "make_pill_image",
    "load_pscam_file_icon",
    "generate_icons",
    "generate_icons_pil",
    "generate_tab_icons",
    "generate_tab_icons_pil",
    "generate_mode_icons",
    "generate_mode_icons_pil",
    "generate_status_icons",
    "generate_status_icons_pil",
]
