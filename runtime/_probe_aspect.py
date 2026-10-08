"""Probe: measure the letterbox with and without an aspect override.

Brotato renders at 320x180 with display/window/stretch/aspect = "keep", so a
4:3 screen letterboxes the image. This measures whether putting an
override.cfg beside the executable changes that, by screenshotting the
client area and counting the black bars.

Two obstacles, both solved here:

  * Brotato launched directly exits with "Restarting game over Steam..."
    because Steam is running. So the game is launched via steam:// and this
    waits for the *second* window -- the one Steam starts.
  * The result has only been confirmed from logs, which cannot show whether
    the picture actually changed. Hence screenshots.

Everything is restored afterwards: override.cfg is removed and settings.json
is restored from a backup. The game is left closed.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

GAME_DIR = Path(r"F:\steam\steamapps\common\Brotato")
OVERRIDE = GAME_DIR / "override.cfg"
WINDOW_SIZE = "800x600"          # 4:3
STEAM_URI = "steam://rungameid/1942280"

user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

# Explicit signatures: without them ctypes truncates the HWND on 64-bit and
# GetClientRect reports 0x0 against a garbage handle.
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.ClientToScreen.argtypes = [wt.HWND, ctypes.POINTER(wt.POINT)]

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass


def brotato_pid() -> int:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Brotato.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, encoding="gbk", errors="replace",
        ).stdout or ""
        for line in out.splitlines():
            if "Brotato.exe" in line:
                return int(line.split('","')[1])
    except Exception:
        pass
    return 0


def largest_window(pid: int):
    best = None

    def cb(hwnd, _l):
        nonlocal best
        owner = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid or not user32.IsWindowVisible(hwnd):
            return True
        rect = wt.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w, h = rect.right - rect.left, rect.bottom - rect.top
        if w > 200 and h > 200:
            if best is None or w * h > best[1]:
                best = (hwnd, w * h, w, h)
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return best


def client_box(hwnd):
    rect = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    origin = wt.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(origin))
    return (origin.x, origin.y, rect.right, rect.bottom)


def kill_game():
    subprocess.run(["taskkill", "/F", "/IM", "Brotato.exe"],
                   capture_output=True, text=True, encoding="gbk", errors="replace")


def measure(img):
    """(top_px, bottom_px, height) of uniform bars, or None."""
    grey = img.convert("L")
    w, h = grey.size
    if w < 8 or h < 8:
        return None
    scaled = grey.resize((64, h))
    data = list(scaled.getdata())
    rows = [max(data[y * 64:(y + 1) * 64]) - min(data[y * 64:(y + 1) * 64])
            for y in range(h)]
    content = [y for y, spread in enumerate(rows) if spread > 12]
    if not content:
        return None
    return (content[0], h - 1 - content[-1], h)


def wait_for_window(timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        pid = brotato_pid()
        if pid:
            found = largest_window(pid)
            if found:
                return found[0]
        time.sleep(2.0)
    return None


def run_case(label, override_text):
    from PIL import ImageGrab

    kill_game()
    time.sleep(2.0)

    if override_text is None:
        if OVERRIDE.exists():
            OVERRIDE.unlink()
    else:
        OVERRIDE.write_text(override_text, encoding="utf-8")

    print(f"\n--- {label} ---")
    print("    override:", "none" if not override_text
          else " ".join(override_text.split()))

    os.startfile(STEAM_URI)
    hwnd = wait_for_window(90)
    if hwnd is None:
        print("    no window appeared")
        kill_game()
        return None

    rect = client_box(hwnd)
    print(f"    client box: {rect[2]-rect[0]}x{rect[3]-rect[1]}")

    # Sample until the picture is stable, so the loading screen is not
    # mistaken for the menu.
    samples = []
    for _ in range(14):
        time.sleep(3.5)
        try:
            shot = ImageGrab.grab(bbox=rect)
        except Exception:
            continue
        m = measure(shot)
        if m:
            samples.append(m)
            if len(samples) >= 3 and samples[-1] == samples[-2]:
                break

    if not samples:
        print("    no content detected")
        kill_game()
        return None

    top, bottom, height = samples[-1]
    shot = ImageGrab.grab(bbox=rect)
    shot.save(str(Path(tempfile.gettempdir()) / f"aspect_{label}.png"))
    pct = (top + bottom) / height * 100
    print(f"    top {top}px  bottom {bottom}px  height {height}px  "
          f"letterbox {pct:.1f}%")
    kill_game()
    time.sleep(1.5)
    return pct


def main() -> int:
    if not (GAME_DIR / "Brotato.exe").exists():
        print("game not found")
        return 1

    candidates = glob.glob(os.path.expandvars(r"%APPDATA%\Brotato\*\settings.json"))
    if not candidates:
        print("settings.json not found")
        return 1
    settings_path = Path(candidates[0])
    backup = settings_path.with_name("settings.probe-backup.json")
    shutil.copy2(settings_path, backup)
    print(f"settings: {settings_path}")

    data = json.loads(settings_path.read_text(encoding="utf-8"))
    original_fullscreen = data["settings"].get("fullscreen")
    data["settings"]["fullscreen"] = False
    settings_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    results = {}
    try:
        results["keep (default)"] = run_case("keep", None)
        results["expand"] = run_case(
            "expand", '[display]\n\nwindow/stretch/mode="2d"\n'
                      'window/stretch/aspect="expand"\n')
        results["ignore"] = run_case(
            "ignore", '[display]\n\nwindow/stretch/mode="2d"\n'
                      'window/stretch/aspect="ignore"\n')
    finally:
        kill_game()
        time.sleep(2.0)
        if OVERRIDE.exists():
            OVERRIDE.unlink()
        shutil.copy2(backup, settings_path)
        backup.unlink()
        print("\nrestored settings.json, removed override.cfg")

    print("\n=== result: letterbox as % of client height ===")
    for label, pct in results.items():
        if pct is None:
            print(f"  {label:18} inconclusive")
        else:
            print(f"  {label:18} {pct:5.1f}%   {'FILLS' if pct < 5 else 'bars'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
