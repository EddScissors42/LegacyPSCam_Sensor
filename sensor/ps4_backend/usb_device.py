"""
PlayStation 4 Camera USB Device Controller (WinUSB User-Space Driver).
Manages USB device detection, firmware initialization, Interface 0 (VideoControl)
and Interface 1 (VideoStreaming) handles, UVC Probe/Commit negotiation, and
hardware-verified ISP controls (Auto-Exposure, Gain, Powerline Frequency, White Balance).
"""
import ctypes
from ctypes import wintypes
import struct
import threading
from typing import Optional

from .constants import (
    VID_OMNIVISION,
    PID_BOOTLOADER,
    PID_STREAM_FINAL,
    PID_STREAM_LEGACY,
    ISO_ENDPOINT_IN,
    ISO_MAX_PAYLOAD_TRANSFER_SIZE,
    UVC_SET_CUR,
    UVC_GET_CUR,
    UVC_GET_MIN,
    UVC_GET_MAX,
    VS_PROBE_CONTROL,
    VS_COMMIT_CONTROL,
    CT_AE_MODE_CONTROL,
    AE_MODE_AUTO,
    PU_BRIGHTNESS_CONTROL,
    PU_CONTRAST_CONTROL,
    PU_GAIN_CONTROL,
    PU_POWER_LINE_FREQUENCY_CONTROL,
    PU_SATURATION_CONTROL,
    PU_SHARPNESS_CONTROL,
    PU_WHITE_BALANCE_TEMPERATURE_CONTROL,
    PU_WHITE_BALANCE_TEMPERATURE_AUTO_CONTROL,
    IspGeometry,
    DEFAULT_ISP_GEOMETRY,
    find_isp_geometry,
)
from .winusb_bindings import (
    GENERIC_READ,
    GENERIC_WRITE,
    FILE_SHARE_READ,
    FILE_SHARE_WRITE,
    OPEN_EXISTING,
    FILE_FLAG_OVERLAPPED,
    INVALID_HANDLE_VALUE,
    USB_CONFIGURATION_DESCRIPTOR_TYPE,
    WINUSB_SETUP_PACKET,
    WINUSB_PIPE_INFORMATION_EX,
    get_winusb_api,
    enumerate_present_device_ids,
    find_ps4_device_paths,
)
from .firmware_manager import PS4FirmwareManager


class PS4UsbDevice:
    """
    Encapsulates an open WinUSB session to a physical PlayStation 4 Camera (OV580).
    Maintains both Interface 0 (VideoControl) and Interface 1 (VideoStreaming) handles.
    """

    def __init__(self):
        self.api = get_winusb_api()
        self.lock = threading.RLock()

        self.device_path: Optional[str] = None
        self.active_pid: int = 0
        self.h_file: Optional[int] = None
        self.h_vc: Optional[int] = None  # Interface 0: VideoControl
        self.h_vs: Optional[int] = None  # Interface 1: VideoStreaming

        self.ct_entity_id: int = 1
        self.pu_entity_id: int = 3
        self.max_bytes_per_interval: int = ISO_MAX_PAYLOAD_TRANSFER_SIZE
        self.geometry: IspGeometry = DEFAULT_ISP_GEOMETRY
        self._is_open: bool = False

    @property
    def is_open(self) -> bool:
        return self._is_open and bool(self.h_vc) and bool(self.h_vs)

    @staticmethod
    def probe_hardware_status() -> dict:
        """
        Inspects Windows PnP and WinUSB interfaces to determine the exact hardware
        and driver state of the PlayStation 4 Camera without opening handles.
        """
        pnp_devs = enumerate_present_device_ids()
        vid_prefix = f"USB\\VID_{VID_OMNIVISION:04X}"

        pnp_bootloader = any(f"{vid_prefix}&PID_{PID_BOOTLOADER:04X}" in d for d in pnp_devs)
        pnp_streaming = any(
            f"{vid_prefix}&PID_{PID_STREAM_FINAL:04X}" in d
            or f"{vid_prefix}&PID_{PID_STREAM_LEGACY:04X}" in d
            for d in pnp_devs
        )

        winusb_boot_paths = find_ps4_device_paths((PID_BOOTLOADER,))
        winusb_stream_paths = find_ps4_device_paths((PID_STREAM_FINAL, PID_STREAM_LEGACY))

        winusb_bound = bool(winusb_boot_paths or winusb_stream_paths)
        fw_ready = PS4FirmwareManager.has_valid_firmware()

        if pnp_streaming and winusb_stream_paths:
            state = "READY"
        elif pnp_bootloader and winusb_boot_paths:
            state = "BOOTLOADER_UPLOADING"
        elif (pnp_streaming or pnp_bootloader) and not winusb_bound:
            state = "DRIVER_MISSING"
        else:
            state = "DISCONNECTED"

        return {
            "state": state,
            "connected": bool(pnp_bootloader or pnp_streaming),
            "bootloader": pnp_bootloader,
            "active_hw": pnp_streaming,
            "winusb_bound": winusb_bound,
            "firmware_cached": fw_ready,
            "stream_path": winusb_stream_paths[0][1] if winusb_stream_paths else None,
            "boot_path": winusb_boot_paths[0][1] if winusb_boot_paths else None,
        }

    def open(
        self,
        target_w: int = 1280,
        target_h: int = 800,
        target_fps: int = 60,
        allow_firmware_download: bool = True,
    ) -> bool:
        """
        Opens the PS4 Camera in streaming mode, automatically uploading firmware if the
        device is currently in bootloader mode (05A9:0580), claims VideoControl and
        VideoStreaming interfaces, selects Alternate Setting 1, and commits UVC YUY2 mode.
        """
        with self.lock:
            if self.is_open:
                self.request_geometry(target_w, target_h, target_fps)
                return True

            if not self.api.available:
                return False

            # 1. Ensure device is in streaming mode (058B or 058A), uploading firmware if in 0580
            stream_devs = find_ps4_device_paths((PID_STREAM_FINAL, PID_STREAM_LEGACY))
            if not stream_devs:
                ok_fw, msg_fw = PS4FirmwareManager.upload_to_bootloader_device(
                    allow_download=allow_firmware_download,
                    wait_reenumerate_s=6.5,
                )
                if not ok_fw:
                    print(f"[PS4-USB] Firmware bring-up failed: {msg_fw}")
                    return False
                stream_devs = find_ps4_device_paths((PID_STREAM_FINAL, PID_STREAM_LEGACY))
                if not stream_devs:
                    print("[PS4-USB] Streaming interface not found after firmware upload.")
                    return False

            self.active_pid, self.device_path = stream_devs[0]

            # 2. Open File Handle with Overlapped I/O for Isochronous Streaming
            h_file = self.api.kernel32.CreateFileW(
                self.device_path,
                GENERIC_READ | GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                None,
                OPEN_EXISTING,
                FILE_FLAG_OVERLAPPED,
                None,
            )
            if not h_file or h_file == INVALID_HANDLE_VALUE:
                err = self.api.kernel32.GetLastError()
                print(f"[PS4-USB] CreateFileW failed on {self.device_path} (err={err})")
                self.device_path = None
                return False

            # 3. Initialize Interface 0 (VideoControl)
            h_vc = wintypes.HANDLE()
            if not self.api.winusb.WinUsb_Initialize(h_file, ctypes.byref(h_vc)):
                err = self.api.kernel32.GetLastError()
                print(f"[PS4-USB] WinUsb_Initialize failed (err={err})")
                self.api.kernel32.CloseHandle(h_file)
                return False

            # 4. Acquire Associated Interface 1 (VideoStreaming)
            h_vs = wintypes.HANDLE()
            if not self.api.winusb.WinUsb_GetAssociatedInterface(h_vc, 0, ctypes.byref(h_vs)):
                err = self.api.kernel32.GetLastError()
                print(f"[PS4-USB] WinUsb_GetAssociatedInterface(0) failed (err={err})")
                self.api.winusb.WinUsb_Free(h_vc)
                self.api.kernel32.CloseHandle(h_file)
                return False

            self.h_file = h_file
            self.h_vc = h_vc.value
            self.h_vs = h_vs.value

            # 5. Parse UVC Entity IDs from Configuration Descriptor
            self._discover_uvc_entities()

            # 6. Select Streaming Alternate Setting 1 on Interface 1
            if not self.api.winusb.WinUsb_SetCurrentAlternateSetting(self.h_vs, 1):
                err = self.api.kernel32.GetLastError()
                print(f"[PS4-USB] WinUsb_SetCurrentAlternateSetting(1) failed (err={err})")
                self.close()
                return False

            # 7. Query Isochronous Endpoint 0x81 parameters
            pipe_ex = WINUSB_PIPE_INFORMATION_EX()
            if self.api.winusb.WinUsb_QueryPipeEx(self.h_vs, 1, 0, ctypes.byref(pipe_ex)):
                if pipe_ex.MaximumBytesPerInterval > 0:
                    self.max_bytes_per_interval = int(pipe_ex.MaximumBytesPerInterval)

            # 8. Resolve requested geometry & commit UVC stream
            geom = find_isp_geometry(target_w, target_h, target_fps) or DEFAULT_ISP_GEOMETRY
            self.geometry = geom

            if not self._bring_up_isp(self.geometry):
                print("[PS4-USB] ISP UVC Probe/Commit failed.")
                self.close()
                return False

            self._is_open = True
            print(
                f"[PS4-USB] Opened PlayStation 4 Camera (PID={self.active_pid:#06x}) | "
                f"Mode: {self.geometry.eye_w}x{self.geometry.eye_h} @ {self.geometry.fps} FPS | "
                f"Isoch Bytes/Interval: {self.max_bytes_per_interval}"
            )
            return True

    def _discover_uvc_entities(self) -> None:
        """
        Parses the USB Configuration Descriptor to locate the Camera Terminal (ITT_CAMERA=0x0201)
        and Processing Unit (VC_PROCESSING_UNIT=0x05) entity IDs.
        """
        if not self.h_vc:
            return
        buf = (ctypes.c_uint8 * 1024)()
        transferred = wintypes.ULONG(0)
        ok = self.api.winusb.WinUsb_GetDescriptor(
            self.h_vc,
            USB_CONFIGURATION_DESCRIPTOR_TYPE,
            0,
            0,
            buf,
            1024,
            ctypes.byref(transferred),
        )
        if not ok or transferred.value < 9:
            return

        raw = bytes(buf[: transferred.value])
        pos = 0
        while pos + 3 <= len(raw):
            length = raw[pos]
            dtype = raw[pos + 1]
            dsub = raw[pos + 2]
            if length < 3 or pos + length > len(raw):
                break
            # CS_INTERFACE (0x24) -> VC_INPUT_TERMINAL (0x02) -> ITT_CAMERA (0x0201)
            if dtype == 0x24 and dsub == 0x02 and length >= 6:
                term_type = raw[pos + 4] | (raw[pos + 5] << 8)
                if term_type == 0x0201:
                    self.ct_entity_id = raw[pos + 3]
            # CS_INTERFACE (0x24) -> VC_PROCESSING_UNIT (0x05)
            elif dtype == 0x24 and dsub == 0x05 and length >= 4:
                self.pu_entity_id = raw[pos + 3]
            pos += length

    def _recover_control_pipe(self) -> None:
        """
        Clears a stalled control pipe and resynchronizes with a known-good VS_PROBE GET_CUR.
        """
        if not self.h_vc or not self.h_vs:
            return
        self.api.winusb.WinUsb_ResetPipe(self.h_vc, 0x00)
        probe = (ctypes.c_uint8 * 26)()
        transferred = wintypes.ULONG(0)
        pkt = WINUSB_SETUP_PACKET(0xA1, UVC_GET_CUR, VS_PROBE_CONTROL, 1, 26)
        self.api.winusb.WinUsb_ControlTransfer(
            self.h_vs, pkt, probe, 26, ctypes.byref(transferred), None
        )

    def _bring_up_isp(self, geom: IspGeometry) -> bool:
        """
        Commits the UVC YUY2 video format and frame geometry on Interface 1 (VideoStreaming),
        then enables Auto-Exposure and 60Hz Anti-Flicker on Interface 0 (VideoControl).
        """
        if not self.h_vc or not self.h_vs:
            return False

        probe_buf = bytearray(26)
        # bmHint = 0x0001 (keep dwFrameInterval), bFormatIndex = 1 (YUY2), bFrameIndex = geom.frame_index
        struct.pack_into(
            "<HBBII",
            probe_buf,
            0,
            0x0001,
            1,
            geom.frame_index,
            geom.interval_100ns,
            0,
        )
        # dwMaxVideoFrameSize (offset 18) and dwMaxPayloadTransferSize (offset 22)
        struct.pack_into(
            "<II",
            probe_buf,
            18,
            geom.frame_bytes,
            ISO_MAX_PAYLOAD_TRANSFER_SIZE,
        )

        c_probe = (ctypes.c_uint8 * 26).from_buffer(probe_buf)
        transferred = wintypes.ULONG(0)

        # 1. VS_PROBE_CONTROL SET_CUR on Interface 1 (h_vs)
        pkt_set_probe = WINUSB_SETUP_PACKET(0x21, UVC_SET_CUR, VS_PROBE_CONTROL, 1, 26)
        if not self.api.winusb.WinUsb_ControlTransfer(
            self.h_vs, pkt_set_probe, c_probe, 26, ctypes.byref(transferred), None
        ):
            self._recover_control_pipe()
            if not self.api.winusb.WinUsb_ControlTransfer(
                self.h_vs, pkt_set_probe, c_probe, 26, ctypes.byref(transferred), None
            ):
                return False

        # 2. VS_PROBE_CONTROL GET_CUR on Interface 1 (h_vs)
        c_got = (ctypes.c_uint8 * 26)()
        pkt_get_probe = WINUSB_SETUP_PACKET(0xA1, UVC_GET_CUR, VS_PROBE_CONTROL, 1, 26)
        ok_get = self.api.winusb.WinUsb_ControlTransfer(
            self.h_vs, pkt_get_probe, c_got, 26, ctypes.byref(transferred), None
        )
        commit_payload = c_got if (ok_get and transferred.value == 26) else c_probe

        # 3. VS_COMMIT_CONTROL SET_CUR on Interface 1 (h_vs)
        pkt_commit = WINUSB_SETUP_PACKET(0x21, UVC_SET_CUR, VS_COMMIT_CONTROL, 1, 26)
        if not self.api.winusb.WinUsb_ControlTransfer(
            self.h_vs, pkt_commit, commit_payload, 26, ctypes.byref(transferred), None
        ):
            self._recover_control_pipe()
            if not self.api.winusb.WinUsb_ControlTransfer(
                self.h_vs, pkt_commit, commit_payload, 26, ctypes.byref(transferred), None
            ):
                return False

        # 4. Enable Auto-Exposure on Camera Terminal (lifts near-black default image to normal luma)
        self.apply_default_isp_controls()
        return True

    def _uvc_set_vc_control(self, selector: int, entity_id: int, payload: bytes) -> bool:
        """
        Sends a UVC SET_CUR control transfer to an entity on Interface 0 (VideoControl).
        Note: WinUSB overwrites the low byte of Index with the interface number (0),
        while preserving the high byte (entity_id << 8).
        """
        if not self.h_vc:
            return False
        size = len(payload)
        c_data = (ctypes.c_uint8 * size).from_buffer_copy(payload)
        transferred = wintypes.ULONG(0)
        pkt = WINUSB_SETUP_PACKET(
            0x21,
            UVC_SET_CUR,
            (selector << 8),
            (entity_id << 8) | 0,
            size,
        )
        ok = self.api.winusb.WinUsb_ControlTransfer(
            self.h_vc, pkt, c_data, size, ctypes.byref(transferred), None
        )
        if not ok:
            self._recover_control_pipe()
            ok = self.api.winusb.WinUsb_ControlTransfer(
                self.h_vc, pkt, c_data, size, ctypes.byref(transferred), None
            )
            if not ok:
                self._recover_control_pipe()
        return bool(ok)

    def apply_default_isp_controls(self) -> None:
        """
        Applies hardware-verified ISP controls on Interface 0 (VideoControl):
        - Camera Terminal Auto-Exposure (CT_AE_MODE_CONTROL = 0x02)
        - Processing Unit 60Hz Powerline Anti-Flicker (PU_POWER_LINE_FREQUENCY_CONTROL = 2)
        - Processing Unit Auto White Balance (PU_WHITE_BALANCE_TEMPERATURE_AUTO_CONTROL = 1)
        """
        if self.ct_entity_id:
            self._uvc_set_vc_control(
                CT_AE_MODE_CONTROL, self.ct_entity_id, bytes([AE_MODE_AUTO])
            )
        if self.pu_entity_id:
            # Powerline frequency: 2 = 60 Hz anti-flicker
            self._uvc_set_vc_control(
                PU_POWER_LINE_FREQUENCY_CONTROL, self.pu_entity_id, bytes([2])
            )
            # Auto White Balance: 1 = enabled
            self._uvc_set_vc_control(
                PU_WHITE_BALANCE_TEMPERATURE_AUTO_CONTROL, self.pu_entity_id, bytes([1])
            )

    def set_gain(self, gain_0_to_8: int) -> bool:
        """
        Adjusts the OV580 Processing Unit gain (hardware range 0..8).
        """
        if not self.pu_entity_id:
            return False
        clamped = max(0, min(8, int(gain_0_to_8)))
        return self._uvc_set_vc_control(
            PU_GAIN_CONTROL, self.pu_entity_id, struct.pack("<H", clamped)
        )

    def request_geometry(self, width: int, height: int, fps: int) -> bool:
        """
        Switches the OV580 to a new hardware-verified ISP geometry.
        """
        geom = find_isp_geometry(width, height, fps)
        if geom is None:
            return False
        with self.lock:
            if geom == self.geometry and self._is_open:
                return True
            self.geometry = geom
            if self._is_open and self.h_vs:
                self.api.winusb.WinUsb_SetCurrentAlternateSetting(self.h_vs, 0)
                self.api.winusb.WinUsb_SetCurrentAlternateSetting(self.h_vs, 1)
                return self._bring_up_isp(self.geometry)
            return True

    def close(self) -> None:
        """
        Cleanly releases Interface 1, Interface 0, and the underlying device file handle.
        """
        with self.lock:
            self._is_open = False
            if self.h_vs:
                try:
                    self.api.winusb.WinUsb_Free(self.h_vs)
                except Exception:
                    pass
                self.h_vs = None

            if self.h_vc:
                try:
                    self.api.winusb.WinUsb_Free(self.h_vc)
                except Exception:
                    pass
                self.h_vc = None

            if self.h_file and self.h_file != INVALID_HANDLE_VALUE:
                try:
                    self.api.kernel32.CloseHandle(self.h_file)
                except Exception:
                    pass
                self.h_file = None

            self.device_path = None
            self.active_pid = 0
