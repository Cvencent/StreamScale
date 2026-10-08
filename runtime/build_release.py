"""Build the distributable package.

Produces a zip the user extracts over their existing install. Onedir means
"the app" is a folder, so the artefact is an archive of that folder rather
than a lone exe.

A short version marker is written into the archive as well. It is not what
the upgrade checks -- that reads the exe's version resource, which cannot be
spoofed by an unzipped file -- but it makes a downloaded package
self-describing for anyone inspecting it.

Usage:
    python build_release.py
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
VENV_PYTHON = HERE / ".buildvenv" / "Scripts" / "python.exe"


def app_version() -> str:
    text = (HERE / "tray_app.py").read_text(encoding="utf-8")
    match = re.search(r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']', text, re.M)
    if not match:
        raise SystemExit("APP_VERSION not found in tray_app.py")
    return match.group(1)


def build() -> Path:
    """Run PyInstaller and return the onedir output folder."""
    subprocess.run([sys.executable, str(HERE / "version_info.py")],
                   cwd=str(HERE), check=True)

    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         str(HERE / "StreamScale.spec")],
        cwd=str(HERE), capture_output=True, text=True, timeout=1800)
    if result.returncode != 0:
        print(result.stdout[-3000:])
        print(result.stderr[-3000:])
        raise SystemExit("PyInstaller failed")

    folder = HERE / "dist" / "StreamScale"
    if not folder.exists():
        raise SystemExit(f"expected onedir output at {folder}")
    return folder


def package(folder: Path, version: str) -> Path:
    """Zip the folder, with a version marker inside."""
    marker = folder / "version.json"
    marker.write_text(json.dumps({
        "product": "StreamScale",
        "version": version,
        "layout": "onedir",
    }, indent=2), encoding="utf-8")

    archive = HERE / "dist" / f"StreamScale-{version}.zip"
    files = [f for f in folder.rglob("*") if f.is_file()]
    total = sum(f.stat().st_size for f in files)

    print(f"packaging {len(files)} files, {total/1048576:.1f} MB uncompressed")

    start = time.time()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in files:
            zf.write(path, path.relative_to(folder))
    elapsed = time.time() - start

    size = archive.stat().st_size / 1048576
    print(f"  {archive.name}: {size:.1f} MB in {elapsed:.1f}s")
    return archive


def main() -> int:
    version = app_version()
    print(f"building StreamScale {version}")
    print()

    folder = build()
    print()

    # Confirm the exe inside carries its version resource, since an upgrade
    # has nothing to compare without it. Re-imported here because the module
    # reads APP_VERSION at import time.
    sys.path.insert(0, str(HERE))
    import importlib
    updater = importlib.import_module("updater")
    exe = folder / "StreamScale.exe"
    stamped = updater.read_exe_version(exe)
    if not stamped:
        raise SystemExit(
            "the built exe has no version resource; an upgrade could not "
            "tell it apart from another build")
    print(f"version resource: {stamped}")
    print()

    archive = package(folder, version)
    print()
    print("done:")
    print(f"  folder  {folder}")
    print(f"  archive {archive}")
    print()
    print("the user extracts the archive over their existing install; the")
    print("tray picks up the new build on its next start.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
