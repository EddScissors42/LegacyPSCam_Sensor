"""
Legacy PSCam Sensor - Assets and Visual Media Package.
"""
from pathlib import Path

ASSETS_DIR = Path(__file__).resolve().parent
ICONS_DIR = ASSETS_DIR / "icons"
FONTS_DIR = ASSETS_DIR / "fonts"

ICON_PSCAMERA_PATH = ICONS_DIR / "IconePSCAMERA.png" if (ICONS_DIR / "IconePSCAMERA.png").exists() else ASSETS_DIR / "IconePSCAMERA.png"
ICON_SETTINGS_PATH = ICONS_DIR / "settings.svg" if (ICONS_DIR / "settings.svg").exists() else ASSETS_DIR / "settings.svg"
ICON_SLIDERS_PATH = ICONS_DIR / "sliders.svg" if (ICONS_DIR / "sliders.svg").exists() else ASSETS_DIR / "sliders.svg"

MODELS_DIR = ASSETS_DIR.parent / "models"
MODEL_POSE_PATH = MODELS_DIR / "pose_landmarker_lite.task"

__all__ = [
    "ASSETS_DIR",
    "ICONS_DIR",
    "FONTS_DIR",
    "ICON_PSCAMERA_PATH",
    "ICON_SETTINGS_PATH",
    "ICON_SLIDERS_PATH",
    "MODELS_DIR",
    "MODEL_POSE_PATH",
]
