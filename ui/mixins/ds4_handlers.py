"""
DualShock 4 & Logs Handlers Mixin for Legacy PSCam Sensor Qt 6 GUI.
Encapsulates DualShock 4 rumble test, reconnect, permissive discovery, hand/sensitivity
settings, PlayStation Move Light Bar sync, and opening the diagnostic logs folder.
"""
from __future__ import annotations

import os
import sys

from PySide6 import QtCore
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import QMessageBox


class UIDS4HandlersMixin:
    """Mixin handling DualShock 4 / PlayStation Move Emulator settings and Logs actions."""

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

    # =========================================================================
    # DUALSHOCK 4 HANDLERS
    # =========================================================================
    def _test_ds4_rumble(self):
        ok = self.controller.devices.trigger_test_rumble()
        if not ok:
            QMessageBox.information(
                self,
                "DualShock 4",
                "DualShock 4 is not connected. Please connect it via USB or pair via Windows Bluetooth settings.",
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

    def _on_ds4_sync_lightbar_changed(self, state: int):
        val = (state == Qt.CheckState.Checked.value or state == 2)
        self.controller.devices.set_ds4_sync_lightbar(val)


__all__ = ["UIDS4HandlersMixin"]
