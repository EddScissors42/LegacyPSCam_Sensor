"""
Declarative Qt 6 Page 2 Builder: Experimental Features.
Constructs the caution banner, Auto-Frame Digital PTZ toggle,
Virtual Phone Controller panel, and preserved hidden Telemetry Benchmark handles.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QCheckBox, QFrame, QLineEdit
)

from ui.theme import PALETTE


class UIExperimentalPageMixin:
    """Declarative builder for Page 2 (Experimental Features)."""

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
