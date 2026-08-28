# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_all
from stock_tool.version_resource import write_version_resource

version_resource = write_version_resource(Path('build') / 'stocktool-version-info.txt')

datas = [('.streamlit\\config.toml', '.streamlit'), ('src\\stock_tool\\dashboard\\app.py', 'stock_tool\\dashboard'), ('src\\stock_tool\\data\\migrations', 'stock_tool\\data\\migrations'), ('src\\stock_tool\\application\\official_trading_calendars.json', 'stock_tool\\application')]
binaries = []
hiddenimports = ['stock_tool.dashboard.app', 'stock_tool.runtime_paths']
tmp_ret = collect_all('streamlit')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['launcher.py'],
    pathex=['src'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='StockToolPayload',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=str(version_resource),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='StockToolPayload',
)
