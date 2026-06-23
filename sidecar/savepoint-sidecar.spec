# PyInstaller spec for the Savepoint AI sidecar (one-file executable).
#
# Force-collects:
#   - sqlite-vec's loadable extension (vec0.dll / .dylib / .so) + its data, so
#     the frozen app can still load the vector extension
#   - uvicorn's dynamically-imported submodules (loops, protocols, lifespan)
#
# Build:  uv run pyinstaller savepoint-sidecar.spec --noconfirm --clean
# Output: dist/savepoint-sidecar(.exe)

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    copy_metadata,
)

datas = collect_data_files("sqlite_vec")
binaries = collect_dynamic_libs("sqlite_vec")
hiddenimports = collect_submodules("uvicorn")

# keyring discovers OS backends via entry points — bundle the backends AND their
# package metadata, or the frozen app finds no keychain and secrets break.
hiddenimports += collect_submodules("keyring")
hiddenimports += collect_submodules("win32ctypes")
datas += copy_metadata("keyring")

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="savepoint-sidecar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # no console window when spawned in a release build
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
