# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

block_cipher = None

# Collect all required binaries, data and hidden imports for mediapipe
mp_datas, mp_binaries, mp_hiddenimports = collect_all('mediapipe')

added_datas = [
    ('models/pose_landmarker_lite.task', 'models'),
    ('assets', 'assets'),
    ('tools/PSCam4Win-Setup.exe', 'tools'),
    ('tools/get_cameras.ps1', 'tools'),
] + mp_datas

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
        'sensor',
        'ui',
        'assets',
        'version',
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
