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
from .pose_filters import (
    HandAnchorFilter, AdaptiveSmoother, SkeletonCalibrator,
    CameraSpaceXTracker, CameraSpaceYTracker,
    apply_camera_space_translation, apply_camera_space_y_translation, apply_slot_snap,
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
    suppress_duplicate_poses,
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
    get_app_data_dir, get_config_path, get_logs_dir, get_models_dir, is_portable_mode
)
from .kinect_emulator import KinectEmulatorDaemon, get_kinect_emulator
from .session_logger import SessionLogger, get_session_logger

import importlib

# Lazy-loaded symbols (PEP 562) to keep cold startup fast (<100ms)
_LAZY_SYMBOL_MAP = {
    # Heavy AI / Tracking
    "PoseTracker": (".pose_tracker", "PoseTracker"),
    "build_body_mask": (".body_mask", "build_body_mask"),
    "extract_joints_2d": (".body_mask", "extract_joints_2d"),
    "ModelManager": (".model_manager", "ModelManager"),
    "MODEL_SPECS": (".model_manager", "MODEL_SPECS"),
    "run_tracking_session": (".tracking_session", "run_tracking_session"),
    "TrackingOverlay": (".tracking_overlay", "TrackingOverlay"),
    "StereoCalibrator": (".stereo_matcher", "StereoCalibrator"),
    "StereoDepthEngine": (".stereo_matcher", "StereoDepthEngine"),
    "STEREO_MODE_DISABLED": (".stereo_matcher", "STEREO_MODE_DISABLED"),
    "STEREO_MODE_SPARSE_METRIC": (".stereo_matcher", "STEREO_MODE_SPARSE_METRIC"),
    "STEREO_MODE_FULL_DEPTH": (".stereo_matcher", "STEREO_MODE_FULL_DEPTH"),
    "STEREO_MODES": (".stereo_matcher", "STEREO_MODES"),
    "PS4_STEREO_BASELINE_M": (".stereo_matcher", "PS4_STEREO_BASELINE_M"),
    # PS4 Backend
    "PS4CameraBackend": (".ps4_backend", "PS4CameraBackend"),
    "PS4UsbDevice": (".ps4_backend", "PS4UsbDevice"),
    "PS4FirmwareManager": (".ps4_backend", "PS4FirmwareManager"),
    "PS4DriverInstaller": (".ps4_backend", "PS4DriverInstaller"),
    "EYE_RIGHT": (".ps4_backend", "EYE_RIGHT"),
    "EYE_LEFT": (".ps4_backend", "EYE_LEFT"),
    "DEFAULT_EYE": (".ps4_backend", "DEFAULT_EYE"),
    "IspGeometry": (".ps4_backend", "IspGeometry"),
    "ISP_GEOMETRIES": (".ps4_backend", "ISP_GEOMETRIES"),
    "find_isp_geometry": (".ps4_backend", "find_isp_geometry"),
    # Phone Camera WebApp
    "PhoneCameraServer": (".phone_camera", "PhoneCameraServer"),
    "QRCodeGenerator": (".qr_encoder", "QRCodeGenerator"),
    "SelfSignedTLSManager": (".tls_manager", "SelfSignedTLSManager"),
    "get_phone_camera_server": (".phone_camera", "get_phone_camera_server"),
    # PlayStation Move Shared Memory Bridge (ZCM2 Emulator IPC)
    "PSMoveSharedMemory": (".psmove_shared_memory", "PSMoveSharedMemory"),
    "get_psmove_bridge": (".psmove_shared_memory", "get_psmove_bridge"),
    "close_psmove_bridge": (".psmove_shared_memory", "close_psmove_bridge"),
    "PSMOVE_SHARED_NAME": (".psmove_shared_memory", "PSMOVE_SHARED_NAME"),
    "PSMOVE_SHARED_SIZE": (".psmove_shared_memory", "PSMOVE_SHARED_SIZE"),
    "encode_zcm2_input_report": (".psmove_shared_memory", "encode_zcm2_input_report"),
    "ds4_to_psmove_imu": (".psmove_shared_memory", "ds4_to_psmove_imu"),
    "buttons_dict_to_psmove_mask": (".psmove_shared_memory", "buttons_dict_to_psmove_mask"),
    # DualShock 4 Controller
    "DS4Controller": (".ds4_controller", "DS4Controller"),
    "DS4State": (".ds4_controller", "DS4State"),
    "find_ds4_devices": (".ds4_controller", "find_ds4_devices"),
    "get_ds4_controller": (".ds4_controller", "get_ds4_controller"),
    "detect_controller_name": (".ds4_controller", "detect_controller_name"),
    "is_known_ds4_target": (".ds4_controller", "is_known_ds4_target"),
    "is_compatible_ds4_path": (".ds4_controller", "is_compatible_ds4_path"),
    # Telemetry Benchmark
    "parse_telemetry_csv": (".telemetry_benchmark", "parse_telemetry_csv"),
    "compare_telemetries": (".telemetry_benchmark", "compare_telemetries"),
    "find_available_benchmarks": (".telemetry_benchmark", "find_available_benchmarks"),
}

_LAZY_SUBMODULES = {
    "pose_tracker",
    "body_mask",
    "camera_capture",
    "camera_win32",
    "framebus_reader",
    "model_manager",
    "player_reid",
    "tracking_session",
    "tracking_overlay",
    "stereo_matcher",
    "ps4_backend",
    "phone_camera",
    "qr_encoder",
    "tls_manager",
    "psmove_shared_memory",
    "ds4_controller",
    "telemetry_benchmark",
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
    "build_body_mask",
    "extract_joints_2d",
    "HandAnchorFilter",
    "AdaptiveSmoother",
    "SkeletonCalibrator",
    "CameraSpaceXTracker",
    "CameraSpaceYTracker",
    "apply_camera_space_translation",
    "apply_camera_space_y_translation",
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
    "suppress_duplicate_poses",
    "avg",
    "lerp",
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
    "ModelManager",
    "MODEL_SPECS",
    "get_app_data_dir",
    "get_config_path",
    "get_logs_dir",
    "get_models_dir",
    "is_portable_mode",
    "parse_preset",
    "PRESETS_PSCAM",
    "PRESETS_WEBCAM",
    "PRESETS_PHONE_CAM",
    "PhoneCameraServer",
    "QRCodeGenerator",
    "SelfSignedTLSManager",
    "get_phone_camera_server",
    "PSMoveSharedMemory",
    "get_psmove_bridge",
    "close_psmove_bridge",
    "PSMOVE_SHARED_NAME",
    "PSMOVE_SHARED_SIZE",
    "encode_zcm2_input_report",
    "ds4_to_psmove_imu",
    "buttons_dict_to_psmove_mask",
    "DS4Controller",
    "DS4State",
    "find_ds4_devices",
    "get_ds4_controller",
    "detect_controller_name",
    "is_known_ds4_target",
    "is_compatible_ds4_path",
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
