# Legacy PSCam Sensor - Technical Documentation

Legacy PSCam Sensor is a high-performance, ultra-low latency, and zero-bloatware body motion tracking sensor designed for Just Dance PC (Legacy Offline). It unifies support for standard USB/integrated webcams and the PlayStation 4 Camera (PS4 Camera Slim & V1 via a Native WinUSB User-Space Backend at 1280x800 @ 60 FPS).

---

## Project Goal

The original community emulator accumulated hundreds of megabytes of secondary bloatware (MP3 background music, coin systems, XP levels, gifts, opening videos, and telemetry) that made the application bulky (~632 MB) and slow to start.

Legacy PSCam Sensor was rebuilt from the ground up with a single goal:
> "Launch, pick your camera, and jump straight into dancing."

All non-essential overhead has been removed while perfecting the core components:
1. Anatomical body tracking via Google MediaPipe Pose with the Hand Anchor Filter.
2. 60 FPS support dedicated to the PlayStation 4 Camera and high-speed webcams.
3. Complete Windows shared memory IPC bridge (Pose + Image/Mask) using atomic seqlock consumed by `Kinect10.dll` in Just Dance PC.
4. Player silhouette shadow and neon contour, restoring visual feedback in both the sensor preview window and the in-game Just Dance HUD and dancer selection screen.

---

## Key Features

| Feature | Description | Status |
|---|---|---|
| Skeletal Tracking (20 Joints) | Maps human body pose to the exact 20-joint binary format consumed by Just Dance PC. | Implemented |
| Silhouette & Neon Contour | Real-time anatomical segmentation mask rendering player shadow and feeding Just Dance PC. | Implemented |
| Image & Depth Bridge (JMI1 & JMI2) | `Local\LegacyWebcamKinectImage` buffer (1.3 MB) streaming BGRA frame and player mask to the game. | Implemented |
| PlayStation 4 Camera Native WinUSB Backend | Direct user-space WinUSB driver (`sensor/ps4_backend/`), automatic OV580 firmware upload, 1280x800 @ 60 FPS isochronous capture, and eye selection (Right Eye default / Left Eye). | Implemented |
| Real-time Hotplug Detection | Instant PnP Win32 connection/disconnection polling (< 3ms) without freezing the UI. | Implemented |
| Hand Anchor Filter | Forearm vector extrapolation preventing lost tracking during rapid hand movements and routines. | Implemented |
| Dynamic Anti-Jitter EMA Filter | Velocity-dependent adaptive smoothing eliminating resting jitter while preserving instant response. | Implemented |
| Multi-Tier Auto-Height Calibration | Automatic height and metric normalization for full-body, flexible-torso, and desk setups. | Implemented |
| Modern Device Status Cards | Visual connection badges (supersampled error 'X', warning, and success checks) with diagnostic status and integrated action buttons matching the console-inspired sidebar style. | Implemented |
| 6-Player Coach Selection Support | Expanded lateral tracking range allowing selection of all dancer slots (Slots 1 to 6). | Implemented |
| 2-Player Tracking (Duo Mode) & Anti-Swap Memory | Simultaneous tracking of 2 dancers (`JDP2` 664B + `JMI2` indexed mask 1 & 2, P1 Blue / P2 Light Orange) with long-term appearance & trajectory memory across waltz turns and crossovers (`sensor/player_slot.py`). | Implemented |
| Auto-Framing / FaceFollow PTZ | Dynamic software pan/tilt/zoom (1.22x) keeping player face focused and centered in Just Dance (1P mode). | Implemented |
| Device Settings & Navigation Polish | Aligned controls anatomy, experimental safety notice, and auto-return to Video Settings on device toggle. | Implemented |
| Camera Orientation Control | Real-time 0°, 90°, 180°, and 270° rotation block supporting inverted or sideways camera mounts. | Implemented |
| Responsive Scroll & Anti-Collision | Transparent QScrollArea with minimum card heights preventing widget overlap on compact window sizes. | Implemented |
| Scoring Bridge (Just Dance Controller App mode) | Emulates the Just Dance Smartphone Controller over WebSocket (`/smartphone`) inside Controller Settings with Game Connection Status, Reconnect Game, Auto-Find and Skip Finish shortcuts. | Implemented |
| DualShock 4 & Clones (Level A) | Native Bluetooth/USB HID driver supporting official DS4, licensed pads (Hori, Nacon, Razer, Astro, Scuf) and clone chips (ShanWan, DragonRise) with automatic IMU frozen (0G) diagnostic. | Implemented |
| Emulate Kinect (Zero-File-Replacement) | Emulates Kinect directly in game memory via process detection; keeps original Kinect10.dll on disk intact. | Implemented |
| High-Resolution Windows Timer (1ms) | Python timer synchronization ensuring `Sleep(33)` in `Kinect10.dll` delivers solid 30 FPS. | Implemented |
| Person Lock-In Subsystem | Modular tracking lock combining 3D/2D inertial coasting, HSV torso color identity signature, and ROI attenuation. | Implemented |
| Smart PTZ Auto-Framing | FaceFollow PTZ with 360° spin head fallback and adaptive zoom. | Implemented |
| High-Speed Stereo Luminance | Direct monochrome extraction and zero-cost rectification achieving rock-solid 60 FPS on PS4 Camera. | Implemented |
| Phone Camera via Wi-Fi WebApp | Use any iOS or Android phone as camera via QR code & local HTTPS without app installation. Sidebar card located below DualShock 4 with crisp phone.svg vector rendering. | Implemented |

---

## System Requirements

- Operating System: Windows 10 or Windows 11 (64-bit).
- Python: Version 3.10+ (64-bit).
- Dependencies: `opencv-python`, `mediapipe`, `numpy`, `Pillow`, `PySide6`.
- Hardware: USB webcam (720p/1080p recommended), PlayStation 4 Camera (with AUX-to-USB3 adapter), Android/iOS smartphone (Wi-Fi WebApp), or DualShock 4.
- Drivers (for PS4 Camera): Built-in Native WinUSB Backend (`driver/legacy_pscam_device.inf` + `winusb.dll`).

---

## Directory Overview

```
LegacyPSCam_Sensor/
├── main.py                     # CLI launcher and entry point (--version, --portable, --start, --mode, --camera)
├── version.py                  # Official versioning & build metadata (v0.11.0 Alpha)
├── test_suite.py               # 19 isolated automated test suites + modular unittest runner (19/19 PASSED)
├── tests/                      # Modular unittest suites (test_vphone_protocol, test_tracking_math, test_controllers_and_cli)
├── config.json                 # Local template for user preferences (stored in %APPDATA%\LegacyPSCam_Sensor\)
├── legacy_pscam_sensor.spec    # Reproducible PyInstaller spec (--onefile / --onedir with binary pruning)
├── THIRD_PARTY_NOTICES.md      # Licensing & third-party attribution notices
├── .github/workflows/
│   ├── ci.yml                  # Automated push/PR Windows test workflow
│   └── release.yml             # Tag-validated Windows build, smoke test, SHA256SUMS & GitHub Release workflow
├── driver/
│   └── legacy_pscam_device.inf # WinUSB association package for PS4 Camera
├── sensor/                     # Tracking Engine and AI package
│   ├── ps4_backend/            # Native WinUSB PlayStation 4 Camera Backend
│   ├── camera_manager.py       # Camera discovery, PS4 state machine & compatibility facade
│   ├── camera_win32.py         # Win32 ctypes helpers (CfgMgr32 PnP <3ms, SetupAPI ~3ms, Toolhelp32)
│   ├── framebus_reader.py      # Direct seqlock IPC reader for PSCam4Win FrameBus YUY2 memory
│   ├── camera_capture.py       # Zero-latency threaded LatestFrameCamera (Phone, PS4 WinUSB, FrameBus, DirectShow)
│   ├── stereo_matcher.py       # Stereo Vision Engine (Rectification, Sub-Pixel PyrLK 3D, Depth Mask)
│   ├── pose_tracker.py         # MediaPipe 1P/2P engine & multi-player slot dispatch
│   ├── body_mask.py            # Pure geometric anatomical silhouette mask & 2D Kinect joint projection
│   ├── player_reid.py          # Long-Term Identity Memory (Anti-Swap Re-ID), plausibility & Pose NMS
│   ├── player_slot.py          # Per-player slot pipeline (PlayerSlotState) & indexed mask compositor
│   ├── pose_filters.py         # Kinematic filters (HandAnchor, dt-compensated AdaptiveSmoother, Calibrator, PTZ)
│   ├── person_lock.py          # Modular Person Lock-In (InertialCoastingFilter, DancerIdentityLock)
│   ├── gesture_detector.py     # Raised-arm ENTER gesture detector (1P & 2P)
│   ├── model_manager.py        # Persistent %APPDATA%\models manager (strict SHA-256 + on-demand download)
│   ├── phone_camera.py         # HTTPS/WSS Phone Camera server for iOS & Android smartphones
│   ├── qr_encoder.py           # Pure-Python ISO/IEC 18004 QR Code encoder
│   ├── tls_manager.py          # Per-installation RSA-2048 & X.509v3 TLS certificate manager
│   ├── virtual_phone.py        # UbiArt Smartphone WebSocket controller orchestrator
│   ├── vphone_protocol.py      # HandAccelerometer, RFC 6455 WS client, AdaptiveTuner & song detector
│   ├── ds4_controller.py       # Native Bluetooth/USB HID DualShock 4 driver
│   ├── telemetry_benchmark.py  # Comparative telemetry benchmark (Camera vs DS4)
│   ├── kinect_emulator.py      # In-memory Kinect API emulator & Game Process Monitor
│   ├── tracking_session.py     # Tracking loop orchestrator and hotkeys
│   ├── tracking_overlay.py     # Skeleton, HUD, and silhouette renderer
│   ├── kinect_shared_memory.py # Windows shared memory IPC driver (JDP1, JDP2, JMI1/2, JXC1)
│   ├── session_logger.py       # Rotating session diagnostics & async CSV telemetry
│   └── config_manager.py       # config.json persistence & AppData/Portable path resolution
├── ui/                         # User Interface package
│   ├── controllers/            # Decoupled MVP controllers (App, Camera, Device, Session)
│   ├── gui_qt.py               # Lean PlayStation-themed Qt 6 window shell (signals, layout shell, pixmaps, lifecycle)
│   ├── pages/                  # Declarative Qt 6 page builders package (video, tracking, experimental, ds4)
│   ├── styles.py               # Centralized QSS stylesheet builder
│   ├── mixins/                 # Modular Qt 6 event/readout mixins (device_readout, camera, phone, ds4_vphone, tracking)
│   ├── widgets.py              # Reusable Qt 6 widgets (SlidingStackedWidget, DeviceNavCard, CalibPresetCard, SettingBlock)
│   ├── benchmark_dialog.py     # Telemetry Benchmark & Calibration Comparator dialog & 2D chart
│   ├── theme.py                # Palette, fonts, and calibration presets
│   └── icons.py                # Supersampled icons, SVGs, and status badges
├── assets/                     # Visual assets and media
│   ├── icons/                  # Custom icons (IconePSCAMERA.png, officialdualshock.png, SVGs)
│   ├── fonts/                  # Bundled typography (Kanit, National Park, Inter Tight)
│   └── webapp/                 # Static HTML5/CSS/JS templates for Phone Camera WebApp
├── models/                     # Pre-trained neural network models
│   ├── pose_landmarker_lite.task  # Google MediaPipe Pose Lite model (Competitive preset)
│   └── pose_landmarker_full.task  # Google MediaPipe Pose Full model (Balanced preset)
└── tools/                      # Setup utilities & in-memory proxy DLLs
    ├── Legacy10.dll            # 32-bit in-memory proxy DLL for Just Dance Legacy (Legacy.exe)
    ├── Legacy10_x64.dll        # 64-bit in-memory proxy DLL for Just Dance Legacy Lab (Legacy Lab.exe)
    ├── legacy10_x64_src/       # C++ source & .def for Legacy10_x64.dll (Kinect SDK v1.8 x64 ABI)
    └── get_cameras.ps1         # WinRT camera enumeration fallback script
```

---

## Quick Steps

1. Run the Sensor:
   Launch `LegacyPSCam.exe` (or `LegacySensor.exe`) or execute `python main.py`.
2. Automatic In-Memory Kinect Emulation:
   The built-in in-memory Kinect emulator starts automatically on boot and streams poses/silhouettes via the Shared Memory IPC Bridge (zero game file replacement).
3. Select Device & Start Tracking:
   Choose PlayStation 4 Camera (built-in Stereo Vision active by default), Standard Webcam, Phone Camera (QR Code), or DualShock 4, click **START TRACKING**, and launch Just Dance PC.
