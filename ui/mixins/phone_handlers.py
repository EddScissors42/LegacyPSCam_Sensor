"""
Phone Camera (Wi-Fi WebApp & QR Code) Handlers Mixin for Legacy PSCam Sensor Qt 6 GUI.
Encapsulates LAN IP selection, Windows Firewall rule button, QR Code rendering,
URL copying, wireless stream settings, and client disconnection.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer, Slot
from PySide6.QtWidgets import QApplication, QMessageBox

from ui.widgets import pil_to_qpixmap


class UIPhoneHandlersMixin:
    """Mixin handling Phone Camera WebApp pairing, firewall, and stream controls."""

    def _ensure_phone_cam_server_started(self):
        return self.controller.devices.ensure_phone_cam_server_started()

    def _refresh_phone_cam_ip_selector(self):
        if not hasattr(self, "cb_phone_cam_ip"):
            return
        try:
            items, active_ip = self.controller.devices.list_phone_cam_ips()
            self.cb_phone_cam_ip.blockSignals(True)
            self.cb_phone_cam_ip.clear()
            sel_idx = 0
            for idx, item in enumerate(items):
                ip_val = item.get("ip", "")
                label = item.get("label", ip_val)
                self.cb_phone_cam_ip.addItem(label, ip_val)
                if ip_val == active_ip:
                    sel_idx = idx
            if self.cb_phone_cam_ip.count() > 0:
                self.cb_phone_cam_ip.setCurrentIndex(sel_idx)
            self.cb_phone_cam_ip.blockSignals(False)
        except Exception:
            try:
                self.cb_phone_cam_ip.blockSignals(False)
            except Exception:
                pass

    def _refresh_phone_cam_firewall_button(self):
        if not hasattr(self, "btn_phone_firewall"):
            return
        try:
            fw = self.controller.devices.get_phone_cam_firewall_status()
            port = fw.get("port", 8443)
            if fw.get("port_rule_allowed"):
                self.btn_phone_firewall.setText("Firewall OK")
                self.btn_phone_firewall.setStyleSheet(
                    f"background-color: #ECFDF5; color: #047857; border: 1px solid #6EE7B7; "
                    f"border-radius: 6px; padding: 0 10px; font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold;"
                )
                self.btn_phone_firewall.setToolTip(
                    f"Windows Firewall allows inbound TCP port {port} on Private & Public Wi-Fi. Click to re-apply rule."
                )
            else:
                self.btn_phone_firewall.setText("Allow Firewall")
                self.btn_phone_firewall.setStyleSheet(
                    f"background-color: #FEF3C7; color: #92400E; border: 1px solid #F59E0B; "
                    f"border-radius: 6px; padding: 0 10px; font-family: '{self.font_heading}'; font-size: 11px; font-weight: bold;"
                )
                self.btn_phone_firewall.setToolTip(
                    f"Windows Firewall rule for TCP port {port} not found. Click to allow Private & Public Wi-Fi and prevent ERR_CONNECTION_TIMED_OUT."
                )
        except Exception:
            pass

    def _on_phone_cam_ip_changed(self, _index: int = 0):
        if not hasattr(self, "cb_phone_cam_ip"):
            return
        selected_ip = self.cb_phone_cam_ip.currentData()
        if selected_ip:
            self.controller.devices.set_phone_cam_ip(str(selected_ip))
            self._refresh_phone_cam_qr(rotate_token=False, refresh_adapters=False)

    def _on_allow_phone_cam_firewall(self):
        if hasattr(self, "btn_phone_firewall"):
            self.btn_phone_firewall.setEnabled(False)
            self.btn_phone_firewall.setText("Allowing...")

        def _fw_done(ok: bool, msg: str):
            if getattr(self, "_is_closing", False):
                return
            try:
                self.phone_firewall_signal.emit(bool(ok), str(msg))
            except RuntimeError:
                pass

        self.controller.devices.allow_phone_cam_firewall_async(callback=_fw_done)

    @Slot(bool, str)
    def _on_phone_firewall_finished(self, ok: bool, msg: str):
        if getattr(self, "_is_closing", False):
            return
        if hasattr(self, "btn_phone_firewall"):
            self.btn_phone_firewall.setEnabled(True)
        self._refresh_phone_cam_firewall_button()
        if ok:
            QMessageBox.information(self, "Windows Firewall Updated", msg)
        else:
            QMessageBox.warning(self, "Windows Firewall", msg)

    def _refresh_phone_cam_qr(self, _checked: bool = False, rotate_token: bool = False, refresh_adapters: bool = True):
        if refresh_adapters:
            self._refresh_phone_cam_ip_selector()
        self._refresh_phone_cam_firewall_button()
        pil_qr, url = self.controller.devices.render_pairing_qr_image(rotate_token=rotate_token)
        if hasattr(self, "lbl_phone_cam_url"):
            self.lbl_phone_cam_url.setText(url)
        if hasattr(self, "lbl_phone_qr_img") and pil_qr is not None:
            try:
                pix_qr = pil_to_qpixmap(pil_qr, dpr=2.0)
                self.lbl_phone_qr_img.setPixmap(pix_qr)
            except Exception as e:
                print(f"[WARN] Failed to render Phone Camera QR Code: {e}")

    def _on_copy_phone_cam_url(self):
        url = self.controller.devices.get_phone_cam_url()
        cb = QApplication.clipboard()
        if cb is not None:
            cb.setText(url)
        if hasattr(self, "btn_copy_phone_url"):
            self.btn_copy_phone_url.setText("Copied!")
            QTimer.singleShot(
                1500,
                self,
                lambda: self.btn_copy_phone_url.setText("Copy URL")
                if (not getattr(self, "_is_closing", False) and hasattr(self, "btn_copy_phone_url"))
                else None,
            )

    def _on_phone_cam_settings_changed(self):
        if not hasattr(self, "cb_phone_res") or not hasattr(self, "cb_phone_fps"):
            return
        res = self.cb_phone_res.currentText().split()[0]
        fps_val = self.cb_phone_fps.currentText().split()[0]
        preset = f"{res} @ {fps_val} FPS"
        self.cfg["phone_cam_preset"] = preset
        self._save_settings()
        self.controller.devices.update_phone_cam_preset(preset)

    def _on_disconnect_phone_cam(self):
        if self.is_tracking_active and self.cfg.get("camera_mode") == "phone_cam":
            self.controller.session.stop_tracking()
        self.controller.devices.disconnect_phone_cam(rotate_token=True)
        self._refresh_phone_cam_qr(rotate_token=False)
        self._update_phone_cam_status()


__all__ = ["UIPhoneHandlersMixin"]
