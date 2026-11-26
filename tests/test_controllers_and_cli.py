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


if __name__ == "__main__":
    unittest.main()
