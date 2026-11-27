"""
Camera, Mode & Tab Navigation Handlers Mixin for Legacy PSCam Sensor Qt 6 GUI.
Encapsulates device/tab availability, PlayStation 4 Camera state transitions,
Webcam discovery/presets, camera orientation, and display option events.
"""
from __future__ import annotations

from typing import Optional

from PySide6 import QtCore
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMessageBox

from sensor.camera_manager import CameraManager
from sensor.config_manager import (
    parse_preset,
    PRESETS_PSCAM,
    PRESETS_WEBCAM,
    PRESETS_PHONE_CAM,
)
from ui.theme import PALETTE


class UICameraHandlersMixin:
    """Mixin handling mode switching, tab gating, PS4 Camera state, and Webcam controls."""

    def is_camera_accessible(self) -> bool:
        """Returns True if the currently selected camera device is connected and accessible."""
        return self.controller.camera.is_camera_accessible(self.cfg.get("camera_mode", "pscam"))

    def is_device_ready_for_tracking(self, mode: Optional[str] = None) -> bool:
        """Returns True if the peripheral/camera corresponding to the active mode is connected and ready."""
        m = mode or self.cfg.get("camera_mode", "pscam")
        if m == "ds4":
            try:
                st = self.controller.devices.get_ds4_readout()
                return bool(st.get("is_connected", False))
            except Exception:
                return False
        elif m == "pscam":
            return (getattr(self, "_current_pscam_state", "DISCONNECTED") == "READY")
        elif m == "phone_cam":
            try:
                st = self.controller.devices.get_phone_cam_status()
                return bool(st.get("is_connected", False))
            except Exception:
                return False
        else:  # webcam
            cams = getattr(self, "camera_list", [])
            webcams = [c for c in cams if not c.is_pscam]
            if not webcams and not any(c.is_pscam for c in cams):
                webcams = cams
            return len(webcams) > 0

    def _update_start_button_state(self):
        """
        Dynamically updates the enabled state, text, cursor and tooltip of the primary CTA
        button (btn_start) based on whether tracking is currently active and whether the
        hardware/stream required for the active mode is fully connected and ready.
        """
        if not hasattr(self, "btn_start"):
            return

        if getattr(self, "is_tracking_active", False):
            self.btn_start.setText("TRACKING IN PROGRESS...")
            self.btn_start.setEnabled(False)
            self.btn_start.setCursor(Qt.CursorShape.ForbiddenCursor)
            self.btn_start.setToolTip("Dance tracking is currently active.")
            return

        mode = self.cfg.get("camera_mode", "pscam")
        ready = self.is_device_ready_for_tracking(mode)

        if mode == "ds4":
            if hasattr(self, "btn_bottom_disconnect_phone"):
                self.btn_bottom_disconnect_phone.setVisible(False)
            self.btn_start.setText("START CONTROLLER (DS4)")
            self.btn_start.setEnabled(ready)
            self.btn_start.setVisible(ready)
            if ready:
                self.btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
                self.btn_start.setToolTip("Start motion tracking with DualShock 4 controller")
            else:
                self.btn_start.setCursor(Qt.CursorShape.ForbiddenCursor)
                self.btn_start.setToolTip("DualShock 4 not connected. Connect via USB cable or pair via Bluetooth.")
        elif mode == "pscam":
            if hasattr(self, "btn_bottom_disconnect_phone"):
                self.btn_bottom_disconnect_phone.setVisible(False)
            self.btn_start.setText("START TRACKING")
            self.btn_start.setEnabled(ready)
            self.btn_start.setVisible(ready)
            if ready:
                self.btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
                self.btn_start.setToolTip("Start tracking with PlayStation Camera (60 FPS)")
            else:
                self.btn_start.setCursor(Qt.CursorShape.ForbiddenCursor)
                self.btn_start.setToolTip("PlayStation Camera not connected. Connect via USB 3.0 to start tracking.")
        elif mode == "phone_cam":
            self.btn_start.setText("START TRACKING")
            self.btn_start.setEnabled(ready)
            self.btn_start.setVisible(ready)
            if ready:
                self.btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
                self.btn_start.setToolTip("Start tracking with connected Smartphone Camera")
                if hasattr(self, "btn_bottom_disconnect_phone"):
                    self.btn_bottom_disconnect_phone.setVisible(True)
            else:
                self.btn_start.setCursor(Qt.CursorShape.ForbiddenCursor)
                self.btn_start.setToolTip("Smartphone not connected. Scan the QR code to connect your phone.")
                if hasattr(self, "btn_bottom_disconnect_phone"):
                    self.btn_bottom_disconnect_phone.setVisible(False)
        else:  # webcam
            if hasattr(self, "btn_bottom_disconnect_phone"):
                self.btn_bottom_disconnect_phone.setVisible(False)
            self.btn_start.setText("START TRACKING")
            self.btn_start.setEnabled(ready)
            self.btn_start.setVisible(ready)
            if ready:
                self.btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
                self.btn_start.setToolTip("Start tracking with selected Webcam")
            else:
                self.btn_start.setCursor(Qt.CursorShape.ForbiddenCursor)
                self.btn_start.setToolTip("No webcam detected. Connect a camera to start tracking.")

    def _disabled_tab_css(self) -> str:
        return f"""
            QPushButton {{
                background-color: #F1F5F9;
                color: #94A3B8;
                font-family: '{self.font_heading}', sans-serif;
                font-size: 12px;
                font-weight: bold;
                border: 1px solid #CBD5E1;
                border-radius: 10px;
            }}
        """

    def _update_tab_availability(self):
        """Disables and grays out the Calibration and Experimental tabs when the camera is not connected/accessible."""
        accessible = self.is_camera_accessible()
        if not accessible:
            self.btn_tab_calib.setEnabled(False)
            self.btn_tab_calib.setCursor(Qt.CursorShape.ForbiddenCursor)
            if hasattr(self, "btn_tab_exp"):
                self.btn_tab_exp.setEnabled(False)
                self.btn_tab_exp.setCursor(Qt.CursorShape.ForbiddenCursor)
            if self.active_tab in ("calib", "exp"):
                fallback = "controller" if self.cfg.get("camera_mode") == "ds4" else "video"
                self._switch_tab(fallback)
            else:
                self.btn_tab_calib.setStyleSheet(self._disabled_tab_css())
                self.btn_tab_calib.setIcon(QIcon(self.pix_slid_disabled))
                if hasattr(self, "btn_tab_exp"):
                    self.btn_tab_exp.setStyleSheet(self._disabled_tab_css())
                    self.btn_tab_exp.setIcon(QIcon(self.pix_lab_inact))
        else:
            self.btn_tab_calib.setEnabled(True)
            self.btn_tab_calib.setCursor(Qt.CursorShape.PointingHandCursor)
            if hasattr(self, "btn_tab_exp"):
                self.btn_tab_exp.setEnabled(True)
                self.btn_tab_exp.setCursor(Qt.CursorShape.PointingHandCursor)
            self._apply_tab_styles(self.active_tab)

    def _apply_tab_styles(self, tab_id: str):
        act_css = f"""
            QPushButton {{
                background-color: {PALETTE["tab_gray_act"]};
                color: #0F172A;
                font-family: '{self.font_heading}', sans-serif;
                font-size: 12px;
                font-weight: bold;
                border: 1px solid {PALETTE["tab_gray_border"]};
                border-radius: 10px;
            }}
        """
        inact_css = f"""
            QPushButton {{
                background-color: #FFFFFF;
                color: #64748B;
                font-family: '{self.font_heading}', sans-serif;
                font-size: 12px;
                font-weight: bold;
                border: 1px solid {PALETTE["border_subtle"]};
                border-radius: 10px;
            }}
            QPushButton:hover {{
                background-color: {PALETTE["tab_gray_hover"]};
                border-color: {PALETTE["tab_gray_border"]};
            }}
        """
        accessible = self.is_camera_accessible()

        # Video Tab
        if tab_id == "video":
            self.btn_tab_video.setStyleSheet(act_css)
            self.btn_tab_video.setIcon(QIcon(self.pix_gear_act))
        else:
            self.btn_tab_video.setStyleSheet(inact_css)
            self.btn_tab_video.setIcon(QIcon(self.pix_gear_inact))

        # Calibration Tab (Access-Gated)
        if not accessible:
            self.btn_tab_calib.setEnabled(False)
            self.btn_tab_calib.setCursor(Qt.CursorShape.ForbiddenCursor)
            self.btn_tab_calib.setStyleSheet(self._disabled_tab_css())
            self.btn_tab_calib.setIcon(QIcon(self.pix_slid_disabled))
        else:
            self.btn_tab_calib.setEnabled(True)
            self.btn_tab_calib.setCursor(Qt.CursorShape.PointingHandCursor)
            if tab_id == "calib":
                self.btn_tab_calib.setStyleSheet(act_css)
                self.btn_tab_calib.setIcon(QIcon(self.pix_slid_act))
            else:
                self.btn_tab_calib.setStyleSheet(inact_css)
                self.btn_tab_calib.setIcon(QIcon(self.pix_slid_inact))

        # Experimental Tab (Access-Gated for camera modes)
        if hasattr(self, "btn_tab_exp"):
            if not accessible:
                self.btn_tab_exp.setEnabled(False)
                self.btn_tab_exp.setCursor(Qt.CursorShape.ForbiddenCursor)
                self.btn_tab_exp.setStyleSheet(self._disabled_tab_css())
                self.btn_tab_exp.setIcon(QIcon(self.pix_lab_inact))
            else:
                self.btn_tab_exp.setEnabled(True)
                self.btn_tab_exp.setCursor(Qt.CursorShape.PointingHandCursor)
                if tab_id == "exp":
                    self.btn_tab_exp.setStyleSheet(act_css)
                    self.btn_tab_exp.setIcon(QIcon(self.pix_lab_act))
                else:
                    self.btn_tab_exp.setStyleSheet(inact_css)
                    self.btn_tab_exp.setIcon(QIcon(self.pix_lab_inact))

        # Controller Settings Tab (DualShock 4 Mode)
        if hasattr(self, "btn_tab_controller"):
            if tab_id == "controller":
                self.btn_tab_controller.setStyleSheet(act_css)
                self.btn_tab_controller.setIcon(QIcon(self.pix_ctrl_act))
            else:
                self.btn_tab_controller.setStyleSheet(inact_css)
                self.btn_tab_controller.setIcon(QIcon(self.pix_ctrl_inact))

    def _switch_tab(self, tab_id: str):
        if tab_id in ("calib", "exp") and not self.is_camera_accessible():
            return
        if self.active_tab == tab_id:
            return
        self.active_tab = tab_id
        self._apply_tab_styles(tab_id)

        if tab_id == "video":
            self.stacked_view.slide_to_index(0)
            self._update_video_view_visibility()
        elif tab_id == "calib":
            self.stacked_view.slide_to_index(1)
        elif tab_id == "exp":
            self.stacked_view.slide_to_index(2)
        elif tab_id == "controller":
            self.stacked_view.slide_to_index(3)

    def _set_mode(self, mode: str, animate: bool = True):
        self.cfg["camera_mode"] = mode
        self._update_sidebar_buttons()
        if mode == "ds4":
            if hasattr(self, "btn_tab_video"):
                self.btn_tab_video.setVisible(False)
            if hasattr(self, "btn_tab_calib"):
                self.btn_tab_calib.setVisible(False)
            if hasattr(self, "btn_tab_exp"):
                self.btn_tab_exp.setVisible(True)
            if hasattr(self, "btn_tab_controller"):
                self.btn_tab_controller.setVisible(True)
            self._switch_tab("controller")
            if hasattr(self, "btn_start"):
                self.btn_start.setText("START CONTROLLER (DS4)")
            self._cancel_camera_warmup(sync=False)
            self._update_ds4_ui_readout()
            def _connect_done(_ok):
                try:
                    QtCore.QMetaObject.invokeMethod(self, "_finish_ds4_reconnect", Qt.ConnectionType.QueuedConnection)
                except (RuntimeError, Exception):
                    pass
            self.controller.devices.connect_ds4_async(callback=_connect_done)
        else:
            if hasattr(self, "btn_tab_controller"):
                self.btn_tab_controller.setVisible(False)
            if hasattr(self, "btn_tab_video"):
                self.btn_tab_video.setVisible(True)
            if hasattr(self, "btn_tab_calib"):
                self.btn_tab_calib.setVisible(True)
            if hasattr(self, "btn_tab_exp"):
                self.btn_tab_exp.setVisible(True)
            if mode == "phone_cam":
                self._cancel_camera_warmup(sync=False)
                self._ensure_phone_cam_server_started()
                self._refresh_phone_cam_qr()
                self._update_phone_cam_status()
            else:
                self._schedule_camera_warmup(300)
            self._refresh_presets()
            self._update_camera_dropdown_for_mode()
            self._update_pscam_status()
            self._update_video_view_visibility()
            self._switch_tab("video")
            if hasattr(self, "btn_start"):
                self.btn_start.setText("START TRACKING")
        self._update_exp_view_for_mode(mode)
        self._update_start_button_state()
        self._save_settings()

    def _update_sidebar_buttons(self):
        mode = self.cfg.get("camera_mode", "pscam")
        self.card_pscam.set_active(mode == "pscam")
        self.card_webcam.set_active(mode == "webcam")
        if hasattr(self, "card_phone_cam"):
            self.card_phone_cam.set_active(mode == "phone_cam")
        if hasattr(self, "card_ds4"):
            self.card_ds4.set_active(mode == "ds4")

    def _update_video_view_visibility(self):
        """
        State-aware visibility controller:
        - When DISCONNECTED: The balloon (and QR Code for Phone Camera) is the ONLY THING displayed.
        - When CONNECTED: The balloon/QR disappears; the options card and Additional Display Options are displayed.
        """
        mode = self.cfg.get("camera_mode", "pscam")
        cams = getattr(self, "camera_list", [])

        if hasattr(self, "phone_cam_disconnected_box"):
            self.phone_cam_disconnected_box.setVisible(False)
        if hasattr(self, "phone_cam_card"):
            self.phone_cam_card.setVisible(False)

        if mode == "pscam":
            self.webcam_disconnected_box.setVisible(False)
            self.webcam_card.setVisible(False)

            is_ready = (self._current_pscam_state == "READY")
            if not is_ready:
                self.pscam_card.setVisible(False)
                self.display_card.setVisible(False)
                self.pscam_disconnected_box.setVisible(True)
            else:
                self.pscam_disconnected_box.setVisible(False)
                self.pscam_card.setVisible(True)
                self.display_card.setVisible(True)
        elif mode == "phone_cam":
            self.pscam_disconnected_box.setVisible(False)
            self.pscam_card.setVisible(False)
            self.webcam_disconnected_box.setVisible(False)
            self.webcam_card.setVisible(False)

            is_phone_conn = bool(self.controller.devices.get_phone_cam_status().get("is_connected", False))
            if not is_phone_conn:
                if hasattr(self, "phone_cam_card"):
                    self.phone_cam_card.setVisible(False)
                self.display_card.setVisible(False)
                if hasattr(self, "phone_cam_disconnected_box"):
                    self.phone_cam_disconnected_box.setVisible(True)
            else:
                if hasattr(self, "phone_cam_disconnected_box"):
                    self.phone_cam_disconnected_box.setVisible(False)
                if hasattr(self, "phone_cam_card"):
                    self.phone_cam_card.setVisible(True)
                self.display_card.setVisible(True)
        else:
            self.pscam_disconnected_box.setVisible(False)
            self.pscam_card.setVisible(False)

            webcams = [c for c in cams if not c.is_pscam]
            if not webcams and not any(c.is_pscam for c in cams):
                webcams = cams

            if not webcams and not self._is_refreshing_cams:
                self.webcam_card.setVisible(False)
                self.display_card.setVisible(False)
                self.webcam_disconnected_box.setVisible(True)
            elif webcams:
                self.webcam_disconnected_box.setVisible(False)
                self.webcam_card.setVisible(True)
                self.display_card.setVisible(True)

        self._update_tab_availability()
        self._update_start_button_state()

    def _refresh_presets(self):
        mode = self.cfg.get("camera_mode", "pscam")
        if mode == "pscam":
            presets = PRESETS_PSCAM
            current = self.cfg.get("pscam_preset", presets[0])
        elif mode == "phone_cam":
            presets = PRESETS_PHONE_CAM
            current = self.cfg.get("phone_cam_preset", presets[0])
        else:
            presets = PRESETS_WEBCAM
            current = self.cfg.get("webcam_preset", presets[0])
        w, h, fps = parse_preset(current)
        res_str = f"{w}x{h}"
        fps_str = f"{fps} FPS"

        if hasattr(self, "cb_phone_res") and hasattr(self, "cb_phone_fps"):
            p_w, p_h, p_fps = parse_preset(self.cfg.get("phone_cam_preset", PRESETS_PHONE_CAM[0]))
            self.cb_phone_res.blockSignals(True)
            self.cb_phone_fps.blockSignals(True)
            idx_pr = self.cb_phone_res.findText(f"{p_w}x{p_h}", Qt.MatchFlag.MatchStartsWith)
            self.cb_phone_res.setCurrentIndex(max(0, idx_pr))
            idx_pf = self.cb_phone_fps.findText(f"{p_fps} FPS", Qt.MatchFlag.MatchStartsWith)
            self.cb_phone_fps.setCurrentIndex(max(0, idx_pf))
            self.cb_phone_res.blockSignals(False)
            self.cb_phone_fps.blockSignals(False)

        if hasattr(self, "cb_res") and hasattr(self, "cb_fps"):
            self.cb_res.blockSignals(True)
            self.cb_fps.blockSignals(True)
            idx_r = self.cb_res.findText(res_str, Qt.MatchFlag.MatchStartsWith)
            self.cb_res.setCurrentIndex(max(0, idx_r))
            idx_f = self.cb_fps.findText(fps_str, Qt.MatchFlag.MatchStartsWith)
            self.cb_fps.setCurrentIndex(max(0, idx_f))
            self.cb_res.blockSignals(False)
            self.cb_fps.blockSignals(False)

        if hasattr(self, "cb_preset"):
            self.cb_preset.blockSignals(True)
            self.cb_preset.clear()
            self.cb_preset.addItems(presets)
            idx = self.cb_preset.findText(current)
            self.cb_preset.setCurrentIndex(max(0, idx))
            self.cb_preset.blockSignals(False)

    def _update_camera_dropdown_for_mode(self):
        mode = self.cfg.get("camera_mode", "pscam")
        cams = getattr(self, "camera_list", [])

        if self._is_refreshing_cams and not cams and not getattr(self, "camera_list", []):
            msg = "Searching for PlayStation®Camera..." if mode == "pscam" else "Searching for webcams..."
            self.cb_cameras.blockSignals(True)
            self.cb_cameras.clear()
            self.cb_cameras.addItem(msg)
            self.cb_cameras.blockSignals(False)
            if mode == "webcam":
                self.lbl_webcam_conn_title.setText("Searching for webcams...")
                self.lbl_webcam_info.setText("Scanning USB video capture devices...")
                if hasattr(self, "btn_refresh_webcam"):
                    self.btn_refresh_webcam.setEnabled(False)
                    self.btn_refresh_webcam.setText("Searching...")
            self._update_video_view_visibility()
            return

        if mode in ("phone_cam", "ds4"):
            self._update_video_view_visibility()
            return

        if mode == "pscam":
            ps_cams = [c for c in cams if c.is_pscam]
            if ps_cams:
                self.cfg["camera_index"] = ps_cams[0].index
            elif not cams:
                pass
            else:
                self.cfg["camera_index"] = -1
        else:
            webcams = [c for c in cams if not c.is_pscam]
            if not webcams and not any(c.is_pscam for c in cams):
                webcams = cams

            self.cb_cameras.blockSignals(True)
            self.cb_cameras.clear()
            if webcams:
                for c in webcams:
                    self.cb_cameras.addItem(str(c))
                current_idx = self.cfg.get("camera_index", 0)
                selected_idx = 0
                for i, c in enumerate(webcams):
                    if c.index == current_idx:
                        selected_idx = i
                        break
                self.cb_cameras.setCurrentIndex(selected_idx)
                self.cfg["camera_index"] = webcams[selected_idx].index
            elif not cams:
                pass
            else:
                self.lbl_webcam_icon.setPixmap(self.pix_status_err)
                self.lbl_webcam_conn_title.setText("Webcam not connected")
                self.lbl_webcam_info.setText("Camera disconnected from USB Port")
                self.btn_refresh_webcam.setEnabled(True)
                self.btn_refresh_webcam.setText("Search for Webcams")
                self.cb_cameras.addItem("No webcam found")
                self.cfg["camera_index"] = -1
            self.cb_cameras.blockSignals(False)

        self._update_video_view_visibility()

    def _update_pscam_status(self):
        info = self.controller.camera.get_ps4_state()
        self._apply_pscam_state(info)

    def _apply_pscam_state(self, ps4_info: dict):
        state = ps4_info.get("state", "DISCONNECTED")
        self._current_pscam_state = state

        if state in ("NOT_INSTALLED", "DISCONNECTED"):
            self.lbl_pscam_icon.setPixmap(self.pix_status_err)
            self.lbl_pscam_conn_title.setText("PlayStation Camera not connected")
            self.lbl_pscam_info.setText("Connect camera to USB 3.0 Port (AUX adapter required)")
            self.lbl_pscam_info.setStyleSheet(
                f"font-family: '{self.font_body}'; font-size: 11px; color: {PALETTE['text_muted']}; background: transparent; border: none;"
            )

        elif state in ("DRIVER_STOPPED", "BOOTLOADER_UPLOADING", "WAITING_VCAM"):
            self.lbl_pscam_icon.setPixmap(self.pix_status_warn)
            self.lbl_pscam_conn_title.setText("PlayStation Camera initializing")
            self.lbl_pscam_info.setText("Camera detected! Initializing high-speed 60 FPS video stream...")
            self.lbl_pscam_info.setStyleSheet(
                f"font-family: '{self.font_body}'; font-size: 11px; color: {PALETTE['ps_blue']}; background: transparent; border: none;"
            )

        elif state == "READY":
            self.lbl_pscam_icon.setPixmap(self.pix_status_ok)
            self.lbl_pscam_conn_title.setText("PlayStation Camera connected")
            eye_label = "Left Eye" if str(self.cfg.get("ps4_eye", "right")).lower() == "left" else "Right Eye"
            cams = getattr(self, "camera_list", [])
            ps_cams = [c for c in cams if c.is_pscam]
            if ps_cams:
                cam_idx = ps_cams[0].index
                txt = f"PlayStation®Camera connected (Index {cam_idx} • {eye_label} • 60 FPS)"
            else:
                txt = f"PlayStation®Camera connected ({eye_label} • 60 FPS)"
            self.lbl_pscam_ready_info.setText(txt)

        self._update_video_view_visibility()

    def _refresh_cameras(self):
        self._refresh_cameras_async()

    def _refresh_cameras_async(self):
        if hasattr(self, "btn_refresh"):
            self.btn_refresh.setEnabled(False)
            self.btn_refresh.setIcon(QIcon())
            self.btn_refresh.setText("…")
        if hasattr(self, "btn_refresh_webcam"):
            self.btn_refresh_webcam.setEnabled(False)
            self.btn_refresh_webcam.setText("Searching...")
        self.controller.camera.refresh_cameras_async()

    @Slot(list)
    def _on_cameras_refreshed(self, cams):
        if getattr(self, "_is_closing", False):
            return
        self.camera_list = cams
        if hasattr(self, "btn_refresh"):
            self.btn_refresh.setEnabled(True)
            self.btn_refresh.setText("")
            self.btn_refresh.setIcon(getattr(self, "icon_reload", QIcon()))
        if hasattr(self, "btn_refresh_webcam"):
            self.btn_refresh_webcam.setEnabled(True)
            self.btn_refresh_webcam.setText("Search for Webcams")
        self._update_pscam_status()
        self._update_camera_dropdown_for_mode()
        self._update_start_button_state()

    def _on_camera_selected(self, index: int):
        sel_text = self.cb_cameras.currentText()
        for c in self.camera_list:
            if str(c) == sel_text:
                self.cfg["camera_index"] = c.index
                self._save_settings()
                self._schedule_camera_warmup(300)
                break

    def _on_webcam_res_or_fps_changed(self):
        if not hasattr(self, "cb_res") or not hasattr(self, "cb_fps"):
            return
        res = self.cb_res.currentText().split()[0]
        fps_val = self.cb_fps.currentText().split()[0]
        preset = f"{res} @ {fps_val} FPS"
        self.cfg["webcam_preset"] = preset
        if hasattr(self, "cb_preset"):
            self.cb_preset.blockSignals(True)
            idx = self.cb_preset.findText(preset)
            if idx >= 0:
                self.cb_preset.setCurrentIndex(idx)
            self.cb_preset.blockSignals(False)
        self._save_settings()
        self._schedule_camera_warmup(300)

    def _on_preset_selected(self, index: int = 0):
        mode = self.cfg.get("camera_mode", "pscam")
        if hasattr(self, "cb_preset"):
            preset = self.cb_preset.currentText()
            if mode == "pscam":
                self.cfg["pscam_preset"] = preset
            else:
                self.cfg["webcam_preset"] = preset
                if hasattr(self, "cb_res") and hasattr(self, "cb_fps"):
                    w, h, fps = parse_preset(preset)
                    idx_r = self.cb_res.findText(f"{w}x{h}", Qt.MatchFlag.MatchStartsWith)
                    if idx_r >= 0:
                        self.cb_res.blockSignals(True)
                        self.cb_res.setCurrentIndex(idx_r)
                        self.cb_res.blockSignals(False)
                    idx_f = self.cb_fps.findText(f"{fps} FPS", Qt.MatchFlag.MatchStartsWith)
                    if idx_f >= 0:
                        self.cb_fps.blockSignals(True)
                        self.cb_fps.setCurrentIndex(idx_f)
                        self.cb_fps.blockSignals(False)
        self._save_settings()
        self._schedule_camera_warmup(300)

    def _on_display_options_changed(self):
        self.cfg["show_hud"] = self.chk_hud.isChecked()
        self.cfg["face_follow_enabled"] = self.chk_face.isChecked()
        self._save_settings()

    def _on_orientation_changed(self, index: int):
        orientations = [0, 90, 180, 270]
        angle = orientations[index] if 0 <= index < len(orientations) else 0
        self.cfg["camera_orientation"] = angle
        self._save_settings()
        self._schedule_camera_warmup(300)

    def _on_ps4_eye_changed(self, index: int):
        self.cfg["ps4_eye"] = "left" if index == 1 else "right"
        self._save_settings()
        self._update_pscam_status()
        self._schedule_camera_warmup(300)

    def _launch_pscam_tray(self):
        ok, msg = CameraManager.launch_pscam_tray()
        if ok:
            QMessageBox.information(self, "PlayStation Camera Backend", msg)
            self._refresh_cameras_async()
        else:
            QMessageBox.warning(self, "PlayStation Camera Backend", msg)


__all__ = ["UICameraHandlersMixin"]
