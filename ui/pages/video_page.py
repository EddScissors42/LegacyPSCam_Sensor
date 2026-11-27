"""
Declarative Qt 6 Page 0 Builder: Video Settings.
Constructs the PlayStation 4 Camera, Standard Webcam, Phone Camera (Wi-Fi QR),
and Additional Display Options sections.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QCheckBox, QFrame
)

from ui.theme import PALETTE
from ui.widgets import SettingBlock


class UIVideoPageMixin:
    """Declarative builder for Page 0 (Video Settings)."""

    def _build_video_view(self):
        """Constructs Page 0: Video Settings."""
        self.page_video = QWidget()
        layout = QVBoxLayout(self.page_video)
        layout.setContentsMargins(0, 4, 6, 0)
        layout.setSpacing(12)

        self._build_pscam_section(layout)
        self._build_webcam_section(layout)
        self._build_phone_cam_section(layout)
        self._build_display_options_section(layout)

        layout.addStretch()

        self.scroll_video = self._create_scroll_page(self.page_video)
        self.stacked_view.addWidget(self.scroll_video)

    def _build_pscam_section(self, layout: QVBoxLayout):
        """Constructs PlayStation 4 Camera disconnected balloon & connected options card."""
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
        self.block_ps_eye = SettingBlock(
            "CAMERA SENSOR EYE (OV9713 STEREO)",
            "Select which lens feeds body tracking (Right Eye is the standard default).",
            object_name="settingBlockPsEye",
            font_heading=self.font_heading,
            font_body=self.font_body,
            min_height=92,
            disabled_style=True,
            parent=self.pscam_card,
        )
        ps_eye_layout = self.block_ps_eye.content_layout

        self.cb_ps4_eye = QComboBox(self.block_ps_eye)
        self.cb_ps4_eye.setFixedHeight(32)
        self.cb_ps4_eye.addItems(["Right Eye (Default)", "Left Eye"])
        curr_eye = str(self.cfg.get("ps4_eye", "right")).strip().lower()
        self.cb_ps4_eye.setCurrentIndex(1 if curr_eye == "left" else 0)
        self.cb_ps4_eye.currentIndexChanged.connect(self._on_ps4_eye_changed)
        ps_eye_layout.addWidget(self.cb_ps4_eye)

        ps_conn_layout.addWidget(self.block_ps_eye)

        layout.addWidget(self.pscam_card)

    def _build_webcam_section(self, layout: QVBoxLayout):
        """Constructs Standard Webcam disconnected balloon & connected settings card."""
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
        block_dev = SettingBlock(
            "CAMERA DEVICE",
            "Active Video Source",
            object_name="settingBlockDev",
            font_heading=self.font_heading,
            font_body=self.font_body,
            min_height=90,
            parent=self.webcam_card,
        )
        dev_layout = block_dev.content_layout

        dev_ctrl_row = QHBoxLayout()
        dev_ctrl_row.setContentsMargins(0, 0, 0, 0)
        dev_ctrl_row.setSpacing(6)

        self.cb_cameras = QComboBox(block_dev)
        self.cb_cameras.setFixedHeight(32)
        self.cb_cameras.currentIndexChanged.connect(self._on_camera_selected)
        dev_ctrl_row.addWidget(self.cb_cameras, stretch=1)

        self.btn_refresh = self._create_reload_button(
            block_dev,
            "Scan / Refresh connected webcams",
            self._refresh_cameras,
        )
        dev_ctrl_row.addWidget(self.btn_refresh)
        dev_layout.addLayout(dev_ctrl_row)

        web_conn_layout.addWidget(block_dev)

        # 2. Row 2: Resolution & FPS side-by-side blocks below Camera Device
        row_res_fps = QHBoxLayout()
        row_res_fps.setSpacing(10)

        # Block 2: Resolution
        block_res = SettingBlock(
            "RESOLUTION",
            "Sharper picture, but higher CPU usage. The game still receives as 640x480.",
            object_name="settingBlockRes",
            font_heading=self.font_heading,
            font_body=self.font_body,
            min_height=108,
            parent=self.webcam_card,
        )
        res_layout = block_res.content_layout

        self.cb_res = QComboBox(block_res)
        self.cb_res.setFixedHeight(32)
        self.cb_res.addItems(["640x480 (Recommended)", "1280x720", "1920x1080"])
        self.cb_res.currentIndexChanged.connect(self._on_webcam_res_or_fps_changed)
        res_layout.addWidget(self.cb_res)
        row_res_fps.addWidget(block_res, stretch=1)

        # Block 3: FPS
        block_fps = SettingBlock(
            "FRAMERATE (FPS)",
            "Target capture speed. 60 FPS requires camera support and more CPU.",
            object_name="settingBlockFps",
            font_heading=self.font_heading,
            font_body=self.font_body,
            min_height=108,
            parent=self.webcam_card,
        )
        fps_layout = block_fps.content_layout

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

    def _build_phone_cam_section(self, layout: QVBoxLayout):
        """Constructs Phone Camera (Wi-Fi WebApp QR Code) disconnected & connected views."""
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
            f"font-family: '{self.font_body}'; font-size: 11px; color: {PALETTE['text_main']}; background: transparent; border: none;"
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

        self.btn_refresh_phone_qr = self._create_reload_button(
            self.phone_cam_qr_card,
            "Refresh local IP and QR Code",
            lambda: self._refresh_phone_cam_qr(rotate_token=True),
        )
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
        block_ph_dev = SettingBlock(
            "CONNECTED SMARTPHONE",
            object_name="settingBlockPhoneDev",
            font_heading=self.font_heading,
            font_body=self.font_body,
            min_height=64,
            parent=self.phone_cam_card,
        )
        ph_dev_layout = block_ph_dev.content_layout

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

        block_ph_res = SettingBlock(
            "RESOLUTION",
            "640x480 provides the lowest Wi-Fi latency. The game receives 640x480.",
            object_name="settingBlockPhoneRes",
            font_heading=self.font_heading,
            font_body=self.font_body,
            min_height=108,
            parent=self.phone_cam_card,
        )
        ph_res_layout = block_ph_res.content_layout

        self.cb_phone_res = QComboBox(block_ph_res)
        self.cb_phone_res.setFixedHeight(32)
        self.cb_phone_res.addItems(["640x480 (Recommended)", "1280x720"])
        self.cb_phone_res.currentIndexChanged.connect(self._on_phone_cam_settings_changed)
        ph_res_layout.addWidget(self.cb_phone_res)
        row_ph_res_fps.addWidget(block_ph_res, stretch=1)

        block_ph_fps = SettingBlock(
            "FRAMERATE (FPS)",
            "Target wireless stream speed. 60 FPS requires strong 5 GHz Wi-Fi signal.",
            object_name="settingBlockPhoneFps",
            font_heading=self.font_heading,
            font_body=self.font_body,
            min_height=108,
            parent=self.phone_cam_card,
        )
        ph_fps_layout = block_ph_fps.content_layout

        self.cb_phone_fps = QComboBox(block_ph_fps)
        self.cb_phone_fps.setFixedHeight(32)
        self.cb_phone_fps.addItems(["30 FPS (Recommended)", "60 FPS"])
        self.cb_phone_fps.currentIndexChanged.connect(self._on_phone_cam_settings_changed)
        ph_fps_layout.addWidget(self.cb_phone_fps)
        row_ph_res_fps.addWidget(block_ph_fps, stretch=1)

        ph_conn_layout.addLayout(row_ph_res_fps)
        layout.addWidget(self.phone_cam_card)

    def _build_display_options_section(self, layout: QVBoxLayout):
        """Constructs Additional Display Options card (shown ONLY when connected)."""
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
        block_orient = SettingBlock(
            "CAMERA ORIENTATION",
            "Rotation angle if your camera is physically mounted sideways or inverted.",
            object_name="settingBlockOrient",
            font_heading=self.font_heading,
            font_body=self.font_body,
            min_height=92,
            parent=self.display_card,
        )
        orient_layout = block_orient.content_layout

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
