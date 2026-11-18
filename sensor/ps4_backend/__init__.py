"""
Native PlayStation 4 Camera Backend for Legacy PSCam Sensor.
Provides direct User-Space WinUSB device management, automatic OV580 firmware
staging & upload, UVC ISP negotiation, and 60 FPS dual-eye isochronous streaming.
"""
from .constants import (
    VID_OMNIVISION,
    PID_BOOTLOADER,
    PID_STREAM_LEGACY,
    PID_STREAM_FINAL,
    PS4_DEVICE_INTERFACE_GUID,
    USB_DEVICE_INTERFACE_GUID,
    FIRMWARE_FILENAME,
    FIRMWARE_SIZE,
    FIRMWARE_SHA1,
    FIRMWARE_SHA256,
    EYE_RIGHT,
    EYE_LEFT,
    EYE_BOTH_SBS,
    DEFAULT_EYE,
    IspGeometry,
    ISP_GEOMETRIES,
    DEFAULT_ISP_GEOMETRY,
    find_isp_geometry,
)
from .winusb_bindings import (
    get_winusb_api,
    enumerate_present_device_ids,
    enumerate_interface_paths,
    find_ps4_device_paths,
)
from .firmware_manager import PS4FirmwareManager
from .usb_device import PS4UsbDevice
from .frame_streamer import (
    PS4CameraBackend,
    depacketize_uvc_packet,
    demux_stereo_frame_yuy2,
    yuy2_to_bgr,
)
from .driver_installer import PS4DriverInstaller

__all__ = [
    "VID_OMNIVISION",
    "PID_BOOTLOADER",
    "PID_STREAM_LEGACY",
    "PID_STREAM_FINAL",
    "PS4_DEVICE_INTERFACE_GUID",
    "USB_DEVICE_INTERFACE_GUID",
    "FIRMWARE_FILENAME",
    "FIRMWARE_SIZE",
    "FIRMWARE_SHA1",
    "FIRMWARE_SHA256",
    "EYE_RIGHT",
    "EYE_LEFT",
    "EYE_BOTH_SBS",
    "DEFAULT_EYE",
    "IspGeometry",
    "ISP_GEOMETRIES",
    "DEFAULT_ISP_GEOMETRY",
    "find_isp_geometry",
    "get_winusb_api",
    "enumerate_present_device_ids",
    "enumerate_interface_paths",
    "find_ps4_device_paths",
    "PS4FirmwareManager",
    "PS4UsbDevice",
    "PS4CameraBackend",
    "depacketize_uvc_packet",
    "demux_stereo_frame_yuy2",
    "yuy2_to_bgr",
    "PS4DriverInstaller",
]
