"""
Legacy Sensor Lite - Assets and Visual Media Package.
"""
from pathlib import Path

ASSETS_DIR = Path(__file__).resolve().parent
ICON_PSCAMERA_PATH = ASSETS_DIR / "IconePSCAMERA.png"
MODELS_DIR = ASSETS_DIR.parent / "models"
MODEL_POSE_PATH = MODELS_DIR / "pose_landmarker_lite.task"
