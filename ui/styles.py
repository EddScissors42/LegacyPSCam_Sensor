"""
Qt 6 Stylesheet (QSS) Builders for Legacy PSCam Sensor.
Centralizes the Crisp White & PlayStation Blue (#00439C) visual styling
extracted from `ui/gui_qt.py`.
"""
from __future__ import annotations

from ui.theme import PALETTE


def build_main_stylesheet(font_body: str, font_heading: str, arrow_url: str) -> str:
    """Builds the main application QSS stylesheet."""
    return f"""
        QMainWindow, QWidget#centralWidget {{
            background-color: {PALETTE["bg_window"]};
            color: {PALETTE["text_main"]};
            font-family: '{font_body}', 'Segoe UI', sans-serif;
        }}
        QToolTip {{
            background-color: #0F172A;
            color: #FFFFFF;
            border: 1px solid #334155;
            border-radius: 6px;
            padding: 6px 10px;
            font-family: '{font_body}', sans-serif;
            font-size: 11px;
            font-weight: 500;
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
            font-family: '{font_heading}', sans-serif;
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
            font-family: '{font_heading}', sans-serif;
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
            font-family: '{font_heading}', sans-serif;
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
            font-family: '{font_body}', sans-serif;
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
            font-family: '{font_body}', sans-serif;
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
            font-family: '{font_body}', sans-serif;
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
    """


__all__ = ["build_main_stylesheet"]
