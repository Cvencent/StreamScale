"""Self-check: the built exe can serve as a Sunshine prep-command.

This guards a failure that cost a real streaming session. Sunshine was
pointed at a copy of the tray exe that did not understand `apply`:

    "C:\\...\\Downloads\\StreamScale.exe" apply

The exe treated it as an ordinary launch, started a second tray, and hit the
single-instance guard. Sunshine waits for its prep-command to exit, so:

    the session teardown stalled for five and a half minutes
    the client showed an empty desktop (reported as a black screen)
    the virtual display was never torn down or restored (reported as a
    phantom second monitor)

None of it surfaced as an error. The lesson is that "a command that runs but
never exits" is worse than "a command that fails", which is why an unknown
verb exits non-zero instead of falling back to a tray.

Two other properties are checked here because they were wrong at some point:

  * start-up speed -- the onefile build unpacked ~19 MB on every run, which
    measured 25 s against 0.2 s for onedir, and Sunshine calls the
    prep-command twice per stream;
  * the version resource -- an upgrade cannot compare builds without one.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import updater  # noqa: E402

failures = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f"  -- {detail}" if detail else ""))
    if not condition:
        failures.append(label)


def locate_exe() -> Path:
    """The built exe, in whichever layout was produced.

    Prefers the onedir folder. Also accepts a lone exe directly in dist/ so
    the check still means something against an older build.
    """
    for candidate in (HERE / "dist" / "StreamScale" / "StreamScale.exe",
                      HERE / "dist" / "StreamScale.exe"):
        if candidate.exists():
            return candidate
    return HERE / "dist" / "StreamScale" / "StreamScale.exe"


EXE = locate_exe()

# A start slower than this is a problem: Sunshine waits for the process, so a
# slow start reads as a hang. onedir measures ~0.2 s; onefile measured 25 s.
MAX_START_SECONDS = 5.0


def run(exe: Path, args, env, timeout=45):
    """Run the exe, returning (exit code, elapsed). None means it timed out."""
    start = time.time()
    try:
        proc = subprocess.run([str(exe)] + args, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout,
                              env=env,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return proc.returncode, time.time() - start
    except subprocess.TimeoutExpired:
        return None, time.time() - start


def main() -> int:
    print("\n0. The build exists")
    exists = EXE.exists()
    check("exe found", exists, str(EXE))
    if not exists:
        print(f"\nFAILED: {failures}")
        return 1

    onedir = (EXE.parent / "_internal").is_dir()
    print(f"    location: {EXE}")
    print(f"    layout:   {'onedir' if onedir else 'onefile'}")

    print("\n1. The build carries a version resource")
    version = updater.read_exe_version(EXE)
    check("version resource present", version is not None, str(version))
    check("parses as a version",
          version is not None and version.count(".") == 3, str(version))

    tmp = Path(tempfile.mkdtemp())
    env = dict(os.environ)
    env["LOCALAPPDATA"] = str(tmp / "local")
    env["APPDATA"] = str(tmp / "appdata")
    env["SUNSHINE_APP_NAME"] = "Brotato"
    env["SUNSHINE_CLIENT_NAME"] = "X35S"
    env["SUNSHINE_CLIENT_WIDTH"] = "1280"
    env["SUNSHINE_CLIENT_HEIGHT"] = "960"

    game = tmp / "game"
    game.mkdir(parents=True)
    (game / "Brotato.exe").write_bytes(b"")
    cfg_dir = tmp / "appdata" / "Brotato" / "123"
    cfg_dir.mkdir(parents=True)
    settings = cfg_dir / "settings.json"
    env["STREAMSCALE_GAME_DIR"] = str(game)

    def reset_settings():
        settings.write_text('{"settings":{"font_size":1}}', encoding="utf-8")

    print("\n2. Every verb exits promptly (Sunshine waits for this)")
    for verb in ("show", "apply", "revert"):
        reset_settings()
        code, elapsed = run(EXE, [verb], env)
        check(f"{verb} responds within {MAX_START_SECONDS:.0f}s",
              code is not None and elapsed < MAX_START_SECONDS,
              f"rc={code} in {elapsed:.2f}s")

    print("\n3. An unknown verb is refused, never a tray")
    # The exact regression: falling through to "start the tray" is what made
    # Sunshine wait forever.
    for bad in ("nonsense", "--frobnicate", "apply2"):
        code, elapsed = run(EXE, [bad], env, timeout=15)
        refused = code is not None and code != 0 and elapsed < 10
        check(f"{bad!r} refused quickly", refused, f"rc={code} in {elapsed:.2f}s")
        if code is None:
            subprocess.run(["taskkill", "/F", "/IM", EXE.name],
                           capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    print("\n4. apply changes settings, revert restores them")
    reset_settings()
    run(EXE, ["apply"], env)
    after_apply = json.loads(settings.read_text(encoding="utf-8"))
    check("apply raised the font size",
          after_apply["settings"].get("font_size", 1) > 1,
          f"font_size={after_apply['settings'].get('font_size')}")

    run(EXE, ["revert"], env)
    after_revert = json.loads(settings.read_text(encoding="utf-8"))
    check("revert restored the font size",
          after_revert["settings"].get("font_size") == 1,
          f"font_size={after_revert['settings'].get('font_size')}")

    print("\n5. show changes nothing")
    reset_settings()
    before = settings.read_bytes()
    run(EXE, ["show"], env)
    check("show left the file untouched", settings.read_bytes() == before)

    print("\n6. A bare launch starts the tray and keeps running")
    proc = subprocess.Popen([str(EXE)], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(6)
    alive = proc.poll() is None
    check("tray mode stays resident", alive)
    if alive:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except Exception:
            proc.kill()

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {failures}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
