"""
Legacy PSCam Sensor - UI Controllers Package.
Decouples UI views (PySide6 / Qt 6) from domain hardware, network, and tracking logic.
Implements the Model-View-Presenter (MVP) / Facade architecture.
"""
from .camera_controller import CameraController
from .device_controller import DeviceController
from .session_controller import SessionController
from .app_controller import SensorAppController

__all__ = [
    "CameraController",
    "DeviceController",
    "SessionController",
    "SensorAppController",
]
