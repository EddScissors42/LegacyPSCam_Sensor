"""
Tracking Session Runner for Legacy PSCam Sensor.
Coordinates camera stream, MediaPipe pose processing, shared memory output,
and OpenCV HUD preview window.
"""
import time
import math
import cv2
import ctypes
import threading
import numpy as np
from sensor.camera_manager import LatestFrameCamera, CameraManager
from sensor.kinect_shared_memory import KinectBridge
from sensor.config_manager import parse_preset
from sensor.virtual_phone import get_virtual_phone
from sensor.gesture_detector import (
    ArmRaiseGestureDetector,
    check_arm_raised,
    dispatch_enter_keystroke,
)

_send_enter_keystroke = dispatch_enter_keystroke

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
    ps4_eye = str(config.get("ps4_eye", "right")).strip().lower()
    ps4_backend_mode = str(config.get("ps4_camera_backend", "native")).strip().lower()

    print(f"\n==========================================")
    print(f"  STARTING TRACKING SESSION")
    print(f"  Mode: {'PlayStation Camera' if mode == 'pscam' else 'Standard Webcam'}")
    print(f"  Camera: {cam_idx} | Resolution: {w}x{h} @ {target_fps} FPS")
    if mode == "pscam":
        print(f"  PS4 Backend: {ps4_backend_mode} | Eye: {ps4_eye}")
    print(f"  Mirrored: {mirror} | Smoothing: {smoothing_alpha}")
    print(f"==========================================\n")

    # Enable Windows 1ms high-precision timer for 60 FPS IPC streaming
    set_high_resolution_timer(True)

    # Ensure PS4 Camera is initialized (firmware uploaded if in bootloader state)
    if mode == "pscam":
        if ps4_backend_mode == "pscam4win":
            if CameraManager.is_legacy_pscam4win_installed() and not CameraManager.is_legacy_pscam4win_running():
                CameraManager.launch_pscam_tray()
        else:
            CameraManager.initialize_ps4_camera()

    # 1. Initialize IPC Shared Memory Bridge (Pose, Image & CoachX)
    bridge = KinectBridge()

    # 1.1 Ensure KinectEmulatorDaemon is running if enabled (supports direct CLI --start mode)
    local_kinect_emulator = None
    if bool(config.get("emulate_kinect_enabled", False)):
        from sensor.kinect_emulator import KinectEmulatorDaemon
        local_kinect_emulator = KinectEmulatorDaemon(config)
        local_kinect_emulator.start()

    # 2. Initialize Camera Grabber (pristine raw frames to tracker)
    try:
        camera = LatestFrameCamera(
            camera_index=cam_idx,
            target_w=w,
            target_h=h,
            target_fps=target_fps,
            mirror=mirror,
            is_pscam=(mode == "pscam"),
            orientation=camera_orientation,
            ps4_eye=ps4_eye,
            ps4_backend_mode=ps4_backend_mode,
        )
    except Exception as e:
        print(f"[ERROR] Failed to start camera: {e}")
        bridge.close()
        if on_close_callback:
            on_close_callback()
        return False

    # 3. Initialize Pose Tracker (lazy-imported so GUI startup & DS4 mode never wait on MediaPipe)
    from sensor.pose_tracker import PoseTracker
    from sensor.tracking_overlay import TrackingOverlay

    preset_model_map = {"balanced": "full", "competitive": "lite"}
    pose_model = str(config.get("pose_model", "")).strip().lower()
    if pose_model == "heavy":
        pose_model = "full"
    if pose_model not in ("lite", "full"):
        pose_model = preset_model_map.get(config.get("tracking_preset", "balanced"), "lite")

    if target_fps >= 50 and pose_model == "full":
        print(f"[PERF] Câmera a {target_fps} FPS com modelo '{pose_model}'. Para 60 FPS estáveis na CPU, use o preset 'Competitive' (modelo lite).")

    try:
        tracker = PoseTracker(
            detection_confidence=det_conf,
            smoothing_alpha=smoothing_alpha,
            target_height_m=target_height,
            cfg=config,
            model_variant=pose_model,
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
        sensitivity=float(config.get("virtual_phone_sensitivity", 1.0)),
        phone_name=str(config.get("virtual_phone_name", "Legacy PSCam Phone")),
        auto_record=bool(config.get("benchmark_auto_record", config.get("virtual_phone_auto_record", False))),
        adaptive=bool(config.get("virtual_phone_adaptive", False)),
    )
    should_enable_vphone = (
        config.get("virtual_phone_enabled", False)
        or config.get("benchmark_auto_record", False)
        or config.get("virtual_phone_auto_record", False)
    )
    if should_enable_vphone and not vphone.enabled:
        vphone.set_enabled(True)

    gesture_detector = ArmRaiseGestureDetector(
        enabled=bool(config.get("arm_raise_gesture_enabled", True)),
        hold_seconds=float(config.get("arm_raise_hold_seconds", 2.0)),
        cooldown_seconds=2.5,
    )

    window_name = "Legacy PSCam Sensor"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL | cv2.WINDOW_GUI_EXPANDED)
    cv2.resizeWindow(window_name, min(w, 1280), min(h, 800))

    track_fps_counter = 0
    track_fps_last_time = time.time()
    measured_track_fps = float(target_fps)

    mode_label = f"{'PS Camera' if mode == 'pscam' else 'Webcam'} ({camera.actual_w}x{camera.actual_h})"

    t_start_session = time.time()
    total_frames = 0

    try:
        from sensor.session_logger import get_session_logger
        cfg_summary = f"{w}x{h}@{target_fps}FPS, mode={mode}, backend={ps4_backend_mode if mode == 'pscam' else 'dshow'}"
        get_session_logger().map_active_controller(
            controller_type="camera",
            name="PlayStation 4 Camera" if mode == "pscam" else "Standard Webcam",
            details=cfg_summary,
        )
        get_session_logger().start_telemetry_tracking(
            source="camera",
            song_name=getattr(vphone, "current_map_name", "DanceSession"),
            coach_id=getattr(vphone, "current_coach_id", 0),
            config_summary=cfg_summary,
        )
    except Exception:
        pass

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
                elif key in (13, 32):
                    if vphone.enabled:
                        vphone.send_input("VALID")
                if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                    break
                time.sleep(0.0015)
                continue

            # If stereo vision is active on PS4 Camera, retrieve synchronous Left Eye luminance frame
            # directly from YUY2 buffer (<0.08 ms) to eliminate redundant color conversion.
            frame_left = None
            if getattr(tracker, "stereo_mode", "disabled") != "disabled":
                if hasattr(camera, "read_left_mono"):
                    frame_left = camera.read_left_mono()
                if frame_left is None and hasattr(camera, "read_left_eye"):
                    frame_left = camera.read_left_eye(mono=True)
                if frame_left is None:
                    st_data = camera.read_stereo(only_new=False)
                    if st_data:
                        frame_left = st_data.get("left_bgr")

            # Process Pose on pristine RAW frame with MediaPipe (guarantees correct anatomical limbs)
            is_tracked, kinect_joints, px_joints, body_mask = tracker.process_frame(frame, frame_left=frame_left)

            # Detect arm raised gesture to dispatch virtual ENTER / START command
            gesture_info = gesture_detector.update(px_joints, is_tracked, vphone=vphone)

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
                display_frame = frame
                display_mask = body_mask
                display_px = px_joints

            # Apply dynamic Face Follow (PTZ Auto-framing & Frustum-Aligned Face Square) for dancer selection avatar
            if is_tracked and tracker.last_norm_landmarks:
                tracker.face_ptz.update_from_norm(
                    tracker.last_norm_landmarks,
                    mirrored=mirror,
                    kinect_joints=kinect_joints,
                )
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

            total_frames += 1
            try:
                from sensor.session_logger import get_session_logger
                accel = vphone.accelerometer.latest_accel
                speed = vphone.accelerometer.latest_speed

                def _j_xyz(j):
                    if isinstance(j, (tuple, list)) and len(j) >= 3:
                        return (float(j[0]), float(j[1]), float(j[2]))
                    return (float(getattr(j, "x", 0.0)), float(getattr(j, "y", 0.0)), float(getattr(j, "z", 0.0)))

                def _j_conf(j):
                    if isinstance(j, (tuple, list)) and len(j) >= 4:
                        return float(j[3])
                    return float(getattr(j, "confidence", 1.0))

                is_left_hand = str(getattr(vphone, "hand", "right")).lower() == "left"
                idx_sh, idx_el, idx_wr, idx_hd = (4, 5, 6, 7) if is_left_hand else (8, 9, 10, 11)

                h_pos = _j_xyz(kinect_joints[idx_hd]) if (kinect_joints and len(kinect_joints) > idx_hd) else (0.0, 0.0, 0.0)
                s_r = _j_xyz(kinect_joints[idx_sh]) if (kinect_joints and len(kinect_joints) > idx_sh) else (0.0, 0.0, 0.0)
                e_r = _j_xyz(kinect_joints[idx_el]) if (kinect_joints and len(kinect_joints) > idx_el) else (0.0, 0.0, 0.0)
                w_r = _j_xyz(kinect_joints[idx_wr]) if (kinect_joints and len(kinect_joints) > idx_wr) else (0.0, 0.0, 0.0)
                j_count = sum(1 for j in kinect_joints if _j_conf(j) > 0.3) if kinect_joints else 0
                get_session_logger().record_telemetry_sample(
                    ts_ms=int(time.time() * 1000),
                    source="camera",
                    song_name=getattr(vphone, "current_map_name", None),
                    coach_id=getattr(vphone, "current_coach_id", 0),
                    is_tracked=is_tracked,
                    ax=accel[0],
                    ay=accel[1],
                    az=accel[2],
                    speed_mps=speed,
                    hand_pos=h_pos,
                    shoulder_r=s_r,
                    elbow_r=e_r,
                    wrist_r=w_r,
                    joints_tracked_count=j_count,
                    cam_fps=cam_fps,
                    infer_fps=measured_track_fps,
                    game_feedback=getattr(vphone, "_last_feedback", ""),
                )
            except Exception:
                pass

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

            # Render gesture hold progress / confirmation feedback on preview
            if gesture_info.get("holding"):
                elapsed = min(gesture_info["target"], gesture_info["elapsed"])
                pct = int(gesture_info["progress"] * 100)
                target_s = gesture_info["target"]
                hud_txt = f"HOLD ARM UP: {elapsed:.1f}s / {target_s:.1f}s ({pct}%) -> [ENTER]"
                cv2.putText(display_frame, hud_txt, (max(20, fw // 2 - 180), fh - 44),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3, cv2.LINE_AA)
                cv2.putText(display_frame, hud_txt, (max(20, fw // 2 - 180), fh - 44),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 240, 255), 2, cv2.LINE_AA)
            elif gesture_info.get("feedback_active"):
                hud_txt = ">>> ENTER COMMAND SENT! <<<"
                cv2.putText(display_frame, hud_txt, (max(20, fw // 2 - 150), fh - 44),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 4, cv2.LINE_AA)
                cv2.putText(display_frame, hud_txt, (max(20, fw // 2 - 150), fh - 44),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.65, (50, 255, 50), 2, cv2.LINE_AA)

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
            elif key in (ord('o'), ord('O')):
                camera_orientation = (camera_orientation + 90) % 360
                camera.set_orientation(camera_orientation)
                print(f"[INFO] Camera orientation toggled to: {camera_orientation}°")
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
        try:
            from sensor.session_logger import get_session_logger
            dur = round(time.time() - t_start_session, 2)
            get_session_logger().stop_telemetry_tracking({
                "duration_s": dur,
                "total_frames": total_frames,
                "avg_fps": round(total_frames / max(1.0, dur), 1),
            })
        except Exception:
            pass
        if local_kinect_emulator is not None:
            local_kinect_emulator.stop()
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
    provides visual telemetry (3D accel gauges, battery %, HID sample rate),
    and handles hotkeys ([Q] Quit, [R] Reconnect).
    """
    from sensor.ds4_controller import get_ds4_controller
    from sensor.virtual_phone import get_virtual_phone

    ds4 = get_ds4_controller()
    ds4.permissive_mode = bool(config.get("ds4_permissive_mode", True))
    if not ds4.is_connected:
        ds4.connect(permissive=ds4.permissive_mode)

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
        auto_record=bool(config.get("virtual_phone_auto_record", False)),
        adaptive=bool(config.get("virtual_phone_adaptive", False)),
    )
    if not vphone.enabled:
        vphone.set_enabled(True)

    set_high_resolution_timer(True)
    bridge = KinectBridge()

    window_name = "Legacy PSCam Sensor — DualShock 4"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL | cv2.WINDOW_GUI_EXPANDED)
    cv2.resizeWindow(window_name, 720, 480)

    print(f"\n==========================================")
    print(f"  STARTING DUALSHOCK 4 TRACKING SESSION")
    print(f"  Hand: {hand.upper()} | Sensitivity: {sens:.2f}x")
    print(f"  Connected: {ds4.is_connected} | Polling: {ds4.state.sample_rate_hz:.0f} Hz | Battery: {ds4.state.battery_pct}%")
    print(f"==========================================\n")

    # Dark gradient background canvas for telemetry rendering
    canvas_w, canvas_h = 640, 480
    dark_bg = np.zeros((canvas_h, canvas_w, 3), dtype=np.uint8)
    for y in range(canvas_h):
        r_val = int(12 + (y / canvas_h) * 10)
        g_val = int(18 + (y / canvas_h) * 12)
        b_val = int(28 + (y / canvas_h) * 20)
        dark_bg[y, :] = (b_val, g_val, r_val)

    reconnect_feedback_until = 0.0

    t_start_ds4 = time.time()
    ds4_samples_count = 0

    try:
        from sensor.session_logger import get_session_logger
        conn_str = "USB" if ds4.is_usb else "Bluetooth"
        ds4_summary = f"{ds4.state.controller_name} ({conn_str}), Hand: {hand}, Sens: {sens}x"
        get_session_logger().map_active_controller(
            controller_type="ds4",
            name=ds4.state.controller_name,
            details=ds4_summary,
        )
        get_session_logger().start_telemetry_tracking(
            source="ds4",
            song_name=getattr(vphone, "current_map_name", "DanceSession"),
            coach_id=getattr(vphone, "current_coach_id", 0),
            config_summary=ds4_summary,
        )
    except Exception:
        pass

    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                break

            st = ds4.state
            ax, ay, az = st.accel_g
            tot_g = math.sqrt(ax * ax + ay * ay + az * az)

            ds4_samples_count += 1
            try:
                from sensor.session_logger import get_session_logger
                get_session_logger().record_telemetry_sample(
                    ts_ms=int(time.time() * 1000),
                    source="ds4",
                    song_name=getattr(vphone, "current_map_name", None),
                    coach_id=getattr(vphone, "current_coach_id", 0),
                    is_tracked=ds4.is_connected,
                    ax=ax,
                    ay=ay,
                    az=az,
                    speed_mps=0.0,
                    cam_fps=st.sample_rate_hz,
                    game_feedback=getattr(vphone, "_last_feedback", ""),
                )
            except Exception:
                pass

            frame = dark_bg.copy()

            # Render DualShock 4 HUD Header (PlayStation Blue banner)
            cv2.rectangle(frame, (0, 0), (canvas_w, 54), (156, 67, 0), -1)
            conn_method = "USB" if ds4.is_usb else "BLUETOOTH"
            c_header = f"{st.controller_name.upper()} ({conn_method})"
            cv2.putText(
                frame,
                c_header,
                (18, 34),
                cv2.FONT_HERSHEY_DUPLEX,
                0.54,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )

            # Connection & Battery badge in header
            if ds4.is_connected:
                batt_str = f"BATTERY: {st.battery_pct}%" + (" [CHARGING]" if st.is_charging else "")
                batt_col = (200, 240, 255)
            else:
                batt_str = "DISCONNECTED"
                batt_col = (100, 100, 255)

            cv2.putText(
                frame,
                batt_str,
                (canvas_w - 220, 34),
                cv2.FONT_HERSHEY_DUPLEX,
                0.46,
                batt_col,
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

            # Hand & Sensitivity & Polling Rate info
            cv2.putText(
                frame,
                f"Active Hand: {hand.upper()} | Sens: {sens:.2f}x | Polling: {st.sample_rate_hz:.0f} Hz",
                (20, 115),
                cv2.FONT_HERSHEY_DUPLEX,
                0.46,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )

            # Disconnected / IMU Frozen alert banner
            if not ds4.is_connected:
                cv2.rectangle(frame, (18, 132), (canvas_w - 18, 172), (20, 20, 140), -1)
                cv2.rectangle(frame, (18, 132), (canvas_w - 18, 172), (60, 60, 220), 1)
                cv2.putText(
                    frame,
                    "[!] CONTROLLER NOT CONNECTED — Press [R] to Reconnect",
                    (30, 158),
                    cv2.FONT_HERSHEY_DUPLEX,
                    0.46,
                    (255, 255, 255),
                    1,
                    cv2.LINE_AA,
                )
            elif ds4.state.imu_frozen:
                cv2.rectangle(frame, (18, 132), (canvas_w - 18, 172), (0, 70, 180), -1)
                cv2.rectangle(frame, (18, 132), (canvas_w - 18, 172), (0, 140, 255), 1)
                cv2.putText(
                    frame,
                    "[!] SENSOR IMU ZERADO/TRAVADO (0G) — Conecte via cabo USB!",
                    (26, 158),
                    cv2.FONT_HERSHEY_DUPLEX,
                    0.44,
                    (255, 255, 255),
                    1,
                    cv2.LINE_AA,
                )

            # 3D G-Force Gauge Bars (X, Y, Z)
            gauge_y_start = 175
            bar_w_max = 180
            axes_data = [
                ("ACCEL X (Lateral)", ax, (0, 215, 255)),    # Gold/Yellow
                ("ACCEL Y (Vertical)", ay, (255, 128, 0)),   # Cyan
                ("ACCEL Z (Forward)", az, (100, 255, 100)),  # Neon Green
            ]

            for idx, (label, val, bar_col) in enumerate(axes_data):
                y_pos = gauge_y_start + idx * 42
                cv2.putText(
                    frame,
                    f"{label}: {val:+.2f} G",
                    (20, y_pos + 12),
                    cv2.FONT_HERSHEY_DUPLEX,
                    0.45,
                    (220, 220, 220),
                    1,
                    cv2.LINE_AA,
                )
                # Background track
                bx = 270
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
                (20, 315),
                cv2.FONT_HERSHEY_DUPLEX,
                0.58,
                (0, 255, 200) if tot_g >= 2.5 else (200, 200, 200),
                1,
                cv2.LINE_AA,
            )

            # Coach selection & controls guidance
            coach_text = f"COACH: {vphone.current_coach_id + 1} / {vphone.total_coaches}"
            cv2.putText(
                frame,
                coach_text,
                (20, 365),
                cv2.FONT_HERSHEY_DUPLEX,
                0.52,
                (0, 230, 255),
                1,
                cv2.LINE_AA,
            )
            cv2.putText(
                frame,
                "[L1] Prev Coach   •   [R1] Next Coach   •   [Enter] Confirm",
                (175, 365),
                cv2.FONT_HERSHEY_DUPLEX,
                0.42,
                (220, 220, 220),
                1,
                cv2.LINE_AA,
            )

            # Reconnection visual feedback
            now_ts = time.time()
            if now_ts < reconnect_feedback_until:
                cv2.putText(
                    frame,
                    "Reconnecting DualShock 4...",
                    (canvas_w - 240, 365),
                    cv2.FONT_HERSHEY_DUPLEX,
                    0.44,
                    (0, 255, 255),
                    1,
                    cv2.LINE_AA,
                )

            # Footer navigation hints ([Q] Quit and [R] Reconnect)
            cv2.rectangle(frame, (0, canvas_h - 40), (canvas_w, canvas_h), (20, 20, 20), -1)
            cv2.putText(
                frame,
                "[Q] Quit   •   [R] Reconnect DS4   •   [L1/R1] Switch Coach",
                (20, canvas_h - 15),
                cv2.FONT_HERSHEY_DUPLEX,
                0.42,
                (200, 200, 200),
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
                print("[INFO] DualShock 4 tracking session terminated by user ([Q] key).")
                break
            elif key in (ord('r'), ord('R')):
                print("[INFO] Reconnecting DualShock 4 controller ([R] key)...")
                reconnect_feedback_until = time.time() + 1.5
                ds4.disconnect()
                time.sleep(0.15)
                success = ds4.connect(permissive=ds4.permissive_mode)
                if success:
                    ds4.trigger_rumble(small=160, large=100, duration_sec=0.25)
                    print("[INFO] DualShock 4 reconnected successfully!")
                else:
                    print("[WARN] Failed to reconnect DualShock 4.")
            elif key in (13, 32):  # Enter or Space
                vphone.send_input("VALID")
                ds4.trigger_rumble(small=160, large=80, duration_sec=0.10)
            elif key in (ord('['), ord('a'), ord('A')):
                vphone.change_coach(-1)
                ds4.trigger_rumble(small=120, large=0, duration_sec=0.08)
            elif key in (ord(']'), ord('d'), ord('D')):
                vphone.change_coach(+1)
                ds4.trigger_rumble(small=120, large=0, duration_sec=0.08)

            if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                break

    except Exception as e:
        print(f"[ERROR] Exception in DualShock 4 tracking loop: {e}")
    finally:
        set_high_resolution_timer(False)
        try:
            from sensor.session_logger import get_session_logger
            dur = round(time.time() - t_start_ds4, 2)
            get_session_logger().stop_telemetry_tracking({
                "duration_s": dur,
                "samples_count": ds4_samples_count,
                "avg_hz": round(ds4_samples_count / max(1.0, dur), 1),
            })
        except Exception:
            pass
        bridge.write_empty()
        bridge.close()
        ds4.disconnect()
        cv2.destroyAllWindows()
        print("[INFO] DualShock 4 tracking session ended.")
        if on_close_callback:
            on_close_callback()

    return True
