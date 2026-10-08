"""One-command build: venv, dependencies, icon, PyInstaller, copy out.

Exists so the build is repeatable without anyone having to remember the
flags, and so the icon is always regenerated from tray_icons.py rather than
being a stale binary someone forgot to update.

Usage:
    cd runtime
    python build.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
VENV = HERE / ".buildvenv"
EXE_NAME = "StreamScale.exe"
DEPENDENCIES = ["pillow", "pystray", "pyinstaller"]


def run(args, **kwargs) -> None:
    print(f"  $ {' '.join(str(a) for a in args)}")
    subprocess.run([str(a) for a in args], check=True, **kwargs)


def venv_python() -> Path:
    candidate = VENV / "Scripts" / "python.exe"
    if candidate.exists():
        return candidate
    candidate = VENV / "bin" / "python"          # non-Windows, for completeness
    return candidate


def ensure_venv() -> Path:
    python = venv_python()
    if python.exists():
        print(f"  reusing {VENV}")
        return python

    print("  checking tkinter (required by the settings window)")
    probe = subprocess.run(
        [sys.executable, "-c", "import tkinter; print(tkinter.TkVersion)"],
        capture_output=True, text=True,
    )
    if probe.returncode != 0:
        raise SystemExit(
            "This Python has no tkinter, so the settings window cannot work.\n"
            "Use the python.org installer, or install the tcl/tk package."
        )
    print(f"  tkinter {probe.stdout.strip()}")

    print(f"  creating {VENV}")
    run([sys.executable, "-m", "venv", str(VENV)])
    return venv_python()


def install_dependencies(python: Path) -> None:
    print("  installing dependencies")
    run([python, "-m", "pip", "install", "--quiet", "--upgrade", "pip"])
    run([python, "-m", "pip", "install", "--quiet", *DEPENDENCIES])


def regenerate_icon(python: Path) -> None:
    print("  regenerating icon from tray_icons.py")
    code = (
        "import sys; sys.path.insert(0, r'%s');"
        "import tray_icons; tray_icons.make_ico(r'%s', 'active');"
        "print('    icon written')" % (HERE, HERE / "app.ico")
    )
    run([python, "-c", code])


def build(python: Path) -> Path:
    print("  running PyInstaller")
    run([python, "-m", "PyInstaller", "--noconfirm", "--clean",
         str(HERE / "StreamScale.spec")], cwd=str(HERE))

    built = HERE / "dist" / EXE_NAME
    if not built.exists():
        raise SystemExit(f"build produced no executable at {built}")
    return built


def main() -> int:
    print("StreamScale build")
    print("=" * 56)

    python = ensure_venv()
    install_dependencies(python)
    regenerate_icon(python)
    built = build(python)

    target = PROJECT / EXE_NAME
    shutil.copy2(built, target)
    size_mb = target.stat().st_size / (1024 * 1024)

    print()
    print("=" * 56)
    print(f"  {target}")
    print(f"  {size_mb:.1f} MB")
    print()
    print("  Verify before shipping:")
    print("    .buildvenv\\Scripts\\python.exe _smoke_exe.py")
    print("    .buildvenv\\Scripts\\python.exe _e2e_exe.py")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
