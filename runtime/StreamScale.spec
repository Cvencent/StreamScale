# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the StreamScale tray app.

Why onedir and not onefile
--------------------------
onefile packs everything into a single exe, but unpacks that payload into a
temporary directory on *every* run and deletes it afterwards. Measured on
this project:

    onefile   25 s per start   (two of these per stream: apply and revert)
    onedir     0.2 s per start

Sunshine waits for its prep-command to exit, so a 25-second start is not
just slow, it is a correctness problem -- it used to look like a hang. Onedir
leaves the files unpacked, so only the interpreter start remains. The cost
moves to install time, which is paid once per version:

    40 MB, 1020 files, ~1.4 s to copy

That trade is clearly worth it.

Notes that matter:

* The tray needs the `streamscale` package at runtime -- the Settings tab
  reads the adapter registry to list supported games. The package lives at
  ../src/streamscale and is added to `datas` so it is importable from inside
  the bundle. PyInstaller cannot discover this: the import is inside a
  try/except that builds the path from sys._MEIPASS.

* `pystray._win32` must be listed explicitly. pystray selects its backend by
  importing a module name built at runtime, which static analysis cannot
  follow; without this line the tray silently fails to find a backend.

* tkinter is not excluded. It is what the Settings window uses, and the
  default PyInstaller hook already pulls in the tcl/tk runtime.

* console=False: this is a tray app, a console window would be wrong. The
  app redirects stdout to a log file, so nothing is lost.
"""

from pathlib import Path

runtime = Path(SPECPATH)
project = runtime.parent

# Ship the CLI package so the Settings tab can enumerate adapters.
streamscale_src = project / "src" / "streamscale"

datas = []
if streamscale_src.exists():
    datas.append((str(streamscale_src), "streamscale"))

# The generated launcher is useful to have alongside the exe, though the
# tray can rebuild the command itself if it is missing.
launcher = project / "streamscale.bat"
if launcher.exists():
    datas.append((str(launcher), "."))

icon = runtime / "app.ico"

# A version resource is what lets an upgrade compare builds without running
# them. Generated from APP_VERSION so there is one source of truth.
version_file = runtime / "app_version.txt"
if not version_file.exists():
    import subprocess
    subprocess.run([sys.executable, str(runtime / "version_info.py")],
                   cwd=str(runtime), check=False)

hiddenimports = [
    "pystray._win32",
    "PIL.Image",
    "PIL.ImageDraw",
    # Pulled in lazily by the settings window, the process watcher and the
    # updater. None of these are reachable by static analysis.
    "streamscale.registry",
    "streamscale.games.brotato",
    "updater",
    "version_info",
]

excludes = [
    # Keep the bundle small; none of these are used.
    "numpy", "scipy", "pandas", "matplotlib",
    "pytest", "setuptools", "pip",
    "unittest", "test",
    # Other pystray backends are irrelevant on Windows.
    "pystray._appindicator", "pystray._gtk", "pystray._darwin",
]

a = Analysis(
    [str(runtime / "tray_app.py")],
    pathex=[str(runtime), str(project / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="StreamScale",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,          # tray app: no console window
    disable_windowed_traceback=False,
    version=str(version_file) if version_file.exists() else None,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon) if icon.exists() else None,
)

# onedir: the payload stays unpacked beside the exe, so a start costs only
# the interpreter boot instead of a 19 MB extraction.
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="StreamScale",
)
