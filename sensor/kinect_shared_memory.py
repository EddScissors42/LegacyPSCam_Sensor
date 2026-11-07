"""
Shared Memory IPC Bridge for Just Dance PC (Legacy Offline).
Provides atomic seqlock buffers consumed by Kinect10.dll:
1. Pose Bridge: Local\\LegacyWebcamKinectPose (344 bytes, JDP1)
2. Image & Mask Bridge: Local\\LegacyWebcamKinectImage (1,305,632 bytes, JMI1)
3. Coach X Bridge: Local\\LegacyWebcamKinectCoachX (28 bytes, JXC1)
"""
import mmap
import os
import struct
import time
import cv2
import numpy as np

# --- 1. Pose Bridge Constants (344 bytes) ---
JOINT_COUNT = 20
HEADER_FMT = '<IIIIQ'
JOINT_FMT = '<ffff'
MAGIC = 0x3150444A  # 'JDP1'
VERSION = 1
SHARED_NAME = r'Local\LegacyWebcamKinectPose'
SHARED_SIZE = struct.calcsize(HEADER_FMT) + JOINT_COUNT * struct.calcsize(JOINT_FMT)  # 344 bytes

JOINT_NAMES = [
    "HipCenter",       # 0
    "Spine",           # 1
    "ShoulderCenter",  # 2
    "Head",            # 3
    "ShoulderLeft",    # 4
    "ElbowLeft",       # 5
    "WristLeft",       # 6
    "HandLeft",        # 7
    "ShoulderRight",   # 8
    "ElbowRight",      # 9
    "WristRight",      # 10
    "HandRight",       # 11
    "HipLeft",         # 12
    "KneeLeft",        # 13
    "AnkleLeft",       # 14
    "FootLeft",        # 15
    "HipRight",        # 16
    "KneeRight",       # 17
    "AnkleRight",      # 18
    "FootRight"        # 19
]

# Neutral standing pose fallback (in Kinect coordinates: X, Y, Z, Conf)
NEUTRAL_POSE = [
    (0.00,  0.00, 2.0, 1.0),  # 0 HipCenter
    (0.00,  0.25, 2.0, 1.0),  # 1 Spine
    (0.00,  0.50, 2.0, 1.0),  # 2 ShoulderCenter
    (0.00,  0.70, 2.0, 1.0),  # 3 Head
    (-0.20, 0.45, 2.0, 1.0),  # 4 ShoulderLeft
    (-0.25, 0.20, 2.0, 1.0),  # 5 ElbowLeft
    (-0.27, 0.00, 2.0, 1.0),  # 6 WristLeft
    (-0.28,-0.07, 2.0, 1.0),  # 7 HandLeft
    (0.20,  0.45, 2.0, 1.0),  # 8 ShoulderRight
    (0.25,  0.20, 2.0, 1.0),  # 9 ElbowRight
    (0.27,  0.00, 2.0, 1.0),  # 10 WristRight
    (0.28, -0.07, 2.0, 1.0),  # 11 HandRight
    (-0.10,-0.05, 2.0, 1.0),  # 12 HipLeft
    (-0.10,-0.50, 2.0, 1.0),  # 13 KneeLeft
    (-0.10,-0.90, 2.0, 1.0),  # 14 AnkleLeft
    (-0.10,-0.95, 2.0, 1.0),  # 15 FootLeft
    (0.10, -0.05, 2.0, 1.0),  # 16 HipRight
    (0.10, -0.50, 2.0, 1.0),  # 17 KneeRight
    (0.10, -0.90, 2.0, 1.0),  # 18 AnkleRight
    (0.10, -0.95, 2.0, 1.0),  # 19 FootRight
]

FULL_JOINTS_FMT = '<' + 'ffff' * JOINT_COUNT
ZERO_JOINTS_BYTES = struct.pack(FULL_JOINTS_FMT, *([0.0] * (JOINT_COUNT * 4)))

# --- 1.1 Multi-Pose Bridge Constants (664 bytes, JDP2) ---
MAX_PLAYERS = 2
MULTI_MAGIC = 0x3250444A  # 'JDP2'
MULTI_VERSION = 2
MULTI_SHARED_NAME = r'Local\LegacyWebcamKinectPoseV2'
MULTI_SHARED_SIZE = struct.calcsize(HEADER_FMT) + (JOINT_COUNT * struct.calcsize(JOINT_FMT) * MAX_PLAYERS)  # 664 bytes

# --- 2. Image & Mask Bridge Constants (1,305,632 bytes) ---
IMAGE_SHARED_NAME = r'Local\LegacyWebcamKinectImage'
IMAGE_MAGIC = 0x31494D4A   # 'JMI1'
IMAGE_VERSION = 1
IMAGE_W = 640
IMAGE_H = 480
MASK_W = 320
MASK_H = 240
IMAGE_HEADER_FMT = '<IIIIIIQ'  # magic, version, seq, tracked, width, height, timestamp_ms (32 bytes)
IMAGE_HEADER_SIZE = struct.calcsize(IMAGE_HEADER_FMT)
IMAGE_BGRA_SIZE = IMAGE_W * IMAGE_H * 4    # 1,228,800 bytes
IMAGE_MASK_SIZE = MASK_W * MASK_H          # 76,800 bytes
IMAGE_SHARED_SIZE = IMAGE_HEADER_SIZE + IMAGE_BGRA_SIZE + IMAGE_MASK_SIZE  # 1,305,632 bytes

MULTI_IMAGE_SHARED_NAME = r'Local\LegacyWebcamKinectImageV2'
MULTI_IMAGE_MAGIC = 0x32494D4A   # 'JMI2'
MULTI_IMAGE_VERSION = 2

ZERO_BGRA_BYTES = b'\x00' * IMAGE_BGRA_SIZE
ZERO_MASK_BYTES = b'\x00' * IMAGE_MASK_SIZE

# --- 3. Coach X Bridge Constants (28 bytes) ---
COACHX_SHARED_NAME = r'Local\LegacyWebcamKinectCoachX'
COACHX_MAGIC = 0x3143584A  # 'JXC1'
COACHX_VERSION = 1
COACHX_HEADER_FMT = '<IIIIfQ'  # magic, version, seq, enabled, coachX, timestamp_ms (28 bytes)
COACHX_SHARED_SIZE = struct.calcsize(COACHX_HEADER_FMT)


class KinectSharedMemory:
    """
    Manages the 344-byte skeleton tracking memory buffer (JDP1).
    """
    def __init__(self, tagname=SHARED_NAME):
        self.tagname = tagname
        self.mm = None
        self.seq = 0
        self.is_connected = False
        self._init_shared_memory()

    def _init_shared_memory(self):
        try:
            self.mm = mmap.mmap(-1, SHARED_SIZE, tagname=self.tagname)
            self.is_connected = True
            self.write_empty()
            print(f"[OK] Shared Memory Pose: {self.tagname} ({SHARED_SIZE} bytes)")
        except Exception as e:
            self.is_connected = False
            print(f"[ERROR] Failed to initialize pose shared memory {self.tagname}: {e}")

    def write_pose(self, joints, tracked=True):
        if not self.is_connected or self.mm is None:
            return False

        try:
            self.seq = (self.seq + 2) | 1
            ts_ms = int(time.time() * 1000)
            tracked_val = 1 if tracked and joints else 0

            self.mm.seek(0)
            self.mm.write(struct.pack(HEADER_FMT, MAGIC, VERSION, self.seq, tracked_val, ts_ms))

            if joints and tracked_val == 1:
                flat_floats = []
                count = min(len(joints), JOINT_COUNT)
                for i in range(count):
                    x, y, z, conf = joints[i]
                    flat_floats.extend((float(x), float(y), float(z), float(conf)))
                if count < JOINT_COUNT:
                    flat_floats.extend([0.0] * ((JOINT_COUNT - count) * 4))
                self.mm.write(struct.pack(FULL_JOINTS_FMT, *flat_floats))
            else:
                self.mm.write(ZERO_JOINTS_BYTES)

            self.seq += 1
            self.mm.seek(8)
            self.mm.write(struct.pack('<I', self.seq))
            self.mm.flush()
            return True
        except Exception as e:
            print(f"[WARN] Error writing pose: {e}")
            return False

    def write_empty(self):
        return self.write_pose(None, tracked=False)

    def close(self):
        if self.mm is not None:
            try:
                self.write_empty()
                self.mm.close()
            except Exception:
                pass
            self.mm = None
            self.is_connected = False


class KinectMultiPoseSharedMemory:
    """
    Manages the 664-byte dual skeleton tracking memory buffer (JDP2).
    Consumed preferentially by Kinect10.dll.
    Preserves absolute metric camera-space coordinates without auto-centering,
    enabling dancer slot selection in Just Dance PC.
    """
    def __init__(self, tagname=MULTI_SHARED_NAME):
        self.tagname = tagname
        self.mm = None
        self.seq = 0
        self.is_connected = False
        self._init_shared_memory()

    def _init_shared_memory(self):
        try:
            self.mm = mmap.mmap(-1, MULTI_SHARED_SIZE, tagname=self.tagname)
            self.is_connected = True
            self.write_empty()
            print(f"[OK] Shared Memory Pose V2: {self.tagname} ({MULTI_SHARED_SIZE} bytes)")
        except Exception as e:
            self.is_connected = False
            print(f"[ERROR] Failed to initialize pose V2 shared memory {self.tagname}: {e}")

    def write_poses(self, players, tracked=True):
        if not self.is_connected or self.mm is None:
            return False

        try:
            if not players:
                return self.write_empty()

            if isinstance(players[0], tuple) and len(players[0]) == 4:
                bodies = [players, None]
            else:
                bodies = list(players[:MAX_PLAYERS])
                while len(bodies) < MAX_PLAYERS:
                    bodies.append(None)

            tracked_mask = sum(1 << i for i, b in enumerate(bodies) if b is not None and tracked)
            self.seq = (self.seq + 2) | 1
            ts_ms = int(time.time() * 1000)

            self.mm.seek(0)
            self.mm.write(struct.pack(HEADER_FMT, MULTI_MAGIC, MULTI_VERSION, self.seq, tracked_mask, ts_ms))

            for body in bodies:
                if body and tracked_mask > 0:
                    flat_floats = []
                    count = min(len(body), JOINT_COUNT)
                    for i in range(count):
                        x, y, z, conf = body[i]
                        flat_floats.extend((float(x), float(y), float(z), float(conf)))
                    if count < JOINT_COUNT:
                        flat_floats.extend([0.0] * ((JOINT_COUNT - count) * 4))
                    self.mm.write(struct.pack(FULL_JOINTS_FMT, *flat_floats))
                else:
                    self.mm.write(ZERO_JOINTS_BYTES)

            self.seq += 1
            self.mm.seek(8)
            self.mm.write(struct.pack('<I', self.seq))
            self.mm.flush()
            return True
        except Exception as e:
            print(f"[WARN] Error writing pose V2 to shared memory: {e}")
            return False

    def write_empty(self):
        if not self.is_connected or self.mm is None:
            return False
        try:
            self.seq = (self.seq + 2) | 1
            ts_ms = int(time.time() * 1000)
            self.mm.seek(0)
            self.mm.write(struct.pack(HEADER_FMT, MULTI_MAGIC, MULTI_VERSION, self.seq, 0, ts_ms))
            self.mm.write(ZERO_JOINTS_BYTES)
            self.mm.write(ZERO_JOINTS_BYTES)
            self.seq += 1
            self.mm.seek(8)
            self.mm.write(struct.pack('<I', self.seq))
            self.mm.flush()
            return True
        except Exception:
            return False

    def close(self):
        if self.mm is not None:
            try:
                self.write_empty()
                self.mm.close()
            except Exception:
                pass
            self.mm = None
            self.is_connected = False


class KinectImageSharedMemory:
    """
    Manages the 1,305,632-byte image and player segmentation mask buffer.
    Populates both:
      - Local\\LegacyWebcamKinectImage (JMI1, version 1, mask with 255 for player)
      - Local\\LegacyWebcamKinectImageV2 (JMI2, version 2, player index mask with 1 for Player 1)
    Ensures 100% binary compatibility with any version of Kinect10.dll.
    """
    def __init__(self, tagname=IMAGE_SHARED_NAME):
        self.tagname = tagname
        self.mm_v1 = None
        self.mm_v2 = None
        self.mm = None  # Alias for mm_v1 (backwards compatibility with tests)
        self.seq_v1 = 0
        self.seq_v2 = 0
        self.seq = 0
        self.is_connected = False
        self._init_shared_memory()

    def _init_shared_memory(self):
        try:
            self.mm_v1 = mmap.mmap(-1, IMAGE_SHARED_SIZE, tagname=IMAGE_SHARED_NAME)
            self.mm = self.mm_v1
            print(f"[OK] Shared Memory Image/Mask V1: {IMAGE_SHARED_NAME} ({IMAGE_SHARED_SIZE} bytes)")
        except Exception as e:
            print(f"[ERROR] Failed to initialize image memory V1: {e}")

        try:
            self.mm_v2 = mmap.mmap(-1, IMAGE_SHARED_SIZE, tagname=MULTI_IMAGE_SHARED_NAME)
            print(f"[OK] Shared Memory Image/Mask V2: {MULTI_IMAGE_SHARED_NAME} ({IMAGE_SHARED_SIZE} bytes)")
        except Exception as e:
            print(f"[WARN] Failed to initialize image memory V2: {e}")

        self.is_connected = (self.mm_v1 is not None or self.mm_v2 is not None)
        if self.is_connected:
            self.write_empty()

    def write_image_and_mask(self, frame_bgr, mask_binary, tracked=True):
        """
        Writes 640x480 BGRA camera frame and 320x240 player index mask to both JMI1 and JMI2 channels.
        In JMI1, player pixels must be >= 64 (0x40 in Kinect10.dll) -> written as 255.
        In JMI2, player pixels correspond to player index -> written as 1 (Player 1).
        """
        if not self.is_connected:
            return False

        try:
            ts_ms = int(time.time() * 1000)
            tracked_val = 1 if tracked else 0

            # 1. Prepare 640x480 BGRA buffer
            if frame_bgr is not None:
                if frame_bgr.shape[0] != IMAGE_H or frame_bgr.shape[1] != IMAGE_W:
                    resized_bgr = cv2.resize(frame_bgr, (IMAGE_W, IMAGE_H), interpolation=cv2.INTER_LINEAR)
                else:
                    resized_bgr = frame_bgr
                bgra_bytes = cv2.cvtColor(resized_bgr, cv2.COLOR_BGR2BGRA).tobytes()
            else:
                bgra_bytes = ZERO_BGRA_BYTES

            # 2. Prepare 320x240 masks for both V1 and V2
            if mask_binary is not None and tracked_val == 1:
                if mask_binary.shape[0] != MASK_H or mask_binary.shape[1] != MASK_W:
                    small_mask = cv2.resize(mask_binary, (MASK_W, MASK_H), interpolation=cv2.INTER_NEAREST)
                else:
                    small_mask = mask_binary

                # JMI1 expects values >= 0x40 (64) for player -> 255
                v1_mask = np.where(small_mask > 64, np.uint8(255), np.uint8(0))
                v1_mask_bytes = v1_mask.tobytes()

                # JMI2 expects player index: 1 for Player 1 -> 1
                v2_mask = np.where(small_mask > 64, np.uint8(1), np.uint8(0))
                v2_mask_bytes = v2_mask.tobytes()
            else:
                v1_mask_bytes = ZERO_MASK_BYTES
                v2_mask_bytes = ZERO_MASK_BYTES

            # 3. Write JMI1 channel (Local\LegacyWebcamKinectImage)
            if self.mm_v1 is not None:
                self.seq_v1 = (self.seq_v1 + 2) | 1
                self.mm_v1.seek(0)
                self.mm_v1.write(struct.pack(
                    IMAGE_HEADER_FMT,
                    IMAGE_MAGIC,
                    IMAGE_VERSION,
                    self.seq_v1,
                    tracked_val,
                    IMAGE_W,
                    IMAGE_H,
                    ts_ms
                ))
                self.mm_v1.write(bgra_bytes)
                self.mm_v1.write(v1_mask_bytes)
                self.seq_v1 += 1
                self.mm_v1.seek(8)
                self.mm_v1.write(struct.pack('<I', self.seq_v1))
                self.mm_v1.flush()
                self.seq = self.seq_v1

            # 4. Write JMI2 channel (Local\LegacyWebcamKinectImageV2)
            if self.mm_v2 is not None:
                self.seq_v2 = (self.seq_v2 + 2) | 1
                self.mm_v2.seek(0)
                self.mm_v2.write(struct.pack(
                    IMAGE_HEADER_FMT,
                    MULTI_IMAGE_MAGIC,
                    MULTI_IMAGE_VERSION,
                    self.seq_v2,
                    tracked_val,  # tracked_mask: bit 0 = Player 1
                    IMAGE_W,
                    IMAGE_H,
                    ts_ms
                ))
                self.mm_v2.write(bgra_bytes)
                self.mm_v2.write(v2_mask_bytes)
                self.seq_v2 += 1
                self.mm_v2.seek(8)
                self.mm_v2.write(struct.pack('<I', self.seq_v2))
                self.mm_v2.flush()

            return True
        except Exception as e:
            print(f"[WARN] Error writing image to shared memory: {e}")
            return False

    def write_empty(self):
        return self.write_image_and_mask(None, None, tracked=False)

    def close(self):
        self.write_empty()
        if self.mm_v1 is not None:
            try:
                self.mm_v1.close()
            except Exception:
                pass
            self.mm_v1 = None
        if self.mm_v2 is not None:
            try:
                self.mm_v2.close()
            except Exception:
                pass
            self.mm_v2 = None
        self.mm = None
        self.is_connected = False


class KinectCoachXSharedMemory:
    """
    Manages the 28-byte Coach X position buffer (JXC1).
    Allows setting a manual coach selection offset if enabled.
    """
    def __init__(self, tagname=COACHX_SHARED_NAME):
        self.tagname = tagname
        self.mm = None
        self.seq = 0
        self.is_connected = False
        self._init_shared_memory()

    def _init_shared_memory(self):
        try:
            self.mm = mmap.mmap(-1, COACHX_SHARED_SIZE, tagname=self.tagname)
            self.is_connected = True
            self.seq = 0
            self.write_coach_x(coach_x=0.0, enabled=False)
            print(f"[OK] Shared Memory CoachX: {self.tagname} ({COACHX_SHARED_SIZE} bytes)")
        except Exception as e:
            self.is_connected = False
            print(f"[ERROR] Failed to initialize CoachX {self.tagname}: {e}")

    def write_coach_x(self, coach_x=0.0, enabled=False):
        if not self.is_connected or self.mm is None:
            return False
        try:
            self.seq = (self.seq + 2) | 1
            ts_ms = int(time.time() * 1000)
            en_val = 1 if enabled else 0
            self.mm.seek(0)
            self.mm.write(struct.pack(
                COACHX_HEADER_FMT,
                COACHX_MAGIC,
                COACHX_VERSION,
                self.seq,
                en_val,
                float(coach_x),
                ts_ms
            ))
            self.seq += 1
            self.mm.seek(8)
            self.mm.write(struct.pack('<I', self.seq))
            self.mm.flush()
            return True
        except Exception as e:
            print(f"[WARN] Error writing CoachX to shared memory: {e}")
            return False

    def close(self):
        if self.mm is not None:
            try:
                self.mm.close()
            except Exception:
                pass
            self.mm = None
            self.is_connected = False


class KinectBridge:
    r"""
    Unified manager handling all shared memory channels for Just Dance PC:
    - Pose V1: Local\LegacyWebcamKinectPose (344 bytes, JDP1)
    - Pose V2: Local\LegacyWebcamKinectPoseV2 (664 bytes, JDP2)
    - Image V1 & V2: Local\LegacyWebcamKinectImage (1.3MB, JMI1 & JMI2)
    - CoachX: Local\LegacyWebcamKinectCoachX (28 bytes, JXC1)
    """
    def __init__(self):
        self.pose = KinectSharedMemory()
        self.pose_v2 = KinectMultiPoseSharedMemory()
        self.image = KinectImageSharedMemory()
        self.coach_x = KinectCoachXSharedMemory()

    @property
    def is_connected(self):
        return self.pose.is_connected and self.pose_v2.is_connected and self.image.is_connected

    def write(self, joints, frame_bgr, mask_binary, tracked=True):
        p1_ok = self.pose.write_pose(joints, tracked=tracked)
        p2_ok = self.pose_v2.write_poses(joints, tracked=tracked)
        i_ok = self.image.write_image_and_mask(frame_bgr, mask_binary, tracked=tracked)
        hip_x = float(joints[0][0]) if joints and tracked else 0.0
        c_ok = self.coach_x.write_coach_x(coach_x=hip_x, enabled=(tracked and joints is not None))
        return p1_ok and p2_ok and i_ok

    def write_empty(self):
        p1_ok = self.pose.write_empty()
        p2_ok = self.pose_v2.write_empty()
        i_ok = self.image.write_empty()
        self.coach_x.write_coach_x(coach_x=0.0, enabled=False)
        return p1_ok and p2_ok and i_ok

    def close(self):
        self.pose.close()
        self.pose_v2.close()
        self.image.close()
        self.coach_x.close()
        print("[INFO] All IPC shared memory channels closed.")
