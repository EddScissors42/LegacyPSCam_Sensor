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
import math
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
    QFrame, QSlider, QMessageBox, QScrollArea, QLineEdit, QGridLayout
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
    generate_ds4_icons_pil,
    generate_tab_icons_pil,
    generate_controller_tab_icon_pil,
    generate_mode_icons_pil,
    generate_status_icons_pil
)
from assets import (
    ICON_PSCAMERA_PATH,
    ICON_ARROW_DOWN_PATH,
    ICON_DUALSHOCK4_PATH,
    ICON_CONTROLLER_PATH
)
from version import WINDOW_TITLE, VERSION_STRING, APP_NAME
from sensor.config_manager import ConfigManager, parse_preset, PRESETS_PSCAM, PRESETS_WEBCAM
from sensor.camera_manager import CameraManager
from sensor.kinect_shared_memory import KinectBridge
from sensor.virtual_phone import get_virtual_phone
from sensor.ds4_controller import get_ds4_controller, find_ds4_devices
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
        self.resize(960, 640)
        self.setMinimumSize(920, 500)
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

        # Initialize Virtual Phone Controller from config
        self.vphone = get_virtual_phone()
        self.vphone.configure(
            host=str(self.cfg.get("virtual_phone_host", "127.0.0.1")),
            port=int(self.cfg.get("virtual_phone_port", 8080)),
            hand=str(self.cfg.get("virtual_phone_hand", "right")),
            sensitivity=float(self.cfg.get("virtual_phone_sensitivity", 1.2)),
            phone_name=str(self.cfg.get("virtual_phone_name", "Legacy PSCam Phone")),
        )
        if self.cfg.get("virtual_phone_enabled", False):
            self.vphone.set_enabled(True)

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

            # Fast UI readout timer for Virtual Phone status & accelerometer (150ms)
            self.timer_vphone = QTimer(self)
            self.timer_vphone.timeout.connect(self._update_vphone_ui_readout)
            self.timer_vphone.start(150)
        else:
            self.timer_periodic = None
            self.timer_vphone = None

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
            p_ds4_act, p_ds4_inact = generate_ds4_icons_pil(target_box=(38, 26), scale=4)
            self.pix_ds4_act = pil_to_qpixmap(p_ds4_act, dpr=4.0)
            self.pix_ds4_inact = pil_to_qpixmap(p_ds4_inact, dpr=4.0)
        except Exception as e:
            print(f"[WARN] Failed to load DS4 icons: {e}")
            self.pix_ds4_act = self.pix_ds4_inact = QPixmap()

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
            p_ctrl_act, p_ctrl_inact = generate_controller_tab_icon_pil(size=(18, 18), scale=4)
            self.pix_ctrl_act = pil_to_qpixmap(p_ctrl_act, dpr=4.0)
            self.pix_ctrl_inact = pil_to_qpixmap(p_ctrl_inact, dpr=4.0)
        except Exception as e:
            print(f"[WARN] Failed to load controller tab icons: {e}")
            self.pix_ctrl_act = self.pix_ctrl_inact = QPixmap()

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
        arrow_url = str(ICON_ARROW_DOWN_PATH).replace("\\", "/")
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
            QComboBox::drop-down:hover {{
                background-color: {PALETTE["blue_pastel_hover"]};
            }}
            QComboBox::down-arrow {{
                image: url("{arrow_url}");
                width: 10px;
                height: 7px;
            }}
            QComboBox QAbstractItemView {{
                background-color: #FFFFFF;
                color: {PALETTE["text_main"]};
                selection-background-color: {PALETTE["ps_blue"]};
                selection-color: #FFFFFF;
                border: 1px solid {PALETTE["input_border"]};
                border-radius: 6px;
            }}
            QLineEdit {{
                background-color: {PALETTE["input_bg"]};
                color: {PALETTE["text_main"]};
                font-family: '{self.font_body}', sans-serif;
                border: 1px solid {PALETTE["input_border"]};
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 12px;
            }}
            QLineEdit:focus {{
                border: 1px solid {PALETTE["ps_blue"]};
                background-color: #FFFFFF;
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
            QScrollArea {{
                background: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                border: none;
                background: transparent;
                width: 8px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: #CBD5E1;
                min-height: 28px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: #94A3B8;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
                background: none;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
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

        lbl_edition = QLabel("ooomaga :O", self.sidebar_frame)
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
            "the most hated one",
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
        sidebar_layout.addSpacing(8)

        # 1.5 Card DualShock 4 (with supersampled icon)
        self.card_ds4 = DeviceNavCard(
            "DualShock 4",
            "⚠️ EXPERIMENTAL",
            self.font_heading,
            self.font_body,
            self.sidebar_frame
        )
        self.card_ds4.set_icons(self.pix_ds4_act, self.pix_ds4_inact)
        self.card_ds4.clicked.connect(lambda: self._set_mode("ds4"))
        sidebar_layout.addWidget(self.card_ds4)
        sidebar_layout.addSpacing(14)

        # 1.6 Quick Action: Open Kinect10.dll folder
        self.btn_dll_folder = QPushButton("Open Kinect10.dll Folder", self.sidebar_frame)
        self.btn_dll_folder.setProperty("class", "btn_secondary")
        self.btn_dll_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_dll_folder.clicked.connect(self._open_dll_folder)
        sidebar_layout.addWidget(self.btn_dll_folder)
        sidebar_layout.addSpacing(6)

        lbl_dll_tip = QLabel("Copy Kinect10.dll to the game folder\n(only for Legacy Offline PC).", self.sidebar_frame)
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

        self.btn_tab_controller = QPushButton("  Controller Settings", self.content_widget)
        self.btn_tab_controller.setFixedSize(175, 42)
        self.btn_tab_controller.setIcon(QIcon(self.pix_ctrl_act))
        self.btn_tab_controller.setIconSize(QSize(18, 18))
        self.btn_tab_controller.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_tab_controller.clicked.connect(lambda: self._switch_tab("controller"))
        self.btn_tab_controller.setVisible(False)

        top_nav_layout.addStretch()
        top_nav_layout.addWidget(self.btn_tab_video)
        top_nav_layout.addSpacing(10)
        top_nav_layout.addWidget(self.btn_tab_calib)
        top_nav_layout.addSpacing(10)
        top_nav_layout.addWidget(self.btn_tab_exp)
        top_nav_layout.addWidget(self.btn_tab_controller)
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

        # Build Page 0 (Video), Page 1 (Calibration), Page 2 (Experimental) & Page 3 (DualShock 4)
        self._build_video_view()
        self._build_calib_view()
        self._build_exp_view()
        self._build_ds4_view()

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

    def _build_video_view(self):
        """Constructs Page 0: Video Settings."""
        self.page_video = QWidget()
        layout = QVBoxLayout(self.page_video)
        layout.setContentsMargins(0, 4, 6, 0)
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
        self.webcam_card.setMinimumHeight(280)
        web_conn_layout = QVBoxLayout(self.webcam_card)
        web_conn_layout.setContentsMargins(16, 14, 16, 14)
        web_conn_layout.setSpacing(10)

        lbl_wc_title = QLabel("WEBCAM VIDEO SETTINGS", self.webcam_card)
        lbl_wc_title.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 12px; font-weight: bold; color: {PALETTE['blue_dark']}; background: transparent; border: none;"
        )
        web_conn_layout.addWidget(lbl_wc_title)

        lbl_wc_sub = QLabel("Select your camera device, resolution and target framerate.", self.webcam_card)
        lbl_wc_sub.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 11px; color: {PALETTE['text_muted']}; background: transparent; border: none;"
        )
        web_conn_layout.addWidget(lbl_wc_sub)

        # 1. Row 1: Camera Device (Full width block)
        block_dev = QFrame(self.webcam_card)
        block_dev.setObjectName("settingBlockDev")
        block_dev.setFixedHeight(90)
        block_dev.setStyleSheet(f"""
            QFrame#settingBlockDev {{
                background-color: #FFFFFF;
                border: 1px solid {PALETTE["border_subtle"]};
                border-radius: 10px;
            }}
            QFrame#settingBlockDev:hover {{
                border-color: {PALETTE["input_border"]};
            }}
        """)
        dev_layout = QVBoxLayout(block_dev)
        dev_layout.setContentsMargins(14, 10, 14, 10)
        dev_layout.setSpacing(4)

        lbl_dev_title = QLabel("CAMERA DEVICE", block_dev)
        lbl_dev_title.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['blue_dark']}; background: transparent; border: none;"
        )
        dev_layout.addWidget(lbl_dev_title)

        lbl_dev_sub = QLabel("Active Video Source", block_dev)
        lbl_dev_sub.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 10px; color: {PALETTE['text_muted']}; background: transparent; border: none;"
        )
        dev_layout.addWidget(lbl_dev_sub)

        dev_ctrl_row = QHBoxLayout()
        dev_ctrl_row.setContentsMargins(0, 0, 0, 0)
        dev_ctrl_row.setSpacing(6)

        self.cb_cameras = QComboBox(block_dev)
        self.cb_cameras.setFixedHeight(32)
        self.cb_cameras.currentIndexChanged.connect(self._on_camera_selected)
        dev_ctrl_row.addWidget(self.cb_cameras, stretch=1)

        self.btn_refresh = QPushButton("↻", block_dev)
        self.btn_refresh.setFixedSize(34, 32)
        self.btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh.setToolTip("Scan / Refresh connected webcams")
        self.btn_refresh.setStyleSheet(f"""
            QPushButton {{
                background-color: {PALETTE["blue_pastel"]};
                color: {PALETTE["ps_blue"]};
                font-family: '{self.font_heading}', sans-serif;
                font-size: 15px;
                font-weight: bold;
                border: 1px solid #CBD5E1;
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
        self.btn_refresh.clicked.connect(self._refresh_cameras)
        dev_ctrl_row.addWidget(self.btn_refresh)
        dev_layout.addLayout(dev_ctrl_row)

        web_conn_layout.addWidget(block_dev)

        # 2. Row 2: Resolution & FPS side-by-side blocks below Camera Device
        row_res_fps = QHBoxLayout()
        row_res_fps.setSpacing(10)

        # Block 2: Resolution
        block_res = QFrame(self.webcam_card)
        block_res.setObjectName("settingBlockRes")
        block_res.setFixedHeight(108)
        block_res.setStyleSheet(f"""
            QFrame#settingBlockRes {{
                background-color: #FFFFFF;
                border: 1px solid {PALETTE["border_subtle"]};
                border-radius: 10px;
            }}
            QFrame#settingBlockRes:hover {{
                border-color: {PALETTE["input_border"]};
            }}
        """)
        res_layout = QVBoxLayout(block_res)
        res_layout.setContentsMargins(14, 10, 14, 10)
        res_layout.setSpacing(4)

        lbl_res_title = QLabel("RESOLUTION", block_res)
        lbl_res_title.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['blue_dark']}; background: transparent; border: none;"
        )
        res_layout.addWidget(lbl_res_title)

        lbl_res_sub = QLabel("Sharper picture, but higher CPU usage. The game still receives as 640x480.", block_res)
        lbl_res_sub.setWordWrap(True)
        lbl_res_sub.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 10px; color: {PALETTE['text_muted']}; background: transparent; border: none; line-height: 120%;"
        )
        res_layout.addWidget(lbl_res_sub)

        self.cb_res = QComboBox(block_res)
        self.cb_res.setFixedHeight(32)
        self.cb_res.addItems(["640x480 (Recommended)", "1280x720", "1920x1080"])
        self.cb_res.currentIndexChanged.connect(self._on_webcam_res_or_fps_changed)
        res_layout.addWidget(self.cb_res)
        row_res_fps.addWidget(block_res, stretch=1)

        # Block 3: FPS
        block_fps = QFrame(self.webcam_card)
        block_fps.setObjectName("settingBlockFps")
        block_fps.setFixedHeight(108)
        block_fps.setStyleSheet(f"""
            QFrame#settingBlockFps {{
                background-color: #FFFFFF;
                border: 1px solid {PALETTE["border_subtle"]};
                border-radius: 10px;
            }}
            QFrame#settingBlockFps:hover {{
                border-color: {PALETTE["input_border"]};
            }}
        """)
        fps_layout = QVBoxLayout(block_fps)
        fps_layout.setContentsMargins(14, 10, 14, 10)
        fps_layout.setSpacing(4)

        lbl_fps_title = QLabel("FRAMERATE (FPS)", block_fps)
        lbl_fps_title.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['blue_dark']}; background: transparent; border: none;"
        )
        fps_layout.addWidget(lbl_fps_title)

        lbl_fps_sub = QLabel("Target capture speed. 60 FPS requires camera support and more CPU.", block_fps)
        lbl_fps_sub.setWordWrap(True)
        lbl_fps_sub.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 10px; color: {PALETTE['text_muted']}; background: transparent; border: none; line-height: 120%;"
        )
        fps_layout.addWidget(lbl_fps_sub)

        self.cb_fps = QComboBox(block_fps)
        self.cb_fps.setFixedHeight(32)
        self.cb_fps.addItems(["30 FPS (Recommended)", "60 FPS"])
        self.cb_fps.currentIndexChanged.connect(self._on_webcam_res_or_fps_changed)
        fps_layout.addWidget(self.cb_fps)
        row_res_fps.addWidget(block_fps, stretch=1)

        web_conn_layout.addLayout(row_res_fps)

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
        self.display_card.setMinimumHeight(195)
        disp_layout = QVBoxLayout(self.display_card)
        disp_layout.setContentsMargins(16, 14, 16, 14)
        disp_layout.setSpacing(10)

        lbl_disp_title = QLabel("ADDITIONAL DISPLAY OPTIONS", self.display_card)
        lbl_disp_title.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 12px; font-weight: bold; color: {PALETTE['blue_dark']}; background: transparent; border: none;"
        )
        disp_layout.addWidget(lbl_disp_title)

        lbl_disp_sub = QLabel("Configure camera image rotation and in-game visual overlays.", self.display_card)
        lbl_disp_sub.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 11px; color: {PALETTE['text_muted']}; background: transparent; border: none;"
        )
        disp_layout.addWidget(lbl_disp_sub)

        # Block: Camera Orientation
        block_orient = QFrame(self.display_card)
        block_orient.setObjectName("settingBlockOrient")
        block_orient.setFixedHeight(92)
        block_orient.setStyleSheet(f"""
            QFrame#settingBlockOrient {{
                background-color: #FFFFFF;
                border: 1px solid {PALETTE["border_subtle"]};
                border-radius: 10px;
            }}
            QFrame#settingBlockOrient:hover {{
                border-color: {PALETTE["input_border"]};
            }}
        """)
        orient_layout = QVBoxLayout(block_orient)
        orient_layout.setContentsMargins(14, 10, 14, 10)
        orient_layout.setSpacing(4)

        lbl_orient_title = QLabel("CAMERA ORIENTATION", block_orient)
        lbl_orient_title.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['blue_dark']}; background: transparent; border: none;"
        )
        orient_layout.addWidget(lbl_orient_title)

        lbl_orient_sub = QLabel("Rotation angle if your camera is physically mounted sideways or inverted.", block_orient)
        lbl_orient_sub.setWordWrap(True)
        lbl_orient_sub.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 10px; color: {PALETTE['text_muted']}; background: transparent; border: none;"
        )
        orient_layout.addWidget(lbl_orient_sub)

        self.cb_orient = QComboBox(block_orient)
        self.cb_orient.setFixedHeight(32)
        self.cb_orient.addItems(["0° (Default)", "90° (Clockwise)", "180° (Inverted)", "270° (Counter-clockwise)"])
        curr_orient = self.cfg.get("camera_orientation", 0)
        orient_map = {0: 0, 90: 1, 180: 2, 270: 3}
        self.cb_orient.setCurrentIndex(orient_map.get(curr_orient, 0))
        self.cb_orient.currentIndexChanged.connect(self._on_orientation_changed)
        orient_layout.addWidget(self.cb_orient)

        disp_layout.addWidget(block_orient)

        self.chk_hud = QCheckBox("Display HUD Overlay in Tracking Window (FPS, IPC & Shortcuts)", self.display_card)
        self.chk_hud.setChecked(self.cfg.get("show_hud", True))
        self.chk_hud.stateChanged.connect(self._on_display_options_changed)
        disp_layout.addWidget(self.chk_hud)

        layout.addWidget(self.display_card)
        layout.addStretch()

        self.scroll_video = self._create_scroll_page(self.page_video)
        self.stacked_view.addWidget(self.scroll_video)

    def _build_calib_view(self):
        """Constructs Page 1: Calibration & Motion Profile."""
        self.page_calib = QWidget()
        layout = QVBoxLayout(self.page_calib)
        layout.setContentsMargins(0, 4, 6, 0)
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

        self.scroll_calib = self._create_scroll_page(self.page_calib)
        self.stacked_view.addWidget(self.scroll_calib)
        self._update_calib_cards_ui()

    def _build_exp_view(self):
        """Constructs Page 2: Experimental Features."""
        self.page_exp = QWidget()
        layout = QVBoxLayout(self.page_exp)
        layout.setContentsMargins(0, 4, 6, 0)
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

        # Warning Callout Box
        warn_box = QFrame(exp_card)
        warn_box.setStyleSheet("""
            QFrame {
                background-color: #FEF3C7;
                border: 1px solid #FCD34D;
                border-radius: 8px;
            }
        """)
        warn_layout = QHBoxLayout(warn_box)
        warn_layout.setContentsMargins(12, 10, 12, 10)
        warn_layout.setSpacing(10)

        lbl_warn_icon = QLabel("⚠️", warn_box)
        lbl_warn_icon.setStyleSheet("font-size: 16px; background: transparent; border: none;")
        warn_layout.addWidget(lbl_warn_icon, alignment=Qt.AlignmentFlag.AlignTop)

        lbl_warn_text = QLabel(
            "CAUTION: Features here are under constant testing and development. "
            "They may not work as intended or may fail to function entirely, which could affect your gameplay experience.",
            warn_box
        )
        lbl_warn_text.setWordWrap(True)
        lbl_warn_text.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 11px; font-weight: 500; color: #92400E; background: transparent; border: none;"
        )
        warn_layout.addWidget(lbl_warn_text, stretch=1)
        exp_layout.addWidget(warn_box)

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

        # Virtual Phone Controller Feature Box (Single Block)
        vphone_box = QFrame(exp_card)
        vphone_box.setStyleSheet(f"""
            QFrame {{
                background-color: {PALETTE["input_bg"]};
                border: 1px solid {PALETTE["border_subtle"]};
                border-radius: 8px;
            }}
        """)
        vp_layout = QVBoxLayout(vphone_box)
        vp_layout.setContentsMargins(14, 12, 14, 12)
        vp_layout.setSpacing(8)

        self.chk_vphone_enabled = QCheckBox("Virtual Phone Controller (JD Controller via Camera)", vphone_box)
        self.chk_vphone_enabled.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 13px; font-weight: bold; color: {PALETTE['text_main']};"
        )
        self.chk_vphone_enabled.setChecked(bool(self.cfg.get("virtual_phone_enabled", False)))
        self.chk_vphone_enabled.stateChanged.connect(self._on_vphone_toggle_changed)
        vp_layout.addWidget(self.chk_vphone_enabled)

        lbl_vp_desc = QLabel(
            "Emulates a smartphone connected to Just Dance via WebSocket/TLS (/smartphone) and converts your hand motion "
            "in the camera into 3D accelerometer commands for songs that only support hand controllers.",
            vphone_box
        )
        lbl_vp_desc.setWordWrap(True)
        lbl_vp_desc.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 11px; color: {PALETTE['text_muted']}; background: transparent; border: none;"
        )
        vp_layout.addWidget(lbl_vp_desc)

        # Status & Controls Container (Hidden when Virtual Phone is disabled)
        self.vphone_details_frame = QFrame(vphone_box)
        self.vphone_details_frame.setObjectName("vphone_details_frame")
        self.vphone_details_frame.setStyleSheet(f"""
            QFrame#vphone_details_frame {{
                background-color: {PALETTE["bg_card"]};
                border: 1px solid {PALETTE["border_subtle"]};
                border-radius: 8px;
            }}
        """)
        vp_det_layout = QVBoxLayout(self.vphone_details_frame)
        vp_det_layout.setContentsMargins(14, 12, 14, 12)
        vp_det_layout.setSpacing(10)

        # Status readout
        self.lbl_vphone_status = QLabel("Status: Disabled", self.vphone_details_frame)
        self.lbl_vphone_status.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['text_muted']}; background: transparent; border: none;"
        )
        vp_det_layout.addWidget(self.lbl_vphone_status)

        # Live Accel readout (only visible while tracking is active)
        self.lbl_vphone_accel = QLabel("3D Accelerometer: X: +0.00G | Y: -1.00G | Z: +0.00G (0.0 m/s)", self.vphone_details_frame)
        self.lbl_vphone_accel.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['ps_blue']}; background: transparent; border: none;"
        )
        self.lbl_vphone_accel.setVisible(getattr(self, "is_tracking_active", False))
        vp_det_layout.addWidget(self.lbl_vphone_accel)

        # Hidden Host/Port fields (preserved for logic and persistence without UI clutter)
        self.txt_vphone_host = QLineEdit(str(self.cfg.get("virtual_phone_host", "127.0.0.1")), self)
        self.txt_vphone_host.setVisible(False)
        self.txt_vphone_port = QLineEdit(str(self.cfg.get("virtual_phone_port", 8080)), self)
        self.txt_vphone_port.setVisible(False)

        # Action buttons row (Reconnect, Auto-Find, Skip Finish, Record Log)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        btn_outline_style = f"""
            QPushButton {{
                background-color: #FFFFFF;
                color: {PALETTE["text_main"]};
                font-family: '{self.font_heading}', sans-serif;
                font-size: 11px;
                font-weight: bold;
                border: 1px solid {PALETTE["tab_gray_border"]};
                border-radius: 6px;
                padding: 6px 14px;
            }}
            QPushButton:hover {{
                background-color: {PALETTE["tab_gray_hover"]};
                border-color: {PALETTE["ps_blue"]};
                color: {PALETTE["ps_blue"]};
            }}
            QPushButton:pressed {{
                background-color: {PALETTE["tab_gray_act"]};
            }}
            QPushButton:disabled {{
                background-color: #F8FAFC;
                color: {PALETTE["text_muted"]};
                border-color: {PALETTE["border_subtle"]};
            }}
        """
        self._btn_vphone_outline_style = btn_outline_style

        self.btn_vphone_reconnect = QPushButton("Reconnect", self.vphone_details_frame)
        self.btn_vphone_reconnect.setStyleSheet(btn_outline_style)
        self.btn_vphone_reconnect.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_vphone_reconnect.clicked.connect(self._on_vphone_reconnect_clicked)

        self.btn_vphone_discover = QPushButton("Auto-Find", self.vphone_details_frame)
        self.btn_vphone_discover.setStyleSheet(btn_outline_style)
        self.btn_vphone_discover.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_vphone_discover.clicked.connect(self._on_vphone_discover_clicked)

        self.btn_vphone_ftue = QPushButton("Skip Finish", self.vphone_details_frame)
        self.btn_vphone_ftue.setStyleSheet(btn_outline_style)
        self.btn_vphone_ftue.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_vphone_ftue.setToolTip("for Just Dance 2022 phone tutorial")
        self.btn_vphone_ftue.clicked.connect(self._on_skip_finish_clicked)

        self.btn_vphone_log = QPushButton("Record Log", self.vphone_details_frame)
        self.btn_vphone_log.setStyleSheet(btn_outline_style)
        self.btn_vphone_log.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_vphone_log.setToolTip("Records accelerometer telemetry (CSV) for analysis and comparison with real phones")
        self.btn_vphone_log.clicked.connect(self._toggle_vphone_logging)

        btn_row.addWidget(self.btn_vphone_reconnect)
        btn_row.addWidget(self.btn_vphone_discover)
        btn_row.addWidget(self.btn_vphone_ftue)
        btn_row.addWidget(self.btn_vphone_log)
        btn_row.addStretch()
        vp_det_layout.addLayout(btn_row)

        # Settings row: Hand Selection & Sensitivity Slider
        settings_row = QHBoxLayout()
        settings_row.setSpacing(16)

        # Hand block
        hand_box = QVBoxLayout()
        hand_box.setSpacing(4)
        lbl_hand = QLabel("TRACKED HAND", self.vphone_details_frame)
        lbl_hand.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['text_main']}; background: transparent; border: none;"
        )
        self.cb_vphone_hand = QComboBox(self.vphone_details_frame)
        self.cb_vphone_hand.addItems(["Right Hand (Default)", "Left Hand"])
        saved_hand = str(self.cfg.get("virtual_phone_hand", "right")).lower()
        self.cb_vphone_hand.setCurrentIndex(1 if saved_hand == "left" else 0)
        self.cb_vphone_hand.setStyleSheet(f"""
            QComboBox {{
                background-color: #FFFFFF;
                color: {PALETTE['text_main']};
                font-family: '{self.font_body}', sans-serif;
                border: 1px solid {PALETTE['tab_gray_border']};
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 11px;
                font-weight: 500;
                min-width: 160px;
            }}
            QComboBox:hover {{
                border-color: {PALETTE['ps_blue']};
            }}
        """)
        self.cb_vphone_hand.currentIndexChanged.connect(self._on_vphone_config_changed)
        hand_box.addWidget(lbl_hand)
        hand_box.addWidget(self.cb_vphone_hand)

        # Sensitivity block
        sens_box = QVBoxLayout()
        sens_box.setSpacing(4)
        sens_val = float(self.cfg.get("virtual_phone_sensitivity", 1.2))
        self.lbl_vphone_sens = QLabel(f"SENSITIVITY: {sens_val:.2f}x (DEFAULT: 1.20x)", self.vphone_details_frame)
        self.lbl_vphone_sens.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['text_main']}; background: transparent; border: none;"
        )

        self.slider_vphone_sens = QSlider(Qt.Orientation.Horizontal, self.vphone_details_frame)
        self.slider_vphone_sens.setRange(40, 250)
        self.slider_vphone_sens.setValue(int(round(sens_val * 100)))
        self.slider_vphone_sens.valueChanged.connect(self._on_vphone_sens_changed)
        sens_box.addWidget(self.lbl_vphone_sens)
        sens_box.addWidget(self.slider_vphone_sens)

        settings_row.addLayout(hand_box, stretch=0)
        settings_row.addLayout(sens_box, stretch=1)
        vp_det_layout.addLayout(settings_row)

        vp_layout.addWidget(self.vphone_details_frame)
        self.vphone_details_frame.setVisible(self.chk_vphone_enabled.isChecked())

        exp_layout.addWidget(vphone_box)
        layout.addWidget(exp_card)
        layout.addStretch()

        self.scroll_exp = self._create_scroll_page(self.page_exp)
        self.stacked_view.addWidget(self.scroll_exp)
        self._update_vphone_ui_readout()

    def _build_ds4_view(self):
        """Constructs Page 3: DualShock 4 [EXPERIMENTAL] Controller Settings."""
        self.page_ds4 = QWidget()
        layout = QVBoxLayout(self.page_ds4)
        layout.setContentsMargins(0, 4, 6, 0)
        layout.setSpacing(12)

        ds4_card = QFrame(self.page_ds4)
        ds4_card.setProperty("class", "card")
        ds4_layout = QVBoxLayout(ds4_card)
        ds4_layout.setContentsMargins(16, 16, 16, 16)
        ds4_layout.setSpacing(14)

        lbl_title = QLabel("DUALSHOCK® 4 CONTROLLER SETTINGS", ds4_card)
        lbl_title.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 12px; font-weight: bold; color: {PALETTE['blue_dark']}; background: transparent; border: none;"
        )
        ds4_layout.addWidget(lbl_title)

        # Warning Callout Box (Exact warning requested by user)
        warn_box = QFrame(ds4_card)
        warn_box.setStyleSheet("""
            QFrame {
                background-color: #FEF3C7;
                border: 1px solid #FCD34D;
                border-radius: 8px;
            }
        """)
        warn_layout = QHBoxLayout(warn_box)
        warn_layout.setContentsMargins(14, 12, 14, 12)
        warn_layout.setSpacing(12)

        lbl_warn_icon = QLabel("⚠️", warn_box)
        lbl_warn_icon.setStyleSheet("font-size: 20px; background: transparent; border: none;")
        warn_layout.addWidget(lbl_warn_icon, alignment=Qt.AlignmentFlag.AlignTop)

        lbl_warn_text = QLabel(
            "CAUTION: Playing with a DualShock 4 is for lunatics! Only do this if you want to do "
            "wild experiments, and do not forget to hold the controller so f*ing firmly! "
            "This feature is ultra-experimental and may not be supported in future versions. (maybe...)\n\n"
            "This controller mode automatically enables the virtual phone feature, and may not work as intended. Use at your own risk.",
            warn_box
        )
        lbl_warn_text.setWordWrap(True)
        lbl_warn_text.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 11px; font-weight: 500; color: #92400E; background: transparent; border: none; line-height: 1.4;"
        )
        warn_layout.addWidget(lbl_warn_text, stretch=1)
        ds4_layout.addWidget(warn_box)

        # Disconnected Balloon (Shown when DualShock 4 is not connected)
        self.ds4_disconnected_box = QWidget(ds4_card)
        ds4_disc_layout = QVBoxLayout(self.ds4_disconnected_box)
        ds4_disc_layout.setContentsMargins(0, 0, 0, 0)
        ds4_disc_layout.setSpacing(10)

        self.ds4_status_card = QFrame(self.ds4_disconnected_box)
        self.ds4_status_card.setProperty("class", "status_balloon")
        card_layout = QHBoxLayout(self.ds4_status_card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        card_layout.setSpacing(14)

        self.lbl_ds4_icon = QLabel(self.ds4_status_card)
        self.lbl_ds4_icon.setPixmap(self.pix_status_err)
        self.lbl_ds4_icon.setFixedSize(38, 38)
        self.lbl_ds4_icon.setStyleSheet("background: transparent; border: none;")
        card_layout.addWidget(self.lbl_ds4_icon)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self.lbl_ds4_conn_title = QLabel("DualShock® 4 not connected", self.ds4_status_card)
        self.lbl_ds4_conn_title.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 14px; font-weight: bold; color: {PALETTE['text_main']}; background: transparent; border: none;"
        )
        self.lbl_ds4_conn_info = QLabel("No Wireless Controller detected via Bluetooth HID", self.ds4_status_card)
        self.lbl_ds4_conn_info.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 11px; color: {PALETTE['text_muted']}; background: transparent; border: none;"
        )
        text_col.addWidget(self.lbl_ds4_conn_title)
        text_col.addWidget(self.lbl_ds4_conn_info)
        card_layout.addLayout(text_col, stretch=1)
        ds4_disc_layout.addWidget(self.ds4_status_card)
        ds4_layout.addWidget(self.ds4_disconnected_box)

        # Controller Details & Settings Frame (Shown when DualShock 4 is connected)
        self.ds4_info_frame = QFrame(ds4_card)
        self.ds4_info_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {PALETTE["bg_card"]};
                border: 1px solid {PALETTE["border_subtle"]};
                border-radius: 8px;
            }}
        """)
        ds4_info_layout = QVBoxLayout(self.ds4_info_frame)
        ds4_info_layout.setContentsMargins(16, 14, 16, 14)
        ds4_info_layout.setSpacing(12)

        self.lbl_ds4_status = QLabel("Status: Controller Ready for Setup (Awaiting Technical Driver Integration)", self.ds4_info_frame)
        self.lbl_ds4_status.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['ps_blue']}; background: transparent; border: none;"
        )
        ds4_info_layout.addWidget(self.lbl_ds4_status)

        # Settings row: Tracked Hand & Sensitivity
        settings_row = QHBoxLayout()
        settings_row.setSpacing(16)

        # Hand selection block
        hand_box = QVBoxLayout()
        hand_box.setSpacing(4)
        lbl_hand = QLabel("TRACKED HAND (HOLDING CONTROLLER)", self.ds4_info_frame)
        lbl_hand.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: #0F172A; background: transparent; border: none;"
        )
        self.cb_ds4_hand = QComboBox(self.ds4_info_frame)
        self.cb_ds4_hand.addItem("Right Hand (Standard)")
        self.cb_ds4_hand.addItem("Left Hand")
        self.cb_ds4_hand.setStyleSheet(f"""
            QComboBox {{
                background-color: #FFFFFF;
                color: #0F172A;
                font-family: '{self.font_body}', sans-serif;
                border: 1px solid {PALETTE['tab_gray_border']};
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 11px;
                font-weight: 500;
                min-width: 170px;
            }}
            QComboBox:hover {{
                border-color: {PALETTE['ps_blue']};
            }}
        """)
        hand_box.addWidget(lbl_hand)
        hand_box.addWidget(self.cb_ds4_hand)

        # Sensitivity block
        sens_box = QVBoxLayout()
        sens_box.setSpacing(4)
        lbl_sens = QLabel("HARDWARE ACCELEROMETER GAIN", self.ds4_info_frame)
        lbl_sens.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: #0F172A; background: transparent; border: none;"
        )
        self.cb_ds4_sens = QComboBox(self.ds4_info_frame)
        self.cb_ds4_sens.addItem("1.00x (Standard Hardware Scale)")
        self.cb_ds4_sens.addItem("1.25x (High Energy / Fast Dances)")
        self.cb_ds4_sens.addItem("0.85x (Smooth / Gentle Gestures)")
        self.cb_ds4_sens.setStyleSheet(f"""
            QComboBox {{
                background-color: #FFFFFF;
                color: #0F172A;
                font-family: '{self.font_body}', sans-serif;
                border: 1px solid {PALETTE['tab_gray_border']};
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 11px;
                font-weight: 500;
                min-width: 190px;
            }}
            QComboBox:hover {{
                border-color: {PALETTE['ps_blue']};
            }}
        """)
        sens_box.addWidget(lbl_sens)
        sens_box.addWidget(self.cb_ds4_sens)

        current_hand = self.cfg.get("ds4_hand", "right").lower()
        self.cb_ds4_hand.setCurrentIndex(0 if current_hand == "right" else 1)
        self.cb_ds4_hand.currentIndexChanged.connect(self._on_ds4_hand_changed)

        current_sens = float(self.cfg.get("ds4_sensitivity", 1.0))
        if abs(current_sens - 1.25) < 0.05:
            self.cb_ds4_sens.setCurrentIndex(1)
        elif abs(current_sens - 0.85) < 0.05:
            self.cb_ds4_sens.setCurrentIndex(2)
        else:
            self.cb_ds4_sens.setCurrentIndex(0)
        self.cb_ds4_sens.currentIndexChanged.connect(self._on_ds4_sens_changed)

        settings_row.addLayout(hand_box, stretch=0)
        settings_row.addLayout(sens_box, stretch=1)
        ds4_info_layout.addLayout(settings_row)

        # Real-time Telemetry Readout
        self.lbl_ds4_accel = QLabel("3D Accelerometer: Searching for controller...", self.ds4_info_frame)
        self.lbl_ds4_accel.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 11px; font-weight: 600; color: {PALETTE['text_main']}; background: transparent; border: none;"
        )
        ds4_info_layout.addWidget(self.lbl_ds4_accel)

        # Quick Action Buttons: Test Rumble, Reconnect & Skip Finish
        actions_row = QHBoxLayout()
        actions_row.setSpacing(10)

        self.btn_ds4_rumble = QPushButton("Test Rumble Vibration", self.ds4_info_frame)
        self.btn_ds4_rumble.setStyleSheet(f"""
            QPushButton {{
                background-color: #FFFFFF;
                color: {PALETTE["ps_blue"]};
                font-family: '{self.font_heading}', sans-serif;
                font-size: 11px;
                font-weight: bold;
                border: 1px solid {PALETTE["tab_gray_border"]};
                border-radius: 6px;
                padding: 6px 14px;
            }}
            QPushButton:hover {{
                border-color: {PALETTE["ps_blue"]};
                background-color: #F8FAFC;
            }}
        """)
        self.btn_ds4_rumble.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ds4_rumble.clicked.connect(self._test_ds4_rumble)

        self.btn_ds4_reconnect = QPushButton("Reconnect Controller", self.ds4_info_frame)
        self.btn_ds4_reconnect.setStyleSheet(f"""
            QPushButton {{
                background-color: #FFFFFF;
                color: #0F172A;
                font-family: '{self.font_heading}', sans-serif;
                font-size: 11px;
                font-weight: bold;
                border: 1px solid {PALETTE["tab_gray_border"]};
                border-radius: 6px;
                padding: 6px 14px;
            }}
            QPushButton:hover {{
                border-color: {PALETTE["ps_blue"]};
                background-color: #F8FAFC;
            }}
        """)
        self.btn_ds4_reconnect.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ds4_reconnect.clicked.connect(self._reconnect_ds4)

        self.btn_ds4_skip_finish = QPushButton("Skip Finish", self.ds4_info_frame)
        self.btn_ds4_skip_finish.setStyleSheet(f"""
            QPushButton {{
                background-color: #FFFFFF;
                color: #0F172A;
                font-family: '{self.font_heading}', sans-serif;
                font-size: 11px;
                font-weight: bold;
                border: 1px solid {PALETTE["tab_gray_border"]};
                border-radius: 6px;
                padding: 6px 14px;
            }}
            QPushButton:hover {{
                border-color: {PALETTE["ps_blue"]};
                background-color: #F8FAFC;
            }}
        """)
        self.btn_ds4_skip_finish.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ds4_skip_finish.setToolTip("for Just Dance 2022 phone tutorial")
        self.btn_ds4_skip_finish.clicked.connect(self._on_skip_finish_clicked)

        actions_row.addWidget(self.btn_ds4_rumble)
        actions_row.addWidget(self.btn_ds4_reconnect)
        actions_row.addWidget(self.btn_ds4_skip_finish)
        actions_row.addStretch()
        ds4_info_layout.addLayout(actions_row)

        # Instruction details
        lbl_instructions = QLabel(
            "• Hold the DualShock 4 in your active dancing hand with the light bar pointing forward.\n"
            "• Pair wirelessly via Windows Bluetooth settings.\n"
            "• When started, the controller's internal 6-axis IMU will stream physical 3D G-force data directly to Just Dance via the Virtual Phone scoring bridge.",
            self.ds4_info_frame
        )
        lbl_instructions.setWordWrap(True)
        lbl_instructions.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 11px; color: {PALETTE['text_muted']}; background: transparent; border: none;"
        )
        ds4_info_layout.addWidget(lbl_instructions)

        ds4_layout.addWidget(self.ds4_info_frame)

        # Initial visibility: disconnected balloon shown, details hidden until connected
        self.ds4_disconnected_box.setVisible(True)
        self.ds4_info_frame.setVisible(False)
        layout.addWidget(ds4_card)
        layout.addStretch()

        self.scroll_ds4 = self._create_scroll_page(self.page_ds4)
        self.stacked_view.addWidget(self.scroll_ds4)

    # =========================================================================
    # UI STATE MANAGEMENT & VISIBILITY
    # =========================================================================
    def is_camera_accessible(self) -> bool:
        """Returns True if the currently selected camera device is connected and accessible."""
        mode = self.cfg.get("camera_mode", "pscam")
        if mode == "ds4":
            return True
        elif mode == "pscam":
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
        """Disables and grays out the Calibration and Experimental tabs when the camera is not connected/accessible."""
        accessible = self.is_camera_accessible()
        if not accessible:
            self.btn_tab_calib.setEnabled(False)
            self.btn_tab_calib.setCursor(Qt.CursorShape.ForbiddenCursor)
            if hasattr(self, "btn_tab_exp"):
                self.btn_tab_exp.setEnabled(False)
                self.btn_tab_exp.setCursor(Qt.CursorShape.ForbiddenCursor)
            if self.active_tab in ("calib", "exp"):
                self._switch_tab("video")
            else:
                self.btn_tab_calib.setStyleSheet(self._disabled_tab_css())
                self.btn_tab_calib.setIcon(QIcon(self.pix_slid_disabled))
                if hasattr(self, "btn_tab_exp"):
                    self.btn_tab_exp.setStyleSheet(self._disabled_tab_css())
                    self.btn_tab_exp.setIcon(QIcon(self.pix_lab_inact))
        else:
            self.btn_tab_calib.setEnabled(True)
            self.btn_tab_calib.setCursor(Qt.CursorShape.PointingHandCursor)
            if hasattr(self, "btn_tab_exp"):
                self.btn_tab_exp.setEnabled(True)
                self.btn_tab_exp.setCursor(Qt.CursorShape.PointingHandCursor)
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

        # Experimental Tab (Access-Gated for camera modes)
        if hasattr(self, "btn_tab_exp"):
            if not accessible:
                self.btn_tab_exp.setEnabled(False)
                self.btn_tab_exp.setCursor(Qt.CursorShape.ForbiddenCursor)
                self.btn_tab_exp.setStyleSheet(self._disabled_tab_css())
                self.btn_tab_exp.setIcon(QIcon(self.pix_lab_inact))
            else:
                self.btn_tab_exp.setEnabled(True)
                self.btn_tab_exp.setCursor(Qt.CursorShape.PointingHandCursor)
                if tab_id == "exp":
                    self.btn_tab_exp.setStyleSheet(act_css)
                    self.btn_tab_exp.setIcon(QIcon(self.pix_lab_act))
                else:
                    self.btn_tab_exp.setStyleSheet(inact_css)
                    self.btn_tab_exp.setIcon(QIcon(self.pix_lab_inact))

        # Controller Settings Tab (DualShock 4 Mode)
        if hasattr(self, "btn_tab_controller"):
            if tab_id == "controller":
                self.btn_tab_controller.setStyleSheet(act_css)
                self.btn_tab_controller.setIcon(QIcon(self.pix_ctrl_act))
            else:
                self.btn_tab_controller.setStyleSheet(inact_css)
                self.btn_tab_controller.setIcon(QIcon(self.pix_ctrl_inact))

    def _switch_tab(self, tab_id: str):
        if tab_id in ("calib", "exp") and not self.is_camera_accessible():
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
        elif tab_id == "controller":
            self.stacked_view.slide_to_index(3)

    def _set_mode(self, mode: str, animate: bool = True):
        self.cfg["camera_mode"] = mode
        self._update_sidebar_buttons()
        if mode == "ds4":
            if hasattr(self, "btn_tab_video"):
                self.btn_tab_video.setVisible(False)
            if hasattr(self, "btn_tab_calib"):
                self.btn_tab_calib.setVisible(False)
            if hasattr(self, "btn_tab_exp"):
                self.btn_tab_exp.setVisible(False)
            if hasattr(self, "btn_tab_controller"):
                self.btn_tab_controller.setVisible(True)
            self._switch_tab("controller")
            if hasattr(self, "btn_start"):
                self.btn_start.setText("START CONTROLLER (DS4)")
            self._update_ds4_ui_readout()
            threading.Thread(
                target=lambda: (get_ds4_controller().connect(), QtCore.QMetaObject.invokeMethod(self, "_finish_ds4_reconnect", Qt.ConnectionType.QueuedConnection)),
                daemon=True
            ).start()
        else:
            if hasattr(self, "btn_tab_controller"):
                self.btn_tab_controller.setVisible(False)
            if hasattr(self, "btn_tab_video"):
                self.btn_tab_video.setVisible(True)
            if hasattr(self, "btn_tab_calib"):
                self.btn_tab_calib.setVisible(True)
            if hasattr(self, "btn_tab_exp"):
                self.btn_tab_exp.setVisible(True)
            self._refresh_presets()
            self._update_camera_dropdown_for_mode()
            self._update_pscam_status()
            self._update_video_view_visibility()
            self._switch_tab("video")
            if hasattr(self, "btn_start"):
                self.btn_start.setText("START TRACKING")
        self._save_settings()

    def _update_sidebar_buttons(self):
        mode = self.cfg.get("camera_mode", "pscam")
        self.card_pscam.set_active(mode == "pscam")
        self.card_webcam.set_active(mode == "webcam")
        if hasattr(self, "card_ds4"):
            self.card_ds4.set_active(mode == "ds4")

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

            if not webcams and not self._is_refreshing_cams:
                self.webcam_card.setVisible(False)
                self.display_card.setVisible(False)
                self.webcam_disconnected_box.setVisible(True)
            elif webcams:
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
            idx_r = self.cb_res.findText(res_str, Qt.MatchFlag.MatchStartsWith)
            self.cb_res.setCurrentIndex(max(0, idx_r))
            idx_f = self.cb_fps.findText(fps_str, Qt.MatchFlag.MatchStartsWith)
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

        if self._is_refreshing_cams and not cams and not getattr(self, "camera_list", []):
            msg = "Searching for PlayStation®Camera..." if mode == "pscam" else "Searching for webcams..."
            self.cb_cameras.blockSignals(True)
            self.cb_cameras.clear()
            self.cb_cameras.addItem(msg)
            self.cb_cameras.blockSignals(False)
            if mode == "webcam":
                self.lbl_webcam_conn_title.setText("Searching for webcams...")
                self.lbl_webcam_info.setText("Scanning USB video capture devices...")
                if hasattr(self, "btn_refresh_webcam"):
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
        if hasattr(self, "btn_refresh"):
            self.btn_refresh.setEnabled(False)
            self.btn_refresh.setText("…")
        if hasattr(self, "btn_refresh_webcam"):
            self.btn_refresh_webcam.setEnabled(False)
            self.btn_refresh_webcam.setText("Searching...")

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
        if hasattr(self, "btn_refresh"):
            self.btn_refresh.setEnabled(True)
            self.btn_refresh.setText("↻")
        if hasattr(self, "btn_refresh_webcam"):
            self.btn_refresh_webcam.setEnabled(True)
            self.btn_refresh_webcam.setText("Search for Webcams")
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
        res = self.cb_res.currentText().split()[0]
        fps_val = self.cb_fps.currentText().split()[0]
        preset = f"{res} @ {fps_val} FPS"
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
                    idx_r = self.cb_res.findText(f"{w}x{h}", Qt.MatchFlag.MatchStartsWith)
                    if idx_r >= 0:
                        self.cb_res.blockSignals(True)
                        self.cb_res.setCurrentIndex(idx_r)
                        self.cb_res.blockSignals(False)
                    idx_f = self.cb_fps.findText(f"{fps} FPS", Qt.MatchFlag.MatchStartsWith)
                    if idx_f >= 0:
                        self.cb_fps.blockSignals(True)
                        self.cb_fps.setCurrentIndex(idx_f)
                        self.cb_fps.blockSignals(False)
        self._save_settings()

    def _on_display_options_changed(self):
        self.cfg["show_hud"] = self.chk_hud.isChecked()
        self.cfg["face_follow_enabled"] = self.chk_face.isChecked()
        self._save_settings()

    def _on_orientation_changed(self, index: int):
        orientations = [0, 90, 180, 270]
        angle = orientations[index] if 0 <= index < len(orientations) else 0
        self.cfg["camera_orientation"] = angle
        self._save_settings()

    # =========================================================================
    # VIRTUAL PHONE CONTROLLER (CELULAR VIRTUAL) HANDLERS
    # =========================================================================
    def _on_vphone_toggle_changed(self):
        enabled = self.chk_vphone_enabled.isChecked()
        self.cfg["virtual_phone_enabled"] = enabled
        if hasattr(self, "vphone_details_frame"):
            self.vphone_details_frame.setVisible(enabled)
        self._apply_vphone_settings_to_controller()
        self.vphone.set_enabled(enabled)
        self._save_settings()
        self._update_vphone_ui_readout()

    def _on_vphone_sens_changed(self, val: int):
        sens = round(val / 100.0, 2)
        self.lbl_vphone_sens.setText(f"SENSITIVITY: {sens:.2f}x (DEFAULT: 1.20x)")
        self.cfg["virtual_phone_sensitivity"] = sens
        self.vphone.configure(sensitivity=sens)
        self._save_settings()

    def _on_vphone_config_changed(self):
        self._apply_vphone_settings_to_controller()
        self._save_settings()

    def _apply_vphone_settings_to_controller(self):
        host = self.txt_vphone_host.text().strip() or "127.0.0.1"
        try:
            port = int(self.txt_vphone_port.text().strip())
        except ValueError:
            port = 8080
            self.txt_vphone_port.setText("8080")
        hand = "left" if self.cb_vphone_hand.currentIndex() == 1 else "right"
        sens = round(self.slider_vphone_sens.value() / 100.0, 2)

        self.cfg["virtual_phone_host"] = host
        self.cfg["virtual_phone_port"] = port
        self.cfg["virtual_phone_hand"] = hand
        self.cfg["virtual_phone_sensitivity"] = sens

        self.vphone.configure(host=host, port=port, hand=hand, sensitivity=sens)

    def _on_vphone_reconnect_clicked(self):
        self._apply_vphone_settings_to_controller()
        self._save_settings()
        if not self.chk_vphone_enabled.isChecked():
            self.chk_vphone_enabled.setChecked(True)
        else:
            self.vphone.request_reconnect()
        self._update_vphone_ui_readout()

    def _on_vphone_discover_clicked(self):
        self.btn_vphone_discover.setEnabled(False)
        self.btn_vphone_discover.setText("Searching...")

        def _discover_worker():
            res = self.vphone.discover_server(timeout=1.2)
            QtCore.QMetaObject.invokeMethod(
                self,
                "_on_vphone_discover_finished",
                Qt.ConnectionType.QueuedConnection,
                QtCore.Q_ARG(str, res[0] if res else ""),
                QtCore.Q_ARG(int, res[1] if res else 0),
                QtCore.Q_ARG(str, res[2] if res else ""),
            )

        threading.Thread(target=_discover_worker, daemon=True).start()

    @Slot(str, int, str)
    def _on_vphone_discover_finished(self, ip: str, port: int, code: str):
        self.btn_vphone_discover.setEnabled(True)
        self.btn_vphone_discover.setText("Auto-Find")
        if ip:
            self.txt_vphone_host.setText(ip)
            if port > 0:
                self.txt_vphone_port.setText(str(port))
            self._apply_vphone_settings_to_controller()
            self._save_settings()
            if self.vphone.enabled:
                self.vphone.request_reconnect()
            info_code = f" (Pairing Code: {code})" if code else ""
            QMessageBox.information(
                self,
                "Just Dance Server Found",
                f"Game detected at {ip}:{port}{info_code}!"
            )
        else:
            QMessageBox.information(
                self,
                "UDP Auto-Discovery",
                "No UDP response on port 6000/7000.\n"
                "If the game is running on the same PC, port 8080 works directly."
            )

    def _on_skip_finish_clicked(self):
        """Sends the FTUE_FINISH shortcut packet for Just Dance 2022 phone tutorial."""
        if not self.vphone.enabled:
            self.vphone.set_enabled(True)
            if hasattr(self, "chk_vphone_enabled"):
                self.chk_vphone_enabled.setChecked(True)
        self.vphone.send_input("FTUE_FINISH")
        self.vphone._ftue_until_ts = time.perf_counter() + 4.0

    def _toggle_vphone_logging(self):
        if not self.vphone.is_logging:
            path = self.vphone.set_logging(True)
            self.btn_vphone_log.setText("⏹ Stop Log")
            self.btn_vphone_log.setStyleSheet(f"""
                QPushButton {{
                    background-color: {PALETTE["blue_pastel"]};
                    color: {PALETTE["blue_dark"]};
                    font-family: '{self.font_heading}', sans-serif;
                    font-size: 11px;
                    font-weight: bold;
                    border: 1px solid {PALETTE["ps_blue"]};
                    border-radius: 6px;
                    padding: 6px 14px;
                }}
            """)
        else:
            saved_path = self.vphone.log_path
            self.vphone.set_logging(False)
            self.btn_vphone_log.setText("Record Log")
            self.btn_vphone_log.setStyleSheet(getattr(self, "_btn_vphone_outline_style", ""))
            if saved_path and os.path.exists(saved_path):
                QMessageBox.information(
                    self,
                    "Telemetry Recording Finished",
                    f"Accelerometer CSV log saved successfully to:\n{saved_path}\n\n"
                    "File ready for analysis and comparison with real smartphone data."
                )

    def _update_vphone_ui_readout(self):
        if not hasattr(self, "lbl_vphone_status") or not hasattr(self, "lbl_vphone_accel"):
            return
        status = self.vphone.status_text
        self.lbl_vphone_status.setText(f"Status: {status}")
        if self.vphone.connected:
            color = PALETTE["status_ok"]
        elif self.vphone.enabled:
            color = PALETTE["status_warn"]
        else:
            color = PALETTE["text_muted"]
        self.lbl_vphone_status.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {color}; background: transparent; border: none;"
        )
        should_show_accel = getattr(self, "is_tracking_active", False)
        if self.lbl_vphone_accel.isVisible() != should_show_accel:
            self.lbl_vphone_accel.setVisible(should_show_accel)
        if should_show_accel:
            ax, ay, az = self.vphone.latest_accel
            spd = getattr(self.vphone.accelerometer, "latest_speed", 0.0)
            self.lbl_vphone_accel.setText(
                f"3D Accelerometer: X: {ax:+.2f}G | Y: {ay:+.2f}G | Z: {az:+.2f}G ({spd:.1f} m/s)"
            )
        self._update_ds4_ui_readout()

    def _update_ds4_ui_readout(self):
        if not hasattr(self, "lbl_ds4_status") or not hasattr(self, "lbl_ds4_accel"):
            return
        ds4 = get_ds4_controller()
        if ds4.is_connected:
            if hasattr(self, "ds4_disconnected_box"):
                self.ds4_disconnected_box.setVisible(False)
            if hasattr(self, "ds4_info_frame"):
                self.ds4_info_frame.setVisible(True)
            st = ds4.state
            charging_str = " ⚡ [Charging]" if st.is_charging else ""
            self.lbl_ds4_status.setText(
                f"Status: Connected (Bluetooth HID • {st.sample_rate_hz:.0f} Hz • Battery: {st.battery_pct}%{charging_str})"
            )
            self.lbl_ds4_status.setStyleSheet(
                f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['ps_blue']}; background: transparent; border: none;"
            )
            ax, ay, az = st.accel_g
            tot = math.sqrt(ax * ax + ay * ay + az * az)
            act_btns = [b.upper() for b, pressed in st.buttons.items() if pressed]
            btn_str = f"  |  Buttons: {', '.join(act_btns)}" if act_btns else ""
            self.lbl_ds4_accel.setText(
                f"3D Accelerometer: X: {ax:+.2f}G  |  Y: {ay:+.2f}G  |  Z: {az:+.2f}G  |  |G|: {tot:.2f}G{btn_str}"
            )
            self.lbl_ds4_accel.setStyleSheet(
                f"font-family: '{self.font_body}'; font-size: 11px; font-weight: 600; color: {PALETTE['text_main']}; background: transparent; border: none;"
            )
        else:
            if hasattr(self, "ds4_disconnected_box"):
                self.ds4_disconnected_box.setVisible(True)
            if hasattr(self, "ds4_info_frame"):
                self.ds4_info_frame.setVisible(False)
            paths = find_ds4_devices()
            if paths:
                if hasattr(self, "lbl_ds4_conn_info"):
                    self.lbl_ds4_conn_info.setText("DualShock® 4 paired via Bluetooth. Turn controller on (PS button).")
                self.lbl_ds4_status.setText("Status: DualShock 4 Paired (Turn Controller On)")
                self.lbl_ds4_status.setStyleSheet(
                    f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['status_warn']}; background: transparent; border: none;"
                )
            else:
                if hasattr(self, "lbl_ds4_conn_info"):
                    self.lbl_ds4_conn_info.setText("No Wireless Controller detected. Pair in Windows Bluetooth Settings.")
                self.lbl_ds4_status.setText("Status: Controller Disconnected (Pair via Windows Bluetooth Settings)")
                self.lbl_ds4_status.setStyleSheet(
                    f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['text_muted']}; background: transparent; border: none;"
                )
            self.lbl_ds4_accel.setText("3D Accelerometer: Disconnected")
            self.lbl_ds4_accel.setStyleSheet(
                f"font-family: '{self.font_body}'; font-size: 11px; font-weight: 500; color: {PALETTE['text_muted']}; background: transparent; border: none;"
            )

    def _test_ds4_rumble(self):
        ds4 = get_ds4_controller()
        if not ds4.is_connected:
            ds4.connect()
        if ds4.is_connected:
            ds4.trigger_rumble(small=180, large=120, duration_sec=0.35)
        else:
            QMessageBox.information(
                self,
                "DualShock 4",
                "DualShock 4 is not connected. Please pair it via Windows Bluetooth settings."
            )

    def _reconnect_ds4(self):
        if hasattr(self, "lbl_ds4_conn_info"):
            self.lbl_ds4_conn_info.setText("Searching for DualShock® 4 via Bluetooth HID...")
        def worker():
            ds4 = get_ds4_controller()
            if ds4.is_connected:
                ds4.disconnect()
                time.sleep(0.1)
            ok = ds4.connect()
            if ok:
                ds4.trigger_rumble(small=140, large=80, duration_sec=0.15)
            QtCore.QMetaObject.invokeMethod(self, "_finish_ds4_reconnect", Qt.ConnectionType.QueuedConnection)
        threading.Thread(target=worker, daemon=True).start()

    @Slot()
    def _finish_ds4_reconnect(self):
        self._update_ds4_ui_readout()

    def _on_ds4_hand_changed(self, idx: int):
        hand = "right" if idx == 0 else "left"
        self.cfg["ds4_hand"] = hand
        ds4 = get_ds4_controller()
        ds4.hand = hand
        self._save_settings()

    def _on_ds4_sens_changed(self, idx: int):
        sens_map = {0: 1.0, 1: 1.25, 2: 0.85}
        sens = sens_map.get(idx, 1.0)
        self.cfg["ds4_sensitivity"] = sens
        ds4 = get_ds4_controller()
        ds4.sensitivity = sens
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
            Path(sys.executable).parent / "Kinect for Legacy DLL",
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

        if mode == "ds4":
            ds4 = get_ds4_controller()
            if not ds4.is_connected:
                if not ds4.connect():
                    QMessageBox.warning(
                        self,
                        "DualShock 4 Not Detected",
                        "DualShock 4 controller was not detected on this computer!\n\n"
                        "• Ensure the DualShock 4 is paired wirelessly via Windows Bluetooth settings.\n"
                        "• Press the PS Button on the controller to wake it up."
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
            return

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
        if hasattr(self, "lbl_vphone_accel"):
            self.lbl_vphone_accel.setVisible(True)
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
        if hasattr(self, "lbl_vphone_accel"):
            self.lbl_vphone_accel.setVisible(False)
        if self.cfg.get("camera_source") == "ds4":
            self.btn_start.setText("START CONTROLLER (DS4)")
        else:
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
        if hasattr(self, "timer_vphone") and self.timer_vphone is not None:
            self.timer_vphone.stop()
        if hasattr(self, "vphone") and self.vphone is not None:
            self.vphone.stop()
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
