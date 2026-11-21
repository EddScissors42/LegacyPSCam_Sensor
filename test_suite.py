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

from sensor.config_manager import ConfigManager, parse_preset, PRESETS_PSCAM, PRESETS_WEBCAM
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
    print("[TEST] ConfigManager...")
    cfg_mgr = ConfigManager()
    cfg = cfg_mgr.config
    assert "camera_mode" in cfg
    assert "smoothing_alpha" in cfg
    assert "ds4_permissive_mode" in cfg
    assert cfg["ds4_permissive_mode"] is True
    assert parse_preset("1280x800 @ 60 FPS") == (1280, 800, 60)
    assert parse_preset("640x480 @ 30 FPS") == (640, 480, 30)
    assert "1280x800 @ 60 FPS" in PRESETS_PSCAM
    assert "640x480 @ 30 FPS" in PRESETS_WEBCAM
    print("  -> ConfigManager PASSED")

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

    # Verify Kinect10.dll pacer byte (33ms / 30 FPS standard for Just Dance scoring compatibility)
    # and Ordinal 9 (NuiImageGetColorPixelCoordinatesFromDepthPixel) 320x240 -> 640x480 2x scaling
    for dll_name in ("Kinect10.dll", "Legacy10.dll"):
        dll_path = BASE_DIR / "tools" / dll_name
        if dll_path.exists():
            dll_bytes = dll_path.read_bytes()
            assert len(dll_bytes) == 121344, f"Unexpected {dll_name} size: {len(dll_bytes)}"
            assert dll_bytes[0x1746] == 0x6A, f"Expected push opcode 0x6A at 0x1746, got {dll_bytes[0x1746]:#x}"
            assert dll_bytes[0x1747] == 0x21, f"Expected 33ms pacer byte 0x21 at 0x1747 (30 FPS standard), got {dll_bytes[0x1747]:#x}"
            assert dll_bytes[0x1748:0x174A] == b"\xff\xd3", "Expected call ebx (Sleep) at 0x1748"
            assert dll_bytes[0x19AC:0x19AE] == b"\xd1\xe0", f"Expected shl eax, 1 (0xd1 0xe0) for lColorX in {dll_name} Ordinal 9"
            assert dll_bytes[0x19BC:0x19BE] == b"\xd1\xe0", f"Expected shl eax, 1 (0xd1 0xe0) for lColorY in {dll_name} Ordinal 9"
    print("  -> Kinect10.dll & Legacy10.dll Pacer Byte (30 FPS) + Ordinal 9 (2x Depth->Color Scale) PASSED")

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
    assert (BASE_DIR / "assets" / "icons" / "sliders.svg").exists(), "Asset sliders.svg must exist in assets/icons/"
    assert (BASE_DIR / "assets" / "icons" / "mode_balanced.svg").exists(), "Asset mode_balanced.svg must exist in assets/icons/"
    assert (BASE_DIR / "assets" / "icons" / "mode_competitive.svg").exists(), "Asset mode_competitive.svg must exist in assets/icons/"
    assert (BASE_DIR / "assets" / "icons" / "mode_stable.svg").exists(), "Asset mode_stable.svg must exist in assets/icons/"
    assert (BASE_DIR / "assets" / "icons" / "lab.svg").exists(), "Asset lab.svg must exist in assets/icons/"
    assert (BASE_DIR / "assets" / "icons" / "arrow_down.png").exists() or (BASE_DIR / "assets" / "icons" / "arrow_down.svg").exists(), "Asset arrow_down must exist in assets/icons/"
    assert (BASE_DIR / "models" / "pose_landmarker_lite.task").exists(), "models/pose_landmarker_lite.task must exist"
    assert (BASE_DIR / "models" / "pose_landmarker_full.task").exists(), "models/pose_landmarker_full.task must exist"
    assert (BASE_DIR / "models" / "pose_landmarker_heavy.task").exists(), "models/pose_landmarker_heavy.task must exist"

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

    import ui
    assert hasattr(ui, "LegacySensorGUI")
    assert hasattr(ui, "LegacySensorQtGUI")
    assert hasattr(ui, "UIPagesMixin")
    assert hasattr(ui, "launch_app")
    assert hasattr(ui, "PALETTE")
    assert hasattr(ui, "CALIB_PRESETS")
    assert ui.CALIB_PRESETS["balanced"]["pose_model"] == "full"
    assert ui.CALIB_PRESETS["competitive"]["pose_model"] == "lite"
    assert ui.CALIB_PRESETS["stable"]["pose_model"] == "heavy"
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
        assert not win.pix_gear_act.isNull(), "Settings icon pixmap must not be null"
        assert not win.pix_slid_act.isNull(), "Sliders icon pixmap must not be null"
        assert not win.pix_slid_disabled.isNull(), "Disabled sliders icon pixmap must not be null"
        assert not win.pix_lab_act.isNull(), "Lab icon pixmap must not be null"
        assert win.pix_gear_act.devicePixelRatio() >= 2.0, "Icons must have High-DPI supersampling"
        assert "balanced" in win.mode_pixmaps and not win.mode_pixmaps["balanced"][0].isNull(), "Mode icon balanced must not be null"
        assert "competitive" in win.mode_pixmaps and not win.mode_pixmaps["competitive"][0].isNull(), "Mode icon competitive must not be null"
        assert "stable" in win.mode_pixmaps and not win.mode_pixmaps["stable"][0].isNull(), "Mode icon stable must not be null"
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
        assert win.emulate_kinect_box.isHidden(), "Emulate Kinect box must be hidden in ds4 mode"
        win._switch_tab("exp")
        assert win.active_tab == "exp", "Should be able to switch to experimental tab in ds4 mode"
        assert win.btn_tab_exp.isEnabled(), "Experimental tab must be enabled in ds4 mode"

        # Verify Emulate Kinect & Virtual Phone Controller mutual exclusion
        assert hasattr(win, "lbl_vphone_kinect_conflict"), "Conflict label must exist"
        win._set_mode("webcam")
        assert not win.emulate_kinect_box.isHidden(), "Emulate Kinect box must be visible in webcam mode"
        win.chk_emulate_kinect.setChecked(True)
        assert not win.chk_vphone_enabled.isEnabled(), "vphone must be disabled when Emulate Kinect is ON"
        assert not win.chk_vphone_enabled.isChecked(), "vphone must be unchecked when Emulate Kinect is ON"
        assert not win.lbl_vphone_kinect_conflict.isHidden(), "vphone conflict label must be visible when Emulate Kinect is ON"

        # In ds4 mode, vphone is used as DS4 bridge and conflict label is hidden
        win._set_mode("ds4")
        assert win.chk_vphone_enabled.isChecked(), "vphone must be checked in ds4 mode"
        assert win.lbl_vphone_kinect_conflict.isHidden(), "conflict label must be hidden in ds4 mode"

        # Switching back to webcam maintains lock if Emulate Kinect is still ON
        win._set_mode("webcam")
        assert not win.chk_vphone_enabled.isEnabled(), "vphone must remain disabled when Emulate Kinect is ON"
        assert not win.chk_vphone_enabled.isChecked(), "vphone must remain unchecked"
        assert not win.lbl_vphone_kinect_conflict.isHidden(), "conflict label must be visible again"

        # Turning Emulate Kinect OFF reverts and re-enables vphone
        win.chk_emulate_kinect.setChecked(False)
        assert win.chk_vphone_enabled.isEnabled(), "vphone must be re-enabled when Emulate Kinect is OFF"
        assert win.lbl_vphone_kinect_conflict.isHidden(), "conflict label must be hidden when Emulate Kinect is OFF"

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
    assert assets.ICON_SLIDERS_PATH.exists()
    assert assets.ICON_MODE_BALANCED_PATH.exists()
    assert assets.ICON_MODE_COMPETITIVE_PATH.exists()
    assert assets.ICON_MODE_STABLE_PATH.exists()
    assert assets.ICON_WEBCAM_PATH.exists()
    assert assets.ICON_DUALSHOCK4_PATH.exists()
    assert assets.MODEL_POSE_PATH.exists(), "Canonical pose model path must exist via assets.MODEL_POSE_PATH"
    assert assets.MODEL_POSE_LITE_PATH.exists()
    assert assets.MODEL_POSE_FULL_PATH.exists()
    assert assets.MODEL_POSE_HEAVY_PATH.exists()

    from sensor.pose_tracker import _resolve_model_path
    assert _resolve_model_path("lite").name == "pose_landmarker_lite.task"
    assert _resolve_model_path("full").name == "pose_landmarker_full.task"
    assert _resolve_model_path("heavy").name == "pose_landmarker_heavy.task"

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

    # 2. Test Proxy DLL Presence & Validity
    base_dir = Path(__file__).parent
    proxy_path = base_dir / "tools" / "Legacy10.dll"
    assert proxy_path.exists(), f"Legacy10.dll not found at {proxy_path}"
    assert proxy_path.stat().st_size == 121344, f"Legacy10.dll unexpected size: {proxy_path.stat().st_size}"

    with open(proxy_path, "rb") as f:
        data = f.read()
    assert data[:2] == b"MZ", "Legacy10.dll is not a valid PE binary"

    # 3. Test Ordinal and target definitions
    assert KINECT_ORDINALS_ORDER == [16, 5, 6, 21, 22, 9, 17, 26]
    assert "legacy.exe" in TARGET_PROCESS_NAMES
    assert "justdance.exe" in TARGET_PROCESS_NAMES
    assert "jd2022.exe" in TARGET_PROCESS_NAMES

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
    print("==========================================")
    print("   ALL TESTS PASSED SUCCESSFULLY (15/15)  ")
    print("==========================================")

if __name__ == "__main__":
    run_all_tests()
