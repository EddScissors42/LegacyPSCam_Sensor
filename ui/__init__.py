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
    generate_ds4_icons_pil,
    generate_tab_icons,
    generate_tab_icons_pil,
    generate_controller_tab_icon_pil,
    generate_mode_icons,
    generate_mode_icons_pil,
    generate_status_icons,
    generate_status_icons_pil,
)

# PySide6 modern Qt 6 GUI
try:
    from .gui_qt import LegacySensorQtGUI
    from .pages import UIPagesMixin
    from .widgets import (
        pil_to_qpixmap,
        SlidingStackedWidget,
        DeviceNavCard,
        CalibPresetCard,
    )
    HAS_QT = True
except ImportError:
    HAS_QT = False
    LegacySensorQtGUI = None
    UIPagesMixin = None
    pil_to_qpixmap = None
    SlidingStackedWidget = None
    DeviceNavCard = None
    CalibPresetCard = None

# Default GUI class alias
LegacySensorGUI = LegacySensorQtGUI


def launch_app(cli_overrides=None) -> int:
    """
    Launches the primary graphical interface using PySide6 (Qt 6).
    """
    if not HAS_QT:
        print("[ERROR] PySide6 is not installed. Please install requirements: pip install -r requirements.txt")
        return 1

    # Bind explicit Windows AppUserModelID before QApplication so the taskbar uses our custom icon & identity
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("LegacyPSCam")
        except Exception:
            pass

    from PySide6.QtWidgets import QApplication
    from PySide6 import QtGui
    from assets import ICON_APP_ICO_PATH, ICON_PSCAMERA_PATH
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("LegacyPSCam")
    app.setApplicationDisplayName("LegacyPSCam")
    app_icon_path = ICON_APP_ICO_PATH if (ICON_APP_ICO_PATH and ICON_APP_ICO_PATH.exists()) else ICON_PSCAMERA_PATH
    if app_icon_path and app_icon_path.exists():
        app.setWindowIcon(QtGui.QIcon(str(app_icon_path)))

    # Force a crisp-white & PlayStation light palette so OS dark mode never bleeds black into popup menus/comboboxes
    pal = QtGui.QPalette()
    pal.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColor("#F5F8FC"))
    pal.setColor(QtGui.QPalette.ColorRole.WindowText, QtGui.QColor("#0F172A"))
    pal.setColor(QtGui.QPalette.ColorRole.Base, QtGui.QColor("#FFFFFF"))
    pal.setColor(QtGui.QPalette.ColorRole.AlternateBase, QtGui.QColor("#F0F4FA"))
    pal.setColor(QtGui.QPalette.ColorRole.ToolTipBase, QtGui.QColor("#0F172A"))
    pal.setColor(QtGui.QPalette.ColorRole.ToolTipText, QtGui.QColor("#FFFFFF"))
    pal.setColor(QtGui.QPalette.ColorRole.Text, QtGui.QColor("#0F172A"))
    pal.setColor(QtGui.QPalette.ColorRole.Button, QtGui.QColor("#FFFFFF"))
    pal.setColor(QtGui.QPalette.ColorRole.ButtonText, QtGui.QColor("#0F172A"))
    pal.setColor(QtGui.QPalette.ColorRole.BrightText, QtGui.QColor("#00439C"))
    pal.setColor(QtGui.QPalette.ColorRole.Highlight, QtGui.QColor("#00439C"))
    pal.setColor(QtGui.QPalette.ColorRole.HighlightedText, QtGui.QColor("#FFFFFF"))
    pal.setColor(QtGui.QPalette.ColorGroup.Disabled, QtGui.QPalette.ColorRole.Text, QtGui.QColor("#94A3B8"))
    pal.setColor(QtGui.QPalette.ColorGroup.Disabled, QtGui.QPalette.ColorRole.ButtonText, QtGui.QColor("#94A3B8"))
    pal.setColor(QtGui.QPalette.ColorGroup.Disabled, QtGui.QPalette.ColorRole.WindowText, QtGui.QColor("#94A3B8"))
    app.setPalette(pal)

    window = LegacySensorQtGUI(cli_overrides=cli_overrides)
    window.show()

    # Dismiss PyInstaller native boot splash screen as soon as Qt window is painted
    try:
        import pyi_splash  # type: ignore[import-not-found]
        if pyi_splash.is_alive():
            pyi_splash.close()
    except Exception:
        pass

    return app.exec()


__all__ = [
    "LegacySensorGUI",
    "LegacySensorQtGUI",
    "UIPagesMixin",
    "pil_to_qpixmap",
    "SlidingStackedWidget",
    "DeviceNavCard",
    "CalibPresetCard",
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
    "generate_ds4_icons_pil",
    "generate_tab_icons",
    "generate_tab_icons_pil",
    "generate_controller_tab_icon_pil",
    "generate_mode_icons",
    "generate_mode_icons_pil",
    "generate_status_icons",
    "generate_status_icons_pil",
]
