"""
OV580 Firmware Manager for PlayStation 4 Camera.
Handles local discovery, offline staging, automatic HTTPS download,
SHA-1 / SHA-256 cryptographic validation, and 512-byte chunked USB control upload.
"""
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import shutil
import sys
import time
from typing import Optional
import urllib.request

from .constants import (
    FIRMWARE_FILENAME,
    FIRMWARE_SIZE,
    FIRMWARE_SHA1,
    FIRMWARE_SHA256,
    FIRMWARE_DOWNLOAD_URLS,
    STARTUP_FILENAME,
    STARTUP_SIZE,
    STARTUP_SHA1,
    STARTUP_SHA256,
    STARTUP_DOWNLOAD_URLS,
    FW_CHUNK_SIZE,
    FW_REQ_TYPE_VENDOR_OUT,
    FW_REQ_UPLOAD,
    FW_BASE_INDEX,
    FW_REBOOT_VALUE,
    FW_REBOOT_INDEX,
    FW_REBOOT_BYTE,
    PID_BOOTLOADER,
    PID_STREAM_FINAL,
    PID_STREAM_LEGACY,
)
from .winusb_bindings import (
    GENERIC_READ,
    GENERIC_WRITE,
    FILE_SHARE_READ,
    FILE_SHARE_WRITE,
    OPEN_EXISTING,
    FILE_FLAG_OVERLAPPED,
    INVALID_HANDLE_VALUE,
    WINUSB_SETUP_PACKET,
    get_winusb_api,
    find_ps4_device_paths,
)


class PS4FirmwareManager:
    """
    Manages the proprietary OV580 firmware blob without bundling Sony IP inside the repository.
    Official cache path: %ProgramData%\\LegacySensor\\Firmware\\firmware.bin
    """

    @staticmethod
    def get_firmware_cache_dir() -> Path:
        prog_data = os.environ.get("ProgramData", r"C:\ProgramData")
        return Path(prog_data) / "LegacySensor" / "Firmware"

    @staticmethod
    def get_primary_firmware_path() -> Path:
        return PS4FirmwareManager.get_firmware_cache_dir() / FIRMWARE_FILENAME

    @staticmethod
    def get_candidate_directories() -> list[Path]:
        """
        Ordered list of directories searched for firmware.bin (supports offline installs).
        """
        dirs: list[Path] = [PS4FirmwareManager.get_firmware_cache_dir()]

        # Portable / local directories next to executable or project root
        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).resolve().parent
            dirs.append(exe_dir / "Firmware")
            dirs.append(exe_dir)
        else:
            proj_root = Path(__file__).resolve().parent.parent.parent
            dirs.append(proj_root / "Firmware")
            dirs.append(proj_root)

        # Fallback: existing PSCam4Win ProgramData cache (migrated automatically if valid)
        prog_data = os.environ.get("ProgramData", r"C:\ProgramData")
        dirs.append(Path(prog_data) / "PSCam4Win")

        return dirs

    @staticmethod
    def compute_sha1(data: bytes) -> str:
        return hashlib.sha1(data).hexdigest().lower()

    @staticmethod
    def compute_sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest().lower()

    @staticmethod
    def validate_firmware_bytes(data: bytes) -> bool:
        """
        Strictly verifies that `data` matches the final OV580 firmware (PS4 sys 6.00-7.02)
        by exact byte size (68,032), SHA-1, and SHA-256.
        """
        if not data or len(data) != FIRMWARE_SIZE:
            return False
        sha1 = PS4FirmwareManager.compute_sha1(data)
        if sha1 != FIRMWARE_SHA1:
            return False
        sha256 = PS4FirmwareManager.compute_sha256(data)
        return sha256 == FIRMWARE_SHA256

    @staticmethod
    def validate_startup_bytes(data: bytes) -> bool:
        if not data or len(data) != STARTUP_SIZE:
            return False
        return (
            PS4FirmwareManager.compute_sha1(data) == STARTUP_SHA1
            and PS4FirmwareManager.compute_sha256(data) == STARTUP_SHA256
        )

    @staticmethod
    def locate_valid_firmware() -> Optional[bytes]:
        """
        Searches candidate local directories for a valid firmware.bin.
        If found in a secondary location, caches a verified copy in
        %ProgramData%\\LegacySensor\\Firmware\\firmware.bin.
        """
        primary_path = PS4FirmwareManager.get_primary_firmware_path()

        for folder in PS4FirmwareManager.get_candidate_directories():
            candidate = folder / FIRMWARE_FILENAME
            if not candidate.is_file():
                continue
            try:
                raw = candidate.read_bytes()
            except Exception:
                continue

            if PS4FirmwareManager.validate_firmware_bytes(raw):
                # Ensure primary cache has a copy if loaded from a fallback path
                if candidate.resolve() != primary_path.resolve():
                    try:
                        primary_path.parent.mkdir(parents=True, exist_ok=True)
                        primary_path.write_bytes(raw)
                    except Exception:
                        pass
                return raw

        return None

    @staticmethod
    def has_valid_firmware() -> bool:
        return PS4FirmwareManager.locate_valid_firmware() is not None

    @staticmethod
    def download_firmware(timeout: float = 15.0) -> Optional[bytes]:
        """
        Downloads firmware.bin from the pinned upstream repositories, verifies SHA-1 and SHA-256
        in memory before touching disk, and persists to %ProgramData%\\LegacySensor\\Firmware.
        """
        for url in FIRMWARE_DOWNLOAD_URLS:
            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "LegacyPSCamSensor-FirmwareManager/2.0"},
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    if resp.status != 200:
                        continue
                    data = resp.read(FIRMWARE_SIZE + 65536)
                if PS4FirmwareManager.validate_firmware_bytes(data):
                    primary_path = PS4FirmwareManager.get_primary_firmware_path()
                    try:
                        primary_path.parent.mkdir(parents=True, exist_ok=True)
                        primary_path.write_bytes(data)
                    except Exception as e:
                        print(f"[PS4-FW] Warning: could not write firmware to cache ({e})")
                    return data
                else:
                    print(f"[PS4-FW] Downloaded blob from {url} failed SHA-1/SHA-256 verification; rejected.")
            except Exception as e:
                print(f"[PS4-FW] Download attempt from {url} failed: {e}")

        return None

    @staticmethod
    def ensure_firmware(allow_download: bool = True) -> Optional[bytes]:
        """
        Returns verified OV580 firmware bytes from local cache or (if allowed) HTTPS download.
        """
        fw = PS4FirmwareManager.locate_valid_firmware()
        if fw is not None:
            return fw
        if allow_download:
            print("[PS4-FW] Local firmware.bin not found; downloading verified OV580 firmware...")
            return PS4FirmwareManager.download_firmware()
        return None

    @staticmethod
    def upload_firmware_to_handle(h_winusb: int, fw_bytes: bytes) -> bool:
        """
        Uploads verified firmware bytes to an open OV580 bootloader (05A9:0580) WinUSB handle
        in 512-byte chunks, followed by the 0x5B reboot control transfer.
        """
        if not h_winusb or not PS4FirmwareManager.validate_firmware_bytes(fw_bytes):
            return False

        api = get_winusb_api()
        if not api.available:
            return False

        index = FW_BASE_INDEX
        value = 0
        total_len = len(fw_bytes)

        for pos in range(0, total_len, FW_CHUNK_SIZE):
            chunk = fw_bytes[pos : pos + FW_CHUNK_SIZE]
            size = len(chunk)
            pkt = WINUSB_SETUP_PACKET(
                FW_REQ_TYPE_VENDOR_OUT,
                FW_REQ_UPLOAD,
                value,
                index,
                size,
            )
            c_buf = (ctypes.c_uint8 * size).from_buffer_copy(chunk)
            transferred = wintypes.ULONG(0)
            ok = api.winusb.WinUsb_ControlTransfer(
                h_winusb,
                pkt,
                c_buf,
                size,
                ctypes.byref(transferred),
                None,
            )
            if not ok or transferred.value != size:
                err = api.kernel32.GetLastError()
                print(f"[PS4-FW] Firmware chunk upload failed at offset {pos} (err={err})")
                return False

            if value + size > 0xFFFF:
                index += 1
            value = (value + size) & 0xFFFF

        # Issue the OV580 reboot command (0x5B to wValue=0x2200, wIndex=0x8018).
        # The device immediately disconnects from USB to re-enumerate as 058B, so
        # a transfer error on this final packet is normal and expected.
        reboot_pkt = WINUSB_SETUP_PACKET(
            FW_REQ_TYPE_VENDOR_OUT,
            FW_REQ_UPLOAD,
            FW_REBOOT_VALUE,
            FW_REBOOT_INDEX,
            1,
        )
        go_buf = (ctypes.c_uint8 * 1)(FW_REBOOT_BYTE)
        transferred = wintypes.ULONG(0)
        api.winusb.WinUsb_ControlTransfer(
            h_winusb,
            reboot_pkt,
            go_buf,
            1,
            ctypes.byref(transferred),
            None,
        )
        return True

    @staticmethod
    def upload_to_bootloader_device(allow_download: bool = True, wait_reenumerate_s: float = 6.0) -> tuple[bool, str]:
        """
        Finds a connected PS4 Camera in bootloader state (05A9:0580), uploads verified firmware,
        and waits up to `wait_reenumerate_s` seconds for it to re-enumerate in streaming mode (058B/058A).
        """
        api = get_winusb_api()
        if not api.available:
            return False, "WinUSB is only supported on Windows."

        # If already in streaming mode, nothing to upload
        streaming_devs = find_ps4_device_paths((PID_STREAM_FINAL, PID_STREAM_LEGACY))
        if streaming_devs:
            return True, "PlayStation 4 Camera is already initialized in streaming mode."

        boot_devs = find_ps4_device_paths((PID_BOOTLOADER,))
        if not boot_devs:
            return False, "PlayStation 4 Camera bootloader (05A9:0580) not found on WinUSB."

        fw_bytes = PS4FirmwareManager.ensure_firmware(allow_download=allow_download)
        if not fw_bytes:
            return (
                False,
                f"Valid OV580 firmware.bin (SHA-1 {FIRMWARE_SHA1[:10]}...) could not be located or downloaded.",
            )

        _, boot_path = boot_devs[0]
        h_file = api.kernel32.CreateFileW(
            boot_path,
            GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None,
            OPEN_EXISTING,
            FILE_FLAG_OVERLAPPED,
            None,
        )
        if not h_file or h_file == INVALID_HANDLE_VALUE:
            err = api.kernel32.GetLastError()
            return False, f"Could not open PS4 Camera bootloader device (Win32 error {err})."

        h_winusb = wintypes.HANDLE()
        if not api.winusb.WinUsb_Initialize(h_file, ctypes.byref(h_winusb)):
            err = api.kernel32.GetLastError()
            api.kernel32.CloseHandle(h_file)
            return False, f"WinUsb_Initialize failed on bootloader device (Win32 error {err})."

        try:
            print("[PS4-FW] Uploading 68 KB firmware to PlayStation 4 Camera (OV580)...")
            uploaded = PS4FirmwareManager.upload_firmware_to_handle(h_winusb, fw_bytes)
        finally:
            api.winusb.WinUsb_Free(h_winusb)
            api.kernel32.CloseHandle(h_file)

        if not uploaded:
            return False, "Failed to transfer firmware chunks over USB."

        if wait_reenumerate_s <= 0:
            return True, "Firmware uploaded; reboot command sent."

        deadline = time.perf_counter() + wait_reenumerate_s
        while time.perf_counter() < deadline:
            time.sleep(0.1)
            streaming_devs = find_ps4_device_paths((PID_STREAM_FINAL, PID_STREAM_LEGACY))
            if streaming_devs:
                print("[PS4-FW] PlayStation 4 Camera re-enumerated in streaming mode (05A9:058B).")
                return True, "PlayStation 4 Camera initialized and ready."

        return False, "Firmware uploaded, but streaming device (05A9:058B) did not re-enumerate within timeout."
