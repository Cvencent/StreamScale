"""Self-check: the EXE detects a real stream, end to end.

This is the only test that proves the business logic works *inside the
bundle* -- imports resolved, the monitor thread runs, the state machine
reacts. Everything else can pass while the packaged app is subtly broken.

Isolation
---------
The test runs the EXE against a scratch log file and scratch config, via:

    STREAMSCALE_SUNSHINE_LOG   fake session log
    STREAMSCALE_LOG_DIR        where the tray writes its own log

Nothing under Program Files or the real APPDATA is read or written. An
earlier version appended to the real sunshine.log and hit a permission
error -- which was the right outcome, and is why the overrides exist.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
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
WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def tray_windows():
    found = []

    def cb(hwnd, _l):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        if "SystemTrayIcon" in buf.value:
            found.append(hwnd)
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return found


def kill_exe():
    subprocess.run(["taskkill", "/F", "/IM", "StreamScale.exe"],
                   capture_output=True, text=True, encoding="gbk", errors="replace")


def main() -> int:
    failures = []

    if not EXE.exists():
        print(f"[FAIL] EXE not found: {EXE}")
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        fake_log = tmp / "sunshine.log"
        log_dir = tmp / "logdir"
        log_dir.mkdir(parents=True, exist_ok=True)
        tray_log = log_dir / "tray.log"

        # Something already in the file: the monitor must ignore history and
        # only react to what happens after it starts.
        fake_log.write_text(
            "[old] CLIENT CONNECTED\n[old] CLIENT DISCONNECTED\n", encoding="utf-8")

        print(f"scratch log : {fake_log}")
        print(f"tray log    : {tray_log}")

        print("\n1. Clean slate")
        kill_exe()
        time.sleep(1.5)

        print("\n2. Start the EXE against the scratch log")
        env = dict(os.environ)
        env["STREAMSCALE_SUNSHINE_LOG"] = str(fake_log)
        env["STREAMSCALE_LOG_DIR"] = str(log_dir)

        proc = subprocess.Popen([str(EXE)], cwd=str(EXE.parent), env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        deadline = time.time() + 45
        while time.time() < deadline and not tray_windows():
            time.sleep(1.0)
        ok = bool(tray_windows())
        print(f"  [{'PASS' if ok else 'FAIL'}] tray is up")
        if not ok:
            failures.append("tray start")
            kill_exe()
            _dump(tray_log)
            return 1

        time.sleep(2.5)
        base = _read(tray_log)
        print(f"  startup log: {len(base)} chars")

        print("\n3. History in the file must be ignored")
        check_ignored = "streaming=True" not in base
        print(f"  [{'PASS' if check_ignored else 'FAIL'}] pre-existing session not reported")
        if not check_ignored:
            failures.append("history ignored")

        print("\n4. Append a fake session start")
        with open(fake_log, "a", encoding="utf-8") as fh:
            fh.write("Executing: [steam://open/bigpicture] in [\"\"]\n")
            fh.write("Client requested stream resolution (clientViewport): 1280x960\n")
            fh.write("CLIENT CONNECTED\n")

        detected = _wait_for(tray_log, base, "streaming=True", 30)
        print(f"  [{'PASS' if detected else 'FAIL'}] detected the session")
        for line in _delta(tray_log, base):
            print(f"        {line}")
        if not detected:
            failures.append("detect start")

        after_start = _read(tray_log)

        print("\n5. The resolution should have been picked up")
        # Check the whole log, not just the delta: the resolution line can
        # land in the same timestamp as the start line, which makes a
        # before/after slice boundary unreliable.
        got_res = "1280x960" in after_start
        print(f"  [{'PASS' if got_res else 'FAIL'}] resolution captured")
        if not got_res:
            failures.append("resolution")

        print("\n6. Append a fake session end")
        with open(fake_log, "a", encoding="utf-8") as fh:
            fh.write("CLIENT DISCONNECTED\n")
            fh.write("Stopping streaming session 1\n")

        ended = _wait_for(tray_log, after_start, "streaming=False", 30)
        print(f"  [{'PASS' if ended else 'FAIL'}] detected the session ending")
        for line in _delta(tray_log, after_start):
            print(f"        {line}")
        if not ended:
            failures.append("detect end")

        print("\n7. Shut down and confirm the tray disappears")
        kill_exe()
        time.sleep(2.0)
        gone = not tray_windows()
        print(f"  [{'PASS' if gone else 'FAIL'}] tray removed")
        if not gone:
            failures.append("clean exit")

        if proc.poll() is None:
            proc.terminate()

        print("\n8. Nothing leaked outside the scratch directory")
        # Check for our override's fingerprint rather than a timestamp: the
        # real log may legitimately have been touched moments ago by another
        # check in the same suite, so mtime is not evidence.
        real = Path(os.environ.get("LOCALAPPDATA", "")) / "StreamScale" / "tray.log"
        real_text = _read(real)
        leaked = str(tmp) in real_text
        print(f"  [{'PASS' if not leaked else 'FAIL'}] scratch path absent from real log")
        if leaked:
            failures.append("isolation")

    print()
    if failures:
        print(f"FAILED: {failures}")
        return 1
    print("All checks passed.")
    return 0


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _delta(path: Path, base: str) -> list:
    text = _read(path)
    return [l for l in text[len(base):].strip().splitlines() if l.strip()]


def _wait_for(path: Path, base: str, needle: str, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if needle in _read(path)[len(base):]:
            return True
        time.sleep(1.2)
    return False


def _dump(path: Path) -> None:
    print("  --- tray log ---")
    text = _read(path)
    if not text:
        print("  (no log written - the app may have crashed before logging)")
        return
    for line in text.strip().splitlines()[-25:]:
        print(f"  {line}")


if __name__ == "__main__":
    sys.exit(main())
