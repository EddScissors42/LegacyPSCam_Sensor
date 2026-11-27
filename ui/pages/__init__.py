"""
Declarative Qt 6 Page Builders package for Legacy PSCam Sensor UI.
Separates the layout construction of the 4 navigation pages into focused modules:
- video_page.py:        Page 0 — Video Settings (PS4 Camera, Webcam, Phone Camera, Display)
- tracking_page.py:     Page 1 — Tracking & Motion Profiles (1P/2P, Auto-Height, Advanced Drawer)
- experimental_page.py: Page 2 — Experimental Features (Auto-Frame PTZ & Virtual Phone)
- ds4_page.py:          Page 3 — DualShock 4 Controller Settings & Scoring Bridge
"""
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QWidget, QPushButton, QFrame, QScrollArea

from ui.theme import PALETTE
from ui.pages.video_page import UIVideoPageMixin
from ui.pages.tracking_page import UITrackingPageMixin
from ui.pages.experimental_page import UIExperimentalPageMixin
from ui.pages.ds4_page import UIDS4PageMixin


class UIPagesMixin(
    UIVideoPageMixin,
    UITrackingPageMixin,
    UIExperimentalPageMixin,
    UIDS4PageMixin,
):
    """
    Unified page-builder mixin for LegacySensorQtGUI.
    Keeps declarative widget trees decoupled from window event handlers and hardware threads.
    """

    def _create_scroll_page(self, page_widget: QWidget) -> QScrollArea:
        """Wraps a page widget into a clean, smooth, borderless scroll area."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.viewport().setStyleSheet("background: transparent; border: none;")
        scroll.setWidget(page_widget)
        return scroll

    def _create_reload_button(self, parent: QWidget, tooltip: str, on_click) -> QPushButton:
        """Creates a crisp, unclipped square icon button using assets/icons/reload.svg."""
        btn = QPushButton("", parent)
        btn.setFixedSize(34, 32)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip(tooltip)
        btn.setIcon(getattr(self, "icon_reload", QIcon()))
        btn.setIconSize(QSize(15, 15))
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {PALETTE["blue_pastel"]};
                color: {PALETTE["ps_blue"]};
                font-family: '{self.font_heading}', sans-serif;
                font-size: 13px;
                font-weight: bold;
                border: 1px solid #94A3B8;
                border-radius: 6px;
                padding: 0px;
            }}
            QPushButton:hover {{
                background-color: {PALETTE["blue_pastel_hover"]};
                border-color: {PALETTE["ps_blue"]};
            }}
            QPushButton:pressed {{
                background-color: #B8E2F2;
            }}
            QPushButton:disabled {{
                background-color: {PALETTE["input_bg"]};
                color: {PALETTE["text_muted"]};
                border-color: {PALETTE["border_subtle"]};
            }}
        """)
        btn.clicked.connect(on_click)
        return btn


__all__ = [
    "UIPagesMixin",
    "UIVideoPageMixin",
    "UITrackingPageMixin",
    "UIExperimentalPageMixin",
    "UIDS4PageMixin",
]
