"""
Device Controller for Legacy PSCam Sensor.
Handles secondary peripherals: Phone Camera WebApp and DualShock 4 Controller
(with native PlayStation Move ZCM2 emulation).
Decoupled from Qt UI presentation. Fully lazy via PEP 562.
"""
import sys
import math
import threading
import time
from typing import Optional, Tuple, Dict, Any, Callable

from sensor.config_manager import ConfigManager, parse_preset


class DeviceController:
    """
    Manages non-optical hardware and network inputs:
    - Smartphone Camera WebApp (Wi-Fi HTTPS/WSS + QR Code)
    - DualShock 4 & compatible clone controllers (Bluetooth/USB HID -> PS Move ZCM2)
    """
    def __init__(self, config_manager: Optional[ConfigManager] = None):
        self.cfg_mgr = config_manager or ConfigManager()
        self.cfg = self.cfg_mgr.config

        # Lazy references & non-blocking DS4 probe/connect state
        self._ds4 = None
        self._ds4_conn_lock = threading.Lock()
        self._is_connecting_ds4 = False
        self._ds4_probe_lock = threading.Lock()
        self._ds4_probe_cache: Dict[str, Any] = {"is_connected": False, "device_present": False}
        self._ds4_probe_ts: float = 0.0
        self._ds4_probe_inflight: bool = False
        self._last_phone_cam_conn = None

    @property
    def is_connecting_ds4(self) -> bool:
        with self._ds4_conn_lock:
            return self._is_connecting_ds4

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

    def list_phone_cam_ips(self) -> Tuple[list, str]:
        """Returns (ranked_interfaces, active_ip) for the Phone Camera QR selector."""
        srv = self.ensure_phone_cam_server_started()
        items = srv.list_local_lan_ips()
        active_ip = srv.get_active_ip()
        return items, active_ip

    def set_phone_cam_ip(self, ip: str) -> str:
        """Selects which local LAN IPv4 address should be used for Phone Camera QR pairing."""
        srv = self.ensure_phone_cam_server_started()
        return srv.set_preferred_ip(ip)

    def get_phone_cam_firewall_status(self) -> Dict[str, Any]:
        """Checks whether Windows Defender Firewall already allows inbound TCP for Phone Camera."""
        srv = self.ensure_phone_cam_server_started()
        return srv.check_windows_firewall_rule(srv.actual_port)

    def allow_phone_cam_firewall_async(self, callback: Optional[Callable[[bool, str], None]] = None):
        """Adds the Windows Defender Firewall inbound rule on a background thread (never blocks Qt UI)."""
        srv = self.ensure_phone_cam_server_started()
        port = srv.actual_port

        def worker():
            ok, msg = srv.ensure_windows_firewall_rule(port)
            if callback:
                callback(ok, msg)

        threading.Thread(target=worker, daemon=True, name="PhoneCamFirewallThread").start()

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

    def disconnect_phone_cam(self, rotate_token: bool = True):
        import sensor
        srv = sensor.get_phone_camera_server()
        srv.disconnect_client(rotate_token=rotate_token)

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
            "client_lens": srv.client_lens,
            "width": srv.actual_w,
            "height": srv.actual_h,
            "fps": srv.measured_fps,
            "target_fps": srv.target_fps,
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
        ds4.sync_lightbar = bool(self.cfg.get("ds4_sync_lightbar", True))

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

            rate = st.sample_rate_hz if (time.perf_counter() - getattr(st, "last_update_ts", 0.0) < 1.0) else 0.0

            return {
                "is_connected": True,
                "controller_name": ctrl_name,
                "connection_type": conn_type,
                "sample_rate_hz": rate,
                "battery_pct": st.battery_pct,
                "is_charging": st.is_charging,
                "charging_str": charging_str,
                "imu_frozen": imu_frozen,
                "accel_g": (ax, ay, az),
                "total_g": tot,
                "buttons": act_btns,
            }

        # Controller is not connected: return cached snapshot immediately (<0.01ms on Qt UI thread)
        # and refresh Win32 SetupAPI HID enumeration asynchronously at most once per 1.0s.
        self._trigger_ds4_probe_async()
        with self._ds4_probe_lock:
            return dict(self._ds4_probe_cache)

    def _trigger_ds4_probe_async(self, min_interval_s: float = 1.0) -> None:
        now = time.perf_counter()
        with self._ds4_probe_lock:
            if self._ds4_probe_inflight or (now - self._ds4_probe_ts) < min_interval_s:
                return
            self._ds4_probe_inflight = True
            perm = bool(self.cfg.get("ds4_permissive_mode", True))

        def _probe_worker():
            result: Dict[str, Any] = {"is_connected": False, "device_present": False}
            try:
                from sensor.ds4_controller import find_ds4_devices, detect_controller_name
                paths = find_ds4_devices(permissive=perm)
                if paths:
                    is_usb = any(
                        "bth" not in p.lower() and "bluetooth" not in p.lower() and "00001124" not in p.lower()
                        for p in paths
                    )
                    detected_type = "on USB" if is_usb else "via Bluetooth"
                    detected_name = detect_controller_name(paths[0])
                    result = {
                        "is_connected": False,
                        "device_present": True,
                        "controller_name": detected_name,
                        "connection_type": detected_type,
                    }
            except Exception:
                pass
            finally:
                with self._ds4_probe_lock:
                    self._ds4_probe_cache = result
                    self._ds4_probe_ts = time.perf_counter()
                    self._ds4_probe_inflight = False

        threading.Thread(target=_probe_worker, daemon=True, name="DS4ProbeThread").start()

    def connect_ds4_async(self, callback: Optional[Callable[[bool], None]] = None):
        """Asynchronously attempts connection to DualShock 4 (single source of truth for connection state)."""
        with self._ds4_conn_lock:
            if self._is_connecting_ds4:
                return
            self._is_connecting_ds4 = True
        perm = bool(self.cfg.get("ds4_permissive_mode", True))

        def worker():
            ok = False
            try:
                ds4 = self.get_ds4()
                if ds4.is_connected:
                    ok = True
                else:
                    ok = ds4.connect(permissive=perm)
                    if ok:
                        ds4.trigger_rumble(small=140, large=80, duration_sec=0.15)
            except Exception:
                ok = False
            finally:
                with self._ds4_conn_lock:
                    self._is_connecting_ds4 = False
            if callback:
                try:
                    callback(ok)
                except Exception:
                    pass

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

    def set_ds4_sync_lightbar(self, enabled: bool):
        self.cfg["ds4_sync_lightbar"] = bool(enabled)
        self.get_ds4().sync_lightbar = bool(enabled)
        self.cfg_mgr.save()

    def get_psmove_readout(self) -> Dict[str, Any]:
        """Returns live PlayStation Move (ZCM2) emulator link status and sphere color feedback."""
        from sensor.kinect_emulator import get_kinect_emulator
        from sensor.psmove_shared_memory import get_psmove_bridge

        emu_st = get_kinect_emulator(self.cfg).get_status()
        fb = get_psmove_bridge().read_feedback()
        ds4 = self._ds4
        streaming = bool(ds4 is not None and ds4.is_connected and ds4.psmove_streaming)
        game_conn = bool(fb.get("game_connected", False)) and streaming
        sphere_rgb = tuple(fb.get("led_rgb", (0, 67, 156))) if game_conn else (0, 67, 156)
        game_name = emu_st.get("game_name", "")

        if game_conn:
            status_text = f"Connected to {game_name or 'Just Dance'} (ZCM2 Active)"
        elif streaming and emu_st.get("psmove_hooked"):
            status_text = f"Streaming to {game_name or 'Just Dance'} — Discovering PS Move..."
        elif streaming:
            status_text = "Streaming Ready — Waiting for Just Dance..."
        elif emu_st.get("psmove_hooked"):
            status_text = f"Hook Ready ({game_name}) — Click START CONTROLLER (DS4)"
        else:
            status_text = "Ready — Click START CONTROLLER (DS4) to emulate PS Move"

        return {
            "streaming": streaming,
            "game_connected": game_conn,
            "psmove_hooked": bool(emu_st.get("psmove_hooked", False)),
            "game_name": game_name,
            "sphere_rgb": sphere_rgb,
            "rumble": int(fb.get("rumble", 0)) if game_conn else 0,
            "status_text": status_text,
        }

    def cleanup(self):
        """Safely terminates all secondary device services without waking uninstantiated modules."""
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
