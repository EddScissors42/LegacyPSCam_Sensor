"""
Declarative Qt 6 Page 3 Builder: DualShock 4 Controller Settings.
Constructs the caution banner, Permissive Discovery toggle, disconnected balloon,
and connected controller hardware + PlayStation Move (ZCM2) Emulator block (ds4_info_frame).
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QCheckBox, QFrame
)

from ui.theme import PALETTE
from ui.widgets import SettingBlock


class UIDS4PageMixin:
    """Declarative builder for Page 3 (DualShock 4 Controller Settings)."""

    def _build_ds4_view(self):
        """Constructs Page 3: DualShock 4 Controller & PlayStation Move Emulator Settings."""
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

        lbl_sub = QLabel(
            "Emulate a native PlayStation Move (ZCM2) motion controller using your DualShock 4's 6-axis IMU.",
            ds4_card,
        )
        lbl_sub.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 11px; color: {PALETTE['text_muted']}; background: transparent; border: none;"
        )
        ds4_layout.addWidget(lbl_sub)

        # Warning Callout Box
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
        lbl_warn_icon.setStyleSheet(
            "font-family: monospace; font-size: 14px; font-weight: bold; color: #92400E; background: transparent; border: none;"
        )
        warn_layout.addWidget(lbl_warn_icon, alignment=Qt.AlignmentFlag.AlignTop)

        lbl_warn_text = QLabel(
            "CAUTION: Hold the DualShock 4 firmly while dancing! This mode emulates a native PlayStation Move "
            "controller in memory (Legacy 2018 Offline, Legacy Lab, and Legacy Lab Offline) using your controller's "
            "6-axis accelerometer and gyroscope with zero driver installation required.",
            warn_box,
        )
        lbl_warn_text.setWordWrap(True)
        lbl_warn_text.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 11px; font-weight: 500; color: #92400E; background: transparent; border: none;"
        )
        warn_layout.addWidget(lbl_warn_text, stretch=1)
        ds4_layout.addWidget(warn_box)

        # Permissive Mode Toggle
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

        self.btn_refresh_ds4 = QPushButton("Search for Controllers", self.ds4_disconnected_box)
        self.btn_refresh_ds4.setProperty("class", "btn_balloon_action")
        self.btn_refresh_ds4.setFixedHeight(42)
        self.btn_refresh_ds4.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh_ds4.clicked.connect(self._reconnect_ds4)
        ds4_disc_layout.addWidget(self.btn_refresh_ds4)

        ds4_layout.addWidget(self.ds4_disconnected_box)

        # =====================================================================
        # Connected Controller View (Shown ONLY when a DualShock 4 is connected)
        # =====================================================================
        self.ds4_info_frame = QWidget(ds4_card)
        ds4_info_layout = QVBoxLayout(self.ds4_info_frame)
        ds4_info_layout.setContentsMargins(0, 0, 0, 0)
        ds4_info_layout.setSpacing(10)

        # Block 1: Active Controller Device & Refresh
        block_ds4_dev = SettingBlock(
            "CONTROLLER HARDWARE",
            "Active Wireless / USB Motion Device",
            object_name="settingBlockDs4Dev",
            font_heading=self.font_heading,
            font_body=self.font_body,
            min_height=90,
            parent=self.ds4_info_frame,
        )
        ds4_dev_layout = block_ds4_dev.content_layout

        dev_ctrl_row = QHBoxLayout()
        dev_ctrl_row.setContentsMargins(0, 0, 0, 0)
        dev_ctrl_row.setSpacing(8)

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

        self.btn_refresh_ds4_icon = self._create_reload_button(
            block_ds4_dev,
            "Reconnect / Rescan Controller",
            self._reconnect_ds4,
        )
        dev_ctrl_row.addWidget(self.btn_refresh_ds4_icon)
        ds4_dev_layout.addLayout(dev_ctrl_row)

        ds4_info_layout.addWidget(block_ds4_dev)

        # Block 2: Side-by-side Blocks for Tracked Hand & Sensitivity
        row_settings = QHBoxLayout()
        row_settings.setSpacing(10)

        block_hand = SettingBlock(
            "TRACKED HAND",
            "Holding Controller",
            object_name="settingBlockDs4Hand",
            font_heading=self.font_heading,
            font_body=self.font_body,
            min_height=108,
            parent=self.ds4_info_frame,
        )
        hand_layout = block_hand.content_layout

        self.cb_ds4_hand = QComboBox(block_hand)
        self.cb_ds4_hand.setFixedHeight(32)
        self.cb_ds4_hand.addItem("Right Hand (Standard)")
        self.cb_ds4_hand.addItem("Left Hand")
        current_hand = self.cfg.get("ds4_hand", "right").lower()
        self.cb_ds4_hand.setCurrentIndex(0 if current_hand == "right" else 1)
        self.cb_ds4_hand.currentIndexChanged.connect(self._on_ds4_hand_changed)
        hand_layout.addWidget(self.cb_ds4_hand)
        row_settings.addWidget(block_hand, stretch=1)

        block_sens = SettingBlock(
            "MOTION SENSITIVITY",
            "Hardware IMU Gain",
            object_name="settingBlockDs4Sens",
            font_heading=self.font_heading,
            font_body=self.font_body,
            min_height=108,
            parent=self.ds4_info_frame,
        )
        sens_layout = block_sens.content_layout

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

        # Block 3: Quick Action Buttons (Rumble, Reconnect)
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

        # Hidden Telemetry Readout (kept for backward compatibility)
        self.lbl_ds4_accel = QLabel("", self.ds4_info_frame)
        self.lbl_ds4_accel.setVisible(False)
        ds4_info_layout.addWidget(self.lbl_ds4_accel)

        # Grip instruction details
        lbl_instructions = QLabel(
            "• Hold the DualShock 4 vertically (thumbs-up grip) with your fingers near the touchpad and thumb below the right stick.\n"
            "• Click START CONTROLLER (DS4) and Just Dance will automatically detect a PlayStation Move (ZCM2) within ~2 seconds.",
            self.ds4_info_frame,
        )
        lbl_instructions.setWordWrap(True)
        lbl_instructions.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 11px; color: {PALETTE['text_muted']}; background: transparent; border: none;"
        )
        ds4_info_layout.addWidget(lbl_instructions)

        # =====================================================================
        # PlayStation Move (ZCM2) Native Emulator Block
        # Lives inside ds4_info_frame so it ONLY appears when a DS4 is connected.
        # =====================================================================
        self.psmove_bridge_box = QFrame(self.ds4_info_frame)
        self.psmove_bridge_box.setObjectName("settingBlockPSMoveBridge")
        self.psmove_bridge_box.setStyleSheet(f"""
            QFrame#settingBlockPSMoveBridge {{
                background-color: #FFFFFF;
                border: 1px solid {PALETTE["border_subtle"]};
                border-radius: 10px;
            }}
            QFrame#settingBlockPSMoveBridge:hover {{
                border-color: {PALETTE["input_border"]};
            }}
        """)
        pm_layout = QVBoxLayout(self.psmove_bridge_box)
        pm_layout.setContentsMargins(14, 12, 14, 12)
        pm_layout.setSpacing(8)

        lbl_pm_title = QLabel("PLAYSTATION MOVE EMULATOR (NATIVE ZCM2)", self.psmove_bridge_box)
        lbl_pm_title.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['blue_dark']}; background: transparent; border: none;"
        )
        pm_layout.addWidget(lbl_pm_title)

        self.lbl_ds4_pm_desc = QLabel(
            "Exposes a virtual PlayStation Move (ZCM2) controller directly in memory to Just Dance PC "
            "(6-axis accelerometer + gyroscope, native menu buttons, Light Bar color sync, and Gold Move rumble).",
            self.psmove_bridge_box,
        )
        self.lbl_ds4_pm_desc.setWordWrap(True)
        self.lbl_ds4_pm_desc.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 11px; color: {PALETTE['text_muted']}; background: transparent; border: none;"
        )
        pm_layout.addWidget(self.lbl_ds4_pm_desc)

        # Status badge container with live sphere color swatch
        pm_status_box = QFrame(self.psmove_bridge_box)
        pm_status_box.setFixedHeight(32)
        pm_status_box.setStyleSheet(f"""
            QFrame {{
                background-color: #F8FAFC;
                border: 1px solid {PALETTE["border_subtle"]};
                border-radius: 6px;
                padding: 0px 8px;
            }}
        """)
        pm_st_layout = QHBoxLayout(pm_status_box)
        pm_st_layout.setContentsMargins(8, 0, 8, 0)
        pm_st_layout.setSpacing(8)

        self.lbl_psmove_swatch = QLabel("", pm_status_box)
        self.lbl_psmove_swatch.setFixedSize(12, 12)
        self.lbl_psmove_swatch.setStyleSheet(
            "background-color: #00439C; border: 1px solid #CBD5E1; border-radius: 6px;"
        )
        pm_st_layout.addWidget(self.lbl_psmove_swatch)

        self.lbl_ds4_pm_status = QLabel("Status: Ready (Start controller session to connect to Just Dance)", pm_status_box)
        self.lbl_ds4_pm_status.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['text_muted']}; background: transparent; border: none;"
        )
        pm_st_layout.addWidget(self.lbl_ds4_pm_status, stretch=1)
        pm_layout.addWidget(pm_status_box)

        # Light Bar & Rumble Sync checkbox
        self.chk_ds4_sync_lightbar = QCheckBox(
            "Sync DualShock 4 Light Bar & Rumble with Just Dance Player Color",
            self.psmove_bridge_box,
        )
        self.chk_ds4_sync_lightbar.setChecked(bool(self.cfg.get("ds4_sync_lightbar", True)))
        self.chk_ds4_sync_lightbar.setStyleSheet(f"""
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
        self.chk_ds4_sync_lightbar.stateChanged.connect(self._on_ds4_sync_lightbar_changed)
        pm_layout.addWidget(self.chk_ds4_sync_lightbar)

        # Compact button map reference
        lbl_btn_map = QLabel(
            "Buttons: R2 = Trigger (T)  •  Cross / R1 = Move (Confirm)  •  Circle = Back  •  Options = Start  •  PS = Menu",
            self.psmove_bridge_box,
        )
        lbl_btn_map.setWordWrap(True)
        lbl_btn_map.setStyleSheet(
            f"font-family: '{self.font_body}'; font-size: 10px; color: {PALETTE['text_muted']}; background: transparent; border: none;"
        )
        pm_layout.addWidget(lbl_btn_map)

        ds4_info_layout.addWidget(self.psmove_bridge_box)

        ds4_layout.addWidget(self.ds4_info_frame)

        # Initial visibility: disconnected balloon shown, details & PS Move Emulator hidden until connected
        self.ds4_disconnected_box.setVisible(True)
        self.ds4_info_frame.setVisible(False)
        layout.addWidget(ds4_card)
        layout.addStretch()

        self.scroll_ds4 = self._create_scroll_page(self.page_ds4)
        self.stacked_view.addWidget(self.scroll_ds4)
        self._update_device_readout()
