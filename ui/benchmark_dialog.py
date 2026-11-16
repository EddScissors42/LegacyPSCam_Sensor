"""
Telemetry Benchmark & Calibration Comparator Dialog for Legacy PSCam Sensor.
"""
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QPoint, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QFrame, QGridLayout, QDialog, QFileDialog, QMessageBox
)
from PySide6.QtGui import QPainter, QPen, QColor, QPainterPath

from ui.theme import PALETTE, FONT_HEADING, FONT_BODY
from sensor.telemetry_benchmark import compare_telemetries, find_available_benchmarks


class TelemetryBenchmarkChart(QWidget):
    """
    Renders an aligned 2D comparison plot of acceleration magnitude over time (Camera vs DS4).
    Uses pure QPainter for lightweight, high-DPI rendering without external plotting dependencies.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.chart_t: List[float] = []
        self.chart_cam: List[float] = []
        self.chart_ds4: List[float] = []
        self.setMinimumHeight(180)

    def set_data(self, t: List[float], cam: List[float], ds4: List[float]):
        self.chart_t = t
        self.chart_cam = cam
        self.chart_ds4 = ds4
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        margin_left = 44
        margin_right = 20
        margin_top = 26
        margin_bottom = 26

        # Background: Crisp white canvas matching main GUI cards
        painter.fillRect(0, 0, w, h, QColor("#FFFFFF"))
        painter.setPen(QPen(QColor(PALETTE["border_subtle"]), 1))
        painter.drawRect(0, 0, w - 1, h - 1)

        plot_w = w - margin_left - margin_right
        plot_h = h - margin_top - margin_bottom

        if plot_w <= 10 or plot_h <= 10 or not self.chart_t:
            painter.setPen(QPen(QColor(PALETTE["text_muted"])))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No telemetry curves available to display.")
            return

        max_g = max(5.0, max(self.chart_cam + self.chart_ds4, default=5.0)) * 1.05
        max_t = max(self.chart_t, default=1.0)
        if max_t <= 0:
            max_t = 1.0

        # Draw grid lines for G-forces
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)

        for g_level in [1.0, 2.0, 3.5, 5.0]:
            if g_level <= max_g:
                y = int(margin_top + plot_h - (g_level / max_g) * plot_h)
                painter.setPen(QPen(QColor(PALETTE["border_subtle"]), 1, Qt.PenStyle.DashLine))
                painter.drawLine(margin_left, y, margin_left + plot_w, y)
                painter.setPen(QPen(QColor(PALETTE["text_muted"])))
                painter.drawText(6, y + 4, f"{g_level:.1f}G")

        # Time markers (start, mid, end)
        painter.setPen(QPen(QColor(PALETTE["text_muted"])))
        painter.drawText(margin_left, h - 8, "0.0s")
        painter.drawText(margin_left + plot_w // 2 - 15, h - 8, f"{max_t / 2:.1f}s")
        painter.drawText(margin_left + plot_w - 30, h - 8, f"{max_t:.1f}s")

        def pt(t_val, g_val):
            px = margin_left + (t_val / max_t) * plot_w
            py = margin_top + plot_h - (g_val / max_g) * plot_h
            return QPoint(int(px), int(py))

        # Draw DS4 curve (PlayStation Blue #00439C)
        if self.chart_ds4:
            path_ds4 = QPainterPath()
            path_ds4.moveTo(pt(self.chart_t[0], self.chart_ds4[0]))
            for t_val, g_val in zip(self.chart_t[1:], self.chart_ds4[1:]):
                path_ds4.lineTo(pt(t_val, g_val))
            painter.setPen(QPen(QColor(PALETTE["ps_blue"]), 2))
            painter.drawPath(path_ds4)

        # Draw Camera curve (Amber #EA580C)
        if self.chart_cam:
            path_cam = QPainterPath()
            path_cam.moveTo(pt(self.chart_t[0], self.chart_cam[0]))
            for t_val, g_val in zip(self.chart_t[1:], self.chart_cam[1:]):
                path_cam.lineTo(pt(t_val, g_val))
            painter.setPen(QPen(QColor("#EA580C"), 2))
            painter.drawPath(path_cam)

        # Legend at top
        painter.setPen(QPen(QColor(PALETTE["ps_blue"]), 2))
        painter.drawLine(margin_left + 10, 14, margin_left + 30, 14)
        painter.setPen(QPen(QColor(PALETTE["ps_blue"])))
        painter.drawText(margin_left + 35, 18, "DualShock 4 IMU (Physical Ground Truth)")

        painter.setPen(QPen(QColor("#EA580C"), 2))
        painter.drawLine(margin_left + 260, 14, margin_left + 280, 14)
        painter.setPen(QPen(QColor("#EA580C")))
        painter.drawText(margin_left + 285, 18, "Camera Hand Tracking (Virtual Phone)")


class TelemetryBenchmarkDialog(QDialog):
    """
    Dialog for benchmarking and comparing dance telemetry between Camera and DualShock 4.
    """

    applied_sensitivity = Signal(float)

    def __init__(self, parent=None, logs_dir: Optional[str] = None, current_sens: float = 1.0):
        super().__init__(parent)
        self.setWindowTitle("Telemetry Benchmark & Calibration Comparator")
        self.resize(780, 580)
        self.setMinimumSize(720, 520)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.current_sens = float(current_sens)
        base_dir = Path(__file__).resolve().parent.parent
        self.logs_dir = Path(logs_dir) if logs_dir else base_dir / "logs"
        self._last_result: Optional[Dict[str, Any]] = None

        # Clean Crisp-White & PlayStation Blue dialog stylesheet
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {PALETTE["bg_window"]};
                color: {PALETTE["text_main"]};
                font-family: '{FONT_BODY}', 'Segoe UI', sans-serif;
            }}
            QLabel {{
                color: {PALETTE["text_main"]};
                font-family: '{FONT_BODY}', 'Segoe UI', sans-serif;
            }}
            QComboBox {{
                background-color: {PALETTE["input_bg"]};
                color: {PALETTE["text_main"]};
                font-family: '{FONT_BODY}', sans-serif;
                border: 1px solid {PALETTE["input_border"]};
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 11px;
                min-width: 280px;
            }}
            QComboBox:hover {{
                border-color: {PALETTE["ps_blue"]};
            }}
            QComboBox QAbstractItemView {{
                background-color: #FFFFFF;
                color: {PALETTE["text_main"]};
                selection-background-color: {PALETTE["ps_blue"]};
                selection-color: #FFFFFF;
                border: 1px solid {PALETTE["border_subtle"]};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        # Header Title
        lbl_head = QLabel("TELEMETRY COMPARATIVE BENCHMARK (CAMERA vs DUALSHOCK 4)")
        lbl_head.setStyleSheet(f"""
            font-family: '{FONT_HEADING}', 'Segoe UI', sans-serif;
            font-size: 13px;
            font-weight: bold;
            color: {PALETTE['blue_dark']};
            background: transparent;
            border: none;
        """)
        layout.addWidget(lbl_head)

        lbl_sub = QLabel(
            "Select a song that was danced twice (once with the Camera and once with the DualShock 4). "
            "The comparator aligns both curves to calculate time latency, peak G-forces, and suggests optimal camera sensitivity."
        )
        lbl_sub.setWordWrap(True)
        lbl_sub.setStyleSheet(f"""
            font-family: '{FONT_BODY}', 'Segoe UI', sans-serif;
            font-size: 11px;
            color: {PALETTE['text_muted']};
            background: transparent;
            border: none;
            line-height: 1.4;
        """)
        layout.addWidget(lbl_sub)

        # Session Selector Card
        sel_card = QFrame()
        sel_card.setObjectName("sel_card")
        sel_card.setStyleSheet(f"""
            QFrame#sel_card {{
                background-color: #FFFFFF;
                border: 1px solid {PALETTE['border_subtle']};
                border-radius: 8px;
            }}
        """)
        sel_layout = QHBoxLayout(sel_card)
        sel_layout.setContentsMargins(14, 10, 14, 10)
        sel_layout.setSpacing(10)

        lbl_sess = QLabel("Available Song Runs:")
        lbl_sess.setStyleSheet(f"""
            font-family: '{FONT_HEADING}', sans-serif;
            font-weight: bold;
            font-size: 11px;
            color: {PALETTE['text_main']};
            background: transparent;
            border: none;
        """)

        self.cb_sessions = QComboBox()
        self.cb_sessions.currentIndexChanged.connect(self._on_session_selected)

        btn_style = f"""
            QPushButton {{
                background-color: #FFFFFF;
                color: {PALETTE["text_main"]};
                font-family: '{FONT_HEADING}', sans-serif;
                font-size: 11px;
                font-weight: bold;
                border: 1px solid {PALETTE["tab_gray_border"]};
                border-radius: 6px;
                padding: 6px 14px;
            }}
            QPushButton:hover {{
                border-color: {PALETTE["ps_blue"]};
                color: {PALETTE["ps_blue"]};
                background-color: {PALETTE["tab_gray_hover"]};
            }}
            QPushButton:pressed {{
                background-color: {PALETTE["tab_gray_act"]};
            }}
        """

        self.btn_refresh = QPushButton("Refresh Logs")
        self.btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh.setStyleSheet(btn_style)
        self.btn_refresh.clicked.connect(self._populate_sessions)

        self.btn_browse = QPushButton("Browse Files...")
        self.btn_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_browse.setStyleSheet(btn_style)
        self.btn_browse.clicked.connect(self._on_manual_browse)

        sel_layout.addWidget(lbl_sess)
        sel_layout.addWidget(self.cb_sessions, stretch=1)
        sel_layout.addWidget(self.btn_refresh)
        sel_layout.addWidget(self.btn_browse)
        layout.addWidget(sel_card)

        # Metrics Card Grid (4 PlayStation Style Spec Tiles)
        metrics_card = QFrame()
        metrics_card.setObjectName("metrics_card")
        metrics_card.setStyleSheet(f"""
            QFrame#metrics_card {{
                background-color: #FFFFFF;
                border: 1px solid {PALETTE['border_subtle']};
                border-radius: 8px;
            }}
        """)
        m_layout = QGridLayout(metrics_card)
        m_layout.setContentsMargins(12, 12, 12, 12)
        m_layout.setHorizontalSpacing(12)
        m_layout.setVerticalSpacing(10)

        def make_tile(title_text: str):
            tile = QFrame()
            tile.setStyleSheet(f"""
                QFrame {{
                    background-color: {PALETTE['input_bg']};
                    border: 1px solid {PALETTE['border_subtle']};
                    border-radius: 6px;
                }}
            """)
            t_layout = QVBoxLayout(tile)
            t_layout.setContentsMargins(10, 8, 10, 8)
            t_layout.setSpacing(3)
            lbl_t = QLabel(title_text)
            lbl_t.setStyleSheet(f"""
                font-family: '{FONT_BODY}', sans-serif;
                font-size: 10px;
                font-weight: bold;
                color: {PALETTE['text_muted']};
                background: transparent;
                border: none;
            """)
            lbl_v = QLabel("--")
            lbl_v.setStyleSheet(f"""
                font-family: '{FONT_HEADING}', sans-serif;
                font-size: 13px;
                font-weight: bold;
                color: {PALETTE['text_main']};
                background: transparent;
                border: none;
            """)
            t_layout.addWidget(lbl_t)
            t_layout.addWidget(lbl_v)
            return tile, lbl_v

        tile_corr, self.lbl_metric_corr = make_tile("CURVE CORRELATION")
        tile_lag, self.lbl_metric_lag = make_tile("TIME LATENCY")
        tile_peaks, self.lbl_metric_peaks = make_tile("PEAK G-FORCE (CAM / DS4)")
        tile_sens, self.lbl_metric_sens = make_tile("SUGGESTED SENSITIVITY")

        self.lbl_metric_corr.setText("--%")
        self.lbl_metric_lag.setText("-- ms")
        self.lbl_metric_peaks.setText("--G / --G")
        self.lbl_metric_sens.setText(f"--x (Current: {self.current_sens:.2f}x)")

        m_layout.addWidget(tile_corr, 0, 0)
        m_layout.addWidget(tile_lag, 0, 1)
        m_layout.addWidget(tile_peaks, 1, 0)
        m_layout.addWidget(tile_sens, 1, 1)
        layout.addWidget(metrics_card)

        # Comparison Plot
        self.chart = TelemetryBenchmarkChart()
        layout.addWidget(self.chart, stretch=1)

        # Bottom Actions Row
        bot_row = QHBoxLayout()
        bot_row.setSpacing(10)

        self.btn_apply_sens = QPushButton("Apply Suggested Sensitivity")
        self.btn_apply_sens.setEnabled(False)
        self.btn_apply_sens.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_apply_sens.setStyleSheet(f"""
            QPushButton {{
                background-color: {PALETTE['ps_blue']};
                color: #FFFFFF;
                font-family: '{FONT_HEADING}', sans-serif;
                font-size: 11px;
                font-weight: bold;
                border: none;
                border-radius: 6px;
                padding: 9px 20px;
            }}
            QPushButton:hover {{
                background-color: {PALETTE['ps_blue_hover']};
            }}
            QPushButton:pressed {{
                background-color: {PALETTE['ps_blue_active']};
            }}
            QPushButton:disabled {{
                background-color: #CBD5E1;
                color: #64748B;
            }}
        """)
        self.btn_apply_sens.clicked.connect(self._on_apply_sens_clicked)

        self.btn_close = QPushButton("Close")
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.setStyleSheet(btn_style)
        self.btn_close.clicked.connect(self.accept)

        bot_row.addWidget(self.btn_apply_sens)
        bot_row.addStretch()
        bot_row.addWidget(self.btn_close)
        layout.addLayout(bot_row)

        self._populate_sessions()

    def _populate_sessions(self):
        self.cb_sessions.clear()
        benchmarks = find_available_benchmarks(self.logs_dir)
        ready_count = 0
        for b in benchmarks:
            status = " [READY (Cam + DS4)]" if b["is_ready"] else " [Incomplete]"
            self.cb_sessions.addItem(f"{b['map_name']}{status}", b)
            if b["is_ready"]:
                ready_count += 1

        if not benchmarks:
            self.cb_sessions.addItem("No dance telemetry logs found in logs/ directory", None)
            self._clear_results()
        elif ready_count == 0:
            self.cb_sessions.addItem("No matching Camera + DS4 log pairs found", None)
            self._clear_results()

    def _on_session_selected(self, index: int):
        data = self.cb_sessions.currentData()
        if not data or not data.get("is_ready"):
            self._clear_results()
            return
        self._run_comparison(data["camera_path"], data["ds4_path"])

    def _on_manual_browse(self):
        cam_file, _ = QFileDialog.getOpenFileName(
            self, "Select Camera Telemetry CSV", str(self.logs_dir), "CSV Files (*.csv)"
        )
        if not cam_file:
            return
        ds4_file, _ = QFileDialog.getOpenFileName(
            self, "Select DualShock 4 Telemetry CSV", str(self.logs_dir), "CSV Files (*.csv)"
        )
        if not ds4_file:
            return
        self._run_comparison(cam_file, ds4_file)

    def _run_comparison(self, cam_path: str, ds4_path: str):
        try:
            res = compare_telemetries(cam_path, ds4_path, current_sensitivity=self.current_sens)
            self._last_result = res
            self.lbl_metric_corr.setText(f"{res['correlation_pct']:.1f}%")
            self.lbl_metric_corr.setStyleSheet(
                f"font-family: '{FONT_HEADING}', sans-serif; font-size: 13px; font-weight: bold; color: {PALETTE['ps_blue']}; background: transparent; border: none;"
            )
            self.lbl_metric_lag.setText(f"{res['lag_ms']:+.1f} ms")
            self.lbl_metric_lag.setStyleSheet(
                f"font-family: '{FONT_HEADING}', sans-serif; font-size: 13px; font-weight: bold; color: {PALETTE['ps_blue']}; background: transparent; border: none;"
            )
            self.lbl_metric_peaks.setText(f"{res['cam_max_g']:.2f}G / {res['ds4_max_g']:.2f}G")
            self.lbl_metric_peaks.setStyleSheet(
                f"font-family: '{FONT_HEADING}', sans-serif; font-size: 13px; font-weight: bold; color: {PALETTE['text_main']}; background: transparent; border: none;"
            )
            self.lbl_metric_sens.setText(
                f"{res['suggested_sensitivity']:.2f}x (Current: {res['current_sensitivity']:.2f}x)"
            )
            self.lbl_metric_sens.setStyleSheet(
                f"font-family: '{FONT_HEADING}', sans-serif; font-size: 13px; font-weight: bold; color: {PALETTE['status_ok']}; background: transparent; border: none;"
            )
            self.chart.set_data(res["chart_t"], res["chart_cam"], res["chart_ds4"])
            self.btn_apply_sens.setEnabled(True)
            self.btn_apply_sens.setText(f"Apply Suggested Sensitivity ({res['suggested_sensitivity']:.2f}x)")
        except Exception as e:
            QMessageBox.warning(self, "Benchmark Comparison Error", f"Failed to compare logs:\n{e}")
            self._clear_results()

    def _clear_results(self):
        self._last_result = None
        self.lbl_metric_corr.setText("--%")
        self.lbl_metric_corr.setStyleSheet(
            f"font-family: '{FONT_HEADING}', sans-serif; font-size: 13px; font-weight: bold; color: {PALETTE['text_muted']}; background: transparent; border: none;"
        )
        self.lbl_metric_lag.setText("-- ms")
        self.lbl_metric_lag.setStyleSheet(
            f"font-family: '{FONT_HEADING}', sans-serif; font-size: 13px; font-weight: bold; color: {PALETTE['text_muted']}; background: transparent; border: none;"
        )
        self.lbl_metric_peaks.setText("--G / --G")
        self.lbl_metric_peaks.setStyleSheet(
            f"font-family: '{FONT_HEADING}', sans-serif; font-size: 13px; font-weight: bold; color: {PALETTE['text_muted']}; background: transparent; border: none;"
        )
        self.lbl_metric_sens.setText(f"--x (Current: {self.current_sens:.2f}x)")
        self.lbl_metric_sens.setStyleSheet(
            f"font-family: '{FONT_HEADING}', sans-serif; font-size: 13px; font-weight: bold; color: {PALETTE['text_muted']}; background: transparent; border: none;"
        )
        self.chart.set_data([], [], [])
        self.btn_apply_sens.setEnabled(False)
        self.btn_apply_sens.setText("Apply Suggested Sensitivity")

    def _on_apply_sens_clicked(self):
        if self._last_result:
            sugg = self._last_result["suggested_sensitivity"]
            self.applied_sensitivity.emit(sugg)
            QMessageBox.information(
                self,
                "Sensitivity Applied",
                f"Camera Virtual Phone sensitivity updated to {sugg:.2f}x!",
            )
            self.accept()
