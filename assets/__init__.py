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
ICON_MODE_BALANCED_PATH = ICONS_DIR / "mode_balanced.svg" if (ICONS_DIR / "mode_balanced.svg").exists() else ASSETS_DIR / "mode_balanced.svg"
ICON_MODE_COMPETITIVE_PATH = ICONS_DIR / "mode_competitive.svg" if (ICONS_DIR / "mode_competitive.svg").exists() else ASSETS_DIR / "mode_competitive.svg"
ICON_MODE_STABLE_PATH = (
    ICONS_DIR / "mode_stable.svg"
    if (ICONS_DIR / "mode_stable.svg").exists()
    else (ICONS_DIR / "mode_.svg" if (ICONS_DIR / "mode_.svg").exists() else ASSETS_DIR / "mode_.svg")
)
ICON_LAB_PATH = ICONS_DIR / "lab.svg" if (ICONS_DIR / "lab.svg").exists() else ASSETS_DIR / "lab.svg"
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
    "ICON_ARROW_DOWN_PATH",
    "MODELS_DIR",
    "MODEL_POSE_PATH",
]
