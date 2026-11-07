"""
Modern PlayStation 5-Themed Qt 6 User Interface for Legacy PSCam Sensor.
Features:
- Sliding navigation tabs with cubic easing transitions (60 FPS fluid animation).
- Hardware-accelerated drop shadows and modern glass/card aesthetic.
- State-aware video panel: when disconnected, displays strictly the status balloon and action button.
- Asynchronous hotplug detection with Qt Signals and non-blocking timers.
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
    QPoint, QRect, QSize, Signal, Slot, QParallelAnimationGroup
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QCheckBox, QStackedWidget,
    QFrame, QGraphicsDropShadowEffect, QGraphicsOpacityEffect,
    QSlider, QSpacerItem, QSizePolicy, QMessageBox
)
from PySide6.QtGui import (
    QColor, QFont, QPainter, QBrush, QPen, QPixmap, QIcon, QCursor, QImage
)

from ui.theme import PALETTE, CALIB_PRESETS
from ui.icons import generate_icons, generate_tab_icons, generate_status_icons
from assets import ICON_PSCAMERA_PATH
from sensor.config_manager import ConfigManager, PRESETS_PSCAM, PRESETS_WEBCAM
from sensor.camera_manager import CameraManager
from sensor.kinect_shared_memory import KinectBridge
from sensor import tracking_session


def pil_to_qpixmap(pil_img) -> QPixmap:
    """Converts a Pillow RGBA Image to a Qt QPixmap with antialiasing."""
    if pil_img is None:
        return QPixmap()
    img_rgba = pil_img.convert("RGBA")
    data = img_rgba.tobytes("raw", "RGBA")
    qimg = QImage(data, img_rgba.width, img_rgba.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg)


class SlidingStackedWidget(QStackedWidget):
    """
    QStackedWidget featuring hardware-friendly sliding animations between pages
    with cubic easing curves inspired by the PlayStation 5 console UI.
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
            self._is_animating = False

        self.anim_group.finished.connect(on_finished)
        self.anim_group.start()


class LegacySensorQtGUI(QMainWindow):
    """Modern PlayStation 5-themed primary window."""
    cameras_refreshed_signal = Signal(list)
    tracking_finished_signal = Signal(bool, str)

    def __init__(self, parent=None, *args, **kwargs):
        if parent is not None and not isinstance(parent, QWidget):
            parent = None
        super().__init__(parent)
        self.setWindowTitle("Legacy PSCam Sensor")
        self.resize(960, 580)
        self.setMinimumSize(920, 550)
        if ICON_PSCAMERA_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PSCAMERA_PATH)))

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
        self._refresh_cameras_async()

        # Periodic non-blocking check (1000ms)
        self.timer_periodic = QTimer(self)
        self.timer_periodic.timeout.connect(self._periodic_check)
        self.timer_periodic.start(1000)

    def _load_pixmaps(self):
        """Loads and converts PIL icons into antialiased QPixmaps."""
        try:
            p_ps_act, p_ps_inact, p_web_act, p_web_inact = generate_icons()
            self.pix_ps_act = pil_to_qpixmap(p_ps_act)
            self.pix_ps_inact = pil_to_qpixmap(p_ps_inact)
            self.pix_web_act = pil_to_qpixmap(p_web_act)
            self.pix_web_inact = pil_to_qpixmap(p_web_inact)
        except Exception:
            self.pix_ps_act = self.pix_ps_inact = self.pix_web_act = self.pix_web_inact = QPixmap()

        try:
            p_gear_act, p_gear_inact, p_slid_act, p_slid_inact = generate_tab_icons()
            self.pix_gear_act = pil_to_qpixmap(p_gear_act)
            self.pix_gear_inact = pil_to_qpixmap(p_gear_inact)
            self.pix_slid_act = pil_to_qpixmap(p_slid_act)
            self.pix_slid_inact = pil_to_qpixmap(p_slid_inact)
        except Exception:
            self.pix_gear_act = self.pix_gear_inact = self.pix_slid_act = self.pix_slid_inact = QPixmap()

        try:
            p_err, p_ok, p_warn = generate_status_icons(size=(38, 38))
            self.pix_status_err = pil_to_qpixmap(p_err)
            self.pix_status_ok = pil_to_qpixmap(p_ok)
            self.pix_status_warn = pil_to_qpixmap(p_warn)
        except Exception:
            self.pix_status_err = self.pix_status_ok = self.pix_status_warn = QPixmap()

    def _setup_style(self):
        """Applies a dark PlayStation console stylesheet (QSS)."""
        self.setStyleSheet("""
            QMainWindow, QWidget#centralWidget {
                background-color: #0B111E;
                color: #F8FAFC;
                font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            }
            QFrame#sidebar {
                background-color: #0F172A;
                border-right: 1px solid #1E293B;
            }
            QFrame.card {
                background-color: #162032;
                border: 1px solid #1E293B;
                border-radius: 12px;
            }
            QFrame.status_balloon {
                background-color: #131D2D;
                border: 1px solid #334155;
                border-radius: 12px;
            }
            QFrame.spec_badge {
                background-color: #1E3A5F;
                border: 1px solid #2563EB;
                border-radius: 10px;
            }
            QPushButton.btn_cta {
                background-color: #0070D1;
                color: #FFFFFF;
                font-weight: bold;
                font-size: 13px;
                border-radius: 10px;
                padding: 12px;
                border: none;
            }
            QPushButton.btn_cta:hover {
                background-color: #0082F0;
            }
            QPushButton.btn_cta:pressed {
                background-color: #005BB5;
            }
            QPushButton.btn_cta:disabled {
                background-color: #334155;
                color: #64748B;
            }
            QPushButton.btn_secondary {
                background-color: #1E3A5F;
                color: #38BDF8;
                font-weight: bold;
                font-size: 11px;
                border-radius: 8px;
                padding: 8px 12px;
                border: 1px solid #2563EB;
            }
            QPushButton.btn_secondary:hover {
                background-color: #2563EB;
                color: #FFFFFF;
            }
            QPushButton.btn_secondary:pressed {
                background-color: #1D4ED8;
            }
            QPushButton.btn_secondary:disabled {
                background-color: #162032;
                color: #64748B;
                border-color: #1E293B;
            }
            QPushButton.btn_balloon_action {
                background-color: #131D2D;
                color: #FFFFFF;
                font-weight: bold;
                font-size: 11px;
                border: 1px solid #1E293B;
                border-radius: 12px;
                padding: 10px 16px;
                text-align: center;
            }
            QPushButton.btn_balloon_action:hover {
                background-color: #1E293B;
                border-color: #334155;
            }
            QPushButton.btn_balloon_action:pressed {
                background-color: #0F172A;
            }
            QPushButton.btn_balloon_action:disabled {
                background-color: #131D2D;
                color: #475569;
                border-color: #1E293B;
            }
            QComboBox {
                background-color: #131D2D;
                color: #F8FAFC;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 6px 12px;
                font-size: 11px;
            }
            QComboBox:hover {
                border-color: #0070D1;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 24px;
                border-left: 1px solid #334155;
            }
            QComboBox QAbstractItemView {
                background-color: #162032;
                color: #F8FAFC;
                selection-background-color: #0070D1;
                border: 1px solid #334155;
                border-radius: 6px;
            }
            QCheckBox {
                color: #E2E8F0;
                font-size: 11px;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 5px;
                border: 1px solid #334155;
                background-color: #131D2D;
            }
            QCheckBox::indicator:hover {
                border-color: #0070D1;
            }
            QCheckBox::indicator:checked {
                background-color: #0070D1;
                border-color: #0070D1;
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: #1E293B;
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: #0070D1;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #38BDF8;
                width: 16px;
                margin-top: -5px;
                margin-bottom: -5px;
                border-radius: 8px;
            }
        """)

    def _build_ui(self):
        """Builds the main PlayStation console layout with horizontal split."""
        central_widget = QWidget(self)
        central_widget.setObjectName("centralWidget")
        self.setCentralWidget(central_widget)

        master_layout = QHBoxLayout(central_widget)
        master_layout.setContentsMargins(0, 0, 0, 0)
        master_layout.setSpacing(0)

        # =====================================================================
        # 1. LEFT SIDEBAR (Width 270)
        # =====================================================================
        self.sidebar_frame = QFrame(central_widget)
        self.sidebar_frame.setObjectName("sidebar")
        self.sidebar_frame.setFixedWidth(270)
        sidebar_layout = QVBoxLayout(self.sidebar_frame)
        sidebar_layout.setContentsMargins(20, 22, 20, 20)
        sidebar_layout.setSpacing(12)

        # 1.1 Brand Header
        brand_layout = QHBoxLayout()
        lbl_brand_title = QLabel("LEGACY PSCAM", self.sidebar_frame)
        lbl_brand_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #FFFFFF; letter-spacing: 1px;")
        lbl_brand_sub = QLabel("SENSOR", self.sidebar_frame)
        lbl_brand_sub.setStyleSheet("font-size: 15px; font-weight: bold; color: #0070D1; letter-spacing: 1px;")
        brand_layout.addWidget(lbl_brand_title)
        brand_layout.addWidget(lbl_brand_sub)
        brand_layout.addStretch()
        sidebar_layout.addLayout(brand_layout)

        lbl_desc = QLabel("Motion Tracker for Just Dance PC", self.sidebar_frame)
        lbl_desc.setStyleSheet("font-size: 10px; color: #64748B;")
        sidebar_layout.addWidget(lbl_desc)

        sidebar_layout.addSpacing(8)

        # 1.2 Device Switcher Cards
        lbl_devices_hdr = QLabel("INPUT DEVICE", self.sidebar_frame)
        lbl_devices_hdr.setStyleSheet("font-size: 10px; font-weight: bold; color: #475569; letter-spacing: 0.5px;")
        sidebar_layout.addWidget(lbl_devices_hdr)

        # Card PS Camera
        self.btn_card_pscam = QPushButton(self.sidebar_frame)
        self.btn_card_pscam.setFixedHeight(58)
        self.btn_card_pscam.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_card_pscam.clicked.connect(lambda: self._set_mode("pscam"))
        sidebar_layout.addWidget(self.btn_card_pscam)

        # Card Webcam
        self.btn_card_webcam = QPushButton(self.sidebar_frame)
        self.btn_card_webcam.setFixedHeight(58)
        self.btn_card_webcam.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_card_webcam.clicked.connect(lambda: self._set_mode("webcam"))
        sidebar_layout.addWidget(self.btn_card_webcam)

        sidebar_layout.addSpacing(6)

        # 1.3 Quick Action: Open Kinect10.dll folder
        self.btn_dll_folder = QPushButton("📁 Open Kinect10.dll Folder", self.sidebar_frame)
        self.btn_dll_folder.setProperty("class", "btn_secondary")
        self.btn_dll_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_dll_folder.clicked.connect(self._open_dll_folder)
        sidebar_layout.addWidget(self.btn_dll_folder)

        lbl_dll_tip = QLabel("Copy Kinect10.dll to your Just Dance\nfolder to enable motion capture.", self.sidebar_frame)
        lbl_dll_tip.setStyleSheet("font-size: 9px; color: #64748B; line-height: 1.3;")
        sidebar_layout.addWidget(lbl_dll_tip)

        sidebar_layout.addStretch()

        # 1.4 Mini Credits
        lbl_cred1 = QLabel("Original Legacy Sensor by itsVexor", self.sidebar_frame)
        lbl_cred1.setStyleSheet("font-size: 9px; color: #475569;")
        lbl_cred2 = QLabel("PSCam4Win by BumbleTree", self.sidebar_frame)
        lbl_cred2.setStyleSheet("font-size: 9px; color: #475569;")
        sidebar_layout.addWidget(lbl_cred1)
        sidebar_layout.addWidget(lbl_cred2)

        sidebar_layout.addSpacing(4)

        # 1.5 IPC Bridge Status Badge
        ipc_badge = QFrame(self.sidebar_frame)
        ipc_badge.setStyleSheet("""
            background-color: #064E3B;
            border: 1px solid #10B981;
            border-radius: 8px;
            padding: 4px;
        """)
        ipc_layout = QVBoxLayout(ipc_badge)
        ipc_layout.setContentsMargins(8, 6, 8, 6)
        ipc_layout.setSpacing(2)

        lbl_ipc = QLabel("● IPC Bridge Active", ipc_badge)
        lbl_ipc.setStyleSheet("font-size: 11px; font-weight: bold; color: #34D399; background: transparent;")
        lbl_ipc_sub = QLabel("JDP1 (Pose) & JMI1 (Silhouette)", ipc_badge)
        lbl_ipc_sub.setStyleSheet("font-size: 9px; color: #A7F3D0; background: transparent;")
        ipc_layout.addWidget(lbl_ipc)
        ipc_layout.addWidget(lbl_ipc_sub)
        sidebar_layout.addWidget(ipc_badge)

        master_layout.addWidget(self.sidebar_frame)

        # =====================================================================
        # 2. MAIN CONTENT AREA (Right Side)
        # =====================================================================
        self.content_widget = QWidget(central_widget)
        content_layout = QVBoxLayout(self.content_widget)
        content_layout.setContentsMargins(28, 20, 28, 20)
        content_layout.setSpacing(14)

        # 2.1 Top Tab Navigation Strip (Centered)
        top_nav_layout = QHBoxLayout()
        top_nav_layout.setContentsMargins(0, 0, 0, 4)

        self.btn_tab_video = QPushButton("  Video Settings", self.content_widget)
        self.btn_tab_video.setFixedSize(144, 40)
        self.btn_tab_video.setIcon(QIcon(self.pix_gear_act))
        self.btn_tab_video.setIconSize(QSize(18, 18))
        self.btn_tab_video.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_tab_video.clicked.connect(lambda: self._switch_tab("video"))

        self.btn_tab_calib = QPushButton("  Calibration", self.content_widget)
        self.btn_tab_calib.setFixedSize(126, 40)
        self.btn_tab_calib.setIcon(QIcon(self.pix_slid_inact))
        self.btn_tab_calib.setIconSize(QSize(18, 18))
        self.btn_tab_calib.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_tab_calib.clicked.connect(lambda: self._switch_tab("calib"))

        top_nav_layout.addStretch()
        top_nav_layout.addWidget(self.btn_tab_video)
        top_nav_layout.addSpacing(10)
        top_nav_layout.addWidget(self.btn_tab_calib)
        top_nav_layout.addStretch()
        content_layout.addLayout(top_nav_layout)
        self._apply_tab_styles("video")

        # Separator line
        sep = QFrame(self.content_widget)
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #1E293B; max-height: 1px;")
        content_layout.addWidget(sep)

        # 2.2 Animated Sliding Stacked Widget
        self.stacked_view = SlidingStackedWidget(self.content_widget)
        content_layout.addWidget(self.stacked_view, stretch=1)

        # Build Page 0 (Video) & Page 1 (Calibration)
        self._build_video_view()
        self._build_calib_view()

        # 2.3 Bottom Action Area (PlayStation Blue CTA & Footer)
        self.btn_start = QPushButton("START TRACKING", self.content_widget)
        self.btn_start.setProperty("class", "btn_cta")
        self.btn_start.setFixedHeight(48)
        self.btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_start.clicked.connect(self._start_tracking)
        content_layout.addWidget(self.btn_start)

        footer_layout = QHBoxLayout()
        lbl_author = QLabel("Made by Edd <3", self.content_widget)
        lbl_author.setStyleSheet("font-size: 10px; color: #64748B;")
        lbl_ver = QLabel("Legacy PSCam Sensor v0.5 (Qt6)", self.content_widget)
        lbl_ver.setStyleSheet("font-size: 10px; color: #475569;")
        footer_layout.addWidget(lbl_author)
        footer_layout.addStretch()
        footer_layout.addWidget(lbl_ver)
        content_layout.addLayout(footer_layout)

        master_layout.addWidget(self.content_widget, stretch=1)

    def _build_video_view(self):
        """Constructs Page 0: Video Settings."""
        self.page_video = QWidget()
        layout = QVBoxLayout(self.page_video)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(12)

        # =====================================================================
        # 1. PlayStation Camera Views
        # =====================================================================
        # 1.1 Disconnected Balloon (Shown as the ONLY element when disconnected)
        self.pscam_disconnected_box = QFrame(self.page_video)
        ps_disc_layout = QVBoxLayout(self.pscam_disconnected_box)
        ps_disc_layout.setContentsMargins(0, 0, 0, 0)
        ps_disc_layout.setSpacing(10)

        self.pscam_status_card = QFrame(self.pscam_disconnected_box)
        self.pscam_status_card.setProperty("class", "status_balloon")
        card_layout = QHBoxLayout(self.pscam_status_card)
        card_layout.setContentsMargins(18, 16, 18, 16)
        card_layout.setSpacing(16)

        self.lbl_pscam_icon = QLabel(self.pscam_status_card)
        self.lbl_pscam_icon.setPixmap(self.pix_status_err)
        self.lbl_pscam_icon.setFixedSize(38, 38)
        card_layout.addWidget(self.lbl_pscam_icon)

        text_col = QVBoxLayout()
        text_col.setSpacing(4)
        self.lbl_pscam_conn_title = QLabel("PlayStation Camera not connected", self.pscam_status_card)
        self.lbl_pscam_conn_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #FFFFFF;")
        self.lbl_pscam_info = QLabel("Driver Offline and Camera disconnected from USB Port", self.pscam_status_card)
        self.lbl_pscam_info.setStyleSheet("font-size: 11px; color: #94A3B8;")
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
        ps_conn_layout.setContentsMargins(18, 16, 18, 16)
        ps_conn_layout.setSpacing(10)

        lbl_ps_title = QLabel("PLAYSTATION®CAMERA INTEGRATION", self.pscam_card)
        lbl_ps_title.setStyleSheet("font-size: 12px; font-weight: bold; color: #38BDF8; letter-spacing: 0.5px;")
        ps_conn_layout.addWidget(lbl_ps_title)

        self.lbl_pscam_ready_info = QLabel("Driver active and PlayStation®Camera connected (60 FPS)", self.pscam_card)
        self.lbl_pscam_ready_info.setStyleSheet("font-size: 11px; color: #10B981;")
        ps_conn_layout.addWidget(self.lbl_pscam_ready_info)

        spec_badge = QFrame(self.pscam_card)
        spec_badge.setProperty("class", "spec_badge")
        spec_layout = QVBoxLayout(spec_badge)
        spec_layout.setContentsMargins(14, 10, 14, 10)
        lbl_spec_title = QLabel("Optimized Auto Mode: 1280x800 @ 60 FPS (OV580 Stereo DirectShow)", spec_badge)
        lbl_spec_title.setStyleSheet("font-size: 11px; font-weight: bold; color: #FFFFFF;")
        lbl_spec_sub = QLabel("Resolution picker is hidden in this tab because the PlayStation®Camera operates in the driver's native format.", spec_badge)
        lbl_spec_sub.setStyleSheet("font-size: 10px; color: #93C5FD;")
        spec_layout.addWidget(lbl_spec_title)
        spec_layout.addWidget(lbl_spec_sub)
        ps_conn_layout.addWidget(spec_badge)
        layout.addWidget(self.pscam_card)

        # =====================================================================
        # 2. Webcam Views
        # =====================================================================
        # 2.1 Disconnected Balloon
        self.webcam_disconnected_box = QFrame(self.page_video)
        web_disc_layout = QVBoxLayout(self.webcam_disconnected_box)
        web_disc_layout.setContentsMargins(0, 0, 0, 0)
        web_disc_layout.setSpacing(10)

        self.webcam_status_card = QFrame(self.webcam_disconnected_box)
        self.webcam_status_card.setProperty("class", "status_balloon")
        web_card_layout = QHBoxLayout(self.webcam_status_card)
        web_card_layout.setContentsMargins(18, 16, 18, 16)
        web_card_layout.setSpacing(16)

        self.lbl_webcam_icon = QLabel(self.webcam_status_card)
        self.lbl_webcam_icon.setPixmap(self.pix_status_err)
        self.lbl_webcam_icon.setFixedSize(38, 38)
        web_card_layout.addWidget(self.lbl_webcam_icon)

        web_text_col = QVBoxLayout()
        web_text_col.setSpacing(4)
        self.lbl_webcam_conn_title = QLabel("Webcam not connected", self.webcam_status_card)
        self.lbl_webcam_conn_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #FFFFFF;")
        self.lbl_webcam_info = QLabel("Camera disconnected from USB Port", self.webcam_status_card)
        self.lbl_webcam_info.setStyleSheet("font-size: 11px; color: #94A3B8;")
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
        web_conn_layout.setContentsMargins(18, 16, 18, 16)
        web_conn_layout.setSpacing(10)

        lbl_wc_title = QLabel("WEBCAM VIDEO SETTINGS", self.webcam_card)
        lbl_wc_title.setStyleSheet("font-size: 12px; font-weight: bold; color: #38BDF8; letter-spacing: 0.5px;")
        web_conn_layout.addWidget(lbl_wc_title)

        dev_row = QHBoxLayout()
        lbl_dev = QLabel("Device:", self.webcam_card)
        lbl_dev.setStyleSheet("font-size: 11px; font-weight: bold; color: #E2E8F0;")
        lbl_dev.setFixedWidth(110)
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

        res_row = QHBoxLayout()
        lbl_res = QLabel("Resolution / FPS:", self.webcam_card)
        lbl_res.setStyleSheet("font-size: 11px; font-weight: bold; color: #E2E8F0;")
        lbl_res.setFixedWidth(110)
        self.cb_preset = QComboBox(self.webcam_card)
        self.cb_preset.currentIndexChanged.connect(self._on_preset_selected)
        res_row.addWidget(lbl_res)
        res_row.addWidget(self.cb_preset, stretch=1)
        web_conn_layout.addLayout(res_row)

        layout.addWidget(self.webcam_card)

        # =====================================================================
        # 3. Additional Display Options (Shown ONLY when connected)
        # =====================================================================
        self.display_card = QFrame(self.page_video)
        self.display_card.setProperty("class", "card")
        disp_layout = QVBoxLayout(self.display_card)
        disp_layout.setContentsMargins(18, 16, 18, 16)
        disp_layout.setSpacing(10)

        lbl_disp_title = QLabel("ADDITIONAL DISPLAY OPTIONS", self.display_card)
        lbl_disp_title.setStyleSheet("font-size: 12px; font-weight: bold; color: #38BDF8; letter-spacing: 0.5px;")
        disp_layout.addWidget(lbl_disp_title)

        self.chk_hud = QCheckBox("Display HUD Overlay in Tracking Window (FPS, IPC & Shortcuts)", self.display_card)
        self.chk_hud.setChecked(self.cfg.get("show_hud", True))
        self.chk_hud.stateChanged.connect(self._on_display_options_changed)
        disp_layout.addWidget(self.chk_hud)

        self.chk_face = QCheckBox("[EXPERIMENTAL] Auto-Frame player's face in Just Dance", self.display_card)
        self.chk_face.setChecked(self.cfg.get("face_follow_enabled", True))
        self.chk_face.stateChanged.connect(self._on_display_options_changed)
        disp_layout.addWidget(self.chk_face)

        layout.addWidget(self.display_card)
        layout.addStretch()

        self.stacked_view.addWidget(self.page_video)

    def _build_calib_view(self):
        """Constructs Page 1: Calibration & Motion Profile."""
        self.page_calib = QWidget()
        layout = QVBoxLayout(self.page_calib)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(12)

        main_card = QFrame(self.page_calib)
        main_card.setProperty("class", "card")
        card_layout = QVBoxLayout(main_card)
        card_layout.setContentsMargins(18, 16, 18, 16)
        card_layout.setSpacing(12)

        lbl_head = QLabel("TRACKING & MOTION PROFILE", main_card)
        lbl_head.setStyleSheet("font-size: 12px; font-weight: bold; color: #38BDF8; letter-spacing: 0.5px;")
        lbl_sub = QLabel("Select the profile that best fits your playstyle and camera setup.", main_card)
        lbl_sub.setStyleSheet("font-size: 11px; color: #94A3B8;")
        card_layout.addWidget(lbl_head)
        card_layout.addWidget(lbl_sub)

        # 3 Profile cards
        cards_row = QHBoxLayout()
        cards_row.setSpacing(10)

        for pid, pdata in CALIB_PRESETS.items():
            card = QPushButton(main_card)
            card.setFixedHeight(120)
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            card.clicked.connect(lambda _, p=pid: self._select_calib_preset(p))

            c_layout = QVBoxLayout(card)
            c_layout.setContentsMargins(12, 10, 12, 10)
            c_layout.setSpacing(4)

            top_row = QHBoxLayout()
            lbl_title = QLabel(f"{pdata['icon']} {pdata['title']}", card)
            lbl_title.setStyleSheet("font-size: 12px; font-weight: bold; color: #FFFFFF;")
            lbl_tag = QLabel(pdata["tag"], card)
            lbl_tag.setStyleSheet("font-size: 8px; font-weight: bold; color: #38BDF8; background: #0F172A; padding: 2px 6px; border-radius: 4px;")
            top_row.addWidget(lbl_title)
            top_row.addStretch()
            top_row.addWidget(lbl_tag)
            c_layout.addLayout(top_row)

            lbl_sub_p = QLabel(pdata["subtitle"], card)
            lbl_sub_p.setStyleSheet("font-size: 10px; font-weight: bold; color: #0070D1;")
            c_layout.addWidget(lbl_sub_p)

            lbl_desc = QLabel(pdata["desc"], card)
            lbl_desc.setStyleSheet("font-size: 9px; color: #94A3B8;")
            lbl_desc.setWordWrap(True)
            c_layout.addWidget(lbl_desc, stretch=1)

            lbl_specs = QLabel(pdata["specs"], card)
            lbl_specs.setStyleSheet("font-size: 8px; color: #64748B;")
            c_layout.addWidget(lbl_specs)

            cards_row.addWidget(card)
            self.calib_cards[pid] = card

        card_layout.addLayout(cards_row)

        # Auto-height callout
        auto_h = QFrame(main_card)
        auto_h.setStyleSheet("background-color: #131D2D; border: 1px solid #1E293B; border-radius: 8px; padding: 8px;")
        ah_layout = QHBoxLayout(auto_h)
        lbl_ruler = QLabel("📏", auto_h)
        lbl_ruler.setStyleSheet("font-size: 16px;")
        ah_layout.addWidget(lbl_ruler)
        ah_text = QVBoxLayout()
        ah_title = QLabel("Automatic Height Normalization (1.75m Standard)", auto_h)
        ah_title.setStyleSheet("font-size: 11px; font-weight: bold; color: #38BDF8;")
        ah_sub = QLabel("The sensor dynamically scales body proportions to the Kinect v1 metric convention. No manual adjustment needed.", auto_h)
        ah_sub.setStyleSheet("font-size: 10px; color: #94A3B8;")
        ah_text.addWidget(ah_title)
        ah_text.addWidget(ah_sub)
        ah_layout.addLayout(ah_text, stretch=1)
        card_layout.addWidget(auto_h)

        # Advanced toggle button
        self.btn_toggle_adv = QPushButton("Show Advanced Filter Settings ▼", main_card)
        self.btn_toggle_adv.setProperty("class", "btn_secondary")
        self.btn_toggle_adv.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle_adv.clicked.connect(self._toggle_advanced_calib)
        card_layout.addWidget(self.btn_toggle_adv)

        # Advanced drawer
        self.adv_drawer = QFrame(main_card)
        self.adv_drawer.setStyleSheet("background-color: #131D2D; border: 1px solid #1E293B; border-radius: 8px; padding: 12px;")
        adv_layout = QVBoxLayout(self.adv_drawer)
        adv_layout.setSpacing(8)

        # Slider 1: Smoothing
        self.lbl_smooth = QLabel(f"EMA Motion Smoothing: {self.cfg.get('smoothing_alpha', 0.55):.2f}", self.adv_drawer)
        self.lbl_smooth.setStyleSheet("font-size: 11px; font-weight: bold; color: #FFFFFF;")
        adv_layout.addWidget(self.lbl_smooth)
        self.slider_smooth = QSlider(Qt.Orientation.Horizontal, self.adv_drawer)
        self.slider_smooth.setRange(20, 85)
        self.slider_smooth.setValue(int(self.cfg.get("smoothing_alpha", 0.55) * 100))
        self.slider_smooth.valueChanged.connect(self._on_smooth_slider_changed)
        adv_layout.addWidget(self.slider_smooth)

        # Slider 2: Confidence
        self.lbl_conf = QLabel(f"MediaPipe Detection Confidence: {self.cfg.get('detection_confidence', 0.50):.2f}", self.adv_drawer)
        self.lbl_conf.setStyleSheet("font-size: 11px; font-weight: bold; color: #FFFFFF;")
        adv_layout.addWidget(self.lbl_conf)
        self.slider_conf = QSlider(Qt.Orientation.Horizontal, self.adv_drawer)
        self.slider_conf.setRange(30, 80)
        self.slider_conf.setValue(int(self.cfg.get("detection_confidence", 0.50) * 100))
        self.slider_conf.valueChanged.connect(self._on_conf_slider_changed)
        adv_layout.addWidget(self.slider_conf)

        self.adv_drawer.setVisible(False)
        card_layout.addWidget(self.adv_drawer)

        layout.addWidget(main_card)
        layout.addStretch()

        self.stacked_view.addWidget(self.page_calib)
        self._update_calib_cards_ui()

    # =========================================================================
    # UI STATE MANAGEMENT & VISIBILITY
    # =========================================================================
    def _apply_tab_styles(self, tab_id: str):
        if tab_id == "video":
            self.btn_tab_video.setStyleSheet("""
                background-color: #1E293B;
                color: #FFFFFF;
                font-weight: bold;
                border: 1px solid #334155;
                border-radius: 8px;
            """)
            self.btn_tab_video.setIcon(QIcon(self.pix_gear_act))
            self.btn_tab_calib.setStyleSheet("""
                background-color: transparent;
                color: #94A3B8;
                font-weight: normal;
                border: 1px solid transparent;
                border-radius: 8px;
            """)
            self.btn_tab_calib.setIcon(QIcon(self.pix_slid_inact))
        else:
            self.btn_tab_calib.setStyleSheet("""
                background-color: #1E293B;
                color: #FFFFFF;
                font-weight: bold;
                border: 1px solid #334155;
                border-radius: 8px;
            """)
            self.btn_tab_calib.setIcon(QIcon(self.pix_slid_act))
            self.btn_tab_video.setStyleSheet("""
                background-color: transparent;
                color: #94A3B8;
                font-weight: normal;
                border: 1px solid transparent;
                border-radius: 8px;
            """)
            self.btn_tab_video.setIcon(QIcon(self.pix_gear_inact))

    def _switch_tab(self, tab_id: str):
        if self.active_tab == tab_id:
            return
        self.active_tab = tab_id
        self._apply_tab_styles(tab_id)

        if tab_id == "video":
            self.stacked_view.slide_to_index(0)
            self._update_video_view_visibility()
        else:
            self.stacked_view.slide_to_index(1)

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
        active_style = """
            QPushButton {
                background-color: #00439C;
                color: #FFFFFF;
                border: 1px solid #2563EB;
                border-radius: 12px;
                text-align: left;
                padding-left: 14px;
            }
        """
        inactive_style = """
            QPushButton {
                background-color: #131D2D;
                color: #94A3B8;
                border: 1px solid #1E293B;
                border-radius: 12px;
                text-align: left;
                padding-left: 14px;
            }
            QPushButton:hover {
                background-color: #1E293B;
                border-color: #334155;
            }
        """
        if mode == "pscam":
            self.btn_card_pscam.setStyleSheet(active_style)
            self.btn_card_pscam.setIcon(QIcon(self.pix_ps_act))
            self.btn_card_pscam.setIconSize(QSize(28, 28))
            self.btn_card_pscam.setText(" PlayStation®Camera\n OV580 Stereo • 60 FPS")

            self.btn_card_webcam.setStyleSheet(inactive_style)
            self.btn_card_webcam.setIcon(QIcon(self.pix_web_inact))
            self.btn_card_webcam.setIconSize(QSize(28, 28))
            self.btn_card_webcam.setText(" Standard Webcam\n USB or Integrated")
        else:
            self.btn_card_webcam.setStyleSheet(active_style)
            self.btn_card_webcam.setIcon(QIcon(self.pix_web_act))
            self.btn_card_webcam.setIconSize(QSize(28, 28))
            self.btn_card_webcam.setText(" Standard Webcam\n USB or Integrated")

            self.btn_card_pscam.setStyleSheet(inactive_style)
            self.btn_card_pscam.setIcon(QIcon(self.pix_ps_inact))
            self.btn_card_pscam.setIconSize(QSize(28, 28))
            self.btn_card_pscam.setText(" PlayStation®Camera\n OV580 Stereo • 60 FPS")

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

    def _refresh_presets(self):
        mode = self.cfg.get("camera_mode", "pscam")
        presets = PRESETS_PSCAM if mode == "pscam" else PRESETS_WEBCAM
        current = self.cfg.get("pscam_preset" if mode == "pscam" else "webcam_preset", presets[0])

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
            self.lbl_pscam_info.setStyleSheet("font-size: 11px; color: #EF4444;")
            self.btn_launch_pscam.setEnabled(False)
            self.btn_launch_pscam.setText("Driver Not Installed")

        elif state == "DISCONNECTED":
            self.lbl_pscam_icon.setPixmap(self.pix_status_err)
            self.lbl_pscam_conn_title.setText("PlayStation Camera not connected")
            if running:
                self.lbl_pscam_info.setText("Driver Online and Camera disconnected from USB Port")
                self.lbl_pscam_info.setStyleSheet("font-size: 11px; color: #F59E0B;")
                self.btn_launch_pscam.setEnabled(False)
                self.btn_launch_pscam.setText("PSCam4Win Driver Active")
            else:
                self.lbl_pscam_info.setText("Driver Offline and Camera disconnected from USB Port")
                self.lbl_pscam_info.setStyleSheet("font-size: 11px; color: #94A3B8;")
                self.btn_launch_pscam.setEnabled(True)
                self.btn_launch_pscam.setText("Start PSCam4Win Driver")

        elif state == "DRIVER_STOPPED":
            self.lbl_pscam_icon.setPixmap(self.pix_status_warn)
            self.lbl_pscam_conn_title.setText("PlayStation Camera detected")
            self.lbl_pscam_info.setText("Camera connected, but PSCam4Win Driver is Offline")
            self.lbl_pscam_info.setStyleSheet("font-size: 11px; color: #F59E0B;")
            self.btn_launch_pscam.setEnabled(True)
            self.btn_launch_pscam.setText("Start PSCam4Win Driver")

        elif state == "BOOTLOADER_UPLOADING":
            self.lbl_pscam_icon.setPixmap(self.pix_status_warn)
            self.lbl_pscam_conn_title.setText("PlayStation Camera initializing")
            self.lbl_pscam_info.setText("PlayStation®Camera detected! PSCam4Win uploading USB firmware...")
            self.lbl_pscam_info.setStyleSheet("font-size: 11px; color: #38BDF8;")
            self.btn_launch_pscam.setEnabled(False)
            self.btn_launch_pscam.setText("Uploading Firmware...")

        elif state == "WAITING_VCAM":
            self.lbl_pscam_icon.setPixmap(self.pix_status_warn)
            self.lbl_pscam_conn_title.setText("PlayStation Camera initializing")
            self.lbl_pscam_info.setText("Hardware ready! Initializing DirectShow virtual camera (60 FPS)...")
            self.lbl_pscam_info.setStyleSheet("font-size: 11px; color: #38BDF8;")
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
        if self._is_refreshing_cams:
            return
        self._is_refreshing_cams = True

        def worker():
            try:
                cams = CameraManager.enumerate_cameras()
            except Exception:
                cams = []
            self.cameras_refreshed_signal.emit(cams)

        threading.Thread(target=worker, daemon=True).start()

    @Slot(list)
    def _on_cameras_refreshed(self, cams):
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

    def _on_preset_selected(self, index: int):
        mode = self.cfg.get("camera_mode", "pscam")
        preset = self.cb_preset.currentText()
        if mode == "pscam":
            self.cfg["pscam_preset"] = preset
        else:
            self.cfg["webcam_preset"] = preset
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

        self.slider_smooth.setValue(int(p["smoothing_alpha"] * 100))
        self.slider_conf.setValue(int(p["detection_confidence"] * 100))
        self._update_calib_cards_ui()
        self._save_settings()

    def _update_calib_cards_ui(self):
        for pid, card in self.calib_cards.items():
            if pid == self.current_calib_preset:
                card.setStyleSheet("""
                    QPushButton {
                        background-color: #1E3A5F;
                        border: 2px solid #0070D1;
                        border-radius: 10px;
                        text-align: left;
                    }
                """)
            else:
                card.setStyleSheet("""
                    QPushButton {
                        background-color: #131D2D;
                        border: 1px solid #1E293B;
                        border-radius: 10px;
                        text-align: left;
                    }
                    QPushButton:hover {
                        border-color: #334155;
                        background-color: #162032;
                    }
                """)

    def _toggle_advanced_calib(self):
        self.is_adv_calib_open = not self.is_adv_calib_open
        self.adv_drawer.setVisible(self.is_adv_calib_open)
        self.btn_toggle_adv.setText("Hide Advanced Filter Settings ▲" if self.is_adv_calib_open else "Show Advanced Filter Settings ▼")

    def _on_smooth_slider_changed(self, val: int):
        alpha = val / 100.0
        self.lbl_smooth.setText(f"EMA Motion Smoothing: {alpha:.2f}")
        self.cfg["smoothing_alpha"] = alpha
        self._save_settings()

    def _on_conf_slider_changed(self, val: int):
        conf = val / 100.0
        self.lbl_conf.setText(f"MediaPipe Detection Confidence: {conf:.2f}")
        self.cfg["detection_confidence"] = conf
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
