# -*- mode: python ; coding: utf-8 -*-
# Spec de PyInstaller: build one-dir (arranque rapido, seccion 15 del plan).
# Uso: pyinstaller --clean scripts/port-forwarder.spec

import os

block_cipher = None

a = Analysis(
    ["../scripts/entry_point.py"],
    pathex=[os.path.dirname(os.path.dirname(os.path.abspath(SPECPATH)))],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pystray", "PIL", "ttkbootstrap", "winotify"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="port-forwarder",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="port-forwarder",
)
