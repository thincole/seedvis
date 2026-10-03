# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('shopeevideo.py', '.'), ('seedvis_icon.ico', '.'), ('seedvis_logo.png', '.')]
binaries = []
hiddenimports = ['customtkinter', 'pystray', 'PIL', 'edge_tts', 'google.genai', 'groq']
tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['E:\\0 - Seedvis\\seedvis_app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['rthook_mode_seedvis.py'],
    excludes=['torch', 'torchvision', 'tensorflow', 'onnxruntime', 'scipy', 'pandas', 'numpy', 'cv2', 'matplotlib', 'sqlalchemy', 'psycopg2', 'lxml', 'av', 'google.generativeai'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Seedvis',
    icon='seedvis_icon.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Seedvis',
)
