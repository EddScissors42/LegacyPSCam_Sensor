# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all
from PyInstaller.utils.win32.versioninfo import (
    VSVersionInfo,
    FixedFileInfo,
    StringFileInfo,
    StringTable,
    StringStruct,
    VarFileInfo,
    VarStruct,
)

sys.path.insert(0, str(Path.cwd()))
from version import __version__, APP_NAME, VERSION_STRING

_ver_parts = [int(p) if p.isdigit() else 0 for p in (__version__.split(".") + ["0", "0", "0"])[:4]]
_ver_tuple = (_ver_parts[0], _ver_parts[1], _ver_parts[2], _ver_parts[3])

pe_version_info = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=_ver_tuple,
        prodvers=_ver_tuple,
        mask=0x3F,
        flags=0x0,
        OS=0x40004,
        fileType=0x1,
        subtype=0x0,
        date=(0, 0),
    ),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "040904B0",
                    [
                        StringStruct("CompanyName", "Legacy PSCam Sensor Project"),
                        StringStruct("FileDescription", f"{APP_NAME} — Motion Sensor for Just Dance PC"),
                        StringStruct("FileVersion", f"{__version__}.0"),
                        StringStruct("InternalName", "LegacyPSCam_Sensor"),
                        StringStruct("LegalCopyright", "Open Source — Legacy PSCam Sensor Contributors"),
                        StringStruct("OriginalFilename", "LegacyPSCam_Sensor.exe"),
                        StringStruct("ProductName", APP_NAME),
                        StringStruct("ProductVersion", VERSION_STRING),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)

block_cipher = None

# Collect all required binaries, data and hidden imports for mediapipe
mp_datas, mp_binaries, mp_hiddenimports = collect_all('mediapipe')

added_datas = [
    ('models/pose_landmarker_lite.task', 'models'),
    ('models/pose_landmarker_full.task', 'models'),
    ('assets', 'assets'),
    ('tools/Legacy10.dll', 'tools'),
    ('tools/get_cameras.ps1', 'tools'),
    ('driver/legacy_pscam_device.inf', 'driver'),
] + mp_datas

if Path('tools/PSCam4Win-Setup.exe').exists():
    added_datas.append(('tools/PSCam4Win-Setup.exe', 'tools'))

added_binaries = [] + mp_binaries

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=added_binaries,
    datas=added_datas,
    hiddenimports=[
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'PySide6.QtSvg',
        'sensor',
        'sensor.camera_manager',
        'sensor.config_manager',
        'sensor.ds4_controller',
        'sensor.gesture_detector',
        'sensor.kinect_emulator',
        'sensor.kinect_shared_memory',
        'sensor.person_lock',
        'sensor.phone_camera',
        'sensor.player_slot',
        'sensor.pose_filters',
        'sensor.pose_tracker',
        'sensor.ps4_backend',
        'sensor.session_logger',
        'sensor.stereo_matcher',
        'sensor.telemetry_benchmark',
        'sensor.tracking_overlay',
        'sensor.tracking_session',
        'sensor.virtual_phone',
        'ui',
        'ui.gui_qt',
        'ui.pages',
        'ui.theme',
        'ui.icons',
        'ui.widgets',
        'ui.benchmark_dialog',
        'ui.controllers',
        'ui.controllers.camera_controller',
        'ui.controllers.device_controller',
        'ui.controllers.session_controller',
        'assets',
        'version',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'PIL.QFont',
    ] + mp_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['rthook_mediapipe.py'],
    excludes=['tkinter', 'matplotlib', 'scipy', 'unittest'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='LegacyPSCam_Sensor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=pe_version_info,
    icon=None,
)
