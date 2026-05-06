# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for Teams Recorder.
# Build with:  pyinstaller build.spec
#
# Place ffmpeg.exe in the project root before building;
# it will be copied to the output dist/TeamsRecorder/ folder.

import os
from pathlib import Path

ROOT = Path(SPECPATH)

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "assets"), "assets"),
    ],
    hiddenimports=[
        "pyaudiowpatch",
        "pycaw",
        "pycaw.pycaw",
        "comtypes",
        "comtypes.client",
        "plyer",
        "plyer.platforms.win.notification",
        "soundfile",
        "samplerate",
        "numpy",
        "pydub",
        "pystray",
        "PIL",
        "PIL.Image",
        "PIL.ImageDraw",
        "tkinter",
        "tkinter.ttk",
        "tkinter.filedialog",
        "tkinter.messagebox",
        "winreg",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "scipy", "pandas", "IPython"],
    noarchive=False,
)

# Bundle ffmpeg.exe if present in project root
ffmpeg_src = ROOT / "ffmpeg.exe"
if ffmpeg_src.exists():
    a.binaries += [("ffmpeg.exe", str(ffmpeg_src), "BINARY")]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TeamsRecorder",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # no console window
    icon=str(ROOT / "assets" / "icon_idle.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="TeamsRecorder",
)
