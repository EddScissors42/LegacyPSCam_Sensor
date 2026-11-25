"""
Declarative Qt 6 Page Builders for Legacy PSCam Sensor UI.
Separates the layout construction of the 4 navigation pages:
- Page 0: Video Settings (PlayStation Camera & Standard Webcam)
- Page 1: Calibration & Motion Profiles
- Page 2: Experimental Features (Auto-Frame PTZ & Virtual Phone Controller)
- Page 3: DualShock 4 Controller Settings
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QCheckBox, QFrame, QSlider, QScrollArea, QLineEdit
)

from ui.theme import PALETTE, CALIB_PRESETS
from ui.widgets import CalibPresetCard


class UIPagesMixin:
    """
    Mixin providing page construction methods for LegacySensorQtGUI.
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
        self.lbl_pscam_info = QLabel("Connect camera to USB 3.0 Port (AUX adapter required)", self.pscam_status_card)
        self.lbl_pscam_info.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 11px; color: {PALETTE['text_muted']}; background: transparent; border: none;"
        )
        text_col.addWidget(self.lbl_pscam_conn_title)
        text_col.addWidget(self.lbl_pscam_info)
        card_layout.addLayout(text_col, stretch=1)
        ps_disc_layout.addWidget(self.pscam_status_card)

        # Retained hidden for backward compatibility
        self.btn_launch_pscam = QPushButton(self.pscam_disconnected_box)
        self.btn_launch_pscam.setVisible(False)
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

        self.lbl_pscam_ready_info = QLabel("PlayStation®Camera connected and ready (60 FPS)", self.pscam_card)
        self.lbl_pscam_ready_info.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 11px; color: {PALETTE['status_ok']}; background: transparent; border: none;"
        )
        ps_conn_layout.addWidget(self.lbl_pscam_ready_info)

        spec_badge = QFrame(self.pscam_card)
        spec_badge.setProperty("class", "spec_badge")
        spec_layout = QVBoxLayout(spec_badge)
        spec_layout.setContentsMargins(12, 8, 12, 8)
        spec_layout.setSpacing(0)
        lbl_spec_title = QLabel("Optimized Auto Mode: 1280x800 @ 60 FPS (OV580 Stereo Vision)", spec_badge)
        lbl_spec_title.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['blue_dark']}; background: transparent; border: none;"
        )
        spec_layout.addWidget(lbl_spec_title)
        ps_conn_layout.addWidget(spec_badge)

        # Eye Sensor Selector Block (Right Eye Default / Left Eye)
        self.block_ps_eye = QFrame(self.pscam_card)
        self.block_ps_eye.setObjectName("settingBlockPsEye")
        self.block_ps_eye.setFixedHeight(92)
        self.block_ps_eye.setStyleSheet(f"""
            QFrame#settingBlockPsEye {{
                background-color: #FFFFFF;
                border: 1px solid {PALETTE["border_subtle"]};
                border-radius: 10px;
            }}
            QFrame#settingBlockPsEye:hover {{
                border-color: {PALETTE["input_border"]};
            }}
            QFrame#settingBlockPsEye:disabled {{
                background-color: {PALETTE["input_bg"]};
                border-color: {PALETTE["border_subtle"]};
            }}
        """)
        ps_eye_layout = QVBoxLayout(self.block_ps_eye)
        ps_eye_layout.setContentsMargins(14, 10, 14, 10)
        ps_eye_layout.setSpacing(4)

        lbl_eye_title = QLabel("CAMERA SENSOR EYE (OV9713 STEREO)", self.block_ps_eye)
        lbl_eye_title.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['blue_dark']}; background: transparent; border: none;"
        )
        ps_eye_layout.addWidget(lbl_eye_title)

        lbl_eye_sub = QLabel("Select which lens feeds body tracking (Right Eye is the standard default).", self.block_ps_eye)
        lbl_eye_sub.setWordWrap(True)
        lbl_eye_sub.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 10px; color: {PALETTE['text_muted']}; background: transparent; border: none;"
        )
        ps_eye_layout.addWidget(lbl_eye_sub)

        self.cb_ps4_eye = QComboBox(self.block_ps_eye)
        self.cb_ps4_eye.setFixedHeight(32)
        self.cb_ps4_eye.addItems(["Right Eye (Default)", "Left Eye"])
        curr_eye = str(self.cfg.get("ps4_eye", "right")).strip().lower()
        self.cb_ps4_eye.setCurrentIndex(1 if curr_eye == "left" else 0)
        self.cb_ps4_eye.currentIndexChanged.connect(self._on_ps4_eye_changed)
        ps_eye_layout.addWidget(self.cb_ps4_eye)

        ps_conn_layout.addWidget(self.block_ps_eye)

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
        # 2.5 Phone Camera Views (Android or iOS via Wi-Fi WebApp QR Code)
        # =====================================================================
        # 2.5.1 Disconnected View (Status Balloon + QR Code Pairing Card)
        self.phone_cam_disconnected_box = QWidget(self.page_video)
        ph_disc_layout = QVBoxLayout(self.phone_cam_disconnected_box)
        ph_disc_layout.setContentsMargins(0, 0, 0, 0)
        ph_disc_layout.setSpacing(12)

        self.phone_cam_status_card = QFrame(self.phone_cam_disconnected_box)
        self.phone_cam_status_card.setProperty("class", "status_balloon")
        ph_bal_layout = QHBoxLayout(self.phone_cam_status_card)
        ph_bal_layout.setContentsMargins(16, 14, 16, 14)
        ph_bal_layout.setSpacing(14)

        self.lbl_phone_cam_icon = QLabel(self.phone_cam_status_card)
        self.lbl_phone_cam_icon.setPixmap(self.pix_status_warn)
        self.lbl_phone_cam_icon.setFixedSize(38, 38)
        self.lbl_phone_cam_icon.setStyleSheet("background: transparent; border: none;")
        ph_bal_layout.addWidget(self.lbl_phone_cam_icon)

        ph_text_col = QVBoxLayout()
        ph_text_col.setSpacing(2)
        self.lbl_phone_cam_conn_title = QLabel("Phone Camera waiting for connection", self.phone_cam_status_card)
        self.lbl_phone_cam_conn_title.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 14px; font-weight: bold; color: {PALETTE['text_main']}; background: transparent; border: none;"
        )
        self.lbl_phone_cam_info = QLabel("Scan the QR Code below with your Android or iOS camera on the same Wi-Fi network", self.phone_cam_status_card)
        self.lbl_phone_cam_info.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 11px; color: {PALETTE['text_muted']}; background: transparent; border: none;"
        )
        ph_text_col.addWidget(self.lbl_phone_cam_conn_title)
        ph_text_col.addWidget(self.lbl_phone_cam_info)
        ph_bal_layout.addLayout(ph_text_col, stretch=1)
        ph_disc_layout.addWidget(self.phone_cam_status_card)

        # QR Code & English Connection Instructions Card
        self.phone_cam_qr_card = QFrame(self.phone_cam_disconnected_box)
        self.phone_cam_qr_card.setProperty("class", "card")
        qr_card_layout = QVBoxLayout(self.phone_cam_qr_card)
        qr_card_layout.setContentsMargins(16, 14, 16, 14)
        qr_card_layout.setSpacing(10)

        lbl_qr_hdr = QLabel("CONNECT SMARTPHONE CAMERA (NO APP INSTALL REQUIRED)", self.phone_cam_qr_card)
        lbl_qr_hdr.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 12px; font-weight: bold; color: {PALETTE['blue_dark']}; background: transparent; border: none;"
        )
        qr_card_layout.addWidget(lbl_qr_hdr)

        qr_row = QHBoxLayout()
        qr_row.setSpacing(16)

        # Left: Crisp QR Code Box
        self.qr_frame_box = QFrame(self.phone_cam_qr_card)
        self.qr_frame_box.setFixedSize(172, 172)
        self.qr_frame_box.setStyleSheet(f"""
            QFrame {{
                background-color: #FFFFFF;
                border: 1px solid {PALETTE["border_subtle"]};
                border-radius: 12px;
            }}
        """)
        qr_box_layout = QVBoxLayout(self.qr_frame_box)
        qr_box_layout.setContentsMargins(8, 8, 8, 8)
        qr_box_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_phone_qr_img = QLabel(self.qr_frame_box)
        self.lbl_phone_qr_img.setFixedSize(154, 154)
        self.lbl_phone_qr_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_phone_qr_img.setStyleSheet("background: transparent; border: none;")
        qr_box_layout.addWidget(self.lbl_phone_qr_img)
        qr_row.addWidget(self.qr_frame_box)

        # Right: Step-by-Step Instructions in English + URL Action Bar
        instr_col = QVBoxLayout()
        instr_col.setSpacing(8)

        lbl_steps = QLabel(
            "<b>1. Same Wi-Fi Network:</b> Connect your Android or iPhone to the same local Wi-Fi as this PC (disable VPN & avoid Guest Wi-Fi).<br>"
            "<b>2. Scan QR Code:</b> Point your phone's Camera at the QR Code (or open the URL below in Safari / Chrome).<br>"
            "<b>3. Allow Access:</b> Tap <b>Advanced → Proceed</b> on the local HTTPS prompt and grant camera permission.<br>"
            "<span style='color:#64748B;'>Getting <b>ERR_CONNECTION_TIMED_OUT</b>? Click <b>Allow Firewall</b> below or pick your Wi-Fi/Ethernet IP.</span>",
            self.phone_cam_qr_card
        )
        lbl_steps.setWordWrap(True)
        lbl_steps.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 11px; color: {PALETTE['text_main']}; background: transparent; border: none; line-height: 132%;"
        )
        instr_col.addWidget(lbl_steps)
        instr_col.addStretch()

        net_bar = QHBoxLayout()
        net_bar.setSpacing(8)

        self.cb_phone_cam_ip = QComboBox(self.phone_cam_qr_card)
        self.cb_phone_cam_ip.setFixedHeight(30)
        self.cb_phone_cam_ip.setToolTip("Select the Wi-Fi or Ethernet LAN IP of this PC (avoid VPN/Virtual adapters)")
        self.cb_phone_cam_ip.currentIndexChanged.connect(self._on_phone_cam_ip_changed)
        net_bar.addWidget(self.cb_phone_cam_ip, stretch=1)

        self.btn_phone_firewall = QPushButton("Allow Firewall", self.phone_cam_qr_card)
        self.btn_phone_firewall.setProperty("class", "btn_secondary")
        self.btn_phone_firewall.setFixedHeight(30)
        self.btn_phone_firewall.setToolTip(
            "Add a Windows Defender Firewall inbound rule for Phone Camera (Private & Public Wi-Fi) to fix ERR_CONNECTION_TIMED_OUT"
        )
        self.btn_phone_firewall.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_phone_firewall.clicked.connect(self._on_allow_phone_cam_firewall)
        net_bar.addWidget(self.btn_phone_firewall)

        instr_col.addLayout(net_bar)

        url_bar = QHBoxLayout()
        url_bar.setSpacing(8)

        self.lbl_phone_cam_url = QLabel("https://127.0.0.1:8443", self.phone_cam_qr_card)
        self.lbl_phone_cam_url.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_phone_cam_url.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 12px; font-weight: bold; color: {PALETTE['ps_blue']}; "
            f"background-color: {PALETTE['blue_pastel']}; padding: 6px 10px; border-radius: 6px; border: none;"
        )
        url_bar.addWidget(self.lbl_phone_cam_url, stretch=1)

        self.btn_copy_phone_url = QPushButton("Copy URL", self.phone_cam_qr_card)
        self.btn_copy_phone_url.setProperty("class", "btn_secondary")
        self.btn_copy_phone_url.setFixedHeight(32)
        self.btn_copy_phone_url.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_copy_phone_url.clicked.connect(self._on_copy_phone_cam_url)
        url_bar.addWidget(self.btn_copy_phone_url)

        self.btn_refresh_phone_qr = QPushButton("↻", self.phone_cam_qr_card)
        self.btn_refresh_phone_qr.setProperty("class", "btn_secondary")
        self.btn_refresh_phone_qr.setFixedSize(34, 32)
        self.btn_refresh_phone_qr.setToolTip("Refresh local IP and QR Code")
        self.btn_refresh_phone_qr.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh_phone_qr.clicked.connect(lambda: self._refresh_phone_cam_qr(rotate_token=True))
        url_bar.addWidget(self.btn_refresh_phone_qr)

        instr_col.addLayout(url_bar)
        qr_row.addLayout(instr_col, stretch=1)
        qr_card_layout.addLayout(qr_row)

        ph_disc_layout.addWidget(self.phone_cam_qr_card)
        layout.addWidget(self.phone_cam_disconnected_box)

        # 2.5.2 Connected Card (Shown when smartphone connects; QR Code disappears)
        self.phone_cam_card = QFrame(self.page_video)
        self.phone_cam_card.setProperty("class", "card")
        self.phone_cam_card.setMinimumHeight(280)
        ph_conn_layout = QVBoxLayout(self.phone_cam_card)
        ph_conn_layout.setContentsMargins(16, 14, 16, 14)
        ph_conn_layout.setSpacing(10)

        lbl_ph_title = QLabel("PHONE CAMERA VIDEO SETTINGS", self.phone_cam_card)
        lbl_ph_title.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 12px; font-weight: bold; color: {PALETTE['blue_dark']}; background: transparent; border: none;"
        )
        ph_conn_layout.addWidget(lbl_ph_title)

        # Row 1: Connected Smartphone Info (Pulled to the top)
        block_ph_dev = QFrame(self.phone_cam_card)
        block_ph_dev.setObjectName("settingBlockPhoneDev")
        block_ph_dev.setFixedHeight(64)
        block_ph_dev.setStyleSheet(f"""
            QFrame#settingBlockPhoneDev {{
                background-color: #FFFFFF;
                border: 1px solid {PALETTE["border_subtle"]};
                border-radius: 10px;
            }}
            QFrame#settingBlockPhoneDev:hover {{
                border-color: {PALETTE["input_border"]};
            }}
        """)
        ph_dev_layout = QVBoxLayout(block_ph_dev)
        ph_dev_layout.setContentsMargins(14, 10, 14, 10)
        ph_dev_layout.setSpacing(4)

        lbl_ph_dev_title = QLabel("CONNECTED SMARTPHONE", block_ph_dev)
        lbl_ph_dev_title.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['blue_dark']}; background: transparent; border: none;"
        )
        ph_dev_layout.addWidget(lbl_ph_dev_title)

        self.lbl_phone_cam_ready_info = QLabel("Smartphone connected and ready (Wi-Fi WebApp)", block_ph_dev)
        self.lbl_phone_cam_ready_info.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 11px; font-weight: 600; color: {PALETTE['status_ok']}; background: transparent; border: none;"
        )
        ph_dev_layout.addWidget(self.lbl_phone_cam_ready_info)
        self.lbl_phone_device_meta = self.lbl_phone_cam_ready_info
        ph_conn_layout.addWidget(block_ph_dev)

        # Row 2: Resolution & FPS side-by-side blocks
        row_ph_res_fps = QHBoxLayout()
        row_ph_res_fps.setSpacing(10)

        block_ph_res = QFrame(self.phone_cam_card)
        block_ph_res.setObjectName("settingBlockPhoneRes")
        block_ph_res.setFixedHeight(108)
        block_ph_res.setStyleSheet(f"""
            QFrame#settingBlockPhoneRes {{
                background-color: #FFFFFF;
                border: 1px solid {PALETTE["border_subtle"]};
                border-radius: 10px;
            }}
            QFrame#settingBlockPhoneRes:hover {{
                border-color: {PALETTE["input_border"]};
            }}
        """)
        ph_res_layout = QVBoxLayout(block_ph_res)
        ph_res_layout.setContentsMargins(14, 10, 14, 10)
        ph_res_layout.setSpacing(4)

        lbl_ph_res_title = QLabel("RESOLUTION", block_ph_res)
        lbl_ph_res_title.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['blue_dark']}; background: transparent; border: none;"
        )
        ph_res_layout.addWidget(lbl_ph_res_title)

        lbl_ph_res_sub = QLabel("640x480 provides the lowest Wi-Fi latency. The game receives 640x480.", block_ph_res)
        lbl_ph_res_sub.setWordWrap(True)
        lbl_ph_res_sub.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 10px; color: {PALETTE['text_muted']}; background: transparent; border: none; line-height: 120%;"
        )
        ph_res_layout.addWidget(lbl_ph_res_sub)

        self.cb_phone_res = QComboBox(block_ph_res)
        self.cb_phone_res.setFixedHeight(32)
        self.cb_phone_res.addItems(["640x480 (Recommended)", "1280x720"])
        self.cb_phone_res.currentIndexChanged.connect(self._on_phone_cam_settings_changed)
        ph_res_layout.addWidget(self.cb_phone_res)
        row_ph_res_fps.addWidget(block_ph_res, stretch=1)

        block_ph_fps = QFrame(self.phone_cam_card)
        block_ph_fps.setObjectName("settingBlockPhoneFps")
        block_ph_fps.setFixedHeight(108)
        block_ph_fps.setStyleSheet(f"""
            QFrame#settingBlockPhoneFps {{
                background-color: #FFFFFF;
                border: 1px solid {PALETTE["border_subtle"]};
                border-radius: 10px;
            }}
            QFrame#settingBlockPhoneFps:hover {{
                border-color: {PALETTE["input_border"]};
            }}
        """)
        ph_fps_layout = QVBoxLayout(block_ph_fps)
        ph_fps_layout.setContentsMargins(14, 10, 14, 10)
        ph_fps_layout.setSpacing(4)

        lbl_ph_fps_title = QLabel("FRAMERATE (FPS)", block_ph_fps)
        lbl_ph_fps_title.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['blue_dark']}; background: transparent; border: none;"
        )
        ph_fps_layout.addWidget(lbl_ph_fps_title)

        lbl_ph_fps_sub = QLabel("Target wireless stream speed. 60 FPS requires strong 5 GHz Wi-Fi signal.", block_ph_fps)
        lbl_ph_fps_sub.setWordWrap(True)
        lbl_ph_fps_sub.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 10px; color: {PALETTE['text_muted']}; background: transparent; border: none; line-height: 120%;"
        )
        ph_fps_layout.addWidget(lbl_ph_fps_sub)

        self.cb_phone_fps = QComboBox(block_ph_fps)
        self.cb_phone_fps.setFixedHeight(32)
        self.cb_phone_fps.addItems(["30 FPS (Recommended)", "60 FPS"])
        self.cb_phone_fps.currentIndexChanged.connect(self._on_phone_cam_settings_changed)
        ph_fps_layout.addWidget(self.cb_phone_fps)
        row_ph_res_fps.addWidget(block_ph_fps, stretch=1)

        ph_conn_layout.addLayout(row_ph_res_fps)
        layout.addWidget(self.phone_cam_card)

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

        # 2 Profile cards (Balanced / Competitive)
        cards_row = QHBoxLayout()
        cards_row.setSpacing(10)

        for pid, pdata in CALIB_PRESETS.items():
            pix_act, pix_inact = self.mode_pixmaps.get(pid, (QPixmap(), QPixmap()))
            card = CalibPresetCard(pid, pdata, self.font_heading, self.font_body, pix_act, pix_inact, main_card)
            card.clicked.connect(self._select_calib_preset)
            cards_row.addWidget(card)
            self.calib_cards[pid] = card

        card_layout.addLayout(cards_row)

        # On-demand AI Model Download Status Banner (hidden unless downloading Full AI to %APPDATA%)
        self.model_dl_box = QFrame(main_card)
        self.model_dl_box.setObjectName("modelDownloadBox")
        self.model_dl_box.setStyleSheet(f"""
            QFrame#modelDownloadBox {{
                background-color: #EFF6FF;
                border: 1px solid #93C5FD;
                border-radius: 8px;
            }}
        """)
        mdl_layout = QHBoxLayout(self.model_dl_box)
        mdl_layout.setContentsMargins(12, 8, 12, 8)
        mdl_layout.setSpacing(10)
        self.lbl_model_dl_status = QLabel("", self.model_dl_box)
        self.lbl_model_dl_status.setWordWrap(True)
        self.lbl_model_dl_status.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 10.5px; font-weight: 600; color: {PALETTE['blue_dark']}; background: transparent; border: none;"
        )
        mdl_layout.addWidget(self.lbl_model_dl_status, stretch=1)
        self.model_dl_box.setVisible(False)
        card_layout.addWidget(self.model_dl_box)

        # 2-Player Lite AI Warning Banner (displayed right below model selection when 2 Players is active)
        self.two_player_warn_box = QFrame(main_card)
        self.two_player_warn_box.setObjectName("twoPlayerWarnBox")
        self.two_player_warn_box.setStyleSheet("""
            QFrame#twoPlayerWarnBox {
                background-color: #FEF3C7;
                border: 1px solid #FCD34D;
                border-radius: 8px;
            }
        """)
        tp_warn_layout = QHBoxLayout(self.two_player_warn_box)
        tp_warn_layout.setContentsMargins(12, 8, 12, 8)
        tp_warn_layout.setSpacing(10)

        lbl_tp_icon = QLabel("[!]", self.two_player_warn_box)
        lbl_tp_icon.setStyleSheet(
            "font-family: monospace; font-size: 13px; font-weight: bold; color: #92400E; background: transparent; border: none;"
        )
        tp_warn_layout.addWidget(lbl_tp_icon, alignment=Qt.AlignmentFlag.AlignTop)

        self.lbl_2p_model_warning = QLabel(
            "2-Player Mode Active: Lite AI (Competitive) is strongly recommended to sustain stable 30–60 FPS on the CPU when tracking two dancers simultaneously.",
            self.two_player_warn_box,
        )
        self.lbl_2p_model_warning.setWordWrap(True)
        self.lbl_2p_model_warning.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 10.5px; font-weight: 600; color: #92400E; background: transparent; border: none;"
        )
        tp_warn_layout.addWidget(self.lbl_2p_model_warning, stretch=1)
        self.two_player_warn_box.setVisible(int(self.cfg.get("max_players", 1)) >= 2)
        card_layout.addWidget(self.two_player_warn_box)

        # Players Mode Selector Block (1 Player Solo / 2 Players Duo)
        self.block_players_mode = QFrame(main_card)
        self.block_players_mode.setObjectName("settingBlockPlayersMode")
        self.block_players_mode.setFixedHeight(96)
        self.block_players_mode.setStyleSheet(f"""
            QFrame#settingBlockPlayersMode {{
                background-color: #FFFFFF;
                border: 1px solid {PALETTE["border_subtle"]};
                border-radius: 10px;
            }}
            QFrame#settingBlockPlayersMode:hover {{
                border-color: {PALETTE["input_border"]};
            }}
        """)
        pm_layout = QVBoxLayout(self.block_players_mode)
        pm_layout.setContentsMargins(14, 10, 14, 10)
        pm_layout.setSpacing(3)

        lbl_pm_title = QLabel("PLAYERS MODE", self.block_players_mode)
        lbl_pm_title.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['blue_dark']}; background: transparent; border: none;"
        )
        pm_layout.addWidget(lbl_pm_title)

        lbl_pm_sub = QLabel(
            "Choose whether to play by yourself or dance with a friend. The sensor tracks both players smoothly without mixing anyone up, even when dancing close together.",
            self.block_players_mode,
        )
        lbl_pm_sub.setWordWrap(True)
        lbl_pm_sub.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 10px; color: {PALETTE['text_muted']}; background: transparent; border: none;"
        )
        pm_layout.addWidget(lbl_pm_sub)

        self.cb_players_mode = QComboBox(self.block_players_mode)
        self.cb_players_mode.setFixedHeight(32)
        self.cb_players_mode.addItems([
            "1 Player",
            "2 Players [Experimental]",
        ])
        curr_mp = max(1, min(2, int(self.cfg.get("max_players", 1))))
        self.cb_players_mode.setCurrentIndex(1 if curr_mp >= 2 else 0)
        self.cb_players_mode.currentIndexChanged.connect(self._on_players_mode_changed)
        pm_layout.addWidget(self.cb_players_mode)
        card_layout.addWidget(self.block_players_mode)

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
        lbl_ruler = QLabel("", auto_h)
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
        btn_reset = QPushButton("↺ Reset to Recommended Profile (Competitive — Lite AI)", self.adv_drawer)
        btn_reset.setProperty("class", "btn_secondary")
        btn_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_reset.clicked.connect(lambda: self._select_calib_preset("competitive"))
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
        """Constructs Page 2: Experimental Features (full controls in Camera modes; empty placeholder in DS4 mode)."""
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

        # Empty placeholder shown ONLY in DualShock 4 mode (Scoring Bridge lives in Controller Settings)
        self.lbl_exp_empty = QLabel("No experimental features available at this time.", exp_card)
        self.lbl_exp_empty.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 11px; color: {PALETTE['text_muted']}; background: transparent; border: none;"
        )
        self.lbl_exp_empty.setVisible(False)
        exp_layout.addWidget(self.lbl_exp_empty)

        # Warning Callout Box (Camera modes)
        self.exp_warn_box = QFrame(exp_card)
        self.exp_warn_box.setStyleSheet("""
            QFrame {
                background-color: #FEF3C7;
                border: 1px solid #FCD34D;
                border-radius: 8px;
            }
        """)
        warn_layout = QHBoxLayout(self.exp_warn_box)
        warn_layout.setContentsMargins(12, 10, 12, 10)
        warn_layout.setSpacing(10)

        lbl_warn_icon = QLabel("[!]", self.exp_warn_box)
        lbl_warn_icon.setStyleSheet("font-family: monospace; font-size: 14px; font-weight: bold; color: #92400E; background: transparent; border: none;")
        warn_layout.addWidget(lbl_warn_icon, alignment=Qt.AlignmentFlag.AlignTop)

        lbl_warn_text = QLabel(
            "CAUTION: Features here are under constant testing and development. "
            "They may not work as intended or may fail to function entirely, which could affect your gameplay experience.",
            self.exp_warn_box
        )
        lbl_warn_text.setWordWrap(True)
        lbl_warn_text.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 11px; font-weight: 500; color: #92400E; background: transparent; border: none;"
        )
        warn_layout.addWidget(lbl_warn_text, stretch=1)
        exp_layout.addWidget(self.exp_warn_box)

        # Auto-Frame Feature Box (Camera modes)
        self.auto_frame_box = QFrame(exp_card)
        self.auto_frame_box.setStyleSheet(f"""
            QFrame {{
                background-color: {PALETTE["input_bg"]};
                border: 1px solid {PALETTE["border_subtle"]};
                border-radius: 8px;
            }}
        """)
        af_layout = QVBoxLayout(self.auto_frame_box)
        af_layout.setContentsMargins(14, 12, 14, 12)
        af_layout.setSpacing(6)

        self.chk_face = QCheckBox("Auto-Frame player's face in Just Dance (Digital PTZ)", self.auto_frame_box)
        self.chk_face.setChecked(self.cfg.get("face_follow_enabled", True))
        self.chk_face.stateChanged.connect(self._on_display_options_changed)
        af_layout.addWidget(self.chk_face)

        lbl_desc = QLabel(
            "Dynamically tracks and frames the dancer's face and upper torso using real-time landmark tracking. "
            "Smoothly pans and crops the game video stream sent to Just Dance PC while keeping 3D skeletal tracking unaffected.",
            self.auto_frame_box
        )
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 11px; color: {PALETTE['text_muted']}; background: transparent; border: none;"
        )
        af_layout.addWidget(lbl_desc)
        exp_layout.addWidget(self.auto_frame_box)

        # Virtual Phone Controller Feature Box (Camera modes)
        self.vphone_box = QFrame(exp_card)
        self.vphone_box.setStyleSheet(f"""
            QFrame {{
                background-color: {PALETTE["input_bg"]};
                border: 1px solid {PALETTE["border_subtle"]};
                border-radius: 8px;
            }}
        """)
        vp_layout = QVBoxLayout(self.vphone_box)
        vp_layout.setContentsMargins(14, 12, 14, 12)
        vp_layout.setSpacing(8)

        self.chk_vphone_enabled = QCheckBox("Virtual Phone Controller (JD Controller via Camera)", self.vphone_box)
        self.chk_vphone_enabled.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 13px; font-weight: bold; color: {PALETTE['text_main']};"
        )
        self.chk_vphone_enabled.setChecked(bool(self.cfg.get("virtual_phone_enabled", False)))
        self.chk_vphone_enabled.stateChanged.connect(self._on_vphone_toggle_changed)
        vp_layout.addWidget(self.chk_vphone_enabled)

        self.lbl_vp_desc = QLabel(
            "Emulates a smartphone connected to Just Dance via WebSocket/TLS (/smartphone) and converts your hand motion "
            "in the camera into 3D accelerometer commands for songs that only support hand controllers.",
            self.vphone_box
        )
        self.lbl_vp_desc.setWordWrap(True)
        self.lbl_vp_desc.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 11px; color: {PALETTE['text_muted']}; background: transparent; border: none;"
        )
        vp_layout.addWidget(self.lbl_vp_desc)

        # Status & Controls Container (Hidden when Virtual Phone is disabled)
        self.vphone_details_frame = QFrame(self.vphone_box)
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

        self.lbl_vphone_status = QLabel("Status: Disabled", self.vphone_details_frame)
        self.lbl_vphone_status.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['text_muted']}; background: transparent; border: none;"
        )
        vp_det_layout.addWidget(self.lbl_vphone_status)

        self.lbl_vphone_accel = QLabel("3D Accelerometer: X: +0.00G | Y: -1.00G | Z: +0.00G (0.0 m/s)", self.vphone_details_frame)
        self.lbl_vphone_accel.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['ps_blue']}; background: transparent; border: none;"
        )
        self.lbl_vphone_accel.setVisible(getattr(self, "is_tracking_active", False))
        vp_det_layout.addWidget(self.lbl_vphone_accel)

        self.txt_vphone_host = QLineEdit(str(self.cfg.get("virtual_phone_host", "127.0.0.1")), self)
        self.txt_vphone_host.setVisible(False)
        self.txt_vphone_port = QLineEdit(str(self.cfg.get("virtual_phone_port", 8080)), self)
        self.txt_vphone_port.setVisible(False)

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
        self.btn_vphone_ftue.setToolTip("Skip phone tutorial prompt in Just Dance PC")
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

        settings_row = QHBoxLayout()
        settings_row.setSpacing(16)
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
        settings_row.addLayout(hand_box, stretch=1)
        vp_det_layout.addLayout(settings_row)

        vp_layout.addWidget(self.vphone_details_frame)
        self.vphone_details_frame.setVisible(self.chk_vphone_enabled.isChecked())
        exp_layout.addWidget(self.vphone_box)

        # Dedicated Telemetry Benchmark Feature Box (Preserved but Disabled & Hidden from UI)
        self.benchmark_box = QFrame(exp_card)
        self.benchmark_box.setVisible(False)
        self.benchmark_box.setEnabled(False)
        self.chk_benchmark_enabled = QCheckBox("Telemetry Benchmark", self.benchmark_box)
        self.chk_benchmark_enabled.setVisible(False)
        self.lbl_benchmark_song = QLabel("Active Song: None", self.benchmark_box)
        self.lbl_benchmark_song.setVisible(False)
        self.btn_open_benchmark = QPushButton("Benchmark", self.benchmark_box)
        self.btn_open_benchmark.setVisible(False)
        self.btn_open_logs_dir = QPushButton("Open Logs Folder", self.benchmark_box)
        self.btn_open_logs_dir.setVisible(False)
        self.chk_benchmark_adaptive = QCheckBox("Adaptive", self.benchmark_box)
        self.chk_benchmark_adaptive.setVisible(False)

        # Compatibility aliases
        self.lbl_vphone_song = self.lbl_benchmark_song
        self.btn_vphone_benchmark = self.btn_open_benchmark
        self.chk_vphone_auto_record = self.chk_benchmark_enabled
        self.chk_vphone_adaptive = self.chk_benchmark_adaptive

        layout.addWidget(exp_card)
        layout.addStretch()

        self.scroll_exp = self._create_scroll_page(self.page_exp)
        self.stacked_view.addWidget(self.scroll_exp)
        self._update_exp_view_for_mode(self.cfg.get("camera_mode", "pscam"))

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
        ds4_layout.setSpacing(12)

        lbl_title = QLabel("DUALSHOCK® 4 CONTROLLER SETTINGS", ds4_card)
        lbl_title.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 12px; font-weight: bold; color: {PALETTE['blue_dark']}; background: transparent; border: none;"
        )
        ds4_layout.addWidget(lbl_title)

        lbl_sub = QLabel("Configure motion sensors, tracked hand and hardware responsiveness.", ds4_card)
        lbl_sub.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 11px; color: {PALETTE['text_muted']}; background: transparent; border: none;"
        )
        ds4_layout.addWidget(lbl_sub)

        # Warning Callout Box (Kept in same position)
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

        lbl_warn_icon = QLabel("[!]", warn_box)
        lbl_warn_icon.setStyleSheet("font-family: monospace; font-size: 14px; font-weight: bold; color: #92400E; background: transparent; border: none;")
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

        # Permissive Mode Toggle (Kept in same position)
        perm_box = QFrame(ds4_card)
        perm_box.setStyleSheet(f"""
            QFrame {{
                background-color: {PALETTE["input_bg"]};
                border: 1px solid {PALETTE["tab_gray_border"]};
                border-radius: 8px;
            }}
        """)
        perm_layout = QHBoxLayout(perm_box)
        perm_layout.setContentsMargins(14, 10, 14, 10)
        perm_layout.setSpacing(10)

        self.chk_ds4_permissive = QCheckBox("Permissive Discovery Mode (Third-Party & Clone PS4 Controllers)", perm_box)
        self.chk_ds4_permissive.setStyleSheet(f"""
            QCheckBox {{
                font-family: '{self.font_body}';
                font-size: 11px;
                font-weight: 600;
                color: {PALETTE['text_main']};
                background: transparent;
            }}
            QCheckBox::indicator {{
                width: 15px;
                height: 15px;
                border-radius: 3px;
                border: 1px solid {PALETTE['tab_gray_border']};
            }}
            QCheckBox::indicator:checked {{
                background-color: {PALETTE['ps_blue']};
                border-color: {PALETTE['ps_blue']};
            }}
        """)
        self.chk_ds4_permissive.setChecked(bool(self.cfg.get("ds4_permissive_mode", True)))
        self.chk_ds4_permissive.setToolTip(
            "Enables discovery of licensed third-party controllers (Hori, Nacon, Razer, Astro, Scuf) "
            "and generic DS4 clone chipsets (ShanWan, DragonRise, etc.)."
        )
        self.chk_ds4_permissive.stateChanged.connect(self._on_ds4_permissive_changed)
        perm_layout.addWidget(self.chk_ds4_permissive)
        perm_layout.addStretch()
        ds4_layout.addWidget(perm_box)

        # =====================================================================
        # Disconnected Balloon (Identical structure to Webcam & PS Camera)
        # =====================================================================
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
        self.lbl_ds4_conn_info = QLabel("No Wireless Controller detected via Bluetooth HID or USB Port", self.ds4_status_card)
        self.lbl_ds4_conn_info.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 11px; color: {PALETTE['text_muted']}; background: transparent; border: none;"
        )
        text_col.addWidget(self.lbl_ds4_conn_title)
        text_col.addWidget(self.lbl_ds4_conn_info)
        card_layout.addLayout(text_col, stretch=1)
        ds4_disc_layout.addWidget(self.ds4_status_card)

        # Full-width action button matching webcam's "Search for Webcams"
        self.btn_refresh_ds4 = QPushButton("Search for Controllers", self.ds4_disconnected_box)
        self.btn_refresh_ds4.setProperty("class", "btn_balloon_action")
        self.btn_refresh_ds4.setFixedHeight(42)
        self.btn_refresh_ds4.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh_ds4.clicked.connect(self._reconnect_ds4)
        ds4_disc_layout.addWidget(self.btn_refresh_ds4)

        ds4_layout.addWidget(self.ds4_disconnected_box)

        # =====================================================================
        # Connected Controller View (Matching Webcam Card & Settings Blocks)
        # =====================================================================
        self.ds4_info_frame = QWidget(ds4_card)
        ds4_info_layout = QVBoxLayout(self.ds4_info_frame)
        ds4_info_layout.setContentsMargins(0, 0, 0, 0)
        ds4_info_layout.setSpacing(10)

        # Block 1: Active Controller Device & Refresh (Full-width block matching block_dev of Webcam)
        block_ds4_dev = QFrame(self.ds4_info_frame)
        block_ds4_dev.setObjectName("settingBlockDs4Dev")
        block_ds4_dev.setFixedHeight(90)
        block_ds4_dev.setStyleSheet(f"""
            QFrame#settingBlockDs4Dev {{
                background-color: #FFFFFF;
                border: 1px solid {PALETTE["border_subtle"]};
                border-radius: 10px;
            }}
            QFrame#settingBlockDs4Dev:hover {{
                border-color: {PALETTE["input_border"]};
            }}
        """)
        ds4_dev_layout = QVBoxLayout(block_ds4_dev)
        ds4_dev_layout.setContentsMargins(14, 10, 14, 10)
        ds4_dev_layout.setSpacing(4)

        lbl_dev_title = QLabel("CONTROLLER HARDWARE", block_ds4_dev)
        lbl_dev_title.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['blue_dark']}; background: transparent; border: none;"
        )
        ds4_dev_layout.addWidget(lbl_dev_title)

        lbl_dev_sub = QLabel("Active Wireless / USB Motion Device", block_ds4_dev)
        lbl_dev_sub.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 10px; color: {PALETTE['text_muted']}; background: transparent; border: none;"
        )
        ds4_dev_layout.addWidget(lbl_dev_sub)

        dev_ctrl_row = QHBoxLayout()
        dev_ctrl_row.setContentsMargins(0, 0, 0, 0)
        dev_ctrl_row.setSpacing(8)

        # Styled Status badge container
        status_box = QFrame(block_ds4_dev)
        status_box.setFixedHeight(32)
        status_box.setStyleSheet(f"""
            QFrame {{
                background-color: #F8FAFC;
                border: 1px solid {PALETTE["border_subtle"]};
                border-radius: 6px;
                padding: 0px 8px;
            }}
        """)
        st_box_layout = QHBoxLayout(status_box)
        st_box_layout.setContentsMargins(6, 0, 6, 0)

        self.lbl_ds4_status = QLabel("Status: Controller Connected", status_box)
        self.lbl_ds4_status.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['ps_blue']}; background: transparent; border: none;"
        )
        st_box_layout.addWidget(self.lbl_ds4_status)
        dev_ctrl_row.addWidget(status_box, stretch=1)

        self.btn_refresh_ds4_icon = QPushButton("↻", block_ds4_dev)
        self.btn_refresh_ds4_icon.setFixedSize(34, 32)
        self.btn_refresh_ds4_icon.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh_ds4_icon.setToolTip("Reconnect / Rescan Controller")
        self.btn_refresh_ds4_icon.setStyleSheet(f"""
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
        """)
        self.btn_refresh_ds4_icon.clicked.connect(self._reconnect_ds4)
        dev_ctrl_row.addWidget(self.btn_refresh_ds4_icon)
        ds4_dev_layout.addLayout(dev_ctrl_row)

        ds4_info_layout.addWidget(block_ds4_dev)

        # Block 2: Side-by-side Blocks for Tracked Hand & Sensitivity (Matching block_res & block_fps of Webcam)
        row_settings = QHBoxLayout()
        row_settings.setSpacing(10)

        # Hand block
        block_hand = QFrame(self.ds4_info_frame)
        block_hand.setObjectName("settingBlockDs4Hand")
        block_hand.setFixedHeight(108)
        block_hand.setStyleSheet(f"""
            QFrame#settingBlockDs4Hand {{
                background-color: #FFFFFF;
                border: 1px solid {PALETTE["border_subtle"]};
                border-radius: 10px;
            }}
            QFrame#settingBlockDs4Hand:hover {{
                border-color: {PALETTE["input_border"]};
            }}
        """)
        hand_layout = QVBoxLayout(block_hand)
        hand_layout.setContentsMargins(14, 10, 14, 10)
        hand_layout.setSpacing(4)

        lbl_hand = QLabel("TRACKED HAND", block_hand)
        lbl_hand.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['blue_dark']}; background: transparent; border: none;"
        )
        hand_layout.addWidget(lbl_hand)

        lbl_hand_sub = QLabel("Holding Controller", block_hand)
        lbl_hand_sub.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 10px; color: {PALETTE['text_muted']}; background: transparent; border: none;"
        )
        hand_layout.addWidget(lbl_hand_sub)

        self.cb_ds4_hand = QComboBox(block_hand)
        self.cb_ds4_hand.setFixedHeight(32)
        self.cb_ds4_hand.addItem("Right Hand (Standard)")
        self.cb_ds4_hand.addItem("Left Hand")
        current_hand = self.cfg.get("ds4_hand", "right").lower()
        self.cb_ds4_hand.setCurrentIndex(0 if current_hand == "right" else 1)
        self.cb_ds4_hand.currentIndexChanged.connect(self._on_ds4_hand_changed)
        hand_layout.addWidget(self.cb_ds4_hand)
        row_settings.addWidget(block_hand, stretch=1)

        # Sensitivity block
        block_sens = QFrame(self.ds4_info_frame)
        block_sens.setObjectName("settingBlockDs4Sens")
        block_sens.setFixedHeight(108)
        block_sens.setStyleSheet(f"""
            QFrame#settingBlockDs4Sens {{
                background-color: #FFFFFF;
                border: 1px solid {PALETTE["border_subtle"]};
                border-radius: 10px;
            }}
            QFrame#settingBlockDs4Sens:hover {{
                border-color: {PALETTE["input_border"]};
            }}
        """)
        sens_layout = QVBoxLayout(block_sens)
        sens_layout.setContentsMargins(14, 10, 14, 10)
        sens_layout.setSpacing(4)

        lbl_sens = QLabel("MOTION SENSITIVITY", block_sens)
        lbl_sens.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['blue_dark']}; background: transparent; border: none;"
        )
        sens_layout.addWidget(lbl_sens)

        lbl_sens_sub = QLabel("Hardware Accelerometer Gain", block_sens)
        lbl_sens_sub.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 10px; color: {PALETTE['text_muted']}; background: transparent; border: none;"
        )
        sens_layout.addWidget(lbl_sens_sub)

        self.cb_ds4_sens = QComboBox(block_sens)
        self.cb_ds4_sens.setFixedHeight(32)
        self.cb_ds4_sens.addItem("1.00x (Standard Hardware Scale)")
        self.cb_ds4_sens.addItem("1.25x (High Energy / Fast Dances)")
        self.cb_ds4_sens.addItem("0.85x (Smooth / Gentle Gestures)")
        current_sens = float(self.cfg.get("ds4_sensitivity", 1.0))
        if abs(current_sens - 1.25) < 0.05:
            self.cb_ds4_sens.setCurrentIndex(1)
        elif abs(current_sens - 0.85) < 0.05:
            self.cb_ds4_sens.setCurrentIndex(2)
        else:
            self.cb_ds4_sens.setCurrentIndex(0)
        self.cb_ds4_sens.currentIndexChanged.connect(self._on_ds4_sens_changed)
        sens_layout.addWidget(self.cb_ds4_sens)
        row_settings.addWidget(block_sens, stretch=1)

        ds4_info_layout.addLayout(row_settings)

        # Block 3: Quick Action Buttons (Rumble, Reconnect, Skip Finish)
        actions_row = QHBoxLayout()
        actions_row.setSpacing(10)

        self.btn_ds4_rumble = QPushButton("Test Rumble Vibration", self.ds4_info_frame)
        self.btn_ds4_rumble.setFixedHeight(36)
        self.btn_ds4_rumble.setStyleSheet(f"""
            QPushButton {{
                background-color: #FFFFFF;
                color: {PALETTE["ps_blue"]};
                font-family: '{self.font_heading}', sans-serif;
                font-size: 11px;
                font-weight: bold;
                border: 1px solid {PALETTE["tab_gray_border"]};
                border-radius: 6px;
                padding: 6px 16px;
            }}
            QPushButton:hover {{
                border-color: {PALETTE["ps_blue"]};
                background-color: #F8FAFC;
            }}
        """)
        self.btn_ds4_rumble.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ds4_rumble.clicked.connect(self._test_ds4_rumble)

        self.btn_ds4_reconnect = QPushButton("Reconnect Controller", self.ds4_info_frame)
        self.btn_ds4_reconnect.setFixedHeight(36)
        self.btn_ds4_reconnect.setStyleSheet(f"""
            QPushButton {{
                background-color: #FFFFFF;
                color: #0F172A;
                font-family: '{self.font_heading}', sans-serif;
                font-size: 11px;
                font-weight: bold;
                border: 1px solid {PALETTE["tab_gray_border"]};
                border-radius: 6px;
                padding: 6px 16px;
            }}
            QPushButton:hover {{
                border-color: {PALETTE["ps_blue"]};
                background-color: #F8FAFC;
            }}
        """)
        self.btn_ds4_reconnect.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ds4_reconnect.clicked.connect(self._reconnect_ds4)

        actions_row.addWidget(self.btn_ds4_rumble)
        actions_row.addWidget(self.btn_ds4_reconnect)
        actions_row.addStretch()
        ds4_info_layout.addLayout(actions_row)

        # Hidden Telemetry Readout (kept for backward compatibility, hidden per user request)
        self.lbl_ds4_accel = QLabel("", self.ds4_info_frame)
        self.lbl_ds4_accel.setVisible(False)
        ds4_info_layout.addWidget(self.lbl_ds4_accel)

        # Instruction details
        lbl_instructions = QLabel(
            "• Hold the DualShock 4 in your active dancing hand with the light bar pointing forward.\n"
            "• When started, the controller's internal 6-axis IMU will stream motion data directly to Just Dance via the Virtual Phone scoring bridge.",
            self.ds4_info_frame
        )
        lbl_instructions.setWordWrap(True)
        lbl_instructions.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 11px; color: {PALETTE['text_muted']}; line-height: 1.4; background: transparent; border: none;"
        )
        ds4_info_layout.addWidget(lbl_instructions)

        ds4_layout.addWidget(self.ds4_info_frame)

        # =====================================================================
        # Scoring Bridge (Just Dance Controller App mode) Block
        # =====================================================================
        self.scoring_bridge_box = QFrame(ds4_card)
        self.scoring_bridge_box.setObjectName("settingBlockScoringBridge")
        self.scoring_bridge_box.setStyleSheet(f"""
            QFrame#settingBlockScoringBridge {{
                background-color: #FFFFFF;
                border: 1px solid {PALETTE["border_subtle"]};
                border-radius: 10px;
            }}
            QFrame#settingBlockScoringBridge:hover {{
                border-color: {PALETTE["input_border"]};
            }}
        """)
        sb_layout = QVBoxLayout(self.scoring_bridge_box)
        sb_layout.setContentsMargins(14, 12, 14, 12)
        sb_layout.setSpacing(8)

        lbl_sb_title = QLabel("SCORING BRIDGE (JUST DANCE CONTROLLER APP MODE)", self.scoring_bridge_box)
        lbl_sb_title.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['blue_dark']}; background: transparent; border: none;"
        )
        sb_layout.addWidget(lbl_sb_title)

        self.lbl_ds4_sb_desc = QLabel(
            "Emulates a smartphone connected to Just Dance via WebSocket/TLS (/smartphone) and converts your hand motion "
            "in the camera into 3D accelerometer commands for songs that only support hand controllers.",
            self.scoring_bridge_box
        )
        self.lbl_ds4_sb_desc.setWordWrap(True)
        self.lbl_ds4_sb_desc.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 11px; color: {PALETTE['text_muted']}; background: transparent; border: none;"
        )
        sb_layout.addWidget(self.lbl_ds4_sb_desc)

        # Status badge container
        sb_status_box = QFrame(self.scoring_bridge_box)
        sb_status_box.setFixedHeight(32)
        sb_status_box.setStyleSheet(f"""
            QFrame {{
                background-color: #F8FAFC;
                border: 1px solid {PALETTE["border_subtle"]};
                border-radius: 6px;
                padding: 0px 8px;
            }}
        """)
        sb_st_layout = QHBoxLayout(sb_status_box)
        sb_st_layout.setContentsMargins(8, 0, 8, 0)

        self.lbl_ds4_sb_status = QLabel("Status: Disconnected", sb_status_box)
        self.lbl_ds4_sb_status.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['text_muted']}; background: transparent; border: none;"
        )
        sb_st_layout.addWidget(self.lbl_ds4_sb_status)
        sb_layout.addWidget(sb_status_box)

        # Action buttons row: Reconnect Game, Auto-Find, Skip Finish
        btn_sb_outline_style = getattr(self, "_btn_vphone_outline_style", "")

        sb_btn_row = QHBoxLayout()
        sb_btn_row.setSpacing(8)

        self.btn_ds4_sb_reconnect = QPushButton("Reconnect Game", self.scoring_bridge_box)
        self.btn_ds4_sb_reconnect.setFixedHeight(34)
        self.btn_ds4_sb_reconnect.setStyleSheet(btn_sb_outline_style)
        self.btn_ds4_sb_reconnect.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ds4_sb_reconnect.clicked.connect(self._on_vphone_reconnect_clicked)

        self.btn_ds4_sb_discover = QPushButton("Auto-Find", self.scoring_bridge_box)
        self.btn_ds4_sb_discover.setFixedHeight(34)
        self.btn_ds4_sb_discover.setStyleSheet(btn_sb_outline_style)
        self.btn_ds4_sb_discover.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ds4_sb_discover.clicked.connect(self._on_vphone_discover_clicked)

        self.btn_ds4_sb_ftue = QPushButton("Skip Finish", self.scoring_bridge_box)
        self.btn_ds4_sb_ftue.setFixedHeight(34)
        self.btn_ds4_sb_ftue.setStyleSheet(btn_sb_outline_style)
        self.btn_ds4_sb_ftue.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ds4_sb_ftue.setToolTip("Skip phone tutorial prompt in Just Dance PC")
        self.btn_ds4_sb_ftue.clicked.connect(self._on_skip_finish_clicked)

        sb_btn_row.addWidget(self.btn_ds4_sb_reconnect)
        sb_btn_row.addWidget(self.btn_ds4_sb_discover)
        sb_btn_row.addWidget(self.btn_ds4_sb_ftue)
        sb_btn_row.addStretch()
        sb_layout.addLayout(sb_btn_row)

        ds4_layout.addWidget(self.scoring_bridge_box)
        self.btn_ds4_skip_finish = self.btn_ds4_sb_ftue

        # Initial visibility: disconnected balloon shown, details hidden until connected
        self.ds4_disconnected_box.setVisible(True)
        self.ds4_info_frame.setVisible(False)
        layout.addWidget(ds4_card)
        layout.addStretch()

        self.scroll_ds4 = self._create_scroll_page(self.page_ds4)
        self.stacked_view.addWidget(self.scroll_ds4)
        self._update_vphone_ui_readout()
