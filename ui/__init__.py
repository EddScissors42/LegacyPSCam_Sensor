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
    from .benchmark_dialog import (
        TelemetryBenchmarkChart,
        TelemetryBenchmarkDialog,
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
    TelemetryBenchmarkChart = None
    TelemetryBenchmarkDialog = None

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
    from PySide6 import QtGui
    app = QApplication.instance() or QApplication(sys.argv)

    # Force a crisp-white & PlayStation light palette so OS dark mode never bleeds black into popup menus/comboboxes
    pal = QtGui.QPalette()
    pal.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColor("#F5F8FC"))
    pal.setColor(QtGui.QPalette.ColorRole.WindowText, QtGui.QColor("#0F172A"))
    pal.setColor(QtGui.QPalette.ColorRole.Base, QtGui.QColor("#FFFFFF"))
    pal.setColor(QtGui.QPalette.ColorRole.AlternateBase, QtGui.QColor("#F0F4FA"))
    pal.setColor(QtGui.QPalette.ColorRole.ToolTipBase, QtGui.QColor("#FFFFFF"))
    pal.setColor(QtGui.QPalette.ColorRole.ToolTipText, QtGui.QColor("#0F172A"))
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

    window = LegacySensorQtGUI()
    window.show()
    return app.exec()


__all__ = [
    "LegacySensorGUI",
    "LegacySensorQtGUI",
    "UIPagesMixin",
    "pil_to_qpixmap",
    "SlidingStackedWidget",
    "DeviceNavCard",
    "CalibPresetCard",
    "TelemetryBenchmarkChart",
    "TelemetryBenchmarkDialog",
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
