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
        # Camera modes show full Experimental features (Warning, Auto-Frame, Virtual Phone);
        # DualShock 4 mode keeps Experimental tab clean/empty (Scoring Bridge lives in Controller Settings).
        if hasattr(self, "exp_warn_box"):
            self.exp_warn_box.setVisible(not is_ds4)
        if hasattr(self, "auto_frame_box"):
            self.auto_frame_box.setVisible(not is_ds4)
        if hasattr(self, "vphone_box"):
            self.vphone_box.setVisible(not is_ds4)
        if hasattr(self, "lbl_exp_empty"):
            self.lbl_exp_empty.setVisible(is_ds4)

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

            if hasattr(self, "vphone_details_frame"):
                self.vphone_details_frame.setVisible(saved_state)
            # Sync controller state when leaving DS4 so DS4 doesn't leave vphone stuck enabled in camera modes
            if getattr(self.controller.devices, "_vphone", None) is not None:
                self.controller.devices.set_vphone_enabled(saved_state)

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

    @Slot(str, int, str)
    def _on_vphone_discover_finished(self, ip: str, port: int, code: str):
        if getattr(self, "_is_closing", False):
            return
        for btn_attr in ("btn_vphone_discover", "btn_ds4_sb_discover"):
            btn = getattr(self, btn_attr, None)
            if btn is not None:
                btn.setEnabled(True)
                btn.setText("Auto-Find")

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
            dis_style = (
                f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['text_muted']}; background: transparent; border: none;"
            )
            self._set_text_if_changed(self.lbl_vphone_status, "Status: Disabled (Virtual Phone)")
            self._set_style_if_changed(self.lbl_vphone_status, dis_style)
            if hasattr(self, "lbl_ds4_sb_status"):
                self._set_text_if_changed(self.lbl_ds4_sb_status, "Status: Disconnected")
                self._set_style_if_changed(self.lbl_ds4_sb_status, dis_style)
            return

        status = st.get("status_text", "")
        if st.get("connected"):
            color = PALETTE["status_ok"]
        elif st.get("enabled"):
            color = PALETTE["status_warn"]
        else:
            color = PALETTE["text_muted"]
        st_style = (
            f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {color}; background: transparent; border: none;"
        )
        self._set_text_if_changed(self.lbl_vphone_status, f"Status: {status}")
        self._set_style_if_changed(self.lbl_vphone_status, st_style)
        if hasattr(self, "lbl_ds4_sb_status"):
            self._set_text_if_changed(self.lbl_ds4_sb_status, f"Status: {status}")
            self._set_style_if_changed(self.lbl_ds4_sb_status, st_style)

        lbl_song = getattr(self, "lbl_benchmark_song", getattr(self, "lbl_vphone_song", None))
        if lbl_song is not None and lbl_song.isVisible():
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
                self._set_text_if_changed(lbl_song, f"Active Song: {song_name}{status_tag}")
                self._set_style_if_changed(
                    lbl_song,
                    f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {color}; background: transparent; border: none;",
                )
            else:
                if is_watching:
                    msg = "Active Song: None (Watching for Just Dance song start...)"
                else:
                    msg = "Active Song: None (Awaiting Just Dance Selection)"
                self._set_text_if_changed(lbl_song, msg)
                self._set_style_if_changed(
                    lbl_song,
                    f"font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold; color: {PALETTE['text_muted']}; background: transparent; border: none;",
                )

        if hasattr(self, "btn_vphone_log") and self.btn_vphone_log.isVisible():
            if st.get("is_logging"):
                self._set_text_if_changed(self.btn_vphone_log, "Stop Log (REC)")
                self._set_style_if_changed(
                    self.btn_vphone_log,
                    f"""
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
                """,
                )
            else:
                self._set_text_if_changed(self.btn_vphone_log, "Record Log")
                self._set_style_if_changed(self.btn_vphone_log, getattr(self, "_btn_vphone_outline_style", ""))

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
                # Use DeviceController.is_connecting_ds4 as single source of truth (prevents reconnect deadlock)
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
