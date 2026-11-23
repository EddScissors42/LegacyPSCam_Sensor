"""
Gesture Detection Subsystem for Legacy PSCam Sensor.
Provides real-time body gesture recognition (such as holding an arm raised)
to trigger game actions (such as sending an ENTER keystroke or Virtual Phone VALID).
Supports both 1-Player and 2-Player modes (any active player raising an arm triggers ENTER).
"""
import time
import threading
import ctypes
from typing import List, Tuple, Optional, Dict, Any


def dispatch_enter_keystroke(dry_run: bool = False):
    """
    Simulates a physical Enter key press via Windows keybd_event in a non-blocking thread.
    VK_RETURN = 0x0D, SCAN_RETURN = 0x1C.
    When dry_run=True (e.g. automated tests), skips injecting OS keystrokes into the active window.
    """
    if dry_run:
        return

    def _worker():
        try:
            VK_RETURN = 0x0D
            SCAN_RETURN = 0x1C
            KEYEVENTF_KEYUP = 0x0002
            ctypes.windll.user32.keybd_event(VK_RETURN, SCAN_RETURN, 0, 0)
            time.sleep(0.04)
            ctypes.windll.user32.keybd_event(VK_RETURN, SCAN_RETURN, KEYEVENTF_KEYUP, 0)
            print("[GESTURE] Virtual ENTER keystroke dispatched to active window.")
        except Exception as e:
            print(f"[WARN] Failed to dispatch Enter key: {e}")

    threading.Thread(target=_worker, daemon=True, name="GestureEnterKeyThread").start()


def check_arm_raised(px_joints: Optional[List[Tuple[float, float, float]]]) -> bool:
    """
    Detects if either the left or right arm is held raised upwards.
    px_joints: list of 20 2D pixel tuples (px, py, conf) from PoseTracker.
               Joint order:
               2: ShoulderCenter, 3: Head, 4: ShoulderLeft, 6: WristLeft, 7: HandLeft,
               8: ShoulderRight, 10: WristRight, 11: HandRight.
    Note in pixel coordinates: lower Y is higher on screen.
    """
    if not px_joints or len(px_joints) < 12:
        return False

    head = px_joints[3]
    sh_l, sh_r = px_joints[4], px_joints[8]
    wrist_l, wrist_r = px_joints[6], px_joints[10]
    hand_l, hand_r = px_joints[7], px_joints[11]

    ref_y = head[1] if (len(head) > 2 and head[2] > 0.3) else min(sh_l[1], sh_r[1]) - 20

    r_up = (hand_r[2] > 0.3 and (hand_r[1] < ref_y or (hand_r[1] < sh_r[1] - 25 and wrist_r[1] < sh_r[1])))
    l_up = (hand_l[2] > 0.3 and (hand_l[1] < ref_y or (hand_l[1] < sh_l[1] - 25 and wrist_l[1] < sh_l[1])))

    return bool(r_up or l_up)


def get_raised_hand_coords(px_joints: Optional[List[Tuple[float, float, float]]]) -> Optional[Tuple[int, int]]:
    """Returns the (x, y) coordinates of the active raised hand, or None if neither hand is up."""
    if not px_joints or len(px_joints) < 12:
        return None

    head = px_joints[3]
    sh_l, sh_r = px_joints[4], px_joints[8]
    wrist_l, wrist_r = px_joints[6], px_joints[10]
    hand_l, hand_r = px_joints[7], px_joints[11]

    ref_y = head[1] if (len(head) > 2 and head[2] > 0.3) else min(sh_l[1], sh_r[1]) - 20

    r_up = (hand_r[2] > 0.3 and (hand_r[1] < ref_y or (hand_r[1] < sh_r[1] - 25 and wrist_r[1] < sh_r[1])))
    l_up = (hand_l[2] > 0.3 and (hand_l[1] < ref_y or (hand_l[1] < sh_l[1] - 25 and wrist_l[1] < sh_l[1])))

    if r_up and l_up:
        return (int(hand_r[0]), int(hand_r[1])) if hand_r[1] < hand_l[1] else (int(hand_l[0]), int(hand_l[1]))
    elif r_up:
        return (int(hand_r[0]), int(hand_r[1]))
    elif l_up:
        return (int(hand_l[0]), int(hand_l[1]))
    return None


class ArmRaiseGestureDetector:
    """
    Modular state machine that detects an arm held raised for a specified duration,
    triggers keyboard/virtual phone events, and reports progress for HUD rendering.
    In 2-player mode, accepts an arm raise from either Player 1 or Player 2.
    """
    def __init__(
        self,
        enabled: bool = True,
        hold_seconds: float = 2.0,
        cooldown_seconds: float = 2.5,
        dispatch_keystroke: bool = True,
    ):
        self.enabled = bool(enabled)
        self.hold_seconds = max(0.5, float(hold_seconds))
        self.cooldown_seconds = max(1.0, float(cooldown_seconds))
        self.dispatch_keystroke = bool(dispatch_keystroke)

        self.start_time: Optional[float] = None
        self.triggered: bool = False
        self.last_trigger_time: float = 0.0
        self.feedback_duration: float = 1.4
        self.active_player_idx: Optional[int] = None
        self.last_hand_pos: Optional[Tuple[int, int]] = None

    def reset(self):
        self.start_time = None
        self.triggered = False
        self.active_player_idx = None
        self.last_hand_pos = None

    def update(
        self,
        px_joints: Optional[List[Tuple[float, float, float]]],
        is_tracked: bool,
        vphone=None,
        now: Optional[float] = None
    ) -> Dict[str, Any]:
        """Single-player update wrapper."""
        players_list = [px_joints] if (is_tracked and px_joints) else []
        return self.update_multi(players_list, is_tracked=bool(is_tracked and px_joints), vphone=vphone, now=now)

    def update_multi(
        self,
        players_px_joints: List[Optional[List[Tuple[float, float, float]]]],
        is_tracked: bool = True,
        vphone=None,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Updates detector state across 1 or 2 players.
        If either Player 1 or Player 2 holds an arm raised for `hold_seconds`, dispatches ENTER.
        """
        if now is None:
            now = time.time()

        valid_players = [
            (idx, px)
            for idx, px in enumerate(players_px_joints or [])
            if px is not None and len(px) >= 12
        ]

        if not self.enabled or not is_tracked or not valid_players:
            self.reset()
            return {
                "enabled": self.enabled,
                "holding": False,
                "progress": 0.0,
                "elapsed": 0.0,
                "target": self.hold_seconds,
                "triggered": False,
                "player_idx": None,
                "feedback_active": (now - self.last_trigger_time < self.feedback_duration),
            }

        in_cooldown = (now - self.last_trigger_time < self.cooldown_seconds)
        raising_player = None
        current_hand_pos = None
        for idx, px in valid_players:
            if check_arm_raised(px):
                raising_player = idx
                current_hand_pos = get_raised_hand_coords(px)
                break

        arm_up = (raising_player is not None)
        just_triggered = False
        holding = False
        elapsed = 0.0
        progress = 0.0

        if arm_up and not in_cooldown:
            self.active_player_idx = raising_player
            if current_hand_pos:
                self.last_hand_pos = current_hand_pos
            if self.start_time is None:
                self.start_time = now
                self.triggered = False
            else:
                elapsed = now - self.start_time
                progress = min(1.0, elapsed / self.hold_seconds)
                holding = True

                if elapsed >= self.hold_seconds and not self.triggered:
                    self.triggered = True
                    just_triggered = True
                    self.last_trigger_time = now

                    if self.dispatch_keystroke:
                        dispatch_enter_keystroke()

                    if vphone is not None and getattr(vphone, "enabled", False):
                        try:
                            vphone.send_input("VALID")
                        except Exception as e:
                            print(f"[WARN] Virtual Phone VALID dispatch error: {e}")

                    p_label = f"P{raising_player + 1}"
                    print(f"\n[GESTURE] >>> {p_label} ARM RAISED >= {self.hold_seconds:.1f}s: ENTER COMMAND DISPATCHED! <<<\n")
                    try:
                        from sensor.session_logger import get_session_logger
                        get_session_logger().log(
                            "GESTURE",
                            f"{p_label} arm raised hold >= {self.hold_seconds:.1f}s: ENTER command dispatched.",
                        )
                    except Exception:
                        pass
        else:
            self.start_time = None
            self.triggered = False
            self.active_player_idx = None

        feedback_active = (now - self.last_trigger_time < self.feedback_duration)

        return {
            "enabled": self.enabled,
            "holding": holding and not self.triggered,
            "progress": progress,
            "elapsed": elapsed,
            "target": self.hold_seconds,
            "triggered": just_triggered,
            "player_idx": self.active_player_idx,
            "feedback_active": feedback_active,
            "hand_pos": current_hand_pos if holding else self.last_hand_pos,
        }
