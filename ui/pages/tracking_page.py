"""
Declarative Qt 6 Page 1 Builder: Tracking & Motion Profile.
Constructs the Competitive/Balanced profile cards, model download banner,
1P/2P selector, automatic height calibration callout, and hidden advanced drawer.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QFrame, QSlider
)

from ui.theme import PALETTE, CALIB_PRESETS
from ui.widgets import CalibPresetCard, SettingBlock


class UITrackingPageMixin:
    """Declarative builder for Page 1 (Tracking & Calibration)."""

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
        self.model_dl_box.setStyleSheet("""
            QFrame#modelDownloadBox {
                background-color: #EFF6FF;
                border: 1px solid #93C5FD;
                border-radius: 8px;
            }
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
        self.block_players_mode = SettingBlock(
            "PLAYERS MODE",
            "Choose whether to play by yourself or dance with a friend. The sensor tracks both players smoothly without mixing anyone up, even when dancing close together.",
            object_name="settingBlockPlayersMode",
            font_heading=self.font_heading,
            font_body=self.font_body,
            min_height=96,
            spacing=3,
            parent=main_card,
        )
        pm_layout = self.block_players_mode.content_layout

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
