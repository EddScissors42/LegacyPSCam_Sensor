"""
Tracking Session Runner for Legacy PSCam Sensor.
Coordinates camera stream, MediaPipe pose processing, shared memory output,
and OpenCV HUD preview window.
"""
import time
import cv2
import ctypes
from sensor.camera_manager import LatestFrameCamera, CameraManager
from sensor.kinect_shared_memory import KinectBridge
from sensor.pose_tracker import PoseTracker
from sensor.tracking_overlay import TrackingOverlay
from sensor.config_manager import parse_preset

def set_high_resolution_timer(enable=True):
    """
    Enables/disables Windows 1ms high-resolution timer via winmm and ntdll
    to guarantee smooth 60 FPS pacing for camera grab, MediaPipe, and IPC DLL.
    """
    try:
        if enable:
            ctypes.windll.winmm.timeBeginPeriod(1)
            cur = ctypes.c_ulong()
            ctypes.windll.ntdll.NtSetTimerResolution(ctypes.c_ulong(10000), 1, ctypes.byref(cur))
        else:
            ctypes.windll.winmm.timeEndPeriod(1)
    except Exception:
        pass

def run_tracking_session(config, on_close_callback=None, stop_event=None):
    """
    Starts the live tracking loop.
    config: dictionary with tracking parameters.
    on_close_callback: optional function called when tracking terminates.
    stop_event: optional threading.Event to signal loop termination.
    """
    mode = config.get("camera_mode", "pscam")
    cam_idx = config.get("camera_index", 0)
    preset_str = config.get("pscam_preset" if mode == "pscam" else "webcam_preset", "1280x800 @ 60 FPS" if mode == "pscam" else "640x480 @ 30 FPS")
    w, h, target_fps = parse_preset(preset_str)
    mirror = config.get("mirror_horizontal", True)
    smoothing_alpha = config.get("smoothing_alpha", 0.55)
    det_conf = config.get("detection_confidence", 0.5)
    target_height = config.get("target_height_m", 1.75)
    show_hud = config.get("show_hud", True)

    print(f"\n==========================================")
    print(f"  STARTING TRACKING SESSION")
    print(f"  Mode: {'PlayStation Camera' if mode == 'pscam' else 'Standard Webcam'}")
    print(f"  Camera: {cam_idx} | Resolution: {w}x{h} @ {target_fps} FPS")
    print(f"  Mirrored: {mirror} | Smoothing: {smoothing_alpha}")
    print(f"==========================================\n")

    # Enable Windows 1ms high-precision timer for 60 FPS IPC streaming
    set_high_resolution_timer(True)

    # Auto-launch PSCam4Win tray if running in PS Camera mode and tray is inactive
    if mode == "pscam" and CameraManager.is_pscam_installed() and not CameraManager.is_pscam_running():
        CameraManager.launch_pscam_tray()

    # 1. Initialize IPC Shared Memory Bridge (Pose, Image & CoachX)
    bridge = KinectBridge()

    # 2. Initialize Camera Grabber (pristine raw frames to tracker)
    try:
        camera = LatestFrameCamera(
            camera_index=cam_idx,
            target_w=w,
            target_h=h,
            target_fps=target_fps,
            mirror=mirror,
            is_pscam=(mode == "pscam")
        )
    except Exception as e:
        print(f"[ERROR] Failed to start camera: {e}")
        bridge.close()
        if on_close_callback:
            on_close_callback()
        return False

    # 3. Initialize Pose Tracker
    try:
        tracker = PoseTracker(
            detection_confidence=det_conf,
            smoothing_alpha=smoothing_alpha,
            target_height_m=target_height,
            cfg=config
        )
    except Exception as e:
        print(f"[ERROR] Failed to start MediaPipe Pose Tracker: {e}")
        camera.release()
        bridge.close()
        if on_close_callback:
            on_close_callback()
        return False

    # 4. Initialize Overlay
    overlay = TrackingOverlay(show_hud=show_hud)

    window_name = "Legacy PSCam Sensor"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL | cv2.WINDOW_GUI_EXPANDED)
    cv2.resizeWindow(window_name, min(w, 1280), min(h, 800))

    track_fps_counter = 0
    track_fps_last_time = time.time()
    measured_track_fps = float(target_fps)

    mode_label = f"{'PS Camera' if mode == 'pscam' else 'Webcam'} ({camera.actual_w}x{camera.actual_h})"

    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                break

            ret, frame, cam_fps = camera.read()
            if not ret or frame is None:
                # Pump OpenCV event queue so window doesn't freeze during frame wait
                key = cv2.waitKey(5) & 0xFF
                if key in (27, ord('q'), ord('Q')):
                    break
                time.sleep(0.005)
                continue

            # Process Pose on pristine RAW frame with MediaPipe (guarantees correct anatomical limbs)
            is_tracked, kinect_joints, px_joints, body_mask = tracker.process_frame(frame)

            # Measure tracking FPS
            track_fps_counter += 1
            now = time.time()
            dt = now - track_fps_last_time
            if dt >= 1.0:
                measured_track_fps = track_fps_counter / dt
                track_fps_counter = 0
                track_fps_last_time = now

            # Prepare frame, mask and skeleton for display and Kinect HUD preview
            fh, fw = frame.shape[:2]
            if mirror:
                display_frame = cv2.flip(frame, 1)
                display_mask = cv2.flip(body_mask, 1) if body_mask is not None else None
                display_px = [(fw - 1 - p[0], p[1], p[2]) for p in px_joints] if px_joints else None
            else:
                display_frame = frame.copy()
                display_mask = body_mask
                display_px = px_joints

            # Apply dynamic Face Follow (PTZ Auto-framing) for dancer selection avatar
            if is_tracked and tracker.last_norm_landmarks:
                tracker.face_ptz.update_from_norm(tracker.last_norm_landmarks, mirrored=mirror)
                kinect_frame, kinect_mask = tracker.face_ptz.apply(display_frame, display_mask)
            else:
                tracker.face_ptz.reset()
                kinect_frame, kinect_mask = display_frame, display_mask

            # Update Shared Memory for Just Dance PC (Pose JDP1, 640x480 Image and 320x240 Player Mask JMI1 & JMI2)
            if is_tracked and kinect_joints:
                bridge.write(kinect_joints, kinect_frame, kinect_mask, tracked=True)
            else:
                bridge.write_empty()

            # Render Player Silhouette Shadow & Contour ("sombrinha")
            if is_tracked and display_mask is not None:
                display_frame = overlay.draw_player_silhouette(display_frame, display_mask)

            # Render Skeleton on top
            if is_tracked and display_px:
                display_frame = overlay.draw_skeleton(display_frame, display_px)

            display_frame = overlay.draw_hud(
                display_frame,
                camera_info_str=mode_label,
                is_tracked=is_tracked,
                cam_fps=cam_fps,
                track_fps=measured_track_fps,
                is_calibrated=tracker.calibrator.is_calibrated,
                is_mirrored=mirror,
                calibration_tier=tracker.calibrator.calibration_tier
            )

            cv2.imshow(window_name, display_frame)

            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord('q'), ord('Q')):  # ESC or Q
                print("[INFO] Exit requested by user.")
                break
            elif key in (ord('c'), ord('C')):
                tracker.recalibrate()
                print("[INFO] Height/skeleton recalibration triggered!")
            elif key in (ord('m'), ord('M')):
                mirror = not mirror
                camera.set_mirror(mirror)
                print(f"[INFO] Mirroring toggled to: {mirror}")
            elif key in (ord('h'), ord('H')):
                overlay.toggle_hud()

            # Check if user clicked window close button (X)
            if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                break

    except Exception as e:
        print(f"[ERROR] Exception in tracking loop: {e}")
    finally:
        set_high_resolution_timer(False)
        bridge.write_empty()
        bridge.close()
        camera.release()
        tracker.close()
        cv2.destroyAllWindows()
        print("[INFO] Tracking session ended.")
        if on_close_callback:
            on_close_callback()

    return True
