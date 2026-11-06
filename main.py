"""
Legacy Sensor Lite - Main Entry Point.
Supports Standard Webcams & PlayStation 4 Camera (PS4 Camera via PSCam4Win).
"""
import sys
import argparse
from pathlib import Path

# Setup paths for modular packages
BASE_DIR = Path(__file__).resolve().parent
for sub in [BASE_DIR, BASE_DIR / "sensor", BASE_DIR / "ui"]:
    if str(sub) not in sys.path:
        sys.path.insert(0, str(sub))

from sensor import ConfigManager, run_tracking_session
from ui import LegacySensorGUI

def run():
    parser = argparse.ArgumentParser(description="Legacy Sensor Lite")
    parser.add_argument("--start", action="store_true", help="Inicia o rastreamento diretamente sem abrir o menu GUI")
    parser.add_argument("--mode", choices=["pscam", "webcam"], help="Força o modo de câmera")
    parser.add_argument("--camera", type=int, help="Índice da câmera a utilizar")
    args = parser.parse_args()

    cfg_mgr = ConfigManager()
    cfg = cfg_mgr.config

    if args.mode:
        cfg["camera_mode"] = args.mode
    if args.camera is not None:
        cfg["camera_index"] = args.camera

    if args.start:
        print("[INFO] Iniciando rastreamento direto (--start)...")
        run_tracking_session(cfg)
    else:
        import tkinter as tk
        root = tk.Tk()
        app = LegacySensorGUI(root)
        root.mainloop()

if __name__ == "__main__":
    run()
