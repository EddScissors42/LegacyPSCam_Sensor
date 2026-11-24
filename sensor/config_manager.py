"""
Configuration Manager for Legacy PSCam Sensor.
Saves and loads user preferences to/from config.json.
"""
import sys
import json
import os
import shutil
from pathlib import Path
from typing import Optional

DEFAULT_CONFIG = {
    "camera_mode": "pscam",  # "pscam", "webcam", "phone_cam", or "ds4"
    "camera_index": 0,
    "camera_orientation": 0,
    "ps4_camera_backend": "native",  # "native" (WinUSB direct) or "pscam4win" (legacy fallback)
    "ps4_eye": "right",              # "right" (default) or "left"
    "pscam_preset": "1280x800 @ 60 FPS",
    "webcam_preset": "640x480 @ 30 FPS",
    "phone_cam_preset": "640x480 @ 30 FPS",
    "phone_cam_port": 8443,
    "phone_cam_lens": "user",
    "phone_cam_processing_mode": "pc_video",
    "mirror_horizontal": True,
    "tracking_preset": "competitive",
    "pose_model": "lite",
    "smoothing_alpha": 0.75,
    "detection_confidence": 0.50,
    "max_players": 1,
    "infer_max_w_2p": 640,
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
    "face_follow_spin_fallback": True,
    "face_follow_adaptive_zoom": False,
    "person_lock_enabled": True,
    "inertial_coasting_enabled": True,
    "inertial_coasting_max_ms": 250,
    "dancer_lock_enabled": True,
    "dancer_lock_color_thresh": 0.35,
    "dancer_lock_roi_focus": True,
    "arm_raise_gesture_enabled": True,
    "arm_raise_hold_seconds": 2.0,
    "virtual_phone_enabled": False,
    "virtual_phone_host": "127.0.0.1",
    "virtual_phone_port": 8080,
    "virtual_phone_hand": "right",
    "virtual_phone_sensitivity": 1.0,
    "virtual_phone_name": "Legacy PSCam Phone",
    "virtual_phone_auto_record": False,
    "virtual_phone_adaptive": False,
    "ds4_hand": "right",
    "ds4_sensitivity": 1.0,
    "ds4_permissive_mode": True,
    "benchmark_auto_record": False,
    "stereo_mode": "sparse_metric",
    "emulate_kinect_enabled": True
}

PRESETS_PSCAM = [
    "1280x800 @ 60 FPS",
    "1280x800 @ 30 FPS",
    "1280x800 @ 15 FPS",
    "640x400 @ 120 FPS",
    "640x400 @ 60 FPS",
    "640x400 @ 30 FPS",
    "320x192 @ 240 FPS",
    "320x192 @ 120 FPS",
    "320x192 @ 60 FPS",
    "640x480 @ 60 FPS",
    "640x480 @ 30 FPS"
]

PRESETS_WEBCAM = [
    "640x480 @ 30 FPS",
    "1280x720 @ 30 FPS",
    "1920x1080 @ 30 FPS",
    "640x480 @ 60 FPS",
    "1280x720 @ 60 FPS"
]

PRESETS_PHONE_CAM = [
    "640x480 @ 30 FPS",
    "640x480 @ 60 FPS",
    "1280x720 @ 30 FPS",
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


def is_portable_mode() -> bool:
    """
    Checks whether the application should run in portable mode.
    Portable mode is enabled if:
    1. '--portable' is in sys.argv, or
    2. Environment variable 'LEGACY_PSCAM_PORTABLE' is set ('1', 'true'), or
    3. A file named 'portable.txt' or '.portable' exists next to the executable (or project root).
    """
    if "--portable" in sys.argv or os.environ.get("LEGACY_PSCAM_PORTABLE", "").strip().lower() in ("1", "true"):
        return True

    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
    else:
        exe_dir = Path(__file__).resolve().parent.parent

    return (exe_dir / "portable.txt").exists() or (exe_dir / ".portable").exists()


def get_app_data_dir(portable: Optional[bool] = None) -> Path:
    """
    Returns the dedicated application directory for user configuration and logs.
    In standard mode (default):
      - Windows: %APPDATA%/LegacyPSCam_Sensor (e.g. C:/Users/<User>/AppData/Roaming/LegacyPSCam_Sensor)
      - Non-Windows / Fallback: ~/.config/LegacyPSCam_Sensor
    In portable mode:
      - Next to the executable (frozen) or project root (dev).
    Ensures the directory exists.
    """
    if portable is None:
        portable = is_portable_mode()

    if portable:
        if getattr(sys, "frozen", False):
            base = Path(sys.executable).resolve().parent
        else:
            base = Path(__file__).resolve().parent.parent
        return base

    appdata = os.environ.get("APPDATA")
    if appdata:
        base = Path(appdata) / "LegacyPSCam_Sensor"
    else:
        base = Path.home() / ".config" / "LegacyPSCam_Sensor"

    try:
        base.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"[WARN] Failed to create AppData directory at {base}: {e}. Falling back to home.")
        base = Path.home() / ".legacy_pscam_sensor"
        base.mkdir(parents=True, exist_ok=True)

    return base


def get_logs_dir(portable: Optional[bool] = None) -> Path:
    """
    Returns the dedicated directory for diagnostic session logs and telemetry CSVs.
    Always located in <AppData>/logs (or <PortableDir>/logs).
    Ensures the directory exists.
    """
    logs_dir = get_app_data_dir(portable=portable) / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def get_models_dir(portable: Optional[bool] = None) -> Path:
    """
    Returns the persistent directory for cached MediaPipe AI `.task` models.
    Always located in <AppData>/models (or <PortableDir>/models).
    Ensures the directory exists.
    """
    models_dir = get_app_data_dir(portable=portable) / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    return models_dir


def get_config_path(portable: Optional[bool] = None) -> Path:
    """
    Returns the canonical path for config.json.
    If config.json does not yet exist in the AppData directory, attempts to seed it
    from candidate local/bundled config.json files (or writes DEFAULT_CONFIG).
    """
    app_data_dir = get_app_data_dir(portable=portable)
    target_config = app_data_dir / "config.json"

    if target_config.exists():
        return target_config

    # Seed / migrate from local template if available
    try:
        candidates = []
        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).resolve().parent
            candidates.append(exe_dir / "config.json")
            if hasattr(sys, "_MEIPASS"):
                candidates.append(Path(sys._MEIPASS) / "config.json")
        else:
            proj_root = Path(__file__).resolve().parent.parent
            candidates.append(proj_root / "config.json")
            candidates.append(Path(__file__).resolve().parent / "config.json")

        seed_file = next((c for c in candidates if c.exists() and c.resolve() != target_config.resolve()), None)
        if seed_file:
            shutil.copy2(seed_file, target_config)
        else:
            with open(target_config, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_CONFIG, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"[WARN] Failed to seed initial config at {target_config}: {e}")

    return target_config


class ConfigManager:
    def __init__(self, config_path=None):
        if config_path is None:
            self.config_path = get_config_path()
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
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
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
