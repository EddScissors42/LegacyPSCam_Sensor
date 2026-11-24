"""
Device Readout & Live Status Presentation Mixin for Legacy PSCam Sensor Qt 6 GUI.
Encapsulates real-time UI presentation updates for Phone Camera, Virtual Phone,
DualShock 4, and Experimental mode views, decoupled from `ui/gui_qt.py`.
"""
from __future__ import annotations

import os
from PySide6 import QtCore
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import QMessageBox

from ui.theme import PALETTE


class UIDeviceReadoutMixin:
    """Mixin providing live status readout updates for connected input devices."""

    def _update_exp_view_for_mode(self, mode: str):
        """Adapts the Experimental tab layout and Virtual Phone toggle according to the active controller mode."""
        if not hasattr(self, "chk_vphone_enabled"):
            return

        is_ds4 = (mode == "ds4")
        if hasattr(self, "auto_frame_box"):
            self.auto_frame_box.setVisible(not is_ds4)

        if is_ds4:
            if hasattr(self, "cb_ds4_hand") and hasattr(self, "cb_vphone_hand"):
                self.cb_vphone_hand.blockSignals(True)
                self.cb_vphone_hand.setCurrentIndex(self.cb_ds4_hand.currentIndex())
                self.cb_vphone_hand.blockSignals(False)

            self.chk_vphone_enabled.blockSignals(True)
            self.chk_vphone_enabled.setChecked(True)
            self.chk_vphone_enabled.setEnabled(False)
            self.chk_vphone_enabled.setText("Virtual Phone Controller (DualShock® 4 Scoring Bridge)")
            self.chk_vphone_enabled.setStyleSheet(f"""
                QCheckBox {{
                    font-family: '{self.font_heading}';
                    font-size: 13px;
                    font-weight: bold;
                    color: #94A3B8;
                    background: transparent;
                }}
                QCheckBox::indicator {{
                    width: 18px;
                    height: 18px;
                    border-radius: 4px;
                    border: 1px solid #CBD5E1;
                    background-color: #E2E8F0;
                }}
                QCheckBox::indicator:checked {{
                    background-color: #94A3B8;
                    border-color: #94A3B8;
                }}
            """)
            self.chk_vphone_enabled.blockSignals(False)

            if hasattr(self, "lbl_vp_desc"):
                self.lbl_vp_desc.setText(
                    "Streams physical 3D accelerometer commands from your DualShock 4 directly to Just Dance via the /smartphone WebSocket protocol for seamless dance scoring."
                )
            if hasattr(self, "vphone_details_frame"):
                self.vphone_details_frame.setVisible(True)
        else:
            self.chk_vphone_enabled.blockSignals(True)
            self.chk_vphone_enabled.setEnabled(True)
            self.chk_vphone_enabled.setText("Virtual Phone Controller (JD Controller via Camera)")
            self.chk_vphone_enabled.setStyleSheet(f"""
                QCheckBox {{
                    font-family: '{self.font_heading}';
                    font-size: 13px;
                    font-weight: bold;
                    color: {PALETTE['text_main']};
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
            """)
            saved_state = bool(self.cfg.get("virtual_phone_enabled", False))
            self.chk_vphone_enabled.setChecked(saved_state)
            self.chk_vphone_enabled.blockSignals(False)

            if hasattr(self, "lbl_vp_desc"):
                self.lbl_vp_desc.setText(
                    "Emulates a smartphone connected to Just Dance via WebSocket/TLS (/smartphone) and converts your hand motion in the camera into 3D accelerometer commands for songs that only support hand controllers."
                )
            if hasattr(self, "vphone_details_frame"):
                self.vphone_details_frame.setVisible(saved_state)

    def _update_phone_cam_status(self):
        st = self.controller.devices.get_phone_cam_status()
        is_conn = st.get("is_connected", False)
        prev_conn = getattr(self, "_last_phone_cam_conn", None)

        if is_conn:
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

    @Slot(str, int, str)
    def _on_vphone_discover_finished(self, ip: str, port: int, code: str):
        if hasattr(self, "btn_vphone_discover"):
            self.btn_vphone_discover.setEnabled(True)
            self.btn_vphone_discover.setText("Auto-Find")

        if ip:
            self.txt_vphone_host.setText(ip)
            if port > 0:
                self.txt_vphone_port.setText(str(port))
            self._apply_vphone_settings_to_controller()
            self._save_settings()
            if self.vphone.enabled:
                self.controller.devices.request_vphone_reconnect()
            info_code = f" (Pairing Code: {code})" if code else ""
            QMessageBox.information(
                self,
                "Just Dance Server Found",
                f"Game detected at {ip}:{port}{info_code}!",
            )
        else:
            QMessageBox.information(
                self,
                "UDP Auto-Discovery",
                "No UDP response on port 6000/7000.\n"
                "If the game is running on the same PC, port 8080 works directly.",
            )

    def _toggle_vphone_logging(self):
        mode = self.cfg.get("camera_mode", "pscam")
        src = "ds4" if mode == "ds4" else "camera"
        is_logging, path = self.controller.devices.toggle_vphone_logging(source=src)
        if is_logging:
            self.btn_vphone_log.setText("Stop Log")
            self.btn_vphone_log.setStyleSheet(f"""
                QPushButton {{
                    background-color: {PALETTE["blue_pastel"]};
                    color: {PALETTE["blue_dark"]};
                    font-family: '{self.font_heading}', sans-serif;
                    font-size: 11px;
                    font-weight: bold;
                    border: 1px solid {PALETTE["ps_blue"]};
                    border-radius: 6px;
                    padding: 6px 14px;
                }}
            """)
        else:
            self.btn_vphone_log.setText("Record Log")
            self.btn_vphone_log.setStyleSheet(getattr(self, "_btn_vphone_outline_style", ""))
            if path and os.path.exists(path):
                QMessageBox.information(
                    self,
                    "Telemetry Recording Finished",
                    f"Accelerometer CSV log saved successfully to:\n{path}\n\n"
                    "File ready for analysis and comparison with real smartphone data."
                )

    def _update_vphone_ui_readout(self):
        # Always update DualShock 4 and Phone Camera in real-time (150ms) regardless of Virtual Phone session
        if self.cfg.get("camera_mode") == "ds4":
            self._update_ds4_ui_readout()
        elif self.cfg.get("camera_mode") == "phone_cam":
            self._update_phone_cam_status()

        if not hasattr(self, "lbl_vphone_status") or not hasattr(self, "lbl_vphone_accel"):
            return
        st = self.controller.devices.get_vphone_readout()
        if not st.get("initialized"):
            self.lbl_vphone_status.setText("Status: Disabled (Virtual Phone)")
            self.lbl_vphone_status.setStyleSheet(
                f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['text_muted']}; background: transparent; border: none;"
            )
            return

        status = st.get("status_text", "")
        self.lbl_vphone_status.setText(f"Status: {status}")
        if st.get("connected"):
            color = PALETTE["status_ok"]
        elif st.get("enabled"):
            color = PALETTE["status_warn"]
        else:
            color = PALETTE["text_muted"]
        self.lbl_vphone_status.setStyleSheet(
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {color}; background: transparent; border: none;"
        )

        lbl_song = getattr(self, "lbl_benchmark_song", getattr(self, "lbl_vphone_song", None))
        if lbl_song is not None:
            is_watching = getattr(self, "chk_benchmark_enabled", None) and self.chk_benchmark_enabled.isChecked()
            if is_watching and not self.vphone.enabled:
                self.controller.devices.set_vphone_enabled(True)
            song_name = st.get("song_name", "")
            if song_name:
                if st.get("is_dancing"):
                    status_tag = " [Scoring Active - Capturing Telemetry]" if is_watching else " [Scoring Active]"
                    color = PALETTE["ps_blue"]
                else:
                    status_tag = " [Lobby / Paused - Ready]" if is_watching else " [Lobby / Paused]"
                    color = PALETTE["blue_dark"]
                lbl_song.setText(f"Active Song: {song_name}{status_tag}")
                lbl_song.setStyleSheet(
                    f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {color}; background: transparent; border: none;"
                )
            else:
                if is_watching:
                    msg = "Active Song: None (Watching for Just Dance song start...)"
                else:
                    msg = "Active Song: None (Awaiting Just Dance Selection)"
                lbl_song.setText(msg)
                lbl_song.setStyleSheet(
                    f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['text_muted']}; background: transparent; border: none;"
                )

        if hasattr(self, "btn_vphone_log"):
            if st.get("is_logging"):
                self.btn_vphone_log.setText("Stop Log (REC)")
                self.btn_vphone_log.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {PALETTE["blue_pastel"]};
                        color: {PALETTE["blue_dark"]};
                        font-family: '{self.font_heading}', sans-serif;
                        font-size: 11px;
                        font-weight: bold;
                        border: 1px solid {PALETTE["ps_blue"]};
                        border-radius: 6px;
                        padding: 6px 14px;
                    }}
                """)
            else:
                self.btn_vphone_log.setText("Record Log")
                self.btn_vphone_log.setStyleSheet(getattr(self, "_btn_vphone_outline_style", ""))

        should_show_accel = getattr(self, "is_tracking_active", False)
        if self.lbl_vphone_accel.isVisible() != should_show_accel:
            self.lbl_vphone_accel.setVisible(should_show_accel)
        if should_show_accel:
            ax, ay, az = self.vphone.latest_accel
            spd = getattr(self.vphone.accelerometer, "latest_speed", 0.0)
            self.lbl_vphone_accel.setText(
                f"3D Accelerometer: X: {ax:+.2f}G | Y: {ay:+.2f}G | Z: {az:+.2f}G ({spd:.1f} m/s)"
            )

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
                self.lbl_ds4_status.setText(
                    f"Status: {ctrl_name} ({conn_type}) — [!] IMU SENSOR FROZEN (0G): Connect via USB cable!"
                )
                self.lbl_ds4_status.setStyleSheet(
                    f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['status_err']}; background: transparent; border: none;"
                )
            else:
                self.lbl_ds4_status.setText(
                    f"Status: {ctrl_name} ({conn_type} • {rate:.0f} Hz • Battery: {batt}%{charging_str})"
                )
                self.lbl_ds4_status.setStyleSheet(
                    f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['ps_blue']}; background: transparent; border: none;"
                )

            ax, ay, az = st.get("accel_g", (0.0, 0.0, 0.0))
            tot = st.get("total_g", 0.0)
            act_btns = st.get("buttons", [])
            btn_str = f"  |  Buttons: {', '.join(act_btns)}" if act_btns else ""

            if st.get("imu_frozen", False):
                self.lbl_ds4_accel.setText(
                    f"3D Accelerometer: 0.00G (IMU Inactive/Zeroed over BT)  |  Buttons: {', '.join(act_btns) if act_btns else 'None'}"
                )
                self.lbl_ds4_accel.setStyleSheet(
                    f"font-family: '{self.font_body}'; font-size: 11px; font-weight: 600; color: {PALETTE['status_err']}; background: transparent; border: none;"
                )
            else:
                self.lbl_ds4_accel.setText(
                    f"3D Accelerometer: X: {ax:+.2f}G  |  Y: {ay:+.2f}G  |  Z: {az:+.2f}G  |  |G|: {tot:.2f}G{btn_str}"
                )
                self.lbl_ds4_accel.setStyleSheet(
                    f"font-family: '{self.font_body}'; font-size: 11px; font-weight: 600; color: {PALETTE['text_main']}; background: transparent; border: none;"
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
                    self.lbl_ds4_conn_title.setText(f"{det_name} detected {det_str}")
                if hasattr(self, "lbl_ds4_conn_info"):
                    self.lbl_ds4_conn_info.setText(f"Connecting to {det_name} {det_str}...")
                self.lbl_ds4_status.setText(f"Status: {det_name} detected {det_str} (Connecting...)")
                self.lbl_ds4_status.setStyleSheet(
                    f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['status_warn']}; background: transparent; border: none;"
                )
                if not getattr(self, "_is_connecting_ds4", False) and not getattr(self, "is_tracking_active", False):
                    self._is_connecting_ds4 = True
                    def _done(_ok):
                        self._is_connecting_ds4 = False
                        try:
                            QtCore.QMetaObject.invokeMethod(self, "_finish_ds4_reconnect", Qt.ConnectionType.QueuedConnection)
                        except (RuntimeError, Exception):
                            pass
                    self.controller.devices.connect_ds4_async(callback=_done)
            else:
                if hasattr(self, "lbl_ds4_conn_title"):
                    self.lbl_ds4_conn_title.setText("DualShock® 4 not connected")
                if hasattr(self, "lbl_ds4_conn_info"):
                    self.lbl_ds4_conn_info.setText("Connect via USB cable or pair via Windows Bluetooth Settings.")
                self.lbl_ds4_status.setText("Status: Controller Disconnected (Connect via USB cable or pair via Bluetooth.)")
                self.lbl_ds4_status.setStyleSheet(
                    f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['text_muted']}; background: transparent; border: none;"
                )
            self.lbl_ds4_accel.setText("3D Accelerometer: Disconnected")
            self.lbl_ds4_accel.setStyleSheet(
                f"font-family: '{self.font_body}'; font-size: 11px; font-weight: 500; color: {PALETTE['text_muted']}; background: transparent; border: none;"
            )
        self._update_start_button_state()


__all__ = ["UIDeviceReadoutMixin"]
