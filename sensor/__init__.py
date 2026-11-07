"""
Legacy PSCam Sensor - Sensor & Tracking Engine Module.
Unifies camera capture, MediaPipe AI tracking, IPC shared memory,
and OpenCV HUD overlay.
"""
from .camera_manager import CameraManager, LatestFrameCamera, FrameBusReader
from .pose_filters import (
    HandAnchorFilter, AdaptiveSmoother, SkeletonCalibrator,
    CameraSpaceXTracker, apply_camera_space_translation, apply_slot_snap,
    FaceFollowPTZ, KINECT_CONNECTIONS, avg, lerp
)
from .pose_tracker import PoseTracker
from .kinect_shared_memory import (
    KinectBridge, KinectSharedMemory, KinectMultiPoseSharedMemory, KinectImageSharedMemory, KinectCoachXSharedMemory,
    SHARED_NAME, SHARED_SIZE, MULTI_SHARED_NAME, MULTI_SHARED_SIZE, IMAGE_SHARED_NAME, IMAGE_SHARED_SIZE,
    COACHX_SHARED_NAME, COACHX_SHARED_SIZE, NEUTRAL_POSE, JOINT_NAMES
)
from .tracking_session import run_tracking_session
from .tracking_overlay import TrackingOverlay
from .config_manager import ConfigManager, parse_preset, PRESETS_PSCAM, PRESETS_WEBCAM

__all__ = [
    "CameraManager",
    "LatestFrameCamera",
    "FrameBusReader",
    "PoseTracker",
    "HandAnchorFilter",
    "AdaptiveSmoother",
    "SkeletonCalibrator",
    "CameraSpaceXTracker",
    "apply_camera_space_translation",
    "apply_slot_snap",
    "FaceFollowPTZ",
    "KINECT_CONNECTIONS",
    "JOINT_NAMES",
    "KinectBridge",
    "KinectSharedMemory",
    "KinectMultiPoseSharedMemory",
    "KinectImageSharedMemory",
    "KinectCoachXSharedMemory",
    "SHARED_NAME",
    "SHARED_SIZE",
    "MULTI_SHARED_NAME",
    "MULTI_SHARED_SIZE",
    "IMAGE_SHARED_NAME",
    "IMAGE_SHARED_SIZE",
    "COACHX_SHARED_NAME",
    "COACHX_SHARED_SIZE",
    "NEUTRAL_POSE",
    "run_tracking_session",
    "TrackingOverlay",
    "ConfigManager",
    "parse_preset",
    "PRESETS_PSCAM",
    "PRESETS_WEBCAM"
]
