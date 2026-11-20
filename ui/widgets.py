"""
Reusable custom Qt 6 widgets and High-DPI image utilities for Legacy PSCam Sensor.
"""
from typing import Dict, Optional

from PySide6.QtCore import (
    Qt, QPropertyAnimation, QEasingCurve, QPoint, Signal, QParallelAnimationGroup
)
from PySide6.QtWidgets import (
    QStackedWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel
)
from PySide6.QtGui import QPixmap, QImage

from ui.theme import PALETTE


def pil_to_qpixmap(pil_img, dpr: float = 4.0) -> QPixmap:
    """Converts a Pillow RGBA Image to a Qt QPixmap with explicit stride, deep copy, and High-DPI devicePixelRatio."""
    if pil_img is None:
        return QPixmap()
    img_rgba = pil_img.convert("RGBA")
    data = img_rgba.tobytes("raw", "RGBA")
    qimg = QImage(
        data,
        img_rgba.width,
        img_rgba.height,
        img_rgba.width * 4,
        QImage.Format.Format_RGBA8888
    ).copy()
    pm = QPixmap.fromImage(qimg)
    if dpr > 1.0:
        pm.setDevicePixelRatio(dpr)
    return pm


class SlidingStackedWidget(QStackedWidget):
    """
    QStackedWidget featuring hardware-friendly sliding animations between pages
    with cubic easing curves.
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
        if w <= 0 or h <= 0:
            self.setCurrentIndex(index)
            return

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
            next_widget.move(0, 0)
            self._is_animating = False

        self.anim_group.finished.connect(on_finished)
        self.anim_group.start()


class DeviceNavCard(QFrame):
    """
    Interactive rounded navigation card for the sidebar (PlayStation Camera / Standard Webcam / DualShock 4).
    Displays a crisp 38x26 icon on the left and two-line title/subtitle on the right.
    """
    clicked = Signal()

    def __init__(self, title: str, subtitle: str, font_heading: str, font_body: str, parent=None):
        super().__init__(parent)
        self.font_heading = font_heading
        self.font_body = font_body
        self._is_active = False
        self._pix_act = QPixmap()
        self._pix_inact = QPixmap()

        self.setFixedHeight(58)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        self.lbl_icon = QLabel(self)
        self.lbl_icon.setFixedSize(38, 26)
        self.lbl_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_icon.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(self.lbl_icon)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)

        self.lbl_title = QLabel(title, self)
        self.lbl_sub = QLabel(subtitle, self)
        text_col.addWidget(self.lbl_title)
        text_col.addWidget(self.lbl_sub)
        layout.addLayout(text_col, stretch=1)

    def set_icons(self, pix_act: QPixmap, pix_inact: QPixmap):
        self._pix_act = pix_act
        self._pix_inact = pix_inact
        self._refresh_visuals(hovered=False)

    def set_active(self, active: bool):
        self._is_active = active
        self._refresh_visuals(hovered=False)

    def _refresh_visuals(self, hovered: bool = False):
        if self._is_active:
            self.setStyleSheet(f"""
                DeviceNavCard {{
                    background-color: {PALETTE["ps_blue"]};
                    border: 1px solid {PALETTE["ps_blue"]};
                    border-radius: 12px;
                }}
            """)
            self.lbl_title.setStyleSheet(
                f"font-family: '{self.font_heading}'; font-size: 12px; font-weight: bold; color: {PALETTE['text_white']}; background: transparent; border: none;"
            )
            self.lbl_sub.setStyleSheet(
                f"font-family: '{self.font_body}'; font-size: 10px; color: {PALETTE['blue_pastel']}; background: transparent; border: none;"
            )
            if not self._pix_act.isNull():
                self.lbl_icon.setPixmap(self._pix_act)
        else:
            bg = "#F1F5F9" if hovered else "#F8FAFC"
            bdr = "#CBD5E1" if hovered else PALETTE["border_subtle"]
            self.setStyleSheet(f"""
                DeviceNavCard {{
                    background-color: {bg};
                    border: 1px solid {bdr};
                    border-radius: 12px;
                }}
            """)
            self.lbl_title.setStyleSheet(
                f"font-family: '{self.font_heading}'; font-size: 12px; font-weight: bold; color: {PALETTE['text_main']}; background: transparent; border: none;"
            )
            self.lbl_sub.setStyleSheet(
                f"font-family: '{self.font_body}'; font-size: 10px; color: {PALETTE['text_muted']}; background: transparent; border: none;"
            )
            if not self._pix_inact.isNull():
                self.lbl_icon.setPixmap(self._pix_inact)

    def enterEvent(self, event):
        if not self._is_active:
            self._refresh_visuals(hovered=True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self._is_active:
            self._refresh_visuals(hovered=False)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class CalibPresetCard(QFrame):
    """Interactive card for calibration presets (Balanced, Competitive, Ultra Stable)."""
    clicked = Signal(str)

    def __init__(
        self,
        preset_id: str,
        pdata: Dict,
        font_heading: str,
        font_body: str,
        pix_act: Optional[QPixmap] = None,
        pix_inact: Optional[QPixmap] = None,
        parent=None
    ):
        super().__init__(parent)
        self.preset_id = preset_id
        self.pdata = pdata
        self.font_heading = font_heading
        self.font_body = font_body
        self.pix_act = pix_act or QPixmap()
        self.pix_inact = pix_inact or QPixmap()
        self._is_active = False

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(140)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(6)

        self.lbl_icon = QLabel(self)
        self.lbl_icon.setFixedSize(15, 15)
        self.lbl_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_icon.setStyleSheet("background: transparent; border: none;")

        self.lbl_title = QLabel(pdata["title"], self)
        tag_text = pdata.get("tag", "")
        self.lbl_tag = QLabel(tag_text, self)
        if not tag_text:
            self.lbl_tag.setVisible(False)

        top_row.addWidget(self.lbl_icon)
        top_row.addWidget(self.lbl_title)
        top_row.addStretch()
        top_row.addWidget(self.lbl_tag)
        layout.addLayout(top_row)

        self.lbl_sub = QLabel(pdata["subtitle"], self)
        layout.addWidget(self.lbl_sub)

        self.lbl_desc = QLabel(pdata["desc"], self)
        self.lbl_desc.setWordWrap(True)
        layout.addWidget(self.lbl_desc, stretch=1)

        self.set_active(False)

    def set_active(self, active: bool, hovered: bool = False):
        self._is_active = active
        if active:
            if not self.pix_act.isNull():
                self.lbl_icon.setPixmap(self.pix_act)
            bg = PALETTE["ps_blue_tint"]
            self.setStyleSheet(f"""
                CalibPresetCard {{
                    background-color: {bg};
                    border: 2px solid {PALETTE["ps_blue"]};
                    border-radius: 10px;
                }}
            """)
            self.lbl_title.setStyleSheet(
                f"font-family: '{self.font_heading}'; font-size: 12px; font-weight: bold; color: {PALETTE['ps_blue']}; background: transparent; border: none;"
            )
            self.lbl_tag.setStyleSheet(
                f"font-family: '{self.font_heading}'; font-size: 8px; font-weight: bold; color: #FFFFFF; background-color: {PALETTE['ps_blue']}; padding: 2px 6px; border-radius: 4px; border: none;"
            )
            self.lbl_sub.setStyleSheet(
                f"font-family: '{self.font_heading}'; font-size: 10px; font-weight: bold; color: {PALETTE['blue_dark']}; background: transparent; border: none;"
            )
            self.lbl_desc.setStyleSheet(
                f"font-family: '{self.font_body}'; font-size: 10px; color: {PALETTE['text_main']}; background: transparent; border: none;"
            )
        else:
            if not self.pix_inact.isNull():
                self.lbl_icon.setPixmap(self.pix_inact)
            bg = PALETTE["bg_card"]
            bdr = PALETTE["input_border"] if hovered else PALETTE["border_subtle"]
            self.setStyleSheet(f"""
                CalibPresetCard {{
                    background-color: {bg};
                    border: 1px solid {bdr};
                    border-radius: 10px;
                }}
            """)
            self.lbl_title.setStyleSheet(
                f"font-family: '{self.font_heading}'; font-size: 12px; font-weight: bold; color: {PALETTE['text_main']}; background: transparent; border: none;"
            )
            self.lbl_tag.setStyleSheet(
                f"font-family: '{self.font_heading}'; font-size: 8px; font-weight: bold; color: {PALETTE['text_muted']}; background-color: {PALETTE['input_bg']}; padding: 2px 6px; border-radius: 4px; border: none;"
            )
            self.lbl_sub.setStyleSheet(
                f"font-family: '{self.font_heading}'; font-size: 10px; font-weight: bold; color: {PALETTE['blue_dark']}; background: transparent; border: none;"
            )
            self.lbl_desc.setStyleSheet(
                f"font-family: '{self.font_body}'; font-size: 10px; color: {PALETTE['text_muted']}; background: transparent; border: none;"
            )

    def enterEvent(self, event):
        if not self._is_active:
            self.set_active(False, hovered=True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self._is_active:
            self.set_active(False, hovered=False)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.preset_id)
        super().mousePressEvent(event)
