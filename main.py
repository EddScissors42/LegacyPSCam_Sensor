"""
Legacy Sensor Lite - Main Entry Point.
Supports Standard Webcams & PlayStation 4 Camera (PS4 Camera via PSCam4Win).
"""
import sys
import argparse
from pathlib import Path

# Setup root package path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from sensor import ConfigManager, run_tracking_session
from ui import LegacySensorGUI

def run():
    parser = argparse.ArgumentParser(description="Legacy Sensor Lite")
    parser.add_argument("--start", action="store_true", help="Start tracking directly without opening GUI menu")
    parser.add_argument("--mode", choices=["pscam", "webcam"], help="Force camera mode")
    parser.add_argument("--camera", type=int, help="Camera index to use")
    args = parser.parse_args()

    cfg_mgr = ConfigManager()
    cfg = cfg_mgr.config

    if args.mode:
        cfg["camera_mode"] = args.mode
    if args.camera is not None:
        cfg["camera_index"] = args.camera

    if args.start:
        print("[INFO] Starting direct tracking session (--start)...")
        run_tracking_session(cfg)
    else:
        import tkinter as tk
        root = tk.Tk()
        app = LegacySensorGUI(root)
        root.mainloop()

if __name__ == "__main__":
    run()
