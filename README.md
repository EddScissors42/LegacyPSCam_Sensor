# Legacy Sensor Lite - Motion Tracking Sensor for Just Dance PC

Legacy Sensor Lite is a high-performance, lightweight motion tracking sensor for Just Dance PC (Legacy Offline), unifying support for Standard USB/Integrated Webcams and the PlayStation Camera (PS4 Camera at up to 60 FPS).

---

## Key Features

- Zero Bloatware: Purely focused on dancing. No background audio, no gift animations, no coin/XP systems. Instant startup and minimal CPU/RAM usage.
- Native PlayStation Camera Support:
  - Optimized presets for PS4 Camera (1280x800 @ 60 FPS).
  - Automatic detection and lifecycle management for the PSCam4Win driver.
- Standard and USB Webcam Support:
  - Presets for 640x480 @ 30 FPS, 720p HD, and 1080p Full HD.
- High-Fidelity Tracking with MediaPipe Pose:
  - Full anatomical mapping of all 20 Kinect v1 joints.
  - Hand Anchor Filter: Anatomical forearm vector extrapolation ensures fast hand and arm gestures never lose tracking during fast routines.
  - Dynamic Anti-Jitter Smoothing (EMA): Adaptive velocity-based filter eliminates resting jitter while preserving instantaneous response during fast steps.
  - Automatic Height and Scale Normalization: Calibrates body proportions directly into the coordinate space expected by Just Dance.
  - Full 6-Player Coach Slot Support: Lateral range tracking allows players to select any dancer slot across the room.
  - Auto-Framing / FaceFollow PTZ: Smooth pan/tilt/zoom (1.22x) auto-centers and focuses the player's face for the dancer selection portrait box.
- Direct Shared Memory IPC (Kinect Bridge):
  - Streams directly to Just Dance via Windows shared memory (`Local\LegacyWebcamKinectPose`, `Local\LegacyWebcamKinectImage`, and `Local\LegacyWebcamKinectCoachX`) using lockless seqlock protocol, consumed by `Kinect10.dll`.
  - Windows 1ms high-precision timer ensures a solid 30 FPS sync for in-game scoring and silhouette HUD.
- Sleek HUD & Quick Controls:
  - Vibrant skeleton overlay, player silhouette shadow and neon contour, camera and tracking FPS counters.
  - Hotkeys: [C] Recalibrate, [M] Mirror, [H] Toggle HUD, [ESC / Q] Exit.

---

## Getting Started

### 1. Install DLL into Just Dance
1. In the `Kinect for Legacy DLL` folder, copy `Kinect10.dll`.
2. Paste it into the root directory of your Just Dance PC installation (where the game executable is located), replacing any existing file.
(You can also click the "Open Kinect10.dll Folder" button directly inside the Legacy Sensor Lite launcher).

### 2. Run the Sensor
- Launch `LegacySensor.exe` (or run `python main.py`) to open the control panel and configure your camera.

### 3. In the Configuration Menu
1. Select your capture device:
   - PlayStation 4 Camera: For 60 FPS tracking via PSCam4Win.
   - Standard Webcam: For USB or built-in laptop cameras.
2. Choose your device and resolution preset (e.g. 1280x800 @ 60 FPS or 640x480 @ 30 FPS).
3. Click "START TRACKING".

### 4. In Just Dance PC
1. Start Just Dance PC.
2. In the controller selection screen, select Kinect Sensor.
3. Pick your song, step onto your dancer slot, and enjoy!

---

## Keyboard Shortcuts During Tracking

| Key | Action |
|---|---|
| C | Recalibrates hip center and body height |
| M | Toggles camera horizontal mirroring |
| H | Shows or hides the HUD overlay |
| Q or ESC | Closes the tracking window and returns to launcher |

---

## PlayStation 4 Camera Tips

- For stable 60 FPS, ensure PSCam4Win is installed and active (the launcher displays driver status in real-time).
- The interface automatically selects the PS4 Camera and prevents accidental webcam fallback if disconnected.
- Select 1280x800 @ 60 FPS for maximum scoring precision.
- Position the camera approximately 1.8 to 2.5 meters away to frame your full body.

---

## Project Structure

- `main.py`: Application entry point and CLI dispatcher.
- `test_suite.py`: Complete automated test suite (9/9 suites).
- `config.json`: Local user configuration persistence.
- `sensor/`: Computer vision, camera capture, AI pose tracking, IPC, and session orchestration.
  - `sensor/camera_manager.py`: Camera discovery, PnP hardware monitoring, and PSCam4Win integration.
  - `sensor/pose_tracker.py`: MediaPipe Pose engine, Hand Anchor, adaptive smoother, and multi-tier calibrator.
  - `sensor/kinect_shared_memory.py`: Windows shared memory IPC driver (JDP1, JMI1/2, JXC1).
  - `sensor/tracking_session.py`: Live tracking loop orchestrator and keyboard handlers.
  - `sensor/tracking_overlay.py`: OpenCV HUD, player silhouette shadow, neon contour, and skeleton renderer.
  - `sensor/config_manager.py`: Local settings reader and writer.
- `ui/`: Modern Tkinter/ttk user interface (`ui/gui.py`).
- `assets/`: Visual assets and application icons (`assets/IconePSCAMERA.png`).
- `models/`: Pre-trained Google MediaPipe neural network model (`models/pose_landmarker_lite.task`).
- `tools/`: Utilities and official driver setup (`tools/PSCam4Win-Setup.exe`).
- `Kinect for Legacy DLL/`: 32-bit proxy DLL for Just Dance PC (`Kinect10.dll`).
