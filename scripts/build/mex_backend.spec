# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for MEX Backend API
Comprehensive bundling with all dependencies audited
"""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules
import os
import sys
from pathlib import Path

# In PyInstaller spec files, use SPECPATH instead of __file__
# SPECPATH is scripts/build, so go up 2 directories to reach project root
project_root = Path(SPECPATH).parent.parent

# Platform detection for executable naming
IS_WINDOWS = sys.platform == 'win32'
EXE_EXTENSION = '.exe' if IS_WINDOWS else ''

# =============================================================================
# THIRD-PARTY PACKAGES (hiddenimports)
# =============================================================================

hiddenimports = [
    # Flask ecosystem
    'flask',
    'flask_cors',
    'flask_socketio',
    'socketio',
    'engineio',
    'werkzeug',
    'werkzeug.utils',
    'jinja2',
    'click',
    'itsdangerous',
    'markupsafe',

    # WebSocket support with all backends
    'simple_websocket',
    'wsproto',
    'h11',

    # Threading support for SocketIO
    'threading',
    'queue',

    # EngineIO threading backend - CRITICAL for PyInstaller
    'engineio.async_drivers',
    'engineio.async_drivers.threading',
    'engineio.async_threading',

    # DNS (flask-socketio dependency)
    'dns',
    'dns.resolver',

    # Logging
    'logging.handlers',

    # Image processing
    'PIL',
    'PIL.Image',
    'PIL.ImageOps',
    'PIL.ImageDraw',
    'PIL.ImageFont',
    'PIL.ImageEnhance',
    'PIL.ImageStat',

    # NumPy for image processing
    'numpy',

    # YAML parsing
    'yaml',

    # Compression
    'zipfile',
    'py7zr',  # Optional 7z support

    # JSON/Data
    'json',

    # Backend modules (from backend/)
    'backend.character_detector',
    'backend.stage_detector',
    'backend.mex_api',

    # MexBridge - CRITICAL module
    'mex_bridge',

    # Utility modules (dynamically imported)
    'generate_csp',
    'generate_stock_icon',
    'detect_character',
    'validate_costume',
    'dat_processor',
]

# =============================================================================
# PATH SETUP
# =============================================================================

# Add paths for module discovery
additional_paths = [
    str(project_root / 'backend'),
    str(project_root / 'utility' / 'website' / 'backend' / 'tools' / 'processor'),
    str(project_root / 'utility' / 'website' / 'backend' / 'app' / 'services'),
    str(project_root / 'utility' / 'website' / 'backend' / 'app' / 'utils'),
]

# =============================================================================
# DATA FILES (datas)
# =============================================================================

datas = []

# Python modules from utility (must be bundled as source)
utility_modules = [
    ('utility/website/backend/tools/processor/*.py', 'utility/website/backend/tools/processor'),
    ('utility/website/backend/app/services/*.py', 'utility/website/backend/app/services'),
    ('utility/website/backend/app/utils/*.py', 'utility/website/backend/app/utils'),
]

for src_pattern, dst_folder in utility_modules:
    import glob
    for py_file in glob.glob(str(project_root / src_pattern)):
        datas.append((py_file, dst_folder))

# CSP generation data (character assets)
csp_data_path = project_root / 'utility' / 'website' / 'backend' / 'tools' / 'processor' / 'csp_data'
if csp_data_path.exists():
    datas.append((str(csp_data_path), 'utility/website/backend/tools/processor/csp_data'))

# HSDRawViewer and dependencies (entire directory needed for .NET app)
hsdraw_dir = project_root / 'utility' / 'website' / 'backend' / 'tools' / 'HSDLib' / 'HSDRawViewer' / 'bin' / 'Release' / 'net6.0-windows'
if hsdraw_dir.exists():
    datas.append((str(hsdraw_dir), 'utility/website/backend/tools/HSDLib/HSDRawViewer/bin/Release/net6.0-windows'))

# Costume validator
validator_dir = project_root / 'utility' / 'website' / 'backend' / 'tools' / 'processor' / 'CostumeValidator'
if validator_dir.exists():
    datas.append((str(validator_dir), 'utility/website/backend/tools/processor/CostumeValidator'))

# Vanilla assets (character-specific)
vanilla_dir = project_root / 'utility' / 'assets' / 'vanilla'
if vanilla_dir.exists():
    datas.append((str(vanilla_dir), 'utility/assets/vanilla'))

# Build assets (numbered CSPs and stock icons used by MEX)
build_assets_dir = project_root / 'build' / 'assets'
if build_assets_dir.exists():
    datas.append((str(build_assets_dir), 'build/assets'))

# Dynamic Alternate Stages framework
das_dir = project_root / 'utility' / 'DynamicAlternateStages'
if das_dir.exists():
    datas.append((str(das_dir), 'utility/DynamicAlternateStages'))

# =============================================================================
# BINARIES
# =============================================================================

binaries = []

# Note: .NET executables (mexcli.exe, HSDRawViewer.exe) are included in datas
# They will be bundled in electron-builder separately with their full runtime

# =============================================================================
# ANALYSIS
# =============================================================================

a = Analysis(
    [str(project_root / 'backend' / 'mex_api.py'),
     str(project_root / 'scripts' / 'tools' / 'mex_bridge.py')],
    pathex=additional_paths,
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude heavy packages not needed
        'matplotlib',
        'scipy',
        'pandas',
        'tkinter',
        '_tkinter',
        'PyQt5',
        'PyQt6',
        'notebook',
        'IPython',
        'jupyter',

        # Test frameworks (not needed in production)
        'pytest',
        'pytest-flask',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

# =============================================================================
# BUNDLE
# =============================================================================

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=f'mex_backend{EXE_EXTENSION}',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # No console window - runs in background
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
