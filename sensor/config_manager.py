"""
Configuration Manager for Legacy PSCam Sensor.
Saves and loads user preferences to/from config.json.
"""
import json
import os
from pathlib import Path

DEFAULT_CONFIG = {
    "camera_mode": "pscam",  # "pscam" or "webcam"
    "camera_index": 0,
    "pscam_preset": "1280x800 @ 60 FPS",
    "webcam_preset": "640x480 @ 30 FPS",
    "mirror_horizontal": True,
    "tracking_preset": "balanced",
    "smoothing_alpha": 0.55,
    "detection_confidence": 0.5,
    "target_height_m": 1.75,
    "hip_height_m": 1.0,
    "baseline_z_m": 2.2,
    "depth_gain": 0.65,
    "auto_calibrate": True,
    "launch_pscam_tray": True,
    "show_hud": True,
    "camera_x_slot_tracking": True,
    "camera_x_reverse_for_coach_selection": True,
    "camera_x_range_m": 2.2,
    "camera_x_deadzone": 0.025,
    "camera_x_smoothing": 0.42,
    "coach_assist_enabled": True,
    "coach_assist_multiplier": 1.25,
    "coach_assist_max_m": 1.20,
    "slot_snap_enabled": True,
    "slot_snap_gain": 1.25,
    "slot_snap_deadzone": 0.06,
    "face_follow_enabled": True,
    "face_follow_zoom": 1.22,
    "face_follow_smoothing": 0.20,
    "face_follow_y_bias": 0.06,
    "virtual_phone_enabled": False,
    "virtual_phone_host": "127.0.0.1",
    "virtual_phone_port": 8080,
    "virtual_phone_hand": "right",
    "virtual_phone_sensitivity": 1.2,
    "virtual_phone_name": "Legacy PSCam Phone"
}

PRESETS_PSCAM = [
    "1280x800 @ 60 FPS",
    "640x480 @ 60 FPS",
    "640x400 @ 60 FPS",
    "1280x800 @ 30 FPS",
    "640x480 @ 30 FPS"
]

PRESETS_WEBCAM = [
    "640x480 @ 30 FPS",
    "1280x720 @ 30 FPS",
    "1920x1080 @ 30 FPS",
    "640x480 @ 60 FPS",
    "1280x720 @ 60 FPS"
]

def parse_preset(preset_str):
    """
    Parses a string like '1280x800 @ 60 FPS' into (width, height, fps).
    """
    try:
        parts = preset_str.split('@')
        res_part = parts[0].strip()
        fps_part = parts[1].replace('FPS', '').strip()
        w, h = res_part.split('x')
        return int(w), int(h), int(fps_part)
    except Exception:
        return 640, 480, 30

class ConfigManager:
    def __init__(self, config_path=None):
        if config_path is None:
            parent_dir = Path(__file__).resolve().parent
            candidates = [parent_dir / "config.json", parent_dir.parent / "config.json"]
            self.config_path = next((c for c in candidates if c.exists()), parent_dir.parent / "config.json")
        else:
            self.config_path = Path(config_path)
        self.config = dict(DEFAULT_CONFIG)
        self.load()

    def load(self):
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.config.update(data)
            except Exception as e:
                print(f"[WARN] Failed to load config: {e}. Using defaults.")
        return self.config

    def save(self):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"[ERROR] Failed to save config: {e}")
            return False

    def get(self, key, default=None):
        return self.config.get(key, default)

    def set(self, key, value):
        self.config[key] = value
