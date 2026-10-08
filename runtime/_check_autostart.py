"""Self-check: autostart registry round-trip.

Writes, reads back, and removes the HKCU Run entry, restoring whatever was
there before. HKCU needs no administrator rights, so this runs anywhere.

The test deliberately restores the original state: leaving an autostart
entry behind would be a surprising side effect of running a self-check.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def main() -> int:
    import tray_app

    failures = []

    print("1. Read current state")
    original = tray_app.autostart_enabled()
    print(f"   autostart currently: {original}")

    print("\n2. Command path looks sane")
    cmd = tray_app._command_path()
    looks_ok = "StreamScale" in cmd or "tray_app" in cmd
    print(f"  [{'PASS' if looks_ok else 'FAIL'}] {cmd}")
    if not looks_ok:
        failures.append("command path")

    print("\n3. Enable -> should read back True")
    tray_app.set_autostart(True)
    enabled = tray_app.autostart_enabled()
    print(f"  [{'PASS' if enabled else 'FAIL'}] enabled={enabled}")
    if not enabled:
        failures.append("enable")

    print("\n4. Disable -> should read back False")
    tray_app.set_autostart(False)
    disabled = tray_app.autostart_enabled()
    print(f"  [{'PASS' if not disabled else 'FAIL'}] enabled={disabled}")
    if disabled:
        failures.append("disable")

    print("\n5. Restore original state")
    tray_app.set_autostart(original)
    restored = tray_app.autostart_enabled()
    ok = restored == original
    print(f"  [{'PASS' if ok else 'FAIL'}] restored={restored} (was {original})")
    if not ok:
        failures.append("restore")

    print()
    if failures:
        print(f"FAILED: {failures}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
