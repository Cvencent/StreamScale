"""Generate the Windows version resource embedded into the executable.

Why this exists
---------------
An upgrade has to decide whether the package the user just double-clicked is
newer than what is installed, and it must not start the installed copy to
find out. Windows exposes an executable's version resource without running
it, so embedding one turns "which build is this?" into a file read.

Before this existed the packaged exe carried no version at all, and the
build's version string was compressed inside the bundle where it could not
be read -- so there was no way to compare two builds.

Usage:
    python version_info.py            # writes app_version.txt for PyInstaller
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def current_version() -> str:
    """Read APP_VERSION out of tray_app.py, so there is one source of truth."""
    text = (HERE / "tray_app.py").read_text(encoding="utf-8")
    match = re.search(r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']', text, re.M)
    if not match:
        raise SystemExit("APP_VERSION not found in tray_app.py")
    return match.group(1)


def numeric_parts(version: str) -> tuple:
    """Four integers, as the version resource requires.

    Windows stores four 16-bit fields; a three-part version gets a trailing
    zero. Pre-release suffixes are ignored for the numeric fields but kept in
    the display strings, which is where a human would look.
    """
    cleaned = version.strip().lstrip("vV").split("-")[0].split("+")[0]
    parts = []
    for chunk in cleaned.split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts[:4])


def build_resource(version: str) -> str:
    a, b, c, d = numeric_parts(version)
    dotted = f"{a}.{b}.{c}.{d}"
    return f"""\
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({a}, {b}, {c}, {d}),
    prodvers=({a}, {b}, {c}, {d}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [StringStruct('CompanyName', 'StreamScale'),
         StringStruct('FileDescription', 'StreamScale tray companion'),
         StringStruct('FileVersion', '{dotted}'),
         StringStruct('InternalName', 'StreamScale'),
         StringStruct('LegalCopyright', 'MIT Licence'),
         StringStruct('OriginalFilename', 'StreamScale.exe'),
         StringStruct('ProductName', 'StreamScale'),
         StringStruct('ProductVersion', '{version}')])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def main() -> int:
    version = current_version()
    output = HERE / "app_version.txt"
    output.write_text(build_resource(version), encoding="utf-8")
    print(f"wrote {output.name} for version {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
