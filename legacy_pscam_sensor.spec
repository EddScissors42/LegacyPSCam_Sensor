# -*- mode: python ; coding: utf-8 -*-
import os
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

BASE_DIR = Path(SPECPATH).resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
from version import __version__, APP_NAME, VERSION_STRING

BUILD_MODE = os.environ.get("LEGACY_BUILD_MODE", "onefile").strip().lower()
IS_ONEDIR = BUILD_MODE == "onedir"

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
                        StringStruct("CompanyName", "LegacyPSCam"),
                        StringStruct("FileDescription", "LegacyPSCam"),
                        StringStruct("FileVersion", f"{__version__}.0"),
                        StringStruct("InternalName", "LegacyPSCam"),
                        StringStruct("LegalCopyright", "Open Source — Legacy PSCam Sensor Contributors"),
                        StringStruct("OriginalFilename", "LegacyPSCam.exe"),
                        StringStruct("ProductName", "LegacyPSCam"),
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

# Option 1B: Bundle Lite AI offline (5.5 MB); Full AI (9.0 MB) downloads on-demand into %APPDATA%\LegacyPSCam_Sensor\models\
added_datas = [
    (str(BASE_DIR / 'models' / 'pose_landmarker_lite.task'), 'models'),
    (str(BASE_DIR / 'assets'), 'assets'),
    (str(BASE_DIR / 'tools' / 'Legacy10.dll'), 'tools'),
    (str(BASE_DIR / 'tools' / 'Legacy10_x64.dll'), 'tools'),
    (str(BASE_DIR / 'tools' / 'get_cameras.ps1'), 'tools'),
    (str(BASE_DIR / 'driver' / 'legacy_pscam_device.inf'), 'driver'),
] + mp_datas

if (BASE_DIR / 'tools' / 'PSCam4Win-Setup.exe').exists():
    added_datas.append((str(BASE_DIR / 'tools' / 'PSCam4Win-Setup.exe'), 'tools'))

added_binaries = [] + mp_binaries

a = Analysis(
    [str(BASE_DIR / 'main.py')],
    pathex=[str(BASE_DIR)],
    binaries=added_binaries,
    datas=added_datas,
    hiddenimports=[
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'PySide6.QtSvg',
        'sensor',
        'sensor.body_mask',
        'sensor.camera_capture',
        'sensor.camera_manager',
        'sensor.camera_win32',
        'sensor.config_manager',
        'sensor.ds4_controller',
        'sensor.framebus_reader',
        'sensor.gesture_detector',
        'sensor.kinect_emulator',
        'sensor.kinect_shared_memory',
        'sensor.model_manager',
        'sensor.person_lock',
        'sensor.phone_camera',
        'sensor.qr_encoder',
        'sensor.tls_manager',
        'sensor.player_reid',
        'sensor.player_slot',
        'sensor.pose_filters',
        'sensor.pose_tracker',
        'sensor.ps4_backend',
        'sensor.ps4_backend.constants',
        'sensor.ps4_backend.driver_installer',
        'sensor.ps4_backend.firmware_manager',
        'sensor.ps4_backend.frame_streamer',
        'sensor.ps4_backend.usb_device',
        'sensor.ps4_backend.winusb_bindings',
        'sensor.session_logger',
        'sensor.stereo_matcher',
        'sensor.telemetry_benchmark',
        'sensor.tracking_overlay',
        'sensor.tracking_session',
        'sensor.virtual_phone',
        'sensor.vphone_protocol',
        'ui',
        'ui.gui_qt',
        'ui.pages',
        'ui.pages.video_page',
        'ui.pages.tracking_page',
        'ui.pages.experimental_page',
        'ui.pages.ds4_page',
        'ui.styles',
        'ui.mixins',
        'ui.mixins.device_readout',
        'ui.mixins.camera_handlers',
        'ui.mixins.phone_handlers',
        'ui.mixins.ds4_vphone_handlers',
        'ui.mixins.tracking_handlers',
        'ui.theme',
        'ui.icons',
        'ui.widgets',
        'ui.benchmark_dialog',
        'ui.controllers',
        'ui.controllers.app_controller',
        'ui.controllers.camera_controller',
        'ui.controllers.device_controller',
        'ui.controllers.session_controller',
        'assets',
        'version',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'PIL.ImageFont',
    ] + mp_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(BASE_DIR / 'rthook_mediapipe.py')],
    excludes=[
        'tkinter',
        'matplotlib',
        'scipy',
        'unittest',
        'sounddevice',
        '_sounddevice_data',
        'websockets',
        'PySide6.QtQml',
        'PySide6.QtQuick',
        'PySide6.QtPdf',
        'PySide6.QtNetwork',
        'PySide6.QtOpenGL',
        'PySide6.QtSql',
        'PySide6.QtTest',
        'PySide6.QtWebEngine',
        'PySide6.QtMultimedia',
        'PySide6.Qt3DCore',
        'PIL.AvifImagePlugin',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Surgical pruning of unused heavy DLLs/plugins (~92 MB uncompressed saved on every launch)
_PRUNE_SUBSTRINGS = (
    'opencv_videoio_ffmpeg',
    'opengl32sw.dll',
    'qt6quick',
    'qt6qml',
    'qt6pdf',
    'qt6opengl',
    'qt6network',
    'qtnetwork.pyd',
    'qdirect2d.dll',
    'qtiff.dll',
    'qwebp.dll',
    'pil/_avif',
    'pil\\_avif',
    '_sounddevice_data',
    'websockets',
    'dmsans.ttf',
    '__pycache__',
    '.pyc',
    'licenses/notice',
)


def _should_keep(entry) -> bool:
    dest = str(entry[0]).replace('\\', '/').lower()
    src = str(entry[1]).replace('\\', '/').lower() if len(entry) > 1 else ''
    return not any(tok in dest or tok in src for tok in _PRUNE_SUBSTRINGS)


a.binaries = [b for b in a.binaries if _should_keep(b)]
a.datas = [d for d in a.datas if _should_keep(d)]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
_icon_file = BASE_DIR / 'assets' / 'icons' / 'app_icon.ico'
icon_path = str(_icon_file) if _icon_file.exists() else None

# Generate build-time splash inside build/ so tracked assets/icons/splash.png is never dirtied
_build_splash = BASE_DIR / 'build' / 'splash.png'
_fallback_splash = BASE_DIR / 'assets' / 'icons' / 'splash.png'
splash_path = str(_fallback_splash)
try:
    from tools.generate_splash import generate_splash
    _build_splash.parent.mkdir(parents=True, exist_ok=True)
    generate_splash(_build_splash)
    splash_path = str(_build_splash)
except Exception as _splash_err:
    print(f"[WARN] Could not regenerate splash screen automatically: {_splash_err}")

if IS_ONEDIR:
    # Fast-launch Portable Folder build (< 1s startup, zero %TEMP% re-extraction)
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name='LegacyPSCam',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        version=pe_version_info,
        icon=icon_path,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name='LegacyPSCam',
    )
else:
    # Slim Single-File Executable with instant PlayStation Blue boot Splash Screen
    splash_args = []
    if Path(splash_path).exists():
        splash = Splash(
            splash_path,
            binaries=a.binaries,
            datas=a.datas,
            text_pos=None,
            text_size=12,
            minify_script=True,
            always_on_top=True,
        )
        splash_args = [splash, splash.binaries]

    exe = EXE(
        pyz,
        a.scripts,
        *splash_args,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name='LegacyPSCam',
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
        icon=icon_path,
    )
