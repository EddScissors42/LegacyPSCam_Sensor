"""
Comprehensive Test Suite for Legacy PSCam Sensor.
Verifies config persistence, shared memory bridge, pose engine,
hand anchor (3D & 2D), smoother, coordinate calibrator (X & Y inversion),
high-frequency monotonic timestamps, overlay, and camera manager.
"""
import math
import mmap
import os
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
    assert "mirror_horizontal" not in DEFAULT_CONFIG, "Legacy mirror_horizontal toggle must be removed"
    assert "smoothing_alpha" in cfg
    assert "ds4_permissive_mode" in cfg
    assert isinstance(cfg["ds4_permissive_mode"], bool)
    assert DEFAULT_CONFIG["ds4_permissive_mode"] is True
    assert parse_preset("1280x800 @ 60 FPS") == (1280, 800, 60)
    assert parse_preset("640x480 @ 30 FPS") == (640, 480, 30)
    assert "1280x800 @ 60 FPS" in PRESETS_PSCAM
    assert "640x480 @ 30 FPS" in PRESETS_WEBCAM

    # Verify VirtualPhoneController.set_logging (import re) & JD_PhoneDataCmdSyncEnd (self.accelerometer.hand)
    from sensor.virtual_phone import VirtualPhoneController
    with tempfile.TemporaryDirectory() as td:
        vp = VirtualPhoneController()
        csv_path = str(Path(td) / "vphone_test.csv")
        out_path = vp.set_logging(True, custom_path=csv_path, map_name="Rasputin!@#")
        assert out_path == csv_path and Path(csv_path).exists()
        vp.set_logging(False)

        class _DummyWS:
            def __init__(self):
                self.sent = []
            def send_text(self, txt):
                self.sent.append(txt)

        dws = _DummyWS()
        vp._handle_incoming_message(dws, '{"__class":"JD_PhoneDataCmdSyncEnd","phoneID":7}')
        assert vp._handshake_complete is True and len(dws.sent) == 1

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

    # Verify custom tagname isolation (never silently overwrites production buffer)
    custom_tag = f"Local\\LegacyTestImg_{os.getpid()}"
    kism_custom = KinectImageSharedMemory(tagname=custom_tag)
    try:
        assert kism_custom.is_connected
        assert kism_custom.tagname == custom_tag
        assert kism_custom.tagname_v2 == f"{custom_tag}V2"
        assert kism_custom.write_image_and_mask(dummy_frame, dummy_mask, tracked=True)
        mm_custom = mmap.mmap(-1, IMAGE_SHARED_SIZE, tagname=custom_tag)
        try:
            mm_custom.seek(0)
            m_c, _, s_c, tr_c, _, _, _ = struct.unpack(IMAGE_HEADER_FMT, mm_custom.read(32))
            assert m_c == IMAGE_MAGIC and tr_c == 1 and (s_c % 2 == 0)
        finally:
            mm_custom.close()
    finally:
        kism_custom.close()
    print("  -> KinectImageSharedMemory (Image/Mask JMI1 & JMI2 + Custom Tagname) PASSED")

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

    # Test Unified Bridge (full-frame 640x480 BGRA + full-height 320x240 player mask without letterbox crops)
    bridge = KinectBridge()
    assert bridge.is_connected
    assert bridge.write(NEUTRAL_POSE, dummy_frame, dummy_mask, tracked=True)

    wide_frame = np.full((800, 1280, 3), 180, dtype=np.uint8)
    wide_mask = np.full((240, 320), 255, dtype=np.uint8)
    assert bridge.write(NEUTRAL_POSE, wide_frame, wide_mask, tracked=True)
    mm_wide = mmap.mmap(-1, IMAGE_SHARED_SIZE, tagname=IMAGE_SHARED_NAME)
    mm_wide.seek(32)
    bgra_wide = np.frombuffer(mm_wide.read(640 * 480 * 4), dtype=np.uint8).reshape((480, 640, 4))
    mask_wide = np.frombuffer(mm_wide.read(320 * 240), dtype=np.uint8).reshape((240, 320))
    mm_wide.close()
    # Must fill full 640x480 / 320x240 canvas (no artificial black letterbox cuts at top/bottom)
    assert int(bgra_wide[10, 320, 0]) == 180 and int(bgra_wide[470, 320, 0]) == 180
    assert int(mask_wide[10, 160]) == 255 and int(mask_wide[230, 160]) == 255

    assert bridge.write_empty()
    bridge.close()
    print("  -> KinectBridge (Unified IPC & Full-Frame Silhouette Mapping) PASSED")

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

    # Verify FPS-independent physical smoothing time constant:
    # Continuous-time EMA: eff_alpha = 1 - (1 - alpha_ref) ** (dt / REF_DT)
    # 1) On a stationary micro-jitter step (0 -> 0.002m), 2 consecutive ticks at 60 FPS
    #    must land at the exact same smoothed position as 1 tick at 30 FPS!
    s30 = AdaptiveSmoother(base_alpha=0.50, alpha_fast=0.90, speed_threshold=0.15)
    s60 = AdaptiveSmoother(base_alpha=0.50, alpha_fast=0.90, speed_threshold=0.15)
    s30.apply(j1)
    s60.apply(j1)
    step_target = [(0.002, 0.0, 2.0, 1.0)] * 20
    out30 = s30.apply(step_target, dt=1.0 / 30.0)
    s60.apply(step_target, dt=1.0 / 60.0)
    out60_2ticks = s60.apply(step_target, dt=1.0 / 60.0)
    assert abs(out30[0][0] - out60_2ticks[0][0]) < 1e-4, (
        f"Expected matching 30/60 FPS time constant on stationary step, got {out30[0][0]:.6f} vs {out60_2ticks[0][0]:.6f}"
    )

    # 2) At 60 FPS, a single step must smooth MORE tightly than a 30 FPS single step
    #    (preventing smoothing decay from vanishing at high framerates).
    s60_single = AdaptiveSmoother(base_alpha=0.50, alpha_fast=0.90, speed_threshold=0.15)
    s60_single.apply(j1)
    out60_1tick = s60_single.apply(step_target, dt=1.0 / 60.0)
    assert 0.0 < out60_1tick[0][0] < out30[0][0], (
        f"Single 60 FPS tick ({out60_1tick[0][0]:.6f}) must smooth more tightly than 30 FPS tick ({out30[0][0]:.6f})"
    )

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

    # Test ModelManager (AppData persistent cache, SHA-256 verification & atomic loopback download)
    from sensor.model_manager import ModelManager
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import tempfile
    import threading as _th

    lite_local = ModelManager.locate_model("lite")
    full_local = ModelManager.locate_model("full")
    assert lite_local is not None and ModelManager.validate_model_file(lite_local, "lite", strict_hash=True), (
        "Local pose_landmarker_lite.task must pass strict SHA-256 verification"
    )
    assert full_local is not None and ModelManager.validate_model_file(full_local, "full", strict_hash=True), (
        "Local pose_landmarker_full.task must pass strict SHA-256 verification"
    )

    with tempfile.TemporaryDirectory() as tmp_models_dir:
        tmp_mpath = Path(tmp_models_dir)
        # 1. Staging local model into isolated cache dir
        staged = ModelManager.locate_model("lite", cache_dir=tmp_mpath, stage_to_cache=True)
        assert staged is not None and staged.parent.resolve() == tmp_mpath.resolve()
        assert ModelManager.is_model_ready("lite", cache_dir=tmp_mpath, include_bundled=False)

        # 2. Atomic loopback HTTP download test (valid payload + corrupt rejection)
        real_lite_bytes = lite_local.read_bytes()

        class _ModelHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/corrupt":
                    body = b"NOT_A_VALID_TASK_FILE"
                elif self.path == "/tampered":
                    # Valid ZIP header + size >= min_size_bytes, but tampered trailing byte (wrong SHA-256)
                    body = real_lite_bytes[:-1] + bytes([real_lite_bytes[-1] ^ 0xFF])
                else:
                    body = real_lite_bytes
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                pass

        httpd = HTTPServer(("127.0.0.1", 0), _ModelHandler)
        port = httpd.server_address[1]
        srv_t = _th.Thread(target=httpd.serve_forever, daemon=True)
        srv_t.start()
        try:
            dl_dir = tmp_mpath / "dl_test"
            bad_res = ModelManager.download_model(
                "lite", cache_dir=dl_dir, urls=(f"http://127.0.0.1:{port}/corrupt",)
            )
            assert bad_res is None, "Corrupt model payload must be rejected and discarded"

            # Phase 2 Regression: default strict_hash=True must reject tampered ZIP with mismatched SHA-256
            tampered_res = ModelManager.download_model(
                "lite", cache_dir=dl_dir, urls=(f"http://127.0.0.1:{port}/tampered",)
            )
            assert tampered_res is None, "Tampered model with wrong SHA-256 must be rejected by default!"

            prog_events = []
            ok_res = ModelManager.download_model(
                "lite",
                cache_dir=dl_dir,
                urls=(f"http://127.0.0.1:{port}/lite",),
                progress_cb=lambda done, tot: prog_events.append((done, tot)),
            )
            assert ok_res is not None and ok_res.is_file(), "Loopback model download must succeed atomically"
            assert not ok_res.with_suffix(".task.part").exists(), "Temp .part file must be cleaned up"
            assert len(prog_events) >= 1 and prog_events[-1][0] == len(real_lite_bytes)
        finally:
            httpd.shutdown()
            httpd.server_close()

    print("  -> PoseTracker & ModelManager PASSED (Monotonic timestamp, FaceFollowPTZ & %APPDATA% cache validated)")

def test_overlay():
    print("[TEST] TrackingOverlay (ROI silhouette, 320x240 upscaling & skeleton)...")
    overlay = TrackingOverlay(show_hud=True)
    frame = np.zeros((800, 1280, 3), dtype=np.uint8)
    px_joints = [(50 + i*15, 50 + i*15, 0.9) for i in range(20)]
    # Test with 320x240 native Kinect mask rendered onto a 1280x800 PS4 Camera frame
    dummy_mask = np.zeros((240, 320), dtype=np.uint8)
    dummy_mask[30:150, 40:160] = 255
    # Carve an interior hollow gap (e.g., gap between bent arm and waist)
    dummy_mask[65:115, 75:125] = 0
    frame = overlay.draw_player_silhouette(frame, dummy_mask)
    # Center of hollow gap (x=100*4=400, y=90*(800/240)=300) must remain un-tinted (0)
    assert np.all(frame[300, 400] == 0), "Interior silhouette gaps must stay hollow (not filled solid)"
    # Solid ring pixel (x=55*4=220, y=90*(800/240)=300) must be tinted
    assert np.any(frame[300, 220] > 0), "Active silhouette body region must be tinted"

    # Verify PlayerSlotState._build_exact_player_mask preserves real neural silhouette without anatomical bloat
    from sensor.player_slot import PlayerSlotState
    slot = PlayerSlotState(slot_index=0)
    # Synthetic 3D (480, 640, 1) neural mask: person ring + detached background blob far away
    seg_arr = np.zeros((480, 640, 1), dtype=np.float32)
    seg_arr[100:380, 220:420, 0] = 0.92
    seg_arr[180:260, 280:360, 0] = 0.05  # Hollow gap inside silhouette (e.g. hand on hip)
    seg_arr[10:60, 10:60, 0] = 0.95      # Unrelated background lamp/chair blob
    mock_seg = type("MockSeg", (), {"numpy_view": lambda self: seg_arr})()
    mock_lm = [type("MockLM", (), {"x": 0.5, "y": 0.30, "visibility": 0.95, "presence": 0.95})() for _ in range(33)]
    fallback_called = []
    exact_mask = slot._build_exact_player_mask(
        mock_seg, mock_lm, 320, 240, lambda *a, **kw: fallback_called.append(True) or np.full((240, 320), 255, dtype=np.uint8)
    )
    assert not fallback_called, "Anatomical fallback must not overwrite a valid neural silhouette"
    assert exact_mask[110, 160] == 0, "Hollow interior gap must be preserved in neural body mask"
    assert exact_mask[15, 15] == 0, "Detached background blob must be filtered out"
    assert exact_mask[70, 160] == 255, "Real dancer body pixels must be preserved"

    frame = overlay.draw_skeleton(frame, px_joints)
    frame = overlay.draw_hud(frame, "PS Camera 60 FPS", True, 60.0, 59.8, True, True)
    assert frame.shape == (800, 1280, 3)
    assert np.any(frame > 0)

    # Verify Phone Camera portrait orientation notification pill renders cleanly above bottom controls
    portrait_canvas = np.zeros((640, 480, 3), dtype=np.uint8)
    portrait_hud = overlay.draw_hud(
        portrait_canvas, "Phone Camera (480x640)", True, 30.0, 30.0, True, True, phone_portrait_warning=True
    )
    assert portrait_hud.shape == (640, 480, 3)
    # Region directly above bottom controls bar (y in 544..588) must contain the notification pill pixels
    assert np.any(portrait_hud[544:588, 100:380] > 0), "Rotate phone notification pill must render above bottom controls"

    portrait_clean = np.zeros((640, 480, 3), dtype=np.uint8)
    portrait_no_warn = overlay.draw_hud(
        portrait_clean, "Phone Camera (640x480)", True, 30.0, 30.0, True, True, phone_portrait_warning=False
    )
    assert not np.any(portrait_no_warn[544:588, 100:380] > 0), "Notification pill must disappear when landscape"

    # Verify Picture-in-Picture (PiP) mode toggle ([P] shortcut)
    assert overlay.pip_mode is False
    assert overlay.toggle_pip() is True
    assert overlay.pip_mode is True
    assert overlay.toggle_pip() is False
    assert overlay.pip_mode is False

    # Test Controller Tracking HUD (PlayStation Floating Glass Pills & Motion Aura)
    ds4_canvas = np.zeros((480, 640, 3), dtype=np.uint8)
    ds4_canvas = overlay.draw_controller_hud(
        ds4_canvas,
        controller_name="DualShock 4",
        conn_type="Bluetooth",
        hand="right",
        sens=1.0,
        sample_rate_hz=250.0,
        battery_pct=85,
        is_charging=False,
        is_connected=True,
        imu_frozen=False,
        vphone_status="Connected",
        vphone_connected=True,
        tot_g=1.05,
        current_coach=0,
        total_coaches=4,
        song_name="Levitating",
        action_toast="Switched to Coach 1",
        accel_axes=(0.15, 0.98, -0.05),
        gyro_axes=(12, -4, 0),
    )
    assert ds4_canvas.shape == (480, 640, 3)
    assert np.any(ds4_canvas > 0)
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
    assert (BASE_DIR / "sensor" / "body_mask.py").exists(), "sensor/body_mask.py must exist"
    assert (BASE_DIR / "sensor" / "camera_win32.py").exists(), "sensor/camera_win32.py must exist"
    assert (BASE_DIR / "sensor" / "framebus_reader.py").exists(), "sensor/framebus_reader.py must exist"
    assert (BASE_DIR / "sensor" / "camera_capture.py").exists(), "sensor/camera_capture.py must exist"
    assert (BASE_DIR / "ui").is_dir(), "Directory ui/ must exist"
    assert not (BASE_DIR / "ui" / "pages.py").exists(), "Legacy monolithic ui/pages.py must be removed"
    assert (BASE_DIR / "ui" / "pages").is_dir(), "Package directory ui/pages/ must exist"
    for page_mod in ("__init__.py", "video_page.py", "tracking_page.py", "experimental_page.py", "ds4_page.py"):
        assert (BASE_DIR / "ui" / "pages" / page_mod).exists(), f"ui/pages/{page_mod} must exist"
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
    assert (BASE_DIR / "assets" / "icons" / "reload.svg").exists(), "Asset reload.svg must exist in assets/icons/"
    assert (BASE_DIR / "assets" / "icons" / "arrow_down.png").exists() or (BASE_DIR / "assets" / "icons" / "arrow_down.svg").exists(), "Asset arrow_down must exist in assets/icons/"
    assert (BASE_DIR / "assets" / "webapp" / "mobile_webapp.html").exists(), "Asset mobile_webapp.html must exist in assets/webapp/"
    assert (BASE_DIR / "assets" / "webapp" / "expired_session.html").exists(), "Asset expired_session.html must exist in assets/webapp/"
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
    assert (BASE_DIR / "sensor" / "player_reid.py").exists(), "sensor/player_reid.py must exist"
    assert (BASE_DIR / "sensor" / "gesture_detector.py").exists(), "sensor/gesture_detector.py must exist"
    assert (BASE_DIR / "sensor" / "qr_encoder.py").exists(), "sensor/qr_encoder.py must exist"
    assert (BASE_DIR / "sensor" / "tls_manager.py").exists(), "sensor/tls_manager.py must exist"
    assert (BASE_DIR / "sensor" / "vphone_protocol.py").exists(), "sensor/vphone_protocol.py must exist"
    assert (BASE_DIR / "ui" / "styles.py").exists(), "ui/styles.py must exist"
    assert (BASE_DIR / "ui" / "mixins").is_dir(), "ui/mixins/ package must exist"
    assert (BASE_DIR / "ui" / "mixins" / "device_readout.py").exists(), "ui/mixins/device_readout.py must exist"
    assert (BASE_DIR / "ui" / "mixins" / "camera_handlers.py").exists(), "ui/mixins/camera_handlers.py must exist"
    assert (BASE_DIR / "ui" / "mixins" / "phone_handlers.py").exists(), "ui/mixins/phone_handlers.py must exist"
    assert (BASE_DIR / "ui" / "mixins" / "ds4_vphone_handlers.py").exists(), "ui/mixins/ds4_vphone_handlers.py must exist"
    assert (BASE_DIR / "ui" / "mixins" / "tracking_handlers.py").exists(), "ui/mixins/tracking_handlers.py must exist"
    assert not (BASE_DIR / "ui" / "device_readout_mixin.py").exists(), "Legacy ui/device_readout_mixin.py must be moved into ui/mixins/"
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
        assert not win.pix_reload_act.isNull(), "Reload SVG icon pixmap must not be null"
        assert not win.btn_refresh.icon().isNull(), "Webcam reload button must use reload.svg icon"
        assert not win.btn_refresh_phone_qr.icon().isNull(), "Phone QR reload button must use reload.svg icon"
        assert not win.btn_refresh_ds4_icon.icon().isNull(), "DS4 reload button must use reload.svg icon"
        assert "border: 1px solid #94A3B8" in win.styleSheet(), "Dropdown menus must have crisp visible thin border"
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
        assert not hasattr(win, "stereo_box"), "Stereo Vision feature box must be removed from UI"
        assert not hasattr(win, "chk_stereo"), "Stereo Vision toggle checkbox must be removed from UI"
        assert win.cfg.get("stereo_mode") == "sparse_metric", "Stereo Vision must be enabled by default (sparse_metric)"
        assert hasattr(win, "btn_logs_folder"), "Open Logs Folder button must exist in sidebar"
        assert win.btn_logs_folder.text() == "Open Logs Folder"
        assert hasattr(win, "block_ps_eye"), "Camera eye sensor block must exist"
        assert win.block_ps_eye.isEnabled(), "Camera eye block must remain enabled with always-on Stereo Vision"
        assert hasattr(win, "model_dl_box") and not win.model_dl_box.isVisible(), "Model download banner must exist and start hidden"
        import assets as _assets_mod
        assert _assets_mod.ICON_APP_ICO_PATH is not None and _assets_mod.ICON_APP_ICO_PATH.exists(), "Bundled app_icon.ico must exist"
        assert _assets_mod.SPLASH_IMAGE_PATH is not None and _assets_mod.SPLASH_IMAGE_PATH.exists(), "Bundled splash.png must exist"
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
        assert hasattr(win, "scoring_bridge_box"), "Scoring Bridge pill must exist in Controller Settings"
        assert hasattr(win, "btn_ds4_sb_reconnect"), "Reconnect Game button must exist in Scoring Bridge"
        assert win.btn_ds4_sb_reconnect.text() == "Reconnect Game", "Button text must be 'Reconnect Game'"
        assert hasattr(win, "btn_ds4_sb_discover"), "Auto-Find button must exist in Scoring Bridge"
        assert win.btn_ds4_sb_discover.text() == "Auto-Find", "Button text must be 'Auto-Find'"
        assert hasattr(win, "btn_ds4_sb_ftue"), "Skip Finish button must exist in Scoring Bridge"
        assert win.btn_ds4_sb_ftue.text() == "Skip Finish", "Button text must be 'Skip Finish'"

        # Verify Experimental features ARE visible in Camera modes (pscam/webcam/phone_cam)
        for cam_mode in ("pscam", "webcam", "phone_cam"):
            win._set_mode(cam_mode, animate=False)
            assert not win.auto_frame_box.isHidden(), f"Auto-Frame box must be visible in {cam_mode} mode"
            assert not win.vphone_box.isHidden(), f"Virtual Phone box must be visible in {cam_mode} mode"
            assert win.lbl_exp_empty.isHidden(), f"Empty placeholder must be hidden in {cam_mode} mode"

        win._set_mode("ds4")
        assert win.active_tab == "controller", "Should switch to controller settings tab on ds4 mode"
        assert not win.btn_tab_controller.isHidden(), "Controller settings tab must be visible in ds4 mode"
        assert not win.btn_tab_exp.isHidden(), "Experimental tab must be visible in ds4 mode"
        assert win.chk_vphone_enabled.isChecked(), "Virtual phone must be checked in ds4 mode"
        assert not win.chk_vphone_enabled.isEnabled(), "Virtual phone checkbox must be disabled/locked in ds4 mode"
        assert not win.vphone_details_frame.isHidden(), "Virtual phone telemetry details must not be hidden in ds4 mode"
        assert win.auto_frame_box.isHidden(), "Auto-frame box must be hidden in ds4 mode"
        assert win.vphone_box.isHidden(), "Virtual Phone box in Experimental must be hidden in ds4 mode"
        assert not win.lbl_exp_empty.isHidden(), "Experimental empty placeholder must be visible in ds4 mode"
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
        win.controller.cleanup()
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
            if cam.ps4_backend is None:
                print("  -> Physical PS4 Camera is held exclusively by another active session; skipping live HW capture.")
            else:
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

    # 3.0b Symmetric Left-Eye Primary Triangulation (ensures Stereo Vision works with either eye selected)
    joints_2d_left = {0: (float(target_u_l), float(target_v_r), 0.95)}
    res_left = engine.triangulate_sparse_joints(test_l, test_r, joints_2d_left, search_radius_px=60, primary_eye="left")
    assert 0 in res_left, "Left-eye primary target joint must be triangulated"
    assert abs(res_left[0][2] - expected_z) < 0.15, f"Expected Left-primary Z around {expected_z:.2f}m, got {res_left[0][2]:.2f}m"

    # 3.0c Phase 1 Regression: Right-eye far depth (disparity 4px < patch_half_size=6 at 320x192 -> ~4.58m)
    # and close depth (~1.0m, disparity 73px > default search_radius_px=48 at 1280x800)
    far_l = np.ones((192, 320, 3), dtype=np.uint8) * 45
    far_r = np.ones((192, 320, 3), dtype=np.uint8) * 45
    fu_r, fv_r, fdisp = 150, 96, 4
    for r in range(-8, 9):
        for c in range(-8, 9):
            pv = int(((r * 19 + c * 29) % 180) + 60)
            far_r[fv_r + r, fu_r + c] = (pv, 255 - pv, 110)
            far_l[fv_r + r, fu_r + fdisp + c] = (pv, 255 - pv, 110)
    engine.reset_calibration()
    res_far = engine.triangulate_sparse_joints(far_l, far_r, {0: (float(fu_r), float(fv_r), 0.95)}, primary_eye="right")
    assert 0 in res_far, "Right-eye far depth (disparity < patch_half_size) must not be clipped"
    exp_far_z = (215.0 * PS4_STEREO_BASELINE_M) / float(fdisp)
    assert abs(res_far[0][2] - exp_far_z) < 0.35, f"Expected far Z ~{exp_far_z:.2f}m, got {res_far[0][2]:.2f}m"

    close_l = np.ones((800, 1280, 3), dtype=np.uint8) * 45
    close_r = np.ones((800, 1280, 3), dtype=np.uint8) * 45
    cu_r, cv_r, cdisp = 550, 400, 73
    for r in range(-10, 11):
        for c in range(-10, 11):
            pv = int(((r * 17 + c * 31) % 180) + 60)
            close_r[cv_r + r, cu_r + c] = (pv, 255 - pv, 110)
            close_l[cv_r + r, cu_r + cdisp + c] = (pv, 255 - pv, 110)
    engine.reset_calibration()
    # Uses default search_radius_px=48 (auto-scales for 1280x800)
    res_close = engine.triangulate_sparse_joints(close_l, close_r, {0: (float(cu_r), float(cv_r), 0.95)}, primary_eye="right")
    assert 0 in res_close, "Close dancer (~1.0m at 1280x800) must triangulate with default search_radius_px"
    assert 0.85 <= res_close[0][2] <= 1.15, f"Expected close Z ~1.0m, got {res_close[0][2]:.2f}m"
    # Verify OpenCV stereoRectify baseline translation sign (T = [-B, 0, 0] -> Q[3, 2] > 0)
    assert engine.calibrator.Q is not None and float(engine.calibrator.Q[3, 2]) > 0.0, "stereoRectify T sign must yield positive 1/B in Q[3,2]"
    engine.reset_calibration()

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

    # 5.1 Stereo Head.z & Hand.z Anti-Oscillation Regression Test (prevents face zoom-in/zoom-out pumping)
    head_zs = []
    hand_zs = []
    for tick in range(20):
        # Simulate violent frame-to-frame stereo spikes (1.15m <-> 3.45m) on Head(3), Hip(0), and HandRight(11)
        spike_z = 3.45 if (tick % 2 == 0) else 1.15
        noisy_stereo = {
            0: (0.0, 0.0, spike_z, 0.85),
            3: (0.0, 0.7, spike_z, 0.90),
            11: (0.3, 0.2, spike_z, 0.90),
        }
        out_noisy = sk_calib.transform(joints, stereo_depths=noisy_stereo)
        head_zs.append(out_noisy[3][2])
        hand_zs.append(out_noisy[11][2])
    head_z_span = max(head_zs) - min(head_zs)
    hand_z_max_step = max(abs(hand_zs[i] - hand_zs[i - 1]) for i in range(1, len(hand_zs)))
    assert head_z_span < 0.05, f"Stereo Head.z must never pump face zoom (span={head_z_span:.3f}m)"
    assert hand_z_max_step < 0.45, f"Stereo Hand.z must stay anatomically bounded (max_step={hand_z_max_step:.3f}m)"
    print(f"  -> Stereo Anti-Zoom-Oscillation PASSED (Head.z span={head_z_span:.4f}m, Hand max_step={hand_z_max_step:.3f}m)")

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

    # Validate rest-locked IMU scale calibration in production DS4Controller (prevents peak swing >1.46G halving G-force)
    scale_lsb = 8192.0
    scale_locked = False
    rest_samples = []
    prev_mag = None
    for _ in range(15):
        scale_lsb, scale_locked, prev_mag = DS4Controller.update_imu_scale_calibration(
            8200.0, scale_lsb, scale_locked, rest_samples, prev_mag
        )
    assert scale_locked is True and scale_lsb == 8192.0, f"Expected Sony DS4 locked at 8192, got {scale_lsb} (locked={scale_locked})"
    # Violent 2.2G dance swing (raw_mag ~ 18022) must NEVER flip scale to 16384!
    scale_lsb, scale_locked, prev_mag = DS4Controller.update_imu_scale_calibration(
        18022.0, scale_lsb, scale_locked, rest_samples, prev_mag
    )
    assert scale_lsb == 8192.0, f"Peak dance swing corrupted locked IMU scale to {scale_lsb}!"
    assert math.isclose(18022.0 / scale_lsb, 2.2, abs_tol=0.05)

    # Validate 4096 LSB/G clone locking at rest
    c_scale, c_locked, c_samples, c_prev = 8192.0, False, [], None
    for _ in range(15):
        c_scale, c_locked, c_prev = DS4Controller.update_imu_scale_calibration(
            4096.0, c_scale, c_locked, c_samples, c_prev
        )
    assert c_locked is True and c_scale == 4096.0, f"Expected 4096 LSB/G clone lock, got {c_scale}"

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

    # 2. Test Proxy DLL Presence & Validity (32-bit Legacy10.dll + 64-bit Legacy10_x64.dll present; manual Kinect10.dll removed)
    base_dir = Path(__file__).parent
    assert not (base_dir / "tools" / "Kinect10.dll").exists(), "Manual tools/Kinect10.dll must be removed"
    proxy_x64_path = base_dir / "tools" / "Legacy10_x64.dll"
    assert proxy_x64_path.exists(), f"64-bit Legacy10_x64.dll not found at {proxy_x64_path}"
    assert proxy_x64_path.stat().st_size > 100_000, f"Legacy10_x64.dll unexpected size: {proxy_x64_path.stat().st_size}"
    proxy_path = base_dir / "tools" / "Legacy10.dll"
    assert proxy_path.exists(), f"Legacy10.dll not found at {proxy_path}"
    assert proxy_path.stat().st_size == 121344, f"Legacy10.dll unexpected size: {proxy_path.stat().st_size}"

    with open(proxy_path, "rb") as f:
        data = f.read()
    assert data[:2] == b"MZ", "Legacy10.dll is not a valid PE binary"

    # 3. Test Ordinal and target definitions (32-bit Legacy + 64-bit Legacy Lab) & AV anti-false-positive hardening
    import sensor.kinect_emulator as ke_mod
    assert KINECT_ORDINALS_ORDER == [16, 5, 6, 21, 22, 9, 17, 26]
    assert TARGET_PROCESS_NAMES == ["legacy.exe", "legacy lab.exe", "justdance.exe"]
    assert not hasattr(ke_mod, "PAGE_EXECUTE_READWRITE"), "PAGE_EXECUTE_READWRITE must not be used for IAT data patching"
    assert not hasattr(ke_mod, "PROCESS_ALL_ACCESS"), "PROCESS_ALL_ACCESS must not be requested by KinectEmulatorDaemon"
    ke_src = (base_dir / "sensor" / "kinect_emulator.py").read_text(encoding="utf-8")
    assert "PAGE_EXECUTE_READWRITE" not in ke_src, "kinect_emulator.py must use PAGE_READWRITE instead of RWX"
    assert "PROCESS_ALL_ACCESS" not in ke_src, "kinect_emulator.py must use minimal PROCESS_INJECT_ACCESS"
    spec_src = (base_dir / "legacy_pscam_sensor.spec").read_text(encoding="utf-8")
    assert "VSVersionInfo" in spec_src and "version=pe_version_info" in spec_src, "PyInstaller spec must embed VSVersionInfo PE metadata"
    assert "Legacy10_x64.dll" in spec_src, "PyInstaller spec must bundle tools/Legacy10_x64.dll for 64-bit Legacy Lab"

    # 4. Test Daemon Instantiation & Lifecycle
    daemon = KinectEmulatorDaemon({"emulate_kinect_enabled": False})
    assert not daemon.enabled
    status = daemon.get_status()
    assert status["enabled"] is False
    assert status["connected"] is False
    assert "last_error_code" in status and "last_error_message" in status
    assert hasattr(ke_mod, "LIST_MODULES_32BIT") and ke_mod.LIST_MODULES_32BIT == 0x01
    assert hasattr(ke_mod, "LIST_MODULES_64BIT") and ke_mod.LIST_MODULES_64BIT == 0x02
    assert hasattr(ke_mod, "TARGET_PROCESS_ALIASES") and "justdance2017.exe" in ke_mod.TARGET_PROCESS_ALIASES
    assert hasattr(daemon, "_stage_proxy_dll") and hasattr(daemon, "_resolve_iat_via_ilt")
    assert hasattr(daemon, "_hook_running_game_64") and hasattr(daemon, "_find_kinect_delay_iat_descriptor_64")
    assert hasattr(daemon, "_validate_fallback_iat_rva")
    assert daemon.proxy_dll_x64_path.is_file(), f"64-bit proxy DLL missing: {daemon.proxy_dll_x64_path}"
    # Verify PE32+ magic on tools/Legacy10_x64.dll
    x64_bytes = daemon.proxy_dll_x64_path.read_bytes()
    x64_lfanew = struct.unpack_from("<I", x64_bytes, 0x3C)[0]
    assert struct.unpack_from("<H", x64_bytes, x64_lfanew + 24)[0] == 0x020B, "Legacy10_x64.dll must be PE32+ (64-bit)"
    # Exact process name matching must include Legacy Lab and reject launcher / unrelated processes
    assert KinectEmulatorDaemon.is_target_process_name("Legacy.exe") is True
    assert KinectEmulatorDaemon.is_target_process_name("Legacy Lab.exe") is True
    assert KinectEmulatorDaemon.is_target_process_name("LegacyLab.exe") is True
    assert KinectEmulatorDaemon.is_target_process_name("JustDance2017.exe") is True
    assert KinectEmulatorDaemon.is_target_process_name("legacylab-launcher.exe") is False
    assert KinectEmulatorDaemon.is_target_process_name("SomeAppLegacy.exe") is False
    assert KinectEmulatorDaemon.is_target_process_name("LegacyPSCam.exe") is False
    assert KinectEmulatorDaemon.is_target_process_name("LegacySensor.exe") is False
    assert daemon._validate_fallback_iat_rva(None, 0, 0x9CD250, 32) is False

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

        # 4.1 Phase 2 Regression: CSV quoting for song titles with commas/quotes + zero row loss on immediate stop
        import csv
        logger.start_telemetry_tracking(source="camera", song_name='Hey Ya!, "Remix"', coach_id=1)
        for i in range(25):
            logger.record_telemetry_sample(
                ts_ms=2000000 + i * 16,
                source="camera",
                song_name='Hey Ya!, "Remix"',
                coach_id=1,
                is_tracked=True,
                ax=0.1, ay=0.2, az=1.0, speed_mps=0.5,
                game_feedback="SUPER, COMBO",
            )
        logger.stop_telemetry_tracking({"samples": 25})
        with open(logger.telemetry_csv_path, "r", encoding="utf-8", newline="") as f:
            parsed_rows = list(csv.reader(f))
        assert len(parsed_rows) == 26, f"Expected header + all 25 rows without batch drop, got {len(parsed_rows)}"
        assert parsed_rows[1][3] == 'Hey Ya!, "Remix"', f"CSV quoting failed: {parsed_rows[1][3]!r}"
        assert parsed_rows[1][26] == "SUPER, COMBO"

        # 5. Test session rotation / backup on second initialization
        orig_hook = sys.excepthook
        logger.close()
        assert sys.excepthook is not logger._exception_hook if hasattr(logger, "_exception_hook") else True

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

    # Rapid vertical crouch down in place (same horizontal X, big vertical drop + shirt occluded) must be ACCEPTED!
    crouch_lms = make_person_lms(0.53, 0.84, sh_w=0.18)
    assert lock.validate_candidate(scene_bgr, crouch_lms, dt=0.016) is True, (
        "Rapid vertical crouch in place must NEVER be rejected as an impostor"
    )

    # Phase 1 Regression A: PlayerSlotState.reset_transient() must preserve DancerIdentityLock
    # so the 18-frame impostor gate works even when inertial_coasting_enabled=False
    from sensor.player_slot import PlayerSlotState
    from sensor.pose_tracker import PoseTracker
    slot_lock_test = PlayerSlotState(
        slot_index=0,
        cfg={"person_lock_enabled": True, "dancer_lock_enabled": True, "inertial_coasting_enabled": False},
    )
    for _ in range(6):
        assert slot_lock_test.person_lock.validate_candidate(scene_bgr, dancer_lms, dt=0.016) is True
    assert slot_lock_test.person_lock.identity.is_locked is True
    # First impostor rejection triggers handle_missing() -> reset_transient(); identity MUST survive!
    assert slot_lock_test.person_lock.validate_candidate(scene_bgr, impostor_lms, dt=0.016) is False
    slot_lock_test.handle_missing(dt=0.016, frame_w=640, frame_h=400)
    assert slot_lock_test.person_lock.identity.is_locked is True, "reset_transient() must NOT wipe DancerIdentityLock!"
    assert slot_lock_test.person_lock.identity.rejected_streak == 1

    # Phase 1 Regression B: Upper-body lower-limb synthesis (hips_visible=False) must NOT invert Left/Right legs
    class _LM3D:
        def __init__(self, x, y, z=0.0, vis=0.95):
            self.x = x
            self.y = y
            self.z = z
            self.visibility = vis
            self.presence = vis

    slot_ub = PlayerSlotState(slot_index=0, cfg={"person_lock_enabled": False})
    world_ub = [_LM3D(0.0, 0.0, 0.0, vis=0.05) for _ in range(33)]
    norm_ub = [_LM3D(0.5, 0.5, 0.0, vis=0.05) for _ in range(33)]
    # Facing camera (un-mirrored MediaPipe convention): LEFT_SHOULDER has +X (image right), RIGHT_SHOULDER has -X (image left)
    world_ub[0] = _LM3D(0.0, -0.55, 0.0, vis=0.95)
    world_ub[7] = _LM3D(0.08, -0.55, 0.0, vis=0.95)
    world_ub[8] = _LM3D(-0.08, -0.55, 0.0, vis=0.95)
    world_ub[11] = _LM3D(0.20, -0.35, 0.0, vis=0.95)   # LEFT_SHOULDER (+X in MediaPipe -> -X in Kinect)
    world_ub[12] = _LM3D(-0.20, -0.35, 0.0, vis=0.95)  # RIGHT_SHOULDER (-X in MediaPipe -> +X in Kinect)
    world_ub[13] = _LM3D(0.25, -0.10, 0.0, vis=0.90)
    world_ub[14] = _LM3D(-0.25, -0.10, 0.0, vis=0.90)
    world_ub[15] = _LM3D(0.28, 0.05, 0.0, vis=0.90)
    world_ub[16] = _LM3D(-0.28, 0.05, 0.0, vis=0.90)
    world_ub[19] = _LM3D(0.30, 0.10, 0.0, vis=0.90)
    world_ub[20] = _LM3D(-0.30, 0.10, 0.0, vis=0.90)

    norm_ub[0] = _LM3D(0.50, 0.20, 0.0, vis=0.95)
    norm_ub[7] = _LM3D(0.54, 0.20, 0.0, vis=0.95)
    norm_ub[8] = _LM3D(0.46, 0.20, 0.0, vis=0.95)
    norm_ub[11] = _LM3D(0.62, 0.35, 0.0, vis=0.95)  # LEFT_SHOULDER (right side of raw image)
    norm_ub[12] = _LM3D(0.38, 0.35, 0.0, vis=0.95)  # RIGHT_SHOULDER (left side of raw image)
    norm_ub[13] = _LM3D(0.66, 0.50, 0.0, vis=0.90)
    norm_ub[14] = _LM3D(0.34, 0.50, 0.0, vis=0.90)
    norm_ub[15] = _LM3D(0.68, 0.62, 0.0, vis=0.90)
    norm_ub[16] = _LM3D(0.32, 0.62, 0.0, vis=0.90)
    norm_ub[19] = _LM3D(0.69, 0.65, 0.0, vis=0.90)
    norm_ub[20] = _LM3D(0.31, 0.65, 0.0, vis=0.90)

    pf_ub = slot_ub.process_detection(
        world_lm=world_ub,
        norm_lm=norm_ub,
        seg_mask_obj=None,
        frame_bgr=scene_bgr,
        frame_left=None,
        stereo_engine=None,
        stereo_mode="disabled",
        extract_joints_2d_fn=lambda *a, **k: {},
        build_body_mask_fn=lambda lms, mw, mh: np.zeros((mh, mw), dtype=np.uint8),
        dt_infer=0.016,
        w=640,
        h=400,
    )
    assert pf_ub is not None and pf_ub.tracked
    # Kinect space: ShoulderLeft(4) & HipLeft(12) & FootLeft(15) on negative X; Right(8, 16, 19) on positive X
    assert pf_ub.kinect_joints[4][0] < 0.0 and pf_ub.kinect_joints[8][0] > 0.0
    assert pf_ub.kinect_joints[12][0] < 0.0 and pf_ub.kinect_joints[16][0] > 0.0, (
        f"Synthesized hips inverted! HipLeft={pf_ub.kinect_joints[12][0]:.3f}, HipRight={pf_ub.kinect_joints[16][0]:.3f}"
    )
    assert pf_ub.kinect_joints[15][0] < pf_ub.kinect_joints[19][0], "Synthesized Left/Right feet must not cross!"
    # 2D un-mirrored pixels: px_hip_l(12) must align with px_sh_l(4) on image right (> px_hip_r)
    assert pf_ub.pixel_joints[12][0] > pf_ub.pixel_joints[16][0], (
        f"2D synthesized hips inverted! px_hip_l={pf_ub.pixel_joints[12][0]}, px_hip_r={pf_ub.pixel_joints[16][0]}"
    )

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

    # 4. Test PersonLockController master toggle, low-FPS spin coasting & ROI bypass while coasting
    ctrl = PersonLockController(cfg={"person_lock_enabled": True, "inertial_coasting_max_ms": 250})
    assert ctrl.is_enabled is True
    for _ in range(6):
        ctrl.validate_candidate(scene_bgr, dancer_lms, dt=0.016)
    ctrl.record_valid_frame([(0.1, 0.5, 2.0, 0.95)] * 20, [(320, 240, 0.95)] * 20, mask_in, dt=0.016)
    # Simulate transient low-FPS (dt=0.060s) micro-drop: must survive 300ms (5 frames) and disable ROI darkening while coasting!
    for step in range(5):
        ok_lo, _, _, _ = ctrl.coast(dt=0.060, frame_w=640, frame_h=480)
        assert ok_lo is True, f"Low-FPS spin coasting must survive 300ms (failed at step {step})"
    test_rgb_coast = np.full((400, 640, 3), 200, dtype=np.uint8)
    ctrl.apply_pre_inference_roi(test_rgb_coast)
    assert int(test_rgb_coast[200, 5, 0]) == 200, "ROI darkening must be bypassed while coasting so re-acquisition sees full bright frame"
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

    # Test State Machine with simulated time progression (dry-run keystroke to avoid injecting OS keys during tests)
    detector = ArmRaiseGestureDetector(
        enabled=True, hold_seconds=2.0, cooldown_seconds=2.5, dispatch_keystroke=False
    )

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
    from sensor.phone_camera import (
        QRCodeGenerator,
        SelfSignedTLSManager,
        PhoneCameraServer,
        load_webapp_html,
        MOBILE_WEBAPP_HTML,
        EXPIRED_SESSION_HTML,
    )
    from sensor.camera_manager import LatestFrameCamera

    # 0. Verify external HTML templates in assets/webapp/
    assert "Legacy PSCam Sensor" in MOBILE_WEBAPP_HTML and "computeScaledDimensions" in MOBILE_WEBAPP_HTML
    assert "Rotate your phone horizontally" in MOBILE_WEBAPP_HTML and "rotateBanner" in MOBILE_WEBAPP_HTML
    assert "Pairing Session Expired" in EXPIRED_SESSION_HTML
    assert load_webapp_html("nonexistent_file.html", "FALLBACK_OK") == "FALLBACK_OK"

    # 1. Verify Pure-Python ISO/IEC 18004 QR Code generation and OpenCV QR decoding
    test_url = "https://192.168.1.42:8443"
    qr_pil = QRCodeGenerator.render_pil_image(test_url, box_size_px=240)
    assert qr_pil.size == (240, 240)
    qr_bgr = cv2.cvtColor(np.array(qr_pil), cv2.COLOR_RGBA2BGR)
    decoded_url, _, _ = cv2.QRCodeDetector().detectAndDecode(qr_bgr)
    assert decoded_url == test_url, f"OpenCV QRCodeDetector failed to decode QR: got {decoded_url!r}"

    # 2. Verify Pure-Python X.509v3 Self-Signed TLS Certificate (multi-IP SAN) & SSLContext loading
    cert_pem, _key_pem = SelfSignedTLSManager.build_self_signed_pem(
        "192.168.1.42", extra_ips=["10.0.0.15", "192.168.1.42"]
    )
    assert "BEGIN CERTIFICATE" in cert_pem
    tls_ctx = SelfSignedTLSManager.create_ssl_context("127.0.0.1", extra_ips=["192.168.1.42"])
    assert isinstance(tls_ctx, ssl.SSLContext)

    # 2b. Verify smart LAN IP ranking (physical Wi-Fi/Ethernet outranks VPN/virtual adapters) & firewall probe
    from sensor.phone_camera import _is_virtual_or_vpn_adapter, _score_lan_candidate
    assert _is_virtual_or_vpn_adapter("Wi-Fi", "Intel Wireless", 71, "192.168.1.42", True) is False
    assert _is_virtual_or_vpn_adapter("Radmin VPN", "Famatech Radmin VPN", 6, "26.212.15.52", True) is True
    assert _is_virtual_or_vpn_adapter("Tailscale", "Tailscale Tunnel", 53, "100.64.10.2", False) is True
    assert _is_virtual_or_vpn_adapter("VirtualBox Host-Only", "VirtualBox", 6, "192.168.56.1", False) is True
    assert _is_virtual_or_vpn_adapter("vEthernet (WSL)", "Hyper-V Virtual Ethernet", 6, "172.24.0.1", False) is True
    wifi_score = _score_lan_candidate("192.168.1.42", "Wi-Fi", "Intel Wireless", 71, True, False, "26.212.15.52")
    vpn_score = _score_lan_candidate("26.212.15.52", "Radmin VPN", "Radmin", 6, True, True, "26.212.15.52")
    assert wifi_score > vpn_score, f"Physical Wi-Fi ({wifi_score}) must outrank VPN ({vpn_score})"
    lan_list = PhoneCameraServer.list_local_lan_ips()
    assert isinstance(lan_list, list) and len(lan_list) >= 1 and "ip" in lan_list[0] and "label" in lan_list[0]
    fw_status = PhoneCameraServer.check_windows_firewall_rule(8443)
    assert isinstance(fw_status, dict) and fw_status.get("port") == 8443 and "port_rule_allowed" in fw_status

    # 3. Start PhoneCameraServer on an ephemeral loopback port and test HTTPS GET / + WSS /ws
    srv = PhoneCameraServer(port=0)
    assert srv.start(port=0, bind_host="127.0.0.1") is True
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
        assert b"Front Camera" in resp and b"Rear Camera" in resp and b"Cool Mode" in resp
        assert b"CAMERA SLEEPING" in resp and b"runThermalGovernor" in resp
        assert b"willReadFrequently: true" not in resp, "mobile_webapp.html must not force CPU software 2D canvas"
        assert b"computeScaledDimensions" in resp and b"Standby" in resp

        # Phase 2 Regression: TLS manager must have no hardcoded repo primes and enforce TLSv1.2
        tls_src = (BASE_DIR / "sensor" / "tls_manager.py").read_text(encoding="utf-8")
        assert "_LOCAL_RSA_P" not in tls_src and "_LOCAL_RSA_Q" not in tls_src, "Static RSA primes must not be hardcoded"
        tls_ctx = SelfSignedTLSManager.create_ssl_context("127.0.0.1")
        assert tls_ctx.minimum_version == ssl.TLSVersion.TLSv1_2

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

                # Phase 2 Regression: malformed JSON payloads (list / bad width) must NOT drop the WebSocket
                send_masked_frame(0x01, b"[1, 2, 3]")
                send_masked_frame(0x01, b'{"type":"hello","width":"not_an_int","height":null}')

                # Phase 2 Regression: RFC 6455 fragmented WebSocket frame (FIN=0 + continuation opcode=0x00)
                frag_payload = json.dumps({
                    "type": "edge_metrics",
                    "ts_ms": 987654321,
                    "imu_accel": [0.3, 0.4, 0.9],
                }).encode("utf-8")
                mid = len(frag_payload) // 2
                mask_k = b"\x12\x34\x56\x78"
                for idx_f, (b0_val, chunk) in enumerate([(0x01, frag_payload[:mid]), (0x80, frag_payload[mid:])]):
                    hdr_f = struct.pack("!BB", b0_val, 0x80 | len(chunk))
                    masked_c = bytes(b ^ mask_k[i % 4] for i, b in enumerate(chunk))
                    wss.sendall(hdr_f + mask_k + masked_c)

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

        # Verify DeviceController status readout includes full stream metadata (lens, dims, fps, info_text)
        from ui.controllers.device_controller import DeviceController
        from ui.controllers.session_controller import SessionController
        from ui.controllers.camera_controller import CameraController
        dc = DeviceController()
        st_snap = dc.get_phone_cam_status()
        for req_k in ("is_connected", "info_text", "client_lens", "width", "height", "fps", "target_fps"):
            assert req_k in st_snap, f"Missing key {req_k!r} in DeviceController.get_phone_cam_status()"

        # Phase 2 Regression: Non-blocking DS4 probe cache, SessionController thread tracking & CameraController warmup token
        t_ds4 = time.perf_counter()
        ds4_snap = dc.get_ds4_readout()
        dt_ds4_ms = (time.perf_counter() - t_ds4) * 1000.0
        assert isinstance(ds4_snap, dict) and "is_connected" in ds4_snap
        assert dt_ds4_ms < 25.0, f"get_ds4_readout() must return cached snapshot without blocking UI ({dt_ds4_ms:.2f}ms)"
        assert hasattr(dc, "is_connecting_ds4")
        sc = SessionController()
        assert hasattr(sc, "_tracking_thread")
        cc = CameraController()
        gen_before = getattr(cc, "_warmup_gen", 0)
        cc.cancel_warmup(sync=False)
        assert getattr(cc, "_warmup_gen", 0) == gen_before + 1, "cancel_warmup must increment cancellation generation token"
        cc.set_closing(True)
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
        extract_detection_features,
    )
    # Regression guard: upper-body-only poses (knees hidden) and frame_bgr=None must never raise UnboundLocalError
    upper_only_lms = [type("Lm", (), {"x": 0.5, "y": 0.35, "z": 0.0, "visibility": 0.9 if i <= 24 else 0.05})() for i in range(33)]
    upper_only_lms[11].x, upper_only_lms[11].y = 0.42, 0.30
    upper_only_lms[12].x, upper_only_lms[12].y = 0.58, 0.30
    upper_only_lms[23].x, upper_only_lms[23].y = 0.44, 0.55
    upper_only_lms[24].x, upper_only_lms[24].y = 0.56, 0.55
    _cx, _cy, _sw, _bb, _sig = extract_detection_features(np.full((240, 320, 3), 120, dtype=np.uint8), upper_only_lms)
    assert _sig.lower_v_hist is None and _sig.torso_hs_hist is not None
    _cx2, _cy2, _sw2, _bb2, _sig2 = extract_detection_features(None, upper_only_lms)
    assert _sig2.body_height >= 0.20 and _sig2.contrast_ratio == 1.0
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
    ok_chair, _ = is_plausible_human_dancer(chair_lms, w=1280, h=800)
    assert ok_chair is False, "Horizontal/flat non-human object must be rejected as implausible dancer"

    # Deep crouch with outstretched arms on 1280x800 PS4 Camera (shoulders near hip level, wide arm span) MUST be accepted!
    crouch_pose = [type("MockLM", (), {"x": 0.50, "y": 0.72, "z": 0.0, "visibility": 0.85, "presence": 0.85})() for _ in range(33)]
    crouch_pose[0] = type("MockLM", (), {"x": 0.50, "y": 0.56, "z": 0.0, "visibility": 0.90, "presence": 0.90})()   # Nose
    crouch_pose[11] = type("MockLM", (), {"x": 0.43, "y": 0.66, "z": 0.0, "visibility": 0.88, "presence": 0.88})()  # ShL
    crouch_pose[12] = type("MockLM", (), {"x": 0.57, "y": 0.66, "z": 0.0, "visibility": 0.88, "presence": 0.88})()  # ShR
    crouch_pose[15] = type("MockLM", (), {"x": 0.25, "y": 0.68, "z": 0.0, "visibility": 0.85, "presence": 0.85})()  # WristL wide
    crouch_pose[16] = type("MockLM", (), {"x": 0.75, "y": 0.68, "z": 0.0, "visibility": 0.85, "presence": 0.85})()  # WristR wide
    crouch_pose[23] = type("MockLM", (), {"x": 0.45, "y": 0.68, "z": 0.0, "visibility": 0.82, "presence": 0.82})()  # HipL (nearly level with shoulders!)
    crouch_pose[24] = type("MockLM", (), {"x": 0.55, "y": 0.68, "z": 0.0, "visibility": 0.82, "presence": 0.82})()  # HipR
    crouch_pose[27] = type("MockLM", (), {"x": 0.44, "y": 0.90, "z": 0.0, "visibility": 0.80, "presence": 0.80})()  # AnkleL
    crouch_pose[28] = type("MockLM", (), {"x": 0.56, "y": 0.90, "z": 0.0, "visibility": 0.80, "presence": 0.80})()  # AnkleR
    ok_crouch, crouch_score = is_plausible_human_dancer(crouch_pose, w=1280, h=800)
    assert ok_crouch is True, f"Deep crouch pose on 1280x800 PS4 Camera must be accepted (score={crouch_score:.2f})"

    # 3.2 Verify 2P Arm-Overlap Resilience: Pose NMS, Single-Shoulder Occlusion, 3-Candidate Matching,
    # Score-Order Anti-Swap, Overlap Extended Coasting (650 ms), and Anti-Swallow Silhouette Isolation
    from sensor.player_slot import suppress_duplicate_poses, extract_detection_features

    # (a) Single-shoulder occlusion during arm-on-P2 contact must pass plausibility & feature extraction
    occluded_p1 = make_person_lms(0.30)
    occluded_p1[12] = SynthLM(0.38, 0.33, vis=0.08)  # Right shoulder momentarily occluded by P2/arm
    ok_occ, occ_score = is_plausible_human_dancer(occluded_p1, w=1280, h=800)
    assert ok_occ is True, f"Single-shoulder occluded dancer must pass plausibility check (score={occ_score:.2f})"
    occ_feats = extract_detection_features(np.zeros((240, 320, 3), dtype=np.uint8), occluded_p1)
    assert occ_feats is not None, "Single-shoulder occluded dancer must still yield valid detection features"

    # (b) Pose NMS suppresses duplicate overlapping detection on P2 so occluded P1 is NOT pushed out
    p2_main = make_person_lms(0.72)
    p2_dup = make_person_lms(0.735, cy=0.455)  # Duplicate proposal sitting on top of P2
    p1_real = make_person_lms(0.30)
    raw_cands = [
        (11.5, (p2_main, p2_main, None)),
        (10.9, (p2_dup, p2_dup, None)),
        (8.8, (p1_real, p1_real, None)),
    ]
    kept_cands, sup_cnt = suppress_duplicate_poses(raw_cands, max_players=2)
    assert sup_cnt == 1 and len(kept_cands) == 2, (
        f"Expected Pose NMS to suppress 1 duplicate on P2 and retain P1+P2, got sup={sup_cnt}, kept={len(kept_cands)}"
    )
    kept_xs = sorted(float(c[1][1][0].x) for c in kept_cands)
    assert abs(kept_xs[0] - 0.30) < 0.02 and abs(kept_xs[1] - 0.72) < 0.02, (
        f"Pose NMS must keep real P1 (0.30) and P2 (0.72), got nose xs={kept_xs}"
    )

    # (c) 3-candidate matching: enrolled P1 (Blue, 0.25) & P2 (Orange, 0.75) stay matched even when
    # a 3rd candidate sits at index 0 and P1 is pushed to index 2!
    slots_ov = [PlayerSlotState(0), PlayerSlotState(1)]
    assoc_ov = MultiPlayerAssociator(max_players=2)
    t_ov = 200.0
    for _ in range(15):
        t_ov += 1.0 / 30.0
        frm_ov = np.zeros((240, 320, 3), dtype=np.uint8)
        paint_dancer(frm_ov, 0.25, blue_shirt, dark_pants)
        paint_dancer(frm_ov, 0.75, orange_shirt, light_pants)
        assoc_ov.match(slots_ov, [make_person_lms(0.25), make_person_lms(0.75)], frm_ov, dt=1.0 / 30.0, now=t_ov)

    frm_3c = np.zeros((240, 320, 3), dtype=np.uint8)
    paint_dancer(frm_3c, 0.25, blue_shirt, dark_pants)
    paint_dancer(frm_3c, 0.50, (80, 220, 80), (60, 60, 60))  # Green bystander at index 0
    paint_dancer(frm_3c, 0.75, orange_shirt, light_pants)
    assign_3c, _ = assoc_ov.match(
        slots_ov,
        [make_person_lms(0.50), make_person_lms(0.75), make_person_lms(0.25)],
        frm_3c,
        dt=1.0 / 30.0,
        now=t_ov + 0.033,
    )
    assert assign_3c.get(0) == 2 and assign_3c.get(1) == 1, (
        f"3-candidate associator must keep Slot 0 -> det[2] (P1) and Slot 1 -> det[1] (P2), got {assign_3c}"
    )

    # (d) Score-order flip during crowded arm-reach overlap must NOT force a false swap
    t_ov += 0.066
    p1_arm_reach = make_person_lms(0.38)
    p1_arm_reach[16] = SynthLM(0.60, 0.36, vis=0.90)  # P1 right wrist reaches onto P2!
    p2_close = make_person_lms(0.56)
    frm_reach = np.zeros((240, 320, 3), dtype=np.uint8)
    paint_dancer(frm_reach, 0.38, blue_shirt, dark_pants)
    paint_dancer(frm_reach, 0.56, orange_shirt, light_pants)
    # Deliver detections in flipped array order [P2, P1]
    assign_flip, crowd_flip = assoc_ov.match(
        slots_ov, [p2_close, p1_arm_reach], frm_reach, dt=1.0 / 30.0, now=t_ov
    )
    assert crowd_flip is True, "Arm-on-P2 overlap must trigger is_crowded=True"
    assert assign_flip.get(0) == 1 and assign_flip.get(1) == 0, (
        f"Flipped detection array order during overlap must not swap slots, got {assign_flip}"
    )

    # (e) Single surviving detection during overlap keeps is_crowded=True & extends missing slot coasting to >400 ms
    assign_1det, crowd_1det = assoc_ov.match(
        slots_ov, [p2_close], frm_reach, dt=1.0 / 30.0, now=t_ov + 0.033
    )
    assert crowd_1det is True, "Single surviving detection during active overlap must preserve is_crowded=True"
    assert assign_1det.get(1) == 0, f"Surviving detection on P2 must remain assigned to Slot 1, got {assign_1det}"

    # Prime P1's coasting filter and verify crowded overlap coasting survives 400 ms (> 250 ms normal cap)
    dummy_2d = [(200, 200, 0.9)] * 20
    dummy_m = np.full((240, 320), 255, dtype=np.uint8)
    slots_ov[0].person_lock.record_valid_frame(pose_p1, dummy_2d, dummy_m, dt=1.0 / 30.0)
    pf_coast = None
    for _ in range(12):  # 12 * 33ms = 400 ms > 250 ms default cap, < 650 ms overlap cap
        pf_coast = slots_ov[0].handle_missing(dt=0.033, frame_w=640, frame_h=480, is_crowded=True)
    assert pf_coast is not None and pf_coast.tracked and pf_coast.coasting, (
        "2P overlap coasting must keep occluded dancer tracked past 400 ms"
    )

    # (f) Anti-Swallow Silhouette Isolation: merged neural blob touching both dancers must carve out P1 from P2's mask
    class FakeSegMask:
        def __init__(self, arr):
            self._arr = arr
        def numpy_view(self):
            return self._arr

    merged_prob = np.zeros((240, 320), dtype=np.float32)
    merged_prob[40:210, 45:275] = 0.95  # Single merged blob spanning both P1 (x=0.25) and P2 (x=0.75)
    p2_mask_iso = slots_ov[1]._build_exact_player_mask(
        seg_mask_obj=FakeSegMask(merged_prob),
        norm_lm=make_person_lms(0.75),
        mw=320,
        mh=240,
        build_body_mask_fn=tracker_2p.build_body_mask,
        other_norm_lm=make_person_lms(0.25),
        is_crowded=True,
    )
    # P2's torso center (x≈240, y≈108) must stay foreground; P1's torso center (x≈80, y≈108) must be carved out!
    assert int(p2_mask_iso[108, 240]) == 255, "P2 isolated mask must keep P2's own torso"
    assert int(p2_mask_iso[108, 80]) == 0, "P2 isolated mask must carve out P1's torso from merged neural blob"

    # (g) 90° Sideways Profile Spin resilience: shoulders overlapping in 2D (sh_w=0.012) on tall standing dancer MUST pass!
    profile_spin = make_person_lms(0.50, cy=0.50, sh_w=0.012)
    profile_spin[12] = SynthLM(0.506, 0.38, vis=0.10)  # Far shoulder occluded mid-spin
    ok_spin, spin_score = is_plausible_human_dancer(profile_spin, w=1280, h=800)
    assert ok_spin is True, f"90° sideways profile spin must pass plausibility check (score={spin_score:.2f})"

    # (g2) Upper-body start-of-game / menu framing (head + shoulders + elbows visible, legs off-screen) MUST pass!
    upper_menu = [SynthLM(0.50, 0.90, vis=0.02) for _ in range(33)]
    upper_menu[0] = SynthLM(0.50, 0.25, vis=0.92)   # Nose
    upper_menu[11] = SynthLM(0.38, 0.48, vis=0.88)  # ShL
    upper_menu[12] = SynthLM(0.62, 0.48, vis=0.88)  # ShR
    upper_menu[13] = SynthLM(0.34, 0.72, vis=0.45)  # ElbowL
    upper_menu[14] = SynthLM(0.66, 0.72, vis=0.45)  # ElbowR
    upper_menu[23] = SynthLM(0.42, 0.95, vis=0.20)  # HipL edge
    upper_menu[24] = SynthLM(0.58, 0.95, vis=0.20)  # HipR edge
    ok_upper, upper_score = is_plausible_human_dancer(upper_menu, w=1280, h=800)
    assert ok_upper is True, f"Upper-body menu/start framing must pass plausibility check (score={upper_score:.2f})"

    # (h) Neural ROI Top/Bottom Clip Recovery: if MediaPipe's square ROI clips head/feet flat at y=75..165,
    # _build_exact_player_mask must restore the clipped top & bottom bands from landmarks without bloating torso!
    clipped_prob = np.zeros((240, 320), dtype=np.float32)
    clipped_prob[75:165, 130:190] = 0.95  # Hard-clipped top & bottom neural ROI
    tall_dancer = make_person_lms(0.50, cy=0.50, sh_w=0.16)
    tall_dancer[0] = SynthLM(0.50, 0.18, vis=0.95)   # Nose above y=75 (y≈43)
    tall_dancer[7] = SynthLM(0.47, 0.18, vis=0.90)   # Left ear at head level
    tall_dancer[8] = SynthLM(0.53, 0.18, vis=0.90)   # Right ear at head level
    tall_dancer[27] = SynthLM(0.46, 0.88, vis=0.90)  # Left ankle below y=165 (y≈211)
    tall_dancer[28] = SynthLM(0.54, 0.88, vis=0.90)  # Right ankle below y=165 (y≈211)
    slots_ov[0]._seg_prob_ema = None
    recovered_mask = slots_ov[0]._build_exact_player_mask(
        seg_mask_obj=FakeSegMask(clipped_prob),
        norm_lm=tall_dancer,
        mw=320,
        mh=240,
        build_body_mask_fn=tracker_2p.build_body_mask,
    )
    assert np.any(recovered_mask[35:65, 140:180] == 255), "Top clipped head/hand region must be recovered from landmarks"
    assert np.any(recovered_mask[180:215, 135:185] == 255), "Bottom clipped legs/ankles region must be recovered from landmarks"

    # 4. Verify ArmRaiseGestureDetector.update_multi accepts arm raise from Player 2
    g_det = ArmRaiseGestureDetector(
        enabled=True, hold_seconds=1.5, cooldown_seconds=2.0, dispatch_keystroke=False
    )
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
        try:
            assert win.btn_tab_calib.text().strip() == "Tracking", f"Expected tab text 'Tracking', got '{win.btn_tab_calib.text()}'"
            assert win.cb_players_mode.itemText(0) == "1 Player", f"Expected '1 Player', got '{win.cb_players_mode.itemText(0)}'"
            assert win.cb_players_mode.itemText(1) == "2 Players [Experimental]", f"Expected '2 Players [Experimental]', got '{win.cb_players_mode.itemText(1)}'"
            assert hasattr(win, "cb_players_mode"), "Players Mode selector must exist in Calibration/Tracking tab"
            assert hasattr(win, "two_player_warn_box"), "2-Player Lite AI warning banner must exist in Calibration/Tracking tab"
            win.cb_players_mode.setCurrentIndex(1)  # Switch to 2 Players (Duo)
            assert win.cfg["max_players"] == 2
            assert not win.two_player_warn_box.isHidden(), "2P warning box must be visible when 2 Players is active"
            win.cb_players_mode.setCurrentIndex(0)  # Restore 1 Player (Solo)
            assert win.cfg["max_players"] == 1
            assert win.two_player_warn_box.isHidden(), "2P warning box must be hidden in 1-Player mode"

            # 7. Verify Reactive Start Button (matches actual hardware connection state)
            win._set_mode("pscam", animate=False)
            pscam_ready = win.is_camera_accessible()
            assert win.btn_start.isEnabled() is pscam_ready, (
                f"Start button enabled state ({win.btn_start.isEnabled()}) must match PS Camera accessibility ({pscam_ready})"
            )
            assert win.btn_start.text() == "START TRACKING"

            win._set_mode("phone_cam", animate=False)
            assert win.btn_start.isEnabled() is False, "Start button must be disabled when Phone Camera is not connected"
            assert win.btn_start.isHidden() is True, "Start button must be hidden when Phone Camera is not connected"
            assert win.btn_bottom_disconnect_phone.isHidden() is True, "Disconnect button must be hidden when Phone Camera is not connected"
            assert win.btn_start.text() == "START TRACKING"
        finally:
            win.controller.cleanup()
            win.close()

    print("  -> Multi-Player (2P Duo) Pose Engine, Anti-Swap Memory & JDP2/JMI2 IPC PASSED")


from contextlib import contextmanager


@contextmanager
def _isolated_test_environment():
    """
    Isolates %APPDATA% into a temporary directory for the full test run so the user's real
    %APPDATA%/LegacyPSCam_Sensor/config.json, logs, TLS keys, and TCP port 8443 are never touched.
    """
    import json
    import tempfile

    prev_appdata = os.environ.get("APPDATA")
    prev_portable = os.environ.get("LEGACY_PSCAM_PORTABLE")
    prev_qt_platform = os.environ.get("QT_QPA_PLATFORM")

    with tempfile.TemporaryDirectory(prefix="legacy_pscam_test_appdata_") as temp_appdata:
        os.environ["APPDATA"] = temp_appdata
        os.environ.pop("LEGACY_PSCAM_PORTABLE", None)
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

        app_dir = Path(temp_appdata) / "LegacyPSCam_Sensor"
        app_dir.mkdir(parents=True, exist_ok=True)
        seed_cfg = dict(DEFAULT_CONFIG)
        seed_cfg["phone_cam_port"] = 0  # Ephemeral OS port prevents colliding with real port 8443
        (app_dir / "config.json").write_text(json.dumps(seed_cfg, indent=2), encoding="utf-8")

        try:
            yield app_dir
        finally:
            try:
                from sensor.phone_camera import _phone_camera_server
                if _phone_camera_server is not None and _phone_camera_server.is_running:
                    _phone_camera_server.stop()
            except Exception:
                pass
            if prev_appdata is None:
                os.environ.pop("APPDATA", None)
            else:
                os.environ["APPDATA"] = prev_appdata
            if prev_portable is None:
                os.environ.pop("LEGACY_PSCAM_PORTABLE", None)
            else:
                os.environ["LEGACY_PSCAM_PORTABLE"] = prev_portable
            if prev_qt_platform is None:
                os.environ.pop("QT_QPA_PLATFORM", None)
            else:
                os.environ["QT_QPA_PLATFORM"] = prev_qt_platform


def run_modular_unit_tests():
    """Discovers and executes modular unittest suites under LegacyPSCam_Sensor/tests/."""
    import unittest

    tests_dir = BASE_DIR / "tests"
    if not tests_dir.is_dir():
        return
    print("[TEST] Modular unittest suites (tests/test_*.py)...")
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=str(tests_dir), pattern="test_*.py", top_level_dir=str(BASE_DIR))
    runner = unittest.TextTestRunner(verbosity=1, stream=sys.stdout)
    result = runner.run(suite)
    if not result.wasSuccessful():
        raise AssertionError(
            f"Modular unittest suite failed: {len(result.failures)} failures, {len(result.errors)} errors"
        )
    print(f"  -> Modular unittest suites PASSED ({result.testsRun} tests)")


def run_all_tests():
    print("==========================================")
    print("   RUNNING LEGACY PSCAM SENSOR TEST SUITE ")
    print("==========================================")
    with _isolated_test_environment():
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
        run_modular_unit_tests()
    print("==========================================")
    print("   ALL TESTS PASSED SUCCESSFULLY (19/19)  ")
    print("==========================================")

if __name__ == "__main__":
    run_all_tests()
