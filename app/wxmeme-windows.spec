# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for wxmeme standalone Windows app."""

from pathlib import Path

root = Path(SPECPATH).parent
entry = root / "app" / "entry.py"

a = Analysis(
    [str(entry)],
    pathex=[str(root / "exporter"), str(root / "app")],
    binaries=[],
    datas=[
        (str(root / "exporter"), "exporter"),
        (str(root / "scripts"), "scripts"),
        (str(root / "app" / "gui.py"), "app"),
        (str(root / "app" / "paths.py"), "app"),
        (str(root / "app" / "webview_ui.py"), "app"),
        (str(root / "app" / "platform_utils.py"), "app"),
    ],
    hiddenimports=[
        "Crypto",
        "Crypto.Cipher",
        "Crypto.Cipher.AES",
        "wechat_crypto",
        "wcdb_extract",
        "wxmeme",
        "gui",
        "paths",
        "webview",
        "webview_ui",
        "platform_utils",
        "pythonnet",
        "clr_loader",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["mac_seed_scan"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="wxmeme",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="wxmeme-standalone",
)
