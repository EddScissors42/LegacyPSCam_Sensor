"""
Session Controller for Legacy PSCam Sensor.
Orchestrates the live dance tracking loop, Kinect in-memory emulator,
and Windows Shared Memory IPC (KinectBridge).
Decoupled from Qt UI presentation.
"""
import threading
from typing import Optional, Callable

from sensor.config_manager import ConfigManager
from sensor.kinect_shared_memory import close_kinect_bridge
from sensor.kinect_emulator import get_kinect_emulator
from sensor import tracking_session


class SessionController:
    """
    Manages the lifecycle of live tracking sessions and background IPC daemons.
    """
    def __init__(self, config_manager: Optional[ConfigManager] = None):
        self.cfg_mgr = config_manager or ConfigManager()
        self.cfg = self.cfg_mgr.config

        self.is_tracking_active = False
        self._tracking_stop_event = threading.Event()
        self.kinect_emulator = None

    def start_kinect_emulator(self):
        """Starts the zero-file-replacement in-memory Kinect emulator daemon."""
        self.cfg["emulate_kinect_enabled"] = True
        self.kinect_emulator = get_kinect_emulator(self.cfg)
        self.kinect_emulator.enabled = True
        self.kinect_emulator.start()

    def start_tracking(
        self,
        prewarmed_camera=None,
        on_finished: Optional[Callable[[bool, str], None]] = None,
    ) -> bool:
        """
        Starts tracking session asynchronously on a background thread.
        Adopts the pre-warmed camera instance if available for instant 0s start.
        """
        if self.is_tracking_active:
            return False

        self.is_tracking_active = True
        self._tracking_stop_event.clear()

        def tracking_worker():
            success = False
            err_msg = ""
            try:
                success = tracking_session.run_tracking_session(
                    self.cfg,
                    stop_event=self._tracking_stop_event,
                    prewarmed_camera=prewarmed_camera,
                )
            except Exception as e:
                err_msg = str(e)
            finally:
                self.is_tracking_active = False
                if on_finished:
                    on_finished(success, err_msg)

        threading.Thread(target=tracking_worker, daemon=True, name="TrackingSessionThread").start()
        return True

    def stop_tracking(self):
        """Signals the live tracking loop to terminate gracefully."""
        self._tracking_stop_event.set()

    def cleanup(self):
        """Releases all IPC shared memory channels and emulator hooks."""
        self.stop_tracking()
        if self.kinect_emulator is not None:
            try:
                self.kinect_emulator.stop()
            except Exception:
                pass
            self.kinect_emulator = None
        try:
            close_kinect_bridge()
        except Exception:
            pass
