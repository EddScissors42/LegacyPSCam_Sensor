"""
Main Application Controller (Facade) for Legacy PSCam Sensor.
Unifies Camera, Device and Session controllers into a clean, single-point API
for the PySide6 / Qt 6 user interface.
"""
import time
from typing import Optional, Callable, Tuple
from PySide6.QtCore import QObject, Signal, Slot

from sensor.config_manager import ConfigManager
from .camera_controller import CameraController
from .device_controller import DeviceController
from .session_controller import SessionController


class SensorAppController(QObject):
    """
    Central Controller Facade decoupling UI presentation from domain operations.
    Aggregates Camera, Device, and Session subsystems.
    """
    cameras_refreshed = Signal(list)
    pscam_state_changed = Signal(dict)
    tracking_finished = Signal(bool, str)

    def __init__(self, config_manager: Optional[ConfigManager] = None, parent=None):
        super().__init__(parent)
        self.cfg_mgr = config_manager or ConfigManager()
        self.cfg = self.cfg_mgr.config

        # Subsystem controllers
        self.camera = CameraController(self.cfg_mgr, parent=self)
        self.devices = DeviceController(self.cfg_mgr)
        self.session = SessionController(self.cfg_mgr)

        # Connect sub-controller signals
        self.camera.cameras_refreshed.connect(self._on_sub_cameras_refreshed)
        self.camera.pscam_state_changed.connect(self._on_sub_pscam_state_changed)

        self._is_closing = False

    @Slot(list)
    def _on_sub_cameras_refreshed(self, cams):
        self.cameras_refreshed.emit(cams)

    @Slot(dict)
    def _on_sub_pscam_state_changed(self, info):
        self.pscam_state_changed.emit(info)

    # =========================================================================
    # HIGH-LEVEL FACADE ACTIONS
    # =========================================================================
    def save_settings(self):
        """Persists current configuration to JSON file."""
        try:
            self.cfg_mgr.save()
        except Exception:
            pass

    def set_camera_mode(self, mode: str):
        """Switches device input mode (pscam, webcam, phone_cam, ds4) with warm-up coordination."""
        self.cfg["camera_mode"] = mode
        if mode in ("pscam", "webcam"):
            self.camera.schedule_warmup(300)
        else:
            self.camera.cancel_warmup()
            if mode == "phone_cam":
                self.devices.ensure_phone_cam_server_started()
            elif mode == "ds4":
                self.devices.get_ds4()
        self.save_settings()

    def validate_pre_tracking(self, mode: Optional[str] = None) -> tuple[bool, str, str]:
        """
        Validates hardware availability before starting live tracking.
        Returns (is_valid, error_title, error_message).
        """
        m = mode or self.cfg.get("camera_mode", "pscam")

        if m == "ds4":
            ds4 = self.devices.get_ds4()
            if not ds4.is_connected:
                perm = bool(self.cfg.get("ds4_permissive_mode", True))
                if not ds4.connect(permissive=perm):
                    return (
                        False,
                        "DualShock 4 Not Detected",
                        "DualShock 4 controller was not detected on this computer!\n\n"
                        "• Connect the DualShock 4 via USB cable, or\n"
                        "• Ensure the DualShock 4 is paired wirelessly via Windows Bluetooth settings.",
                    )
            return True, "", ""

        if m == "pscam":
            ps4_st = self.camera.get_ps4_state()
            if ps4_st.get("bootloader") or ps4_st.get("state") in ("NOT_INSTALLED", "DRIVER_STOPPED"):
                ok, msg = self.camera.initialize_ps4_camera()
                if not ok:
                    return False, "PlayStation Camera Initialization Error", msg
                time.sleep(0.5)
                self.camera.refresh_cameras()

            ps_cams = [c for c in self.camera.camera_list if c.is_pscam]
            cam_idx = self.cfg.get("camera_index", -1)
            is_valid_pscam = any(c.index == cam_idx and c.is_pscam for c in self.camera.camera_list)
            hw_connected = self.camera.is_pscam_connected()

            if (not ps_cams or not is_valid_pscam or cam_idx < 0) and not hw_connected:
                return (
                    False,
                    "PlayStation®Camera Not Connected",
                    "PlayStation®Camera was not detected on this computer!\n\n"
                    "• Ensure the PS4 Camera USB 3.0 Adapter is connected to a USB 3.0 port.\n"
                    "• Verify that the WinUSB driver association is active.",
                )
            if cam_idx < 0 and ps_cams:
                self.cfg["camera_index"] = ps_cams[0].index
            elif cam_idx < 0 and hw_connected:
                self.cfg["camera_index"] = 0
            return True, "", ""

        if m == "phone_cam":
            srv = self.devices.ensure_phone_cam_server_started()
            if not srv.is_client_connected:
                return (
                    False,
                    "Phone Camera Not Connected",
                    "No smartphone is currently connected to the Wi-Fi WebApp!\n\n"
                    "• Scan the QR Code on screen with your Android or iPhone camera.\n"
                    "• Ensure your phone is connected to the same Wi-Fi network as this PC.",
                )
            return True, "", ""

        # Webcam mode
        cam_idx = self.cfg.get("camera_index", -1)
        if cam_idx < 0 or not self.camera.camera_list:
            return (
                False,
                "No Camera Connected",
                "No webcam was detected on this computer.\n\n"
                "Please connect a camera before starting tracking.",
            )
        return True, "", ""

    def start_tracking(self, on_finished: Optional[Callable[[bool, str], None]] = None) -> bool:
        """Adopts pre-warmed camera and launches tracking session asynchronously."""
        if self.session.is_tracking_active:
            return False

        self.camera.set_tracking_active(True)
        self.save_settings()

        prewarmed = self.camera.take_prewarmed_camera()

        def _handle_finished(success: bool, err_msg: str):
            self.camera.set_tracking_active(False)
            self.tracking_finished.emit(success, err_msg)
            if on_finished:
                try:
                    on_finished(success, err_msg)
                except Exception:
                    pass
            # Re-schedule camera warm-up for next song if in optical mode
            if self.cfg.get("camera_mode") in ("pscam", "webcam"):
                self.camera.schedule_warmup(500)

        started = self.session.start_tracking(
            prewarmed_camera=prewarmed,
            on_finished=_handle_finished,
        )
        if not started:
            self.camera.set_tracking_active(False)
        return started

    def stop_tracking(self):
        """Terminates active tracking session."""
        self.session.stop_tracking()
        self.camera.set_tracking_active(False)

    def periodic_check(self) -> dict:
        """
        Executes non-blocking periodic diagnostics (PnP changes, PS4 state transitions).
        Called by UI timer (1000ms).
        """
        if self.session.is_tracking_active:
            return {}

        mode = self.cfg.get("camera_mode", "pscam")
        hw_changed = self.camera.check_hardware_changes()
        ps_changed, ps_info = self.camera.check_ps4_state_changed()

        if hw_changed:
            self.camera.refresh_cameras_async()

        res = {
            "hw_changed": hw_changed,
            "ps_changed": ps_changed,
            "ps_info": ps_info,
            "mode": mode,
        }
        return res

    def cleanup(self):
        """Deterministic, graceful teardown of all application subsystems."""
        self._is_closing = True
        self.camera.set_closing(True)
        self.camera.cancel_warmup(sync=True)
        self.session.cleanup()
        self.devices.cleanup()
        try:
            from sensor.session_logger import get_session_logger
            get_session_logger().close()
        except Exception:
            pass
