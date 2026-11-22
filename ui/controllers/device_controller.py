"""
Device Controller for Legacy PSCam Sensor.
Handles secondary peripherals: Phone Camera WebApp, DualShock 4 Controller,
and Virtual Phone (UbiArt WebSocket / Smartphone Controller Emulator).
Decoupled from Qt UI presentation. Fully lazy via PEP 562.
"""
import sys
import math
import threading
from typing import Optional, Tuple, Dict, Any, Callable

from sensor.config_manager import ConfigManager, parse_preset


class DeviceController:
    """
    Manages non-optical hardware and network inputs:
    - Smartphone Camera WebApp (Wi-Fi HTTPS/WSS + QR Code)
    - DualShock 4 & compatible clone controllers (Bluetooth/USB HID)
    - Virtual Phone (UbiArt WebSocket emulating Just Dance Controller)
    """
    def __init__(self, config_manager: Optional[ConfigManager] = None):
        self.cfg_mgr = config_manager or ConfigManager()
        self.cfg = self.cfg_mgr.config

        # Lazy references
        self._vphone = None
        self._ds4 = None
        self._is_connecting_ds4 = False
        self._last_phone_cam_conn = None

    # =========================================================================
    # PHONE CAMERA WEBAPP (WI-FI SMARTPHONE STREAM)
    # =========================================================================
    def ensure_phone_cam_server_started(self):
        """Starts the local HTTPS/WSS server for smartphone camera if not running."""
        import sensor
        srv = sensor.get_phone_camera_server(port=int(self.cfg.get("phone_cam_port", 8443)))
        if not srv.running:
            srv.start()
        w, h, fps = parse_preset(self.cfg.get("phone_cam_preset", "640x480 @ 30 FPS"))
        lens = str(self.cfg.get("phone_cam_lens", "user")).strip().lower()
        srv.configure_stream(width=w, height=h, fps=fps, lens=lens)
        return srv

    def get_phone_cam_url(self, rotate_token: bool = False) -> str:
        srv = self.ensure_phone_cam_server_started()
        if rotate_token:
            srv.rotate_session_token()
        return srv.get_connect_url()

    def render_pairing_qr_image(self, rotate_token: bool = False):
        """Generates PIL Image of pairing QR code."""
        import sensor
        url = self.get_phone_cam_url(rotate_token=rotate_token)
        try:
            pil_qr = sensor.QRCodeGenerator.render_pil_image(
                url,
                box_size_px=154 * 2,
                fg_color=(15, 23, 42, 255),
                bg_color=(255, 255, 255, 255),
                quiet_zone=2,
            )
            return pil_qr, url
        except Exception as e:
            print(f"[WARN] Failed to render Phone Camera QR Code: {e}")
            return None, url

    def update_phone_cam_preset(self, preset_str: str):
        self.cfg["phone_cam_preset"] = preset_str
        self.cfg_mgr.save()
        w, h, fps = parse_preset(preset_str)
        import sensor
        srv = sensor.get_phone_camera_server()
        srv.configure_stream(width=w, height=h, fps=fps)

    def disconnect_phone_cam(self):
        import sensor
        srv = sensor.get_phone_camera_server()
        srv.disconnect_client(rotate_token=True)

    def get_phone_cam_status(self) -> Dict[str, Any]:
        """Returns snapshot of Phone Camera server and client status."""
        import sensor
        srv = sensor.get_phone_camera_server()
        is_conn = bool(srv.is_client_connected)
        lens_lbl = "Rear Camera" if srv.client_lens == "environment" else "Front Camera"
        if srv.streaming_active:
            fps_disp = srv.measured_fps if srv.measured_fps > 0.5 else float(srv.target_fps)
            stream_lbl = f"{srv.actual_w}x{srv.actual_h} @ {fps_disp:.0f} FPS"
        else:
            stream_lbl = "Standby (Cool Mode)"
        info_txt = (
            f"{srv.client_device_name} connected ({srv.client_ip} • "
            f"{stream_lbl} • {lens_lbl})"
        ) if is_conn else "Disconnected"

        res = {
            "is_connected": is_conn,
            "info_text": info_txt,
            "device_name": srv.client_device_name,
            "client_ip": srv.client_ip,
            "streaming_active": srv.streaming_active,
        }
        return res

    # =========================================================================
    # DUALSHOCK 4 CONTROLLER
    # =========================================================================
    def get_ds4(self):
        if self._ds4 is None:
            import sensor
            self._ds4 = sensor.get_ds4_controller()
            self._init_ds4_config()
        return self._ds4

    def _init_ds4_config(self):
        ds4 = self.get_ds4()
        ds4.hand = str(self.cfg.get("ds4_hand", "right"))
        ds4.sensitivity = float(self.cfg.get("ds4_sensitivity", 1.0))
        ds4.permissive_mode = bool(self.cfg.get("ds4_permissive_mode", True))

    def get_ds4_readout(self) -> Dict[str, Any]:
        """Returns structured dictionary of DualShock 4 connection, battery and IMU metrics."""
        ds4 = self.get_ds4()
        is_conn = ds4.is_connected
        if is_conn:
            st = ds4.state
            charging_str = " [Charging]" if st.is_charging else ""
            conn_type = "Connected on USB" if ds4.is_usb else "Connected via Bluetooth"
            ctrl_name = getattr(st, "controller_name", "DualShock 4")
            ax, ay, az = st.accel_g
            tot = math.sqrt(ax * ax + ay * ay + az * az)
            act_btns = [b.upper() for b, pressed in st.buttons.items() if pressed]
            imu_frozen = bool(getattr(st, "imu_frozen", False))

            return {
                "is_connected": True,
                "controller_name": ctrl_name,
                "connection_type": conn_type,
                "sample_rate_hz": st.sample_rate_hz,
                "battery_pct": st.battery_pct,
                "is_charging": st.is_charging,
                "charging_str": charging_str,
                "imu_frozen": imu_frozen,
                "accel_g": (ax, ay, az),
                "total_g": tot,
                "buttons": act_btns,
            }

        # Controller is not connected - probe PnP/HID
        try:
            from sensor.ds4_controller import find_ds4_devices, detect_controller_name
            perm = bool(self.cfg.get("ds4_permissive_mode", True))
            paths = find_ds4_devices(permissive=perm)
            if paths:
                is_usb = any("bth" not in p.lower() and "bluetooth" not in p.lower() and "00001124" not in p.lower() for p in paths)
                detected_type = "on USB" if is_usb else "via Bluetooth"
                detected_name = detect_controller_name(paths[0])
                return {
                    "is_connected": False,
                    "device_present": True,
                    "controller_name": detected_name,
                    "connection_type": detected_type,
                }
        except Exception:
            pass

        return {
            "is_connected": False,
            "device_present": False,
        }

    def connect_ds4_async(self, callback: Optional[Callable[[bool], None]] = None):
        """Asynchronously attempts connection to DualShock 4."""
        if self._is_connecting_ds4:
            return
        self._is_connecting_ds4 = True
        perm = bool(self.cfg.get("ds4_permissive_mode", True))

        def worker():
            try:
                ds4 = self.get_ds4()
                if ds4.is_connected:
                    ds4.disconnect()
                    time.sleep(0.1)
                ok = ds4.connect(permissive=perm)
                if ok:
                    ds4.trigger_rumble(small=140, large=80, duration_sec=0.15)
                if callback:
                    callback(ok)
            finally:
                self._is_connecting_ds4 = False

        threading.Thread(target=worker, daemon=True, name="DS4ConnectThread").start()

    def disconnect_ds4(self):
        if self._ds4 is not None:
            try:
                self._ds4.disconnect()
            except Exception:
                pass

    def trigger_test_rumble(self) -> bool:
        ds4 = self.get_ds4()
        perm = bool(self.cfg.get("ds4_permissive_mode", True))
        if not ds4.is_connected:
            ds4.connect(permissive=perm)
        if ds4.is_connected:
            ds4.trigger_rumble(small=180, large=120, duration_sec=0.35)
            return True
        return False

    def set_ds4_permissive(self, val: bool):
        self.cfg["ds4_permissive_mode"] = bool(val)
        self.get_ds4().permissive_mode = bool(val)
        self.cfg_mgr.save()

    def set_ds4_hand(self, hand: str):
        self.cfg["ds4_hand"] = hand
        self.get_ds4().hand = hand
        self.cfg_mgr.save()

    def set_ds4_sensitivity(self, sens: float):
        self.cfg["ds4_sensitivity"] = sens
        self.get_ds4().sensitivity = sens
        self.cfg_mgr.save()

    # =========================================================================
    # VIRTUAL PHONE CONTROLLER (UBIART WEBSOCKET EMULATOR)
    # =========================================================================
    @property
    def vphone(self):
        if self._vphone is None:
            self._ensure_vphone_configured()
        return self._vphone

    def _ensure_vphone_configured(self):
        if self._vphone is None:
            import sensor
            self._vphone = sensor.get_virtual_phone()
            self._vphone.configure(
                host=str(self.cfg.get("virtual_phone_host", "127.0.0.1")),
                port=int(self.cfg.get("virtual_phone_port", 8080)),
                hand=str(self.cfg.get("virtual_phone_hand", "right")),
                sensitivity=float(self.cfg.get("virtual_phone_sensitivity", 1.0)),
                phone_name=str(self.cfg.get("virtual_phone_name", "Legacy PSCam Phone")),
                auto_record=bool(self.cfg.get("benchmark_auto_record", self.cfg.get("virtual_phone_auto_record", False))),
                adaptive=bool(self.cfg.get("virtual_phone_adaptive", False)),
            )
        return self._vphone

    def configure_vphone(self, host: str, port: int, hand: str, sens: float):
        self.cfg["virtual_phone_host"] = host
        self.cfg["virtual_phone_port"] = port
        self.cfg["virtual_phone_hand"] = hand
        self.cfg["virtual_phone_sensitivity"] = sens
        self.vphone.configure(host=host, port=port, hand=hand, sensitivity=sens)
        self.cfg_mgr.save()

    def get_vphone_readout(self) -> Dict[str, Any]:
        """Returns status readout of Virtual Phone emulator."""
        if self._vphone is None and not (
            self.cfg.get("virtual_phone_enabled", False)
            or self.cfg.get("benchmark_auto_record", False)
            or self.cfg.get("virtual_phone_auto_record", False)
        ):
            return {
                "initialized": False,
                "status_text": "Disabled (Virtual Phone)",
                "connected": False,
                "enabled": False,
                "song_name": "",
                "is_dancing": False,
                "is_logging": False,
            }

        vp = self.vphone
        return {
            "initialized": True,
            "status_text": vp.status_text,
            "connected": vp.connected,
            "enabled": vp.enabled,
            "song_name": vp.current_song,
            "is_dancing": vp.is_dancing,
            "is_logging": vp.is_logging,
        }

    def set_vphone_sensitivity(self, sens: float):
        self.cfg["virtual_phone_sensitivity"] = float(sens)
        self.vphone.configure(sensitivity=float(sens))
        self.cfg_mgr.save()

    def set_vphone_auto_record(self, enabled: bool):
        self.cfg["benchmark_auto_record"] = bool(enabled)
        self.cfg["virtual_phone_auto_record"] = bool(enabled)
        self.vphone.set_auto_record(bool(enabled))
        if enabled and not self.vphone.enabled:
            self.vphone.set_enabled(True)
        self.cfg_mgr.save()

    def set_vphone_adaptive(self, enabled: bool):
        self.cfg["virtual_phone_adaptive"] = bool(enabled)
        self.vphone.set_adaptive_calibration(bool(enabled))
        self.cfg_mgr.save()

    def set_vphone_enabled(self, enabled: bool):
        self.cfg["virtual_phone_enabled"] = bool(enabled)
        self.vphone.set_enabled(bool(enabled))
        self.cfg_mgr.save()

    def request_vphone_reconnect(self):
        self.vphone.request_reconnect()

    def discover_vphone_server_async(self, timeout: float = 1.2, callback=None):
        def worker():
            res = self.vphone.discover_server(timeout=timeout)
            if callback:
                callback(res[0] if res else "", res[1] if res else 0, res[2] if res else "")
        threading.Thread(target=worker, daemon=True, name="VPhoneDiscoverThread").start()

    def send_vphone_skip_finish(self):
        """Sends FTUE_FINISH shortcut packet for Just Dance tutorial."""
        if not self.vphone.enabled:
            self.vphone.set_enabled(True)
        self.vphone.send_input("FTUE_FINISH")
        self.vphone._ftue_until_ts = time.perf_counter() + 4.0

    def toggle_vphone_logging(self, source: str = "camera") -> Tuple[bool, Optional[str]]:
        """Toggles accelerometer telemetry recording. Returns (is_logging, path_if_saved)."""
        vp = self.vphone
        if not vp.is_logging:
            path = vp.set_logging(True, source=source)
            return True, path
        else:
            saved_path = vp.log_path
            vp.set_logging(False)
            return False, saved_path

    def cleanup(self):
        """Safely terminates all secondary device services without waking uninstantiated modules."""
        if self._vphone is not None:
            try:
                self._vphone.stop()
            except Exception:
                pass
        if self._ds4 is not None:
            try:
                self._ds4.disconnect()
            except Exception:
                pass
        if "sensor.phone_camera" in sys.modules:
            try:
                import sensor
                sensor.get_phone_camera_server().stop()
            except Exception:
                pass
