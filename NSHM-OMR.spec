# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


root = Path(SPECPATH)

a = Analysis(
    [str(root / "desktop_launcher.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[
        (str(root / "assets"), "assets"),
        (str(root / "static"), "static"),
        (str(root / "templates"), "templates"),
    ],
    hiddenimports=["fitz", "cv2", "PIL"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "IPython",
        "jupyter",
        "notebook",
        "pandas",
        "scipy",
        "torch",
        "tensorflow",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "sklearn",
    ],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NSHM OMR",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(root / "build_assets" / "NSHM-OMR.icns"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="NSHM OMR",
)
app = BUNDLE(
    coll,
    name="NSHM OMR.app",
    icon=str(root / "build_assets" / "NSHM-OMR.icns"),
    bundle_identifier="vn.edu.nshm.omr",
    info_plist={
        "CFBundleDisplayName": "NSHM OMR",
        "CFBundleShortVersionString": "1.0.4",
        "CFBundleVersion": "4",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "12.0",
    },
)
