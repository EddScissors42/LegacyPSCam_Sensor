"""
Legacy PSCam Sensor - Main Entry Point.
Supports Standard Webcams & PlayStation 4 Camera (PS4 Camera via PSCam4Win).
"""
import sys
import argparse
from pathlib import Path

# Setup root package path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Provide lightweight mock for matplotlib if excluded or missing (MediaPipe drawing_utils requires it on import)
if "matplotlib" not in sys.modules:
    import types
    _m = types.ModuleType("matplotlib")
    _plt = types.ModuleType("matplotlib.pyplot")
    _m.pyplot = _plt
    sys.modules["matplotlib"] = _m
    sys.modules["matplotlib.pyplot"] = _plt

from sensor.config_manager import ConfigManager
from sensor.session_logger import get_session_logger
from version import WINDOW_TITLE, VERSION_STRING, APP_NAME

def run():
    # Initialize unified diagnostic session logger immediately on application boot
    logger = get_session_logger()
    logger.initialize()
    logger.log_system_environment()

    parser = argparse.ArgumentParser(description=WINDOW_TITLE)
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {VERSION_STRING}")
    parser.add_argument("--start", action="store_true", help="Start tracking directly without opening GUI menu")
    parser.add_argument("--mode", choices=["pscam", "webcam", "phone_cam", "ds4"], help="Force input mode (pscam, webcam, phone_cam, or ds4)")
    parser.add_argument("--camera", type=int, help="Camera index to use")
    args = parser.parse_args()

    cfg_mgr = ConfigManager()
    cfg = cfg_mgr.config

    if args.mode:
        cfg["camera_mode"] = args.mode
    if args.camera is not None:
        cfg["camera_index"] = args.camera

    if args.start:
        from sensor.tracking_session import run_tracking_session
        print("[INFO] Starting direct tracking session (--start)...")
        run_tracking_session(cfg)
    else:
        from ui import launch_app
        sys.exit(launch_app())

if __name__ == "__main__":
    run()
