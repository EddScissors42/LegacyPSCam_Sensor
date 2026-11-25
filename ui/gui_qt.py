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
from typing import Any, Dict, List, Optional

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
    QFrame, QSlider, QMessageBox, QScrollArea, QLineEdit, QGridLayout,
    QDialog, QFileDialog
)
from PySide6.QtGui import (
    QPixmap, QIcon, QImage, QPainter, QPen, QColor, QPainterPath
)

from ui.theme import (
    PALETTE, CALIB_PRESETS,
    FONT_TITLE, FONT_HEADING, FONT_BODY,
    load_custom_fonts_qt
)
from ui.widgets import (
    pil_to_qpixmap,
    SlidingStackedWidget,
    DeviceNavCard,
    CalibPresetCard
)
from ui.pages import UIPagesMixin
from ui.styles import build_main_stylesheet
from ui.device_readout_mixin import UIDeviceReadoutMixin
from ui.benchmark_dialog import (
    TelemetryBenchmarkChart,
    TelemetryBenchmarkDialog
)
from ui.icons import (
    generate_icons_pil,
    generate_ds4_icons_pil,
    generate_phone_cam_icons_pil,
    generate_tab_icons_pil,
    generate_controller_tab_icon_pil,
    generate_mode_icons_pil,
    generate_status_icons_pil
)
from assets import (
    ICON_APP_ICO_PATH,
    ICON_PSCAMERA_PATH,
    ICON_ARROW_DOWN_PATH,
    ICON_DUALSHOCK4_PATH,
    ICON_CONTROLLER_PATH
)
from version import WINDOW_TITLE, VERSION_STRING, APP_NAME
from sensor.config_manager import ConfigManager, parse_preset, PRESETS_PSCAM, PRESETS_WEBCAM, PRESETS_PHONE_CAM
from sensor.camera_manager import CameraManager
from sensor.kinect_shared_memory import KinectBridge, get_kinect_bridge, close_kinect_bridge
from sensor.kinect_emulator import KinectEmulatorDaemon, get_kinect_emulator
from sensor import tracking_session
from .controllers import SensorAppController
import sensor

# Lazy wrappers for secondary modules (PEP 562 zero-overhead import at startup)
def get_phone_camera_server(*args, **kwargs):
    return sensor.get_phone_camera_server(*args, **kwargs)

class _LazyQRCodeGenerator:
    def __getattr__(self, name):
        return getattr(sensor.QRCodeGenerator, name)
QRCodeGenerator = _LazyQRCodeGenerator()

def get_virtual_phone(*args, **kwargs):
    return sensor.get_virtual_phone(*args, **kwargs)

def get_ds4_controller(*args, **kwargs):
    return sensor.get_ds4_controller(*args, **kwargs)

def find_ds4_devices(*args, **kwargs):
    return sensor.find_ds4_devices(*args, **kwargs)

def detect_controller_name(*args, **kwargs):
    return sensor.detect_controller_name(*args, **kwargs)

def parse_telemetry_csv(*args, **kwargs):
    return sensor.parse_telemetry_csv(*args, **kwargs)

def compare_telemetries(*args, **kwargs):
    return sensor.compare_telemetries(*args, **kwargs)

def find_available_benchmarks(*args, **kwargs):
    return sensor.find_available_benchmarks(*args, **kwargs)


class LegacySensorQtGUI(QMainWindow, UIPagesMixin, UIDeviceReadoutMixin):
    """Modern Crisp-White & PlayStation Blue primary window in Qt 6."""
    cameras_refreshed_signal = Signal(list)
    tracking_finished_signal = Signal(bool, str)
    model_download_signal = Signal(str, int, str)
    phone_firewall_signal = Signal(bool, str)

    def __init__(self, parent=None, *args, auto_discover=True, controller: Optional[SensorAppController] = None, **kwargs):
        if parent is not None and not isinstance(parent, QWidget):
            parent = None
        super().__init__(parent)
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(960, 640)
        self.setMinimumSize(920, 500)
        win_icon = ICON_APP_ICO_PATH if (ICON_APP_ICO_PATH and ICON_APP_ICO_PATH.exists()) else ICON_PSCAMERA_PATH
        if win_icon and win_icon.exists():
            self.setWindowIcon(QIcon(str(win_icon)))

        # Register bundled custom fonts (Kanit, National Park, Inter Tight)
        loaded_fonts = load_custom_fonts_qt()
        self.font_title = loaded_fonts.get("title", FONT_TITLE)
        self.font_heading = loaded_fonts.get("heading", FONT_HEADING)
        self.font_body = loaded_fonts.get("body", FONT_BODY)

        # Configuration and decoupled application controller facade
        self.cfg_mgr = ConfigManager()
        self.cfg = self.cfg_mgr.config
        # Stereo Vision is always enabled by default on PlayStation 4 Camera
        if str(self.cfg.get("stereo_mode", "")).strip().lower() in ("", "disabled", "false", "0"):
            self.cfg["stereo_mode"] = "sparse_metric"
        # Keep Auto-Frame zoom rock-steady (migrates legacy stale True values that caused zoom pumping)
        if self.cfg.get("face_follow_adaptive_zoom", False):
            self.cfg["face_follow_adaptive_zoom"] = False
        self.controller = controller or SensorAppController(self.cfg_mgr, parent=self)

        # Initialize shared memory bridges immediately on startup so Just Dance connects seamlessly
        self.bridge = get_kinect_bridge()
        self.controller.session.start_kinect_emulator()
        self.kinect_emulator = self.controller.session.kinect_emulator

        self._current_pscam_state = "DISCONNECTED"
        self._is_refreshing_cams = False
        self.active_tab = "video"
        self.current_calib_preset = self.cfg.get("tracking_preset", "competitive")
        if self.current_calib_preset == "stable":
            self.current_calib_preset = "competitive"
            self.cfg["tracking_preset"] = "competitive"
        if self.current_calib_preset in CALIB_PRESETS:
            self.cfg["pose_model"] = CALIB_PRESETS[self.current_calib_preset].get("pose_model", "lite")
        elif str(self.cfg.get("pose_model", "")).strip().lower() == "heavy":
            self.cfg["pose_model"] = "full"
        self.is_adv_calib_open = False
        self._is_closing = False
        self._is_connecting_ds4 = False
        self.calib_cards = {}

        self._load_pixmaps()
        self._setup_palette()
        self._setup_style()
        self._build_ui()

        # Connect controller signals to UI presentation slots
        self.controller.cameras_refreshed.connect(self._on_cameras_refreshed)
        self.controller.pscam_state_changed.connect(self._apply_pscam_state)
        self.controller.tracking_finished.connect(self._on_tracking_finished)
        self.cameras_refreshed_signal.connect(self._on_cameras_refreshed)
        self.tracking_finished_signal.connect(self._on_tracking_finished)
        self.model_download_signal.connect(self._on_model_download_progress)
        self.phone_firewall_signal.connect(self._on_phone_firewall_finished)

        # Initial mode setup (already calls _update_pscam_status for camera modes)
        initial_mode = self.cfg.get("camera_mode", "pscam")
        self._set_mode(initial_mode, animate=False)
        if initial_mode == "ds4":
            self._update_pscam_status()
        self._update_start_button_state()

        if auto_discover:
            self._refresh_cameras_async()

            # Background MediaPipe pre-warming after the GUI window is already painted on screen
            QTimer.singleShot(350, self._prewarm_pose_engine_async)

            # Fast background camera pre-warming (400ms after GUI is visible)
            self._schedule_camera_warmup(400)

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

    def _prewarm_pose_engine_async(self):
        """Pre-loads MediaPipe / PoseTracker in a background thread after the window is visible."""
        if getattr(self, "_is_closing", False):
            return

        # Pre-fetch Full AI model into %APPDATA% cache if user already saved Balanced preset
        active_model = str(self.cfg.get("pose_model", "lite")).strip().lower()
        if active_model == "full":
            self._ensure_pose_model_async("full")

        if "mediapipe" in sys.modules:
            return

        def _warm_worker():
            try:
                import sensor.pose_tracker  # noqa: F401
            except Exception:
                pass

        threading.Thread(target=_warm_worker, daemon=True, name="MediaPipePrewarmThread").start()

    def _ensure_pose_model_async(self, variant: str):
        """
        Ensures the requested AI model variant (`lite` or `full`) is available in the local or
        persistent `%APPDATA%\\LegacyPSCam_Sensor\\models` cache without blocking the Qt UI thread.
        """
        if getattr(self, "_is_closing", False):
            return
        try:
            from sensor.model_manager import ModelManager
            norm = ModelManager.normalize_variant(variant)
            if ModelManager.is_model_ready(norm):
                return
        except Exception:
            return

        if getattr(self, "_downloading_model_variant", None) == norm:
            return
        self._downloading_model_variant = norm
        self.model_download_signal.emit(norm, 0, "downloading")

        def _dl_worker():
            try:
                from sensor.model_manager import ModelManager
                last_pct = [-1]

                def _cb(done: int, total: int):
                    pct = int(min(100, round((done * 100.0) / max(1, total))))
                    if pct != last_pct[0]:
                        last_pct[0] = pct
                        self.model_download_signal.emit(norm, pct, "downloading")

                res = ModelManager.download_model(norm, progress_cb=_cb)
                if res is not None:
                    self.model_download_signal.emit(norm, 100, "done")
                else:
                    self.model_download_signal.emit(norm, -1, "offline")
            except Exception:
                self.model_download_signal.emit(norm, -1, "offline")
            finally:
                self._downloading_model_variant = None

        threading.Thread(target=_dl_worker, daemon=True, name=f"ModelDownload-{norm}").start()

    @Slot(str, int, str)
    def _on_model_download_progress(self, variant: str, pct: int, status: str):
        if not hasattr(self, "model_dl_box") or not hasattr(self, "lbl_model_dl_status"):
            return
        label = "Balanced (Full AI)" if variant == "full" else "Competitive (Lite AI)"
        if status == "downloading":
            self.model_dl_box.setStyleSheet(
                "QFrame#modelDownloadBox { background-color: #EFF6FF; border: 1px solid #93C5FD; border-radius: 8px; }"
            )
            self.lbl_model_dl_status.setText(
                f"Downloading {label} model to persistent cache (%APPDATA%)... {max(0, pct)}%"
            )
            self.model_dl_box.setVisible(True)
        elif status == "done":
            self.model_dl_box.setStyleSheet(
                "QFrame#modelDownloadBox { background-color: #ECFDF5; border: 1px solid #6EE7B7; border-radius: 8px; }"
            )
            self.lbl_model_dl_status.setText(
                f"{label} model cached in %APPDATA% — Ready for instant launch!"
            )
            self.model_dl_box.setVisible(True)
            QTimer.singleShot(3000, lambda: self.model_dl_box.setVisible(False) if hasattr(self, "model_dl_box") else None)
        else:
            self.model_dl_box.setStyleSheet(
                "QFrame#modelDownloadBox { background-color: #FEF3C7; border: 1px solid #FCD34D; border-radius: 8px; }"
            )
            self.lbl_model_dl_status.setText(
                f"Could not download {label} (offline). Lite AI will be used automatically until connected."
            )
            self.model_dl_box.setVisible(True)

    # =========================================================================
    # CONTROLLER DELEGATES & COMPATIBILITY PROPERTIES
    # =========================================================================
    @property
    def vphone(self):
        return self.controller.devices.vphone

    @vphone.setter
    def vphone(self, val):
        self.controller.devices._vphone = val

    @property
    def camera_list(self):
        return self.controller.camera.camera_list

    @camera_list.setter
    def camera_list(self, val):
        self.controller.camera.camera_list = val

    @property
    def is_tracking_active(self):
        return self.controller.session.is_tracking_active

    @is_tracking_active.setter
    def is_tracking_active(self, val):
        self.controller.session.is_tracking_active = bool(val)

    @property
    def _tracking_stop_event(self):
        return self.controller.session._tracking_stop_event

    @property
    def _prewarmed_camera(self):
        return self.controller.camera._prewarmed_camera

    @_prewarmed_camera.setter
    def _prewarmed_camera(self, val):
        self.controller.camera._prewarmed_camera = val

    def _schedule_camera_warmup(self, delay_ms: int = 350):
        self.controller.camera.schedule_warmup(delay_ms)

    def _cancel_camera_warmup(self, sync: bool = False):
        self.controller.camera.cancel_warmup(sync=sync)

    def _start_camera_warmup_async(self):
        self.controller.camera.start_warmup_async()

    def _take_prewarmed_camera(self):
        return self.controller.camera.take_prewarmed_camera()

    def _init_ds4_config(self):
        self.controller.devices._init_ds4_config()

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
            p_ph_act, p_ph_inact = generate_phone_cam_icons_pil(target_box=(38, 26), scale=4)
            self.pix_phone_act = pil_to_qpixmap(p_ph_act, dpr=4.0)
            self.pix_phone_inact = pil_to_qpixmap(p_ph_inact, dpr=4.0)
        except Exception as e:
            print(f"[WARN] Failed to load Phone Camera icons: {e}")
            self.pix_phone_act = self.pix_phone_inact = QPixmap()

        try:
            p_gear_act, p_gear_inact, p_slid_act, p_slid_inact, p_slid_dis, p_lab_act, p_lab_inact = generate_tab_icons_pil(size=(18, 18), scale=4)
            self.pix_gear_act = pil_to_qpixmap(p_gear_act, dpr=4.0)
            self.pix_gear_inact = pil_to_qpixmap(p_gear_inact, dpr=4.0)
            self.pix_track_act = self.pix_slid_act = pil_to_qpixmap(p_slid_act, dpr=4.0)
            self.pix_track_inact = self.pix_slid_inact = pil_to_qpixmap(p_slid_inact, dpr=4.0)
            self.pix_track_disabled = self.pix_slid_disabled = pil_to_qpixmap(p_slid_dis, dpr=4.0)
            self.pix_lab_act = pil_to_qpixmap(p_lab_act, dpr=4.0)
            self.pix_lab_inact = pil_to_qpixmap(p_lab_inact, dpr=4.0)
        except Exception as e:
            print(f"[WARN] Failed to load tab icons: {e}")
            self.pix_gear_act = self.pix_gear_inact = self.pix_track_act = self.pix_track_inact = self.pix_track_disabled = self.pix_slid_act = self.pix_slid_inact = self.pix_slid_disabled = self.pix_lab_act = self.pix_lab_inact = QPixmap()

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

    def _setup_palette(self):
        """Forces an explicit Light palette so Windows Dark Mode doesn't render combo popups in black."""
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
        self.setPalette(pal)
        app = QApplication.instance()
        if app is not None:
            app.setPalette(pal)

    def _setup_style(self):
        """Applies the Crisp White & PlayStation Blue stylesheet (QSS)."""
        arrow_url = str(ICON_ARROW_DOWN_PATH).replace("\\", "/")
        self.setStyleSheet(build_main_stylesheet(self.font_body, self.font_heading, arrow_url))

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
            "USB Adapter",
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
            "USB or Bluetooth",
            self.font_heading,
            self.font_body,
            self.sidebar_frame
        )
        self.card_ds4.set_icons(self.pix_ds4_act, self.pix_ds4_inact)
        self.card_ds4.clicked.connect(lambda: self._set_mode("ds4"))
        sidebar_layout.addWidget(self.card_ds4)
        sidebar_layout.addSpacing(8)

        # 1.6 Card Phone Camera (Android or iOS via Wi-Fi WebApp QR Code)
        self.card_phone_cam = DeviceNavCard(
            "Phone Camera",
            "Android or iOS with Wi-Fi",
            self.font_heading,
            self.font_body,
            self.sidebar_frame
        )
        self.card_phone_cam.set_icons(self.pix_phone_act, self.pix_phone_inact)
        self.card_phone_cam.clicked.connect(lambda: self._set_mode("phone_cam"))
        sidebar_layout.addWidget(self.card_phone_cam)
        sidebar_layout.addStretch()

        # 1.6 Quick Action: Open Logs Folder
        self.btn_logs_folder = QPushButton("Open Logs Folder", self.sidebar_frame)
        self.btn_logs_folder.setProperty("class", "btn_secondary")
        self.btn_logs_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_logs_folder.clicked.connect(self._open_logs_folder)
        sidebar_layout.addWidget(self.btn_logs_folder)
        sidebar_layout.addSpacing(10)

        # 1.7 Mini Credits
        lbl_cred1 = QLabel("Original Legacy Sensor by itsVexor", self.sidebar_frame)
        lbl_cred1.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 10px; color: {PALETTE['text_muted']}; background: transparent;"
        )
        lbl_cred3 = QLabel("Made by Edd", self.sidebar_frame)
        lbl_cred3.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 10px; color: {PALETTE['text_muted']}; background: transparent;"
        )
        sidebar_layout.addWidget(lbl_cred1)
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

        self.btn_tab_calib = QPushButton("  Tracking", self.content_widget)
        self.btn_tab_calib.setFixedSize(130, 42)
        self.btn_tab_calib.setIcon(QIcon(self.pix_slid_inact))
        self.btn_tab_calib.setIconSize(QSize(18, 18))
        self.btn_tab_calib.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_tab_calib.clicked.connect(lambda: self._switch_tab("calib"))
        self.btn_tab_tracking = self.btn_tab_calib

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

        top_nav_layout.setSpacing(10)
        top_nav_layout.addStretch()
        top_nav_layout.addWidget(self.btn_tab_video)
        top_nav_layout.addWidget(self.btn_tab_calib)
        top_nav_layout.addWidget(self.btn_tab_controller)
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

        # Build Page 0 (Video), Page 1 (Calibration), Page 2 (Experimental) & Page 3 (DualShock 4)
        self._build_video_view()
        self._build_calib_view()
        self._build_exp_view()
        self._build_ds4_view()

        # 2.3 Bottom Action Area (PlayStation Blue CTA, Red Disconnect & Footer)
        self.bottom_action_layout = QHBoxLayout()
        self.bottom_action_layout.setContentsMargins(0, 0, 0, 0)
        self.bottom_action_layout.setSpacing(10)

        self.btn_start = QPushButton("START TRACKING", self.content_widget)
        self.btn_start.setProperty("class", "btn_cta")
        self.btn_start.setFixedHeight(48)
        self.btn_start.setEnabled(False)
        self.btn_start.setVisible(False)
        self.btn_start.setCursor(Qt.CursorShape.ForbiddenCursor)
        self.btn_start.clicked.connect(self._start_tracking)
        self.bottom_action_layout.addWidget(self.btn_start, stretch=1)

        self.btn_bottom_disconnect_phone = QPushButton("DISCONNECT", self.content_widget)
        self.btn_bottom_disconnect_phone.setFixedHeight(48)
        self.btn_bottom_disconnect_phone.setFixedWidth(140)
        self.btn_bottom_disconnect_phone.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_bottom_disconnect_phone.setToolTip("Disconnect connected smartphone and show QR Code again")
        self.btn_bottom_disconnect_phone.setStyleSheet(f"""
            QPushButton {{
                background-color: #DC2626;
                color: #FFFFFF;
                border: none;
                border-radius: 10px;
                font-family: '{self.font_heading}', sans-serif;
                font-size: 13px;
                font-weight: bold;
                padding: 0 16px;
            }}
            QPushButton:hover {{
                background-color: #B91C1C;
            }}
            QPushButton:pressed {{
                background-color: #991B1B;
            }}
        """)
        self.btn_bottom_disconnect_phone.clicked.connect(self._on_disconnect_phone_cam)
        self.btn_bottom_disconnect_phone.setVisible(False)
        self.btn_disconnect_phone = self.btn_bottom_disconnect_phone
        self.bottom_action_layout.addWidget(self.btn_bottom_disconnect_phone)

        content_layout.addLayout(self.bottom_action_layout)

        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(0, 2, 0, 0)
        lbl_ver = QLabel(VERSION_STRING, self.content_widget)
        lbl_ver.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 11px; color: {PALETTE['text_dim']}; background: transparent;"
        )
        footer_layout.addStretch()
        footer_layout.addWidget(lbl_ver)
        content_layout.addLayout(footer_layout)

        master_layout.addWidget(self.content_widget, stretch=1)

        # Enforce clean light palette on all combobox popup views preserving their native style
        for cb in self.findChildren(QComboBox):
            cb.view().setStyleSheet(
                f"background-color: #FFFFFF; color: {PALETTE['text_main']}; "
                f"selection-background-color: {PALETTE['ps_blue']}; selection-color: #FFFFFF;"
            )

    # =========================================================================
    # UI STATE MANAGEMENT & VISIBILITY
    # =========================================================================
    def is_camera_accessible(self) -> bool:
        """Returns True if the currently selected camera device is connected and accessible."""
        return self.controller.camera.is_camera_accessible(self.cfg.get("camera_mode", "pscam"))

    def is_device_ready_for_tracking(self, mode: Optional[str] = None) -> bool:
        """Returns True if the peripheral/camera corresponding to the active mode is connected and ready."""
        m = mode or self.cfg.get("camera_mode", "pscam")
        if m == "ds4":
            try:
                st = self.controller.devices.get_ds4_readout()
                return bool(st.get("is_connected", False))
            except Exception:
                return False
        elif m == "pscam":
            return (getattr(self, "_current_pscam_state", "DISCONNECTED") == "READY")
        elif m == "phone_cam":
            try:
                st = self.controller.devices.get_phone_cam_status()
                return bool(st.get("is_connected", False))
            except Exception:
                return False
        else:  # webcam
            cams = getattr(self, "camera_list", [])
            webcams = [c for c in cams if not c.is_pscam]
            if not webcams and not any(c.is_pscam for c in cams):
                webcams = cams
            return len(webcams) > 0

    def _update_start_button_state(self):
        """
        Dynamically updates the enabled state, text, cursor and tooltip of the primary CTA
        button (btn_start) based on whether tracking is currently active and whether the
        hardware/stream required for the active mode is fully connected and ready.
        """
        if not hasattr(self, "btn_start"):
            return

        if getattr(self, "is_tracking_active", False):
            self.btn_start.setText("TRACKING IN PROGRESS...")
            self.btn_start.setEnabled(False)
            self.btn_start.setCursor(Qt.CursorShape.ForbiddenCursor)
            self.btn_start.setToolTip("Dance tracking is currently active.")
            return

        mode = self.cfg.get("camera_mode", "pscam")
        ready = self.is_device_ready_for_tracking(mode)

        if mode == "ds4":
            if hasattr(self, "btn_bottom_disconnect_phone"):
                self.btn_bottom_disconnect_phone.setVisible(False)
            self.btn_start.setText("START CONTROLLER (DS4)")
            self.btn_start.setEnabled(ready)
            self.btn_start.setVisible(ready)
            if ready:
                self.btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
                self.btn_start.setToolTip("Start motion tracking with DualShock 4 controller")
            else:
                self.btn_start.setCursor(Qt.CursorShape.ForbiddenCursor)
                self.btn_start.setToolTip("DualShock 4 not connected. Connect via USB cable or pair via Bluetooth.")
        elif mode == "pscam":
            if hasattr(self, "btn_bottom_disconnect_phone"):
                self.btn_bottom_disconnect_phone.setVisible(False)
            self.btn_start.setText("START TRACKING")
            self.btn_start.setEnabled(ready)
            self.btn_start.setVisible(ready)
            if ready:
                self.btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
                self.btn_start.setToolTip("Start tracking with PlayStation Camera (60 FPS)")
            else:
                self.btn_start.setCursor(Qt.CursorShape.ForbiddenCursor)
                self.btn_start.setToolTip("PlayStation Camera not connected. Connect via USB 3.0 to start tracking.")
        elif mode == "phone_cam":
            self.btn_start.setText("START TRACKING")
            self.btn_start.setEnabled(ready)
            self.btn_start.setVisible(ready)
            if ready:
                self.btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
                self.btn_start.setToolTip("Start tracking with connected Smartphone Camera")
                if hasattr(self, "btn_bottom_disconnect_phone"):
                    self.btn_bottom_disconnect_phone.setVisible(True)
            else:
                self.btn_start.setCursor(Qt.CursorShape.ForbiddenCursor)
                self.btn_start.setToolTip("Smartphone not connected. Scan the QR code to connect your phone.")
                if hasattr(self, "btn_bottom_disconnect_phone"):
                    self.btn_bottom_disconnect_phone.setVisible(False)
        else:  # webcam
            if hasattr(self, "btn_bottom_disconnect_phone"):
                self.btn_bottom_disconnect_phone.setVisible(False)
            self.btn_start.setText("START TRACKING")
            self.btn_start.setEnabled(ready)
            self.btn_start.setVisible(ready)
            if ready:
                self.btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
                self.btn_start.setToolTip("Start tracking with selected Webcam")
            else:
                self.btn_start.setCursor(Qt.CursorShape.ForbiddenCursor)
                self.btn_start.setToolTip("No webcam detected. Connect a camera to start tracking.")

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
                fallback = "controller" if self.cfg.get("camera_mode") == "ds4" else "video"
                self._switch_tab(fallback)
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
                self.btn_tab_exp.setVisible(True)
            if hasattr(self, "btn_tab_controller"):
                self.btn_tab_controller.setVisible(True)
            self._switch_tab("controller")
            if hasattr(self, "btn_start"):
                self.btn_start.setText("START CONTROLLER (DS4)")
            self._cancel_camera_warmup(sync=True)
            self._update_ds4_ui_readout()
            def _connect_done(_ok):
                try:
                    QtCore.QMetaObject.invokeMethod(self, "_finish_ds4_reconnect", Qt.ConnectionType.QueuedConnection)
                except (RuntimeError, Exception):
                    pass
            self.controller.devices.connect_ds4_async(callback=_connect_done)
        else:
            if hasattr(self, "btn_tab_controller"):
                self.btn_tab_controller.setVisible(False)
            if hasattr(self, "btn_tab_video"):
                self.btn_tab_video.setVisible(True)
            if hasattr(self, "btn_tab_calib"):
                self.btn_tab_calib.setVisible(True)
            if hasattr(self, "btn_tab_exp"):
                self.btn_tab_exp.setVisible(True)
            if mode == "phone_cam":
                self._cancel_camera_warmup(sync=True)
                self._ensure_phone_cam_server_started()
                self._refresh_phone_cam_qr()
                self._update_phone_cam_status()
            else:
                self._schedule_camera_warmup(300)
            self._refresh_presets()
            self._update_camera_dropdown_for_mode()
            self._update_pscam_status()
            self._update_video_view_visibility()
            self._switch_tab("video")
            if hasattr(self, "btn_start"):
                self.btn_start.setText("START TRACKING")
        self._update_exp_view_for_mode(mode)
        self._update_start_button_state()
        self._save_settings()

    def _update_sidebar_buttons(self):
        mode = self.cfg.get("camera_mode", "pscam")
        self.card_pscam.set_active(mode == "pscam")
        self.card_webcam.set_active(mode == "webcam")
        if hasattr(self, "card_phone_cam"):
            self.card_phone_cam.set_active(mode == "phone_cam")
        if hasattr(self, "card_ds4"):
            self.card_ds4.set_active(mode == "ds4")

    def _update_video_view_visibility(self):
        """
        State-aware visibility controller:
        - When DISCONNECTED: The balloon (and QR Code for Phone Camera) is the ONLY THING displayed.
        - When CONNECTED: The balloon/QR disappears; the options card and Additional Display Options are displayed.
        """
        mode = self.cfg.get("camera_mode", "pscam")
        cams = getattr(self, "camera_list", [])

        if hasattr(self, "phone_cam_disconnected_box"):
            self.phone_cam_disconnected_box.setVisible(False)
        if hasattr(self, "phone_cam_card"):
            self.phone_cam_card.setVisible(False)

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
        elif mode == "phone_cam":
            self.pscam_disconnected_box.setVisible(False)
            self.pscam_card.setVisible(False)
            self.webcam_disconnected_box.setVisible(False)
            self.webcam_card.setVisible(False)

            is_phone_conn = bool(get_phone_camera_server().is_client_connected)
            if not is_phone_conn:
                if hasattr(self, "phone_cam_card"):
                    self.phone_cam_card.setVisible(False)
                self.display_card.setVisible(False)
                if hasattr(self, "phone_cam_disconnected_box"):
                    self.phone_cam_disconnected_box.setVisible(True)
            else:
                if hasattr(self, "phone_cam_disconnected_box"):
                    self.phone_cam_disconnected_box.setVisible(False)
                if hasattr(self, "phone_cam_card"):
                    self.phone_cam_card.setVisible(True)
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
        self._update_start_button_state()

    def _refresh_presets(self):
        mode = self.cfg.get("camera_mode", "pscam")
        if mode == "pscam":
            presets = PRESETS_PSCAM
            current = self.cfg.get("pscam_preset", presets[0])
        elif mode == "phone_cam":
            presets = PRESETS_PHONE_CAM
            current = self.cfg.get("phone_cam_preset", presets[0])
        else:
            presets = PRESETS_WEBCAM
            current = self.cfg.get("webcam_preset", presets[0])
        w, h, fps = parse_preset(current)
        res_str = f"{w}x{h}"
        fps_str = f"{fps} FPS"

        if hasattr(self, "cb_phone_res") and hasattr(self, "cb_phone_fps"):
            p_w, p_h, p_fps = parse_preset(self.cfg.get("phone_cam_preset", PRESETS_PHONE_CAM[0]))
            self.cb_phone_res.blockSignals(True)
            self.cb_phone_fps.blockSignals(True)
            idx_pr = self.cb_phone_res.findText(f"{p_w}x{p_h}", Qt.MatchFlag.MatchStartsWith)
            self.cb_phone_res.setCurrentIndex(max(0, idx_pr))
            idx_pf = self.cb_phone_fps.findText(f"{p_fps} FPS", Qt.MatchFlag.MatchStartsWith)
            self.cb_phone_fps.setCurrentIndex(max(0, idx_pf))
            self.cb_phone_res.blockSignals(False)
            self.cb_phone_fps.blockSignals(False)

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
        info = self.controller.camera.get_ps4_state()
        self._apply_pscam_state(info)

    def _apply_pscam_state(self, ps4_info: dict):
        state = ps4_info.get("state", "DISCONNECTED")
        self._current_pscam_state = state

        if state in ("NOT_INSTALLED", "DISCONNECTED"):
            self.lbl_pscam_icon.setPixmap(self.pix_status_err)
            self.lbl_pscam_conn_title.setText("PlayStation Camera not connected")
            self.lbl_pscam_info.setText("Connect camera to USB 3.0 Port (AUX adapter required)")
            self.lbl_pscam_info.setStyleSheet(
                f"font-family: '{self.font_body}'; font-size: 11px; color: {PALETTE['text_muted']}; background: transparent; border: none;"
            )

        elif state in ("DRIVER_STOPPED", "BOOTLOADER_UPLOADING", "WAITING_VCAM"):
            self.lbl_pscam_icon.setPixmap(self.pix_status_warn)
            self.lbl_pscam_conn_title.setText("PlayStation Camera initializing")
            self.lbl_pscam_info.setText("Camera detected! Initializing high-speed 60 FPS video stream...")
            self.lbl_pscam_info.setStyleSheet(
                f"font-family: '{self.font_body}'; font-size: 11px; color: {PALETTE['ps_blue']}; background: transparent; border: none;"
            )

        elif state == "READY":
            self.lbl_pscam_icon.setPixmap(self.pix_status_ok)
            self.lbl_pscam_conn_title.setText("PlayStation Camera connected")
            eye_label = "Left Eye" if str(self.cfg.get("ps4_eye", "right")).lower() == "left" else "Right Eye"
            cams = getattr(self, "camera_list", [])
            ps_cams = [c for c in cams if c.is_pscam]
            if ps_cams:
                cam_idx = ps_cams[0].index
                txt = f"PlayStation®Camera connected (Index {cam_idx} • {eye_label} • 60 FPS)"
            else:
                txt = f"PlayStation®Camera connected ({eye_label} • 60 FPS)"
            self.lbl_pscam_ready_info.setText(txt)

        self._update_video_view_visibility()

    def _periodic_check(self):
        diag = self.controller.periodic_check()
        if self.cfg.get("camera_mode") == "phone_cam":
            self._update_phone_cam_status()

    def _refresh_cameras(self):
        self._refresh_cameras_async()

    def _refresh_cameras_async(self):
        if hasattr(self, "btn_refresh"):
            self.btn_refresh.setEnabled(False)
            self.btn_refresh.setText("…")
        if hasattr(self, "btn_refresh_webcam"):
            self.btn_refresh_webcam.setEnabled(False)
            self.btn_refresh_webcam.setText("Searching...")
        self.controller.camera.refresh_cameras_async()

    @Slot(list)
    def _on_cameras_refreshed(self, cams):
        if getattr(self, "_is_closing", False):
            return
        self.camera_list = cams
        if hasattr(self, "btn_refresh"):
            self.btn_refresh.setEnabled(True)
            self.btn_refresh.setText("↻")
        if hasattr(self, "btn_refresh_webcam"):
            self.btn_refresh_webcam.setEnabled(True)
            self.btn_refresh_webcam.setText("Search for Webcams")
        self._update_pscam_status()
        self._update_camera_dropdown_for_mode()
        self._update_start_button_state()

    def _on_camera_selected(self, index: int):
        sel_text = self.cb_cameras.currentText()
        for c in self.camera_list:
            if str(c) == sel_text:
                self.cfg["camera_index"] = c.index
                self._save_settings()
                self._schedule_camera_warmup(300)
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
        self._schedule_camera_warmup(300)

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
        self._schedule_camera_warmup(300)

    def _on_display_options_changed(self):
        self.cfg["show_hud"] = self.chk_hud.isChecked()
        self.cfg["face_follow_enabled"] = self.chk_face.isChecked()
        self._save_settings()

    def _on_orientation_changed(self, index: int):
        orientations = [0, 90, 180, 270]
        angle = orientations[index] if 0 <= index < len(orientations) else 0
        self.cfg["camera_orientation"] = angle
        self._save_settings()
        self._schedule_camera_warmup(300)

    def _on_ps4_eye_changed(self, index: int):
        self.cfg["ps4_eye"] = "left" if index == 1 else "right"
        self._save_settings()
        self._update_pscam_status()
        self._schedule_camera_warmup(300)

    # =========================================================================
    # PHONE CAMERA (WI-FI WEBAPP & QR CODE) HANDLERS
    # =========================================================================
    def _ensure_phone_cam_server_started(self):
        return self.controller.devices.ensure_phone_cam_server_started()

    def _refresh_phone_cam_ip_selector(self):
        if not hasattr(self, "cb_phone_cam_ip"):
            return
        try:
            items, active_ip = self.controller.devices.list_phone_cam_ips()
            self.cb_phone_cam_ip.blockSignals(True)
            self.cb_phone_cam_ip.clear()
            sel_idx = 0
            for idx, item in enumerate(items):
                ip_val = item.get("ip", "")
                label = item.get("label", ip_val)
                self.cb_phone_cam_ip.addItem(label, ip_val)
                if ip_val == active_ip:
                    sel_idx = idx
            if self.cb_phone_cam_ip.count() > 0:
                self.cb_phone_cam_ip.setCurrentIndex(sel_idx)
            self.cb_phone_cam_ip.blockSignals(False)
        except Exception:
            try:
                self.cb_phone_cam_ip.blockSignals(False)
            except Exception:
                pass

    def _refresh_phone_cam_firewall_button(self):
        if not hasattr(self, "btn_phone_firewall"):
            return
        try:
            fw = self.controller.devices.get_phone_cam_firewall_status()
            port = fw.get("port", 8443)
            if fw.get("port_rule_allowed"):
                self.btn_phone_firewall.setText("Firewall OK ✓")
                self.btn_phone_firewall.setStyleSheet(
                    f"background-color: #ECFDF5; color: #047857; border: 1px solid #6EE7B7; "
                    f"border-radius: 6px; padding: 0 10px; font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold;"
                )
                self.btn_phone_firewall.setToolTip(
                    f"Windows Firewall allows inbound TCP port {port} on Private & Public Wi-Fi. Click to re-apply rule."
                )
            else:
                self.btn_phone_firewall.setText("Allow Firewall")
                self.btn_phone_firewall.setStyleSheet(
                    f"background-color: #FEF3C7; color: #92400E; border: 1px solid #F59E0B; "
                    f"border-radius: 6px; padding: 0 10px; font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold;"
                )
                self.btn_phone_firewall.setToolTip(
                    f"Windows Firewall rule for TCP port {port} not found. Click to allow Private & Public Wi-Fi and prevent ERR_CONNECTION_TIMED_OUT."
                )
        except Exception:
            pass

    def _on_phone_cam_ip_changed(self, _index: int = 0):
        if not hasattr(self, "cb_phone_cam_ip"):
            return
        selected_ip = self.cb_phone_cam_ip.currentData()
        if selected_ip:
            self.controller.devices.set_phone_cam_ip(str(selected_ip))
            self._refresh_phone_cam_qr(rotate_token=False, refresh_adapters=False)

    def _on_allow_phone_cam_firewall(self):
        if hasattr(self, "btn_phone_firewall"):
            self.btn_phone_firewall.setEnabled(False)
            self.btn_phone_firewall.setText("Allowing...")
        self.controller.devices.allow_phone_cam_firewall_async(
            callback=lambda ok, msg: self.phone_firewall_signal.emit(bool(ok), str(msg))
        )

    @Slot(bool, str)
    def _on_phone_firewall_finished(self, ok: bool, msg: str):
        if hasattr(self, "btn_phone_firewall"):
            self.btn_phone_firewall.setEnabled(True)
        self._refresh_phone_cam_firewall_button()
        if ok:
            QMessageBox.information(self, "Windows Firewall Updated", msg)
        else:
            QMessageBox.warning(self, "Windows Firewall", msg)

    def _refresh_phone_cam_qr(self, _checked: bool = False, rotate_token: bool = False, refresh_adapters: bool = True):
        if refresh_adapters:
            self._refresh_phone_cam_ip_selector()
        self._refresh_phone_cam_firewall_button()
        pil_qr, url = self.controller.devices.render_pairing_qr_image(rotate_token=rotate_token)
        if hasattr(self, "lbl_phone_cam_url"):
            self.lbl_phone_cam_url.setText(url)
        if hasattr(self, "lbl_phone_qr_img") and pil_qr is not None:
            try:
                pix_qr = pil_to_qpixmap(pil_qr, dpr=2.0)
                self.lbl_phone_qr_img.setPixmap(pix_qr)
            except Exception as e:
                print(f"[WARN] Failed to render Phone Camera QR Code: {e}")

    def _on_copy_phone_cam_url(self):
        url = self.controller.devices.get_phone_cam_url()
        cb = QApplication.clipboard()
        if cb is not None:
            cb.setText(url)
        if hasattr(self, "btn_copy_phone_url"):
            self.btn_copy_phone_url.setText("Copied!")
            QTimer.singleShot(1500, lambda: self.btn_copy_phone_url.setText("Copy URL") if hasattr(self, "btn_copy_phone_url") else None)

    def _on_phone_cam_settings_changed(self):
        if not hasattr(self, "cb_phone_res") or not hasattr(self, "cb_phone_fps"):
            return
        res = self.cb_phone_res.currentText().split()[0]
        fps_val = self.cb_phone_fps.currentText().split()[0]
        preset = f"{res} @ {fps_val} FPS"
        self.cfg["phone_cam_preset"] = preset
        self._save_settings()
        self.controller.devices.update_phone_cam_preset(preset)

    def _on_disconnect_phone_cam(self):
        if self.is_tracking_active and self.cfg.get("camera_mode") == "phone_cam":
            self.controller.session.stop_tracking()
        self.controller.devices.disconnect_phone_cam(rotate_token=True)
        self._refresh_phone_cam_qr(rotate_token=False)
        self._update_phone_cam_status()

    # =========================================================================
    # VIRTUAL PHONE CONTROLLER (CELULAR VIRTUAL) HANDLERS
    # =========================================================================
    def _on_vphone_toggle_changed(self):
        if self.cfg.get("camera_mode") == "ds4":
            return
        enabled = self.chk_vphone_enabled.isChecked()
        self.cfg["virtual_phone_enabled"] = enabled
        if hasattr(self, "vphone_details_frame"):
            self.vphone_details_frame.setVisible(enabled)
        self._apply_vphone_settings_to_controller()
        self.controller.devices.set_vphone_enabled(enabled)
        self._save_settings()
        self._update_vphone_ui_readout()

    def _on_vphone_sens_changed(self, val: int):
        sens = round(val / 100.0, 2)
        self.controller.devices.set_vphone_sensitivity(sens)
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
        sens = float(self.cfg.get("virtual_phone_sensitivity", 1.0))
        self.controller.devices.configure_vphone(host=host, port=port, hand=hand, sens=sens)

    def _on_vphone_reconnect_clicked(self):
        self._apply_vphone_settings_to_controller()
        self._save_settings()
        self.controller.devices.set_vphone_enabled(True)
        if hasattr(self, "chk_vphone_enabled"):
            self.chk_vphone_enabled.setChecked(True)
        self.controller.devices.request_vphone_reconnect()
        self._update_vphone_ui_readout()

    def _on_vphone_discover_clicked(self):
        if hasattr(self, "btn_vphone_discover"):
            self.btn_vphone_discover.setEnabled(False)
            self.btn_vphone_discover.setText("Searching...")

        def _done(ip, port, code):
            QtCore.QMetaObject.invokeMethod(
                self,
                "_on_vphone_discover_finished",
                Qt.ConnectionType.QueuedConnection,
                QtCore.Q_ARG(str, ip),
                QtCore.Q_ARG(int, port),
                QtCore.Q_ARG(str, code),
            )

        self.controller.devices.discover_vphone_server_async(callback=_done)

    def _on_skip_finish_clicked(self):
        """Sends the FTUE_FINISH shortcut packet for Just Dance 2022 phone tutorial."""
        if not self.vphone.enabled:
            self.controller.devices.set_vphone_enabled(True)
            if hasattr(self, "chk_vphone_enabled"):
                self.chk_vphone_enabled.setChecked(True)
        self.controller.devices.send_vphone_skip_finish()

    def _on_benchmark_toggle_changed(self, state):
        enabled = (state == Qt.CheckState.Checked.value or state == 2)
        if hasattr(self, "benchmark_details_frame"):
            self.benchmark_details_frame.setVisible(enabled)
        self.controller.devices.set_vphone_auto_record(enabled)
        self._update_vphone_ui_readout()

    def _on_benchmark_adaptive_changed(self, state):
        enabled = (state == Qt.CheckState.Checked.value or state == 2)
        self.controller.devices.set_vphone_adaptive(enabled)

    def _open_logs_folder(self):
        from sensor.config_manager import get_logs_dir
        logs_dir = get_logs_dir()
        try:
            from sensor.session_logger import get_session_logger
            get_session_logger().log_event("INFO", "GUI", f"User opened logs directory: {logs_dir}")
        except Exception:
            pass
        if sys.platform == "win32":
            os.startfile(str(logs_dir))
        else:
            import subprocess
            subprocess.Popen(["xdg-open", str(logs_dir)])

    def _on_vphone_auto_record_changed(self, state):
        self._on_benchmark_toggle_changed(state)

    def _on_vphone_adaptive_changed(self, state):
        self._on_benchmark_adaptive_changed(state)

    def _open_telemetry_benchmark_dialog(self):
        diag = TelemetryBenchmarkDialog(
            parent=self,
            current_sens=self.vphone.accelerometer.sensitivity,
        )
        diag.applied_sensitivity.connect(self._on_benchmark_sensitivity_applied)
        diag.exec()

    def _on_benchmark_sensitivity_applied(self, new_sens: float):
        sens_val = round(float(new_sens), 2)
        self.controller.devices.set_vphone_sensitivity(sens_val)

    # =========================================================================
    # DUALSHOCK 4 HANDLERS (Live Readouts delegated to UIDeviceReadoutMixin)
    # =========================================================================
    def _test_ds4_rumble(self):
        ok = self.controller.devices.trigger_test_rumble()
        if not ok:
            QMessageBox.information(
                self,
                "DualShock 4",
                "DualShock 4 is not connected. Please connect it via USB or pair via Windows Bluetooth settings."
            )

    def _reconnect_ds4(self):
        if hasattr(self, "lbl_ds4_conn_info"):
            self.lbl_ds4_conn_info.setText("Connecting to controller (USB / Bluetooth HID)...")
        def _done(_ok):
            try:
                QtCore.QMetaObject.invokeMethod(self, "_finish_ds4_reconnect", Qt.ConnectionType.QueuedConnection)
            except (RuntimeError, Exception):
                pass
        self.controller.devices.connect_ds4_async(callback=_done)

    @Slot()
    def _finish_ds4_reconnect(self):
        self._update_ds4_ui_readout()

    def _on_ds4_permissive_changed(self, state: int):
        val = (state == Qt.CheckState.Checked.value or state == 2)
        self.controller.devices.set_ds4_permissive(val)
        self._update_ds4_ui_readout()

    def _on_ds4_hand_changed(self, idx: int):
        hand = "right" if idx == 0 else "left"
        self.controller.devices.set_ds4_hand(hand)

    def _on_ds4_sens_changed(self, idx: int):
        sens_map = {0: 1.0, 1: 1.25, 2: 0.85}
        sens = sens_map.get(idx, 1.0)
        self.controller.devices.set_ds4_sensitivity(sens)

    def _select_calib_preset(self, preset_id: str):
        if preset_id not in CALIB_PRESETS:
            return
        self.current_calib_preset = preset_id
        self.cfg["tracking_preset"] = preset_id
        p = CALIB_PRESETS[preset_id]
        self.cfg["pose_model"] = p.get("pose_model", "lite")
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
        self._update_2p_warning_ui()
        self._save_settings()
        if str(self.cfg.get("pose_model", "lite")).strip().lower() == "full":
            self._ensure_pose_model_async("full")

    def _on_players_mode_changed(self, idx: int):
        max_p = 2 if idx == 1 else 1
        self.cfg["max_players"] = max_p
        self._update_2p_warning_ui()
        self._save_settings()

    def _update_2p_warning_ui(self):
        max_p = max(1, min(2, int(self.cfg.get("max_players", 1))))
        is_2p = (max_p >= 2)
        if hasattr(self, "two_player_warn_box"):
            self.two_player_warn_box.setVisible(is_2p)
        if hasattr(self, "lbl_2p_model_warning"):
            cur_model = str(self.cfg.get("pose_model", "lite")).strip().lower()
            if cur_model == "full":
                self.lbl_2p_model_warning.setText(
                    "2-Player Mode Active with Full AI: Tracking 2 dancers with Full AI doubles CPU load and may reduce FPS. "
                    "Switch to 'Competitive (Lite AI)' above for optimal 2-player performance."
                )
            else:
                self.lbl_2p_model_warning.setText(
                    "2-Player Mode Active: Lite AI (Competitive) is active and recommended to sustain stable FPS when tracking two dancers simultaneously."
                )

    def _update_calib_cards_ui(self):
        for pid, card in self.calib_cards.items():
            card.set_active(pid == self.current_calib_preset)
        self._update_2p_warning_ui()

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
            QMessageBox.information(self, "PlayStation Camera Backend", msg)
            self._refresh_cameras_async()
        else:
            QMessageBox.warning(self, "PlayStation Camera Backend", msg)

    def _start_tracking(self):
        if self.is_tracking_active:
            return
        if hasattr(self, "btn_start") and not self.btn_start.isEnabled():
            return

        mode = self.cfg.get("camera_mode", "pscam")
        ok, title, msg = self.controller.validate_pre_tracking(mode)
        if not ok:
            QMessageBox.warning(self, title, msg)
            return

        self._save_settings()

        started = self.controller.start_tracking()
        if not started:
            return

        if hasattr(self, "lbl_vphone_accel"):
            self.lbl_vphone_accel.setVisible(True)
        self.btn_start.setText("TRACKING IN PROGRESS...")
        self.btn_start.setEnabled(False)
        self.showMinimized()

    @Slot(bool, str)
    def _on_tracking_finished(self, success: bool, err_msg: str):
        self.is_tracking_active = False
        if hasattr(self, "lbl_vphone_accel"):
            self.lbl_vphone_accel.setVisible(False)
        self._update_start_button_state()
        self.showNormal()
        self.activateWindow()
        self._refresh_cameras()
        if self.cfg.get("camera_mode") == "phone_cam":
            self._update_phone_cam_status()
            if not get_phone_camera_server().is_client_connected:
                self._refresh_phone_cam_qr(rotate_token=False)

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
        self.controller.save_settings()

    def closeEvent(self, event):
        self._is_closing = True
        if hasattr(self, "timer_periodic") and self.timer_periodic is not None:
            self.timer_periodic.stop()
        if hasattr(self, "timer_vphone") and self.timer_vphone is not None:
            self.timer_vphone.stop()
        self.controller.cleanup()
        event.accept()


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("LegacyPSCam")
        except Exception:
            pass
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("LegacyPSCam")
    app.setApplicationDisplayName("LegacyPSCam")
    win_icon = ICON_APP_ICO_PATH if (ICON_APP_ICO_PATH and ICON_APP_ICO_PATH.exists()) else ICON_PSCAMERA_PATH
    if win_icon and win_icon.exists():
        app.setWindowIcon(QIcon(str(win_icon)))
    window = LegacySensorQtGUI()
    window.show()
    try:
        import pyi_splash  # type: ignore[import-not-found]
        if pyi_splash.is_alive():
            pyi_splash.close()
    except Exception:
        pass
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
