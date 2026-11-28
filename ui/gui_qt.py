"""
Modern PlayStation-Themed Qt 6 User Interface for Legacy PSCam Sensor.
Features:
- Crisp White & Iconic PlayStation Blue (#00439C) aesthetic matching the original design.
- Custom Typography:
  * 'Kanit' for the brand title ("Legacy PSCam Sensor")
  * 'National Park' for headings, navigation tabs, card titles, and interactive controls
  * 'Inter Tight' for body text, status diagnostics, descriptions, and metadata
- High-resolution supersampled Pillow icons converted directly to QPixmap.
- Modular architecture: window shell and lifecycle live here, page trees live in
  `ui/pages.py`, stylesheets in `ui/styles.py`, event/readout handlers in `ui/mixins/`,
  and hardware/session coordination in `ui/controllers/`.
"""
import sys
from pathlib import Path
from typing import Optional

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

from PySide6 import QtGui
from PySide6.QtCore import Qt, QTimer, QSize, Signal
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QFrame
)
from PySide6.QtGui import QPixmap, QIcon

from ui.theme import (
    PALETTE, CALIB_PRESETS,
    FONT_TITLE, FONT_HEADING, FONT_BODY,
    load_custom_fonts_qt
)
from ui.widgets import (
    pil_to_qpixmap,
    SlidingStackedWidget,
    DeviceNavCard,
)
from ui.pages import UIPagesMixin
from ui.styles import build_main_stylesheet
from ui.mixins import (
    UIDeviceReadoutMixin,
    UICameraHandlersMixin,
    UIPhoneHandlersMixin,
    UIDS4HandlersMixin,
    UITrackingHandlersMixin,
)
from ui.icons import (
    generate_icons_pil,
    generate_ds4_icons_pil,
    generate_phone_cam_icons_pil,
    generate_tab_icons_pil,
    generate_controller_tab_icon_pil,
    generate_mode_icons_pil,
    generate_status_icons_pil,
    generate_reload_icon_pil,
)
from assets import (
    ICON_APP_ICO_PATH,
    ICON_PSCAMERA_PATH,
    ICON_ARROW_DOWN_PATH,
)
from version import WINDOW_TITLE, VERSION_STRING
from sensor.config_manager import ConfigManager
from sensor.kinect_shared_memory import get_kinect_bridge
from .controllers import SensorAppController


class LegacySensorQtGUI(
    QMainWindow,
    UIPagesMixin,
    UIDeviceReadoutMixin,
    UICameraHandlersMixin,
    UIPhoneHandlersMixin,
    UIDS4HandlersMixin,
    UITrackingHandlersMixin,
):
    """Modern Crisp-White & PlayStation Blue primary window in Qt 6."""
    cameras_refreshed_signal = Signal(list)
    tracking_finished_signal = Signal(bool, str)
    model_download_signal = Signal(str, int, str)
    phone_firewall_signal = Signal(bool, str)
    pre_tracking_validated_signal = Signal(bool, str, str, str)

    def __init__(
        self,
        parent=None,
        *args,
        auto_discover: bool = True,
        controller: Optional[SensorAppController] = None,
        cli_overrides: Optional[dict] = None,
        **kwargs,
    ):
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
        if cli_overrides:
            self.cfg.update(cli_overrides)
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
        self.active_tab = "video"
        raw_preset = str(self.cfg.get("tracking_preset", "balanced")).strip().lower()
        saved_model = str(self.cfg.get("pose_model", "lite")).strip().lower()
        if saved_model == "heavy":
            saved_model = "full"
            self.cfg["pose_model"] = "full"
        # Clean migration from legacy presets ('competitive' -> 'balanced', legacy 'balanced'+full -> 'high')
        if raw_preset in ("stable", "competitive"):
            raw_preset = "balanced"
            self.cfg["tracking_preset"] = "balanced"
        elif raw_preset == "balanced" and saved_model == "full":
            raw_preset = "high"
            self.cfg["tracking_preset"] = "high"
        elif raw_preset not in CALIB_PRESETS:
            raw_preset = "balanced"
            self.cfg["tracking_preset"] = "balanced"
        self.current_calib_preset = raw_preset
        if self.current_calib_preset in ("performance", "balanced", "high"):
            p = CALIB_PRESETS[self.current_calib_preset]
            self.cfg["pose_model"] = p.get("pose_model", "lite")
            self.cfg["infer_quality_mode"] = p.get("infer_quality_mode", "auto")
            self.cfg["segmentation_mode"] = p.get("segmentation_mode", "accurate")
            self.cfg["adaptive_infer_scale"] = (self.cfg["infer_quality_mode"] == "auto")
            self.cfg["infer_max_w"] = 320 if self.cfg["infer_quality_mode"] == "low" else 640
        self.is_adv_calib_open = False
        self._is_closing = False
        self._is_preparing_tracking = False
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
        self.pre_tracking_validated_signal.connect(self._on_pre_tracking_validated)

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

            # Fast UI readout timer for DualShock 4, PlayStation Move Emulator & Phone Camera (150ms)
            self.timer_device_readout = QTimer(self)
            self.timer_device_readout.timeout.connect(self._update_device_readout)
            self.timer_device_readout.start(150)
        else:
            self.timer_periodic = None
            self.timer_device_readout = None

    # =========================================================================
    # CONTROLLER DELEGATES & COMPATIBILITY PROPERTIES
    # =========================================================================
    @property
    def _is_refreshing_cams(self) -> bool:
        return bool(getattr(self.controller.camera, "_is_refreshing_cams", False))

    @property
    def _is_connecting_ds4(self) -> bool:
        return bool(getattr(self.controller.devices, "is_connecting_ds4", False))

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

    # =========================================================================
    # PIXMAPS, PALETTE & STYLESHEET
    # =========================================================================
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
                pid: (
                    pil_to_qpixmap(act, dpr=4.0) if act is not None else QPixmap(),
                    pil_to_qpixmap(inact, dpr=4.0) if inact is not None else QPixmap(),
                )
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

        try:
            p_rel_act, p_rel_dis = generate_reload_icon_pil(size=(15, 15), scale=4)
            self.pix_reload_act = pil_to_qpixmap(p_rel_act, dpr=4.0)
            self.pix_reload_disabled = pil_to_qpixmap(p_rel_dis, dpr=4.0)
            self.icon_reload = QIcon()
            self.icon_reload.addPixmap(self.pix_reload_act, QIcon.Mode.Normal, QIcon.State.Off)
            self.icon_reload.addPixmap(self.pix_reload_disabled, QIcon.Mode.Disabled, QIcon.State.Off)
        except Exception as e:
            print(f"[WARN] Failed to load reload icon: {e}")
            self.pix_reload_act = self.pix_reload_disabled = QPixmap()
            self.icon_reload = QIcon()

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

    # =========================================================================
    # WINDOW SHELL BUILDERS
    # =========================================================================
    def _build_ui(self):
        """Builds the main horizontal split layout."""
        central_widget = QWidget(self)
        central_widget.setObjectName("centralWidget")
        self.setCentralWidget(central_widget)

        master_layout = QHBoxLayout(central_widget)
        master_layout.setContentsMargins(0, 0, 0, 0)
        master_layout.setSpacing(0)

        master_layout.addWidget(self._build_sidebar(central_widget))

        self.content_widget = QWidget(central_widget)
        content_layout = QVBoxLayout(self.content_widget)
        content_layout.setContentsMargins(26, 20, 26, 20)
        content_layout.setSpacing(14)

        content_layout.addLayout(self._build_top_nav_bar(self.content_widget))
        self._apply_tab_styles("video")

        sep = QFrame(self.content_widget)
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background-color: {PALETTE['border_subtle']}; max-height: 1px; border: none;")
        content_layout.addWidget(sep)

        self.stacked_view = SlidingStackedWidget(self.content_widget)
        content_layout.addWidget(self.stacked_view, stretch=1)

        # Build Page 0 (Video), Page 1 (Tracking), Page 2 (Experimental) & Page 3 (DualShock 4)
        self._build_video_view()
        self._build_calib_view()
        self._build_exp_view()
        self._build_ds4_view()

        action_layout, footer_layout = self._build_bottom_action_bar(self.content_widget)
        content_layout.addLayout(action_layout)
        content_layout.addLayout(footer_layout)

        master_layout.addWidget(self.content_widget, stretch=1)

        # Enforce clean light palette on all combobox popup views preserving their native style
        for cb in self.findChildren(QComboBox):
            cb.view().setStyleSheet(
                f"background-color: #FFFFFF; color: {PALETTE['text_main']}; "
                f"selection-background-color: {PALETTE['ps_blue']}; selection-color: #FFFFFF;"
            )

    def _build_sidebar(self, parent: QWidget) -> QFrame:
        """Builds the left capture-device navigation sidebar."""
        self.sidebar_frame = QFrame(parent)
        self.sidebar_frame.setObjectName("sidebar")
        self.sidebar_frame.setFixedWidth(270)
        sidebar_layout = QVBoxLayout(self.sidebar_frame)
        sidebar_layout.setContentsMargins(18, 20, 18, 20)
        sidebar_layout.setSpacing(0)

        lbl_brand = QLabel("Legacy PSCam Sensor", self.sidebar_frame)
        lbl_brand.setStyleSheet(
            f"font-family: '{self.font_title}'; font-size: 20px; font-weight: 600; color: {PALETTE['ps_blue']}; background: transparent;"
        )
        sidebar_layout.addWidget(lbl_brand)
        sidebar_layout.addSpacing(14)

        div_line = QFrame(self.sidebar_frame)
        div_line.setFrameShape(QFrame.Shape.HLine)
        div_line.setStyleSheet(f"background-color: {PALETTE['border_subtle']}; max-height: 1px; border: none;")
        sidebar_layout.addWidget(div_line)
        sidebar_layout.addSpacing(14)

        lbl_devices_hdr = QLabel("CAPTURE DEVICE", self.sidebar_frame)
        lbl_devices_hdr.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['blue_dark']}; background: transparent;"
        )
        sidebar_layout.addWidget(lbl_devices_hdr)
        sidebar_layout.addSpacing(8)

        nav_specs = [
            ("card_pscam", "PlayStation®Camera", "USB Adapter", self.pix_ps_act, self.pix_ps_inact, "pscam"),
            ("card_webcam", "Standard Webcam", "USB or Integrated", self.pix_web_act, self.pix_web_inact, "webcam"),
            ("card_ds4", "DualShock 4", "USB or Bluetooth", self.pix_ds4_act, self.pix_ds4_inact, "ds4"),
            ("card_phone_cam", "Phone Camera", "Android or iOS with Wi-Fi", self.pix_phone_act, self.pix_phone_inact, "phone_cam"),
        ]
        for attr, title, sub, pix_a, pix_i, mode_key in nav_specs:
            card = DeviceNavCard(title, sub, self.font_heading, self.font_body, self.sidebar_frame)
            card.set_icons(pix_a, pix_i)
            card.clicked.connect(lambda m=mode_key: self._set_mode(m))
            setattr(self, attr, card)
            sidebar_layout.addWidget(card)
            sidebar_layout.addSpacing(8)

        sidebar_layout.addStretch()

        self.btn_logs_folder = QPushButton("Open Logs Folder", self.sidebar_frame)
        self.btn_logs_folder.setProperty("class", "btn_secondary")
        self.btn_logs_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_logs_folder.clicked.connect(self._open_logs_folder)
        sidebar_layout.addWidget(self.btn_logs_folder)
        sidebar_layout.addSpacing(10)

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
        return self.sidebar_frame

    def _build_top_nav_bar(self, parent: QWidget) -> QHBoxLayout:
        """Builds the centered top tab navigation strip."""
        top_nav_layout = QHBoxLayout()
        top_nav_layout.setContentsMargins(0, 0, 0, 2)
        top_nav_layout.setSpacing(10)

        self.btn_tab_video = QPushButton("  Video Settings", parent)
        self.btn_tab_video.setFixedSize(148, 42)
        self.btn_tab_video.setIcon(QIcon(self.pix_gear_act))
        self.btn_tab_video.setIconSize(QSize(18, 18))
        self.btn_tab_video.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_tab_video.clicked.connect(lambda: self._switch_tab("video"))

        self.btn_tab_calib = QPushButton("  Tracking", parent)
        self.btn_tab_calib.setFixedSize(130, 42)
        self.btn_tab_calib.setIcon(QIcon(self.pix_slid_inact))
        self.btn_tab_calib.setIconSize(QSize(18, 18))
        self.btn_tab_calib.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_tab_calib.clicked.connect(lambda: self._switch_tab("calib"))
        self.btn_tab_tracking = self.btn_tab_calib

        self.btn_tab_exp = QPushButton("  Experimental", parent)
        self.btn_tab_exp.setFixedSize(142, 42)
        self.btn_tab_exp.setIcon(QIcon(self.pix_lab_inact))
        self.btn_tab_exp.setIconSize(QSize(18, 18))
        self.btn_tab_exp.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_tab_exp.clicked.connect(lambda: self._switch_tab("exp"))

        self.btn_tab_controller = QPushButton("  Controller Settings", parent)
        self.btn_tab_controller.setFixedSize(175, 42)
        self.btn_tab_controller.setIcon(QIcon(self.pix_ctrl_act))
        self.btn_tab_controller.setIconSize(QSize(18, 18))
        self.btn_tab_controller.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_tab_controller.clicked.connect(lambda: self._switch_tab("controller"))
        self.btn_tab_controller.setVisible(False)

        top_nav_layout.addStretch()
        top_nav_layout.addWidget(self.btn_tab_video)
        top_nav_layout.addWidget(self.btn_tab_calib)
        top_nav_layout.addWidget(self.btn_tab_controller)
        top_nav_layout.addWidget(self.btn_tab_exp)
        top_nav_layout.addStretch()
        return top_nav_layout

    def _build_bottom_action_bar(self, parent: QWidget):
        """Builds the bottom CTA bar (START TRACKING / DISCONNECT) and version footer."""
        self.bottom_action_layout = QHBoxLayout()
        self.bottom_action_layout.setContentsMargins(0, 0, 0, 0)
        self.bottom_action_layout.setSpacing(10)

        self.btn_start = QPushButton("START TRACKING", parent)
        self.btn_start.setProperty("class", "btn_cta")
        self.btn_start.setFixedHeight(48)
        self.btn_start.setEnabled(False)
        self.btn_start.setVisible(False)
        self.btn_start.setCursor(Qt.CursorShape.ForbiddenCursor)
        self.btn_start.clicked.connect(self._start_tracking)
        self.bottom_action_layout.addWidget(self.btn_start, stretch=1)

        self.btn_bottom_disconnect_phone = QPushButton("DISCONNECT", parent)
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

        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(0, 2, 0, 0)
        lbl_ver = QLabel(VERSION_STRING, parent)
        lbl_ver.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 11px; color: {PALETTE['text_dim']}; background: transparent;"
        )
        footer_layout.addStretch()
        footer_layout.addWidget(lbl_ver)
        return self.bottom_action_layout, footer_layout

    # =========================================================================
    # PERIODIC TICK, PERSISTENCE & WINDOW LIFECYCLE
    # =========================================================================
    def _periodic_check(self):
        self.controller.periodic_check()
        if self.cfg.get("camera_mode") == "phone_cam":
            self._update_phone_cam_status()

    def _save_settings(self):
        self.controller.save_settings()

    def closeEvent(self, event):
        self._is_closing = True
        if hasattr(self, "timer_periodic") and self.timer_periodic is not None:
            self.timer_periodic.stop()
        if hasattr(self, "timer_device_readout") and self.timer_device_readout is not None:
            self.timer_device_readout.stop()
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
