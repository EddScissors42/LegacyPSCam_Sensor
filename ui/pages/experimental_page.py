"""
Declarative Qt 6 Page 2 Builder: Experimental Features.
Constructs the caution banner and Auto-Frame Digital PTZ toggle for camera modes,
and a clean empty placeholder when in DualShock 4 mode.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QFrame
)

from ui.theme import PALETTE


class UIExperimentalPageMixin:
    """Declarative builder for Page 2 (Experimental Features)."""

    def _build_exp_view(self):
        """Constructs Page 2: Experimental Features (Digital PTZ in Camera modes; clean placeholder in DS4 mode)."""
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

        # Empty placeholder shown ONLY in DualShock 4 mode
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
        lbl_warn_icon.setStyleSheet(
            "font-family: monospace; font-size: 14px; font-weight: bold; color: #92400E; background: transparent; border: none;"
        )
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

        layout.addWidget(exp_card)
        layout.addStretch()

        self.scroll_exp = self._create_scroll_page(self.page_exp)
        self.stacked_view.addWidget(self.scroll_exp)
        self._update_exp_view_for_mode(self.cfg.get("camera_mode", "pscam"))
