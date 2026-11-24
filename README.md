# Legacy PSCam Sensor

This project is inspired by **[Legacy Sensor by itsVexor]**.

This application is written in Python with zero bloatware to deliver low-latency 60 FPS body and controller motion tracking for **Just Dance PC**.

### Available Devices & Tracking Modes

- **PlayStation 4 Camera (PS4 Camera / OV580):** Native user-space WinUSB driver (`sensor/ps4_backend/`) with automatic firmware upload, 60 FPS dual-eye streaming, built-in Stereo Vision depth (`PyrLK`), plus PSCam4Win fallback.
- **Standard Webcam (USB / Integrated):** DirectShow low-latency capture with asynchronous frame polling (`LatestFrameCamera`).
- **Smartphone Camera (Wi-Fi WebApp):** Use any Android or iOS browser as a 30/60 FPS wireless camera via QR Code pairing over self-signed TLS/WSS (no APK/IPA required).
- **DualShock 4 (USB / Bluetooth HID):** Native Windows HID driver with 500+ Hz 6-axis IMU readout, battery monitoring, haptic rumble, and LED feedback.
- **2-Player [Experimental] (2P Duo) Tracking:** Full 2-player body tracking with anti-swap identity memory and `JDP2` / `JMI2` shared memory channels.

### Zero-File-Replacement Kinect Emulation & Virtual Phone

- **In-Memory Kinect Emulator:** Automatically hooks 32-bit Just Dance Legacy in RAM (`tools/Legacy10.dll`) without modifying or replacing any DLL in the game directory.
- **Virtual Phone Controller:** Emulates the official Just Dance Controller App over `/smartphone` WebSocket, converting 3D camera hand motion (or DualShock 4 IMU data) into 3-axis accelerometer scoring packets.

### Compatibility

- **Legacy Offline PC**
- **Just Dance 2022 PC** by Dreyn

For detailed setup, architecture, API contracts, and developer docs, see [`docs/`](docs/README.md).
