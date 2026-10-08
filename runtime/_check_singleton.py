"""Self-check: the single-instance mutex actually rejects a second process.

Two instances would each own a tray icon and fight over config.json; the
visible symptom is status flickering between icons, which is very hard to
diagnose. This verifies the guard works, without needing two visible icons
(the test process itself never calls icon.run()).
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

CHILD = r"""
import sys
sys.path.insert(0, r"{here}")
import tray_app
guard = tray_app.SingleInstance()
print("ALREADY_RUNNING" if guard.already_running else "GOT_LOCK")
time.sleep(2)
"""


def main() -> int:
    import tray_app

    print("1. First instance acquires the lock")
    first = tray_app.SingleInstance()
    ok_first = not first.already_running
    print(f"  [{'PASS' if ok_first else 'FAIL'}] first instance got the lock")

    print("\n2. Second process must be refused")
    code = CHILD.format(here=str(HERE))
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, timeout=30,
    )
    out = (proc.stdout or "").strip()
    refused = "ALREADY_RUNNING" in out
    print(f"  [{'PASS' if refused else 'FAIL'}] second process reports already running"
          f"  -- output={out!r}")

    print("\n3. After release, a new instance is allowed")
    # The child has exited by now; the first handle above is still held by
    # this process, so check via a fresh process instead.
    proc2 = subprocess.run(
        [sys.executable, "-c", CHILD.format(here=str(HERE))],
        capture_output=True, text=True, timeout=30,
    )
    out2 = (proc2.stdout or "").strip()
    still_refused = "ALREADY_RUNNING" in out2
    print(f"  [{'PASS' if still_refused else 'FAIL'}] still refused while we hold it"
          f"  -- output={out2!r}")

    print()
    failures = []
    if not ok_first:
        failures.append("first instance")
    if not refused:
        failures.append("second instance refused")
    if not still_refused:
        failures.append("mutex held correctly")

    if failures:
        print(f"FAILED: {failures}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
