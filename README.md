# Legacy PSCam Sensor

This project is inspired by **[Legacy Sensor by itsVexor]**.

This application is written in Python with zero bloatware to deliver low-latency 60 FPS body and controller motion tracking for **Just Dance PC**.

### Available Devices & Tracking Modes

- **PlayStation 4 Camera (PS4 Camera / OV580):** Native user-space WinUSB driver (`sensor/ps4_backend/`) with automatic firmware upload, 60 FPS dual-eye streaming, built-in Stereo Vision depth (`PyrLK`), plus PSCam4Win fallback.
- **Standard Webcam (USB / Integrated):** DirectShow low-latency capture with asynchronous frame polling (`LatestFrameCamera`).
- **Smartphone Camera (Wi-Fi WebApp):** Use any Android or iOS browser as a 30/60 FPS wireless camera via QR Code pairing over self-signed TLS/WSS (no APK/IPA required).
- **DualShock 4 (USB / Bluetooth HID → Native PS Move ZCM2):** Native Windows HID driver with 500+ Hz 6-axis IMU readout, battery monitoring, vertical thumbs-up grip alignment, 1:1 PS Move button mapping, and live sphere RGB Light Bar & Gold Move rumble feedback.
- **2-Player [Experimental] (2P Duo) Tracking:** Full 2-player body tracking with anti-swap identity memory and `JDP2` / `JMI2` shared memory channels.

### Zero-File-Replacement In-Memory Emulation (Kinect & PlayStation Move)

- **In-Memory Kinect Emulator:** Automatically hooks 32-bit Just Dance Legacy (`tools/Legacy10.dll`) and 64-bit Legacy Lab / Legacy Lab Offline (`tools/Legacy10_x64.dll`) in RAM without modifying or replacing any DLL in the game directory.
- **In-Memory PlayStation Move (ZCM2) Emulator:** Hooks the game's Windows HID/SetupAPI calls (`tools/LegacyMove.dll` / `tools/LegacyMove_x64.dll`) to expose a native PlayStation Move controller (`VID 0x054C / PID 0x0C5E`) fed by the DualShock 4's 6-axis IMU via shared memory (`Local\LegacyPSMoveState`), syncing the game's sphere RGB color and rumble directly back to the DS4 Light Bar and motors.

### Compatibility

- **Just Dance Legacy 2018 Offline (32-bit)**
- **Just Dance Legacy Lab & Legacy Lab Offline (64-bit)**

### How to Play

1. Open **Legacy PSCam**.
2. Select your capture device (PlayStation 4 Camera, Webcam, Smartphone Camera, or DualShock 4).
3. Click **Start Tracking**.
4. Open a compatible game.
5. In-game, select **Kinect** (for camera tracking) or **Motion Controller** (if using a DualShock 4).

### Security, Code Signing Policy & False Positives

- **100% Open Source & Reproducible CI Builds:** Official Windows releases (`LegacyPSCam.exe` and `LegacyPSCam-Portable-Windows.zip`) are built directly from this public repository on GitHub-hosted Actions runners with verifiable `SHA256SUMS.txt` checksums.
- **Privacy:** This program will **not** transfer any information to other networked systems unless specifically requested by the user (e.g., on-demand AI model download from Google MediaPipe or local LAN Wi-Fi pairing for Smartphone Camera). Zero telemetry, ads, or analytics are collected.
- **Antivirus False Positives:** Standalone Python/PyInstaller `--onefile` executables (`LegacyPSCam.exe`) may occasionally trigger generic heuristic flags from a few antivirus engines due to self-extraction into `%TEMP%` and in-memory Kinect/PS Move emulation. If preferred, use the **`LegacyPSCam-Portable-Windows.zip`** (`--onedir`) build or run directly from source (`python main.py`).

### License

This project is licensed under the **MIT License** — see [`LICENSE`](LICENSE) for details.

For detailed setup, architecture, API contracts, and developer docs, see [`docs/`](docs/README.md).
