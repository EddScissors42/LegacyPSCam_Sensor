"""
Legacy PSCam Sensor - Official Versioning.
Standard:
- Increment 3rd digit for minor changes/improvements (e.g. 0.1.1 -> 0.1.2)
- Increment 2nd digit for major architectural changes or large refactorings (e.g. 0.1.2 -> 0.2.0)
- Always include version number and '(Alpha)' in window titles and UI headers.
"""
__version__ = "0.2.4"
STAGE = "Alpha"
VERSION_STRING = f"v{__version__} ({STAGE})"
APP_NAME = "Legacy PSCam Sensor"
WINDOW_TITLE = f"{APP_NAME} {VERSION_STRING}"

__all__ = [
    "__version__",
    "STAGE",
    "VERSION_STRING",
    "APP_NAME",
    "WINDOW_TITLE",
]
