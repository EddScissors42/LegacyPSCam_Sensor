"""
Legacy PSCam Sensor - Assets and Visual Media Package.
"""
import sys
from pathlib import Path

if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    ROOT_DIR = Path(sys._MEIPASS)
    ASSETS_DIR = ROOT_DIR / "assets"
    MODELS_DIR = ROOT_DIR / "models"
else:
    ASSETS_DIR = Path(__file__).resolve().parent
    MODELS_DIR = ASSETS_DIR.parent / "models"

ICONS_DIR = ASSETS_DIR / "icons"
FONTS_DIR = ASSETS_DIR / "fonts"

ICON_APP_ICO_PATH = ICONS_DIR / "app_icon.ico" if (ICONS_DIR / "app_icon.ico").exists() else None
ICON_PSCAMERA_PATH = ICONS_DIR / "IconePSCAMERA.png"
ICON_SETTINGS_PATH = ICONS_DIR / "settings.svg"
ICON_SLIDERS_PATH = ICONS_DIR / "sliders.svg"
ICON_MODE_BALANCED_PATH = ICONS_DIR / "mode_balanced.svg"
ICON_MODE_COMPETITIVE_PATH = ICONS_DIR / "mode_competitive.svg"
ICON_MODE_STABLE_PATH = ICONS_DIR / "mode_stable.svg"
ICON_LAB_PATH = ICONS_DIR / "lab.svg"
ICON_CAMERA_PATH = ICONS_DIR / "camera.svg"
ICON_WEBCAM_PATH = ICONS_DIR / "webcam.svg"
ICON_ARROW_DOWN_PATH = ICONS_DIR / "arrow_down.png" if (ICONS_DIR / "arrow_down.png").exists() else ICONS_DIR / "arrow_down.svg"
ICON_DUALSHOCK4_PATH = ICONS_DIR / "officialdualshock.png" if (ICONS_DIR / "officialdualshock.png").exists() else ICONS_DIR / "dualshock4.jpg"
ICON_CONTROLLER_PATH = ICONS_DIR / "controller.svg"

MODELS_DIR = ASSETS_DIR.parent / "models"
MODEL_POSE_PATH = MODELS_DIR / "pose_landmarker_lite.task"

__all__ = [
    "ASSETS_DIR",
    "ICONS_DIR",
    "FONTS_DIR",
    "ICON_APP_ICO_PATH",
    "ICON_PSCAMERA_PATH",
    "ICON_SETTINGS_PATH",
    "ICON_SLIDERS_PATH",
    "ICON_MODE_BALANCED_PATH",
    "ICON_MODE_COMPETITIVE_PATH",
    "ICON_MODE_STABLE_PATH",
    "ICON_LAB_PATH",
    "ICON_CAMERA_PATH",
    "ICON_WEBCAM_PATH",
    "ICON_ARROW_DOWN_PATH",
    "ICON_DUALSHOCK4_PATH",
    "ICON_CONTROLLER_PATH",
    "MODELS_DIR",
    "MODEL_POSE_PATH",
]
