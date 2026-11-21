"""
Gesture Detection Subsystem for Legacy PSCam Sensor.
Provides real-time body gesture recognition (such as holding an arm raised)
to trigger game actions (such as sending an ENTER keystroke or Virtual Phone VALID).
Completely modular and configurable.
"""
import time
import threading
import ctypes
from typing import List, Tuple, Optional, Dict, Any


def dispatch_enter_keystroke():
    """
    Simulates a physical Enter key press via Windows keybd_event in a non-blocking thread.
    VK_RETURN = 0x0D, SCAN_RETURN = 0x1C.
    """
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
    sh_c = px_joints[2]
    sh_l, sh_r = px_joints[4], px_joints[8]
    wrist_l, wrist_r = px_joints[6], px_joints[10]
    hand_l, hand_r = px_joints[7], px_joints[11]

    # Reference Y threshold: minimum (highest) between head and shoulders - 20px
    ref_y = head[1] if (len(head) > 2 and head[2] > 0.3) else min(sh_l[1], sh_r[1]) - 20

    # Right arm raised: hand higher than head OR hand & wrist comfortably above shoulder
    r_up = (hand_r[2] > 0.3 and (hand_r[1] < ref_y or (hand_r[1] < sh_r[1] - 25 and wrist_r[1] < sh_r[1])))

    # Left arm raised: hand higher than head OR hand & wrist comfortably above shoulder
    l_up = (hand_l[2] > 0.3 and (hand_l[1] < ref_y or (hand_l[1] < sh_l[1] - 25 and wrist_l[1] < sh_l[1])))

    return bool(r_up or l_up)


class ArmRaiseGestureDetector:
    """
    Modular state machine that detects an arm held raised for a specified duration,
    triggers keyboard/virtual phone events, and reports progress for HUD rendering.
    """
    def __init__(self, enabled: bool = True, hold_seconds: float = 2.0, cooldown_seconds: float = 2.5):
        self.enabled = bool(enabled)
        self.hold_seconds = max(0.5, float(hold_seconds))
        self.cooldown_seconds = max(1.0, float(cooldown_seconds))

        self.start_time: Optional[float] = None
        self.triggered: bool = False
        self.last_trigger_time: float = 0.0
        self.feedback_duration: float = 1.4

    def reset(self):
        self.start_time = None
        self.triggered = False

    def update(
        self,
        px_joints: Optional[List[Tuple[float, float, float]]],
        is_tracked: bool,
        vphone=None,
        now: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Updates detector state with current frame tracking data.
        Returns state dict for HUD rendering and diagnostic logging.
        """
        if now is None:
            now = time.time()

        if not self.enabled or not is_tracked or not px_joints:
            self.reset()
            return {
                "enabled": self.enabled,
                "holding": False,
                "progress": 0.0,
                "elapsed": 0.0,
                "target": self.hold_seconds,
                "triggered": False,
                "feedback_active": (now - self.last_trigger_time < self.feedback_duration),
            }

        in_cooldown = (now - self.last_trigger_time < self.cooldown_seconds)
        arm_up = check_arm_raised(px_joints)

        just_triggered = False
        holding = False
        elapsed = 0.0
        progress = 0.0

        if arm_up and not in_cooldown:
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

                    # Dispatch virtual ENTER keystroke to active game window
                    dispatch_enter_keystroke()

                    # Dispatch Virtual Phone VALID input if controller is active
                    if vphone is not None and getattr(vphone, "enabled", False):
                        try:
                            vphone.send_input("VALID")
                        except Exception as e:
                            print(f"[WARN] Virtual Phone VALID dispatch error: {e}")

                    print("\n[GESTURE] >>> ARM RAISED >= 2.0s: ENTER COMMAND DISPATCHED! <<<\n")
                    try:
                        from sensor.session_logger import get_session_logger
                        get_session_logger().log("GESTURE", f"Arm raised hold >= {self.hold_seconds:.1f}s: ENTER command dispatched.")
                    except Exception:
                        pass
        else:
            self.start_time = None
            self.triggered = False

        feedback_active = (now - self.last_trigger_time < self.feedback_duration)

        return {
            "enabled": self.enabled,
            "holding": holding and not self.triggered,
            "progress": progress,
            "elapsed": elapsed,
            "target": self.hold_seconds,
            "triggered": just_triggered,
            "feedback_active": feedback_active,
        }
