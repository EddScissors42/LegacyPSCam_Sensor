"""
PyInstaller runtime hook for Legacy PSCam Sensor.
MediaPipe 0.10+ unconditionally imports matplotlib.pyplot in drawing_utils at import time,
even though Legacy PSCam Sensor renders its overlays entirely via OpenCV.
Providing a lightweight dummy module avoids ModuleNotFoundError while eliminating 80MB+ of matplotlib dependencies.
"""
import sys
import types

if "matplotlib" not in sys.modules:
    m = types.ModuleType("matplotlib")
    plt = types.ModuleType("matplotlib.pyplot")
    m.pyplot = plt
    sys.modules["matplotlib"] = m
    sys.modules["matplotlib.pyplot"] = plt
