"""
Modern PlayStation-Themed Qt 6 User Interface for Legacy PSCam Sensor.
Features:
- Crisp White & Iconic PlayStation Blue (#00439C) aesthetic matching the original design.
- Custom Typography:
  * 'Kanit' for the brand title ("Legacy PSCam Sensor")
  * 'National Park' for headings, navigation tabs, card titles, and buttons
  * 'Inter Tight' for body text, status diagnostics, descriptions, and metadata
- High-resolution supersampled Pillow icons converted directly to QPixmap (PS4 Camera, Webcam, Gear, Sliders, and Status X/Check/Warn badges).
- Sliding navigation tabs with cubic easing transitions (60 FPS fluid animation).
- State-aware video panel: when disconnected, displays strictly the status balloon and action button.
"""
import os
import sys
import time
import threading
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Python 3.15 lazy-import normalization for concurrent.futures
try:
    import concurrent.futures
    import concurrent.futures.thread
    import concurrent.futures.process
    concurrent.futures.ThreadPoolExecutor = concurrent.futures.thread.ThreadPoolExecutor
    concurrent.futures.ProcessPoolExecutor = concurrent.futures.process.ProcessPoolExecutor
except Exception:
    pass

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve,
    QPoint, QSize, Signal, Slot, QParallelAnimationGroup
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QCheckBox, QStackedWidget,
    QFrame, QSlider, QMessageBox
)
from PySide6.QtGui import (
    QPixmap, QIcon, QImage
)

from ui.theme import (
    PALETTE, CALIB_PRESETS,
    FONT_TITLE, FONT_HEADING, FONT_BODY,
    load_custom_fonts_qt
)
from ui.icons import (
    generate_icons_pil,
    generate_tab_icons_pil,
    generate_mode_icons_pil,
    generate_status_icons_pil
)
from assets import ICON_PSCAMERA_PATH
from version import WINDOW_TITLE, VERSION_STRING, APP_NAME
from sensor.config_manager import ConfigManager, parse_preset, PRESETS_PSCAM, PRESETS_WEBCAM
from sensor.camera_manager import CameraManager
from sensor.kinect_shared_memory import KinectBridge
from sensor import tracking_session


def pil_to_qpixmap(pil_img, dpr: float = 4.0) -> QPixmap:
    """Converts a Pillow RGBA Image to a Qt QPixmap with explicit stride, deep copy, and High-DPI devicePixelRatio."""
    if pil_img is None:
        return QPixmap()
    img_rgba = pil_img.convert("RGBA")
    data = img_rgba.tobytes("raw", "RGBA")
    qimg = QImage(
        data,
        img_rgba.width,
        img_rgba.height,
        img_rgba.width * 4,
        QImage.Format.Format_RGBA8888
    ).copy()
    pm = QPixmap.fromImage(qimg)
    if dpr > 1.0:
        pm.setDevicePixelRatio(dpr)
    return pm


class SlidingStackedWidget(QStackedWidget):
    """
    QStackedWidget featuring hardware-friendly sliding animations between pages
    with cubic easing curves.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_animating = False

    def slide_to_index(self, index: int, duration: int = 240):
        if index == self.currentIndex() or self._is_animating or index < 0 or index >= self.count():
            return

        current_idx = self.currentIndex()
        next_widget = self.widget(index)
        current_widget = self.widget(current_idx)

        w = self.width()
        h = self.height()
        if w <= 0 or h <= 0:
            self.setCurrentIndex(index)
            return

        offset = w if index > current_idx else -w

        next_widget.setGeometry(offset, 0, w, h)
        next_widget.show()
        next_widget.raise_()

        self._is_animating = True

        anim_next = QPropertyAnimation(next_widget, b"pos", self)
        anim_next.setDuration(duration)
        anim_next.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim_next.setStartValue(QPoint(offset, 0))
        anim_next.setEndValue(QPoint(0, 0))

        anim_curr = QPropertyAnimation(current_widget, b"pos", self)
        anim_curr.setDuration(duration)
        anim_curr.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim_curr.setStartValue(QPoint(0, 0))
        anim_curr.setEndValue(QPoint(-offset, 0))

        self.anim_group = QParallelAnimationGroup(self)
        self.anim_group.addAnimation(anim_next)
        self.anim_group.addAnimation(anim_curr)

        def on_finished():
            self.setCurrentIndex(index)
            current_widget.hide()
            current_widget.move(0, 0)
            next_widget.move(0, 0)
            self._is_animating = False

        self.anim_group.finished.connect(on_finished)
        self.anim_group.start()


class DeviceNavCard(QFrame):
    """
    Interactive rounded navigation card for the sidebar (PlayStation Camera / Standard Webcam).
    Displays a crisp 38x26 icon on the left and two-line title/subtitle on the right.
    """
    clicked = Signal()

    def __init__(self, title: str, subtitle: str, font_heading: str, font_body: str, parent=None):
        super().__init__(parent)
        self.font_heading = font_heading
        self.font_body = font_body
        self._is_active = False
        self._pix_act = QPixmap()
        self._pix_inact = QPixmap()

        self.setFixedHeight(58)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        self.lbl_icon = QLabel(self)
        self.lbl_icon.setFixedSize(38, 26)
        self.lbl_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_icon.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(self.lbl_icon)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)

        self.lbl_title = QLabel(title, self)
        self.lbl_sub = QLabel(subtitle, self)
        text_col.addWidget(self.lbl_title)
        text_col.addWidget(self.lbl_sub)
        layout.addLayout(text_col, stretch=1)

    def set_icons(self, pix_act: QPixmap, pix_inact: QPixmap):
        self._pix_act = pix_act
        self._pix_inact = pix_inact
        self._refresh_visuals(hovered=False)

    def set_active(self, active: bool):
        self._is_active = active
        self._refresh_visuals(hovered=False)

    def _refresh_visuals(self, hovered: bool = False):
        if self._is_active:
            self.setStyleSheet(f"""
                DeviceNavCard {{
                    background-color: {PALETTE["ps_blue"]};
                    border: 1px solid {PALETTE["ps_blue"]};
                    border-radius: 12px;
                }}
            """)
            self.lbl_title.setStyleSheet(
                f"font-family: '{self.font_heading}'; font-size: 12px; font-weight: bold; color: {PALETTE['text_white']}; background: transparent; border: none;"
            )
            self.lbl_sub.setStyleSheet(
                f"font-family: '{self.font_body}'; font-size: 10px; color: {PALETTE['blue_pastel']}; background: transparent; border: none;"
            )
            if not self._pix_act.isNull():
                self.lbl_icon.setPixmap(self._pix_act)
        else:
            bg = "#F1F5F9" if hovered else "#F8FAFC"
            bdr = "#CBD5E1" if hovered else PALETTE["border_subtle"]
            self.setStyleSheet(f"""
                DeviceNavCard {{
                    background-color: {bg};
                    border: 1px solid {bdr};
                    border-radius: 12px;
                }}
            """)
            self.lbl_title.setStyleSheet(
                f"font-family: '{self.font_heading}'; font-size: 12px; font-weight: bold; color: {PALETTE['text_main']}; background: transparent; border: none;"
            )
            self.lbl_sub.setStyleSheet(
                f"font-family: '{self.font_body}'; font-size: 10px; color: {PALETTE['text_muted']}; background: transparent; border: none;"
            )
            if not self._pix_inact.isNull():
                self.lbl_icon.setPixmap(self._pix_inact)

    def enterEvent(self, event):
        if not self._is_active:
            self._refresh_visuals(hovered=True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self._is_active:
            self._refresh_visuals(hovered=False)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class CalibPresetCard(QFrame):
    """Interactive card for calibration presets (Balanced, Competitive, Ultra Stable)."""
    clicked = Signal(str)

    def __init__(
        self,
        preset_id: str,
        pdata: dict,
        font_heading: str,
        font_body: str,
        pix_act: QPixmap = None,
        pix_inact: QPixmap = None,
        parent=None
    ):
        super().__init__(parent)
        self.preset_id = preset_id
        self.pdata = pdata
        self.font_heading = font_heading
        self.font_body = font_body
        self.pix_act = pix_act or QPixmap()
        self.pix_inact = pix_inact or QPixmap()
        self._is_active = False

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(140)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(6)

        self.lbl_icon = QLabel(self)
        self.lbl_icon.setFixedSize(15, 15)
        self.lbl_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_icon.setStyleSheet("background: transparent; border: none;")

        self.lbl_title = QLabel(pdata["title"], self)
        tag_text = pdata.get("tag", "")
        self.lbl_tag = QLabel(tag_text, self)
        if not tag_text:
            self.lbl_tag.setVisible(False)

        top_row.addWidget(self.lbl_icon)
        top_row.addWidget(self.lbl_title)
        top_row.addStretch()
        top_row.addWidget(self.lbl_tag)
        layout.addLayout(top_row)

        self.lbl_sub = QLabel(pdata["subtitle"], self)
        layout.addWidget(self.lbl_sub)

        self.lbl_desc = QLabel(pdata["desc"], self)
        self.lbl_desc.setWordWrap(True)
        layout.addWidget(self.lbl_desc, stretch=1)

        bot_row = QHBoxLayout()
        bot_row.setContentsMargins(0, 2, 0, 0)
        self.lbl_specs = QLabel(pdata["specs"], self)
        bot_row.addWidget(self.lbl_specs)
        bot_row.addStretch()
        layout.addLayout(bot_row)

        self.set_active(False)

    def set_active(self, active: bool, hovered: bool = False):
        self._is_active = active
        if active:
            if not self.pix_act.isNull():
                self.lbl_icon.setPixmap(self.pix_act)
            bg = PALETTE["ps_blue_tint"]
            self.setStyleSheet(f"""
                CalibPresetCard {{
                    background-color: {bg};
                    border: 2px solid {PALETTE["ps_blue"]};
                    border-radius: 10px;
                }}
            """)
            self.lbl_title.setStyleSheet(
                f"font-family: '{self.font_heading}'; font-size: 12px; font-weight: bold; color: {PALETTE['ps_blue']}; background: transparent; border: none;"
            )
            self.lbl_tag.setStyleSheet(
                f"font-family: '{self.font_heading}'; font-size: 8px; font-weight: bold; color: #FFFFFF; background-color: {PALETTE['ps_blue']}; padding: 2px 6px; border-radius: 4px; border: none;"
            )
            self.lbl_sub.setStyleSheet(
                f"font-family: '{self.font_heading}'; font-size: 10px; font-weight: bold; color: {PALETTE['blue_dark']}; background: transparent; border: none;"
            )
            self.lbl_desc.setStyleSheet(
                f"font-family: '{self.font_body}'; font-size: 10px; color: {PALETTE['text_main']}; background: transparent; border: none;"
            )
            self.lbl_specs.setStyleSheet(
                f"font-family: '{self.font_body}'; font-size: 9px; color: {PALETTE['ps_blue']}; background: transparent; border: none;"
            )
        else:
            if not self.pix_inact.isNull():
                self.lbl_icon.setPixmap(self.pix_inact)
            bg = PALETTE["bg_card"]
            bdr = PALETTE["input_border"] if hovered else PALETTE["border_subtle"]
            self.setStyleSheet(f"""
                CalibPresetCard {{
                    background-color: {bg};
                    border: 1px solid {bdr};
                    border-radius: 10px;
                }}
            """)
            self.lbl_title.setStyleSheet(
                f"font-family: '{self.font_heading}'; font-size: 12px; font-weight: bold; color: {PALETTE['text_main']}; background: transparent; border: none;"
            )
            self.lbl_tag.setStyleSheet(
                f"font-family: '{self.font_heading}'; font-size: 8px; font-weight: bold; color: {PALETTE['text_muted']}; background-color: {PALETTE['input_bg']}; padding: 2px 6px; border-radius: 4px; border: none;"
            )
            self.lbl_sub.setStyleSheet(
                f"font-family: '{self.font_heading}'; font-size: 10px; font-weight: bold; color: {PALETTE['blue_dark']}; background: transparent; border: none;"
            )
            self.lbl_desc.setStyleSheet(
                f"font-family: '{self.font_body}'; font-size: 10px; color: {PALETTE['text_muted']}; background: transparent; border: none;"
            )
            self.lbl_specs.setStyleSheet(
                f"font-family: '{self.font_body}'; font-size: 9px; color: {PALETTE['text_dim']}; background: transparent; border: none;"
            )

    def enterEvent(self, event):
        if not self._is_active:
            self.set_active(False, hovered=True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self._is_active:
            self.set_active(False, hovered=False)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.preset_id)
        super().mousePressEvent(event)


class LegacySensorQtGUI(QMainWindow):
    """Modern Crisp-White & PlayStation Blue primary window in Qt 6."""
    cameras_refreshed_signal = Signal(list)
    tracking_finished_signal = Signal(bool, str)

    def __init__(self, parent=None, *args, auto_discover=True, **kwargs):
        if parent is not None and not isinstance(parent, QWidget):
            parent = None
        super().__init__(parent)
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(960, 580)
        self.setMinimumSize(920, 550)
        if ICON_PSCAMERA_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PSCAMERA_PATH)))

        # Register bundled custom fonts (Kanit, National Park, Inter Tight)
        loaded_fonts = load_custom_fonts_qt()
        self.font_title = loaded_fonts.get("title", FONT_TITLE)
        self.font_heading = loaded_fonts.get("heading", FONT_HEADING)
        self.font_body = loaded_fonts.get("body", FONT_BODY)

        # Initialize shared memory bridges immediately on startup so Just Dance connects seamlessly
        self.bridge = KinectBridge()

        self.cfg_mgr = ConfigManager()
        self.cfg = self.cfg_mgr.config
        self.is_tracking_active = False
        self._last_hw_snapshot = CameraManager.get_hardware_snapshot()
        self._last_pscam_state = None
        self._current_pscam_state = "DISCONNECTED"
        self._is_refreshing_cams = False
        self.camera_list = []
        self.active_tab = "video"
        self.current_calib_preset = self.cfg.get("tracking_preset", "balanced")
        self.is_adv_calib_open = False
        self._is_closing = False
        self.calib_cards = {}

        self._load_pixmaps()
        self._setup_style()
        self._build_ui()

        # Connect thread-safe Qt signals
        self.cameras_refreshed_signal.connect(self._on_cameras_refreshed)
        self.tracking_finished_signal.connect(self._on_tracking_finished)

        # Initial mode setup
        initial_mode = self.cfg.get("camera_mode", "pscam")
        self._set_mode(initial_mode, animate=False)

        # Initial PS Camera status and camera discovery
        self._update_pscam_status()
        if auto_discover:
            self._refresh_cameras_async()

            # Periodic non-blocking check (1000ms)
            self.timer_periodic = QTimer(self)
            self.timer_periodic.timeout.connect(self._periodic_check)
            self.timer_periodic.start(1000)
        else:
            self.timer_periodic = None

    def _load_pixmaps(self):
        """Loads pure PIL RGBA icons and converts them into antialiased QPixmaps with 4x supersampling."""
        try:
            p_ps_act, p_ps_inact, p_web_act, p_web_inact = generate_icons_pil(target_box=(38, 26), scale=4)
            self.pix_ps_act = pil_to_qpixmap(p_ps_act, dpr=4.0)
            self.pix_ps_inact = pil_to_qpixmap(p_ps_inact, dpr=4.0)
            self.pix_web_act = pil_to_qpixmap(p_web_act, dpr=4.0)
            self.pix_web_inact = pil_to_qpixmap(p_web_inact, dpr=4.0)
        except Exception as e:
            print(f"[WARN] Failed to load device icons: {e}")
            self.pix_ps_act = self.pix_ps_inact = self.pix_web_act = self.pix_web_inact = QPixmap()

        try:
            p_gear_act, p_gear_inact, p_slid_act, p_slid_inact, p_slid_dis, p_lab_act, p_lab_inact = generate_tab_icons_pil(size=(18, 18), scale=4)
            self.pix_gear_act = pil_to_qpixmap(p_gear_act, dpr=4.0)
            self.pix_gear_inact = pil_to_qpixmap(p_gear_inact, dpr=4.0)
            self.pix_slid_act = pil_to_qpixmap(p_slid_act, dpr=4.0)
            self.pix_slid_inact = pil_to_qpixmap(p_slid_inact, dpr=4.0)
            self.pix_slid_disabled = pil_to_qpixmap(p_slid_dis, dpr=4.0)
            self.pix_lab_act = pil_to_qpixmap(p_lab_act, dpr=4.0)
            self.pix_lab_inact = pil_to_qpixmap(p_lab_inact, dpr=4.0)
        except Exception as e:
            print(f"[WARN] Failed to load tab icons: {e}")
            self.pix_gear_act = self.pix_gear_inact = self.pix_slid_act = self.pix_slid_inact = self.pix_slid_disabled = self.pix_lab_act = self.pix_lab_inact = QPixmap()

        try:
            p_modes = generate_mode_icons_pil(size=(15, 15), scale=4)
            self.mode_pixmaps = {
                pid: (pil_to_qpixmap(act, dpr=4.0), pil_to_qpixmap(inact, dpr=4.0))
                for pid, (act, inact) in p_modes.items()
            }
        except Exception as e:
            print(f"[WARN] Failed to load mode icons: {e}")
            self.mode_pixmaps = {}

        try:
            p_err, p_ok, p_warn = generate_status_icons_pil(size=(38, 38), scale=4)
            self.pix_status_err = pil_to_qpixmap(p_err, dpr=4.0)
            self.pix_status_ok = pil_to_qpixmap(p_ok, dpr=4.0)
            self.pix_status_warn = pil_to_qpixmap(p_warn, dpr=4.0)
        except Exception as e:
            print(f"[WARN] Failed to load status icons: {e}")
            self.pix_status_err = self.pix_status_ok = self.pix_status_warn = QPixmap()

    def _setup_style(self):
        """Applies the Crisp White & PlayStation Blue stylesheet (QSS)."""
        self.setStyleSheet(f"""
            QMainWindow, QWidget#centralWidget {{
                background-color: {PALETTE["bg_window"]};
                color: {PALETTE["text_main"]};
                font-family: '{self.font_body}', 'Segoe UI', sans-serif;
            }}
            QFrame#sidebar {{
                background-color: {PALETTE["bg_sidebar"]};
                border-right: 1px solid {PALETTE["border_subtle"]};
            }}
            QFrame[class="card"] {{
                background-color: {PALETTE["bg_card"]};
                border: 1px solid {PALETTE["border_subtle"]};
                border-radius: 10px;
            }}
            QFrame[class="status_balloon"] {{
                background-color: {PALETTE["input_bg"]};
                border: 1px solid {PALETTE["border_subtle"]};
                border-radius: 12px;
            }}
            QFrame[class="spec_badge"] {{
                background-color: {PALETTE["blue_pastel"]};
                border: none;
                border-radius: 8px;
            }}
            QPushButton[class="btn_cta"] {{
                background-color: {PALETTE["ps_blue"]};
                color: #FFFFFF;
                font-family: '{self.font_heading}', sans-serif;
                font-weight: bold;
                font-size: 14px;
                border-radius: 8px;
                padding: 12px;
                border: none;
            }}
            QPushButton[class="btn_cta"]:hover {{
                background-color: {PALETTE["ps_blue_hover"]};
            }}
            QPushButton[class="btn_cta"]:pressed {{
                background-color: {PALETTE["ps_blue_active"]};
            }}
            QPushButton[class="btn_cta"]:disabled {{
                background-color: #CBD5E1;
                color: #64748B;
            }}
            QPushButton[class="btn_secondary"] {{
                background-color: {PALETTE["blue_pastel"]};
                color: {PALETTE["blue_dark"]};
                font-family: '{self.font_heading}', sans-serif;
                font-weight: bold;
                font-size: 11px;
                border-radius: 8px;
                padding: 8px 12px;
                border: none;
            }}
            QPushButton[class="btn_secondary"]:hover {{
                background-color: {PALETTE["blue_pastel_hover"]};
            }}
            QPushButton[class="btn_secondary"]:pressed {{
                background-color: #B8E2F2;
            }}
            QPushButton[class="btn_secondary"]:disabled {{
                background-color: {PALETTE["input_bg"]};
                color: {PALETTE["text_muted"]};
            }}
            QPushButton[class="btn_balloon_action"] {{
                background-color: #F8FAFC;
                color: {PALETTE["blue_dark"]};
                font-family: '{self.font_heading}', sans-serif;
                font-weight: bold;
                font-size: 12px;
                border: 1px solid {PALETTE["border_subtle"]};
                border-radius: 12px;
                padding: 10px 16px;
                text-align: center;
            }}
            QPushButton[class="btn_balloon_action"]:hover {{
                background-color: #F1F5F9;
                border-color: {PALETTE["input_border"]};
            }}
            QPushButton[class="btn_balloon_action"]:pressed {{
                background-color: {PALETTE["blue_pastel"]};
            }}
            QPushButton[class="btn_balloon_action"]:disabled {{
                background-color: {PALETTE["input_bg"]};
                color: {PALETTE["text_muted"]};
                border-color: {PALETTE["border_subtle"]};
            }}
            QComboBox {{
                background-color: {PALETTE["input_bg"]};
                color: {PALETTE["text_main"]};
                font-family: '{self.font_body}', sans-serif;
                border: 1px solid {PALETTE["input_border"]};
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
            }}
            QComboBox:hover {{
                border-color: {PALETTE["ps_blue"]};
            }}
            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 24px;
                border-left: 1px solid {PALETTE["input_border"]};
                background-color: {PALETTE["blue_pastel"]};
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
            }}
            QComboBox QAbstractItemView {{
                background-color: #FFFFFF;
                color: {PALETTE["text_main"]};
                selection-background-color: {PALETTE["ps_blue"]};
                selection-color: #FFFFFF;
                border: 1px solid {PALETTE["input_border"]};
                border-radius: 6px;
            }}
            QCheckBox {{
                color: {PALETTE["text_main"]};
                font-family: '{self.font_body}', sans-serif;
                font-size: 12px;
                spacing: 8px;
                background: transparent;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 1px solid {PALETTE["input_border"]};
                background-color: #FFFFFF;
            }}
            QCheckBox::indicator:hover {{
                border-color: {PALETTE["ps_blue"]};
            }}
            QCheckBox::indicator:checked {{
                background-color: {PALETTE["ps_blue"]};
                border-color: {PALETTE["ps_blue"]};
            }}
            QSlider::groove:horizontal {{
                height: 6px;
                background: {PALETTE["blue_pastel"]};
                border-radius: 3px;
            }}
            QSlider::sub-page:horizontal {{
                background: {PALETTE["ps_blue"]};
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                background: {PALETTE["ps_blue"]};
                width: 16px;
                margin-top: -5px;
                margin-bottom: -5px;
                border-radius: 8px;
            }}
        """)

    def _build_ui(self):
        """Builds the main horizontal split layout."""
        central_widget = QWidget(self)
        central_widget.setObjectName("centralWidget")
        self.setCentralWidget(central_widget)

        master_layout = QHBoxLayout(central_widget)
        master_layout.setContentsMargins(0, 0, 0, 0)
        master_layout.setSpacing(0)

        # =====================================================================
        # 1. LEFT SIDEBAR (Width 270, Crisp White)
        # =====================================================================
        self.sidebar_frame = QFrame(central_widget)
        self.sidebar_frame.setObjectName("sidebar")
        self.sidebar_frame.setFixedWidth(270)
        sidebar_layout = QVBoxLayout(self.sidebar_frame)
        sidebar_layout.setContentsMargins(18, 20, 18, 20)
        sidebar_layout.setSpacing(0)

        # 1.1 Brand Header (Simple visual using Kanit font)
        lbl_brand = QLabel("Legacy PSCam Sensor", self.sidebar_frame)
        lbl_brand.setStyleSheet(
            f"font-family: '{self.font_title}'; font-size: 20px; font-weight: 600; color: {PALETTE['ps_blue']}; background: transparent;"
        )
        sidebar_layout.addWidget(lbl_brand)

        lbl_edition = QLabel("for Legacy Offline PC", self.sidebar_frame)
        lbl_edition.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 11px; font-weight: bold; color: {PALETTE['text_muted']}; background: transparent;"
        )
        sidebar_layout.addWidget(lbl_edition)
        sidebar_layout.addSpacing(14)

        # Divider
        div_line = QFrame(self.sidebar_frame)
        div_line.setFrameShape(QFrame.Shape.HLine)
        div_line.setStyleSheet(f"background-color: {PALETTE['border_subtle']}; max-height: 1px; border: none;")
        sidebar_layout.addWidget(div_line)
        sidebar_layout.addSpacing(14)

        # 1.2 Device Switcher Section Title
        lbl_devices_hdr = QLabel("CAPTURE DEVICE", self.sidebar_frame)
        lbl_devices_hdr.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['blue_dark']}; background: transparent;"
        )
        sidebar_layout.addWidget(lbl_devices_hdr)
        sidebar_layout.addSpacing(8)

        # 1.3 Card PS Camera (with supersampled icon)
        self.card_pscam = DeviceNavCard(
            "PlayStation®Camera",
            "OV580 Stereo • 60 FPS",
            self.font_heading,
            self.font_body,
            self.sidebar_frame
        )
        self.card_pscam.set_icons(self.pix_ps_act, self.pix_ps_inact)
        self.card_pscam.clicked.connect(lambda: self._set_mode("pscam"))
        sidebar_layout.addWidget(self.card_pscam)
        sidebar_layout.addSpacing(8)

        # 1.4 Card Standard Webcam (with supersampled icon)
        self.card_webcam = DeviceNavCard(
            "Standard Webcam",
            "USB or Integrated",
            self.font_heading,
            self.font_body,
            self.sidebar_frame
        )
        self.card_webcam.set_icons(self.pix_web_act, self.pix_web_inact)
        self.card_webcam.clicked.connect(lambda: self._set_mode("webcam"))
        sidebar_layout.addWidget(self.card_webcam)
        sidebar_layout.addSpacing(16)

        # 1.5 Quick Action: Open Kinect10.dll folder
        self.btn_dll_folder = QPushButton("Open Kinect10.dll Folder", self.sidebar_frame)
        self.btn_dll_folder.setProperty("class", "btn_secondary")
        self.btn_dll_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_dll_folder.clicked.connect(self._open_dll_folder)
        sidebar_layout.addWidget(self.btn_dll_folder)
        sidebar_layout.addSpacing(6)

        lbl_dll_tip = QLabel("Copy Kinect10.dll to the game\nfolder to enable motion capture.", self.sidebar_frame)
        lbl_dll_tip.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 10px; color: {PALETTE['text_muted']}; background: transparent;"
        )
        sidebar_layout.addWidget(lbl_dll_tip)

        sidebar_layout.addStretch()

        # 1.6 Mini Credits
        lbl_cred1 = QLabel("Original Legacy Sensor by itsVexor", self.sidebar_frame)
        lbl_cred1.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 10px; color: {PALETTE['text_muted']}; background: transparent;"
        )
        lbl_cred2 = QLabel("PSCam4Win by BumbleTree & Moon36", self.sidebar_frame)
        lbl_cred2.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 10px; color: {PALETTE['text_muted']}; background: transparent;"
        )
        lbl_cred3 = QLabel("Made by Edd", self.sidebar_frame)
        lbl_cred3.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 10px; color: {PALETTE['text_muted']}; background: transparent;"
        )
        sidebar_layout.addWidget(lbl_cred1)
        sidebar_layout.addSpacing(2)
        sidebar_layout.addWidget(lbl_cred2)
        sidebar_layout.addSpacing(2)
        sidebar_layout.addWidget(lbl_cred3)
        sidebar_layout.addSpacing(4)

        master_layout.addWidget(self.sidebar_frame)

        # =====================================================================
        # 2. MAIN CONTENT AREA (Right Side)
        # =====================================================================
        self.content_widget = QWidget(central_widget)
        content_layout = QVBoxLayout(self.content_widget)
        content_layout.setContentsMargins(26, 20, 26, 20)
        content_layout.setSpacing(14)

        # 2.1 Top Tab Navigation Strip (Centered)
        top_nav_layout = QHBoxLayout()
        top_nav_layout.setContentsMargins(0, 0, 0, 2)

        self.btn_tab_video = QPushButton("  Video Settings", self.content_widget)
        self.btn_tab_video.setFixedSize(148, 42)
        self.btn_tab_video.setIcon(QIcon(self.pix_gear_act))
        self.btn_tab_video.setIconSize(QSize(18, 18))
        self.btn_tab_video.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_tab_video.clicked.connect(lambda: self._switch_tab("video"))

        self.btn_tab_calib = QPushButton("  Calibration", self.content_widget)
        self.btn_tab_calib.setFixedSize(130, 42)
        self.btn_tab_calib.setIcon(QIcon(self.pix_slid_inact))
        self.btn_tab_calib.setIconSize(QSize(18, 18))
        self.btn_tab_calib.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_tab_calib.clicked.connect(lambda: self._switch_tab("calib"))

        self.btn_tab_exp = QPushButton("  Experimental", self.content_widget)
        self.btn_tab_exp.setFixedSize(142, 42)
        self.btn_tab_exp.setIcon(QIcon(self.pix_lab_inact))
        self.btn_tab_exp.setIconSize(QSize(18, 18))
        self.btn_tab_exp.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_tab_exp.clicked.connect(lambda: self._switch_tab("exp"))

        top_nav_layout.addStretch()
        top_nav_layout.addWidget(self.btn_tab_video)
        top_nav_layout.addSpacing(10)
        top_nav_layout.addWidget(self.btn_tab_calib)
        top_nav_layout.addSpacing(10)
        top_nav_layout.addWidget(self.btn_tab_exp)
        top_nav_layout.addStretch()
        content_layout.addLayout(top_nav_layout)
        self._apply_tab_styles("video")

        # Full horizontal separator line under tab strip
        sep = QFrame(self.content_widget)
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background-color: {PALETTE['border_subtle']}; max-height: 1px; border: none;")
        content_layout.addWidget(sep)

        # 2.2 Animated Sliding Stacked Widget
        self.stacked_view = SlidingStackedWidget(self.content_widget)
        content_layout.addWidget(self.stacked_view, stretch=1)

        # Build Page 0 (Video), Page 1 (Calibration), & Page 2 (Experimental)
        self._build_video_view()
        self._build_calib_view()
        self._build_exp_view()

        # 2.3 Bottom Action Area (PlayStation Blue CTA & Footer)
        self.btn_start = QPushButton("START TRACKING", self.content_widget)
        self.btn_start.setProperty("class", "btn_cta")
        self.btn_start.setFixedHeight(48)
        self.btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_start.clicked.connect(self._start_tracking)
        content_layout.addWidget(self.btn_start)

        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(0, 2, 0, 0)
        lbl_ver = QLabel(f"{APP_NAME} {VERSION_STRING}", self.content_widget)
        lbl_ver.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 11px; color: {PALETTE['text_dim']}; background: transparent;"
        )
        footer_layout.addStretch()
        footer_layout.addWidget(lbl_ver)
        content_layout.addLayout(footer_layout)

        master_layout.addWidget(self.content_widget, stretch=1)

    def _build_video_view(self):
        """Constructs Page 0: Video Settings."""
        self.page_video = QWidget()
        layout = QVBoxLayout(self.page_video)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(12)

        # =====================================================================
        # 1. PlayStation Camera Views
        # =====================================================================
        # 1.1 Disconnected Balloon (Shown as the ONLY element when disconnected)
        self.pscam_disconnected_box = QWidget(self.page_video)
        ps_disc_layout = QVBoxLayout(self.pscam_disconnected_box)
        ps_disc_layout.setContentsMargins(0, 0, 0, 0)
        ps_disc_layout.setSpacing(10)

        self.pscam_status_card = QFrame(self.pscam_disconnected_box)
        self.pscam_status_card.setProperty("class", "status_balloon")
        card_layout = QHBoxLayout(self.pscam_status_card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        card_layout.setSpacing(14)

        self.lbl_pscam_icon = QLabel(self.pscam_status_card)
        self.lbl_pscam_icon.setPixmap(self.pix_status_err)
        self.lbl_pscam_icon.setFixedSize(38, 38)
        self.lbl_pscam_icon.setStyleSheet("background: transparent; border: none;")
        card_layout.addWidget(self.lbl_pscam_icon)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self.lbl_pscam_conn_title = QLabel("PlayStation Camera not connected", self.pscam_status_card)
        self.lbl_pscam_conn_title.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 14px; font-weight: bold; color: {PALETTE['text_main']}; background: transparent; border: none;"
        )
        self.lbl_pscam_info = QLabel("Driver Offline and Camera disconnected from USB Port", self.pscam_status_card)
        self.lbl_pscam_info.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 11px; color: {PALETTE['text_muted']}; background: transparent; border: none;"
        )
        text_col.addWidget(self.lbl_pscam_conn_title)
        text_col.addWidget(self.lbl_pscam_info)
        card_layout.addLayout(text_col, stretch=1)
        ps_disc_layout.addWidget(self.pscam_status_card)

        self.btn_launch_pscam = QPushButton("Start PSCam4Win Driver", self.pscam_disconnected_box)
        self.btn_launch_pscam.setProperty("class", "btn_balloon_action")
        self.btn_launch_pscam.setFixedHeight(42)
        self.btn_launch_pscam.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_launch_pscam.clicked.connect(self._launch_pscam_tray)
        ps_disc_layout.addWidget(self.btn_launch_pscam)
        layout.addWidget(self.pscam_disconnected_box)

        # 1.2 Connected Options Card
        self.pscam_card = QFrame(self.page_video)
        self.pscam_card.setProperty("class", "card")
        ps_conn_layout = QVBoxLayout(self.pscam_card)
        ps_conn_layout.setContentsMargins(16, 14, 16, 14)
        ps_conn_layout.setSpacing(8)

        lbl_ps_title = QLabel("PLAYSTATION®CAMERA INTEGRATION", self.pscam_card)
        lbl_ps_title.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 12px; font-weight: bold; color: {PALETTE['blue_dark']}; background: transparent; border: none;"
        )
        ps_conn_layout.addWidget(lbl_ps_title)

        self.lbl_pscam_ready_info = QLabel("Driver active and PlayStation®Camera connected (60 FPS)", self.pscam_card)
        self.lbl_pscam_ready_info.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 11px; color: {PALETTE['status_ok']}; background: transparent; border: none;"
        )
        ps_conn_layout.addWidget(self.lbl_pscam_ready_info)

        spec_badge = QFrame(self.pscam_card)
        spec_badge.setProperty("class", "spec_badge")
        spec_layout = QVBoxLayout(spec_badge)
        spec_layout.setContentsMargins(12, 10, 12, 10)
        spec_layout.setSpacing(2)
        lbl_spec_title = QLabel("Optimized Auto Mode: 1280x800 @ 60 FPS (OV580 Stereo DirectShow)", spec_badge)
        lbl_spec_title.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['blue_dark']}; background: transparent; border: none;"
        )
        lbl_spec_sub = QLabel(
            "Resolution picker is hidden in this tab because the PlayStation®Camera operates in the driver's native format.",
            spec_badge
        )
        lbl_spec_sub.setWordWrap(True)
        lbl_spec_sub.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 10px; color: {PALETTE['text_muted']}; background: transparent; border: none;"
        )
        spec_layout.addWidget(lbl_spec_title)
        spec_layout.addWidget(lbl_spec_sub)
        ps_conn_layout.addWidget(spec_badge)
        layout.addWidget(self.pscam_card)

        # =====================================================================
        # 2. Webcam Views
        # =====================================================================
        # 2.1 Disconnected Balloon
        self.webcam_disconnected_box = QWidget(self.page_video)
        web_disc_layout = QVBoxLayout(self.webcam_disconnected_box)
        web_disc_layout.setContentsMargins(0, 0, 0, 0)
        web_disc_layout.setSpacing(10)

        self.webcam_status_card = QFrame(self.webcam_disconnected_box)
        self.webcam_status_card.setProperty("class", "status_balloon")
        web_card_layout = QHBoxLayout(self.webcam_status_card)
        web_card_layout.setContentsMargins(16, 14, 16, 14)
        web_card_layout.setSpacing(14)

        self.lbl_webcam_icon = QLabel(self.webcam_status_card)
        self.lbl_webcam_icon.setPixmap(self.pix_status_err)
        self.lbl_webcam_icon.setFixedSize(38, 38)
        self.lbl_webcam_icon.setStyleSheet("background: transparent; border: none;")
        web_card_layout.addWidget(self.lbl_webcam_icon)

        web_text_col = QVBoxLayout()
        web_text_col.setSpacing(2)
        self.lbl_webcam_conn_title = QLabel("Webcam not connected", self.webcam_status_card)
        self.lbl_webcam_conn_title.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 14px; font-weight: bold; color: {PALETTE['text_main']}; background: transparent; border: none;"
        )
        self.lbl_webcam_info = QLabel("Camera disconnected from USB Port", self.webcam_status_card)
        self.lbl_webcam_info.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 11px; color: {PALETTE['text_muted']}; background: transparent; border: none;"
        )
        web_text_col.addWidget(self.lbl_webcam_conn_title)
        web_text_col.addWidget(self.lbl_webcam_info)
        web_card_layout.addLayout(web_text_col, stretch=1)
        web_disc_layout.addWidget(self.webcam_status_card)

        self.btn_refresh_webcam = QPushButton("Search for Webcams", self.webcam_disconnected_box)
        self.btn_refresh_webcam.setProperty("class", "btn_balloon_action")
        self.btn_refresh_webcam.setFixedHeight(42)
        self.btn_refresh_webcam.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh_webcam.clicked.connect(self._refresh_cameras)
        web_disc_layout.addWidget(self.btn_refresh_webcam)
        layout.addWidget(self.webcam_disconnected_box)

        # 2.2 Connected Card
        self.webcam_card = QFrame(self.page_video)
        self.webcam_card.setProperty("class", "card")
        web_conn_layout = QVBoxLayout(self.webcam_card)
        web_conn_layout.setContentsMargins(16, 14, 16, 14)
        web_conn_layout.setSpacing(10)

        lbl_wc_title = QLabel("WEBCAM VIDEO SETTINGS", self.webcam_card)
        lbl_wc_title.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 12px; font-weight: bold; color: {PALETTE['blue_dark']}; background: transparent; border: none;"
        )
        web_conn_layout.addWidget(lbl_wc_title)

        dev_row = QHBoxLayout()
        lbl_dev = QLabel("Device:", self.webcam_card)
        lbl_dev.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['text_main']}; background: transparent; border: none;"
        )
        lbl_dev.setFixedWidth(115)
        self.cb_cameras = QComboBox(self.webcam_card)
        self.cb_cameras.currentIndexChanged.connect(self._on_camera_selected)
        btn_refresh = QPushButton("↻", self.webcam_card)
        btn_refresh.setFixedSize(36, 32)
        btn_refresh.setProperty("class", "btn_secondary")
        btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_refresh.clicked.connect(self._refresh_cameras)
        dev_row.addWidget(lbl_dev)
        dev_row.addWidget(self.cb_cameras, stretch=1)
        dev_row.addWidget(btn_refresh)
        web_conn_layout.addLayout(dev_row)

        # Resolution & FPS side-by-side blocks
        res_fps_layout = QHBoxLayout()
        res_fps_layout.setSpacing(14)

        # Block 1: Resolution
        res_col = QVBoxLayout()
        res_col.setSpacing(4)
        lbl_res = QLabel("Resolution:", self.webcam_card)
        lbl_res.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['text_main']}; background: transparent; border: none;"
        )
        self.cb_res = QComboBox(self.webcam_card)
        self.cb_res.addItems(["640x480", "1280x720", "1920x1080"])
        self.cb_res.currentIndexChanged.connect(self._on_webcam_res_or_fps_changed)
        res_col.addWidget(lbl_res)
        res_col.addWidget(self.cb_res)
        res_fps_layout.addLayout(res_col, stretch=1)

        # Block 2: FPS
        fps_col = QVBoxLayout()
        fps_col.setSpacing(4)
        lbl_fps = QLabel("Framerate (FPS):", self.webcam_card)
        lbl_fps.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['text_main']}; background: transparent; border: none;"
        )
        self.cb_fps = QComboBox(self.webcam_card)
        self.cb_fps.addItems(["30 FPS", "60 FPS"])
        self.cb_fps.currentIndexChanged.connect(self._on_webcam_res_or_fps_changed)
        fps_col.addWidget(lbl_fps)
        fps_col.addWidget(self.cb_fps)
        res_fps_layout.addLayout(fps_col, stretch=1)

        web_conn_layout.addLayout(res_fps_layout)

        # Backward compatibility handle for cb_preset
        self.cb_preset = QComboBox(self.webcam_card)
        self.cb_preset.setVisible(False)
        self.cb_preset.currentIndexChanged.connect(self._on_preset_selected)

        layout.addWidget(self.webcam_card)

        # =====================================================================
        # 3. Additional Display Options (Shown ONLY when connected)
        # =====================================================================
        self.display_card = QFrame(self.page_video)
        self.display_card.setProperty("class", "card")
        disp_layout = QVBoxLayout(self.display_card)
        disp_layout.setContentsMargins(16, 12, 16, 12)
        disp_layout.setSpacing(8)

        lbl_disp_title = QLabel("ADDITIONAL DISPLAY OPTIONS", self.display_card)
        lbl_disp_title.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 12px; font-weight: bold; color: {PALETTE['blue_dark']}; background: transparent; border: none;"
        )
        disp_layout.addWidget(lbl_disp_title)

        self.chk_hud = QCheckBox("Display HUD Overlay in Tracking Window (FPS, IPC & Shortcuts)", self.display_card)
        self.chk_hud.setChecked(self.cfg.get("show_hud", True))
        self.chk_hud.stateChanged.connect(self._on_display_options_changed)
        disp_layout.addWidget(self.chk_hud)

        layout.addWidget(self.display_card)
        layout.addStretch()

        self.stacked_view.addWidget(self.page_video)

    def _build_calib_view(self):
        """Constructs Page 1: Calibration & Motion Profile."""
        self.page_calib = QWidget()
        layout = QVBoxLayout(self.page_calib)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(10)

        main_card = QFrame(self.page_calib)
        main_card.setProperty("class", "card")
        card_layout = QVBoxLayout(main_card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        card_layout.setSpacing(10)

        lbl_head = QLabel("TRACKING & MOTION PROFILE", main_card)
        lbl_head.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 12px; font-weight: bold; color: {PALETTE['blue_dark']}; background: transparent; border: none;"
        )
        lbl_sub = QLabel("Select the profile that best fits your playstyle and camera setup.", main_card)
        lbl_sub.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 11px; color: {PALETTE['text_muted']}; background: transparent; border: none;"
        )
        card_layout.addWidget(lbl_head)
        card_layout.addWidget(lbl_sub)

        # 3 Profile cards
        cards_row = QHBoxLayout()
        cards_row.setSpacing(8)

        for pid, pdata in CALIB_PRESETS.items():
            pix_act, pix_inact = self.mode_pixmaps.get(pid, (QPixmap(), QPixmap()))
            card = CalibPresetCard(pid, pdata, self.font_heading, self.font_body, pix_act, pix_inact, main_card)
            card.clicked.connect(self._select_calib_preset)
            cards_row.addWidget(card)
            self.calib_cards[pid] = card

        card_layout.addLayout(cards_row)

        # Auto-height callout
        auto_h = QFrame(main_card)
        auto_h.setStyleSheet(f"""
            QFrame {{
                background-color: {PALETTE["input_bg"]};
                border: 1px solid {PALETTE["border_subtle"]};
                border-radius: 8px;
            }}
        """)
        ah_layout = QHBoxLayout(auto_h)
        ah_layout.setContentsMargins(12, 8, 12, 8)
        ah_layout.setSpacing(10)
        lbl_ruler = QLabel("📏", auto_h)
        lbl_ruler.setStyleSheet("font-size: 16px; background: transparent; border: none;")
        ah_layout.addWidget(lbl_ruler)
        ah_text = QVBoxLayout()
        ah_text.setSpacing(1)
        ah_title = QLabel("Automatic Height Calibration (1.75m default)", auto_h)
        ah_title.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['blue_dark']}; background: transparent; border: none;"
        )
        ah_sub = QLabel(
            "The sensor dynamically normalizes body proportions to the Just Dance Kinect v1 metric convention. No manual adjustment needed.",
            auto_h
        )
        ah_sub.setWordWrap(True)
        ah_sub.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 10px; color: {PALETTE['text_muted']}; background: transparent; border: none;"
        )
        ah_text.addWidget(ah_title)
        ah_text.addWidget(ah_sub)
        ah_layout.addLayout(ah_text, stretch=1)
        card_layout.addWidget(auto_h)

        # Advanced settings controls (hidden for now per user request)
        self.btn_toggle_adv = QPushButton("Show Advanced Filter Settings ▼", main_card)
        self.btn_toggle_adv.setProperty("class", "btn_secondary")
        self.btn_toggle_adv.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle_adv.clicked.connect(self._toggle_advanced_calib)
        self.btn_toggle_adv.setVisible(False)

        # Advanced drawer (hidden for now per user request)
        self.adv_drawer = QFrame(main_card)
        self.adv_drawer.setVisible(False)
        self.adv_drawer.setStyleSheet(f"""
            QFrame {{
                background-color: {PALETTE["bg_card"]};
                border: 1px solid {PALETTE["border_subtle"]};
                border-radius: 8px;
            }}
        """)
        adv_layout = QVBoxLayout(self.adv_drawer)
        adv_layout.setContentsMargins(14, 10, 14, 10)
        adv_layout.setSpacing(6)

        # Slider 1: Smoothing
        self.lbl_smooth = QLabel("", self.adv_drawer)
        self.lbl_smooth.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['text_main']}; background: transparent; border: none;"
        )
        adv_layout.addWidget(self.lbl_smooth)
        self.slider_smooth = QSlider(Qt.Orientation.Horizontal, self.adv_drawer)
        self.slider_smooth.setRange(20, 85)
        self.slider_smooth.setValue(int(self.cfg.get("smoothing_alpha", 0.55) * 100))
        self.slider_smooth.valueChanged.connect(self._on_smooth_slider_changed)
        adv_layout.addWidget(self.slider_smooth)
        self._update_smooth_label(self.cfg.get("smoothing_alpha", 0.55))

        # Slider 2: Confidence
        self.lbl_conf = QLabel("", self.adv_drawer)
        self.lbl_conf.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['text_main']}; background: transparent; border: none;"
        )
        adv_layout.addWidget(self.lbl_conf)
        self.slider_conf = QSlider(Qt.Orientation.Horizontal, self.adv_drawer)
        self.slider_conf.setRange(30, 80)
        self.slider_conf.setValue(int(self.cfg.get("detection_confidence", 0.50) * 100))
        self.slider_conf.valueChanged.connect(self._on_conf_slider_changed)
        adv_layout.addWidget(self.slider_conf)
        self._update_conf_label(self.cfg.get("detection_confidence", 0.50))

        # Reset button row
        adv_actions = QHBoxLayout()
        btn_reset = QPushButton("↺ Reset to Recommended Profile (Balanced)", self.adv_drawer)
        btn_reset.setProperty("class", "btn_secondary")
        btn_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_reset.clicked.connect(lambda: self._select_calib_preset("balanced"))
        adv_actions.addWidget(btn_reset)
        adv_actions.addStretch()
        adv_layout.addLayout(adv_actions)

        self.adv_drawer.setVisible(False)

        layout.addWidget(main_card)
        layout.addStretch()

        self.stacked_view.addWidget(self.page_calib)
        self._update_calib_cards_ui()

    def _build_exp_view(self):
        """Constructs Page 2: Experimental Features."""
        self.page_exp = QWidget()
        layout = QVBoxLayout(self.page_exp)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(12)

        exp_card = QFrame(self.page_exp)
        exp_card.setProperty("class", "card")
        exp_layout = QVBoxLayout(exp_card)
        exp_layout.setContentsMargins(16, 16, 16, 16)
        exp_layout.setSpacing(12)

        lbl_title = QLabel("EXPERIMENTAL FEATURES", exp_card)
        lbl_title.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 12px; font-weight: bold; color: {PALETTE['blue_dark']}; background: transparent; border: none;"
        )
        exp_layout.addWidget(lbl_title)

        # Auto-Frame Feature Box
        auto_frame_box = QFrame(exp_card)
        auto_frame_box.setStyleSheet(f"""
            QFrame {{
                background-color: {PALETTE["input_bg"]};
                border: 1px solid {PALETTE["border_subtle"]};
                border-radius: 8px;
            }}
        """)
        af_layout = QVBoxLayout(auto_frame_box)
        af_layout.setContentsMargins(14, 12, 14, 12)
        af_layout.setSpacing(6)

        self.chk_face = QCheckBox("Auto-Frame player's face in Just Dance (Digital PTZ)", auto_frame_box)
        self.chk_face.setChecked(self.cfg.get("face_follow_enabled", True))
        self.chk_face.stateChanged.connect(self._on_display_options_changed)
        af_layout.addWidget(self.chk_face)

        lbl_desc = QLabel(
            "Dynamically tracks and frames the dancer's face and upper torso using real-time landmark tracking. "
            "Smoothly pans and crops the game video stream sent to Just Dance PC while keeping 3D skeletal tracking unaffected.",
            auto_frame_box
        )
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 11px; color: {PALETTE['text_muted']}; background: transparent; border: none;"
        )
        af_layout.addWidget(lbl_desc)

        exp_layout.addWidget(auto_frame_box)
        layout.addWidget(exp_card)
        layout.addStretch()

        self.stacked_view.addWidget(self.page_exp)

    # =========================================================================
    # UI STATE MANAGEMENT & VISIBILITY
    # =========================================================================
    def is_camera_accessible(self) -> bool:
        """Returns True if the currently selected camera device is connected and accessible."""
        mode = self.cfg.get("camera_mode", "pscam")
        if mode == "pscam":
            return getattr(self, "_current_pscam_state", "DISCONNECTED") == "READY"
        else:
            cams = getattr(self, "camera_list", [])
            webcams = [c for c in cams if not c.is_pscam]
            if not webcams and not any(c.is_pscam for c in cams):
                webcams = cams
            return len(webcams) > 0

    def _disabled_tab_css(self) -> str:
        return f"""
            QPushButton {{
                background-color: #F1F5F9;
                color: #94A3B8;
                font-family: '{self.font_heading}', sans-serif;
                font-size: 12px;
                font-weight: bold;
                border: 1px solid #CBD5E1;
                border-radius: 10px;
            }}
        """

    def _update_tab_availability(self):
        """Disables and grays out the Calibration tab when the camera is not connected/accessible."""
        accessible = self.is_camera_accessible()
        if not accessible:
            self.btn_tab_calib.setEnabled(False)
            self.btn_tab_calib.setCursor(Qt.CursorShape.ForbiddenCursor)
            if self.active_tab == "calib":
                self._switch_tab("video")
            else:
                self.btn_tab_calib.setStyleSheet(self._disabled_tab_css())
                self.btn_tab_calib.setIcon(QIcon(self.pix_slid_disabled))
        else:
            self.btn_tab_calib.setEnabled(True)
            self.btn_tab_calib.setCursor(Qt.CursorShape.PointingHandCursor)
            self._apply_tab_styles(self.active_tab)

    def _apply_tab_styles(self, tab_id: str):
        act_css = f"""
            QPushButton {{
                background-color: {PALETTE["tab_gray_act"]};
                color: #0F172A;
                font-family: '{self.font_heading}', sans-serif;
                font-size: 12px;
                font-weight: bold;
                border: 1px solid {PALETTE["tab_gray_border"]};
                border-radius: 10px;
            }}
        """
        inact_css = f"""
            QPushButton {{
                background-color: #FFFFFF;
                color: #64748B;
                font-family: '{self.font_heading}', sans-serif;
                font-size: 12px;
                font-weight: bold;
                border: 1px solid {PALETTE["border_subtle"]};
                border-radius: 10px;
            }}
            QPushButton:hover {{
                background-color: {PALETTE["tab_gray_hover"]};
                border-color: {PALETTE["tab_gray_border"]};
            }}
        """
        accessible = self.is_camera_accessible()

        # Video Tab
        if tab_id == "video":
            self.btn_tab_video.setStyleSheet(act_css)
            self.btn_tab_video.setIcon(QIcon(self.pix_gear_act))
        else:
            self.btn_tab_video.setStyleSheet(inact_css)
            self.btn_tab_video.setIcon(QIcon(self.pix_gear_inact))

        # Calibration Tab (Access-Gated)
        if not accessible:
            self.btn_tab_calib.setEnabled(False)
            self.btn_tab_calib.setCursor(Qt.CursorShape.ForbiddenCursor)
            self.btn_tab_calib.setStyleSheet(self._disabled_tab_css())
            self.btn_tab_calib.setIcon(QIcon(self.pix_slid_disabled))
        else:
            self.btn_tab_calib.setEnabled(True)
            self.btn_tab_calib.setCursor(Qt.CursorShape.PointingHandCursor)
            if tab_id == "calib":
                self.btn_tab_calib.setStyleSheet(act_css)
                self.btn_tab_calib.setIcon(QIcon(self.pix_slid_act))
            else:
                self.btn_tab_calib.setStyleSheet(inact_css)
                self.btn_tab_calib.setIcon(QIcon(self.pix_slid_inact))

        # Experimental Tab
        if hasattr(self, "btn_tab_exp"):
            if tab_id == "exp":
                self.btn_tab_exp.setStyleSheet(act_css)
                self.btn_tab_exp.setIcon(QIcon(self.pix_lab_act))
            else:
                self.btn_tab_exp.setStyleSheet(inact_css)
                self.btn_tab_exp.setIcon(QIcon(self.pix_lab_inact))

    def _switch_tab(self, tab_id: str):
        if tab_id == "calib" and not self.is_camera_accessible():
            return
        if self.active_tab == tab_id:
            return
        self.active_tab = tab_id
        self._apply_tab_styles(tab_id)

        if tab_id == "video":
            self.stacked_view.slide_to_index(0)
            self._update_video_view_visibility()
        elif tab_id == "calib":
            self.stacked_view.slide_to_index(1)
        elif tab_id == "exp":
            self.stacked_view.slide_to_index(2)

    def _set_mode(self, mode: str, animate: bool = True):
        self.cfg["camera_mode"] = mode
        self._update_sidebar_buttons()
        self._refresh_presets()
        self._update_camera_dropdown_for_mode()
        self._update_pscam_status()
        self._update_video_view_visibility()
        self._save_settings()

    def _update_sidebar_buttons(self):
        mode = self.cfg.get("camera_mode", "pscam")
        self.card_pscam.set_active(mode == "pscam")
        self.card_webcam.set_active(mode == "webcam")

    def _update_video_view_visibility(self):
        """
        State-aware visibility controller:
        - When DISCONNECTED: The balloon (and its action button) is the ONLY THING displayed.
        - When CONNECTED: The balloon disappears; the options card and Additional Display Options are displayed.
        """
        mode = self.cfg.get("camera_mode", "pscam")
        cams = getattr(self, "camera_list", [])

        if mode == "pscam":
            self.webcam_disconnected_box.setVisible(False)
            self.webcam_card.setVisible(False)

            is_ready = (self._current_pscam_state == "READY")
            if not is_ready:
                self.pscam_card.setVisible(False)
                self.display_card.setVisible(False)
                self.pscam_disconnected_box.setVisible(True)
            else:
                self.pscam_disconnected_box.setVisible(False)
                self.pscam_card.setVisible(True)
                self.display_card.setVisible(True)
        else:
            self.pscam_disconnected_box.setVisible(False)
            self.pscam_card.setVisible(False)

            webcams = [c for c in cams if not c.is_pscam]
            if not webcams and not any(c.is_pscam for c in cams):
                webcams = cams

            if not webcams:
                self.webcam_card.setVisible(False)
                self.display_card.setVisible(False)
                self.webcam_disconnected_box.setVisible(True)
            else:
                self.webcam_disconnected_box.setVisible(False)
                self.webcam_card.setVisible(True)
                self.display_card.setVisible(True)

        self._update_tab_availability()

    def _refresh_presets(self):
        mode = self.cfg.get("camera_mode", "pscam")
        presets = PRESETS_PSCAM if mode == "pscam" else PRESETS_WEBCAM
        current = self.cfg.get("pscam_preset" if mode == "pscam" else "webcam_preset", presets[0])
        w, h, fps = parse_preset(current)
        res_str = f"{w}x{h}"
        fps_str = f"{fps} FPS"

        if hasattr(self, "cb_res") and hasattr(self, "cb_fps"):
            self.cb_res.blockSignals(True)
            self.cb_fps.blockSignals(True)
            idx_r = self.cb_res.findText(res_str)
            self.cb_res.setCurrentIndex(max(0, idx_r))
            idx_f = self.cb_fps.findText(fps_str)
            self.cb_fps.setCurrentIndex(max(0, idx_f))
            self.cb_res.blockSignals(False)
            self.cb_fps.blockSignals(False)

        if hasattr(self, "cb_preset"):
            self.cb_preset.blockSignals(True)
            self.cb_preset.clear()
            self.cb_preset.addItems(presets)
            idx = self.cb_preset.findText(current)
            self.cb_preset.setCurrentIndex(max(0, idx))
            self.cb_preset.blockSignals(False)

    def _update_camera_dropdown_for_mode(self):
        mode = self.cfg.get("camera_mode", "pscam")
        cams = getattr(self, "camera_list", [])

        if self._is_refreshing_cams and not cams:
            msg = "Searching for PlayStation®Camera..." if mode == "pscam" else "Searching for webcams..."
            self.cb_cameras.blockSignals(True)
            self.cb_cameras.clear()
            self.cb_cameras.addItem(msg)
            self.cb_cameras.blockSignals(False)
            if mode == "webcam":
                self.lbl_webcam_conn_title.setText("Searching for webcams...")
                self.lbl_webcam_info.setText("Scanning USB video capture devices...")
                self.btn_refresh_webcam.setEnabled(False)
                self.btn_refresh_webcam.setText("Searching...")
            self._update_video_view_visibility()
            return

        if mode == "pscam":
            ps_cams = [c for c in cams if c.is_pscam]
            if ps_cams:
                self.cfg["camera_index"] = ps_cams[0].index
            elif not cams:
                pass
            else:
                self.cfg["camera_index"] = -1
        else:
            webcams = [c for c in cams if not c.is_pscam]
            if not webcams and not any(c.is_pscam for c in cams):
                webcams = cams

            self.cb_cameras.blockSignals(True)
            self.cb_cameras.clear()
            if webcams:
                for c in webcams:
                    self.cb_cameras.addItem(str(c))
                current_idx = self.cfg.get("camera_index", 0)
                selected_idx = 0
                for i, c in enumerate(webcams):
                    if c.index == current_idx:
                        selected_idx = i
                        break
                self.cb_cameras.setCurrentIndex(selected_idx)
                self.cfg["camera_index"] = webcams[selected_idx].index
            elif not cams:
                pass
            else:
                self.lbl_webcam_icon.setPixmap(self.pix_status_err)
                self.lbl_webcam_conn_title.setText("Webcam not connected")
                self.lbl_webcam_info.setText("Camera disconnected from USB Port")
                self.btn_refresh_webcam.setEnabled(True)
                self.btn_refresh_webcam.setText("Search for Webcams")
                self.cb_cameras.addItem("No webcam found")
                self.cfg["camera_index"] = -1
            self.cb_cameras.blockSignals(False)

        self._update_video_view_visibility()

    def _update_pscam_status(self):
        info = CameraManager.get_ps4_camera_state()
        self._apply_pscam_state(info)

    def _apply_pscam_state(self, ps4_info: dict):
        state = ps4_info.get("state", "DISCONNECTED")
        self._current_pscam_state = state
        running = ps4_info.get("running", False)
        vcam_count = ps4_info.get("vcam_count", 0)

        if state == "NOT_INSTALLED":
            self.lbl_pscam_icon.setPixmap(self.pix_status_err)
            self.lbl_pscam_conn_title.setText("PlayStation Camera not connected")
            self.lbl_pscam_info.setText("Driver Not Installed and Camera disconnected from USB Port")
            self.lbl_pscam_info.setStyleSheet(
                f"font-family: '{self.font_body}'; font-size: 11px; color: {PALETTE['status_err']}; background: transparent; border: none;"
            )
            self.btn_launch_pscam.setEnabled(False)
            self.btn_launch_pscam.setText("Driver Not Installed")

        elif state == "DISCONNECTED":
            self.lbl_pscam_icon.setPixmap(self.pix_status_err)
            self.lbl_pscam_conn_title.setText("PlayStation Camera not connected")
            if running:
                self.lbl_pscam_info.setText("Driver Online but Camera still disconnected from USB Port")
                self.lbl_pscam_info.setStyleSheet(
                    f"font-family: '{self.font_body}'; font-size: 11px; color: {PALETTE['status_warn']}; background: transparent; border: none;"
                )
                self.btn_launch_pscam.setEnabled(False)
                self.btn_launch_pscam.setText("PSCam4Win Driver Active")
            else:
                self.lbl_pscam_info.setText("Driver Offline and Camera disconnected from USB Port")
                self.lbl_pscam_info.setStyleSheet(
                    f"font-family: '{self.font_body}'; font-size: 11px; color: {PALETTE['text_muted']}; background: transparent; border: none;"
                )
                self.btn_launch_pscam.setEnabled(True)
                self.btn_launch_pscam.setText("Start PSCam4Win Driver")

        elif state == "DRIVER_STOPPED":
            self.lbl_pscam_icon.setPixmap(self.pix_status_warn)
            self.lbl_pscam_conn_title.setText("PlayStation Camera detected")
            self.lbl_pscam_info.setText("Camera connected, but PSCam4Win Driver is Offline")
            self.lbl_pscam_info.setStyleSheet(
                f"font-family: '{self.font_body}'; font-size: 11px; color: {PALETTE['status_warn']}; background: transparent; border: none;"
            )
            self.btn_launch_pscam.setEnabled(True)
            self.btn_launch_pscam.setText("Start PSCam4Win Driver")

        elif state == "BOOTLOADER_UPLOADING":
            self.lbl_pscam_icon.setPixmap(self.pix_status_warn)
            self.lbl_pscam_conn_title.setText("PlayStation Camera initializing")
            self.lbl_pscam_info.setText("PlayStation®Camera detected! PSCam4Win uploading USB firmware...")
            self.lbl_pscam_info.setStyleSheet(
                f"font-family: '{self.font_body}'; font-size: 11px; color: {PALETTE['ps_blue']}; background: transparent; border: none;"
            )
            self.btn_launch_pscam.setEnabled(False)
            self.btn_launch_pscam.setText("Uploading Firmware...")

        elif state == "WAITING_VCAM":
            self.lbl_pscam_icon.setPixmap(self.pix_status_warn)
            self.lbl_pscam_conn_title.setText("PlayStation Camera initializing")
            self.lbl_pscam_info.setText("Hardware ready! Initializing DirectShow virtual camera (60 FPS)...")
            self.lbl_pscam_info.setStyleSheet(
                f"font-family: '{self.font_body}'; font-size: 11px; color: {PALETTE['ps_blue']}; background: transparent; border: none;"
            )
            self.btn_launch_pscam.setEnabled(False)
            self.btn_launch_pscam.setText("PSCam4Win Driver Active")

        elif state == "READY":
            self.lbl_pscam_icon.setPixmap(self.pix_status_ok)
            self.lbl_pscam_conn_title.setText("PlayStation Camera connected")
            cams = getattr(self, "camera_list", [])
            ps_cams = [c for c in cams if c.is_pscam]
            if ps_cams:
                cam_idx = ps_cams[0].index
                txt = f"Driver active and PlayStation®Camera connected (Index {cam_idx} • 60 FPS)"
            else:
                txt = f"Driver active and PlayStation®Camera connected ({vcam_count} virtual camera(s) active • 60 FPS)"
            self.lbl_pscam_ready_info.setText(txt)

        self._update_video_view_visibility()

    def _periodic_check(self):
        if self.is_tracking_active:
            return

        ps4_info = CameraManager.get_ps4_camera_state()
        state_key = (ps4_info.get("state"), ps4_info.get("running"))
        if self._last_pscam_state != state_key:
            self._last_pscam_state = state_key
            self._apply_pscam_state(ps4_info)

        current_snapshot = CameraManager.get_hardware_snapshot()
        if current_snapshot != self._last_hw_snapshot:
            self._last_hw_snapshot = current_snapshot
            self._refresh_cameras_async()

    def _refresh_cameras(self):
        self._refresh_cameras_async()

    def _refresh_cameras_async(self):
        if self._is_refreshing_cams or getattr(self, "is_tracking_active", False):
            return
        self._is_refreshing_cams = True

        def worker():
            if getattr(self, "is_tracking_active", False) or getattr(self, "_is_closing", False):
                self._is_refreshing_cams = False
                return
            try:
                cams = CameraManager.enumerate_cameras()
            except Exception:
                cams = []
            if not getattr(self, "_is_closing", False) and not getattr(self, "is_tracking_active", False):
                try:
                    self.cameras_refreshed_signal.emit(cams)
                except RuntimeError:
                    pass
            self._is_refreshing_cams = False

        threading.Thread(target=worker, daemon=True).start()

    @Slot(list)
    def _on_cameras_refreshed(self, cams):
        if getattr(self, "_is_closing", False):
            return
        self._is_refreshing_cams = False
        self.camera_list = cams
        self._update_pscam_status()
        self._update_camera_dropdown_for_mode()

    def _on_camera_selected(self, index: int):
        sel_text = self.cb_cameras.currentText()
        for c in self.camera_list:
            if str(c) == sel_text:
                self.cfg["camera_index"] = c.index
                self._save_settings()
                break

    def _on_webcam_res_or_fps_changed(self):
        if not hasattr(self, "cb_res") or not hasattr(self, "cb_fps"):
            return
        res = self.cb_res.currentText()
        fps = self.cb_fps.currentText()
        preset = f"{res} @ {fps}"
        self.cfg["webcam_preset"] = preset
        if hasattr(self, "cb_preset"):
            self.cb_preset.blockSignals(True)
            idx = self.cb_preset.findText(preset)
            if idx >= 0:
                self.cb_preset.setCurrentIndex(idx)
            self.cb_preset.blockSignals(False)
        self._save_settings()

    def _on_preset_selected(self, index: int = 0):
        mode = self.cfg.get("camera_mode", "pscam")
        if hasattr(self, "cb_preset"):
            preset = self.cb_preset.currentText()
            if mode == "pscam":
                self.cfg["pscam_preset"] = preset
            else:
                self.cfg["webcam_preset"] = preset
                if hasattr(self, "cb_res") and hasattr(self, "cb_fps"):
                    w, h, fps = parse_preset(preset)
                    idx_r = self.cb_res.findText(f"{w}x{h}")
                    if idx_r >= 0:
                        self.cb_res.blockSignals(True)
                        self.cb_res.setCurrentIndex(idx_r)
                        self.cb_res.blockSignals(False)
                    idx_f = self.cb_fps.findText(f"{fps} FPS")
                    if idx_f >= 0:
                        self.cb_fps.blockSignals(True)
                        self.cb_fps.setCurrentIndex(idx_f)
                        self.cb_fps.blockSignals(False)
        self._save_settings()

    def _on_display_options_changed(self):
        self.cfg["show_hud"] = self.chk_hud.isChecked()
        self.cfg["face_follow_enabled"] = self.chk_face.isChecked()
        self._save_settings()

    def _select_calib_preset(self, preset_id: str):
        if preset_id not in CALIB_PRESETS:
            return
        self.current_calib_preset = preset_id
        self.cfg["tracking_preset"] = preset_id
        p = CALIB_PRESETS[preset_id]
        self.cfg["smoothing_alpha"] = p["smoothing_alpha"]
        self.cfg["detection_confidence"] = p["detection_confidence"]

        self.slider_smooth.blockSignals(True)
        self.slider_smooth.setValue(int(p["smoothing_alpha"] * 100))
        self.slider_smooth.blockSignals(False)
        self._update_smooth_label(p["smoothing_alpha"])

        self.slider_conf.blockSignals(True)
        self.slider_conf.setValue(int(p["detection_confidence"] * 100))
        self.slider_conf.blockSignals(False)
        self._update_conf_label(p["detection_confidence"])

        self._update_calib_cards_ui()
        self._save_settings()

    def _update_calib_cards_ui(self):
        for pid, card in self.calib_cards.items():
            card.set_active(pid == self.current_calib_preset)

    def _toggle_advanced_calib(self):
        self.is_adv_calib_open = not self.is_adv_calib_open
        self.adv_drawer.setVisible(self.is_adv_calib_open)
        self.btn_toggle_adv.setText(
            "Hide Advanced Filter Settings ▲" if self.is_adv_calib_open else "Show Advanced Filter Settings ▼"
        )

    def _update_smooth_label(self, val: float):
        v = float(val)
        desc = "Balanced"
        if v < 0.40:
            desc = "Very Smooth (Higher Latency)"
        elif v > 0.65:
            desc = "Ultra Fast (Lower Filtering)"
        self.lbl_smooth.setText(f"Movement Responsiveness (EMA): {v:.2f} — {desc}")

    def _update_conf_label(self, val: float):
        v = float(val)
        self.lbl_conf.setText(f"AI Detection Rigor (Confidence): {int(v * 100)}%")

    def _on_smooth_slider_changed(self, val: int):
        alpha = round(val / 100.0, 2)
        self._update_smooth_label(alpha)
        self.cfg["smoothing_alpha"] = alpha
        self.current_calib_preset = "custom"
        self.cfg["tracking_preset"] = "custom"
        self._update_calib_cards_ui()
        self._save_settings()

    def _on_conf_slider_changed(self, val: int):
        conf = round(val / 100.0, 2)
        self._update_conf_label(conf)
        self.cfg["detection_confidence"] = conf
        self.current_calib_preset = "custom"
        self.cfg["tracking_preset"] = "custom"
        self._update_calib_cards_ui()
        self._save_settings()

    def _launch_pscam_tray(self):
        ok, msg = CameraManager.launch_pscam_tray()
        if ok:
            QMessageBox.information(self, "PSCam4Win", msg)
            self._refresh_cameras_async()
        else:
            QMessageBox.warning(self, "PSCam4Win", msg)

    def _open_dll_folder(self):
        candidates = [
            BASE_DIR / "Kinect for Legacy DLL",
            BASE_DIR.parent / "Kinect for Legacy DLL",
            BASE_DIR / "tools",
        ]
        dll_dir = next((c for c in candidates if (c / "Kinect10.dll").exists() or c.exists()), None)
        if dll_dir and dll_dir.exists():
            os.startfile(str(dll_dir))
        else:
            QMessageBox.information(self, "Kinect10.dll", "Kinect10.dll folder was not found.")

    def _start_tracking(self):
        if self.is_tracking_active:
            return

        mode = self.cfg.get("camera_mode", "pscam")

        if mode == "pscam":
            if CameraManager.is_pscam_installed() and not CameraManager.is_pscam_running():
                ok, msg = CameraManager.launch_pscam_tray()
                if not ok:
                    QMessageBox.critical(self, "Driver Launch Error", msg)
                    return
                time.sleep(1.2)
                self._refresh_cameras()

            ps_cams = [c for c in getattr(self, "camera_list", []) if c.is_pscam]
            cam_idx = self.cfg.get("camera_index", -1)
            is_valid_pscam = any(c.index == cam_idx and c.is_pscam for c in getattr(self, "camera_list", []))

            if not ps_cams or not is_valid_pscam or cam_idx < 0:
                QMessageBox.warning(
                    self,
                    "PlayStation®Camera Not Connected",
                    "PlayStation®Camera was not detected on this computer!\n\n"
                    "• Ensure the PS4 Camera USB 3.0 Adapter is connected.\n"
                    "• Verify that the PSCam4Win driver is running in the Windows system tray."
                )
                return
        else:
            cam_idx = self.cfg.get("camera_index", -1)
            if cam_idx < 0 or not getattr(self, "camera_list", []):
                QMessageBox.warning(
                    self,
                    "No Camera Connected",
                    "No webcam was detected on this computer.\n\n"
                    "Please connect a camera before starting tracking."
                )
                return

        self._save_settings()

        self.is_tracking_active = True
        self.btn_start.setText("TRACKING IN PROGRESS...")
        self.btn_start.setEnabled(False)
        self.showMinimized()

        def tracking_worker():
            success = False
            err_msg = ""
            try:
                success = tracking_session.run_tracking_session(self.cfg)
            except Exception as e:
                err_msg = str(e)
            finally:
                self.tracking_finished_signal.emit(success, err_msg)

        threading.Thread(target=tracking_worker, daemon=True).start()

    @Slot(bool, str)
    def _on_tracking_finished(self, success: bool, err_msg: str):
        self.is_tracking_active = False
        self.btn_start.setText("START TRACKING")
        self.btn_start.setEnabled(True)
        self.showNormal()
        self.activateWindow()
        self._refresh_cameras()

        if not success:
            detail = f"\n\nDetails: {err_msg}" if err_msg else ""
            QMessageBox.critical(
                self,
                "Tracking Initialization Failed",
                f"Could not start tracking with the selected device.{detail}\n\n"
                "• Check if camera is connected to USB.\n"
                "• Verify that PSCam4Win driver is active.\n"
                "• Make sure no other application is locking the camera."
            )

    def _save_settings(self):
        try:
            self.cfg_mgr.save()
        except Exception:
            pass

    def closeEvent(self, event):
        self._is_closing = True
        if hasattr(self, "timer_periodic") and self.timer_periodic is not None:
            self.timer_periodic.stop()
        if hasattr(self, "bridge") and self.bridge is not None:
            self.bridge.close()
        event.accept()


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    window = LegacySensorQtGUI()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
