"""
High-Performance Isochronous Frame Streamer and Stereo Eye Demultiplexer
for the PlayStation 4 Camera (OV580 + Dual OV9713 Sensors).

Features:
- Asynchronous 8-URB Overlapped Isochronous Ring via WinUsb_ReadIsochPipeAsap.
- Zero-copy C memmove depacketizer stripping 12-byte UVC / 4-byte continuation headers.
- Simultaneous extraction of Left Eye and Right Eye YUY2 planes with hardware PTS timestamps.
- Default Right Eye output ("right") with live switching to Left Eye ("left") or Side-by-Side ("sbs").
- Automatic USB disconnect detection and hot-plug recovery (including automatic firmware re-upload).
"""
import ctypes
from ctypes import wintypes
import struct
import threading
import time
from typing import Optional
import cv2
import numpy as np

from .constants import (
    ISO_ENDPOINT_IN,
    ISO_PACKETS_PER_TRANSFER,
    ISO_NUM_TRANSFERS,
    EYE_RIGHT,
    EYE_LEFT,
    EYE_BOTH_SBS,
    DEFAULT_EYE,
    IspGeometry,
    DEFAULT_ISP_GEOMETRY,
)
from .winusb_bindings import (
    ERROR_IO_PENDING,
    WAIT_OBJECT_0,
    USBD_ISO_PACKET_DESCRIPTOR,
    OVERLAPPED,
    get_winusb_api,
)
from .usb_device import PS4UsbDevice


def depacketize_uvc_packet(packet_bytes: bytes) -> tuple[Optional[int], Optional[int], bytes]:
    """
    Parses a single raw isochronous packet from the OV580 endpoint 0x81.
    Returns (fid, pts, video_payload):
      - If packet starts with 0x0C and has PTS+SCR bits ((b1 & 0x0C) == 0x0C):
        strips 12-byte UVC header and returns (fid_bit, pts_uint32, payload).
      - Otherwise:
        strips 4-byte continuation header and returns (None, None, payload).
    """
    length = len(packet_bytes)
    if length <= 4:
        return None, None, b""

    b0 = packet_bytes[0]
    b1 = packet_bytes[1]
    hdr12 = (b0 == 0x0C) and (length >= 12) and ((b1 & 0x0C) == 0x0C)
    if hdr12:
        fid = b1 & 0x01
        pts = struct.unpack_from("<I", packet_bytes, 2)[0]
        return fid, pts, packet_bytes[12:]
    return None, None, packet_bytes[4:]


def demux_stereo_frame_yuy2(
    raw_frame_buffer: np.ndarray, geom: IspGeometry = DEFAULT_ISP_GEOMETRY
) -> tuple[np.ndarray, np.ndarray]:
    """
    Demultiplexes a complete OV580 raw ISP frame into independent Left and Right YUY2 planes.
    Each row of `raw_frame_buffer` has shape:
        [32B header][64B audio][Left Eye (eye_w * 2B)][Right Eye (eye_w * 2B)][trailer]
    Returns (left_yuy2, right_yuy2), each of shape (eye_h, eye_w, 2) with dtype=uint8.
    """
    image_bytes = geom.eye_h * geom.row_bytes
    if raw_frame_buffer.size < image_bytes:
        raise ValueError(
            f"Raw frame buffer size ({raw_frame_buffer.size}) is smaller than required image bytes ({image_bytes})."
        )

    flat_view = raw_frame_buffer.reshape(-1)[:image_bytes]
    rows_2d = flat_view.reshape((geom.eye_h, geom.row_bytes))

    l_start = geom.left_offset
    l_end = l_start + geom.band_bytes
    r_start = geom.right_offset
    r_end = r_start + geom.band_bytes

    left_yuy2 = np.ascontiguousarray(rows_2d[:, l_start:l_end]).reshape((geom.eye_h, geom.eye_w, 2))
    right_yuy2 = np.ascontiguousarray(rows_2d[:, r_start:r_end]).reshape((geom.eye_h, geom.eye_w, 2))
    return left_yuy2, right_yuy2


def yuy2_to_bgr(yuy2_plane: np.ndarray) -> np.ndarray:
    """Converts a (H, W, 2) YUY2 array into a (H, W, 3) BGR image for OpenCV / MediaPipe."""
    return cv2.cvtColor(yuy2_plane, cv2.COLOR_YUV2BGR_YUY2)


class PS4CameraBackend:
    """
    Native User-Space Streaming Engine for PlayStation 4 Camera Slim.
    Delivers low-latency BGR frames for the selected eye (Right Eye by default)
    while retaining both Left and Right sensor streams in memory for stereo consumers.
    """

    def __init__(
        self,
        target_w: int = 1280,
        target_h: int = 800,
        target_fps: int = 60,
        eye: str = DEFAULT_EYE,
        auto_reconnect: bool = True,
    ):
        self.api = get_winusb_api()
        self.usb_dev = PS4UsbDevice()
        self.target_w = int(target_w)
        self.target_h = int(target_h)
        self.target_fps = int(target_fps)
        self.eye = self._normalize_eye(eye)
        self.auto_reconnect = bool(auto_reconnect)

        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.lock = threading.Lock()

        # Dual-sensor synchronized frame latch
        self._left_yuy2: Optional[np.ndarray] = None
        self._right_yuy2: Optional[np.ndarray] = None
        self._selected_bgr: Optional[np.ndarray] = None
        self._frame_seq: int = 0
        self._last_consumed_seq: int = 0
        self._hardware_pts: int = 0
        self._timestamp_ms: int = 0
        self._last_frame_perf: float = 0.0

        # FPS telemetry
        self._fps_counter: int = 0
        self._fps_t0: float = time.perf_counter()
        self.measured_fps: float = float(target_fps)

    @staticmethod
    def _normalize_eye(eye: str) -> str:
        val = str(eye or DEFAULT_EYE).strip().lower()
        if val in (EYE_LEFT, "esquerdo", "left_eye", "l"):
            return EYE_LEFT
        if val in (EYE_BOTH_SBS, "side_by_side", "stereo"):
            return EYE_BOTH_SBS
        return EYE_RIGHT

    def set_eye(self, eye: str) -> None:
        """
        Switches the active output eye ("right", "left", or "sbs") live without interrupting the USB stream.
        """
        norm = self._normalize_eye(eye)
        with self.lock:
            if norm == self.eye:
                return
            self.eye = norm
            if self._left_yuy2 is not None and self._right_yuy2 is not None:
                self._selected_bgr = self._compose_selected_bgr_unlocked(
                    self._left_yuy2, self._right_yuy2, self.eye
                )

    @staticmethod
    def _compose_selected_bgr_unlocked(
        left_yuy2: np.ndarray, right_yuy2: np.ndarray, eye: str
    ) -> np.ndarray:
        if eye == EYE_LEFT:
            return yuy2_to_bgr(left_yuy2)
        if eye == EYE_BOTH_SBS:
            sbs_yuy2 = np.hstack((left_yuy2, right_yuy2))
            return yuy2_to_bgr(sbs_yuy2)
        return yuy2_to_bgr(right_yuy2)

    @property
    def is_connected(self) -> bool:
        return self.running and self.usb_dev.is_open

    @property
    def actual_width(self) -> int:
        g = self.usb_dev.geometry
        return g.eye_w * 2 if self.eye == EYE_BOTH_SBS else g.eye_w

    @property
    def actual_height(self) -> int:
        return self.usb_dev.geometry.eye_h

    @property
    def actual_fps(self) -> int:
        return self.usb_dev.geometry.fps

    def start(self) -> bool:
        """
        Opens the PlayStation 4 Camera USB device (uploading firmware if in bootloader mode)
        and starts the background isochronous capture thread.
        """
        if self.running:
            return True

        if not self.usb_dev.open(self.target_w, self.target_h, self.target_fps):
            return False

        self.running = True
        self.thread = threading.Thread(
            target=self._iso_stream_loop,
            daemon=True,
            name="PS4IsochStreamThread",
        )
        self.thread.start()
        return True

    def stop(self) -> None:
        """
        Stops the isochronous capture loop and releases all WinUSB handles and buffers.
        """
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.5)
        self.thread = None
        self.usb_dev.close()

    def read_frame(self, only_new: bool = False) -> Optional[np.ndarray]:
        """
        Returns the latest BGR frame for the selected eye (Right Eye by default).
        If `only_new=True`, returns None when no new hardware frame has arrived since the last call.
        """
        with self.lock:
            if self._selected_bgr is None:
                return None
            if only_new and self._frame_seq == self._last_consumed_seq:
                return None
            self._last_consumed_seq = self._frame_seq
            return self._selected_bgr

    def read_left_mono(self) -> Optional[np.ndarray]:
        """
        Returns the latest synchronized Left Eye single-channel 8-bit luminance plane (H, W)
        directly from the raw YUY2 buffer without converting to 3-channel BGR.
        Ultra-fast (<0.08 ms), eliminates redundant YUY2->BGR color conversion overhead.
        """
        with self.lock:
            if self._left_yuy2 is None:
                return None
            return np.ascontiguousarray(self._left_yuy2[:, :, 0])

    def read_right_mono(self) -> Optional[np.ndarray]:
        """
        Returns the latest synchronized Right Eye single-channel 8-bit luminance plane (H, W)
        directly from the raw YUY2 buffer without converting to 3-channel BGR.
        Used by Stereo Vision when the Left Eye is selected as the primary tracking lens.
        """
        with self.lock:
            if self._right_yuy2 is None:
                return None
            return np.ascontiguousarray(self._right_yuy2[:, :, 0])

    def read_left_frame(self, mono: bool = False) -> Optional[np.ndarray]:
        """
        Returns the latest synchronized Left Eye BGR (or 8-bit luminance if mono=True) frame
        without re-converting the Right Eye.
        Used by Stereo Vision when the Right Eye was already read via `read_frame()`.
        """
        if mono:
            return self.read_left_mono()
        with self.lock:
            if self._left_yuy2 is None:
                return None
            if self.eye == EYE_LEFT and self._selected_bgr is not None:
                return self._selected_bgr
            left_copy = self._left_yuy2.copy()
        return yuy2_to_bgr(left_copy)

    def read_stereo_frames(self, only_new: bool = False) -> Optional[dict]:
        """
        Returns both Left and Right sensor frames along with hardware PTS and host timestamp
        for dual-sensor / 3D stereo processing modules:
            {
                "right_bgr": np.ndarray,
                "left_bgr": np.ndarray,
                "right_yuy2": np.ndarray,
                "left_yuy2": np.ndarray,
                "pts": int,
                "timestamp_ms": int,
                "seq": int,
            }
        Reuses the pre-converted `_selected_bgr` buffer for the active eye to eliminate
        redundant YUY2->BGR conversion at 60 FPS.
        """
        with self.lock:
            if self._left_yuy2 is None or self._right_yuy2 is None:
                return None
            if only_new and self._frame_seq == self._last_consumed_seq:
                return None
            self._last_consumed_seq = self._frame_seq
            left_copy = self._left_yuy2.copy()
            right_copy = self._right_yuy2.copy()
            active_eye = self.eye
            cached_bgr = self._selected_bgr
            pts = self._hardware_pts
            ts_ms = self._timestamp_ms
            seq = self._frame_seq

        if active_eye == EYE_RIGHT and cached_bgr is not None:
            right_bgr = cached_bgr
            left_bgr = yuy2_to_bgr(left_copy)
        elif active_eye == EYE_LEFT and cached_bgr is not None:
            left_bgr = cached_bgr
            right_bgr = yuy2_to_bgr(right_copy)
        else:
            right_bgr = yuy2_to_bgr(right_copy)
            left_bgr = yuy2_to_bgr(left_copy)

        return {
            "right_bgr": right_bgr,
            "left_bgr": left_bgr,
            "right_yuy2": right_copy,
            "left_yuy2": left_copy,
            "pts": pts,
            "timestamp_ms": ts_ms,
            "seq": seq,
        }

    def _publish_raw_frame(self, accum_np: np.ndarray, geom: IspGeometry, pts: int) -> None:
        """
        Demuxes a completed raw ISP frame into Left and Right YUY2 planes, converts the active
        eye to BGR, and updates the thread-safe latch.
        """
        left_yuy2, right_yuy2 = demux_stereo_frame_yuy2(accum_np, geom)
        now_perf = time.perf_counter()
        now_ms = int(time.time() * 1000)

        with self.lock:
            active_eye = self.eye

        selected_bgr = self._compose_selected_bgr_unlocked(left_yuy2, right_yuy2, active_eye)

        with self.lock:
            self._left_yuy2 = left_yuy2
            self._right_yuy2 = right_yuy2
            self._selected_bgr = selected_bgr
            self._hardware_pts = int(pts)
            self._timestamp_ms = max(now_ms, self._timestamp_ms + 1)
            self._last_frame_perf = now_perf
            self._frame_seq += 1

            self._fps_counter += 1
            elapsed = now_perf - self._fps_t0
            if elapsed >= 0.5:
                self.measured_fps = self._fps_counter / elapsed
                self._fps_counter = 0
                self._fps_t0 = now_perf

    def _iso_stream_loop(self) -> None:
        """
        Main background loop managing the 8-URB Overlapped Isochronous Ring
        and automatic hot-plug reconnection.
        """
        while self.running:
            if not self.usb_dev.is_open:
                if not self.auto_reconnect:
                    break
                if not self.usb_dev.open(self.target_w, self.target_h, self.target_fps):
                    time.sleep(0.5)
                    continue

            self._run_single_session()

            if self.running and self.auto_reconnect:
                print("[PS4-STREAM] USB stream interrupted; attempting automatic reconnection...")
                self.usb_dev.close()
                time.sleep(0.4)

    def _run_single_session(self) -> None:
        api = self.api
        h_vs = self.usb_dev.h_vs
        if not h_vs:
            return

        geom = self.usb_dev.geometry
        pkt_size = self.usb_dev.max_bytes_per_interval
        num_pkts = ISO_PACKETS_PER_TRANSFER
        num_urb = ISO_NUM_TRANSFERS
        urb_len = num_pkts * pkt_size
        total_buf_size = num_urb * urb_len

        iso_buf = (ctypes.c_uint8 * total_buf_size)()
        iso_buf_addr = ctypes.addressof(iso_buf)

        h_isoch = wintypes.HANDLE()
        if not api.winusb.WinUsb_RegisterIsochBuffer(
            h_vs, ISO_ENDPOINT_IN, iso_buf, total_buf_size, ctypes.byref(h_isoch)
        ):
            err = api.kernel32.GetLastError()
            print(f"[PS4-STREAM] WinUsb_RegisterIsochBuffer failed (err={err})")
            return

        events = [api.kernel32.CreateEventW(None, True, False, None) for _ in range(num_urb)]
        ovs = [OVERLAPPED() for _ in range(num_urb)]
        descs = [(USBD_ISO_PACKET_DESCRIPTOR * num_pkts)() for _ in range(num_urb)]

        frame_bytes = geom.frame_bytes
        max_accum = frame_bytes * 2
        accum_buf = (ctypes.c_uint8 * max_accum)()
        accum_addr = ctypes.addressof(accum_buf)
        accum_np = np.ctypeslib.as_array(accum_buf)

        write_pos = 0
        last_fid = -1
        frame_pts = 0
        frame_pts_valid = False
        consecutive_timeouts = 0

        try:
            # Submit initial isochronous ring
            for i in range(num_urb):
                ovs[i].hEvent = events[i]
                res = api.winusb.WinUsb_ReadIsochPipeAsap(
                    h_isoch,
                    i * urb_len,
                    urb_len,
                    False if i == 0 else True,
                    num_pkts,
                    descs[i],
                    ctypes.byref(ovs[i]),
                )
                if not res and api.kernel32.GetLastError() != ERROR_IO_PENDING:
                    api.winusb.WinUsb_ReadIsochPipeAsap(
                        h_isoch,
                        i * urb_len,
                        urb_len,
                        False,
                        num_pkts,
                        descs[i],
                        ctypes.byref(ovs[i]),
                    )

            urb_idx = 0
            while self.running and self.usb_dev.is_open:
                wait_res = api.kernel32.WaitForSingleObject(events[urb_idx], 500)
                if wait_res != WAIT_OBJECT_0:
                    consecutive_timeouts += 1
                    if consecutive_timeouts >= 4:
                        print("[PS4-STREAM] Isochronous transfer timeout (device unplugged or stalled).")
                        break
                    continue

                consecutive_timeouts = 0
                got_bytes = wintypes.ULONG(0)
                ok_ov = api.winusb.WinUsb_GetOverlappedResult(
                    h_vs, ctypes.byref(ovs[urb_idx]), ctypes.byref(got_bytes), False
                )
                if not ok_ov:
                    err = api.kernel32.GetLastError()
                    # ERROR_DEVICE_NOT_CONNECTED (1167) or ERROR_GEN_FAILURE (31)
                    if err in (31, 1167, 22):
                        break

                base_off = urb_idx * urb_len
                urb_descs = descs[urb_idx]

                for p in range(num_pkts):
                    length = urb_descs[p].Length
                    if urb_descs[p].Status != 0 or length <= 4:
                        continue

                    off = base_off + urb_descs[p].Offset
                    b0 = iso_buf[off]
                    b1 = iso_buf[off + 1]
                    hdr12 = (b0 == 0x0C) and (length >= 12) and ((b1 & 0x0C) == 0x0C)
                    strip = 12 if hdr12 else 4

                    if hdr12:
                        fid = b1 & 0x01
                        if not frame_pts_valid:
                            frame_pts = (
                                iso_buf[off + 2]
                                | (iso_buf[off + 3] << 8)
                                | (iso_buf[off + 4] << 16)
                                | (iso_buf[off + 5] << 24)
                            )
                            frame_pts_valid = True

                        if last_fid >= 0 and fid != last_fid:
                            if write_pos >= frame_bytes:
                                try:
                                    self._publish_raw_frame(accum_np, geom, frame_pts)
                                except Exception as e:
                                    print(f"[PS4-STREAM] Frame demux error: {e}")
                            write_pos = 0
                            frame_pts_valid = False
                        last_fid = fid

                    plen = length - strip
                    if plen > 0:
                        if write_pos + plen > max_accum:
                            write_pos = 0
                        ctypes.memmove(accum_addr + write_pos, iso_buf_addr + off + strip, plen)
                        write_pos += plen

                # Re-submit this URB to keep the ring full
                api.kernel32.ResetEvent(events[urb_idx])
                res = api.winusb.WinUsb_ReadIsochPipeAsap(
                    h_isoch,
                    base_off,
                    urb_len,
                    True,
                    num_pkts,
                    urb_descs,
                    ctypes.byref(ovs[urb_idx]),
                )
                if not res and api.kernel32.GetLastError() != ERROR_IO_PENDING:
                    res2 = api.winusb.WinUsb_ReadIsochPipeAsap(
                        h_isoch,
                        base_off,
                        urb_len,
                        False,
                        num_pkts,
                        urb_descs,
                        ctypes.byref(ovs[urb_idx]),
                    )
                    if not res2 and api.kernel32.GetLastError() != ERROR_IO_PENDING:
                        break

                urb_idx = (urb_idx + 1) % num_urb

        finally:
            if self.usb_dev.h_file:
                try:
                    api.kernel32.CancelIoEx(self.usb_dev.h_file, None)
                except Exception:
                    pass
            try:
                api.winusb.WinUsb_UnregisterIsochBuffer(h_isoch)
            except Exception:
                pass
            for ev in events:
                if ev:
                    try:
                        api.kernel32.CloseHandle(ev)
                    except Exception:
                        pass
