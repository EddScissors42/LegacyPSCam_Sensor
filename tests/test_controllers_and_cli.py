"""
Modular unit tests for CLI entry point (`main.py`), lazy package exports (`sensor`),
and UI controllers (`CameraController`, `DeviceController`, `SessionController`) without hardware.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import sensor
import version
from sensor.config_manager import ConfigManager, DEFAULT_CONFIG, get_app_data_dir, is_portable_mode


class TestControllersAndCLI(unittest.TestCase):
    def test_cli_version_and_help(self):
        env = dict(os.environ)
        with tempfile.TemporaryDirectory(prefix="legacy_cli_test_") as td:
            env["APPDATA"] = td
            env.pop("LEGACY_PSCAM_PORTABLE", None)

            proc_ver = subprocess.run(
                [sys.executable, str(ROOT_DIR / "main.py"), "--version"],
                capture_output=True,
                text=True,
                timeout=15,
                env=env,
            )
            self.assertEqual(proc_ver.returncode, 0, msg=proc_ver.stderr)
            self.assertIn(version.__version__, proc_ver.stdout)
            self.assertIn(version.APP_NAME, proc_ver.stdout)

            proc_help = subprocess.run(
                [sys.executable, str(ROOT_DIR / "main.py"), "--help"],
                capture_output=True,
                text=True,
                timeout=15,
                env=env,
            )
            self.assertEqual(proc_help.returncode, 0, msg=proc_help.stderr)
            self.assertIn("--portable", proc_help.stdout)
            self.assertIn("--mode", proc_help.stdout)
            self.assertIn("--camera", proc_help.stdout)

    def test_portable_mode_env_flag(self):
        prev = os.environ.get("LEGACY_PSCAM_PORTABLE")
        try:
            os.environ["LEGACY_PSCAM_PORTABLE"] = "1"
            self.assertTrue(is_portable_mode())
            self.assertEqual(get_app_data_dir(portable=True), ROOT_DIR)
        finally:
            if prev is None:
                os.environ.pop("LEGACY_PSCAM_PORTABLE", None)
            else:
                os.environ["LEGACY_PSCAM_PORTABLE"] = prev

    def test_sensor_lazy_exports_complete(self):
        for submod in ("model_manager", "player_reid", "qr_encoder", "tls_manager", "vphone_protocol"):
            mod = getattr(sensor, submod)
            self.assertIsNotNone(mod)
        for sym in ("avg", "lerp", "suppress_duplicate_poses", "QRCodeGenerator", "SelfSignedTLSManager"):
            self.assertIn(sym, sensor.__all__)
            self.assertIsNotNone(getattr(sensor, sym))

    def test_controllers_smoke_without_hardware(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from ui.controllers import SensorAppController, CameraController, DeviceController, SessionController

        _ = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory(prefix="legacy_ctrl_test_") as td:
            cfg_mgr = ConfigManager(config_path=Path(td) / "config.json")
            cfg_mgr.set("camera_mode", "webcam")
            cfg_mgr.set("phone_cam_port", 0)

            cam_ctrl = CameraController(cfg_mgr)
            self.assertFalse(cam_ctrl.is_camera_accessible())
            self.assertIsInstance(cam_ctrl.get_hardware_snapshot(), tuple)

            dev_ctrl = DeviceController(cfg_mgr)
            self.assertFalse(dev_ctrl.is_connecting_ds4)
            self.assertIsInstance(dev_ctrl.get_ds4_readout(), dict)

            sess_ctrl = SessionController(cfg_mgr)
            self.assertFalse(sess_ctrl.is_tracking_active)

            app_ctrl = SensorAppController(config_manager=cfg_mgr)
            app_ctrl.camera.camera_list = []
            ok, err_title, err_msg = app_ctrl.validate_pre_tracking()
            self.assertFalse(ok)
            self.assertTrue(len(err_title) > 0 and len(err_msg) > 0)

            app_ctrl.cleanup()
            sess_ctrl.cleanup()
            dev_ctrl.cleanup()
            cam_ctrl.set_closing(True)

    def test_gui_qt_mixins_and_signal_slot_wiring(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from ui.gui_qt import LegacySensorQtGUI
        from ui.mixins import (
            UIDeviceReadoutMixin,
            UICameraHandlersMixin,
            UIPhoneHandlersMixin,
            UIDS4VPhoneHandlersMixin,
            UITrackingHandlersMixin,
        )

        for mixin_cls in (
            UIDeviceReadoutMixin,
            UICameraHandlersMixin,
            UIPhoneHandlersMixin,
            UIDS4VPhoneHandlersMixin,
            UITrackingHandlersMixin,
        ):
            self.assertTrue(issubclass(LegacySensorQtGUI, mixin_cls))

        _ = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory(prefix="legacy_gui_mixin_test_") as td:
            prev_appdata = os.environ.get("APPDATA")
            os.environ["APPDATA"] = td
            try:
                app_dir = Path(td) / "LegacyPSCam_Sensor"
                app_dir.mkdir(parents=True, exist_ok=True)
                import json
                seed = dict(DEFAULT_CONFIG)
                seed["phone_cam_port"] = 0
                (app_dir / "config.json").write_text(json.dumps(seed), encoding="utf-8")

                win = LegacySensorQtGUI(auto_discover=False)
                try:
                    # Emit cross-mixin signals to verify PySide6 @Slot binding on all mixins
                    win.cameras_refreshed_signal.emit([])
                    win.model_download_signal.emit("full", 50, "downloading")
                    self.assertIn("50%", win.lbl_model_dl_status.text())
                    win.model_download_signal.emit("full", 100, "done")
                    self.assertIn("Ready", win.lbl_model_dl_status.text())
                    win._select_calib_preset("competitive")
                    self.assertEqual(win.cfg["tracking_preset"], "competitive")
                finally:
                    win.controller.cleanup()
                    win.close()
            finally:
                if prev_appdata is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = prev_appdata

    def test_pages_package_and_ds4_scoring_bridge_visibility(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from ui.gui_qt import LegacySensorQtGUI
        from ui.pages import (
            UIPagesMixin,
            UIVideoPageMixin,
            UITrackingPageMixin,
            UIExperimentalPageMixin,
            UIDS4PageMixin,
        )

        for page_mixin in (
            UIVideoPageMixin,
            UITrackingPageMixin,
            UIExperimentalPageMixin,
            UIDS4PageMixin,
        ):
            self.assertTrue(issubclass(UIPagesMixin, page_mixin))
            self.assertTrue(issubclass(LegacySensorQtGUI, page_mixin))

        _ = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory(prefix="legacy_ds4_sb_test_") as td:
            prev_appdata = os.environ.get("APPDATA")
            os.environ["APPDATA"] = td
            try:
                app_dir = Path(td) / "LegacyPSCam_Sensor"
                app_dir.mkdir(parents=True, exist_ok=True)
                import json
                seed = dict(DEFAULT_CONFIG)
                seed["phone_cam_port"] = 0
                (app_dir / "config.json").write_text(json.dumps(seed), encoding="utf-8")

                win = LegacySensorQtGUI(auto_discover=False)
                try:
                    # Scoring Bridge MUST live inside ds4_info_frame so it only shows when DS4 is connected
                    self.assertIs(win.scoring_bridge_box.parent(), win.ds4_info_frame)
                    self.assertTrue(win.ds4_info_frame.isHidden())
                    self.assertFalse(win.ds4_disconnected_box.isHidden())
                    # Switching to ds4 mode without controller keeps ds4_info_frame (and Scoring Bridge) hidden
                    win._set_mode("ds4")
                    win._update_ds4_ui_readout()
                    self.assertTrue(win.ds4_info_frame.isHidden())
                    self.assertFalse(win.scoring_bridge_box.isVisible())
                finally:
                    win.controller.cleanup()
                    win.close()
            finally:
                if prev_appdata is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = prev_appdata

    def test_camera_cancel_warmup_nonblocking_and_serialized(self):
        import time
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from ui.controllers import CameraController

        _ = QApplication.instance() or QApplication([])

        class _SlowFakeCamera:
            def __init__(self):
                self.released = False

            def release(self):
                time.sleep(0.35)
                self.released = True

        with tempfile.TemporaryDirectory(prefix="legacy_warmup_cancel_test_") as td:
            cfg_mgr = ConfigManager(config_path=Path(td) / "config.json")
            cam_ctrl = CameraController(cfg_mgr)
            fake_cam = _SlowFakeCamera()
            cam_ctrl._prewarmed_camera = fake_cam

            t0 = time.perf_counter()
            cam_ctrl.cancel_warmup(sync=False)
            elapsed = time.perf_counter() - t0

            # Must return immediately without blocking the Qt UI thread
            self.assertLess(elapsed, 0.05, f"cancel_warmup(sync=False) blocked UI thread for {elapsed*1000:.1f}ms")
            self.assertFalse(fake_cam.released, "Slow camera release should still be running in background")

            # take_prewarmed_camera() must serialize behind _closer_thread so DirectShow handles never collide
            taken = cam_ctrl.take_prewarmed_camera()
            self.assertIsNone(taken)
            self.assertTrue(fake_cam.released, "take_prewarmed_camera() did not wait for closer thread to finish")
            cam_ctrl.set_closing(True)


if __name__ == "__main__":
    unittest.main()
