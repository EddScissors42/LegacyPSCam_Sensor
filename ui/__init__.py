"""
Legacy PSCam Sensor - User Interface Package.
Provides the modern PlayStation-themed Qt 6 interface (PySide6)
with fallback to Tkinter.
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

# Tkinter fallback GUI
from .gui import LegacySensorGUI as LegacySensorTkGUI

# PySide6 modern Qt 6 GUI
try:
    from .gui_qt import LegacySensorQtGUI
    HAS_QT = True
except ImportError:
    HAS_QT = False
    LegacySensorQtGUI = None

# Default GUI class alias
if HAS_QT:
    LegacySensorGUI = LegacySensorQtGUI
else:
    LegacySensorGUI = LegacySensorTkGUI


def launch_app(backend: str = "qt") -> int:
    """
    Launches the primary graphical interface.
    Defaults to the modern PlayStation-themed Qt 6 interface (PySide6),
    with automatic graceful fallback to Tkinter if Qt 6 is unavailable.
    """
    if backend == "qt" and HAS_QT:
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance() or QApplication(sys.argv)
            window = LegacySensorQtGUI()
            window.show()
            return app.exec()
        except Exception as e:
            print(f"[WARN] Failed to launch Qt6 GUI ({e}). Falling back to Tkinter...")

    # Fallback / explicit Tkinter mode
    import tkinter as tk
    root = tk.Tk()
    app = LegacySensorTkGUI(root)
    root.mainloop()
    return 0


__all__ = [
    "LegacySensorGUI",
    "LegacySensorQtGUI",
    "LegacySensorTkGUI",
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
