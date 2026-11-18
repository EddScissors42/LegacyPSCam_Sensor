"""
Legacy PSCam Sensor - Sensor & Tracking Engine Module.
Unifies camera capture, MediaPipe AI tracking, IPC shared memory,
and OpenCV HUD overlay.
"""
# Python 3.15 lazy-import compatibility normalization for concurrent.futures
try:
    import concurrent.futures
    import concurrent.futures.thread
    import concurrent.futures.process
    concurrent.futures.ThreadPoolExecutor = concurrent.futures.thread.ThreadPoolExecutor
    concurrent.futures.ProcessPoolExecutor = concurrent.futures.process.ProcessPoolExecutor
except Exception:
    pass

from .camera_manager import CameraManager, LatestFrameCamera, FrameBusReader
from .ps4_backend import (
    PS4CameraBackend,
    PS4UsbDevice,
    PS4FirmwareManager,
    PS4DriverInstaller,
    EYE_RIGHT,
    EYE_LEFT,
    DEFAULT_EYE,
    IspGeometry,
    ISP_GEOMETRIES,
    find_isp_geometry,
)
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
from .stereo_matcher import (
    StereoCalibrator,
    StereoDepthEngine,
    STEREO_MODE_DISABLED,
    STEREO_MODE_SPARSE_METRIC,
    STEREO_MODE_FULL_DEPTH,
    STEREO_MODES,
    PS4_STEREO_BASELINE_M,
)
from .tracking_session import run_tracking_session
from .tracking_overlay import TrackingOverlay
from .config_manager import ConfigManager, parse_preset, PRESETS_PSCAM, PRESETS_WEBCAM
from .virtual_phone import (
    VirtualPhoneController, HandAccelerometer, AdaptiveCalibrationTuner, get_virtual_phone,
    find_just_dance_pids, detect_active_song_from_game_process
)
from .ds4_controller import DS4Controller, DS4State, find_ds4_devices, get_ds4_controller
from .telemetry_benchmark import parse_telemetry_csv, compare_telemetries, find_available_benchmarks

__all__ = [
    "CameraManager",
    "LatestFrameCamera",
    "FrameBusReader",
    "PS4CameraBackend",
    "PS4UsbDevice",
    "PS4FirmwareManager",
    "PS4DriverInstaller",
    "EYE_RIGHT",
    "EYE_LEFT",
    "DEFAULT_EYE",
    "IspGeometry",
    "ISP_GEOMETRIES",
    "find_isp_geometry",
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
    "PRESETS_WEBCAM",
    "VirtualPhoneController",
    "HandAccelerometer",
    "AdaptiveCalibrationTuner",
    "get_virtual_phone",
    "find_just_dance_pids",
    "detect_active_song_from_game_process",
    "DS4Controller",
    "DS4State",
    "find_ds4_devices",
    "get_ds4_controller",
    "parse_telemetry_csv",
    "compare_telemetries",
    "find_available_benchmarks",
    "StereoCalibrator",
    "StereoDepthEngine",
    "STEREO_MODE_DISABLED",
    "STEREO_MODE_SPARSE_METRIC",
    "STEREO_MODE_FULL_DEPTH",
    "STEREO_MODES",
    "PS4_STEREO_BASELINE_M",
]
