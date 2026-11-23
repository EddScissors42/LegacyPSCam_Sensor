# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

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
    icon=None,
)
