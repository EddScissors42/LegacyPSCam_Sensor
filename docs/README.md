# Legacy Sensor Lite - Technical Documentation

Legacy Sensor Lite is a high-performance, ultra-low latency, and zero-bloatware body motion tracking sensor designed for Just Dance PC (Legacy Offline). It unifies support for standard USB/integrated webcams and the PlayStation 4 Camera (PS4 Camera via PSCam4Win driver at 1280x800 @ 60 FPS).

---

## Project Goal

The original community emulator accumulated hundreds of megabytes of secondary bloatware (MP3 background music, coin systems, XP levels, gifts, opening videos, and telemetry) that made the application bulky (~632 MB) and slow to start.

Legacy Sensor Lite was rebuilt from the ground up with a single goal:
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
| PlayStation 4 Camera Support | Presets optimized for PS4 Camera at 1280x800 @ 60 FPS (native YUY2/NV12 DirectShow). | Implemented |
| Real-time Hotplug Detection | Instant PnP Win32 connection/disconnection polling (< 3ms) without freezing the UI. | Implemented |
| Hand Anchor Filter | Forearm vector extrapolation preventing lost tracking during rapid hand movements and routines. | Implemented |
| Dynamic Anti-Jitter EMA Filter | Velocity-dependent adaptive smoothing eliminating resting jitter while preserving instant response. | Implemented |
| Multi-Tier Auto-Height Calibration | Automatic height and metric normalization for full-body, flexible-torso, and desk setups. | Implemented |
| 6-Player Coach Selection Support | Expanded lateral tracking range allowing selection of all dancer slots (Slots 1 to 6). | Implemented |
| Auto-Framing / FaceFollow PTZ | Dynamic software pan/tilt/zoom (1.22x) keeping player face focused and centered in Just Dance. | Implemented |
| High-Resolution Windows Timer (1ms) | Python timer synchronization ensuring `Sleep(33)` in `Kinect10.dll` delivers solid 30 FPS. | Implemented |

---

## System Requirements

- Operating System: Windows 10 or Windows 11 (64-bit).
- Python: Version 3.10, 3.11, or 3.12 (64-bit).
- Dependencies: `opencv-python`, `mediapipe`, `numpy`.
- Hardware: USB webcam (720p/1080p recommended) or PlayStation 4 Camera (with AUX-to-USB3 adapter).
- Drivers (for PS4 Camera): PSCam4Win (WinUSB user-mode driver + DirectShow virtual camera).

---

## Directory Overview

```
LegacyPSCam_Sensor/
├── main.py                     # CLI launcher and entry point
├── test_suite.py               # 9 complete automated test suites
├── config.json                 # Saved user preferences
├── sensor/                     # Tracking Engine and AI package
│   ├── camera_manager.py       # Camera discovery and async capture
│   ├── pose_tracker.py         # MediaPipe engine, Hand Anchor, Calibrator & EMA
│   ├── tracking_session.py     # Tracking loop orchestrator and hotkeys
│   ├── tracking_overlay.py     # Skeleton, HUD, and silhouette renderer
│   ├── kinect_shared_memory.py # Windows shared memory IPC driver (JDP1, JMI1/2, JXC1)
│   └── config_manager.py       # config.json persistence
├── ui/                         # User Interface package
│   └── gui.py                  # Dark PlayStation-themed control panel (Tkinter)
├── assets/                     # Visual assets and media
│   └── IconePSCAMERA.png       # PS4 Camera icon
├── models/                     # Pre-trained neural network models
│   └── pose_landmarker_lite.task # Google MediaPipe Pose model
├── tools/                      # Setup utilities
│   ├── PSCam4Win-Setup.exe     # Official PSCam4Win driver installer
│   └── get_cameras.ps1         # WinRT camera enumeration script
└── Kinect for Legacy DLL/
    └── Kinect10.dll            # 32-bit proxy DLL for Just Dance PC root folder
```

---

## Quick Steps

1. Copy DLL to Just Dance:
   Place `Kinect10.dll` from `Kinect for Legacy DLL/` into the directory where your Just Dance PC executable is installed.
2. Run the Sensor:
   Launch `LegacySensor.exe` or execute `python main.py`.
3. Select Camera:
   Choose PlayStation 4 Camera (if connected) or Standard Webcam.
4. Start Tracking:
   Click START TRACKING, launch Just Dance PC, and select Kinect as your controller.
