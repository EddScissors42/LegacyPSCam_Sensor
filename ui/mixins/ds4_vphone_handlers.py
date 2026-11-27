"""
DualShock 4, Virtual Phone (Scoring Bridge) & Benchmark Handlers Mixin for Legacy PSCam Sensor Qt 6 GUI.
Encapsulates controller rumble/reconnect/settings, Virtual Phone pairing/FTUE/sensitivity,
telemetry benchmark dialog, and opening the diagnostic logs folder.
"""
from __future__ import annotations

import os
import sys

from PySide6 import QtCore
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import QMessageBox

from ui.benchmark_dialog import TelemetryBenchmarkDialog


class UIDS4VPhoneHandlersMixin:
    """Mixin handling DualShock 4, Virtual Phone / Scoring Bridge, Benchmark, and Logs actions."""

    # =========================================================================
    # VIRTUAL PHONE CONTROLLER (SCORING BRIDGE) HANDLERS
    # =========================================================================
    def _on_vphone_toggle_changed(self):
        if self.cfg.get("camera_mode") == "ds4":
            return
        enabled = self.chk_vphone_enabled.isChecked()
        self.cfg["virtual_phone_enabled"] = enabled
        if hasattr(self, "vphone_details_frame"):
            self.vphone_details_frame.setVisible(enabled)
        self._apply_vphone_settings_to_controller()
        self.controller.devices.set_vphone_enabled(enabled)
        self._save_settings()
        self._update_vphone_ui_readout()

    def _on_vphone_sens_changed(self, val: int):
        sens = round(val / 100.0, 2)
        self.controller.devices.set_vphone_sensitivity(sens)
        self._save_settings()

    def _on_vphone_config_changed(self):
        self._apply_vphone_settings_to_controller()
        self._save_settings()

    def _apply_vphone_settings_to_controller(self):
        host = self.txt_vphone_host.text().strip() or "127.0.0.1"
        try:
            port = int(self.txt_vphone_port.text().strip())
        except ValueError:
            port = 8080
            self.txt_vphone_port.setText("8080")
        hand = "left" if self.cb_vphone_hand.currentIndex() == 1 else "right"
        sens = float(self.cfg.get("virtual_phone_sensitivity", 1.0))
        self.controller.devices.configure_vphone(host=host, port=port, hand=hand, sens=sens)

    def _on_vphone_reconnect_clicked(self):
        self._apply_vphone_settings_to_controller()
        self._save_settings()
        self.controller.devices.set_vphone_enabled(True)
        if hasattr(self, "chk_vphone_enabled"):
            self.chk_vphone_enabled.setChecked(True)
        self.controller.devices.request_vphone_reconnect()
        self._update_vphone_ui_readout()

    def _on_vphone_discover_clicked(self):
        for btn_attr in ("btn_vphone_discover", "btn_ds4_sb_discover"):
            btn = getattr(self, btn_attr, None)
            if btn is not None:
                btn.setEnabled(False)
                btn.setText("Searching...")

        def _done(ip, port, code):
            if getattr(self, "_is_closing", False):
                return
            try:
                QtCore.QMetaObject.invokeMethod(
                    self,
                    "_on_vphone_discover_finished",
                    Qt.ConnectionType.QueuedConnection,
                    QtCore.Q_ARG(str, ip),
                    QtCore.Q_ARG(int, port),
                    QtCore.Q_ARG(str, code),
                )
            except (RuntimeError, Exception):
                pass

        self.controller.devices.discover_vphone_server_async(callback=_done)

    def _on_skip_finish_clicked(self):
        """Sends the FTUE_FINISH shortcut packet for Just Dance 2022 phone tutorial."""
        if not self.vphone.enabled:
            self.controller.devices.set_vphone_enabled(True)
            if hasattr(self, "chk_vphone_enabled"):
                self.chk_vphone_enabled.setChecked(True)
        self.controller.devices.send_vphone_skip_finish()

    def _on_benchmark_toggle_changed(self, state):
        enabled = (state == Qt.CheckState.Checked.value or state == 2)
        if hasattr(self, "benchmark_details_frame"):
            self.benchmark_details_frame.setVisible(enabled)
        self.controller.devices.set_vphone_auto_record(enabled)
        self._update_vphone_ui_readout()

    def _on_benchmark_adaptive_changed(self, state):
        enabled = (state == Qt.CheckState.Checked.value or state == 2)
        self.controller.devices.set_vphone_adaptive(enabled)

    def _open_logs_folder(self):
        from sensor.config_manager import get_logs_dir
        logs_dir = get_logs_dir()
        try:
            from sensor.session_logger import get_session_logger
            get_session_logger().log_event("INFO", "GUI", f"User opened logs directory: {logs_dir}")
        except Exception:
            pass
        if sys.platform == "win32":
            os.startfile(str(logs_dir))
        else:
            import subprocess
            subprocess.Popen(["xdg-open", str(logs_dir)])

    def _on_vphone_auto_record_changed(self, state):
        self._on_benchmark_toggle_changed(state)

    def _on_vphone_adaptive_changed(self, state):
        self._on_benchmark_adaptive_changed(state)

    def _open_telemetry_benchmark_dialog(self):
        diag = TelemetryBenchmarkDialog(
            parent=self,
            current_sens=self.vphone.accelerometer.sensitivity,
        )
        diag.applied_sensitivity.connect(self._on_benchmark_sensitivity_applied)
        diag.exec()

    def _on_benchmark_sensitivity_applied(self, new_sens: float):
        sens_val = round(float(new_sens), 2)
        self.controller.devices.set_vphone_sensitivity(sens_val)

    # =========================================================================
    # DUALSHOCK 4 HANDLERS
    # =========================================================================
    def _test_ds4_rumble(self):
        ok = self.controller.devices.trigger_test_rumble()
        if not ok:
            QMessageBox.information(
                self,
                "DualShock 4",
                "DualShock 4 is not connected. Please connect it via USB or pair via Windows Bluetooth settings."
            )

    def _reconnect_ds4(self):
        if hasattr(self, "lbl_ds4_conn_info"):
            self.lbl_ds4_conn_info.setText("Connecting to controller (USB / Bluetooth HID)...")
        def _done(_ok):
            try:
                QtCore.QMetaObject.invokeMethod(self, "_finish_ds4_reconnect", Qt.ConnectionType.QueuedConnection)
            except (RuntimeError, Exception):
                pass
        self.controller.devices.connect_ds4_async(callback=_done)

    @Slot()
    def _finish_ds4_reconnect(self):
        self._update_ds4_ui_readout()

    def _on_ds4_permissive_changed(self, state: int):
        val = (state == Qt.CheckState.Checked.value or state == 2)
        self.controller.devices.set_ds4_permissive(val)
        self._update_ds4_ui_readout()

    def _on_ds4_hand_changed(self, idx: int):
        hand = "right" if idx == 0 else "left"
        self.controller.devices.set_ds4_hand(hand)

    def _on_ds4_sens_changed(self, idx: int):
        sens_map = {0: 1.0, 1: 1.25, 2: 0.85}
        sens = sens_map.get(idx, 1.0)
        self.controller.devices.set_ds4_sensitivity(sens)


__all__ = ["UIDS4VPhoneHandlersMixin"]
