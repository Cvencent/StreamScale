"""Live check: the built EXE applies a profile when a game starts mid-stream.

Reproduces the reported scenario exactly:

    stream starts via Steam Big Picture  ->  no adapter matches (correct)
    user launches Brotato from Steam     ->  tray notices, applies profile
    game closes                          ->  settings restored

The game is a renamed system utility standing in for Brotato, and APPDATA
points at a temporary directory, so the real Brotato settings are never
touched. Everything else -- the real executable, the real watcher, the real
adapter -- is exercised for real.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import shutil
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

failures = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f"  -- {detail}" if detail else ""))
    if not condition:
        failures.append(label)


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


SETTINGS = {
    "current_profile_id": 0,
    "settings": {
        "font_size": 1,
        "fullscreen": True,
        "language": "zh",
        "volume": {"master": 0.5, "music": 0.25, "sound": 0.75},
    },
}


def main() -> int:
    if not EXE.exists():
        print(f"[FAIL] no exe at {EXE}")
        return 1

    # Pull the watched process name from the registry rather than hardcoding
    # it, so this check keeps working when adapters are added.
    sys.path.insert(0, str(HERE.parent / "src"))
    from streamscale import registry
    watched = registry.watched_processes()
    target = watched[0]
    game_name = registry.find_by_process(target).name
    print(f"watching for : {target}  ({game_name})")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        appdata = tmp / "appdata"
        game_dir = appdata / "Brotato" / "76561198139548430"
        game_dir.mkdir(parents=True)
        settings_file = game_dir / "settings.json"
        settings_file.write_text(json.dumps(SETTINGS, ensure_ascii=False), encoding="utf-8")

        fake_log = tmp / "sunshine.log"
        # A stale session in the file, to prove history is ignored.
        fake_log.write_text("CLIENT CONNECTED\nCLIENT DISCONNECTED\n", encoding="utf-8")
        log_dir = tmp / "logdir"
        log_dir.mkdir()
        tray_log = log_dir / "tray.log"

        env = dict(os.environ)
        env["APPDATA"] = str(appdata)
        env["STREAMSCALE_SUNSHINE_LOG"] = str(fake_log)
        env["STREAMSCALE_LOG_DIR"] = str(log_dir)

        # Tell the copy under test that it *is* the installation. Without
        # this it treats itself as a package opened from elsewhere, compares
        # against the real install and exits instead of showing a tray.
        import sys as _sys
        _sys.path.insert(0, str(HERE))
        from _testenv import self_install_record
        self_install_record(tmp, EXE)

        print("\n1. Start the EXE")
        kill_exe()
        time.sleep(1.5)
        proc = subprocess.Popen([str(EXE)], cwd=str(EXE.parent), env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + 45
        while time.time() < deadline and not tray_windows():
            time.sleep(1.0)
        check("tray is up", bool(tray_windows()))
        if not tray_windows():
            kill_exe()
            _dump(tray_log)
            return 1

        time.sleep(2.5)
        text = _read(tray_log)
        check("started watching processes",
              "watching for processes" in text,
              next((l for l in text.splitlines() if "watching" in l), ""))

        print("\n2. Stream starts (Steam Big Picture)")
        with open(fake_log, "a", encoding="utf-8") as fh:
            fh.write("Executing: [steam://open/bigpicture] in [\"\"]\n")
            fh.write("Client requested stream resolution (clientViewport): 1280x960\n")
            fh.write("CLIENT CONNECTED\n")

        if not _wait_for(tray_log, "streaming=True", 30):
            check("stream detected", False, "never saw streaming=True")
            kill_exe()
            return 1
        check("stream detected", True)

        # The profile must land here, before any game launches. A game reads
        # its settings within milliseconds of starting, which a one-second
        # process poll cannot beat -- the earlier design wrote the file three
        # seconds late and the game had already loaded the old value.
        preapplied = False
        deadline = time.time() + 25
        while time.time() < deadline:
            current = json.loads(settings_file.read_text(encoding="utf-8"))
            if current["settings"]["font_size"] > 1:
                preapplied = True
                break
            time.sleep(1.0)

        staged = json.loads(settings_file.read_text(encoding="utf-8"))
        check("profile applied at stream start, before the game exists",
              preapplied, f"font_size={staged['settings']['font_size']}")
        check("other keys preserved",
              staged["settings"]["volume"] == SETTINGS["settings"]["volume"]
              and staged["settings"]["language"] == "zh")
        for line in _read(tray_log).splitlines():
            if "preapplied" in line:
                print(f"        {line[:140]}")

        print(f"\n3. Launch the game process ({target})")
        game_exe = tmp / target
        # A system utility that keeps running, renamed to look like the game.
        for candidate in ("ping.exe", "timeout.exe"):
            src = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / candidate
            if src.exists():
                shutil.copy2(src, game_exe)
                break
        if not game_exe.exists():
            check("stand-in process created", False)
            kill_exe()
            return 1
        check("stand-in process created", True, str(game_exe.name))

        game_proc = subprocess.Popen(
            [str(game_exe), "-n", "120", "127.0.0.1"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        print("4. The game finds the profile already in place")
        time.sleep(6)
        running = json.loads(settings_file.read_text(encoding="utf-8"))
        check("still applied while the game runs",
              running["settings"]["font_size"] > 1,
              f"font_size={running['settings']['font_size']}")
        for line in _read(tray_log).splitlines():
            if "started" in line and "profile already" in line:
                print(f"        {line}")
                break

        print("\n5. Closing the game restores the settings")
        game_proc.terminate()
        try:
            game_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            game_proc.kill()

        restored = False
        deadline = time.time() + 35
        while time.time() < deadline:
            current = json.loads(settings_file.read_text(encoding="utf-8"))
            if current["settings"]["font_size"] == 1:
                restored = True
                break
            time.sleep(1.5)

        end = json.loads(settings_file.read_text(encoding="utf-8"))
        check("font_size restored on exit", restored,
              f"font_size={end['settings']['font_size']}")
        check("file identical to the original", end == SETTINGS)
        for line in _read(tray_log).splitlines():
            if "exited ->" in line:
                print(f"        {line[:140]}")

        print("\n6. Clean up")
        kill_exe()
        time.sleep(1.5)
        check("tray removed", not tray_windows())
        if proc.poll() is None:
            proc.terminate()

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {failures}")
        return 1
    print("All checks passed.")
    return 0


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _wait_for(path: Path, needle: str, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if needle in _read(path):
            return True
        time.sleep(1.2)
    return False


def _dump(path: Path) -> None:
    print("  --- tray log ---")
    text = _read(path)
    if not text:
        print("  (empty - the app may have crashed before logging)")
        return
    for line in text.strip().splitlines()[-20:]:
        print(f"  {line}")


if __name__ == "__main__":
    sys.exit(main())
