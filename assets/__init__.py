"""
Legacy PSCam Sensor - Assets and Visual Media Package.
"""
from pathlib import Path

ASSETS_DIR = Path(__file__).resolve().parent
ICONS_DIR = ASSETS_DIR / "icons"
FONTS_DIR = ASSETS_DIR / "fonts"

ICON_PSCAMERA_PATH = ICONS_DIR / "IconePSCAMERA.png"
ICON_SETTINGS_PATH = ICONS_DIR / "settings.svg"
ICON_SLIDERS_PATH = ICONS_DIR / "sliders.svg"
ICON_MODE_BALANCED_PATH = ICONS_DIR / "mode_balanced.svg"
ICON_MODE_COMPETITIVE_PATH = ICONS_DIR / "mode_competitive.svg"
ICON_MODE_STABLE_PATH = ICONS_DIR / "mode_stable.svg"
ICON_LAB_PATH = ICONS_DIR / "lab.svg"
ICON_CAMERA_PATH = ICONS_DIR / "camera.svg"
ICON_ARROW_DOWN_PATH = ICONS_DIR / "arrow_down.png" if (ICONS_DIR / "arrow_down.png").exists() else ICONS_DIR / "arrow_down.svg"

MODELS_DIR = ASSETS_DIR.parent / "models"
MODEL_POSE_PATH = MODELS_DIR / "pose_landmarker_lite.task"

__all__ = [
    "ASSETS_DIR",
    "ICONS_DIR",
    "FONTS_DIR",
    "ICON_PSCAMERA_PATH",
    "ICON_SETTINGS_PATH",
    "ICON_SLIDERS_PATH",
    "ICON_MODE_BALANCED_PATH",
    "ICON_MODE_COMPETITIVE_PATH",
    "ICON_MODE_STABLE_PATH",
    "ICON_LAB_PATH",
    "ICON_CAMERA_PATH",
    "ICON_ARROW_DOWN_PATH",
    "MODELS_DIR",
    "MODEL_POSE_PATH",
]
