"""
Legacy PSCam Sensor - Sensor & Tracking Engine Module.
Unifies camera capture, MediaPipe AI tracking (1P & 2P), IPC shared memory,
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
from .person_lock import (
    InertialCoastingFilter,
    DancerIdentityLock,
    PersonLockController,
)
from .player_slot import (
    AppearanceSignature,
    LongTermIdentityProfile,
    PlayerFrame,
    MultiPoseFrame,
    PlayerSlotState,
    MultiPlayerAssociator,
    compose_player_index_mask,
)
from .gesture_detector import (
    ArmRaiseGestureDetector,
    check_arm_raised,
    dispatch_enter_keystroke,
)
from .kinect_shared_memory import (
    KinectBridge, KinectSharedMemory, KinectMultiPoseSharedMemory, KinectImageSharedMemory, KinectCoachXSharedMemory,
    get_kinect_bridge, close_kinect_bridge,
    SHARED_NAME, SHARED_SIZE, MULTI_SHARED_NAME, MULTI_SHARED_SIZE, IMAGE_SHARED_NAME, IMAGE_SHARED_SIZE,
    COACHX_SHARED_NAME, COACHX_SHARED_SIZE, NEUTRAL_POSE, JOINT_NAMES
)
from .config_manager import (
    ConfigManager, parse_preset, PRESETS_PSCAM, PRESETS_WEBCAM, PRESETS_PHONE_CAM,
    get_app_data_dir, get_config_path, get_logs_dir, is_portable_mode
)
from .phone_camera import PhoneCameraServer, QRCodeGenerator, SelfSignedTLSManager, get_phone_camera_server
from .kinect_emulator import KinectEmulatorDaemon, get_kinect_emulator
from .virtual_phone import (
    VirtualPhoneController, HandAccelerometer, AdaptiveCalibrationTuner, get_virtual_phone,
    find_just_dance_pids, detect_active_song_from_game_process
)
from .ds4_controller import DS4Controller, DS4State, find_ds4_devices, get_ds4_controller
from .telemetry_benchmark import parse_telemetry_csv, compare_telemetries, find_available_benchmarks
from .session_logger import SessionLogger, get_session_logger

import importlib

# Lazy-loaded heavy AI / tracking symbols (PEP 562) to avoid loading MediaPipe (~1.45s) before the GUI window opens
_LAZY_SYMBOL_MAP = {
    "PoseTracker": (".pose_tracker", "PoseTracker"),
    "run_tracking_session": (".tracking_session", "run_tracking_session"),
    "TrackingOverlay": (".tracking_overlay", "TrackingOverlay"),
    "StereoCalibrator": (".stereo_matcher", "StereoCalibrator"),
    "StereoDepthEngine": (".stereo_matcher", "StereoDepthEngine"),
    "STEREO_MODE_DISABLED": (".stereo_matcher", "STEREO_MODE_DISABLED"),
    "STEREO_MODE_SPARSE_METRIC": (".stereo_matcher", "STEREO_MODE_SPARSE_METRIC"),
    "STEREO_MODE_FULL_DEPTH": (".stereo_matcher", "STEREO_MODE_FULL_DEPTH"),
    "STEREO_MODES": (".stereo_matcher", "STEREO_MODES"),
    "PS4_STEREO_BASELINE_M": (".stereo_matcher", "PS4_STEREO_BASELINE_M"),
}

_LAZY_SUBMODULES = {
    "pose_tracker",
    "tracking_session",
    "tracking_overlay",
    "stereo_matcher",
}


def __getattr__(name: str):
    if name in _LAZY_SYMBOL_MAP:
        mod_rel, attr_name = _LAZY_SYMBOL_MAP[name]
        mod = importlib.import_module(mod_rel, __name__)
        val = getattr(mod, attr_name)
        globals()[name] = val
        return val
    if name in _LAZY_SUBMODULES:
        mod = importlib.import_module(f".{name}", __name__)
        globals()[name] = mod
        return mod
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(set(globals().keys()) | set(__all__))


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
    "InertialCoastingFilter",
    "DancerIdentityLock",
    "PersonLockController",
    "AppearanceSignature",
    "LongTermIdentityProfile",
    "PlayerFrame",
    "MultiPoseFrame",
    "PlayerSlotState",
    "MultiPlayerAssociator",
    "compose_player_index_mask",
    "ArmRaiseGestureDetector",
    "check_arm_raised",
    "dispatch_enter_keystroke",
    "KINECT_CONNECTIONS",
    "JOINT_NAMES",
    "KinectBridge",
    "KinectSharedMemory",
    "KinectMultiPoseSharedMemory",
    "KinectImageSharedMemory",
    "KinectCoachXSharedMemory",
    "get_kinect_bridge",
    "close_kinect_bridge",
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
    "get_app_data_dir",
    "get_config_path",
    "get_logs_dir",
    "is_portable_mode",
    "parse_preset",
    "PRESETS_PSCAM",
    "PRESETS_WEBCAM",
    "PRESETS_PHONE_CAM",
    "PhoneCameraServer",
    "QRCodeGenerator",
    "SelfSignedTLSManager",
    "get_phone_camera_server",
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
    "KinectEmulatorDaemon",
    "get_kinect_emulator",
    "SessionLogger",
    "get_session_logger",
]
