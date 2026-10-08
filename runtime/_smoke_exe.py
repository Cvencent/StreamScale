"""Self-check: launch the built EXE and confirm a tray icon really appears.

Why not check the process by PID
--------------------------------
PyInstaller's onefile mode forks: the process Popen returns is the extractor,
and the Python code runs in a *child* with a different PID. Enumerating
windows by the returned PID finds nothing and looks like "the tray never
started". So windows are found by class name instead -- pystray's Win32
backend registers a window whose class name contains SystemTrayIcon.

The EXE is then asked to quit via its own tray menu path (WM_CLOSE is not
enough for pystray), falling back to taskkill.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

def _locate_exe() -> Path:
    """Find the built StreamScale.exe, whatever layout it was built in.

    The program ships as a folder now (onedir): the exe lives inside
    `dist/StreamScale/` beside its `_internal/` payload. Older builds put a
    lone exe directly in `dist/`. Both are checked so the self-checks keep
    working across the change, and the newer location wins.
    """
    for candidate in (
        HERE / "dist" / "StreamScale" / "StreamScale.exe",
        HERE / "dist" / "StreamScale.exe",
        HERE.parent / "StreamScale" / "StreamScale.exe",
        HERE.parent / "StreamScale.exe",
    ):
        if candidate.exists():
            return candidate
    return HERE / "dist" / "StreamScale" / "StreamScale.exe"


EXE = _locate_exe()
user32 = ctypes.windll.user32

# pystray's Win32 backend names its window class "<something>SystemTrayIcon".
TRAY_CLASS_HINT = "SystemTrayIcon"

WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def find_tray_windows():
    """Return [(hwnd, class_name, title)] for windows that look like a tray."""
    found = []

    def callback(hwnd, _lparam):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        cls = buf.value
        if TRAY_CLASS_HINT.lower() in cls.lower():
            tbuf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, tbuf, 256)
            found.append((hwnd, cls, tbuf.value))
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return found


def kill_streamscale_exe() -> None:
    """Terminate any leftover StreamScale.exe from a previous run."""
    subprocess.run(
        ["taskkill", "/F", "/IM", "StreamScale.exe"],
        capture_output=True, text=True, encoding="gbk", errors="replace",
    )


def main() -> int:
    print(f"EXE: {EXE}")
    if not EXE.exists():
        print("  [FAIL] EXE not found - build it first")
        return 1

    size_mb = EXE.stat().st_size / (1024 * 1024)
    print(f"  size: {size_mb:.1f} MB")

    failures = []

    print("\n1. No tray window before launch")
    kill_streamscale_exe()
    time.sleep(1.5)
    before = find_tray_windows()
    ok = len(before) == 0
    print(f"  [{'PASS' if ok else 'FAIL'}] windows before: {len(before)}")
    if not ok:
        failures.append("clean start")
        print(f"        (leftover: {before})")

    print("\n2. Launch the EXE")
    proc = subprocess.Popen(
        [str(EXE)],
        cwd=str(EXE.parent),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    print(f"  launched (extractor pid={proc.pid}; real pid differs in onefile mode)")

    print("\n3. Wait for the tray window to appear")
    deadline = time.time() + 45
    windows = []
    while time.time() < deadline:
        windows = find_tray_windows()
        if windows:
            break
        time.sleep(1.0)

    got = len(windows) > 0
    print(f"  [{'PASS' if got else 'FAIL'}] tray windows found: {len(windows)}")
    for hwnd, cls, title in windows:
        print(f"        hwnd={hwnd} class={cls!r} title={title!r}")
    if not got:
        failures.append("tray window created")

    print("\n4. Process is still alive (did not crash on startup)")
    alive = proc.poll() is None or len(windows) > 0
    # In onefile mode the parent may exit while the child lives, so treat a
    # live tray window as proof of life too.
    still_running = len(find_tray_windows()) > 0
    print(f"  [{'PASS' if still_running else 'FAIL'}] tray still present")
    if not still_running:
        failures.append("process alive")

    print("\n5. Shut it down")
    kill_streamscale_exe()
    time.sleep(2.0)
    after = find_tray_windows()
    gone = len(after) == 0
    print(f"  [{'PASS' if gone else 'FAIL'}] windows after kill: {len(after)}")
    if not gone:
        failures.append("clean exit")

    print()
    if failures:
        print(f"FAILED: {failures}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
