"""
Tracking, Calibration & AI Model Lifecycle Handlers Mixin for Legacy PSCam Sensor Qt 6 GUI.
Encapsulates MediaPipe background pre-warming, on-demand %APPDATA% model download UI,
calibration presets/sliders, 1P/2P mode selection, and Start/Stop Tracking lifecycle.
"""
from __future__ import annotations

import sys
import threading

from PySide6.QtCore import QTimer, Slot
from PySide6.QtWidgets import QMessageBox

from ui.theme import CALIB_PRESETS


class UITrackingHandlersMixin:
    """Mixin handling calibration presets, AI model caching, and live tracking lifecycle."""

    # =========================================================================
    # AI MODEL PRE-WARMING & ON-DEMAND DOWNLOAD
    # =========================================================================
    def _prewarm_pose_engine_async(self):
        """Pre-loads MediaPipe / PoseTracker in a background thread after the window is visible."""
        if getattr(self, "_is_closing", False):
            return

        # Pre-fetch Full AI model into %APPDATA% cache if user already saved Balanced preset
        active_model = str(self.cfg.get("pose_model", "lite")).strip().lower()
        if active_model == "full":
            self._ensure_pose_model_async("full")

        if "mediapipe" in sys.modules:
            return

        def _warm_worker():
            try:
                import sensor.pose_tracker  # noqa: F401
            except Exception:
                pass

        threading.Thread(target=_warm_worker, daemon=True, name="MediaPipePrewarmThread").start()

    def _ensure_pose_model_async(self, variant: str):
        """
        Ensures the requested AI model variant (`lite` or `full`) is available in the local or
        persistent `%APPDATA%\\LegacyPSCam_Sensor\\models` cache without blocking the Qt UI thread
        (including SHA-256 verification).
        """
        if getattr(self, "_is_closing", False):
            return
        try:
            from sensor.model_manager import ModelManager
            norm = ModelManager.normalize_variant(variant)
        except Exception:
            return

        if getattr(self, "_downloading_model_variant", None) == norm:
            return
        self._downloading_model_variant = norm

        def _safe_emit(v: str, pct: int, status: str):
            if getattr(self, "_is_closing", False):
                return
            try:
                self.model_download_signal.emit(v, pct, status)
            except RuntimeError:
                pass

        def _dl_worker():
            try:
                from sensor.model_manager import ModelManager
                if ModelManager.is_model_ready(norm):
                    return
                _safe_emit(norm, 0, "downloading")
                last_pct = [-1]

                def _cb(done: int, total: int):
                    pct = int(min(100, round((done * 100.0) / max(1, total))))
                    if pct != last_pct[0]:
                        last_pct[0] = pct
                        _safe_emit(norm, pct, "downloading")

                res = ModelManager.download_model(norm, progress_cb=_cb)
                if res is not None:
                    _safe_emit(norm, 100, "done")
                else:
                    _safe_emit(norm, -1, "offline")
            except Exception:
                _safe_emit(norm, -1, "offline")
            finally:
                if getattr(self, "_downloading_model_variant", None) == norm:
                    self._downloading_model_variant = None

        threading.Thread(target=_dl_worker, daemon=True, name=f"ModelDownload-{norm}").start()

    @Slot(str, int, str)
    def _on_model_download_progress(self, variant: str, pct: int, status: str):
        if getattr(self, "_is_closing", False):
            return
        if not hasattr(self, "model_dl_box") or not hasattr(self, "lbl_model_dl_status"):
            return
        label = "Balanced (Full AI)" if variant == "full" else "Competitive (Lite AI)"
        if status == "downloading":
            self.model_dl_box.setStyleSheet(
                "QFrame#modelDownloadBox { background-color: #EFF6FF; border: 1px solid #93C5FD; border-radius: 8px; }"
            )
            self.lbl_model_dl_status.setText(
                f"Downloading {label} model to persistent cache (%APPDATA%)... {max(0, pct)}%"
            )
            self.model_dl_box.setVisible(True)
        elif status == "done":
            self.model_dl_box.setStyleSheet(
                "QFrame#modelDownloadBox { background-color: #ECFDF5; border: 1px solid #6EE7B7; border-radius: 8px; }"
            )
            self.lbl_model_dl_status.setText(
                f"{label} model cached in %APPDATA% — Ready for instant launch!"
            )
            self.model_dl_box.setVisible(True)
            QTimer.singleShot(
                3000,
                self,
                lambda: self.model_dl_box.setVisible(False)
                if (not getattr(self, "_is_closing", False) and hasattr(self, "model_dl_box"))
                else None,
            )
        else:
            self.model_dl_box.setStyleSheet(
                "QFrame#modelDownloadBox { background-color: #FEF3C7; border: 1px solid #FCD34D; border-radius: 8px; }"
            )
            self.lbl_model_dl_status.setText(
                f"Could not download {label} (offline). Lite AI will be used automatically until connected."
            )
            self.model_dl_box.setVisible(True)

    # =========================================================================
    # CALIBRATION, 1P/2P MODE & FILTER SLIDERS
    # =========================================================================
    def _select_calib_preset(self, preset_id: str):
        if preset_id not in CALIB_PRESETS:
            return
        self.current_calib_preset = preset_id
        self.cfg["tracking_preset"] = preset_id
        p = CALIB_PRESETS[preset_id]
        self.cfg["pose_model"] = p.get("pose_model", "lite")
        self.cfg["smoothing_alpha"] = p["smoothing_alpha"]
        self.cfg["detection_confidence"] = p["detection_confidence"]

        self.slider_smooth.blockSignals(True)
        self.slider_smooth.setValue(int(p["smoothing_alpha"] * 100))
        self.slider_smooth.blockSignals(False)
        self._update_smooth_label(p["smoothing_alpha"])

        self.slider_conf.blockSignals(True)
        self.slider_conf.setValue(int(p["detection_confidence"] * 100))
        self.slider_conf.blockSignals(False)
        self._update_conf_label(p["detection_confidence"])

        self._update_calib_cards_ui()
        self._update_2p_warning_ui()
        self._save_settings()
        if str(self.cfg.get("pose_model", "lite")).strip().lower() == "full":
            self._ensure_pose_model_async("full")

    def _on_players_mode_changed(self, idx: int):
        max_p = 2 if idx == 1 else 1
        self.cfg["max_players"] = max_p
        self._update_2p_warning_ui()
        self._save_settings()

    def _update_2p_warning_ui(self):
        max_p = max(1, min(2, int(self.cfg.get("max_players", 1))))
        is_2p = (max_p >= 2)
        if hasattr(self, "two_player_warn_box"):
            self.two_player_warn_box.setVisible(is_2p)
        if hasattr(self, "lbl_2p_model_warning"):
            cur_model = str(self.cfg.get("pose_model", "lite")).strip().lower()
            if cur_model == "full":
                self.lbl_2p_model_warning.setText(
                    "2-Player Mode Active with Full AI: Tracking 2 dancers with Full AI doubles CPU load and may reduce FPS. "
                    "Switch to 'Competitive (Lite AI)' above for optimal 2-player performance."
                )
            else:
                self.lbl_2p_model_warning.setText(
                    "2-Player Mode Active: Lite AI (Competitive) is active and recommended to sustain stable FPS when tracking two dancers simultaneously."
                )

    def _update_calib_cards_ui(self):
        for pid, card in self.calib_cards.items():
            card.set_active(pid == self.current_calib_preset)
        self._update_2p_warning_ui()

    def _toggle_advanced_calib(self):
        self.is_adv_calib_open = not self.is_adv_calib_open
        self.adv_drawer.setVisible(self.is_adv_calib_open)
        self.btn_toggle_adv.setText(
            "Hide Advanced Filter Settings ▲" if self.is_adv_calib_open else "Show Advanced Filter Settings ▼"
        )

    def _update_smooth_label(self, val: float):
        v = float(val)
        desc = "Balanced"
        if v < 0.40:
            desc = "Very Smooth (Higher Latency)"
        elif v > 0.65:
            desc = "Ultra Fast (Lower Filtering)"
        self.lbl_smooth.setText(f"Movement Responsiveness (EMA): {v:.2f} — {desc}")

    def _update_conf_label(self, val: float):
        v = float(val)
        self.lbl_conf.setText(f"AI Detection Rigor (Confidence): {int(v * 100)}%")

    def _on_smooth_slider_changed(self, val: int):
        alpha = round(val / 100.0, 2)
        self._update_smooth_label(alpha)
        self.cfg["smoothing_alpha"] = alpha
        self.current_calib_preset = "custom"
        self.cfg["tracking_preset"] = "custom"
        self._update_calib_cards_ui()
        self._save_settings()

    def _on_conf_slider_changed(self, val: int):
        conf = round(val / 100.0, 2)
        self._update_conf_label(conf)
        self.cfg["detection_confidence"] = conf
        self.current_calib_preset = "custom"
        self.cfg["tracking_preset"] = "custom"
        self._update_calib_cards_ui()
        self._save_settings()

    # =========================================================================
    # TRACKING SESSION LIFECYCLE
    # =========================================================================
    def _start_tracking(self):
        if self.is_tracking_active or getattr(self, "_is_preparing_tracking", False):
            return
        if hasattr(self, "btn_start") and not self.btn_start.isEnabled():
            return

        mode = self.cfg.get("camera_mode", "pscam")
        self._is_preparing_tracking = True
        if hasattr(self, "btn_start"):
            self.btn_start.setText("PREPARING DEVICE...")
            self.btn_start.setEnabled(False)

        def _on_val_done(ok: bool, title: str, msg: str):
            if getattr(self, "_is_closing", False):
                return
            try:
                self.pre_tracking_validated_signal.emit(bool(ok), str(title), str(msg), str(mode))
            except RuntimeError:
                pass

        self.controller.validate_pre_tracking_async(mode, callback=_on_val_done)

    @Slot(bool, str, str, str)
    def _on_pre_tracking_validated(self, ok: bool, title: str, msg: str, mode: str):
        self._is_preparing_tracking = False
        if getattr(self, "_is_closing", False):
            return
        if not ok:
            self._update_start_button_state()
            QMessageBox.warning(self, title, msg)
            return

        self._save_settings()

        started = self.controller.start_tracking()
        if not started:
            self._update_start_button_state()
            return

        if hasattr(self, "lbl_vphone_accel"):
            self.lbl_vphone_accel.setVisible(True)
        self.btn_start.setText("TRACKING IN PROGRESS...")
        self.btn_start.setEnabled(False)
        self.showMinimized()

    @Slot(bool, str)
    def _on_tracking_finished(self, success: bool, err_msg: str):
        if getattr(self, "_is_closing", False):
            return
        self.is_tracking_active = False
        if hasattr(self, "lbl_vphone_accel"):
            self.lbl_vphone_accel.setVisible(False)
        self._update_start_button_state()
        self.showNormal()
        self.activateWindow()
        self._refresh_cameras()
        mode = self.cfg.get("camera_mode", "pscam")
        if mode == "phone_cam":
            self._update_phone_cam_status()
            if not bool(self.controller.devices.get_phone_cam_status().get("is_connected", False)):
                self._refresh_phone_cam_qr(rotate_token=False)

        if not success:
            detail = f"\n\nDetails: {err_msg}" if err_msg else ""
            if mode == "ds4":
                tips = (
                    "• Verify the DualShock 4 is connected via USB or paired via Windows Bluetooth.\n"
                    "• Make sure no other input remapper (e.g., DS4Windows) is holding exclusive HID access."
                )
            elif mode == "phone_cam":
                tips = (
                    "• Keep the Phone Camera WebApp open on your smartphone browser.\n"
                    "• Ensure PC and smartphone are on the same Wi-Fi network and Windows Firewall allows the port."
                )
            elif mode == "webcam":
                tips = (
                    "• Check if the webcam is properly connected to USB.\n"
                    "• Make sure no other application (OBS, Zoom, Discord) is locking the webcam."
                )
            else:
                tips = (
                    "• Check if the PlayStation 4 Camera is connected to a USB 3.0 port.\n"
                    "• Verify that the WinUSB driver association is active.\n"
                    "• Make sure no other application is locking the camera."
                )
            QMessageBox.critical(
                self,
                "Tracking Initialization Failed",
                f"Could not start tracking with the selected device.{detail}\n\n{tips}",
            )


__all__ = ["UITrackingHandlersMixin"]
