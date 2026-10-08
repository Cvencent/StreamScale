"""Generate the Sunshine prep-cmd JSON for this machine.

Rather than asking the user to hand-edit apps.json, we print the exact
snippet to paste, with absolute paths already filled in. Editing another
program's config file directly would be fragile; printing it lets the user
review before committing.

Usage:
    python install/print_prep_cmd.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def python_executable() -> str:
    """The Python that should run StreamScale.

    Prefer a project virtualenv if present, otherwise fall back to whatever
    is running this script -- which is what the user invoked, so it is by
    definition working.
    """
    for candidate in (
        ROOT / ".venv" / "Scripts" / "python.exe",
        ROOT / ".venv" / "bin" / "python",
    ):
        if candidate.exists():
            return str(candidate)
    return sys.executable


def main() -> int:
    py = python_executable()
    src = ROOT / "src"

    # -m streamscale.cli with PYTHONPATH set works without installing the
    # package, which keeps setup to a git clone for casual users.
    apply_cmd = (
        f'"{py}" -m streamscale.cli apply'
    )
    revert_cmd = (
        f'"{py}" -m streamscale.cli revert'
    )

    snippet = {
        "prep-cmd": [
            {"do": apply_cmd, "undo": revert_cmd}
        ]
    }

    print(__doc__)
    print(f"Python : {py}")
    print(f"Source : {src}")
    print()
    print("Add this to the app you want to scale (Sunshine web UI ->")
    print("Applications -> your app -> Prep Commands), or paste it into")
    print("apps.json under that app's object:")
    print()
    print(json.dumps(snippet, indent=2, ensure_ascii=False))
    print()
    print("Also set this so the import resolves without installing:")
    print()
    print(f"    PYTHONPATH={src}")
    print()
    print("Tip: run `streamscale show` from that same environment to verify")
    print("detection before streaming.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
