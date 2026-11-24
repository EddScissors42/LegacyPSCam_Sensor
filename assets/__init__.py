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
WEBAPP_DIR = ASSETS_DIR / "webapp"

WEBAPP_MOBILE_HTML_PATH = WEBAPP_DIR / "mobile_webapp.html"
WEBAPP_EXPIRED_HTML_PATH = WEBAPP_DIR / "expired_session.html"

ICON_APP_ICO_PATH = ICONS_DIR / "app_icon.ico" if (ICONS_DIR / "app_icon.ico").exists() else None
SPLASH_IMAGE_PATH = ICONS_DIR / "splash.png" if (ICONS_DIR / "splash.png").exists() else None
ICON_PSCAMERA_PATH = ICONS_DIR / "IconePSCAMERA.png"
ICON_SETTINGS_PATH = ICONS_DIR / "settings.svg"
ICON_TRACKING_PATH = ICONS_DIR / "trackingicon.svg"
ICON_SLIDERS_PATH = ICON_TRACKING_PATH  # Compatibility alias
ICON_MODE_BALANCED_PATH = ICONS_DIR / "mode_balanced.svg"
ICON_MODE_COMPETITIVE_PATH = ICONS_DIR / "mode_competitive.svg"
ICON_LAB_PATH = ICONS_DIR / "lab.svg"
ICON_WEBCAM_PATH = ICONS_DIR / "webcam.svg"
ICON_ARROW_DOWN_PATH = ICONS_DIR / "arrow_down.png" if (ICONS_DIR / "arrow_down.png").exists() else ICONS_DIR / "arrow_down.svg"
ICON_DUALSHOCK4_PATH = ICONS_DIR / "officialdualshock.png"
ICON_CONTROLLER_PATH = ICONS_DIR / "controller.svg"
ICON_PHONE_PATH = ICONS_DIR / "phone.svg"

MODEL_POSE_LITE_PATH = MODELS_DIR / "pose_landmarker_lite.task"
MODEL_POSE_FULL_PATH = MODELS_DIR / "pose_landmarker_full.task"
MODEL_POSE_PATHS = {
    "lite": MODEL_POSE_LITE_PATH,
    "full": MODEL_POSE_FULL_PATH,
}
MODEL_POSE_PATH = MODEL_POSE_LITE_PATH

__all__ = [
    "ASSETS_DIR",
    "ICONS_DIR",
    "FONTS_DIR",
    "WEBAPP_DIR",
    "WEBAPP_MOBILE_HTML_PATH",
    "WEBAPP_EXPIRED_HTML_PATH",
    "ICON_APP_ICO_PATH",
    "SPLASH_IMAGE_PATH",
    "ICON_PSCAMERA_PATH",
    "ICON_SETTINGS_PATH",
    "ICON_TRACKING_PATH",
    "ICON_SLIDERS_PATH",
    "ICON_MODE_BALANCED_PATH",
    "ICON_MODE_COMPETITIVE_PATH",
    "ICON_LAB_PATH",
    "ICON_WEBCAM_PATH",
    "ICON_ARROW_DOWN_PATH",
    "ICON_DUALSHOCK4_PATH",
    "ICON_CONTROLLER_PATH",
    "ICON_PHONE_PATH",
    "MODELS_DIR",
    "MODEL_POSE_PATH",
    "MODEL_POSE_LITE_PATH",
    "MODEL_POSE_FULL_PATH",
    "MODEL_POSE_PATHS",
]
