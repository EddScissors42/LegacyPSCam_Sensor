"""
Modular UI Mixins for Legacy PSCam Sensor Qt 6 GUI.
Splits window event handlers and live device readouts into focused, cohesive modules
while keeping `LegacySensorQtGUI` (`ui/gui_qt.py`) lean and readable.
"""
from .device_readout import UIDeviceReadoutMixin
from .camera_handlers import UICameraHandlersMixin
from .phone_handlers import UIPhoneHandlersMixin
from .ds4_vphone_handlers import UIDS4VPhoneHandlersMixin
from .tracking_handlers import UITrackingHandlersMixin

__all__ = [
    "UIDeviceReadoutMixin",
    "UICameraHandlersMixin",
    "UIPhoneHandlersMixin",
    "UIDS4VPhoneHandlersMixin",
    "UITrackingHandlersMixin",
]
