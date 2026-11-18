"""
Constants, Hardware Identifiers, ISP Video Geometries, and UVC Protocol Selectors
for the PlayStation 4 Camera (OmniVision OV580 + Dual OV9713 Stereo Sensors).
"""
from dataclasses import dataclass
from typing import Optional

# =============================================================================
# 1. USB Hardware Identifiers (OmniVision OV580 Bridge)
# =============================================================================
VID_OMNIVISION = 0x05A9
PID_BOOTLOADER = 0x0580      # Pre-firmware "USB Boot" state
PID_STREAM_LEGACY = 0x058A   # Streaming state (legacy firmware)
PID_STREAM_FINAL = 0x058B    # Streaming state (final PS4 sys 6.00-7.02 composite IAD)

PS4_STREAM_PIDS = (PID_STREAM_FINAL, PID_STREAM_LEGACY)
PS4_ALL_PIDS = (PID_BOOTLOADER, PID_STREAM_FINAL, PID_STREAM_LEGACY)

# Device Interface GUIDs for WinUSB & USB Device Discovery
PS4_DEVICE_INTERFACE_GUID = "{B8F4A2C0-5D31-4E76-9A1B-6C0E3F8D2A47}"
USB_DEVICE_INTERFACE_GUID = "{A5DCBF10-6530-11D2-901F-00C04FB951ED}"

# =============================================================================
# 2. OV580 Firmware & Verification Constants
# =============================================================================
# Final OV580 firmware build (byte-identical across PS4 system 6.00-7.02).
FIRMWARE_FILENAME = "firmware.bin"
FIRMWARE_SIZE = 68032
FIRMWARE_SHA1 = "8b8a6621d358f6782c2e3b31aac2cdfb25102c00"
FIRMWARE_SHA256 = "09513d1068b9b5e23b09e03bca5640ed4d01830b034b9802395006b14a927b01"

STARTUP_FILENAME = "startup.bin"
STARTUP_SIZE = 59204
STARTUP_SHA1 = "48d103615008f73a286014ee5408ea9617bb1d3d"
STARTUP_SHA256 = "cd019ab9ac8d6bf127dd9222640ff617b218e44ebf538930f929b9a358fd2ca0"

FIRMWARE_DOWNLOAD_URLS = (
    "https://raw.githubusercontent.com/psxdev/OrbisEyeCam/master/bin/firmware.bin",
    "https://raw.githubusercontent.com/Hackinside/PS4-CAMERA-DRIVERS/master/firmware.bin",
)

STARTUP_DOWNLOAD_URLS = (
    "https://raw.githubusercontent.com/ps4eye/ps4eye/master/binaries/startup.bin",
)

# Bootloader USB Control Transfer Upload Protocol
FW_CHUNK_SIZE = 512
FW_REQ_TYPE_VENDOR_OUT = 0x40
FW_REQ_UPLOAD = 0x00
FW_BASE_INDEX = 0x0014
FW_REBOOT_VALUE = 0x2200
FW_REBOOT_INDEX = 0x8018
FW_REBOOT_BYTE = 0x5B

# =============================================================================
# 3. Eye Selection Constants
# =============================================================================
EYE_RIGHT = "right"
EYE_LEFT = "left"
EYE_BOTH_SBS = "sbs"
DEFAULT_EYE = EYE_RIGHT

# =============================================================================
# 4. UVC & Isochronous Streaming Constants
# =============================================================================
ISO_ENDPOINT_IN = 0x81
ISO_MAX_PAYLOAD_TRANSFER_SIZE = 49152  # 48 KB per SuperSpeed service interval
ISO_PACKETS_PER_TRANSFER = 32          # Multiple of 8 microframes (4 ms per URB)
ISO_NUM_TRANSFERS = 8                  # 8 concurrent URBs (~32 ms ring buffer)

# UVC Request Codes
UVC_SET_CUR = 0x01
UVC_GET_CUR = 0x81
UVC_GET_MIN = 0x82
UVC_GET_MAX = 0x83
UVC_GET_DEF = 0x87

# UVC VideoStreaming Control Selectors (wValue = selector << 8)
VS_PROBE_CONTROL = 0x0100
VS_COMMIT_CONTROL = 0x0200

# UVC Camera Terminal & Processing Unit Control Selectors
CT_AE_MODE_CONTROL = 0x02
AE_MODE_AUTO = 0x02

PU_BRIGHTNESS_CONTROL = 0x02
PU_CONTRAST_CONTROL = 0x03
PU_GAIN_CONTROL = 0x04
PU_POWER_LINE_FREQUENCY_CONTROL = 0x05
PU_SATURATION_CONTROL = 0x07
PU_SHARPNESS_CONTROL = 0x08
PU_WHITE_BALANCE_TEMPERATURE_CONTROL = 0x0A
PU_WHITE_BALANCE_TEMPERATURE_AUTO_CONTROL = 0x0B

# Row Framing Offsets
ROW_HEADER_BYTES = 32
ROW_AUDIO_BYTES = 64
ROW_LEFT_EYE_OFFSET = ROW_HEADER_BYTES + ROW_AUDIO_BYTES  # 96 bytes


# =============================================================================
# 5. Hardware-Verified OV580 ISP Geometries
# =============================================================================
@dataclass(frozen=True)
class IspGeometry:
    """
    Describes one hardware-verified OV580 ISP video mode.
    Every delivered row has the layout:
        [32B header][64B audio][Left Eye (eye_w * 2B)][Right Eye (eye_w * 2B)][trailer]
    """
    frame_index: int
    interval_100ns: int
    row_px: int
    rows: int
    eye_w: int
    eye_h: int
    fps: int

    @property
    def row_bytes(self) -> int:
        return self.row_px * 2

    @property
    def band_bytes(self) -> int:
        return self.eye_w * 2

    @property
    def left_offset(self) -> int:
        return ROW_LEFT_EYE_OFFSET

    @property
    def right_offset(self) -> int:
        return ROW_LEFT_EYE_OFFSET + self.band_bytes

    @property
    def frame_bytes(self) -> int:
        return self.row_bytes * self.rows

    @property
    def eye_bytes(self) -> int:
        return self.eye_w * self.eye_h * 2


ISP_GEOMETRIES: tuple[IspGeometry, ...] = (
    # 1280 x 800 modes (Frame Index 1)
    IspGeometry(frame_index=1, interval_100ns=166666, row_px=3448, rows=808, eye_w=1280, eye_h=800, fps=60),
    IspGeometry(frame_index=1, interval_100ns=333333, row_px=3448, rows=808, eye_w=1280, eye_h=800, fps=30),
    IspGeometry(frame_index=1, interval_100ns=666666, row_px=3448, rows=808, eye_w=1280, eye_h=800, fps=15),
    # 640 x 400 modes (Frame Index 2)
    IspGeometry(frame_index=2, interval_100ns=83333,  row_px=1748, rows=408, eye_w=640,  eye_h=400, fps=120),
    IspGeometry(frame_index=2, interval_100ns=166666, row_px=1748, rows=408, eye_w=640,  eye_h=400, fps=60),
    IspGeometry(frame_index=2, interval_100ns=333333, row_px=1748, rows=408, eye_w=640,  eye_h=400, fps=30),
    # 320 x 192 modes (Frame Index 3)
    IspGeometry(frame_index=3, interval_100ns=41666,  row_px=898,  rows=200, eye_w=320,  eye_h=192, fps=240),
    IspGeometry(frame_index=3, interval_100ns=83333,  row_px=898,  rows=200, eye_w=320,  eye_h=192, fps=120),
    IspGeometry(frame_index=3, interval_100ns=166666, row_px=898,  rows=200, eye_w=320,  eye_h=192, fps=60),
)

DEFAULT_ISP_GEOMETRY: IspGeometry = ISP_GEOMETRIES[0]


def find_isp_geometry(width: int, height: int, fps: int) -> Optional[IspGeometry]:
    """
    Looks up an exact or compatible OV580 ISP geometry.
    Maps legacy 640x480 requests to the hardware's native 640x400 mode.
    Returns None if the requested resolution is not supported by the hardware.
    """
    norm_h = 400 if (width == 640 and height == 480) else height

    # 1. Exact match on (eye_w, eye_h, fps)
    for g in ISP_GEOMETRIES:
        if g.eye_w == width and g.eye_h == norm_h and g.fps == fps:
            return g

    # 2. Match resolution with closest supported FPS
    res_matches = [g for g in ISP_GEOMETRIES if g.eye_w == width and g.eye_h == norm_h]
    if res_matches:
        return min(res_matches, key=lambda g: abs(g.fps - fps))

    return None
