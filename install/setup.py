"""One-time setup: create the launcher and print the prep-cmd to paste.

Run this once after cloning:

    python install/setup.py

It writes `streamscale.bat` next to the project root and prints the exact
JSON snippet for Sunshine. Nothing outside the project folder is touched.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = ROOT / "src"
LAUNCHER = ROOT / "streamscale.bat"
TEMPLATE = HERE / "streamscale.bat.template"


def python_executable() -> str:
    """Pick the Python that will run StreamScale.

    A project virtualenv wins so the install stays isolated; otherwise the
    interpreter running this script is used, which by definition works.
    """
    for candidate in (
        ROOT / ".venv" / "Scripts" / "python.exe",
        ROOT / ".venv" / "bin" / "python",
    ):
        if candidate.exists():
            return str(candidate)
    return sys.executable


def write_launcher(py: str) -> Path:
    text = TEMPLATE.read_text(encoding="utf-8")
    text = text.replace("__SRC__", str(SRC)).replace("__PYTHON__", py)
    # CRLF: cmd.exe misparses bare LF in some locales, and the file must
    # survive being edited on Windows.
    text = text.replace("\r\n", "\n").replace("\n", "\r\n")
    # The template is ASCII-only on purpose -- cmd.exe reads .bat using the
    # system ANSI codepage, so non-ASCII comments corrupt the file.
    LAUNCHER.write_text(text, encoding="ascii")
    return LAUNCHER


def main() -> int:
    py = python_executable()

    if not SRC.exists():
        print(f"ERROR: expected source at {SRC}", file=sys.stderr)
        return 1

    bat = write_launcher(py)
    print("StreamScale setup")
    print("=" * 56)
    print(f"Python   : {py}")
    print(f"Source   : {SRC}")
    print(f"Launcher : {bat}")
    print()

    snippet = {
        "prep-cmd": [
            {"do": f'"{bat}" apply', "undo": f'"{bat}" revert'}
        ]
    }
    print("Paste this into the app entry in the Sunshine web UI")
    print("(Applications -> your app -> Prep Commands):")
    print()
    print(json.dumps(snippet, indent=2, ensure_ascii=False))
    print()
    print("Then verify detection, without changing anything:")
    print()
    print(f'    "{bat}" show')
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
