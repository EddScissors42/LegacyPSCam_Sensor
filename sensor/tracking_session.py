"""
Tracking Session Runner for Legacy PSCam Sensor.
Coordinates camera stream, MediaPipe pose processing (1P & 2P),
shared memory output, and OpenCV HUD preview window.
"""
import os
import time
import math
import cv2
import ctypes
from ctypes import wintypes
import threading
import numpy as np
from typing import Tuple
from sensor.camera_manager import LatestFrameCamera, CameraManager
from sensor.kinect_shared_memory import get_kinect_bridge
from sensor.config_manager import parse_preset
from sensor.gesture_detector import (
    ArmRaiseGestureDetector,
    check_arm_raised,
    dispatch_enter_keystroke,
)

_send_enter_keystroke = dispatch_enter_keystroke


def apply_pip_window_state(
    window_name: str,
    pip_active: bool,
    frame_w: int,
    frame_h: int,
    normal_size: Tuple[int, int],
) -> None:
    """
    Switches the OpenCV tracking window between compact Always-On-Top Picture-in-Picture (PiP)
    mode (320px wide, proportional height, HWND_TOPMOST) and standard window mode.
    """
    if pip_active:
        pip_w = 320
        pip_h = max(180, int(round(320 * (frame_h / float(max(1, frame_w))))))
        target_w, target_h = pip_w, pip_h
    else:
        target_w, target_h = normal_size

    try:
        cv2.resizeWindow(window_name, target_w, target_h)
    except Exception:
        pass

    try:
        if hasattr(cv2, "WND_PROP_TOPMOST"):
            cv2.setWindowProperty(window_name, cv2.WND_PROP_TOPMOST, 1.0 if pip_active else 0.0)
    except Exception:
        pass

    if os.name == "nt":
        try:
            user32 = ctypes.windll.user32
            user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
            user32.FindWindowW.restype = wintypes.HWND
            user32.SetWindowPos.argtypes = [
                wintypes.HWND,
                wintypes.HWND,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.UINT,
            ]
            user32.SetWindowPos.restype = wintypes.BOOL

            hwnd = user32.FindWindowW(None, window_name)
            if hwnd:
                # HWND_TOPMOST = -1, HWND_NOTOPMOST = -2
                z_order = wintypes.HWND(-1 if pip_active else -2)
                SWP_NOMOVE = 0x0002
                SWP_NOSIZE = 0x0001
                SWP_SHOWWINDOW = 0x0040
                user32.SetWindowPos(hwnd, z_order, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        except Exception:
            pass


def apply_window_icon(window_name: str) -> None:
    """
    Applies the bundled multi-resolution `app_icon.ico` directly to an OpenCV Win32 window
    (title bar, Alt+Tab, and Windows Taskbar) via LoadImageW + WM_SETICON.
    """
    if os.name != "nt":
        return
    try:
        from assets import ICON_APP_ICO_PATH
        if not ICON_APP_ICO_PATH or not ICON_APP_ICO_PATH.exists():
            return
        user32 = ctypes.windll.user32
        user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        user32.FindWindowW.restype = wintypes.HWND
        user32.LoadImageW.argtypes = [
            wintypes.HINSTANCE,
            wintypes.LPCWSTR,
            wintypes.UINT,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.SendMessageW.restype = ctypes.c_ssize_t

        hwnd = user32.FindWindowW(None, window_name)
        if not hwnd:
            return
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x0010
        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1
        ico_str = str(ICON_APP_ICO_PATH)
        h_small = user32.LoadImageW(None, ico_str, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
        h_big = user32.LoadImageW(None, ico_str, IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
        if h_small:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, h_small)
        if h_big:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, h_big)
    except Exception:
        pass


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


def run_tracking_session(config, on_close_callback=None, stop_event=None, prewarmed_camera=None):
    """
    Starts the live tracking loop (supports 1 Player Solo and 2 Players Duo).
    config: dictionary with tracking parameters.
    on_close_callback: optional function called when tracking terminates.
    stop_event: optional threading.Event to signal loop termination.
    prewarmed_camera: optional running LatestFrameCamera instance to adopt with 0s latency.
    """
    mode = config.get("camera_mode", "pscam")
    if mode == "ds4":
        return run_ds4_tracking_session(config, on_close_callback=on_close_callback, stop_event=stop_event)

    cam_idx = config.get("camera_index", 0)
    if cam_idx < 0 and mode != "phone_cam":
        cams = CameraManager.enumerate_cameras()
        ps_cams = [c for c in cams if c.is_pscam]
        if mode == "pscam" and ps_cams:
            cam_idx = ps_cams[0].index
        elif cams:
            cam_idx = cams[0].index
        else:
            cam_idx = 0
    if mode == "pscam":
        preset_str = config.get("pscam_preset", "1280x800 @ 60 FPS")
    elif mode == "phone_cam":
        preset_str = config.get("phone_cam_preset", "640x480 @ 30 FPS")
    else:
        preset_str = config.get("webcam_preset", "640x480 @ 30 FPS")
    w, h, target_fps = parse_preset(preset_str)
    mirror = config.get("mirror_horizontal", True)
    smoothing_alpha = config.get("smoothing_alpha", 0.75)
    det_conf = config.get("detection_confidence", 0.45)
    target_height = config.get("target_height_m", 1.75)
    show_hud = config.get("show_hud", True)
    camera_orientation = int(config.get("camera_orientation", 0))
    ps4_eye = str(config.get("ps4_eye", "right")).strip().lower()
    ps4_backend_mode = str(config.get("ps4_camera_backend", "native")).strip().lower()
    max_players = max(1, min(2, int(config.get("max_players", 1))))

    mode_title = "PlayStation Camera" if mode == "pscam" else ("Phone Camera (Wi-Fi)" if mode == "phone_cam" else "Standard Webcam")
    print(f"\n==========================================")
    print(f"  STARTING TRACKING SESSION")
    print(f"  Mode: {mode_title} | Players: {max_players}P")
    print(f"  Camera: {cam_idx if mode != 'phone_cam' else 'WebApp'} | Resolution: {w}x{h} @ {target_fps} FPS")
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

    # 1. Acquire process-wide singleton IPC Shared Memory Bridge (Pose V1/V2, Image V1/V2 & CoachX)
    bridge = get_kinect_bridge()

    # 1.1 Always run KinectEmulatorDaemon (Zero-File-Replacement Mode, always active)
    local_kinect_emulator = None
    if bool(config.get("emulate_kinect_enabled", True)):
        from sensor.kinect_emulator import get_kinect_emulator
        local_kinect_emulator = get_kinect_emulator(config)
        local_kinect_emulator.enabled = True
        local_kinect_emulator.start()

    # 2. Initialize Camera Grabber (pristine raw frames to tracker)
    camera = None
    if (
        prewarmed_camera is not None
        and getattr(prewarmed_camera, "running", False)
        and getattr(prewarmed_camera, "is_compatible", lambda **kw: True)(
            camera_index=cam_idx,
            target_w=w,
            target_h=h,
            target_fps=target_fps,
            mirror=mirror,
            is_pscam=(mode == "pscam"),
            orientation=camera_orientation,
            ps4_eye=ps4_eye,
            ps4_backend_mode=ps4_backend_mode,
            is_phone_cam=(mode == "phone_cam"),
        )
    ):
        camera = prewarmed_camera
        camera.activate_live()
        print(f"[CAMERA] Instância pré-aquecida adotada instantaneamente: {w}x{h}@{target_fps}fps")
    else:
        if prewarmed_camera is not None:
            try:
                prewarmed_camera.release()
            except Exception:
                pass
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
                is_phone_cam=(mode == "phone_cam"),
            )
        except Exception as e:
            print(f"[ERROR] Failed to start camera: {e}")
            bridge.write_empty()
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
        pose_model = preset_model_map.get(config.get("tracking_preset", "competitive"), "lite")

    if (target_fps >= 50 or max_players >= 2) and pose_model == "full":
        print(
            f"[PERF] Rastreamento ({max_players}P @ {target_fps} FPS) com modelo '{pose_model}'. "
            f"Para maior estabilidade de FPS na CPU, recomenda-se o perfil 'Competitive' (Lite AI)."
        )

    try:
        tracker = PoseTracker(
            detection_confidence=det_conf,
            smoothing_alpha=smoothing_alpha,
            target_height_m=target_height,
            cfg=config,
            model_variant=pose_model,
            max_players=max_players,
        )
        # Stereo Vision is always active by default on PlayStation 4 Camera
        if mode == "pscam" and getattr(tracker, "stereo_mode", "disabled") == "disabled":
            tracker.stereo_mode = "sparse_metric"
    except Exception as e:
        print(f"[ERROR] Failed to start MediaPipe Pose Tracker: {e}")
        camera.release()
        bridge.write_empty()
        if on_close_callback:
            on_close_callback()
        return False

    # 4. Initialize Overlay
    overlay = TrackingOverlay(show_hud=show_hud)

    # 5. Configure Virtual Phone Controller (if enabled in config or active via GUI)
    from sensor.virtual_phone import get_virtual_phone
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
    normal_win_size = (min(w, 1280), min(h, 800))
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL | cv2.WINDOW_GUI_EXPANDED)
    cv2.resizeWindow(window_name, normal_win_size[0], normal_win_size[1])
    apply_window_icon(window_name)

    track_fps_counter = 0
    track_fps_last_time = time.time()
    measured_track_fps = float(target_fps)

    dev_label = "PS Camera" if mode == "pscam" else ("Phone Camera" if mode == "phone_cam" else "Webcam")
    mode_label = f"{dev_label} ({camera.actual_w}x{camera.actual_h})"

    t_start_session = time.time()
    total_frames = 0

    try:
        from sensor.session_logger import get_session_logger
        cfg_summary = f"{w}x{h}@{target_fps}FPS, mode={mode}, players={max_players}P, model={pose_model}"
        get_session_logger().map_active_controller(
            controller_type="camera",
            name="PlayStation 4 Camera" if mode == "pscam" else ("Phone Camera (Wi-Fi)" if mode == "phone_cam" else "Standard Webcam"),
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

            if mode == "phone_cam" and getattr(camera, "phone_cam_server", None) is not None:
                if not camera.phone_cam_server.is_client_connected:
                    print("[PHONE-CAM] Smartphone disconnected. Ending tracking session...")
                    break

            ret, frame, cam_fps = camera.read(only_new=True)
            if not ret or frame is None:
                key = cv2.waitKey(1) & 0xFF
                if key in (27, ord('q'), ord('Q')):
                    break
                elif key in (ord('c'), ord('C')):
                    tracker.recalibrate()
                    print("[INFO] Height/skeleton & identity memory recalibration triggered!")
                elif key in (ord('m'), ord('M')):
                    mirror = not mirror
                    camera.set_mirror(mirror)
                    print(f"[INFO] Mirroring toggled to: {mirror}")
                elif key in (ord('h'), ord('H')):
                    overlay.toggle_hud()
                elif key in (ord('p'), ord('P')):
                    pip_on = overlay.toggle_pip()
                    apply_pip_window_state(window_name, pip_on, camera.actual_w or w, camera.actual_h or h, normal_win_size)
                    print(f"[INFO] Picture-in-Picture (PiP) mode toggled to: {pip_on}")
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

            frame_secondary = None
            if getattr(tracker, "stereo_mode", "disabled") != "disabled":
                if ps4_eye == "left":
                    if hasattr(camera, "read_right_mono"):
                        frame_secondary = camera.read_right_mono()
                    if frame_secondary is None:
                        st_data = camera.read_stereo(only_new=False)
                        if st_data:
                            frame_secondary = st_data.get("right_bgr")
                else:
                    if hasattr(camera, "read_left_mono"):
                        frame_secondary = camera.read_left_mono()
                    if frame_secondary is None and hasattr(camera, "read_left_eye"):
                        frame_secondary = camera.read_left_eye(mono=True)
                    if frame_secondary is None:
                        st_data = camera.read_stereo(only_new=False)
                        if st_data:
                            frame_secondary = st_data.get("left_bgr")

            # Process 1 or 2 poses on pristine RAW frame with MediaPipe (guarantees correct anatomical limbs)
            multi_res = tracker.process_frame_multi(frame, frame_left=frame_secondary, primary_eye=ps4_eye)
            is_tracked = multi_res.any_tracked
            primary_p = multi_res.primary_player
            kinect_joints = primary_p.kinect_joints if primary_p else None
            body_mask = multi_res.player_index_mask

            # Detect arm raised gesture from ANY active player (P1 or P2) to dispatch virtual ENTER
            all_px_joints = [
                pf.pixel_joints if (pf is not None and pf.tracked) else None
                for pf in multi_res.players
            ]
            gesture_info = gesture_detector.update_multi(all_px_joints, is_tracked=is_tracked, vphone=vphone)

            # Measure tracking FPS
            track_fps_counter += 1
            now = time.time()
            dt = now - track_fps_last_time
            if dt >= 1.0:
                measured_track_fps = track_fps_counter / dt
                track_fps_counter = 0
                track_fps_last_time = now

            # Prepare frame, mask and per-player skeletons for display and Kinect HUD preview
            fh, fw = frame.shape[:2]
            if mirror:
                display_frame = cv2.flip(frame, 1)
                display_mask = cv2.flip(body_mask, 1) if body_mask is not None else None
                display_players_px = [
                    [(fw - 1 - p[0], p[1], p[2]) for p in pf.pixel_joints]
                    if (pf is not None and pf.tracked and pf.pixel_joints)
                    else None
                    for pf in multi_res.players
                ]
            else:
                display_frame = frame
                display_mask = body_mask
                display_players_px = [
                    pf.pixel_joints if (pf is not None and pf.tracked and pf.pixel_joints) else None
                    for pf in multi_res.players
                ]

            # Apply dynamic Face Follow (PTZ Auto-framing) ONLY in 1-Player mode so Player 2 is never cropped out
            face_follow_on = bool(config.get("face_follow_enabled", False)) and (max_players == 1)
            tracker.face_ptz.cfg["face_follow_enabled"] = face_follow_on
            if face_follow_on and is_tracked and tracker.last_norm_landmarks:
                tracker.face_ptz.update_from_norm(
                    tracker.last_norm_landmarks,
                    mirrored=mirror,
                    kinect_joints=kinect_joints,
                )
                kinect_frame, kinect_mask = tracker.face_ptz.apply(display_frame, display_mask)
            else:
                if tracker.face_ptz.valid:
                    tracker.face_ptz.reset()
                kinect_frame, kinect_mask = display_frame, display_mask

            # Update Shared Memory for Just Dance PC (JDP1, JDP2 664B, JMI1 & JMI2 player index mask)
            # Always stream Kinect skeletons in camera modes (never allow stale vphone flag from DS4 mode to wipe Kinect!)
            players_3d = [
                pf.kinect_joints if (pf is not None and pf.tracked) else None
                for pf in multi_res.players
            ]
            if is_tracked and multi_res.tracked_mask > 0:
                bridge.write_multi(
                    players_3d,
                    kinect_frame,
                    kinect_mask,
                    tracked_mask=multi_res.tracked_mask,
                )
            else:
                bridge.write_empty()

            # Feed primary player's 3D Hand Coordinates to Virtual Phone Controller
            vphone.update_from_joints(kinect_joints, bool(kinect_joints is not None))

            total_frames += 1
            try:
                from sensor.session_logger import get_session_logger
                accel = vphone.latest_accel
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
            except Exception as e:
                try:
                    from sensor.session_logger import get_session_logger
                    get_session_logger().log_throttled(
                        "telemetry_cam_err", "WARN", "TELEMETRY", f"Camera telemetry sample error: {e}"
                    )
                except Exception:
                    pass

            # Render Player Silhouette Shadow & Contour ("sombrinha"): P1 Blue, P2 Light Orange
            if is_tracked and display_mask is not None:
                display_frame = overlay.draw_multi_player_silhouettes(display_frame, display_mask)

            # Render Skeletons on top for each active player with Scoring Hand Aura
            scoring_hand_side = str(getattr(vphone, "hand", "right")).lower()
            current_hand_speed = float(getattr(vphone.accelerometer, "latest_speed", 0.0))
            for s_idx, p_px in enumerate(display_players_px):
                if p_px:
                    display_frame = overlay.draw_skeleton(
                        display_frame,
                        p_px,
                        player_idx=s_idx,
                        show_badge=(max_players >= 2 and not overlay.pip_mode),
                        scoring_hand=scoring_hand_side,
                        hand_speed=current_hand_speed,
                    )

            if not overlay.pip_mode:
                primary_calib = primary_p.is_calibrated if primary_p else tracker.calibrator.is_calibrated
                primary_tier = primary_p.calibration_tier if primary_p else tracker.calibrator.calibration_tier
                emu_st = local_kinect_emulator.get_status() if local_kinect_emulator is not None else None
                display_frame = overlay.draw_hud(
                    display_frame,
                    camera_info_str=mode_label,
                    is_tracked=is_tracked,
                    cam_fps=cam_fps,
                    track_fps=measured_track_fps,
                    is_calibrated=primary_calib,
                    is_mirrored=mirror,
                    calibration_tier=primary_tier,
                    max_players=max_players,
                    tracked_mask=multi_res.tracked_mask,
                    phone_portrait_warning=(mode == "phone_cam" and fh > fw),
                    kinect_emu_status=emu_st,
                )

                # Render modern gesture radial progress ring & success pulse
                display_frame = overlay.draw_gesture_feedback(
                    display_frame,
                    gesture_info,
                    max_players=max_players,
                )

            cv2.imshow(window_name, display_frame)

            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord('q'), ord('Q')):  # ESC or Q
                print("[INFO] Exit requested by user.")
                break
            elif key in (ord('c'), ord('C')):
                tracker.recalibrate()
                print("[INFO] Height/skeleton & identity memory recalibration triggered!")
            elif key in (ord('m'), ord('M')):
                mirror = not mirror
                camera.set_mirror(mirror)
                print(f"[INFO] Mirroring toggled to: {mirror}")
            elif key in (ord('h'), ord('H')):
                overlay.toggle_hud()
            elif key in (ord('p'), ord('P')):
                pip_on = overlay.toggle_pip()
                apply_pip_window_state(window_name, pip_on, fw, fh, normal_win_size)
                print(f"[INFO] Picture-in-Picture (PiP) mode toggled to: {pip_on}")
            elif key in (ord('o'), ord('O')):
                camera_orientation = (camera_orientation + 90) % 360
                camera.set_orientation(camera_orientation)
                print(f"[INFO] Camera orientation toggled to: {camera_orientation}°")
            elif key in (13, 32):  # Enter or Space: Send VALID / OK to game via Virtual Phone
                if vphone.enabled:
                    vphone.send_input("VALID")

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
        if local_kinect_emulator is not None and on_close_callback is None:
            local_kinect_emulator.stop()
        bridge.write_empty()
        camera.release()
        tracker.close()
        cv2.destroyAllWindows()
        print("[INFO] Tracking session ended.")
        if on_close_callback:
            on_close_callback()

    return True


def run_ds4_tracking_session(config, on_close_callback=None, stop_event=None):
    """
    Dedicated motion tracking loop for the Sony DualShock 4 controller over Bluetooth/USB.
    Streams 3D physical accelerometer samples directly into Just Dance via Virtual Phone,
    provides visual telemetry (3D accel gauges, battery %, HID sample rate),
    and handles hotkeys ([Q] Quit, [R] Reconnect).
    """
    from sensor.ds4_controller import get_ds4_controller
    from sensor.virtual_phone import get_virtual_phone
    from sensor.tracking_overlay import TrackingOverlay

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
    bridge = get_kinect_bridge()

    overlay = TrackingOverlay(show_hud=True)

    window_name = "Legacy PSCam Sensor — DualShock 4 Tracking"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL | cv2.WINDOW_GUI_EXPANDED)
    cv2.resizeWindow(window_name, 720, 480)
    apply_window_icon(window_name)

    print(f"\n==========================================")
    print(f"  STARTING DUALSHOCK 4 TRACKING SESSION")
    print(f"  Hand: {hand.upper()} | Sensitivity: {sens:.2f}x")
    print(f"  Connected: {ds4.is_connected} | Polling: {ds4.state.sample_rate_hz:.0f} Hz | Battery: {ds4.state.battery_pct}%")
    print(f"==========================================\n")

    canvas_w, canvas_h = 640, 480
    dark_bg = np.zeros((canvas_h, canvas_w, 3), dtype=np.uint8)
    for y in range(canvas_h):
        r_val = int(14 + (y / canvas_h) * 8)
        g_val = int(18 + (y / canvas_h) * 10)
        b_val = int(26 + (y / canvas_h) * 14)
        dark_bg[y, :] = (b_val, g_val, r_val)

    action_toast = ""
    toast_until = 0.0

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
            except Exception as e:
                try:
                    from sensor.session_logger import get_session_logger
                    get_session_logger().log_throttled(
                        "telemetry_ds4_err", "WARN", "TELEMETRY", f"DS4 telemetry sample error: {e}"
                    )
                except Exception:
                    pass

            frame = dark_bg.copy()

            now_ts = time.time()
            current_toast = action_toast if now_ts < toast_until else None

            frame = overlay.draw_controller_hud(
                frame=frame,
                controller_name=st.controller_name,
                conn_type="USB" if ds4.is_usb else "Bluetooth",
                hand=hand,
                sens=sens,
                sample_rate_hz=st.sample_rate_hz,
                battery_pct=st.battery_pct,
                is_charging=st.is_charging,
                is_connected=ds4.is_connected,
                imu_frozen=st.imu_frozen,
                vphone_status=vphone.status_text,
                vphone_connected=vphone.connected,
                tot_g=tot_g,
                current_coach=vphone.current_coach_id,
                total_coaches=vphone.total_coaches,
                song_name=getattr(vphone, "current_map_name", None),
                action_toast=current_toast,
                accel_axes=(ax, ay, az),
                gyro_axes=st.gyro,
            )

            bridge.pose.write_empty()
            bridge.pose_v2.write_empty()
            bridge.image.write_image_and_mask(frame, np.zeros((240, 320), dtype=np.uint8), tracked=True)

            cv2.imshow(window_name, frame)

            key = cv2.waitKey(16) & 0xFF
            if key in (27, ord('q'), ord('Q')):
                print("[INFO] DualShock 4 tracking session terminated by user ([Q] key).")
                break
            elif key in (ord('h'), ord('H')):
                overlay.toggle_hud()
            elif key in (ord('r'), ord('R')):
                print("[INFO] Reconnecting DualShock 4 controller ([R] key)...")
                action_toast = "Reconnecting DualShock 4..."
                toast_until = time.time() + 2.0
                ds4.disconnect()
                time.sleep(0.15)
                success = ds4.connect(permissive=ds4.permissive_mode)
                if success:
                    ds4.trigger_rumble(small=160, large=100, duration_sec=0.25)
                    action_toast = "DualShock 4 Reconnected \u2713"
                    toast_until = time.time() + 1.8
                    print("[INFO] DualShock 4 reconnected successfully!")
                else:
                    action_toast = "[!] Reconnect Failed — Check Bluetooth/USB"
                    toast_until = time.time() + 2.0
                    print("[WARN] Failed to reconnect DualShock 4.")
            elif key in (13, 32):
                vphone.send_input("VALID")
                ds4.trigger_rumble(small=160, large=80, duration_sec=0.10)
                action_toast = "Enter / Confirm Sent \u2713"
                toast_until = time.time() + 1.2
            elif key in (ord('['), ord('a'), ord('A')):
                vphone.change_coach(-1)
                ds4.trigger_rumble(small=120, large=0, duration_sec=0.08)
                action_toast = f"Switched to Coach {vphone.current_coach_id + 1} / {vphone.total_coaches}"
                toast_until = time.time() + 1.2
            elif key in (ord(']'), ord('d'), ord('D')):
                vphone.change_coach(+1)
                ds4.trigger_rumble(small=120, large=0, duration_sec=0.08)
                action_toast = f"Switched to Coach {vphone.current_coach_id + 1} / {vphone.total_coaches}"
                toast_until = time.time() + 1.2

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
        cv2.destroyAllWindows()
        print("[INFO] DualShock 4 tracking session ended.")
        if on_close_callback:
            on_close_callback()

    return True
