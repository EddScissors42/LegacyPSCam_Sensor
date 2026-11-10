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
from sensor.virtual_phone import get_virtual_phone

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
    if mode == "ds4":
        return run_ds4_tracking_session(config, on_close_callback=on_close_callback, stop_event=stop_event)

    cam_idx = config.get("camera_index", 0)
    if cam_idx < 0:
        cams = CameraManager.enumerate_cameras()
        ps_cams = [c for c in cams if c.is_pscam]
        if mode == "pscam" and ps_cams:
            cam_idx = ps_cams[0].index
        elif cams:
            cam_idx = cams[0].index
        else:
            cam_idx = 0
    preset_str = config.get("pscam_preset" if mode == "pscam" else "webcam_preset", "1280x800 @ 60 FPS" if mode == "pscam" else "640x480 @ 30 FPS")
    w, h, target_fps = parse_preset(preset_str)
    mirror = config.get("mirror_horizontal", True)
    smoothing_alpha = config.get("smoothing_alpha", 0.55)
    det_conf = config.get("detection_confidence", 0.5)
    target_height = config.get("target_height_m", 1.75)
    show_hud = config.get("show_hud", True)
    camera_orientation = int(config.get("camera_orientation", 0))

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
            is_pscam=(mode == "pscam"),
            orientation=camera_orientation
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

    # 5. Configure Virtual Phone Controller (if enabled in config or active via GUI)
    vphone = get_virtual_phone()
    vphone.configure(
        host=str(config.get("virtual_phone_host", "127.0.0.1")),
        port=int(config.get("virtual_phone_port", 8080)),
        hand=str(config.get("virtual_phone_hand", "right")),
        sensitivity=float(config.get("virtual_phone_sensitivity", 1.2)),
        phone_name=str(config.get("virtual_phone_name", "Legacy PSCam Phone")),
    )
    if config.get("virtual_phone_enabled", False) and not vphone.enabled:
        vphone.set_enabled(True)

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

            ret, frame, cam_fps = camera.read(only_new=True)
            if not ret or frame is None:
                # Pump OpenCV event queue and yield briefly until the next hardware frame arrives
                key = cv2.waitKey(1) & 0xFF
                if key in (27, ord('q'), ord('Q')):
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
                elif key in (ord('o'), ord('O')):
                    camera_orientation = (camera_orientation + 90) % 360
                    camera.set_orientation(camera_orientation)
                    print(f"[INFO] Camera orientation toggled to: {camera_orientation}°")
                if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                    break
                time.sleep(0.0015)
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
            # When Virtual Phone is active, mute the Kinect pose channel so Kinect10.dll does NOT
            # spawn an unwanted duplicate ghost player (Player 1) alongside the phone.
            if is_tracked and kinect_joints:
                if vphone.enabled:
                    bridge.pose.write_empty()
                    bridge.pose_v2.write_empty()
                    bridge.image.write_image_and_mask(kinect_frame, kinect_mask, tracked=True)
                else:
                    bridge.write(kinect_joints, kinect_frame, kinect_mask, tracked=True)
            else:
                bridge.write_empty()

            # Feed 3D Hand Coordinates to Virtual Phone Controller (Accelerometer emulation)
            vphone.update_from_joints(kinect_joints, is_tracked)

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
            elif key in (13, 32):  # Enter or Space: Send VALID / OK to game via Virtual Phone
                if vphone.enabled:
                    vphone.send_input("VALID")

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


def run_ds4_tracking_session(config, on_close_callback=None, stop_event=None):
    """
    Dedicated motion tracking loop for the Sony DualShock 4 controller over Bluetooth.
    Streams 3D physical accelerometer samples directly into Just Dance via Virtual Phone,
    provides visual feedback and handles button shortcuts.
    """
    import numpy as np
    from sensor.ds4_controller import get_ds4_controller
    from sensor.virtual_phone import get_virtual_phone

    ds4 = get_ds4_controller()
    if not ds4.is_connected:
        if not ds4.connect():
            print("[ERROR] Failed to connect to DualShock 4 via Bluetooth.")
            if on_close_callback:
                on_close_callback()
            return False

    hand = str(config.get("ds4_hand", "right")).lower()
    sens = float(config.get("ds4_sensitivity", 1.0))
    ds4.hand = hand
    ds4.sensitivity = sens

    vphone = get_virtual_phone()
    vphone.configure(
        host=str(config.get("virtual_phone_host", "127.0.0.1")),
        port=int(config.get("virtual_phone_port", 8080)),
        hand=hand,
        sensitivity=sens,
        phone_name=str(config.get("virtual_phone_name", "Legacy PSCam DS4")),
    )
    if not vphone.enabled:
        vphone.set_enabled(True)

    set_high_resolution_timer(True)
    bridge = KinectBridge()

    # Optional webcam grabber for silhouette if camera is present
    cam = None
    try:
        cams = CameraManager.enumerate_cameras()
        webcams = [c for c in cams if not c.is_pscam]
        if webcams:
            cam = cv2.VideoCapture(webcams[0].index, cv2.CAP_DSHOW)
            cam.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            cam.set(cv2.CAP_PROP_FPS, 30)
    except Exception:
        cam = None

    window_name = "Legacy PSCam Sensor — DualShock 4"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL | cv2.WINDOW_GUI_EXPANDED)
    cv2.resizeWindow(window_name, 720, 480)

    print(f"\n==========================================")
    print(f"  STARTING DUALSHOCK 4 TRACKING SESSION")
    print(f"  Hand: {hand.upper()} | Sensitivity: {sens:.2f}x")
    print(f"  HID Polling: {ds4.state.sample_rate_hz:.0f} Hz | Battery: {ds4.state.battery_pct}%")
    print(f"==========================================\n")

    # Dark background canvas for rendering
    canvas_w, canvas_h = 640, 480
    dark_bg = np.zeros((canvas_h, canvas_w, 3), dtype=np.uint8)
    for y in range(canvas_h):
        r_val = int(12 + (y / canvas_h) * 10)
        g_val = int(18 + (y / canvas_h) * 12)
        b_val = int(28 + (y / canvas_h) * 20)
        dark_bg[y, :] = (b_val, g_val, r_val)

    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                break

            st = ds4.state
            ax, ay, az = st.accel_g
            tot_g = math.sqrt(ax * ax + ay * ay + az * az)

            # Grab camera frame if available, else copy gradient canvas
            if cam is not None and cam.isOpened():
                ret_cam, cam_frame = cam.read()
                if ret_cam and cam_frame is not None:
                    cam_frame = cv2.flip(cam_frame, 1)
                    if cam_frame.shape[1] != canvas_w or cam_frame.shape[0] != canvas_h:
                        cam_frame = cv2.resize(cam_frame, (canvas_w, canvas_h))
                    frame = cv2.addWeighted(cam_frame, 0.40, dark_bg, 0.60, 0)
                else:
                    frame = dark_bg.copy()
            else:
                frame = dark_bg.copy()

            # Render DualShock 4 HUD Header (PlayStation Blue banner)
            cv2.rectangle(frame, (0, 0), (canvas_w, 54), (156, 67, 0), -1)
            cv2.putText(
                frame,
                "DUALSHOCK 4 MOTION SENSOR (BLUETOOTH)",
                (18, 34),
                cv2.FONT_HERSHEY_DUPLEX,
                0.64,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )

            # Connection & Battery badge
            batt_str = f"BATTERY: {st.battery_pct}%" + (" [CHARGING]" if st.is_charging else "")
            cv2.putText(
                frame,
                batt_str,
                (canvas_w - 210, 34),
                cv2.FONT_HERSHEY_DUPLEX,
                0.44,
                (200, 240, 255),
                1,
                cv2.LINE_AA,
            )

            # Game connection status
            v_status = vphone.status_text
            cv2.putText(
                frame,
                f"Just Dance PC: {v_status}",
                (20, 85),
                cv2.FONT_HERSHEY_DUPLEX,
                0.50,
                (0, 230, 255) if vphone.connected else (180, 180, 180),
                1,
                cv2.LINE_AA,
            )

            # Hand & Sensitivity info
            cv2.putText(
                frame,
                f"Active Hand: {hand.upper()} | Sens: {sens:.2f}x | HID: {st.sample_rate_hz:.0f} Hz",
                (20, 115),
                cv2.FONT_HERSHEY_DUPLEX,
                0.48,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )

            # 3D G-Force Gauge Bars (X, Y, Z)
            gauge_y_start = 160
            bar_w_max = 180
            axes_data = [
                ("ACCEL X (Lateral)", ax, (0, 215, 255)),    # Gold/Yellow
                ("ACCEL Y (Vertical)", ay, (255, 128, 0)),   # Cyan
                ("ACCEL Z (Forward)", az, (100, 255, 100)),  # Neon Green
            ]

            for idx, (label, val, bar_col) in enumerate(axes_data):
                y_pos = gauge_y_start + idx * 45
                cv2.putText(
                    frame,
                    f"{label}: {val:+.2f} G",
                    (20, y_pos + 12),
                    cv2.FONT_HERSHEY_DUPLEX,
                    0.46,
                    (220, 220, 220),
                    1,
                    cv2.LINE_AA,
                )
                # Background track
                bx = 260
                cv2.rectangle(frame, (bx - bar_w_max, y_pos), (bx + bar_w_max, y_pos + 14), (45, 45, 45), -1)
                cv2.line(frame, (bx, y_pos - 2), (bx, y_pos + 16), (150, 150, 150), 1)

                # Filled bar clamped to [-4G, +4G]
                bar_len = int(max(-bar_w_max, min(bar_w_max, (val / 4.0) * bar_w_max)))
                if bar_len > 0:
                    cv2.rectangle(frame, (bx, y_pos), (bx + bar_len, y_pos + 14), bar_col, -1)
                elif bar_len < 0:
                    cv2.rectangle(frame, (bx + bar_len, y_pos), (bx, y_pos + 14), bar_col, -1)

            # Total G Magnitude
            cv2.putText(
                frame,
                f"TOTAL G-FORCE: {tot_g:.2f} G",
                (20, 310),
                cv2.FONT_HERSHEY_DUPLEX,
                0.60,
                (0, 255, 200) if tot_g >= 2.5 else (200, 200, 200),
                1,
                cv2.LINE_AA,
            )

            # Interactive Button Indicators
            btn_y = 365
            btns = st.buttons
            cv2.putText(
                frame,
                "PHYSICAL BUTTONS:",
                (20, btn_y),
                cv2.FONT_HERSHEY_DUPLEX,
                0.46,
                (160, 160, 160),
                1,
                cv2.LINE_AA,
            )

            btn_badges = [
                ("✕ VALID", btns.get("cross", False), (0, 230, 100)),
                ("○ BACK", btns.get("circle", False), (60, 60, 240)),
                ("△ FTUE", btns.get("triangle", False), (0, 180, 255)),
                ("□", btns.get("square", False), (200, 100, 255)),
                ("OPTIONS", btns.get("options", False), (240, 240, 60)),
            ]

            badge_x = 180
            for label, is_act, col in btn_badges:
                txt_w = len(label) * 9 + 16
                b_bg = col if is_act else (50, 50, 50)
                b_txt_col = (0, 0, 0) if is_act else (180, 180, 180)
                cv2.rectangle(frame, (badge_x, btn_y - 15), (badge_x + txt_w, btn_y + 8), b_bg, -1)
                cv2.rectangle(frame, (badge_x, btn_y - 15), (badge_x + txt_w, btn_y + 8), (100, 100, 100), 1)
                cv2.putText(
                    frame,
                    label,
                    (badge_x + 8, btn_y),
                    cv2.FONT_HERSHEY_DUPLEX,
                    0.42,
                    b_txt_col,
                    1,
                    cv2.LINE_AA,
                )
                badge_x += txt_w + 10

            # Footer navigation hints
            cv2.rectangle(frame, (0, canvas_h - 38), (canvas_w, canvas_h), (20, 20, 20), -1)
            cv2.putText(
                frame,
                "[✕ / Enter / Space] Confirm   •   [○ / Esc] Back   •   [R] Test Rumble   •   [Q] Exit",
                (20, canvas_h - 14),
                cv2.FONT_HERSHEY_DUPLEX,
                0.40,
                (140, 140, 140),
                1,
                cv2.LINE_AA,
            )

            # Update shared memory for Just Dance (mutes Kinect pose channel so player 1 phone is exclusive)
            bridge.pose.write_empty()
            bridge.pose_v2.write_empty()
            bridge.image.write_image_and_mask(frame, np.zeros((240, 320), dtype=np.uint8), tracked=True)

            cv2.imshow(window_name, frame)

            key = cv2.waitKey(16) & 0xFF
            if key in (27, ord('q'), ord('Q')):
                print("[INFO] Exit requested by user.")
                break
            elif key in (ord('r'), ord('R')):
                ds4.trigger_rumble(small=160, large=100, duration_sec=0.25)
            elif key in (13, 32):  # Enter or Space
                vphone.send_input("VALID")
                ds4.trigger_rumble(small=120, large=0, duration_sec=0.08)

            if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                break

    except Exception as e:
        print(f"[ERROR] Exception in DualShock 4 tracking loop: {e}")
    finally:
        set_high_resolution_timer(False)
        bridge.write_empty()
        bridge.close()
        if cam is not None:
            cam.release()
        cv2.destroyAllWindows()
        print("[INFO] DualShock 4 tracking session ended.")
        if on_close_callback:
            on_close_callback()

    return True
