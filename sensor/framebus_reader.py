"""
Direct Shared Memory Frame Reader for PSCam4Win (FrameBus IPC).
Bypasses Windows Camera Frame Server media type caching and DirectShow
format negotiation mismatches by reading uncompressed YUY2 frames directly
from Global\\PSCam4Win{slot}.FrameBus with full seqlock parity validation.
"""
from __future__ import annotations

import os
import struct
import time
import cv2


class FrameBusReader:
    """
    Direct Shared Memory Frame Reader for PSCam4Win (FrameBus IPC).
    Bypasses Windows Camera Frame Server media type caching and DirectShow
    format negotiation mismatches by reading pristine uncompressed YUY2 frames
    directly from Global\\PSCam4Win{slot}.FrameBus.
    """

    def __init__(self):
        self.h_map = None
        self.view_ptr = None
        self.mapped_size = 0
        self.slot = -1
        self.last_frame_id = -1
        self.last_frame_time = 0.0
        self._k32 = None
        self._mbi_cls = None
        self._connect()

    @property
    def is_connected(self) -> bool:
        return self.view_ptr is not None

    def _get_k32(self):
        if self._k32 is None and os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class _MEMORY_BASIC_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ("BaseAddress", ctypes.c_void_p),
                    ("AllocationBase", ctypes.c_void_p),
                    ("AllocationProtect", wintypes.DWORD),
                    ("PartitionId", wintypes.WORD),
                    ("RegionSize", ctypes.c_size_t),
                    ("State", wintypes.DWORD),
                    ("Protect", wintypes.DWORD),
                    ("Type", wintypes.DWORD),
                ]

            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.OpenFileMappingW.restype = wintypes.HANDLE
            k32.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
            k32.MapViewOfFile.restype = ctypes.c_void_p
            k32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
            k32.VirtualQuery.restype = ctypes.c_size_t
            k32.VirtualQuery.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
            k32.UnmapViewOfFile.restype = wintypes.BOOL
            k32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
            k32.CloseHandle.restype = wintypes.BOOL
            k32.CloseHandle.argtypes = [wintypes.HANDLE]
            self._mbi_cls = _MEMORY_BASIC_INFORMATION
            self._k32 = k32
        return self._k32

    def _connect(self):
        if os.name != "nt":
            return
        try:
            import ctypes

            FILE_MAP_READ = 0x0004
            k32 = self._get_k32()
            if k32 is None:
                return

            # PS4 cameras are assigned top-down: slot 7 first (or 6 for split), legacy slots 0..5
            for s in [7, 6, 0, 1, 2, 3, 4, 5]:
                name = f"Global\\PSCam4Win{s}.FrameBus"
                h = k32.OpenFileMappingW(FILE_MAP_READ, False, name)
                if h:
                    # Map entire section (dwNumberOfBytesToMap = 0) so we never exceed section size
                    ptr = k32.MapViewOfFile(h, FILE_MAP_READ, 0, 0, 0)
                    if ptr:
                        mbi = self._mbi_cls()
                        mapped_sz = 0
                        if k32.VirtualQuery(ctypes.c_void_p(ptr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
                            mapped_sz = int(mbi.RegionSize)
                        if mapped_sz >= 4096:
                            raw = ctypes.string_at(ptr, 64)
                            magic, ver, fmt, w, h_dim = struct.unpack("<IIIII", raw[:20])
                            if magic == 0x50533345 and 1 <= w <= 4096 and 1 <= h_dim <= 2160:
                                self.h_map = h
                                self.view_ptr = ptr
                                self.mapped_size = mapped_sz
                                self.slot = s
                                return
                        k32.UnmapViewOfFile(ptr)
                    k32.CloseHandle(h)
        except Exception:
            pass

    def read_frame(self, only_new: bool = False):
        """
        Reads and decodes a YUY2 frame from the PSCam4Win FrameBus shared memory with
        full seqlock validation (pre/post seq parity) and mapped-section bounds checks.
        If only_new=True, skips YUY2->BGR conversion when frame_id has not advanced.
        """
        if not self.view_ptr:
            self._connect()
            if not self.view_ptr:
                return None
        try:
            import ctypes
            import numpy as np

            if self.mapped_size < 4096:
                return None

            raw_hdr = ctypes.string_at(self.view_ptr, 64)
            magic, ver, fmt, w, h_dim, fpsNum, fpsDen, jpegLen, regionBytes, seq, frame_id, qpc = struct.unpack(
                "<IIIIIIIIIxxxxqqq", raw_hdr
            )

            # Seqlock pre-check + strict bounds validation before reading pixel buffer
            if magic == 0x50533345 and (seq % 2 == 0) and 1 <= w <= 4096 and 1 <= h_dim <= 2160:
                if only_new and frame_id == self.last_frame_id and self.last_frame_id != -1:
                    return None
                nbytes = w * h_dim * 2
                max_valid = self.mapped_size
                if regionBytes > 0:
                    max_valid = min(max_valid, int(regionBytes))
                if 4096 + nbytes > max_valid:
                    return None

                raw_pixels = ctypes.string_at(self.view_ptr + 4096, nbytes)
                # Complete seqlock check: verify sequence number did not change during pixel copy
                seq_after = struct.unpack("<q", ctypes.string_at(self.view_ptr + 40, 8))[0]
                if seq_after != seq or (seq_after % 2 != 0):
                    return None

                yuy2 = np.frombuffer(raw_pixels, dtype=np.uint8).reshape((h_dim, w, 2))
                bgr = cv2.cvtColor(yuy2, cv2.COLOR_YUV2BGR_YUY2)
                self.last_frame_id = frame_id
                self.last_frame_time = time.perf_counter()
                return bgr
        except Exception as e:
            try:
                from sensor.session_logger import get_session_logger

                get_session_logger().log_throttled(
                    "framebus_decode_err", "WARN", "CAMERA", f"FrameBus YUY2 decode error: {e}"
                )
            except Exception:
                pass
        return None

    def close(self):
        if self.h_map:
            try:
                k32 = self._get_k32()
                if k32 is not None:
                    if self.view_ptr:
                        k32.UnmapViewOfFile(self.view_ptr)
                        self.view_ptr = None
                    k32.CloseHandle(self.h_map)
            except Exception:
                pass
            self.h_map = None
            self.mapped_size = 0
            self.slot = -1
