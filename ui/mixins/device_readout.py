"""
Device Readout & Live Status Presentation Mixin for Legacy PSCam Sensor Qt 6 GUI.
Encapsulates real-time UI presentation updates for Phone Camera, DualShock 4,
PlayStation Move Emulator, and Experimental mode views, decoupled from `ui/gui_qt.py`.
"""
from __future__ import annotations

from PySide6 import QtCore
from PySide6.QtCore import Qt

from ui.theme import PALETTE


class UIDeviceReadoutMixin:
    """Mixin providing live status readout updates for connected input devices."""

    def _update_exp_view_for_mode(self, mode: str):
        """Adapts the Experimental tab layout according to the active controller mode."""
        is_ds4 = (mode == "ds4")
        if hasattr(self, "exp_warn_box"):
            self.exp_warn_box.setVisible(not is_ds4)
        if hasattr(self, "auto_frame_box"):
            self.auto_frame_box.setVisible(not is_ds4)
        if hasattr(self, "lbl_exp_empty"):
            self.lbl_exp_empty.setVisible(is_ds4)

    def _update_phone_cam_status(self):
        st = self.controller.devices.get_phone_cam_status()
        is_conn = st.get("is_connected", False)
        prev_conn = getattr(self, "_last_phone_cam_conn", None)

        if is_conn:
            info_txt = st.get("info_text")
            if not info_txt:
                lens_lbl = "Rear Camera" if st.get("client_lens") == "environment" else "Front Camera"
                if st.get("streaming_active"):
                    fps_disp = st.get("fps", 0.0) if st.get("fps", 0.0) > 0.5 else float(st.get("target_fps", 30))
                    stream_lbl = f"{st.get('width', 640)}x{st.get('height', 480)} @ {fps_disp:.0f} FPS"
                else:
                    stream_lbl = "Standby (Cool Mode)"
                info_txt = (
                    f"{st.get('device_name', 'Smartphone')} connected ({st.get('client_ip', '127.0.0.1')} • "
                    f"{stream_lbl} • {lens_lbl})"
                )
            if hasattr(self, "lbl_phone_cam_ready_info"):
                self.lbl_phone_cam_ready_info.setText(info_txt)

        if prev_conn != is_conn:
            self._last_phone_cam_conn = is_conn
            if not is_conn and self.is_tracking_active and self.cfg.get("camera_mode") == "phone_cam":
                self.controller.session.stop_tracking()
            self._update_video_view_visibility()
        self._update_start_button_state()

    @staticmethod
    def _set_style_if_changed(widget, css: str) -> None:
        if widget is None:
            return
        if widget.property("_cached_qss") != css:
            widget.setProperty("_cached_qss", css)
            widget.setStyleSheet(css)

    @staticmethod
    def _set_text_if_changed(widget, text: str) -> None:
        if widget is None:
            return
        if widget.text() != text:
            widget.setText(text)

    def _update_device_readout(self):
        """Real-time (150 ms) readout updater for DualShock 4, PS Move Emulator, and Phone Camera."""
        mode = self.cfg.get("camera_mode", "pscam")
        if mode == "ds4":
            self._update_ds4_ui_readout()
            self._update_psmove_ui_readout()
        elif mode == "phone_cam":
            self._update_phone_cam_status()

    def _update_psmove_ui_readout(self):
        if not hasattr(self, "lbl_ds4_pm_status"):
            return
        try:
            pm = self.controller.devices.get_psmove_readout()
        except Exception:
            return

        status_text = pm.get("status_text", "Ready")
        if pm.get("game_connected"):
            color = PALETTE["status_ok"]
        elif pm.get("streaming") or pm.get("psmove_hooked"):
            color = PALETTE["ps_blue"]
        else:
            color = PALETTE["text_muted"]

        st_style = (
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {color}; background: transparent; border: none;"
        )
        self._set_text_if_changed(self.lbl_ds4_pm_status, f"Status: {status_text}")
        self._set_style_if_changed(self.lbl_ds4_pm_status, st_style)

        if hasattr(self, "lbl_psmove_swatch"):
            r, g, b = pm.get("sphere_rgb", (0, 67, 156))
            swatch_css = f"background-color: rgb({r}, {g}, {b}); border: 1px solid #CBD5E1; border-radius: 6px;"
            self._set_style_if_changed(self.lbl_psmove_swatch, swatch_css)

    def _update_ds4_ui_readout(self):
        if not hasattr(self, "lbl_ds4_status") or not hasattr(self, "lbl_ds4_accel"):
            return
        if self.cfg.get("camera_mode") != "ds4" and self.controller.devices._ds4 is None:
            return
        try:
            st = self.controller.devices.get_ds4_readout()
        except Exception:
            return
        if st.get("is_connected"):
            if hasattr(self, "ds4_disconnected_box"):
                self.ds4_disconnected_box.setVisible(False)
            if hasattr(self, "ds4_info_frame"):
                self.ds4_info_frame.setVisible(True)

            ctrl_name = st.get("controller_name", "DualShock 4")
            conn_type = st.get("connection_type", "Connected")
            charging_str = st.get("charging_str", "")
            rate = st.get("sample_rate_hz", 0.0)
            batt = st.get("battery_pct", 0)

            if st.get("imu_frozen", False):
                self._set_text_if_changed(
                    self.lbl_ds4_status,
                    f"Status: {ctrl_name} ({conn_type}) — [!] IMU SENSOR FROZEN (0G): Connect via USB cable!",
                )
                self._set_style_if_changed(
                    self.lbl_ds4_status,
                    f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['status_err']}; background: transparent; border: none;",
                )
            else:
                self._set_text_if_changed(
                    self.lbl_ds4_status,
                    f"Status: {ctrl_name} ({conn_type} • {rate:.0f} Hz • Battery: {batt}%{charging_str})",
                )
                self._set_style_if_changed(
                    self.lbl_ds4_status,
                    f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['ps_blue']}; background: transparent; border: none;",
                )

            if self.lbl_ds4_accel.isVisible():
                ax, ay, az = st.get("accel_g", (0.0, 0.0, 0.0))
                tot = st.get("total_g", 0.0)
                act_btns = st.get("buttons", [])
                btn_str = f"  |  Buttons: {', '.join(act_btns)}" if act_btns else ""

                if st.get("imu_frozen", False):
                    self._set_text_if_changed(
                        self.lbl_ds4_accel,
                        f"3D Accelerometer: 0.00G (IMU Inactive/Zeroed over BT)  |  Buttons: {', '.join(act_btns) if act_btns else 'None'}",
                    )
                    self._set_style_if_changed(
                        self.lbl_ds4_accel,
                        f"font-family: '{self.font_body}'; font-size: 11px; font-weight: 600; color: {PALETTE['status_err']}; background: transparent; border: none;",
                    )
                else:
                    self._set_text_if_changed(
                        self.lbl_ds4_accel,
                        f"3D Accelerometer: X: {ax:+.2f}G  |  Y: {ay:+.2f}G  |  Z: {az:+.2f}G  |  |G|: {tot:.2f}G{btn_str}",
                    )
                    self._set_style_if_changed(
                        self.lbl_ds4_accel,
                        f"font-family: '{self.font_body}'; font-size: 11px; font-weight: 600; color: {PALETTE['text_main']}; background: transparent; border: none;",
                    )
        else:
            if hasattr(self, "ds4_disconnected_box"):
                self.ds4_disconnected_box.setVisible(True)
            if hasattr(self, "ds4_info_frame"):
                self.ds4_info_frame.setVisible(False)
            if st.get("device_present"):
                det_name = st.get("controller_name", "DualShock 4")
                det_str = st.get("connection_type", "")
                if hasattr(self, "lbl_ds4_conn_title"):
                    self._set_text_if_changed(self.lbl_ds4_conn_title, f"{det_name} detected {det_str}")
                if hasattr(self, "lbl_ds4_conn_info"):
                    self._set_text_if_changed(self.lbl_ds4_conn_info, f"Connecting to {det_name} {det_str}...")
                self._set_text_if_changed(self.lbl_ds4_status, f"Status: {det_name} detected {det_str} (Connecting...)")
                self._set_style_if_changed(
                    self.lbl_ds4_status,
                    f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['status_warn']}; background: transparent; border: none;",
                )
                if not self.controller.devices.is_connecting_ds4 and not getattr(self, "is_tracking_active", False):
                    def _done(_ok):
                        if getattr(self, "_is_closing", False):
                            return
                        try:
                            QtCore.QMetaObject.invokeMethod(self, "_finish_ds4_reconnect", Qt.ConnectionType.QueuedConnection)
                        except (RuntimeError, Exception):
                            pass
                    self.controller.devices.connect_ds4_async(callback=_done)
            else:
                if hasattr(self, "lbl_ds4_conn_title"):
                    self._set_text_if_changed(self.lbl_ds4_conn_title, "DualShock® 4 not connected")
                if hasattr(self, "lbl_ds4_conn_info"):
                    self._set_text_if_changed(self.lbl_ds4_conn_info, "Connect via USB cable or pair via Windows Bluetooth Settings.")
                self._set_text_if_changed(
                    self.lbl_ds4_status,
                    "Status: Controller Disconnected (Connect via USB cable or pair via Bluetooth.)",
                )
                self._set_style_if_changed(
                    self.lbl_ds4_status,
                    f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['text_muted']}; background: transparent; border: none;",
                )
            if self.lbl_ds4_accel.isVisible():
                self._set_text_if_changed(self.lbl_ds4_accel, "3D Accelerometer: Disconnected")
                self._set_style_if_changed(
                    self.lbl_ds4_accel,
                    f"font-family: '{self.font_body}'; font-size: 11px; font-weight: 500; color: {PALETTE['text_muted']}; background: transparent; border: none;",
                )
        self._update_start_button_state()


__all__ = ["UIDeviceReadoutMixin"]
