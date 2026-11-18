# Third-Party Notices and Licensing Attribution

This document records third-party software references, protocol specifications, libraries, and licensing terms applicable to **Legacy PSCam Sensor** (`LegacyPSCam_Sensor`).

---

## 1. Technical Protocol References (PlayStation 4 Camera / OmniVision OV580)

The Native WinUSB PlayStation 4 Camera backend (`sensor/ps4_backend/`) was developed using the hardware protocol documentation, USB control sequences, ISP geometry definitions, and firmware verification standards established by the following open-source projects:

### 1.1. PSCam4Windows (PSCam4Win)
- **Repository:** https://github.com/BumbleTree/PSCam4Windows
- **License:** GNU General Public License v2.0 (GPL-2.0)
- **Scope of Reference:**
  - OV580 bootloader 512-byte chunked firmware upload protocol (`bmRequestType=0x40`, `bRequest=0x00`, `wIndex=0x14+`, reboot command `0x5B` at `wValue=0x2200, wIndex=0x8018`).
  - Final OV580 firmware SHA-1 pinning (`8b8a6621d358f6782c2e3b31aac2cdfb25102c00`, 68,032 bytes, PS4 system 6.00–7.02).
  - Hardware-verified OV580 ISP UVC YUY2 geometries (`1280x800` @ 60/30/15 FPS, `640x400` @ 120/60/30 FPS, `320x192` @ 240/120/60 FPS) and row layout (`[32B header][64B audio][Left Eye][Right Eye][trailer]`).
  - UVC VideoStreaming Probe/Commit and Camera Terminal Auto-Exposure (`CT_AE_MODE_CONTROL = 0x02`) initialization sequence.
  - WinUSB composite interface (`USB\VID_05A9&PID_058B&MI_00`) association architecture.

### 1.2. OrbisEyeCam
- **Repository:** https://github.com/psxdev/OrbisEyeCam
- **Author:** Bigboss (`psxdev`)
- **License:** BSD-style / Open Source Research Attribution
- **Scope of Reference:** OV580 USB bootloader initialization and PS4 Camera reverse-engineering specifications.

### 1.3. PS4-CAMERA-DRIVERS
- **Repository:** https://github.com/Hackinside/PS4-CAMERA-DRIVERS
- **Author:** Hackinside
- **Scope of Reference:** Windows driver INF structure and OV580 initialization reference.

---

## 2. Sony PlayStation 4 Camera Firmware Notice (Proprietary IP Separation)

- **No Firmware Redistribution:** The proprietary OmniVision OV580 firmware binary (`firmware.bin`) is intellectual property of Sony Interactive Entertainment Inc. and/or OmniVision Technologies, Inc. It is **never** embedded in the Legacy PSCam Sensor executable or redistributed in this repository.
- **Local Verification & Caching:** At runtime, `PS4FirmwareManager` locates `firmware.bin` in `%ProgramData%\LegacySensor\Firmware\firmware.bin` (or downloads it directly from the user's configured upstream source during initial setup) and strictly validates its cryptographic hashes before uploading to volatile RAM over USB:
  - **Byte Size:** `68,032` bytes
  - **SHA-1:** `8b8a6621d358f6782c2e3b31aac2cdfb25102c00`
  - **SHA-256:** `09513d1068b9b5e23b09e03bca5640ed4d01830b034b9802395006b14a927b01`
- **Offline Installation:** Users may manually place a verified copy of `firmware.bin` inside `%ProgramData%\LegacySensor\Firmware\` or `<AppFolder>\Firmware\` for completely offline operation.

---

## 3. Runtime Dependencies & System Components

| Component | Version / Source | License | Usage in Legacy PSCam Sensor |
| :--- | :--- | :--- | :--- |
| **Microsoft WinUSB** (`WinUSB.sys` / `winusb.dll`) | Inbox Windows OS Component | Microsoft Windows License | Kernel-to-user-space USB 3.0 control & isochronous transport |
| **Python** | 3.11+ | PSF License v2 | Core application runtime (`ctypes`, `mmap`, `struct`, `threading`) |
| **MediaPipe** | 0.10+ / 1.2+ | Apache License 2.0 | Real-time 33-landmark 3D human pose estimation (`pose_landmarker`) |
| **OpenCV (`opencv-python`)** | 4.x / 5.x | Apache License 2.0 | YUY2-to-BGR color conversion, HUD rendering, and UVC webcam fallback |
| **NumPy** | 1.26+ / 2.x | BSD 3-Clause License | Zero-copy stereo row demultiplexing and vector math |
| **PySide6 (Qt for Python)** | 6.x | LGPLv3 | User interface (`ui/gui_qt.py`) |
| **Pillow (PIL)** | 10.x+ | MIT-CMU License | Image asset handling |
