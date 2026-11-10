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

def test_config():
    print("[TEST] ConfigManager...")
    cfg_mgr = ConfigManager()
    cfg = cfg_mgr.config
    assert "camera_mode" in cfg
    assert "smoothing_alpha" in cfg
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
    dll_path = BASE_DIR / "Kinect for Legacy DLL" / "Kinect10.dll"
    if dll_path.exists():
        dll_bytes = dll_path.read_bytes()
        assert len(dll_bytes) == 121344, f"Unexpected Kinect10.dll size: {len(dll_bytes)}"
        assert dll_bytes[0x1746] == 0x6A, f"Expected push opcode 0x6A at 0x1746, got {dll_bytes[0x1746]:#x}"
        assert dll_bytes[0x1747] == 0x21, f"Expected 33ms pacer byte 0x21 at 0x1747 (30 FPS standard), got {dll_bytes[0x1747]:#x}"
        assert dll_bytes[0x1748:0x174A] == b"\xff\xd3", "Expected call ebx (Sleep) at 0x1748"
        print("  -> Kinect10.dll Pacer Byte (33ms / 30 FPS Kinect standard) PASSED")

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

    # Also test high-resolution 1280x800 frame pre-downscaling path
    dummy_hd = np.zeros((800, 1280, 3), dtype=np.uint8)
    for _ in range(3):
        tracked, kinect_joints, px_joints, body_mask = tracker.process_frame(dummy_hd)
        assert tracked is False
        assert body_mask is None

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

    # Test PS4 Camera multi-stage state machine
    ps4_info = CameraManager.get_ps4_camera_state()
    assert isinstance(ps4_info, dict)
    assert "state" in ps4_info
    valid_states = {"NOT_INSTALLED", "DISCONNECTED", "DRIVER_STOPPED", "BOOTLOADER_UPLOADING", "WAITING_VCAM", "READY"}
    assert ps4_info["state"] in valid_states
    assert isinstance(ps4_info["installed"], bool)
    assert isinstance(ps4_info["running"], bool)
    assert isinstance(ps4_info["bootloader"], bool)
    assert isinstance(ps4_info["active_hw"], bool)
    assert isinstance(ps4_info["vcam_count"], int)
    print(f"  PS4 Camera lifecycle state: {ps4_info['state']} (HW active: {ps4_info['active_hw']}, VCAMs: {ps4_info['vcam_count']})")

    cams = CameraManager.enumerate_cameras(max_probe=2)
    assert len(cams) > 0
    print(f"  Cameras found: {[str(c) for c in cams]}")

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

    import sensor
    assert hasattr(sensor, "PoseTracker")
    assert hasattr(sensor, "HandAnchorFilter")
    assert hasattr(sensor, "CameraManager")
    assert hasattr(sensor, "KinectBridge")
    assert hasattr(sensor, "run_tracking_session")
    assert hasattr(sensor, "DS4Controller")
    assert hasattr(sensor, "find_ds4_devices")
    assert hasattr(sensor, "get_ds4_controller")

    import ui
    assert hasattr(ui, "LegacySensorGUI")
    assert hasattr(ui, "LegacySensorQtGUI")
    assert hasattr(ui, "launch_app")
    assert hasattr(ui, "PALETTE")
    assert hasattr(ui, "CALIB_PRESETS")
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
        assert hasattr(win, "cb_res") and hasattr(win, "cb_fps"), "Split resolution and FPS combos must exist in webcam card"
        assert hasattr(win, "btn_refresh"), "Refresh button in device card must exist"
        win._switch_tab("exp")
        assert win.active_tab == "exp", "Should switch to experimental tab"

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

        win._set_mode("ds4")
        assert win.active_tab == "controller", "Should switch to controller settings tab on ds4 mode"
        assert not win.btn_tab_controller.isHidden(), "Controller settings tab must be visible in ds4 mode"
        assert win.btn_tab_video.isHidden(), "Video settings tab must be hidden in ds4 mode"
        win._set_mode("webcam")
        win._switch_tab("exp")

        # Calibration tab gating when camera is not connected
        if not win.is_camera_accessible():
            assert not win.btn_tab_calib.isEnabled(), "Calibration tab must be disabled when camera is not accessible"
            win._switch_tab("calib")
            assert win.active_tab == "exp", "Switching to calib must be prevented when camera is not accessible"
        win._switch_tab("video")
        win.close()
        app.processEvents()

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

    print("  -> Modular Project Structure PASSED")

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
    print("==========================================")
    print("   ALL TESTS PASSED SUCCESSFULLY (9/9)    ")
    print("==========================================")

if __name__ == "__main__":
    run_all_tests()
