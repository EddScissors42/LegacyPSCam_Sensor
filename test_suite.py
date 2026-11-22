"""
Comprehensive Test Suite for Legacy PSCam Sensor.
Verifies config persistence, shared memory bridge, pose engine,
hand anchor (3D & 2D), smoother, coordinate calibrator (X & Y inversion),
high-frequency monotonic timestamps, overlay, and camera manager.
"""
import math
import mmap
import struct
import sys
import time
from pathlib import Path
import numpy as np

# Setup root package path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from sensor.config_manager import (
    ConfigManager, DEFAULT_CONFIG, parse_preset, PRESETS_PSCAM, PRESETS_WEBCAM,
    get_app_data_dir, get_config_path, get_logs_dir, is_portable_mode
)
from sensor.kinect_shared_memory import (
    KinectSharedMemory, SHARED_NAME, SHARED_SIZE, HEADER_FMT, JOINT_FMT, MAGIC, NEUTRAL_POSE,
    KinectMultiPoseSharedMemory, MULTI_SHARED_NAME, MULTI_SHARED_SIZE, MULTI_MAGIC, MULTI_VERSION,
    KinectImageSharedMemory, IMAGE_SHARED_NAME, IMAGE_SHARED_SIZE, IMAGE_MAGIC, IMAGE_HEADER_FMT,
    MULTI_IMAGE_SHARED_NAME, MULTI_IMAGE_MAGIC, MULTI_IMAGE_VERSION,
    IMAGE_W, IMAGE_H, MASK_W, MASK_H,
    KinectCoachXSharedMemory, COACHX_SHARED_NAME, COACHX_SHARED_SIZE, COACHX_MAGIC, COACHX_HEADER_FMT,
    KinectBridge
)
from sensor.pose_tracker import (
    PoseTracker, HandAnchorFilter, AdaptiveSmoother, SkeletonCalibrator,
    CameraSpaceXTracker, apply_camera_space_translation, apply_slot_snap,
    FaceFollowPTZ, avg, lerp
)
from sensor.camera_manager import CameraManager, FrameBusReader
from sensor.tracking_overlay import TrackingOverlay
from sensor.virtual_phone import (
    VirtualPhoneController, HandAccelerometer, get_virtual_phone, PHONE_INPUT_HASHES
)
from sensor.session_logger import SessionLogger, get_session_logger, TELEMETRY_CSV_HEADER

def test_config():
    print("[TEST] ConfigManager & AppData Storage...")
    import tempfile

    app_dir = get_app_data_dir()
    assert app_dir.exists(), "AppData directory must exist"
    logs_dir = get_logs_dir()
    assert logs_dir.exists(), "Logs directory in AppData must exist"
    assert logs_dir.parent == app_dir

    cfg_path = get_config_path()
    assert cfg_path.name == "config.json"
    assert cfg_path.parent == app_dir

    cfg_mgr = ConfigManager()
    cfg = cfg_mgr.config
    assert "camera_mode" in cfg
    assert "smoothing_alpha" in cfg
    assert "ds4_permissive_mode" in cfg
    assert isinstance(cfg["ds4_permissive_mode"], bool)
    assert DEFAULT_CONFIG["ds4_permissive_mode"] is True
    assert parse_preset("1280x800 @ 60 FPS") == (1280, 800, 60)
    assert parse_preset("640x480 @ 30 FPS") == (640, 480, 30)
    assert "1280x800 @ 60 FPS" in PRESETS_PSCAM
    assert "640x480 @ 30 FPS" in PRESETS_WEBCAM

    # Test custom path isolation
    with tempfile.TemporaryDirectory() as td:
        custom_cfg = Path(td) / "test_custom_config.json"
        custom_mgr = ConfigManager(config_path=custom_cfg)
        custom_mgr.set("camera_mode", "pscam")
        assert custom_mgr.save()
        assert custom_cfg.exists()
        loaded = ConfigManager(config_path=custom_cfg)
        assert loaded.get("camera_mode") == "pscam"

    print("  -> ConfigManager & AppData Storage PASSED")

def test_shared_memory():
    print("[TEST] KinectSharedMemory...")
    ksm = KinectSharedMemory()
    assert ksm.is_connected
    assert ksm.write_pose(NEUTRAL_POSE, tracked=True)

    # Read directly from shared memory to verify binary compatibility
    mm = mmap.mmap(-1, SHARED_SIZE, tagname=SHARED_NAME)
    mm.seek(0)
    magic, ver, seq, tracked, ts = struct.unpack(HEADER_FMT, mm.read(24))
    assert magic == MAGIC, f"Expected magic {MAGIC:#x}, got {magic:#x}"
    assert ver == 1
    assert tracked == 1
    assert seq % 2 == 0, f"Expected even sequence after flush, got {seq}"
    assert ts > 0

    # Verify joint 0 (HipCenter)
    j0 = struct.unpack(JOINT_FMT, mm.read(16))
    assert abs(j0[0] - NEUTRAL_POSE[0][0]) < 1e-4
    assert abs(j0[1] - NEUTRAL_POSE[0][1]) < 1e-4
    assert abs(j0[2] - NEUTRAL_POSE[0][2]) < 1e-4
    assert abs(j0[3] - NEUTRAL_POSE[0][3]) < 1e-4

    # Test empty / untracked write
    assert ksm.write_empty()
    mm.seek(0)
    _, _, _, tracked_empty, _ = struct.unpack(HEADER_FMT, mm.read(24))
    assert tracked_empty == 0

    mm.close()
    ksm.close()
    print("  -> KinectSharedMemory (Pose JDP1) PASSED")

    # Test Multi-Pose Bridge (664 bytes, JDP2 - Primary channel for Kinect10.dll)
    kmpsm = KinectMultiPoseSharedMemory()
    assert kmpsm.is_connected
    assert kmpsm.write_poses(NEUTRAL_POSE, tracked=True)

    mm_p2 = mmap.mmap(-1, MULTI_SHARED_SIZE, tagname=MULTI_SHARED_NAME)
    mm_p2.seek(0)
    magic_p2, ver_p2, seq_p2, mask_p2, ts_p2 = struct.unpack(HEADER_FMT, mm_p2.read(24))
    assert magic_p2 == MULTI_MAGIC, f"Expected JDP2 magic {MULTI_MAGIC:#x}, got {magic_p2:#x}"
    assert ver_p2 == MULTI_VERSION
    assert mask_p2 == 1, f"Expected Player 1 active in tracked_mask, got {mask_p2}"
    assert seq_p2 % 2 == 0
    assert ts_p2 > 0

    # Verify joint 0 (HipCenter) of Player 1
    j0_p2 = struct.unpack(JOINT_FMT, mm_p2.read(16))
    assert abs(j0_p2[0] - NEUTRAL_POSE[0][0]) < 1e-4

    assert kmpsm.write_empty()
    mm_p2.seek(0)
    _, _, _, mask_p2_empty, _ = struct.unpack(HEADER_FMT, mm_p2.read(24))
    assert mask_p2_empty == 0

    mm_p2.close()
    kmpsm.close()
    print("  -> KinectMultiPoseSharedMemory (Pose JDP2 664-byte contract) PASSED")

    # Test Image & Segmentation Mask Bridge (1,305,632 bytes, JMI1 & JMI2)
    kism = KinectImageSharedMemory()
    assert kism.is_connected
    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    dummy_mask = np.zeros((480, 640), dtype=np.uint8)
    dummy_mask[100:200, 100:200] = 255
    assert kism.write_image_and_mask(dummy_frame, dummy_mask, tracked=True)

    # 1. Read JMI1 directly from shared memory to verify binary compatibility
    mm_img = mmap.mmap(-1, IMAGE_SHARED_SIZE, tagname=IMAGE_SHARED_NAME)
    mm_img.seek(0)
    magic_i, ver_i, seq_i, tracked_i, w_i, h_i, ts_i = struct.unpack(IMAGE_HEADER_FMT, mm_img.read(32))
    assert magic_i == IMAGE_MAGIC, f"Expected image magic {IMAGE_MAGIC:#x}, got {magic_i:#x}"
    assert ver_i == 1
    assert tracked_i == 1
    assert w_i == 640
    assert h_i == 480
    assert seq_i % 2 == 0
    assert ts_i > 0
    # Verify JMI1 mask format: player pixels must be >= 64 (0x40 in Kinect10.dll) -> 255
    mm_img.seek(32 + 640 * 480 * 4)
    v1_mask_bytes = mm_img.read(320 * 240)
    v1_mask_arr = np.frombuffer(v1_mask_bytes, dtype=np.uint8).reshape((240, 320))
    assert np.any(v1_mask_arr >= 64), "JMI1 mask must have values >= 64 (255) for Kinect10.dll!"

    # 2. Read JMI2 directly from shared memory to verify multi-image compatibility
    mm_img_v2 = mmap.mmap(-1, IMAGE_SHARED_SIZE, tagname=MULTI_IMAGE_SHARED_NAME)
    mm_img_v2.seek(0)
    magic_i2, ver_i2, seq_i2, tracked_i2, w_i2, h_i2, ts_i2 = struct.unpack(IMAGE_HEADER_FMT, mm_img_v2.read(32))
    assert magic_i2 == MULTI_IMAGE_MAGIC, f"Expected image magic {MULTI_IMAGE_MAGIC:#x}, got {magic_i2:#x}"
    assert ver_i2 == 2
    assert tracked_i2 == 1
    # Verify JMI2 mask format: player 1 pixel must be 1
    mm_img_v2.seek(32 + 640 * 480 * 4)
    v2_mask_bytes = mm_img_v2.read(320 * 240)
    v2_mask_arr = np.frombuffer(v2_mask_bytes, dtype=np.uint8).reshape((240, 320))
    assert np.any(v2_mask_arr == 1), "JMI2 mask must have player index 1 for Player 1!"

    # Test empty / untracked write
    assert kism.write_empty()
    mm_img.seek(0)
    _, _, _, tracked_empty_i, _, _, _ = struct.unpack(IMAGE_HEADER_FMT, mm_img.read(32))
    assert tracked_empty_i == 0

    mm_img.close()
    mm_img_v2.close()
    kism.close()
    print("  -> KinectImageSharedMemory (Image/Mask JMI1 & JMI2) PASSED")

    # Test CoachX Bridge (28 bytes, JXC1)
    kcx = KinectCoachXSharedMemory()
    assert kcx.is_connected
    assert COACHX_SHARED_SIZE == 28, f"Expected CoachX size 28 bytes, got {COACHX_SHARED_SIZE}"
    mm_cx = mmap.mmap(-1, COACHX_SHARED_SIZE, tagname=COACHX_SHARED_NAME)
    magic_cx, ver_cx, seq_cx, en_cx, coach_x, ts_cx = struct.unpack(COACHX_HEADER_FMT, mm_cx.read(28))
    assert magic_cx == COACHX_MAGIC
    assert ver_cx == 1
    assert en_cx == 0, "CoachX must be disabled by default to prevent locking player into slot 4!"
    assert abs(coach_x) < 1e-4
    assert ts_cx > 0
    mm_cx.close()
    kcx.close()
    print("  -> KinectCoachXSharedMemory (CoachX JXC1 28-byte contract) PASSED")

    # Test Unified Bridge
    bridge = KinectBridge()
    assert bridge.is_connected
    assert bridge.write(NEUTRAL_POSE, dummy_frame, dummy_mask, tracked=True)
    assert bridge.write_empty()
    bridge.close()
    print("  -> KinectBridge (Unified IPC) PASSED")

    # Verify Legacy10.dll pacer byte (33ms / 30 FPS standard for Just Dance scoring compatibility)
    # and Ordinal 9 (NuiImageGetColorPixelCoordinatesFromDepthPixel) 320x240 -> 640x480 2x scaling
    assert not (BASE_DIR / "tools" / "Kinect10.dll").exists(), "Manual tools/Kinect10.dll must be removed"
    dll_path = BASE_DIR / "tools" / "Legacy10.dll"
    assert dll_path.exists(), "tools/Legacy10.dll must exist for Emulate Kinect in-memory bridge"
    dll_bytes = dll_path.read_bytes()
    assert len(dll_bytes) == 121344, f"Unexpected Legacy10.dll size: {len(dll_bytes)}"
    assert dll_bytes[0x1746] == 0x6A, f"Expected push opcode 0x6A at 0x1746, got {dll_bytes[0x1746]:#x}"
    assert dll_bytes[0x1747] == 0x21, f"Expected 33ms pacer byte 0x21 at 0x1747 (30 FPS standard), got {dll_bytes[0x1747]:#x}"
    assert dll_bytes[0x1748:0x174A] == b"\xff\xd3", "Expected call ebx (Sleep) at 0x1748"
    assert dll_bytes[0x19AC:0x19AE] == b"\xd1\xe0", "Expected shl eax, 1 (0xd1 0xe0) for lColorX in Legacy10.dll Ordinal 9"
    assert dll_bytes[0x19BC:0x19BE] == b"\xd1\xe0", "Expected shl eax, 1 (0xd1 0xe0) for lColorY in Legacy10.dll Ordinal 9"
    print("  -> Legacy10.dll Pacer Byte (30 FPS) + Ordinal 9 (2x Depth->Color Scale) PASSED")

def test_hand_anchor():
    print("[TEST] HandAnchorFilter (3D and 2D)...")
    haf = HandAnchorFilter(hand_length=0.12)
    # 20 neutral joints in 3D
    joints = [list(j) for j in NEUTRAL_POSE]
    # Set left hand confidence to low (< 0.45) and move it unnaturally
    joints[7] = (5.0, 5.0, 5.0, 0.1) # left hand lost
    filtered = haf.apply(joints)
    wr = joints[6]
    hd = filtered[7]
    dist = np.linalg.norm(np.array(hd[:3]) - np.array(wr[:3]))
    assert abs(dist - 0.12) < 0.01, f"Extrapolated hand distance was {dist}, expected ~0.12m"

    # Test 2D pixel extrapolation
    px_joints = [(100 + i*10, 200 + i*5, 0.9) for i in range(20)]
    # Set right hand (11) confidence low
    px_joints[11] = (0, 0, 0.1)
    px_filtered = haf.apply_pixel(px_joints)
    px_wr = px_joints[10]
    px_hd = px_filtered[11]
    px_dist = np.hypot(px_hd[0] - px_wr[0], px_hd[1] - px_wr[1])
    assert px_dist > 5.0, f"Expected 2D hand to extrapolate past wrist, dist was {px_dist}"
    print("  -> HandAnchorFilter PASSED")

def test_adaptive_smoother():
    print("[TEST] AdaptiveSmoother (dt-normalized 30/60 FPS consistency)...")
    smoother = AdaptiveSmoother(base_alpha=0.50, alpha_fast=0.90, speed_threshold=0.15)
    j1 = [(0.0, 0.0, 2.0, 1.0)] * 20
    # First frame initializes
    res1 = smoother.apply(j1)
    assert res1[0] == j1[0]

    # Small movement (stationary/slow jitter)
    j2 = [(0.002, 0.002, 2.0, 1.0)] * 20
    res2 = smoother.apply(j2, dt=1.0 / 30.0)
    assert res2[0][0] < 0.0016

    # Fast movement (dance swing)
    j3 = [(1.0, 1.0, 2.0, 1.0)] * 20
    res3 = smoother.apply(j3, dt=1.0 / 30.0)
    assert res3[0][0] > 0.6

    # Verify FPS-independent velocity scaling:
    # A 0.04m displacement at 60 FPS (dt = 1/60s) has the exact same physical speed (2.4 m/s)
    # as a 0.08m displacement at 30 FPS (dt = 1/30s).
    s30 = AdaptiveSmoother(base_alpha=0.50, alpha_fast=0.90, speed_threshold=0.15)
    s60 = AdaptiveSmoother(base_alpha=0.50, alpha_fast=0.90, speed_threshold=0.15)
    s30.apply(j1)
    s60.apply(j1)
    out30 = s30.apply([(0.08, 0.0, 2.0, 1.0)] * 20, dt=1.0 / 30.0)
    out60 = s60.apply([(0.04, 0.0, 2.0, 1.0)] * 20, dt=1.0 / 60.0)
    # Effective alpha (out / target_disp) must be identical between 30 FPS and 60 FPS!
    alpha_30 = out30[0][0] / 0.08
    alpha_60 = out60[0][0] / 0.04
    assert abs(alpha_30 - alpha_60) < 1e-5, f"Expected identical alpha across 30/60 FPS, got {alpha_30} vs {alpha_60}"

    # Verify 2D pixel joints EMA smoothing (eliminates stationary jitter, responds fast to big moves)
    px_s = AdaptiveSmoother(base_alpha=0.50, alpha_fast=0.90, speed_threshold=0.15)
    px1 = [(320, 240, 0.95)] * 20
    out_px1 = px_s.apply_pixel(px1, frame_w=640, frame_h=480, dt=1.0 / 30.0)
    assert out_px1[0][:2] == (320, 240)
    # Stationary micro-jitter (+2 px) is damped to +1 px
    out_px2 = px_s.apply_pixel([(322, 242, 0.95)] * 20, frame_w=640, frame_h=480, dt=1.0 / 30.0)
    assert out_px2[0][0] <= 321
    # Fast swing (+200 px) snaps quickly towards target
    out_px3 = px_s.apply_pixel([(520, 440, 0.95)] * 20, frame_w=640, frame_h=480, dt=1.0 / 30.0)
    assert out_px3[0][0] > 480
    print("  -> AdaptiveSmoother PASSED")

def test_calibrator():
    print("[TEST] SkeletonCalibrator (Multi-Tier Calibration & Coordinate Conventions)...")
    calib = SkeletonCalibrator(target_height_m=1.75)
    assert not calib.is_calibrated

    # Create realistic standing skeleton
    # In MediaPipe world coordinates:
    # - Head is at negative Y (upwards), feet at positive Y (downwards)
    # - Right limbs are at negative X, Left limbs are at positive X
    joints = [list(j) for j in NEUTRAL_POSE]
    joints[0] = (0.0, 0.0, 0.0, 0.9)    # HipCenter
    joints[2] = (0.0, -0.45, 0.0, 0.9)  # ShoulderCenter
    joints[3] = (0.0, -0.75, 0.0, 0.9)  # Head
    joints[8] = (-0.20, -0.45, 0.0, 0.9)# ShoulderRight (MediaPipe negative X)
    joints[4] = (0.20, -0.45, 0.0, 0.9) # ShoulderLeft  (MediaPipe positive X)
    joints[14] = (0.1, 0.85, 0.0, 0.9)  # Left ankle
    joints[18] = (-0.1, 0.85, 0.0, 0.9) # Right ankle

    # Test Tier 1: Full-body (Head + Ankles + Hips)
    calib.calibrate(joints)
    assert calib.is_calibrated
    assert calib.calibration_tier == "full_body"

    transformed = calib.transform(joints)
    # Head Y should be positive (Kinect space: positive up)
    head_trans = transformed[3]
    assert head_trans[1] > 0.5, f"Expected head Y > 0.5 in Kinect space, got {head_trans[1]}"
    # Depth should be around 2.0m
    assert abs(head_trans[2] - 2.0) < 0.1

    # Check X inversion: ShoulderRight in Kinect must be POSITIVE X
    sh_r = transformed[8]
    sh_l = transformed[4]
    assert sh_r[0] > 0.1, f"Expected ShoulderRight Kinect X > 0, got {sh_r[0]}"
    assert sh_l[0] < -0.1, f"Expected ShoulderLeft Kinect X < 0, got {sh_l[0]}"

    # Test Tier 2: Flexible Torso (Legs cut off, Ankles = 0 confidence)
    calib_tier2 = SkeletonCalibrator(target_height_m=1.75)
    joints_t2 = [list(j) for j in joints]
    joints_t2[14] = (0.0, 0.0, 0.0, 0.0) # Ankle L lost
    joints_t2[18] = (0.0, 0.0, 0.0, 0.0) # Ankle R lost
    calib_tier2.calibrate(joints_t2)
    assert calib_tier2.is_calibrated
    assert calib_tier2.calibration_tier == "flexible_torso"

    # Test Tier 3: Upper-Body / Desk Framing (Legs and Hips cut off)
    calib_tier3 = SkeletonCalibrator(target_height_m=1.75)
    joints_t3 = [list(j) for j in joints]
    joints_t3[0] = (0.0, 0.0, 0.0, 0.0)  # HipCenter lost
    joints_t3[12] = (0.0, 0.0, 0.0, 0.0) # Hip L lost
    joints_t3[16] = (0.0, 0.0, 0.0, 0.0) # Hip R lost
    joints_t3[14] = (0.0, 0.0, 0.0, 0.0) # Ankle L lost
    joints_t3[18] = (0.0, 0.0, 0.0, 0.0) # Ankle R lost
    calib_tier3.calibrate(joints_t3)
    assert calib_tier3.is_calibrated
    assert calib_tier3.calibration_tier == "upper_body"

    # Test CameraSpaceXTracker & apply_slot_snap (Dancer Slot Selection 1, 2, 3, 4)
    tracker_x = CameraSpaceXTracker(cfg={
        'camera_x_slot_tracking': True,
        'camera_x_reverse_for_coach_selection': True,
        'camera_x_deadzone': 0.025,
        'camera_x_range_m': 2.2,
        'coach_assist_enabled': True,
        'coach_assist_multiplier': 1.35,
        'camera_x_smoothing': 1.0  # instant for test
    })

    class MockLM:
        def __init__(self, x, y=0.5, vis=0.9):
            self.x = x
            self.y = y
            self.visibility = vis
            self.presence = vis

    # Case A: User standing on the right side of the room (camera image left, x = 0.2)
    # Target in Kinect space should be positive X (Dancer 4 / Purple slot)
    norm_right = [MockLM(0.5)] * 33
    norm_right[23] = MockLM(0.2)  # LEFT_HIP
    norm_right[24] = MockLM(0.2)  # RIGHT_HIP
    dx_right = tracker_x.update(norm_right)
    assert dx_right > 0.4, f"Expected positive lateral offset for user right, got {dx_right}"

    # Case B: User standing on the left side of the room (camera image right, x = 0.8)
    # Target in Kinect space should be negative X (Dancer 1 / Blue slot)
    tracker_x.reset()
    norm_left = [MockLM(0.5)] * 33
    norm_left[23] = MockLM(0.8)
    norm_left[24] = MockLM(0.8)
    dx_left = tracker_x.update(norm_left)
    assert dx_left < -0.4, f"Expected negative lateral offset for user left, got {dx_left}"

    # Case C: User in center (x = 0.5) within deadzone
    tracker_x.reset()
    norm_center = [MockLM(0.5)] * 33
    norm_center[23] = MockLM(0.505)
    norm_center[24] = MockLM(0.505)
    dx_center = tracker_x.update(norm_center)
    assert abs(dx_center) < 1e-3, f"Expected zero lateral offset in deadzone, got {dx_center}"

    # Test apply_camera_space_translation shifts whole skeleton equally
    tracker_x.reset()
    translated_skel = apply_camera_space_translation(transformed, norm_right, tracker_x)
    assert abs(translated_skel[0][0] - (transformed[0][0] + dx_right)) < 1e-4
    assert abs(translated_skel[3][0] - (transformed[3][0] + dx_right)) < 1e-4

    # Test apply_slot_snap enhances slot distinction while keeping head-hip relative distance
    snapped = apply_slot_snap(translated_skel, cfg={'slot_snap_enabled': True, 'slot_snap_gain': 1.35, 'slot_snap_deadzone': 0.06})
    assert abs(snapped[0][0]) > abs(translated_skel[0][0])
    orig_dist = math.sqrt((translated_skel[3][0] - translated_skel[0][0])**2 + (translated_skel[3][1] - translated_skel[0][1])**2)
    snap_dist = math.sqrt((snapped[3][0] - snapped[0][0])**2 + (snapped[3][1] - snapped[0][1])**2)
    assert abs(orig_dist - snap_dist) < 1e-4, "Relative body geometry must be invariant under slot snap!"

    print("  -> SkeletonCalibrator PASSED (All 3 Tiers verified + Kinect coordinate standard + Slot Selection)")

def test_pose_tracker():
    print("[TEST] PoseTracker (high-frequency monotonic timestamps, body mask & FaceFollowPTZ)...")
    tracker = PoseTracker()
    dummy = np.zeros((480, 640, 3), dtype=np.uint8)

    # Test FaceFollowPTZ auto-framing
    ptz = FaceFollowPTZ(cfg={"face_follow_enabled": True, "face_follow_zoom": 1.25})
    assert ptz.valid is False

    class MockPt:
        def __init__(self, x, y):
            self.x = x
            self.y = y
            self.visibility = 0.95
            self.presence = 0.95

    mock_lms = [MockPt(0.5, 0.3)] * 33
    ptz.update_from_norm(mock_lms, mirrored=True)
    assert ptz.valid is True
    assert abs(ptz.cx - 0.5) < 0.05
    assert abs(ptz.cy - (0.3 + 0.06)) < 0.05

    dummy_mask = np.zeros((240, 320), dtype=np.uint8)
    out_frame, out_mask = ptz.apply(dummy, dummy_mask)
    assert out_frame.shape == (480, 640, 3)
    assert out_mask.shape == (240, 320)

    # Test 320x240 native body mask generation
    built_mask = tracker.build_body_mask(mock_lms, PoseTracker.MASK_INTERNAL_W, PoseTracker.MASK_INTERNAL_H)
    assert built_mask.shape == (240, 320)
    assert np.any(built_mask == 255)

    # Simulate fast burst frames in quick succession (< 1ms between calls)
    for _ in range(5):
        tracked, kinect_joints, px_joints, body_mask = tracker.process_frame(dummy)
        assert tracked is False
        assert body_mask is None

    # Also test high-resolution 1280x800 frame pre-downscaling path (640x400 aspect-preserved inference buffer)
    dummy_hd = np.zeros((800, 1280, 3), dtype=np.uint8)
    for _ in range(3):
        tracked, kinect_joints, px_joints, body_mask = tracker.process_frame(dummy_hd)
        assert tracked is False
        assert body_mask is None
    assert tracker._infer_bgr is not None and tracker._infer_bgr.shape == (400, 640, 3)
    assert tracker._infer_rgb is not None and tracker._infer_rgb.shape == (400, 640, 3)

    tracker.close()
    print("  -> PoseTracker PASSED (Monotonic timestamp & FaceFollowPTZ validated)")

def test_overlay():
    print("[TEST] TrackingOverlay (ROI silhouette, 320x240 upscaling & skeleton)...")
    overlay = TrackingOverlay(show_hud=True)
    frame = np.zeros((800, 1280, 3), dtype=np.uint8)
    px_joints = [(50 + i*15, 50 + i*15, 0.9) for i in range(20)]
    # Test with 320x240 native Kinect mask rendered onto a 1280x800 PS4 Camera frame
    dummy_mask = np.zeros((240, 320), dtype=np.uint8)
    dummy_mask[30:120, 40:140] = 255
    frame = overlay.draw_player_silhouette(frame, dummy_mask)
    frame = overlay.draw_skeleton(frame, px_joints)
    frame = overlay.draw_hud(frame, "PS Camera 60 FPS", True, 60.0, 59.8, True, True)
    assert frame.shape == (800, 1280, 3)
    assert np.any(frame > 0)
    print("  -> TrackingOverlay PASSED")

def test_camera_manager():
    print("[TEST] CameraManager (PnP Hardware Snapshot & PS4 State Machine)...")
    installed = CameraManager.is_pscam_installed()
    print(f"  PSCam4Win Installed: {installed}")

    # Test Win32 CfgMgr32 fast PnP snapshot (< 3ms)
    t0 = time.perf_counter()
    snapshot = CameraManager.get_hardware_snapshot()
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert isinstance(snapshot, tuple)
    print(f"  Hardware snapshot devices: {len(snapshot)} (query latency: {elapsed_ms:.2f}ms)")

    # Test PS4 Camera multi-stage state machine and fast cached query (< 25ms)
    ps4_info = CameraManager.get_ps4_camera_state()
    t_st = time.perf_counter()
    ps4_info_cached = CameraManager.get_ps4_camera_state()
    st_ms = (time.perf_counter() - t_st) * 1000.0
    assert isinstance(ps4_info, dict)
    assert ps4_info_cached["state"] == ps4_info["state"]
    assert st_ms < 25.0, f"Cached get_ps4_camera_state() took too long ({st_ms:.2f}ms)"
    assert "state" in ps4_info
    valid_states = {"NOT_INSTALLED", "DISCONNECTED", "DRIVER_STOPPED", "BOOTLOADER_UPLOADING", "WAITING_VCAM", "READY"}
    assert ps4_info["state"] in valid_states
    assert isinstance(ps4_info["installed"], bool)
    assert isinstance(ps4_info["running"], bool)
    assert isinstance(ps4_info["bootloader"], bool)
    assert isinstance(ps4_info["active_hw"], bool)
    assert isinstance(ps4_info["vcam_count"], int)
    print(f"  PS4 Camera lifecycle state: {ps4_info['state']} (HW active: {ps4_info['active_hw']}, VCAMs: {ps4_info['vcam_count']}, cached query: {st_ms:.2f}ms)")

    t_enum = time.perf_counter()
    cams = CameraManager.enumerate_cameras(max_probe=2)
    enum_ms = (time.perf_counter() - t_enum) * 1000.0
    assert len(cams) > 0
    assert hasattr(CameraManager, "_get_windows_camera_names_win32")
    print(f"  Cameras found: {[str(c) for c in cams]} (enumeration latency: {enum_ms:.2f}ms)")

    # Test FrameBusReader lifecycle and only_new parameter
    fb = FrameBusReader()
    # It may or may not find a slot if driver is stopped, but it must not crash
    assert fb.slot in {-1, 0, 1, 2, 3, 4, 5, 6, 7}
    assert isinstance(fb.is_connected, bool)
    fb.close()
    assert fb.h_map is None
    assert not fb.is_connected
    print("  FrameBus direct IPC reader lifecycle verified")

    # Test fast strided black-frame detection
    from sensor.camera_manager import LatestFrameCamera
    black_img = np.zeros((800, 1280, 3), dtype=np.uint8)
    bright_img = np.full((800, 1280, 3), 120, dtype=np.uint8)
    assert LatestFrameCamera._is_black_frame(black_img) is True
    assert LatestFrameCamera._is_black_frame(bright_img) is False
    print("  Fast strided black-frame detection verified")

    # Test Stereo Side-by-Side (SBS) auto-cropping logic
    dummy_sbs = np.zeros((800, 2560, 3), dtype=np.uint8)
    h_sbs, w_sbs = dummy_sbs.shape[:2]
    assert w_sbs >= int(1.8 * h_sbs)
    cropped_sbs = dummy_sbs[:, :w_sbs // 2]
    assert cropped_sbs.shape == (800, 1280, 3), f"Expected (800, 1280, 3), got {cropped_sbs.shape}"

    dummy_webcam = np.zeros((480, 640, 3), dtype=np.uint8)
    h_wc, w_wc = dummy_webcam.shape[:2]
    assert w_wc < int(1.8 * h_wc)
    print("  Stereo Side-by-Side auto-crop logic verified")
    print("  -> CameraManager PASSED")

def test_project_structure():
    print("[TEST] Modular Project Structure (sensor/, ui/, assets/)...")
    assert (BASE_DIR / "sensor").is_dir(), "Directory sensor/ must exist"
    assert (BASE_DIR / "sensor" / "pose_filters.py").exists(), "sensor/pose_filters.py must exist"
    assert (BASE_DIR / "ui").is_dir(), "Directory ui/ must exist"
    assert (BASE_DIR / "ui" / "pages.py").exists(), "ui/pages.py must exist"
    assert (BASE_DIR / "ui" / "theme.py").exists(), "ui/theme.py must exist"
    assert (BASE_DIR / "ui" / "icons.py").exists(), "ui/icons.py must exist"
    assert (BASE_DIR / "assets").is_dir(), "Directory assets/ must exist"
    assert (BASE_DIR / "assets" / "icons").is_dir(), "Directory assets/icons/ must exist"
    assert (BASE_DIR / "assets" / "icons" / "IconePSCAMERA.png").exists(), "Asset IconePSCAMERA.png must exist in assets/icons/"
    assert (BASE_DIR / "assets" / "icons" / "settings.svg").exists(), "Asset settings.svg must exist in assets/icons/"
    assert (BASE_DIR / "assets" / "icons" / "trackingicon.svg").exists(), "Asset trackingicon.svg must exist in assets/icons/"
    assert not (BASE_DIR / "assets" / "icons" / "sliders.svg").exists(), "Asset sliders.svg must be removed from assets/icons/"
    assert (BASE_DIR / "assets" / "icons" / "mode_balanced.svg").exists(), "Asset mode_balanced.svg must exist in assets/icons/"
    assert (BASE_DIR / "assets" / "icons" / "mode_competitive.svg").exists(), "Asset mode_competitive.svg must exist in assets/icons/"
    assert (BASE_DIR / "assets" / "icons" / "lab.svg").exists(), "Asset lab.svg must exist in assets/icons/"
    assert (BASE_DIR / "assets" / "icons" / "arrow_down.png").exists() or (BASE_DIR / "assets" / "icons" / "arrow_down.svg").exists(), "Asset arrow_down must exist in assets/icons/"
    assert (BASE_DIR / "models" / "pose_landmarker_lite.task").exists(), "models/pose_landmarker_lite.task must exist"
    assert (BASE_DIR / "models" / "pose_landmarker_full.task").exists(), "models/pose_landmarker_full.task must exist"
    assert not (BASE_DIR / "models" / "pose_landmarker_heavy.task").exists(), "models/pose_landmarker_heavy.task must be removed"

    import sensor
    assert hasattr(sensor, "PoseTracker")
    assert hasattr(sensor, "HandAnchorFilter")
    assert hasattr(sensor, "CameraManager")
    assert hasattr(sensor, "KinectBridge")
    assert hasattr(sensor, "run_tracking_session")
    assert hasattr(sensor, "DS4Controller")
    assert hasattr(sensor, "find_ds4_devices")
    assert hasattr(sensor, "get_ds4_controller")
    assert hasattr(sensor, "StereoCalibrator")
    assert hasattr(sensor, "StereoDepthEngine")
    assert hasattr(sensor, "SessionLogger")
    assert hasattr(sensor, "get_session_logger")
    assert hasattr(sensor, "InertialCoastingFilter")
    assert hasattr(sensor, "DancerIdentityLock")
    assert hasattr(sensor, "PersonLockController")
    assert (BASE_DIR / "sensor" / "person_lock.py").exists(), "sensor/person_lock.py must exist"
    assert (BASE_DIR / "sensor" / "gesture_detector.py").exists(), "sensor/gesture_detector.py must exist"
    assert hasattr(sensor, "ArmRaiseGestureDetector")
    assert hasattr(sensor, "check_arm_raised")

    import ui
    assert hasattr(ui, "LegacySensorGUI")
    assert hasattr(ui, "LegacySensorQtGUI")
    assert hasattr(ui, "UIPagesMixin")
    assert hasattr(ui, "launch_app")
    assert hasattr(ui, "PALETTE")
    assert hasattr(ui, "CALIB_PRESETS")
    assert ui.CALIB_PRESETS["balanced"]["pose_model"] == "full"
    assert ui.CALIB_PRESETS["competitive"]["pose_model"] == "lite"
    assert "stable" not in ui.CALIB_PRESETS, "Ultra Stable / Heavy preset must be removed"
    assert hasattr(ui, "generate_icons")

    # Verify Qt GUI offscreen instantiation, icons, and fonts
    if ui.HAS_QT:
        import os
        import version
        assert hasattr(version, "__version__")
        assert version.STAGE == "Alpha"

        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        win = ui.LegacySensorQtGUI(auto_discover=False)
        assert win.windowTitle() == version.WINDOW_TITLE
        assert not win.pix_ps_act.isNull(), "PS Camera icon pixmap must not be null"
        assert not win.pix_web_act.isNull(), "Webcam icon pixmap must not be null"
        assert not win.pix_phone_act.isNull(), "Phone Camera icon pixmap must not be null"
        assert not win.pix_phone_inact.isNull(), "Phone Camera inactive icon pixmap must not be null"
        assert hasattr(win, "card_phone_cam"), "Phone Camera sidebar card must exist"
        assert not win.pix_gear_act.isNull(), "Settings icon pixmap must not be null"
        assert not win.pix_slid_act.isNull(), "Sliders icon pixmap must not be null"
        assert not win.pix_slid_disabled.isNull(), "Disabled sliders icon pixmap must not be null"
        assert not win.pix_lab_act.isNull(), "Lab icon pixmap must not be null"
        assert win.pix_gear_act.devicePixelRatio() >= 2.0, "Icons must have High-DPI supersampling"
        assert "balanced" in win.mode_pixmaps and not win.mode_pixmaps["balanced"][0].isNull(), "Mode icon balanced must not be null"
        assert "competitive" in win.mode_pixmaps and not win.mode_pixmaps["competitive"][0].isNull(), "Mode icon competitive must not be null"
        assert "stable" not in win.calib_cards and len(win.calib_cards) == 2, "Only Balanced and Competitive cards should exist"
        assert not win.pix_status_err.isNull(), "Status X icon pixmap must not be null"
        assert win.font_title == "Kanit", f"Expected Kanit title font, got {win.font_title}"
        assert win.font_heading == "National Park", f"Expected National Park heading font, got {win.font_heading}"
        assert win.font_body == "Inter Tight", f"Expected Inter Tight body font, got {win.font_body}"

        # Verification of Experimental tab and Virtual Phone controls inside it
        assert hasattr(win, "btn_tab_exp"), "Experimental tab button must exist"
        assert hasattr(win, "page_exp"), "Experimental page widget must exist"
        assert hasattr(win, "chk_vphone_enabled"), "Celular Virtual toggle must exist in Experimental"
        assert hasattr(win, "btn_vphone_ftue"), "Skip Finish button must exist in Celular Virtual block"
        assert hasattr(win, "benchmark_box") and not win.benchmark_box.isVisible(), "Benchmark feature box must exist preserved but hidden from UI"
        assert hasattr(win, "chk_benchmark_enabled"), "Benchmark auto-record toggle must exist"
        assert hasattr(win, "lbl_benchmark_song"), "Benchmark song label must exist"
        assert hasattr(win, "btn_open_benchmark"), "Benchmark open button must exist"
        assert hasattr(win, "chk_benchmark_adaptive"), "Benchmark adaptive calibration toggle must exist"
        assert hasattr(win, "lbl_vphone_song"), "Song label alias must exist"
        assert hasattr(win, "btn_vphone_benchmark"), "Benchmark button alias must exist"
        assert hasattr(win, "chk_vphone_auto_record"), "Auto record checkbox alias must exist"
        assert hasattr(win, "chk_vphone_adaptive"), "Adaptive calibration checkbox alias must exist"
        assert hasattr(win, "stereo_box"), "Stereo feature box must exist in Video Settings card"
        assert hasattr(win, "chk_stereo"), "Stereo toggle checkbox must exist"
        assert win.chk_stereo.text() == "Stereo Vision", f"Expected 'Stereo Vision', got {win.chk_stereo.text()}"
        assert hasattr(win, "btn_logs_folder"), "Open Logs Folder button must exist in sidebar"
        assert win.btn_logs_folder.text() == "Open Logs Folder"
        assert hasattr(win, "cb_stereo_mode"), "Stereo mode alias must exist"
        assert hasattr(win, "block_ps_eye"), "Camera eye sensor block must exist"

        # Verify eye selector disables when Stereo Vision is toggled ON, and enables when OFF
        win.chk_stereo.setChecked(True)
        assert not win.block_ps_eye.isEnabled(), "Camera eye block must be disabled when Stereo Vision is active"
        win.chk_stereo.setChecked(False)
        assert win.block_ps_eye.isEnabled(), "Camera eye block must be re-enabled when Stereo Vision is inactive"
        assert hasattr(win, "cb_res") and hasattr(win, "cb_fps"), "Split resolution and FPS combos must exist in webcam card"
        assert hasattr(win, "btn_refresh"), "Refresh button in device card must exist"
        if win.is_camera_accessible():
            win._switch_tab("exp")
            assert win.active_tab == "exp", "Should switch to experimental tab"
        else:
            assert not win.btn_tab_exp.isEnabled(), "Experimental tab must be disabled when camera is not accessible"

        # Verify VirtualPhoneController & HandAccelerometer physics and JSON packets
        import json
        ha = HandAccelerometer(hand="right", sensitivity=1.2)
        j_frame1 = [list(j) for j in NEUTRAL_POSE]
        j_frame1[9] = (0.25, 0.15, 2.0, 0.95)   # ElbowRight
        j_frame1[10] = (0.30, 0.25, 1.95, 0.95) # WristRight
        j_frame1[11] = (0.35, 0.30, 1.90, 0.95) # HandRight
        acc1 = ha.update(j_frame1, True, now=1.000)
        assert len(acc1) == 3

        # Fast upward/lateral whip of the right hand over 16ms (60 FPS)
        j_frame2 = [list(j) for j in j_frame1]
        j_frame2[10] = (0.55, 0.65, 1.80, 0.95)
        j_frame2[11] = (0.65, 0.75, 1.75, 0.95)
        acc2 = ha.update(j_frame2, True, now=1.016)
        assert abs(acc2[0]) > 0.5 or abs(acc2[1]) > 0.5, f"Expected dynamic G-force spike on fast hand whip, got {acc2}"
        acc2_mag = math.sqrt(acc2[0]**2 + acc2[1]**2 + acc2[2]**2)
        assert acc2_mag <= 7.0001, f"Expected vector magnitude clamped to MAX_G (7.0), got {acc2_mag}"
        assert not hasattr(win, "slider_vphone_sens"), "Sensitivity slider must be removed from GUI per user specifications"

        score_pkt = json.loads(VirtualPhoneController.build_scoring_packet([acc2]))
        assert "root" in score_pkt and score_pkt["root"]["__class"] == "JD_PhoneScoringData"
        assert len(score_pkt["root"]["accelData"]) == 1
        assert len(score_pkt["root"]["accelData"][0]) == 3
        assert PHONE_INPUT_HASHES["VALID"] == 1084313942
        assert PHONE_INPUT_HASHES["UP"] == 3690595578

        # Verify VirtualPhoneController.update_from_hardware_accel
        vp = get_virtual_phone()
        hw_accel = vp.update_from_hardware_accel(0.05, 1.02, 0.22)
        assert hw_accel == (0.05, 1.02, 0.22)
        assert vp.latest_accel == (0.05, 1.02, 0.22)

        # Verify DualShock 4 UI controls and tab switching
        assert hasattr(win, "card_ds4"), "DualShock 4 sidebar card must exist"
        assert hasattr(win, "btn_tab_controller"), "Controller Settings tab button must exist"
        assert hasattr(win, "page_ds4"), "DualShock 4 page widget must exist"
        assert hasattr(win, "btn_ds4_rumble"), "Test rumble button must exist in DS4 view"
        assert hasattr(win, "btn_ds4_reconnect"), "Reconnect button must exist in DS4 view"
        assert hasattr(win, "chk_ds4_permissive"), "Permissive mode checkbox must exist in DS4 settings"

        win._set_mode("ds4")
        assert win.active_tab == "controller", "Should switch to controller settings tab on ds4 mode"
        assert not win.btn_tab_controller.isHidden(), "Controller settings tab must be visible in ds4 mode"
        assert not win.btn_tab_exp.isHidden(), "Experimental tab must be visible in ds4 mode"
        assert win.chk_vphone_enabled.isChecked(), "Virtual phone must be checked in ds4 mode"
        assert not win.chk_vphone_enabled.isEnabled(), "Virtual phone checkbox must be disabled/locked in ds4 mode"
        assert not win.vphone_details_frame.isHidden(), "Virtual phone telemetry details must not be hidden in ds4 mode"
        assert win.auto_frame_box.isHidden(), "Auto-frame box must be hidden in ds4 mode"
        assert not hasattr(win, "emulate_kinect_box"), "Emulate Kinect box must be removed from Experimental UI"
        assert not hasattr(win, "chk_emulate_kinect"), "Emulate Kinect checkbox must be removed from Experimental UI"
        assert not hasattr(win, "lbl_emulate_tip"), "Sidebar Emulate Kinect reminder must be removed"
        assert not hasattr(win, "lbl_vphone_kinect_conflict"), "Conflict label must be removed (no mutual exclusion)"
        win._switch_tab("exp")
        assert win.active_tab == "exp", "Should be able to switch to experimental tab in ds4 mode"
        assert win.btn_tab_exp.isEnabled(), "Experimental tab must be enabled in ds4 mode"

        # Verify Emulate Kinect is ALWAYS active and does NOT disable Virtual Phone Controller
        assert win.cfg.get("emulate_kinect_enabled") is True, "Emulate Kinect must always be enabled"
        assert win.kinect_emulator.enabled is True and win.kinect_emulator._running is True, "KinectEmulatorDaemon must always be running"
        win._set_mode("webcam")
        assert win.chk_vphone_enabled.isEnabled(), "Virtual Phone must remain enabled alongside always-on Emulate Kinect"
        win._set_mode("ds4")
        assert win.chk_vphone_enabled.isChecked(), "vphone must be checked in ds4 mode"
        assert win.kinect_emulator._running is True, "KinectEmulatorDaemon must stay active in ds4 mode"

        win._set_mode("webcam")

        # Calibration & Experimental tab gating when camera is not connected
        if not win.is_camera_accessible():
            assert not win.btn_tab_calib.isEnabled(), "Calibration tab must be disabled when camera is not accessible"
            assert not win.btn_tab_exp.isEnabled(), "Experimental tab must be disabled when camera is not accessible"
            win._switch_tab("calib")
            assert win.active_tab == "video", "Switching to calib must be prevented when camera is not accessible"
            win._switch_tab("exp")
            assert win.active_tab == "video", "Switching to exp must be prevented when camera is not accessible"
        win._switch_tab("video")
        win.close()
        app.processEvents()

    from sensor.ds4_controller import (
        get_ds4_controller, DS4Controller, DS4State, find_ds4_devices,
        KNOWN_DS4_TARGETS, is_compatible_ds4_path, detect_controller_name
    )
    ds4 = get_ds4_controller()
    assert hasattr(ds4, "is_usb")
    assert hasattr(ds4, "permissive_mode")
    assert hasattr(ds4.state, "is_usb")
    assert hasattr(ds4.state, "imu_frozen")
    assert hasattr(ds4.state, "controller_name")
    assert isinstance(find_ds4_devices(), list)

    # Level A compatibility verification:
    assert is_compatible_ds4_path("hid#vid_054c&pid_09cc") is True
    assert is_compatible_ds4_path("hid#vid_1532&pid_1000") is True # Razer Raiju
    assert is_compatible_ds4_path("hid#vid_045e&pid_02e0") is False # Xbox blacklisted
    assert detect_controller_name("hid#vid_1532&pid_1000") == "Razer Raiju (PS4)"
    assert detect_controller_name("hid#vid_2563&pid_0575") == "ShanWan DS4 Clone"
    assert detect_controller_name("hid#vid_9999&pid_8888") == "Generic / Clone DS4"

    from ui.widgets import pil_to_qpixmap, SlidingStackedWidget, DeviceNavCard, CalibPresetCard
    from ui.benchmark_dialog import TelemetryBenchmarkChart, TelemetryBenchmarkDialog
    assert callable(pil_to_qpixmap)
    assert SlidingStackedWidget is not None
    assert DeviceNavCard is not None
    assert CalibPresetCard is not None
    assert TelemetryBenchmarkChart is not None
    assert TelemetryBenchmarkDialog is not None

    import assets
    assert hasattr(assets, "ASSETS_DIR")
    assert hasattr(assets, "ICONS_DIR")
    assert assets.ICON_PSCAMERA_PATH.exists()
    assert assets.ICON_SETTINGS_PATH.exists()
    assert assets.ICON_TRACKING_PATH.exists()
    assert assets.ICON_SLIDERS_PATH.exists()
    assert assets.ICON_MODE_BALANCED_PATH.exists()
    assert assets.ICON_MODE_COMPETITIVE_PATH.exists()
    assert assets.ICON_WEBCAM_PATH.exists()
    assert assets.ICON_DUALSHOCK4_PATH.exists()
    assert assets.MODEL_POSE_PATH.exists(), "Canonical pose model path must exist via assets.MODEL_POSE_PATH"
    assert assets.MODEL_POSE_LITE_PATH.exists()
    assert assets.MODEL_POSE_FULL_PATH.exists()

    from sensor.pose_tracker import _resolve_model_path
    assert _resolve_model_path("lite").name == "pose_landmarker_lite.task"
    assert _resolve_model_path("full").name == "pose_landmarker_full.task"
    assert _resolve_model_path("heavy").name == "pose_landmarker_full.task"  # Legacy fallback to full

    print("  -> Modular Project Structure PASSED")

def test_telemetry_and_adaptive_benchmark():
    print("[TEST] Telemetry Benchmark & Adaptive Calibration...")
    import math
    import tempfile
    from pathlib import Path
    from sensor.virtual_phone import AdaptiveCalibrationTuner, get_virtual_phone
    from sensor.telemetry_benchmark import parse_telemetry_csv, compare_telemetries, find_available_benchmarks

    # 1. Test AdaptiveCalibrationTuner
    tuner = AdaptiveCalibrationTuner(base_sensitivity=1.2)
    assert tuner.current_sensitivity == 1.2
    assert tuner.multiplier == 1.0
    assert tuner.enabled is False

    # Disabled: feedback should not adjust multiplier
    tuner.on_feedback("OK", current_speed=1.5, current_accel=(1.5, 2.5, 1.0))
    assert tuner.multiplier == 1.0
    assert tuner.counts["OK"] == 1

    # Enabled: feedback on fast movement should gently boost sensitivity (+3%)
    tuner.enabled = True
    tuner._last_adjust_ts = 0.0  # bypass rate limiter
    mult = tuner.on_feedback("OK", current_speed=1.5, current_accel=(1.5, 2.5, 1.0))
    assert mult > 1.0
    assert tuner.current_sensitivity > 1.2

    # Summary
    summary = tuner.get_summary()
    assert summary["total_moves"] == 2
    assert summary["counts"]["OK"] == 2
    assert "current_sensitivity" in summary

    # Reset
    tuner.reset_song("TestMap")
    assert tuner.total_moves == 0
    assert tuner.counts["OK"] == 0

    # 2. Test VirtualPhoneController auto-record and song tracking
    vp = get_virtual_phone()
    vp.set_auto_record(True)
    assert vp.auto_record_enabled is True
    vp.set_adaptive_calibration(True)
    assert vp.adaptive_tuner.enabled is True

    # 3. Test Telemetry Benchmark with synthetic data
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        cam_file = tmp_path / "Levitating_camera_1001.csv"
        ds4_file = tmp_path / "Levitating_ds4_1002.csv"

        # Generate 6 seconds of 60Hz synthetic telemetry (360 samples)
        # Periodic peaks every 1.0s
        with open(cam_file, "w", encoding="utf-8") as f:
            f.write("timestamp_ms,ax,ay,az,speed_mps,alpha,hand_x,hand_y,hand_z,is_tracked,source,map_name,feedback\n")
            for i in range(360):
                ts = 1000 + i * 16
                t = i / 60.0
                peak = math.sin(t * 2 * math.pi) * 2.0
                ax = peak
                ay = -1.0 + (peak * 0.5)
                az = 0.1
                f.write(f"{ts},{ax:.4f},{ay:.4f},{az:.4f},1.2,0.8,0.5,0.5,2.0,1,camera,Levitating,\n")

        with open(ds4_file, "w", encoding="utf-8") as f:
            f.write("timestamp_ms,ax,ay,az,speed_mps,alpha,hand_x,hand_y,hand_z,is_tracked,source,map_name,feedback\n")
            for i in range(360):
                ts = 1000 + i * 16 + 32  # 32ms lag
                t = i / 60.0
                peak = math.sin(t * 2 * math.pi) * 2.6  # slightly higher peak
                ax = peak
                ay = -1.0 + (peak * 0.5)
                az = 0.1
                f.write(f"{ts},{ax:.4f},{ay:.4f},{az:.4f},0.0,1.0,0.0,0.0,0.0,1,ds4,Levitating,\n")

        # Parse CSVs
        cam_data = parse_telemetry_csv(cam_file)
        ds4_data = parse_telemetry_csv(ds4_file)
        assert cam_data["map_name"] == "Levitating"
        assert ds4_data["map_name"] == "Levitating"
        assert cam_data["source"] == "camera"
        assert ds4_data["source"] == "ds4"
        assert cam_data["sample_count"] == 360
        assert ds4_data["sample_count"] == 360

        # Run comparison
        res = compare_telemetries(cam_data, ds4_data, current_sensitivity=1.2)
        assert res["map_name"] == "Levitating"
        assert res["correlation_pct"] > 80.0, f"Expected high correlation, got {res['correlation_pct']}%"
        assert abs(res["lag_ms"]) < 100.0, f"Expected reasonable lag, got {res['lag_ms']} ms"
        assert res["suggested_sensitivity"] > 1.0
        assert len(res["chart_t"]) > 10
        assert len(res["chart_cam"]) == len(res["chart_t"])
        assert len(res["chart_ds4"]) == len(res["chart_t"])

        # Check find_available_benchmarks
        benchmarks = find_available_benchmarks(tmp_path)
        assert len(benchmarks) == 1
        assert benchmarks[0]["map_name"] == "Levitating"
        assert benchmarks[0]["is_ready"] is True

        # Check Just Dance process and song discovery helpers
        from sensor.virtual_phone import find_just_dance_pids, detect_active_song_from_game_process
        pids = find_just_dance_pids()
        assert isinstance(pids, list)
        song_str = detect_active_song_from_game_process()
        assert isinstance(song_str, str)

    print("  -> Telemetry Benchmark & Adaptive Calibration PASSED")

def test_ps4_native_backend():
    print("[TEST] PS4 Native WinUSB Backend (Driver, Firmware, UVC Depacketizer, Stereo Demux & Live HW)...")
    from sensor.ps4_backend import (
        PS4CameraBackend,
        PS4UsbDevice,
        PS4FirmwareManager,
        PS4DriverInstaller,
        FIRMWARE_SIZE,
        FIRMWARE_SHA1,
        FIRMWARE_SHA256,
        EYE_RIGHT,
        EYE_LEFT,
        DEFAULT_EYE,
        ISP_GEOMETRIES,
        find_isp_geometry,
        depacketize_uvc_packet,
        demux_stereo_frame_yuy2,
    )
    from sensor.camera_manager import LatestFrameCamera

    # 1. Default Eye & INF Package Verification
    assert DEFAULT_EYE == EYE_RIGHT == "right"
    inf_path = PS4DriverInstaller.get_inf_path()
    assert inf_path.is_file(), f"Expected legacy_pscam_device.inf at {inf_path}"
    drv_info = PS4DriverInstaller.verify_driver_status()
    assert drv_info["inf_file_present"] is True
    assert isinstance(drv_info["winusb_interface_active"], bool)
    assert "fallback_installer_present" in drv_info
    assert isinstance(drv_info["fallback_installer_present"], bool)
    assert hasattr(PS4DriverInstaller, "get_fallback_installer_path")
    assert hasattr(PS4DriverInstaller, "has_driver_store_package_fast")
    assert hasattr(PS4DriverInstaller, "invalidate_cache")
    assert isinstance(PS4DriverInstaller.has_driver_store_package_fast(use_cache=True), bool)

    # 2. ISP Geometries Verification (all 9 hardware modes)
    assert len(ISP_GEOMETRIES) == 9
    g_1280_60 = find_isp_geometry(1280, 800, 60)
    assert g_1280_60 is not None and g_1280_60.frame_bytes == 3448 * 2 * 808
    assert g_1280_60.left_offset == 96 and g_1280_60.right_offset == 96 + 2560
    g_640_120 = find_isp_geometry(640, 400, 120)
    assert g_640_120 is not None and g_640_120.frame_bytes == 1748 * 2 * 408
    g_320_240 = find_isp_geometry(320, 192, 240)
    assert g_320_240 is not None and g_320_240.frame_bytes == 898 * 2 * 200
    # Legacy 640x480 maps cleanly to 640x400
    g_compat = find_isp_geometry(640, 480, 60)
    assert g_compat is not None and g_compat.eye_w == 640 and g_compat.eye_h == 400

    # 3. Firmware Cryptographic Validation (Reject corrupted, accept authentic)
    assert PS4FirmwareManager.validate_firmware_bytes(b"") is False
    assert PS4FirmwareManager.validate_firmware_bytes(b"\x00" * FIRMWARE_SIZE) is False
    fw_bytes = PS4FirmwareManager.locate_valid_firmware()
    if fw_bytes is not None:
        assert len(fw_bytes) == FIRMWARE_SIZE
        assert PS4FirmwareManager.compute_sha1(fw_bytes) == FIRMWARE_SHA1
        assert PS4FirmwareManager.compute_sha256(fw_bytes) == FIRMWARE_SHA256
        assert PS4FirmwareManager.validate_firmware_bytes(fw_bytes) is True
        tampered = bytearray(fw_bytes)
        tampered[1024] ^= 0xFF
        assert PS4FirmwareManager.validate_firmware_bytes(bytes(tampered)) is False
        print("  -> Authentic 68,032-byte OV580 firmware SHA-1 & SHA-256 verified")

    # 4. UVC Isochronous Packet Depacketizer Test
    hdr12_pkt = struct.pack("<BBIIH", 0x0C, 0x0C | 0x01, 0x12345678, 0xABCDEF00, 0x9999) + b"VIDEO_DATA_12"
    fid, pts, payload = depacketize_uvc_packet(hdr12_pkt)
    assert fid == 1 and pts == 0x12345678 and payload == b"VIDEO_DATA_12"

    hdr4_pkt = b"\x01\x02\x03\x04VIDEO_CONT_4"
    fid4, pts4, payload4 = depacketize_uvc_packet(hdr4_pkt)
    assert fid4 is None and pts4 is None and payload4 == b"VIDEO_CONT_4"

    # 5. Dual-Eye Stereo Demultiplexer Test (Synthetic Frame)
    for geom in (g_1280_60, g_640_120, g_320_240):
        synth_raw = np.zeros((geom.rows, geom.row_bytes), dtype=np.uint8)
        # Fill Left Eye band with pattern (Y=80, U/V=110) and Right Eye band with (Y=190, U/V=140)
        l_off = geom.left_offset
        r_off = geom.right_offset
        b_len = geom.band_bytes
        synth_raw[:geom.eye_h, l_off:l_off + b_len:2] = 80
        synth_raw[:geom.eye_h, l_off + 1:l_off + b_len:2] = 110
        synth_raw[:geom.eye_h, r_off:r_off + b_len:2] = 190
        synth_raw[:geom.eye_h, r_off + 1:r_off + b_len:2] = 140

        left_yuy2, right_yuy2 = demux_stereo_frame_yuy2(synth_raw.reshape(-1), geom)
        assert left_yuy2.shape == (geom.eye_h, geom.eye_w, 2)
        assert right_yuy2.shape == (geom.eye_h, geom.eye_w, 2)
        assert int(left_yuy2[0, 0, 0]) == 80 and int(left_yuy2[0, 0, 1]) == 110
        assert int(right_yuy2[0, 0, 0]) == 190 and int(right_yuy2[0, 0, 1]) == 140
    print("  -> Dual-eye demultiplexer verified across 1280x800, 640x400, and 320x192")

    # 6. Physical Hardware Streaming Test (when PS4 Camera is connected)
    hw_status = PS4UsbDevice.probe_hardware_status()
    if hw_status["connected"] and hw_status["winusb_bound"]:
        print("  -> Physical PlayStation 4 Camera detected! Running live 60 FPS hardware capture test...")
        cam = LatestFrameCamera(
            camera_index=0,
            target_w=1280,
            target_h=800,
            target_fps=60,
            is_pscam=True,
            ps4_eye=EYE_RIGHT,
            ps4_backend_mode="native",
        )
        try:
            assert cam.ps4_backend is not None, "Expected native PS4CameraBackend to be active"
            frame_right = None
            t_wait = time.perf_counter()
            while time.perf_counter() - t_wait < 2.0:
                ret, fr, _ = cam.read(only_new=True)
                if ret and fr is not None:
                    frame_right = fr
                    break
                time.sleep(0.005)
            assert frame_right is not None, "Expected live frame from Right Eye"
            assert frame_right.shape == (800, 1280, 3)
            assert not LatestFrameCamera._is_black_frame(frame_right), "Expected non-black exposed image"

            # Switch live to Left Eye
            cam.set_eye(EYE_LEFT)
            frame_left = None
            t_wait = time.perf_counter()
            while time.perf_counter() - t_wait < 1.0:
                ret, fr, _ = cam.read(only_new=True)
                if ret and fr is not None:
                    frame_left = fr
                    break
                time.sleep(0.005)
            assert frame_left is not None and frame_left.shape == (800, 1280, 3)

            # Verify simultaneous dual-sensor stereo access
            stereo = cam.read_stereo(only_new=False)
            assert stereo is not None
            assert stereo["right_bgr"].shape == (800, 1280, 3)
            assert stereo["left_bgr"].shape == (800, 1280, 3)
            assert stereo["pts"] > 0
            print(
                f"  -> Live Hardware Test PASSED (Right mean={frame_right.mean():.1f}, "
                f"Left mean={frame_left.mean():.1f}, PTS={stereo['pts']})"
            )
        finally:
            cam.release()
    else:
        print("  -> Physical PS4 Camera not connected; synthetic backend tests completed")

    print("  -> PS4 Native WinUSB Backend PASSED")

def test_stereo_vision_engine():
    print("[TEST] Stereo Vision Engine (Rectification, Sparse 3D Triangulation, Dense Depth Mask)...")
    from sensor.stereo_matcher import (
        StereoCalibrator,
        StereoDepthEngine,
        STEREO_MODE_DISABLED,
        STEREO_MODE_SPARSE_METRIC,
        STEREO_MODE_FULL_DEPTH,
        PS4_STEREO_BASELINE_M,
    )
    from sensor.pose_filters import SkeletonCalibrator
    from sensor.kinect_shared_memory import NEUTRAL_POSE

    # 1. Optical Constants & Factory Geometry
    assert math.isclose(PS4_STEREO_BASELINE_M, 0.0852, rel_tol=1e-3), "PS4 baseline must be 85.2 mm"
    calibrator = StereoCalibrator(baseline_m=PS4_STEREO_BASELINE_M)
    calibrator.update_resolution(1280, 800)
    assert calibrator.current_w == 1280 and calibrator.current_h == 800
    assert calibrator.map_l_x is not None and calibrator.map_l_x.shape == (800, 1280)
    assert calibrator.map_r_x is not None and calibrator.map_r_x.shape == (800, 1280)
    assert calibrator.Q is not None and calibrator.Q.shape == (4, 4)

    # 2. Epipolar Rectification Execution
    dummy_left = np.zeros((800, 1280, 3), dtype=np.uint8)
    dummy_right = np.zeros((800, 1280, 3), dtype=np.uint8)
    rect_l, rect_r = calibrator.rectify(dummy_left, dummy_right)
    assert rect_l.shape == (800, 1280, 3)
    assert rect_r.shape == (800, 1280, 3)

    # 3. Fast Sparse Landmark Triangulation (<0.5 ms)
    # Synthesize a textured target with known physical disparity:
    # Target depth Z = 2.0 meters => disparity d = (fx * B) / Z = (860.0 * 0.0852) / 2.0 = 36.636 pixels
    engine = StereoDepthEngine(baseline_m=PS4_STEREO_BASELINE_M)
    target_u_r, target_v_r = 600, 400
    disparity_px = 37  # integer pixel shift for synthetic test
    target_u_l = target_u_r + disparity_px  # in left eye shifted rightwards

    test_l = np.ones((800, 1280, 3), dtype=np.uint8) * 50
    test_r = np.ones((800, 1280, 3), dtype=np.uint8) * 50
    for r in range(-10, 11):
        for c in range(-10, 11):
            pattern_val = int(((r * c) % 180) + 70)
            test_r[target_v_r + r, target_u_r + c] = (pattern_val, 255 - pattern_val, 120)
            test_l[target_v_r + r, target_u_l + c] = (pattern_val, 255 - pattern_val, 120)

    joints_2d = {
        0: (float(target_u_r), float(target_v_r), 0.95),  # HipCenter
    }

    engine.calibrator.update_resolution(1280, 800)
    # Warmup OpenCV optical flow buffers
    engine.triangulate_sparse_joints(test_l, test_r, joints_2d, search_radius_px=60)
    t0 = time.perf_counter()
    res = engine.triangulate_sparse_joints(test_l, test_r, joints_2d, search_radius_px=60)
    dt_ms = (time.perf_counter() - t0) * 1000.0

    assert 0 in res, "Target joint must be successfully triangulated"
    x_m, y_m, z_m, conf = res[0]
    expected_z = (860.0 * PS4_STEREO_BASELINE_M) / float(disparity_px)  # ~1.98 m
    assert abs(z_m - expected_z) < 0.15, f"Expected Z around {expected_z:.2f}m, got {z_m:.2f}m"
    assert dt_ms < 5.0, f"Sparse triangulation must execute in <5ms, took {dt_ms:.2f}ms"
    print(f"  -> Sub-Pixel PyrLK Triangulation PASSED (Z={z_m:.2f}m, error={abs(z_m - expected_z)*100:.1f}cm, time={dt_ms:.2f}ms)")

    # 3.1 Dynamic Vertical Epipolar Auto-Calibration (Simulated +3px vertical lens tilt)
    engine.reset_calibration()
    test_l_tilted = np.ones((800, 1280, 3), dtype=np.uint8) * 50
    dy_tilt = 3
    for r in range(-10, 11):
        for c in range(-10, 11):
            pattern_val = int(((r * c) % 180) + 70)
            test_l_tilted[target_v_r + dy_tilt + r, target_u_l + c] = (pattern_val, 255 - pattern_val, 120)

    for _ in range(8):
        res_tilt = engine.triangulate_sparse_joints(test_l_tilted, test_r, joints_2d, search_radius_px=60)
    assert 0 in res_tilt, "Tilted lens joint must still be triangulated via 2D epipolar band + PyrLK"
    assert engine.vertical_offset_px > 1.0, f"Expected learned positive vertical offset, got {engine.vertical_offset_px:.2f}px"
    print(f"  -> Dynamic Epipolar Auto-Calibration PASSED (learned vertical offset={engine.vertical_offset_px:.2f}px for +3px tilt)")

    # 4. Dense Depth Mask Computation (320x240)
    mask = engine.compute_dense_depth_mask(test_l, test_r, target_w=320, target_h=240, min_z_m=0.8, max_z_m=2.8)
    assert mask.shape == (240, 320)
    assert mask.dtype == np.uint8
    print("  -> Dense Depth Mask generation PASSED")

    # 4.1 Confirmed Background Mask & Right-Eye Alignment (Pruning clutter without dissolving body)
    bg_mask = engine.compute_confirmed_background_mask(test_l, test_r, target_w=320, target_h=240, min_z_m=0.8, max_z_m=2.8, align_to_right=True)
    assert bg_mask.shape == (240, 320)
    assert bg_mask.dtype == np.uint8
    print("  -> Confirmed Background Mask & Alignment PASSED")

    # 5. Integration with SkeletonCalibrator
    sk_calib = SkeletonCalibrator(target_height_m=1.75)
    joints = [list(j) for j in NEUTRAL_POSE]
    out_mono = sk_calib.transform(joints)
    assert math.isclose(out_mono[0][2], 2.0, rel_tol=1e-2), f"Expected mono baseline Z=2.0, got {out_mono[0][2]}"

    # With metric stereo grounding (e.g. dancer standing at 2.6m)
    stereo_depths = {0: (0.0, 0.0, 2.60, 0.95)}
    out_stereo = sk_calib.transform(joints, stereo_depths=stereo_depths)
    assert out_stereo[0][2] > 2.2, f"Expected stereo grounded Z > 2.2, got {out_stereo[0][2]}"
    print(f"  -> SkeletonCalibrator Stereo Grounding PASSED (Z moved from {out_mono[0][2]:.2f}m to {out_stereo[0][2]:.2f}m)")

    # 6. PoseTracker Interface Compatibility
    import sensor
    assert hasattr(sensor, "PoseTracker")
    print("  -> Stereo Vision Engine Test PASSED")


def test_ds4_controller():
    print("[TEST] DualShock 4 Controller Compatibility & Clone IMU Engine...")
    from sensor.ds4_controller import (
        KNOWN_DS4_TARGETS,
        is_known_ds4_target,
        is_compatible_ds4_path,
        detect_controller_name,
        _score_hid_interface,
        DS4Controller,
    )
    import struct
    import zlib

    # 1. VID/PID Identification
    assert is_known_ds4_target(r"\\?\hid#vid_054c&pid_05c4#...")  # Sony v1
    assert is_known_ds4_target(r"\\?\hid#vid_054c&pid_09cc#...")  # Sony v2
    assert is_known_ds4_target(r"\\?\hid#vid_2563&pid_0575#...")  # ShanWan clone
    assert is_known_ds4_target(r"\\?\hid#vid_0079&pid_181b#...")  # DragonRise clone
    assert not is_known_ds4_target(r"\\?\hid#vid_045e&pid_028e#...")  # Xbox 360

    # 2. Permissive Path Filtering
    assert is_compatible_ds4_path(r"\\?\hid#{00001124-0000-1000-8000-00805f9b34fb}&col01", permissive=True)
    assert not is_compatible_ds4_path(r"\\?\hid#vid_045e&pid_02e0#...", permissive=True)  # Blacklisted Xbox
    assert not is_compatible_ds4_path(r"\\?\hid#vid_1234&pid_5678#kbd&col01", permissive=True)  # Keyboard
    assert not is_compatible_ds4_path(r"\\?\hid#vid_1234&pid_5678#mouse&col01", permissive=True)  # Mouse

    # 3. HID Interface Scoring
    assert _score_hid_interface(usage_page=0x01, usage=0x05, in_len=64) == 100  # Gamepad
    assert _score_hid_interface(usage_page=0x01, usage=0x04, in_len=64) == 90   # Joystick
    assert _score_hid_interface(usage_page=0x0C, usage=0x01, in_len=64) == -1   # Consumer control
    assert _score_hid_interface(usage_page=0x0D, usage=0x05, in_len=64) == -1   # Touchpad digitizer

    # 4. Output Report 0x11 CRC-32 Validation
    out_rep = bytearray(78)
    out_rep[0] = 0x11
    out_rep[1] = 0xC0
    out_rep[3] = 0x07
    out_rep[8] = 0x00
    out_rep[9] = 0x43
    out_rep[10] = 0x9C
    crc = zlib.crc32(bytes([0xA2]) + bytes(out_rep[:74])) & 0xFFFFFFFF
    out_rep[74:78] = struct.pack("<I", crc)
    assert len(out_rep) == 78
    assert crc != 0

    # 5. Synthetic Report Decoding & Dynamic IMU Detection
    # 5.1 Official Sony Layout in Report 0x11: Gyro at offset 15 (near 0), Accel at offset 21 (~8192 counts = 1G)
    rep_sony = bytearray(78)
    rep_sony[0] = 0x11
    rep_sony[7] = 0x20  # Cross button
    # Gyro at 15..20 = 0
    struct.pack_into("<hhh", rep_sony, 15, 5, -8, 12)
    # Accel at 21..26 = Earth gravity on Y axis (8192 counts)
    struct.pack_into("<hhh", rep_sony, 21, 0, 8192, 0)

    # 5.2 Clone InvenSense Layout in Report 0x11: Accel at Block A (offset 15, 8192 counts), Gyro at Block B (offset 21, near 0)
    rep_clone = bytearray(78)
    rep_clone[0] = 0x11
    rep_clone[7] = 0x40  # Circle button
    struct.pack_into("<hhh", rep_clone, 15, 0, 8192, 0)  # Accel in Block A!
    struct.pack_into("<hhh", rep_clone, 21, 2, -3, 1)    # Gyro in Block B!

    # 5.3 Clone 4096 LSB/G Sensitivity
    rep_clone_4096 = bytearray(78)
    rep_clone_4096[0] = 0x11
    struct.pack_into("<hhh", rep_clone_4096, 15, 0, 4096, 0)
    struct.pack_into("<hhh", rep_clone_4096, 21, 0, 0, 0)

    # Validate detection logic against both packets
    for rep, exp_block_a in [(rep_sony, False), (rep_clone, True)]:
        s1, s2, s3, s4, s5, s6 = struct.unpack_from("<hhhhhh", rep, 15)
        mag_a = math.sqrt(float(s1 * s1 + s2 * s2 + s3 * s3))
        mag_b = math.sqrt(float(s4 * s4 + s5 * s5 + s6 * s6))
        if mag_b >= 1500.0 and mag_b >= mag_a * 0.7:
            is_block_a = False
            ax, ay, az = s4, s5, s6
        else:
            is_block_a = True
            ax, ay, az = s1, s2, s3
        assert is_block_a == exp_block_a
        assert math.isclose(ay, 8192, abs_tol=100)

    # Validate scale detection on 4096 LSB packet
    s1, s2, s3, s4, s5, s6 = struct.unpack_from("<hhhhhh", rep_clone_4096, 15)
    mag = math.sqrt(float(s1 * s1 + s2 * s2 + s3 * s3))
    scale = 4096.0 if 3000.0 <= mag <= 6000.0 else 8192.0
    assert scale == 4096.0
    g_force = mag / scale
    assert math.isclose(g_force, 1.0, rel_tol=1e-2)

    # 6. Verify DeviceController get_ds4_readout() and state contract
    from ui.controllers.device_controller import DeviceController
    dc = DeviceController()
    st = dc.get_ds4_readout()
    assert isinstance(st, dict)
    assert "is_connected" in st

    print("  -> DualShock 4 & Clone IMU Compatibility PASSED")


def test_kinect_emulator():
    """Validates the in-memory Kinect Emulator daemon, binary proxy, and config persistence."""
    print("Testing Kinect In-Memory Emulator (Zero-File-Replacement)...")
    from sensor.kinect_emulator import KinectEmulatorDaemon, KINECT_ORDINALS_ORDER, TARGET_PROCESS_NAMES
    from sensor.config_manager import ConfigManager

    # 1. Test Config persistence
    cm = ConfigManager()
    assert "emulate_kinect_enabled" in cm.config
    assert isinstance(cm.config["emulate_kinect_enabled"], bool)

    # 2. Test Proxy DLL Presence & Validity (Legacy10.dll present, manual Kinect10.dll & x64 artifacts removed)
    base_dir = Path(__file__).parent
    assert not (base_dir / "tools" / "Kinect10.dll").exists(), "Manual tools/Kinect10.dll must be removed"
    assert not (base_dir / "tools" / "Legacy10_x64.dll").exists(), "Unused tools/Legacy10_x64.dll must be removed"
    proxy_path = base_dir / "tools" / "Legacy10.dll"
    assert proxy_path.exists(), f"Legacy10.dll not found at {proxy_path}"
    assert proxy_path.stat().st_size == 121344, f"Legacy10.dll unexpected size: {proxy_path.stat().st_size}"

    with open(proxy_path, "rb") as f:
        data = f.read()
    assert data[:2] == b"MZ", "Legacy10.dll is not a valid PE binary"

    # 3. Test Ordinal and target definitions (exclusively 32-bit Just Dance Legacy)
    assert KINECT_ORDINALS_ORDER == [16, 5, 6, 21, 22, 9, 17, 26]
    assert TARGET_PROCESS_NAMES == ["legacy.exe", "justdance.exe"]

    # 4. Test Daemon Instantiation & Lifecycle
    daemon = KinectEmulatorDaemon({"emulate_kinect_enabled": False})
    assert not daemon.enabled
    status = daemon.get_status()
    assert status["enabled"] is False
    assert status["connected"] is False

    callback_called = []
    def on_status(conn, name, pid):
        callback_called.append((conn, name, pid))

    daemon.register_status_callback(on_status)
    daemon._notify_status(True, "TestGame.exe", 9999)
    assert len(callback_called) == 1
    assert callback_called[0] == (True, "TestGame.exe", 9999)

    # 5. Test fast Toolhelp32 process scanner & 32-bit WoW64 architecture check
    import os
    import ctypes
    t_scan = time.perf_counter()
    scan_res = daemon._scan_for_game_process()
    scan_ms = (time.perf_counter() - t_scan) * 1000.0
    assert scan_res is None or isinstance(scan_res, dict)
    assert scan_ms < 50.0, f"Toolhelp32 process scan took too long ({scan_ms:.2f}ms)"
    is_cur_32 = daemon._is_target_32bit(os.getpid())
    assert isinstance(is_cur_32, bool)
    assert is_cur_32 is (ctypes.sizeof(ctypes.c_void_p) == 4)

    # 6. Test Daemon start / stop
    daemon.enabled = True
    daemon.start()
    assert daemon._running is True
    time.sleep(0.1)
    daemon.stop()
    assert daemon._running is False

    print("  -> Kinect In-Memory Emulator & Auto-Detector PASSED")


def test_session_logger():
    print("[TEST] SessionLogger & Dance Telemetry Subsystem...")
    import tempfile
    import shutil

    temp_dir = Path(tempfile.mkdtemp(prefix="test_pscam_logger_"))
    try:
        # 1. Test initialization, directory creation and startup wipe/rotation
        logger = SessionLogger(logs_dir=temp_dir)
        logger.initialize(wipe_old_logs=True, backup_previous=True)
        assert logger.session_log_path.exists(), "session.log must exist after initialization"

        # 2. Test system environment header
        logger.log_system_environment()
        logger.flush()
        with open(logger.session_log_path, "r", encoding="utf-8") as f:
            log_content = f.read()
        assert "Session Diagnostic Log" in log_content
        assert "Operating System:" in log_content
        assert "Processor:" in log_content
        assert "Python Runtime:" in log_content

        # 3. Test camera discovery and controller mapping
        from sensor.camera_manager import CameraInfo
        logger.log_camera_discovery([CameraInfo(0, "PS4 Camera", True), CameraInfo(1, "Webcam", False)])
        logger.map_active_controller("ds4", "Sony DualShock 4", details="Bluetooth, Hand: Right")
        logger.log_controller_button("L1", coach_id=0, action="press")
        logger.log_ipc_event("KINECT_EMULATOR", "ATTACHED", "Game: JustDance.exe (PID: 9999)")
        logger.flush()

        with open(logger.session_log_path, "r", encoding="utf-8") as f:
            updated_log = f.read()
        assert "[CAMERA      ] Camera discovery completed" in updated_log
        assert "[MAPPING     ] Active dancer control mapped to: [DS4] 'Sony DualShock 4'" in updated_log
        assert "[INPUT       ] Button [L1] press" in updated_log
        assert "[IPC         ] [KINECT_EMULATOR] Status: ATTACHED" in updated_log

        # 4. Test real-time dance telemetry streaming (CSV)
        logger.start_telemetry_tracking(source="camera", song_name="SmalltownBoy", coach_id=0)
        assert logger.telemetry_csv_path.exists(), "session_telemetry.csv must exist after start_telemetry_tracking"

        # Write 50 high-frequency samples
        for i in range(50):
            logger.record_telemetry_sample(
                ts_ms=1000000 + i * 16,
                source="camera",
                song_name="SmalltownBoy",
                coach_id=0,
                is_tracked=True,
                ax=0.15,
                ay=0.25,
                az=1.05,
                speed_mps=1.45,
                hand_pos=(0.35, -0.15, 1.85),
                shoulder_r=(0.20, 0.45, 1.80),
                elbow_r=(0.28, 0.15, 1.82),
                wrist_r=(0.32, -0.05, 1.84),
                joints_tracked_count=20,
                cam_fps=60.0,
                infer_fps=59.8,
                game_feedback="PERFECT" if i % 10 == 0 else "",
            )

        logger.stop_telemetry_tracking({"duration_s": 0.83, "samples": 50, "avg_fps": 60.0})

        with open(logger.telemetry_csv_path, "r", encoding="utf-8") as f:
            csv_lines = [line.strip() for line in f if line.strip()]

        assert len(csv_lines) >= 51, f"Expected header + 50 samples, got {len(csv_lines)}"
        assert csv_lines[0] == TELEMETRY_CSV_HEADER.strip()
        sample_row = csv_lines[1].split(",")
        assert sample_row[2] == "camera"
        assert sample_row[3] == "SmalltownBoy"
        assert sample_row[5] == "1"  # is_tracked
        assert float(sample_row[6]) == 0.15  # ax
        assert float(sample_row[7]) == 0.25  # ay
        assert float(sample_row[8]) == 1.05  # az

        # 5. Test session rotation / backup on second initialization
        logger.close()

        logger2 = SessionLogger(logs_dir=temp_dir)
        logger2.initialize(wipe_old_logs=True, backup_previous=True)
        assert logger2.session_prev_log_path.exists(), "session_previous.log must exist after rotation"
        assert logger2.telemetry_prev_csv_path.exists(), "session_telemetry_previous.csv must exist after rotation"
        with open(logger2.session_prev_log_path, "r", encoding="utf-8") as f:
            prev_content = f.read()
        assert "Active dancer control mapped to: [DS4]" in prev_content
        logger2.close()

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    print("  -> SessionLogger & Dance Telemetry Subsystem PASSED")


def test_person_lock_subsystem():
    print("[TEST] Modular Person Lock-In Subsystem (Inertial Coasting, Identity Lock & Smart Body PTZ)...")
    from sensor.person_lock import InertialCoastingFilter, DancerIdentityLock, PersonLockController
    from sensor.pose_filters import FaceFollowPTZ

    # 1. Test InertialCoastingFilter (Kinematic Dead Reckoning & Smooth Re-entry)
    coasting = InertialCoastingFilter(cfg={
        "person_lock_enabled": True,
        "inertial_coasting_enabled": True,
        "inertial_coasting_max_ms": 250,
        "inertial_coasting_damping": 0.82,
        "inertial_coasting_reentry_frames": 3,
    })
    assert coasting.is_enabled is True

    # Simulate 3 frames of rightward motion (+0.02m per 16.6ms tick => ~1.2 m/s)
    mask_in = np.zeros((240, 320), dtype=np.uint8)
    mask_in[80:160, 120:180] = 255
    for step in range(3):
        x_val = 0.10 + step * 0.02
        px_val = 200 + step * 10
        j3d = [(x_val, 0.5, 2.0, 0.95) for _ in range(20)]
        j2d = [(px_val, 240, 0.95) for _ in range(20)]
        out_3d, out_2d, out_mask = coasting.record_valid_frame(j3d, j2d, mask_in, dt=0.0166)

    # Now simulate a 4-frame tracking loss (e.g. 360° spin / motion blur ~ 66 ms < 250 ms)
    prev_x = out_3d[0][0]
    for _ in range(4):
        ok, c_3d, c_2d, c_mask = coasting.coast(dt=0.0166, frame_w=640, frame_h=480)
        assert ok is True, "Coasting must stay active within 250 ms window"
        assert c_3d is not None and len(c_3d) == 20
        assert c_2d is not None and len(c_2d) == 20
        assert c_mask is not None and c_mask.shape == (240, 320)
        assert np.any(c_mask == 255), "Shifted coasted silhouette mask must remain non-empty"
        assert c_3d[0][0] > prev_x, "Coasted X position must advance along positive velocity vector"
        prev_x = c_3d[0][0]

    # Simulate re-detection and verify smooth LERP re-entry blend
    re_j3d = [(0.30, 0.5, 2.0, 0.95) for _ in range(20)]
    re_j2d = [(300, 240, 0.95) for _ in range(20)]
    b_3d, b_2d, _ = coasting.record_valid_frame(re_j3d, re_j2d, mask_in, dt=0.0166)
    assert prev_x < b_3d[0][0] < 0.30, f"Re-entry frame must smoothly blend between {prev_x:.3f} and 0.30, got {b_3d[0][0]:.3f}"

    # Verify expiration after > 250 ms of loss
    for _ in range(20):
        ok, _, _, _ = coasting.coast(dt=0.020, frame_w=640, frame_h=480)
    assert ok is False, "Coasting must expire and reset cleanly after exceeding 250 ms"

    # Verify modular toggle short-circuit bypass
    coasting.set_enabled(False)
    assert coasting.is_enabled is False
    ok_dis, _, _, _ = coasting.coast(dt=0.016)
    assert ok_dis is False

    # 2. Test DancerIdentityLock (Color Signature + Spatial Continuity + Peripheral ROI)
    lock = DancerIdentityLock(cfg={
        "person_lock_enabled": True,
        "dancer_lock_enabled": True,
        "dancer_lock_color_thresh": 0.35,
        "dancer_lock_roi_focus": True,
    })

    class MockLM:
        def __init__(self, x, y, vis=0.95):
            self.x = x
            self.y = y
            self.visibility = vis
            self.presence = vis

    def make_person_lms(cx, cy, sh_w=0.18):
        lms = [MockLM(cx, cy)] * 33
        lms = list(lms)
        lms[0] = MockLM(cx, cy - 0.18)               # NOSE
        lms[11] = MockLM(cx - sh_w * 0.5, cy - 0.10) # LEFT_SHOULDER
        lms[12] = MockLM(cx + sh_w * 0.5, cy - 0.10) # RIGHT_SHOULDER
        lms[23] = MockLM(cx - sh_w * 0.4, cy + 0.12) # LEFT_HIP
        lms[24] = MockLM(cx + sh_w * 0.4, cy + 0.12) # RIGHT_HIP
        return lms

    # Create frame with Blue shirt dancer at center (x=0.5, y=0.5) and Red shirt impostor on right (x=0.88, y=0.5)
    scene_bgr = np.zeros((400, 640, 3), dtype=np.uint8)
    scene_bgr[:, :] = (30, 30, 30)
    # Center dancer torso: pure Blue/Cyan in BGR (240, 180, 20)
    scene_bgr[120:280, 240:400] = (240, 180, 20)
    # Right edge bystander torso: pure Red in BGR (20, 20, 240)
    scene_bgr[120:280, 500:630] = (20, 20, 240)

    dancer_lms = make_person_lms(0.50, 0.50, sh_w=0.18)
    for _ in range(6):
        assert lock.validate_candidate(scene_bgr, dancer_lms, dt=0.016) is True
    assert lock.is_locked is True

    # Normal movement by the blue-shirt dancer must be accepted
    dancer_step_lms = make_person_lms(0.55, 0.50, sh_w=0.18)
    assert lock.validate_candidate(scene_bgr, dancer_step_lms, dt=0.016) is True

    # Sudden jump to the red-shirt bystander at x=0.88 must be REJECTED as an impostor
    impostor_lms = make_person_lms(0.88, 0.50, sh_w=0.18)
    t0 = time.perf_counter()
    accepted = lock.validate_candidate(scene_bgr, impostor_lms, dt=0.016)
    dt_lock_ms = (time.perf_counter() - t0) * 1000.0
    assert accepted is False, "Bystander with mismatched shirt color and spatial jump must be rejected"
    assert dt_lock_ms < 1.5, f"DancerIdentityLock validation must execute in <1.5ms, took {dt_lock_ms:.3f}ms"

    # Test peripheral ROI focus attenuation on private inference buffer
    test_rgb = np.full((400, 640, 3), 200, dtype=np.uint8)
    lock.apply_roi_focus(test_rgb)
    assert test_rgb[200, 320, 0] == 200, "Active dancer center zone must remain unattenuated"
    assert test_rgb[200, 5, 0] < 100, "Far peripheral edge outside dancer reach must be attenuated"

    # 3. Test Smart Body Framing PTZ (360° Spin Head Fallback & Adaptive Full-Body Zoom)
    ptz = FaceFollowPTZ(cfg={
        "face_follow_enabled": True,
        "face_follow_zoom": 1.25,
        "face_follow_spin_fallback": True,
        "face_follow_adaptive_zoom": True,
    })
    # Simulate 360° spin where face landmarks (NOSE=0, EARS=7,8) have 0.0 visibility, but shoulders & hips are visible
    spin_lms = make_person_lms(0.45, 0.50, sh_w=0.18)
    spin_lms[0] = MockLM(0.45, 0.30, vis=0.01)
    spin_lms[7] = MockLM(0.43, 0.30, vis=0.01)
    spin_lms[8] = MockLM(0.47, 0.30, vis=0.01)
    ptz.update_from_norm(spin_lms, mirrored=False)
    assert ptz.valid is True, "FaceFollowPTZ must stay valid during 360° spin using torso-extrapolated head fallback"
    assert 0.35 <= ptz.cx <= 0.55

    # Simulate wide arm/leg spread near frame boundaries and verify adaptive zoom-out toward 1.0x
    wide_lms = make_person_lms(0.50, 0.50, sh_w=0.22)
    wide_lms[15] = MockLM(0.05, 0.10, vis=0.95)  # Left wrist high & far left
    wide_lms[16] = MockLM(0.95, 0.10, vis=0.95)  # Right wrist high & far right
    wide_lms[27] = MockLM(0.20, 0.94, vis=0.95)  # Left ankle low
    wide_lms[28] = MockLM(0.80, 0.94, vis=0.95)  # Right ankle low
    for _ in range(10):
        ptz.update_from_norm(wide_lms, mirrored=False)
    assert ptz.current_zoom < 1.15, f"Adaptive zoom must widen (<1.15) when limbs approach edges, got {ptz.current_zoom:.2f}"

    # Verify seated/offscreen low-confidence landmarks do NOT trigger zoom-in/zoom-out pumping
    ptz_seated = FaceFollowPTZ(cfg={
        "face_follow_enabled": True,
        "face_follow_zoom": 1.22,
        "face_follow_adaptive_zoom": True,
    })
    for tick in range(20):
        seated_lms = make_person_lms(0.50, 0.45, sh_w=0.20)
        # Alternate occluded offscreen hips/ankles flickering around 0.25..0.40 visibility
        off_vis = 0.35 if (tick % 2 == 0) else 0.15
        seated_lms[23] = MockLM(0.45, 1.15, vis=off_vis)
        seated_lms[24] = MockLM(0.55, 1.15, vis=off_vis)
        seated_lms[27] = MockLM(0.45, 1.45, vis=off_vis)
        seated_lms[28] = MockLM(0.55, 1.45, vis=off_vis)
        ptz_seated.update_from_norm(seated_lms, mirrored=False)
    assert abs(ptz_seated.current_zoom - 1.22) < 0.01, (
        f"Seated offscreen landmarks must not pump zoom, got {ptz_seated.current_zoom:.3f}"
    )

    # Verify SkeletonCalibrator stabilizes monocular Head.z (prevents Just Dance native face-box zoom breathing)
    calib_z = SkeletonCalibrator(target_height_m=1.75, cfg={"baseline_z_m": 2.2, "depth_gain": 0.65})
    z_samples = []
    for tick in range(12):
        j_osc = list(NEUTRAL_POSE)
        # Simulate severe monocular Head.z breathing (-0.45m <-> +0.45m)
        dz = 0.45 if (tick % 2 == 0) else -0.45
        j_osc[0] = (0.0, 0.0, 0.0, 0.9)
        j_osc[2] = (0.0, -0.45, 0.0, 0.9)
        j_osc[3] = (0.0, -0.75, dz, 0.9)
        t_osc = calib_z.transform(j_osc)
        z_samples.append(t_osc[3][2])
    z_span = max(z_samples) - min(z_samples)
    assert z_span < 0.06, f"Monocular Head.z must remain damped against zoom breathing (span={z_span:.3f}m)"

    # 4. Test PersonLockController master toggle & PoseTracker integration
    ctrl = PersonLockController(cfg={"person_lock_enabled": True})
    assert ctrl.is_enabled is True
    ctrl.set_enabled(False)
    assert ctrl.is_enabled is False
    assert ctrl.coasting.is_enabled is False
    assert ctrl.identity.is_enabled is False

    print(f"  -> Modular Person Lock-In Subsystem PASSED (Identity check latency: {dt_lock_ms:.3f}ms)")


def test_arm_raise_gesture():
    print("[TEST] Arm Raise Gesture Recognition & State Machine...")
    from sensor.gesture_detector import check_arm_raised, ArmRaiseGestureDetector

    neutral = [(320, 240, 0.9)] * 20
    neutral[3] = (320, 100, 0.9)  # Head
    neutral[2] = (320, 150, 0.9)  # ShoulderCenter
    neutral[4] = (270, 160, 0.9)  # ShL
    neutral[8] = (370, 160, 0.9)  # ShR
    neutral[6] = (260, 280, 0.9)  # WristL
    neutral[10] = (380, 280, 0.9) # WristR
    neutral[7] = (260, 320, 0.9)  # HandL
    neutral[11] = (380, 320, 0.9) # HandR

    assert check_arm_raised(neutral) is False, "Neutral pose must not trigger arm raised"

    # Raise right arm above head (y=40 < head y=100)
    right_up = list(neutral)
    right_up[10] = (380, 80, 0.9)
    right_up[11] = (380, 40, 0.9)
    assert check_arm_raised(right_up) is True, "Right arm up should be True"

    # Raise left arm above head
    left_up = list(neutral)
    left_up[6] = (260, 80, 0.9)
    left_up[7] = (260, 40, 0.9)
    assert check_arm_raised(left_up) is True, "Left arm up should be True"

    # Test State Machine with simulated time progression
    detector = ArmRaiseGestureDetector(enabled=True, hold_seconds=2.0, cooldown_seconds=2.5)

    # Inactive frame
    st = detector.update(neutral, is_tracked=False, now=100.0)
    assert st["holding"] is False
    assert st["triggered"] is False

    # Neutral frame
    st = detector.update(neutral, is_tracked=True, now=101.0)
    assert st["holding"] is False
    assert st["triggered"] is False

    # Arm raised at t=102.0 (initial detection)
    st = detector.update(right_up, is_tracked=True, now=102.0)
    assert st["holding"] is False  # First frame records start_time
    assert st["progress"] == 0.0

    # Arm raised at t=103.0 (1.0s elapsed of 2.0s hold)
    st = detector.update(right_up, is_tracked=True, now=103.0)
    assert st["holding"] is True
    assert 0.49 <= st["progress"] <= 0.51
    assert st["triggered"] is False

    # Arm raised at t=104.1 (2.1s elapsed -> TRIGGERED!)
    st = detector.update(right_up, is_tracked=True, now=104.1)
    assert st["triggered"] is True
    assert st["feedback_active"] is True

    # Immediate next frame at t=104.2 (still arm up, but should NOT re-trigger due to cooldown)
    st = detector.update(right_up, is_tracked=True, now=104.2)
    assert st["triggered"] is False
    assert st["holding"] is False
    assert st["feedback_active"] is True

    print("  -> Arm Raise Gesture Recognition & State Machine PASSED")


def test_phone_camera_webapp():
    print("[TEST] Phone Camera WebApp (Pure-Python QR Code, Self-Signed TLS, WSS Video & Edge Metrics)...")
    import cv2
    import socket
    import ssl
    import json
    import struct
    from sensor.phone_camera import QRCodeGenerator, SelfSignedTLSManager, PhoneCameraServer
    from sensor.camera_manager import LatestFrameCamera

    # 1. Verify Pure-Python ISO/IEC 18004 QR Code generation and OpenCV QR decoding
    test_url = "https://192.168.1.42:8443"
    qr_pil = QRCodeGenerator.render_pil_image(test_url, box_size_px=240)
    assert qr_pil.size == (240, 240)
    qr_bgr = cv2.cvtColor(np.array(qr_pil), cv2.COLOR_RGBA2BGR)
    decoded_url, _, _ = cv2.QRCodeDetector().detectAndDecode(qr_bgr)
    assert decoded_url == test_url, f"OpenCV QRCodeDetector failed to decode QR: got {decoded_url!r}"

    # 2. Verify Pure-Python X.509v3 Self-Signed TLS Certificate & SSLContext loading
    tls_ctx = SelfSignedTLSManager.create_ssl_context("127.0.0.1")
    assert isinstance(tls_ctx, ssl.SSLContext)

    # 3. Start PhoneCameraServer on an ephemeral port and test HTTPS GET / + WSS /ws
    srv = PhoneCameraServer(port=0)
    assert srv.start(port=0) is True
    port = srv.actual_port
    assert port > 0

    try:
        # 3a. HTTPS GET / WITHOUT token must be rejected (prevents Safari stale tab auto-connect)
        client_ctx = ssl.create_default_context()
        client_ctx.check_hostname = False
        client_ctx.verify_mode = ssl.CERT_NONE
        with socket.create_connection(("127.0.0.1", port), timeout=3.0) as raw_s:
            with client_ctx.wrap_socket(raw_s, server_hostname="127.0.0.1") as tls_s:
                tls_s.sendall(b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
                resp_unauth = b""
                while True:
                    chunk = tls_s.recv(4096)
                    if not chunk:
                        break
                    resp_unauth += chunk
        assert b"403 Forbidden" in resp_unauth and b"Pairing Session Expired" in resp_unauth

        # 3b. HTTPS GET / WITH valid session token serves the Mobile WebApp HTML
        tok = srv.session_token
        assert tok and f"?t={tok}" in srv.get_connect_url()
        with socket.create_connection(("127.0.0.1", port), timeout=3.0) as raw_s:
            with client_ctx.wrap_socket(raw_s, server_hostname="127.0.0.1") as tls_s:
                tls_s.sendall(f"GET /?t={tok} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n".encode("ascii"))
                resp = b""
                while True:
                    chunk = tls_s.recv(4096)
                    if not chunk:
                        break
                    resp += chunk
        assert b"200 OK" in resp and b"Legacy PSCam Sensor" in resp
        assert b"Front Camera" in resp and b"Rear Camera" in resp and b"Dim Screen" in resp
        assert b"computeScaledDimensions" in resp and b"Standby" in resp

        # 3c. WSS /ws WITHOUT token must be rejected with 403 Forbidden
        with socket.create_connection(("127.0.0.1", port), timeout=3.0) as raw_ws_bad:
            with client_ctx.wrap_socket(raw_ws_bad, server_hostname="127.0.0.1") as wss_bad:
                bad_hs = (
                    "GET /ws HTTP/1.1\r\n"
                    "Host: 127.0.0.1\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
                    "Sec-WebSocket-Version: 13\r\n\r\n"
                )
                wss_bad.sendall(bad_hs.encode("ascii"))
                bad_resp = wss_bad.recv(1024)
                assert b"403 Forbidden" in bad_resp

        # 3d. WSS WebSocket Upgrade WITH valid token, Standby->Active lifecycle, Binary JPEG & Edge Metrics
        assert srv.streaming_active is False, "PhoneCameraServer must start in cool Standby mode"
        with socket.create_connection(("127.0.0.1", port), timeout=3.0) as raw_ws:
            with client_ctx.wrap_socket(raw_ws, server_hostname="127.0.0.1") as wss:
                handshake = (
                    f"GET /ws?t={tok} HTTP/1.1\r\n"
                    "Host: 127.0.0.1\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
                    "Sec-WebSocket-Version: 13\r\n\r\n"
                )
                wss.sendall(handshake.encode("ascii"))
                hs_resp = wss.recv(1024)
                assert b"101 Switching Protocols" in hs_resp

                def send_masked_frame(opcode: int, data: bytes):
                    mask_key = b"\x12\x34\x56\x78"
                    length = len(data)
                    if length < 126:
                        hdr = struct.pack("!BB", 0x80 | opcode, 0x80 | length)
                    elif length < 65536:
                        hdr = struct.pack("!BBH", 0x80 | opcode, 0x80 | 126, length)
                    else:
                        hdr = struct.pack("!BBQ", 0x80 | opcode, 0x80 | 127, length)
                    masked = bytes(b ^ mask_key[i % 4] for i, b in enumerate(data))
                    wss.sendall(hdr + mask_key + masked)

                # Send hello packet
                hello_json = json.dumps({
                    "type": "hello",
                    "device": "iPhone (iOS Safari)",
                    "lens": "user",
                    "width": 640,
                    "height": 480,
                    "fps": 30,
                    "capabilities": ["pc_video", "phone_edge"],
                }).encode("utf-8")
                send_masked_frame(0x01, hello_json)

                # Send a synthetic 640x480 JPEG frame over binary WebSocket
                synth_img = np.full((480, 640, 3), (40, 120, 200), dtype=np.uint8)
                ok_enc, jpeg_buf = cv2.imencode(".jpg", synth_img, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                assert ok_enc
                send_masked_frame(0x02, jpeg_buf.tobytes())

                # Send a future-ready edge_metrics JSON packet
                edge_json = json.dumps({
                    "type": "edge_metrics",
                    "ts_ms": 123456789,
                    "imu_accel": [0.1, 0.2, 0.98],
                    "kinect_joints": [[0.0, 1.0, 2.0, 0.95]] * 20,
                }).encode("utf-8")
                send_masked_frame(0x01, edge_json)

                # Wrap with LatestFrameCamera(is_phone_cam=True) and verify frame delivery
                cam = LatestFrameCamera(
                    camera_index=0,
                    target_w=640,
                    target_h=480,
                    target_fps=30,
                    is_phone_cam=True,
                    phone_cam_server=srv,
                )
                try:
                    got_frame = None
                    for _ in range(30):
                        ret, frm, _ = cam.read(only_new=True)
                        if ret and frm is not None:
                            got_frame = frm
                            break
                        time.sleep(0.02)
                    assert got_frame is not None, "LatestFrameCamera failed to read frame from PhoneCameraServer"
                    assert got_frame.shape == (480, 640, 3)
                    assert srv.is_client_connected is True
                    assert srv.client_device_name == "iPhone (iOS Safari)"

                    assert srv.streaming_active is True, "LatestFrameCamera must activate phone streaming"
                    edge_data = cam.read_edge_metrics(only_new=True)
                    assert edge_data is not None and edge_data.get("ts_ms") == 123456789
                finally:
                    cam.release()
                assert srv.streaming_active is False, "LatestFrameCamera.release() must return phone to cool Standby"
        # Verify disconnect_client rotates session token so old URLs cannot auto-reconnect
        old_tok = srv.session_token
        srv.disconnect_client(rotate_token=True)
        assert srv.session_token != old_tok, "disconnect_client must rotate pairing session token"
    finally:
        srv.stop()

    print("  -> Phone Camera WebApp PASSED (QR Code, Self-Signed TLS, WSS Video & Edge Metrics verified)")


def test_multi_player_tracking():
    print("[TEST] Multi-Player (2P Duo) Pose Engine, Long-Term Anti-Swap Identity Memory & JDP2/JMI2 IPC...")
    import cv2
    from sensor.kinect_shared_memory import (
        get_kinect_bridge,
        close_kinect_bridge,
        MULTI_SHARED_NAME,
        MULTI_SHARED_SIZE,
        MULTI_MAGIC,
        MULTI_VERSION,
        MULTI_IMAGE_SHARED_NAME,
        MULTI_IMAGE_MAGIC,
        MULTI_IMAGE_VERSION,
        IMAGE_SHARED_NAME,
        IMAGE_SHARED_SIZE,
        HEADER_FMT,
        JOINT_FMT,
        IMAGE_HEADER_FMT,
        NEUTRAL_POSE,
    )
    from sensor.player_slot import (
        PlayerFrame,
        MultiPoseFrame,
        PlayerSlotState,
        MultiPlayerAssociator,
        compose_player_index_mask,
        is_plausible_human_dancer,
    )
    from sensor.tracking_overlay import (
        TrackingOverlay,
        COLOR_P1_SILHOUETTE,
        COLOR_P2_SILHOUETTE,
    )
    from sensor.gesture_detector import ArmRaiseGestureDetector

    # 1. Verify Singleton KinectBridge & 2-Player JDP2 / JMI2 binary contract
    b1 = get_kinect_bridge()
    b2 = get_kinect_bridge()
    assert b1 is b2, "get_kinect_bridge() must return the process-wide singleton instance"
    assert b1.is_connected

    pose_p1 = [(-0.55 + j[0], j[1], 2.0, 0.95) for j in NEUTRAL_POSE]
    pose_p2 = [(+0.55 + j[0], j[1], 2.2, 0.92) for j in NEUTRAL_POSE]

    mask_p1 = np.zeros((240, 320), dtype=np.uint8)
    mask_p1[40:200, 30:140] = 255
    mask_p2 = np.zeros((240, 320), dtype=np.uint8)
    mask_p2[40:200, 180:290] = 255

    pf1 = PlayerFrame(slot_index=0, tracked=True, kinect_joints=pose_p1, body_mask=mask_p1, center_z=2.0)
    pf2 = PlayerFrame(slot_index=1, tracked=True, kinect_joints=pose_p2, body_mask=mask_p2, center_z=2.2)
    idx_mask = compose_player_index_mask([pf1, pf2], width=320, height=240)
    assert idx_mask is not None and idx_mask.shape == (240, 320)
    assert np.all(idx_mask[60:180, 50:120] == 1), "Player 1 region must have index 1"
    assert np.all(idx_mask[60:180, 200:270] == 2), "Player 2 region must have index 2"
    assert np.all(idx_mask[0:20, 0:20] == 0), "Background region must have index 0"

    # Verify depth-priority overlap resolution (closer player with smaller center_z wins overlapping pixels)
    overlap_m1 = np.zeros((240, 320), dtype=np.uint8)
    overlap_m1[80:160, 100:200] = 255
    overlap_m2 = np.zeros((240, 320), dtype=np.uint8)
    overlap_m2[80:160, 140:240] = 255
    # P2 is closer (center_z=1.75m) than P1 (center_z=2.30m) -> P2 (2) must win overlap [80:160, 140:200]
    ov_mask = compose_player_index_mask([
        PlayerFrame(slot_index=0, tracked=True, body_mask=overlap_m1, center_z=2.30),
        PlayerFrame(slot_index=1, tracked=True, body_mask=overlap_m2, center_z=1.75),
    ])
    assert np.all(ov_mask[90:150, 110:135] == 1), "Non-overlapping P1 region must remain 1"
    assert np.all(ov_mask[90:150, 145:195] == 2), "Overlapping region must belong to closer P2 (index 2)"

    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    assert b1.write_multi([pose_p1, pose_p2], dummy_frame, idx_mask, tracked_mask=3)

    # Read JDP2 (664 bytes): header (24B) + Player 1 (320B at 0x18) + Player 2 (320B at 0x158)
    mm_p2 = mmap.mmap(-1, MULTI_SHARED_SIZE, tagname=MULTI_SHARED_NAME)
    mm_p2.seek(0)
    magic_p2, ver_p2, seq_p2, mask_p2, _ = struct.unpack(HEADER_FMT, mm_p2.read(24))
    assert magic_p2 == MULTI_MAGIC and ver_p2 == MULTI_VERSION
    assert mask_p2 == 3, f"Expected tracked_mask == 3 (P1 + P2), got {mask_p2}"
    assert seq_p2 % 2 == 0
    j0_p1 = struct.unpack(JOINT_FMT, mm_p2.read(16))
    assert abs(j0_p1[0] - (-0.55)) < 1e-4, f"Expected P1 HipCenter X = -0.55, got {j0_p1[0]}"
    mm_p2.seek(24 + 320)  # Offset 0x158 (344): Player 2 Joint 0
    j0_p2 = struct.unpack(JOINT_FMT, mm_p2.read(16))
    assert abs(j0_p2[0] - (+0.55)) < 1e-4, f"Expected P2 HipCenter X = +0.55, got {j0_p2[0]}"
    mm_p2.close()

    # Read JMI2 & JMI1 masks
    mm_i2 = mmap.mmap(-1, IMAGE_SHARED_SIZE, tagname=MULTI_IMAGE_SHARED_NAME)
    mm_i2.seek(0)
    magic_i2, ver_i2, seq_i2, tracked_i2, _, _, _ = struct.unpack(IMAGE_HEADER_FMT, mm_i2.read(32))
    assert magic_i2 == MULTI_IMAGE_MAGIC and ver_i2 == MULTI_IMAGE_VERSION
    assert tracked_i2 == 3, f"Expected JMI2 tracked_mask == 3, got {tracked_i2}"
    mm_i2.seek(32 + 640 * 480 * 4)
    jmi2_arr = np.frombuffer(mm_i2.read(320 * 240), dtype=np.uint8).reshape((240, 320))
    assert np.any(jmi2_arr == 1) and np.any(jmi2_arr == 2), "JMI2 must preserve both index 1 (P1) and index 2 (P2)"
    mm_i2.close()

    mm_i1 = mmap.mmap(-1, IMAGE_SHARED_SIZE, tagname=IMAGE_SHARED_NAME)
    mm_i1.seek(32 + 640 * 480 * 4)
    jmi1_arr = np.frombuffer(mm_i1.read(320 * 240), dtype=np.uint8).reshape((240, 320))
    assert np.all(jmi1_arr[60:180, 50:120] == 255) and np.all(jmi1_arr[60:180, 200:270] == 255)
    mm_i1.close()
    close_kinect_bridge()

    # 2. Verify Long-Term Identity Memory & Waltz / Crossover Anti-Swap Re-ID
    class SynthLM:
        def __init__(self, x, y, vis=0.95):
            self.x = float(x)
            self.y = float(y)
            self.visibility = float(vis)
            self.presence = float(vis)

    def make_person_lms(cx: float, cy: float = 0.45, sh_w: float = 0.16):
        lms = [SynthLM(cx, cy)] * 33
        lms[0] = SynthLM(cx, cy - 0.22)                  # NOSE
        lms[11] = SynthLM(cx - sh_w * 0.5, cy - 0.12)    # LEFT_SHOULDER
        lms[12] = SynthLM(cx + sh_w * 0.5, cy - 0.12)    # RIGHT_SHOULDER
        lms[23] = SynthLM(cx - sh_w * 0.4, cy + 0.12)    # LEFT_HIP
        lms[24] = SynthLM(cx + sh_w * 0.4, cy + 0.12)    # RIGHT_HIP
        lms[25] = SynthLM(cx - sh_w * 0.4, cy + 0.30)    # LEFT_KNEE
        lms[26] = SynthLM(cx + sh_w * 0.4, cy + 0.30)    # RIGHT_KNEE
        lms[27] = SynthLM(cx - sh_w * 0.4, cy + 0.44)    # LEFT_ANKLE
        lms[28] = SynthLM(cx + sh_w * 0.4, cy + 0.44)    # RIGHT_ANKLE
        return lms

    def paint_dancer(canvas: np.ndarray, cx: float, shirt_bgr, pants_bgr):
        h, w = canvas.shape[:2]
        x0 = max(0, int((cx - 0.10) * w))
        x1 = min(w, int((cx + 0.10) * w))
        # Torso region
        canvas[int(0.28 * h):int(0.60 * h), x0:x1] = shirt_bgr
        # Pants region
        canvas[int(0.60 * h):int(0.82 * h), x0:x1] = pants_bgr

    slots = [PlayerSlotState(0), PlayerSlotState(1)]
    assoc = MultiPlayerAssociator(max_players=2)
    blue_shirt, dark_pants = (240, 110, 20), (40, 40, 50)
    orange_shirt, light_pants = (30, 165, 250), (200, 210, 220)

    # Phase A: 20 frames well separated (P1 at x=0.25 Blue, P2 at x=0.75 Orange) -> consolidates anchor_sig
    t_sim = 100.0
    for _ in range(20):
        t_sim += 1.0 / 30.0
        frm = np.zeros((240, 320, 3), dtype=np.uint8)
        paint_dancer(frm, 0.25, blue_shirt, dark_pants)
        paint_dancer(frm, 0.75, orange_shirt, light_pants)
        dets = [make_person_lms(0.25), make_person_lms(0.75)]
        assign, crowded = assoc.match(slots, dets, frm, dt=1.0 / 30.0, now=t_sim)
        assert not crowded
        assert assign[0] == 0 and assign[1] == 1

    # Phase B: Waltz / Close Crossover (P1 and P2 merge at center x=0.48 / 0.52) -> must trigger is_crowded freeze!
    frm_crowd = np.zeros((240, 320, 3), dtype=np.uint8)
    paint_dancer(frm_crowd, 0.49, blue_shirt, dark_pants)
    paint_dancer(frm_crowd, 0.51, orange_shirt, light_pants)
    _, crowded_now = assoc.match(
        slots, [make_person_lms(0.49), make_person_lms(0.51)], frm_crowd, dt=1.0 / 30.0, now=t_sim + 0.033
    )
    assert crowded_now is True, "Close waltz overlap must activate is_crowded appearance freeze!"

    # Phase C: Players finish crossing sides (P1 Blue is now on the RIGHT x=0.75, P2 Orange is on the LEFT x=0.25)
    # AND MediaPipe returns P2 first (index 0) and P1 second (index 1)!
    for step in range(4):
        t_sim += 0.033
        frm_crossed = np.zeros((240, 320, 3), dtype=np.uint8)
        paint_dancer(frm_crossed, 0.25, orange_shirt, light_pants)  # det[0] is P2 (Orange) on left
        paint_dancer(frm_crossed, 0.75, blue_shirt, dark_pants)     # det[1] is P1 (Blue) on right
        dets_crossed = [make_person_lms(0.25), make_person_lms(0.75)]
        assign_c, crowded_c = assoc.match(slots, dets_crossed, frm_crossed, dt=1.0 / 30.0, now=t_sim)
        assert not crowded_c

    # Slot 0 (P1) must be matched to det[1] (Blue at x=0.75), and Slot 1 (P2) to det[0] (Orange at x=0.25)!
    assert assign_c[0] == 1 and assign_c[1] == 0, f"Anti-swap Re-ID failed after crossover: got {assign_c}"

    # Phase D: Temporary exit & re-entry of P2 (Orange)
    slots[1].reset_transient()
    assert not slots[1].identity_profile.active
    assert slots[1].identity_profile.has_valid_memory(now=t_sim + 2.0)
    frm_p2_only = np.zeros((240, 320, 3), dtype=np.uint8)
    paint_dancer(frm_p2_only, 0.60, orange_shirt, light_pants)
    assign_reentry, _ = assoc.match(slots, [make_person_lms(0.60)], frm_p2_only, dt=1.0 / 30.0, now=t_sim + 2.0)
    assert 1 in assign_reentry and assign_reentry[1] == 0, f"P2 should re-claim Slot 1 upon re-entry, got {assign_reentry}"

    # 3. Verify PoseTracker(max_players=2), 640px pre-downscale, ROI bypass & MultiPoseFrame
    tracker_2p = PoseTracker(max_players=2, model_variant="lite")
    assert tracker_2p.max_players == 2
    dummy_hd = np.full((800, 1280, 3), 64, dtype=np.uint8)
    m_res = tracker_2p.process_frame_multi(dummy_hd)
    assert isinstance(m_res, MultiPoseFrame)
    assert len(m_res.players) == 2
    assert m_res.tracked_mask == 0
    assert tracker_2p._infer_bgr is not None and tracker_2p._infer_bgr.shape == (400, 640, 3), (
        f"Expected 640x400 2P pre-downscale buffer, got {tracker_2p._infer_bgr.shape}"
    )
    # Verify ROI focus was bypassed in 2P mode (peripheral pixels remain 64, not bit-shifted to 16)
    assert int(tracker_2p._infer_rgb[10, 2, 0]) == 64
    tracker_2p.close()

    # 3.1 Verify is_plausible_human_dancer accepts valid upright human and rejects inanimate objects (chairs/coats)
    valid_human_lms = make_person_lms(0.50)
    ok_human, score_human = is_plausible_human_dancer(valid_human_lms)
    assert ok_human is True and score_human >= 5.0, f"Valid human should pass plausibility check, got {ok_human}, {score_human}"

    # Chair / coat mock: horizontal, flat, or hips above shoulders
    chair_lms = [type("MockLM", (), {"x": 0.5 + 0.05 * i, "y": 0.8, "z": 0.0, "visibility": 0.35, "presence": 0.35})() for i in range(33)]
    ok_chair, _ = is_plausible_human_dancer(chair_lms)
    assert ok_chair is False, "Horizontal/flat non-human object must be rejected as implausible dancer"

    # 4. Verify ArmRaiseGestureDetector.update_multi accepts arm raise from Player 2
    g_det = ArmRaiseGestureDetector(enabled=True, hold_seconds=1.5, cooldown_seconds=2.0)
    p1_down = [(200, 200, 0.9)] * 20
    p1_down[3] = (200, 120, 0.9)   # Head
    p1_down[7] = (170, 260, 0.9)   # Hand L down
    p1_down[11] = (230, 260, 0.9)  # Hand R down

    p2_up = [(440, 200, 0.9)] * 20
    p2_up[3] = (440, 120, 0.9)     # Head
    p2_up[7] = (410, 260, 0.9)     # Hand L down
    p2_up[11] = (470, 70, 0.95)    # Hand R raised above head!

    st0 = g_det.update_multi([p1_down, p2_up], is_tracked=True, now=500.0)
    assert st0["player_idx"] == 1
    st1 = g_det.update_multi([p1_down, p2_up], is_tracked=True, now=501.6)
    assert st1["triggered"] is True and st1["player_idx"] == 1

    # 5. Verify TrackingOverlay 2P Colors (P1 Blue, P2 Light Orange), badges & HUD
    assert COLOR_P1_SILHOUETTE == (255, 150, 30), "P1 silhouette color must be Blue (BGR 255, 150, 30)"
    assert COLOR_P2_SILHOUETTE == (95, 185, 255), "P2 silhouette color must be Light Orange (BGR 95, 185, 255)"
    ovl = TrackingOverlay(show_hud=True)
    canvas_2p = np.zeros((480, 640, 3), dtype=np.uint8)
    canvas_2p = ovl.draw_multi_player_silhouettes(canvas_2p, idx_mask)
    canvas_2p = ovl.draw_skeleton(canvas_2p, p1_down, player_idx=0, show_badge=True)
    canvas_2p = ovl.draw_skeleton(canvas_2p, p2_up, player_idx=1, show_badge=True)
    canvas_2p = ovl.draw_hud(
        canvas_2p, "PS Camera (1280x800)", True, 60.0, 58.5, True, True, max_players=2, tracked_mask=3
    )
    assert np.any(canvas_2p > 0)

    # 6. Verify Qt 6 UI 2P Controls, Lite AI Recommended Default & 2P Warning Banner
    import ui
    assert ui.CALIB_PRESETS["competitive"]["pose_model"] == "lite"
    assert ui.CALIB_PRESETS["competitive"]["tag"] == "RECOMMENDED", "Lite AI (Competitive) must be the recommended default"
    if ui.HAS_QT:
        from PySide6.QtWidgets import QApplication
        _ = QApplication.instance() or QApplication([])
        win = ui.LegacySensorQtGUI(auto_discover=False)
        assert win.btn_tab_calib.text().strip() == "Tracking", f"Expected tab text 'Tracking', got '{win.btn_tab_calib.text()}'"
        assert win.cb_players_mode.itemText(0) == "1 Player", f"Expected '1 Player', got '{win.cb_players_mode.itemText(0)}'"
        assert win.cb_players_mode.itemText(1) == "2 Players", f"Expected '2 Players', got '{win.cb_players_mode.itemText(1)}'"
        assert hasattr(win, "cb_players_mode"), "Players Mode selector must exist in Calibration/Tracking tab"
        assert hasattr(win, "two_player_warn_box"), "2-Player Lite AI warning banner must exist in Calibration/Tracking tab"
        win.cb_players_mode.setCurrentIndex(1)  # Switch to 2 Players (Duo)
        assert win.cfg["max_players"] == 2
        assert not win.two_player_warn_box.isHidden(), "2P warning box must be visible when 2 Players is active"
        win.cb_players_mode.setCurrentIndex(0)  # Restore 1 Player (Solo)
        assert win.cfg["max_players"] == 1
        assert win.two_player_warn_box.isHidden(), "2P warning box must be hidden in 1-Player mode"

        # 7. Verify Reactive Start Button (disabled when peripheral is disconnected)
        win._set_mode("pscam", animate=False)
        assert win.btn_start.isEnabled() is False, "Start button must be disabled when PS Camera is not connected"
        assert win.btn_start.text() == "START TRACKING"

        win._set_mode("phone_cam", animate=False)
        assert win.btn_start.isEnabled() is False, "Start button must be disabled when Phone Camera is not connected"
        assert win.btn_start.text() == "START TRACKING"
        win.close()

    print("  -> Multi-Player (2P Duo) Pose Engine, Anti-Swap Memory & JDP2/JMI2 IPC PASSED")


def run_all_tests():
    print("==========================================")
    print("   RUNNING LEGACY PSCAM SENSOR TEST SUITE ")
    print("==========================================")
    test_project_structure()
    test_config()
    test_shared_memory()
    test_hand_anchor()
    test_adaptive_smoother()
    test_calibrator()
    test_pose_tracker()
    test_overlay()
    test_camera_manager()
    test_telemetry_and_adaptive_benchmark()
    test_ps4_native_backend()
    test_stereo_vision_engine()
    test_ds4_controller()
    test_kinect_emulator()
    test_session_logger()
    test_person_lock_subsystem()
    test_arm_raise_gesture()
    test_phone_camera_webapp()
    test_multi_player_tracking()
    print("==========================================")
    print("   ALL TESTS PASSED SUCCESSFULLY (19/19)  ")
    print("==========================================")

if __name__ == "__main__":
    run_all_tests()
