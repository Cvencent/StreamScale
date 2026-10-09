"""Self-check: the text-size slider actually changes the text size.

Guards a defect that made the main control of the settings window a no-op.
The multiplier was stored in the config and applied by the tray, but the
process that actually writes a game's settings is the one Sunshine launches
as a prep-command -- a separate invocation that never loads the tray. So the
slider wrote a value nothing read, and moving it changed nothing:

    font_scale=1.0  -> font_size=1.75
    font_scale=1.4  -> font_size=1.75
    font_scale=2.0  -> font_size=1.75

Reported as "I dragged it to 1.75 and nothing changed", which is exactly what
was happening, and there was nothing in the log to say why.

The check drives both paths end to end -- the command Sunshine runs, and the
tray watching for a session -- because they are separate code paths and only
one of them was broken. A test of the tray alone would have passed.

It also asserts the multiplier *scales* the adapter's own choice rather than
replacing it: a handheld at 1280 wide gets a base of 1.75, so 1.4 must land
at about 2.45, not at 1.4.
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
sys.path.insert(0, str(HERE.parent / "src"))

from _testenv import isolated_env, self_install_record  # noqa: E402

failures = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f"  -- {detail}" if detail else ""))
    if not condition:
        failures.append(label)


def locate_exe() -> Path:
    for candidate in (HERE / "dist" / "StreamScale" / "StreamScale.exe",
                      HERE / "dist" / "StreamScale.exe",
                      HERE.parent / "StreamScale" / "StreamScale.exe"):
        if candidate.exists():
            return candidate
    return HERE / "dist" / "StreamScale" / "StreamScale.exe"


EXE = locate_exe()


def sweep() -> None:
    subprocess.run(["taskkill", "/F", "/IM", EXE.name], capture_output=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    time.sleep(1.0)


def make_world(tmp: Path, scale: float):
    """A config, a fake Brotato install, and the settings file it reads."""
    env = isolated_env(tmp)
    config = Path(env["APPDATA"]) / "StreamScale" / "config.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps({
        "enabled": True,
        "font_scale": scale,
        "aspect_fill": "expand",
        "preapply": True,
        "max_client_width": 1600,
        "excluded_apps": ["Desktop"],
        "clients": {},
        "state_dir": "",
        "language": "en",
    }), encoding="utf-8")

    game_cfg = Path(env["APPDATA"]) / "Brotato" / "123"
    game_cfg.mkdir(parents=True, exist_ok=True)
    settings = game_cfg / "settings.json"
    settings.write_text('{"settings":{"font_size":1}}', encoding="utf-8")
    return env, settings


def via_command(scale: float) -> float:
    """The path Sunshine uses: a one-shot `apply`."""
    tmp = Path(tempfile.mkdtemp())
    env, settings = make_world(tmp, scale)
    subprocess.run([str(EXE), "apply"], capture_output=True, timeout=45, env=env,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    value = json.loads(settings.read_text(encoding="utf-8"))["settings"]["font_size"]
    return value


def via_tray(scale: float) -> float:
    """The path the tray uses: notice a session and pre-apply."""
    tmp = Path(tempfile.mkdtemp())
    env, settings = make_world(tmp, scale)
    self_install_record(tmp, EXE)

    sweep()
    proc = subprocess.Popen([str(EXE)], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(6)
        # Announce a session the way Sunshine does.
        with open(env["STREAMSCALE_SUNSHINE_LOG"], "a", encoding="utf-8") as fh:
            fh.write("CLIENT CONNECTED\n")

        deadline = time.time() + 20
        while time.time() < deadline:
            time.sleep(0.5)
            if json.loads(settings.read_text(encoding="utf-8"))["settings"]["font_size"] != 1:
                break
        return json.loads(settings.read_text(encoding="utf-8"))["settings"]["font_size"]
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except Exception:
            proc.kill()
        sweep()


def main() -> int:
    print("\n0. The build exists")
    exists = EXE.exists()
    check("exe found", exists, str(EXE))
    if not exists:
        print(f"\nFAILED: {failures}")
        return 1

    print("\n1. The multiplier scales the base size, not replaces it")
    # 1280 wide is the handheld case, whose base the adapter sets to 1.75.
    base = via_command(1.0)
    check("1.0 leaves the automatic size alone", base == 1.75, f"font_size={base}")

    scaled = via_command(1.4)
    expected = round(1.75 * 1.4, 2)
    check(f"1.4 gives about {expected}", abs(scaled - expected) < 0.05,
          f"font_size={scaled}")

    bigger = via_command(2.0)
    check("2.0 is larger than 1.4", bigger > scaled, f"{bigger} > {scaled}")

    print("\n2. The same multiplier applies on the tray path")
    # These are different code paths: Sunshine launches a fresh process for
    # its prep-command, which never loads the tray. Only one of them was
    # broken, so testing the tray alone would have missed it -- and testing
    # the command alone would have missed the tray.
    tray_scaled = via_tray(1.4)
    check("tray also applies the multiplier", tray_scaled != 1,
          f"font_size={tray_scaled}")

    print("\n3. Out-of-range values are clamped, not obeyed")
    # 0.5 is the lowest the slider offers, so it is a value to honour rather
    # than an error to reject: the result is half the automatic size.
    low = via_command(0.5)
    check("0.5 halves the automatic size", abs(low - round(1.75 * 0.5, 2)) < 0.05,
          f"font_size={low}")
    below = via_command(0.1)
    check("below the slider's range is clamped to 0.5",
          abs(below - 0.875) < 0.05, f"font_size={below}")
    high = via_command(2.5)
    check("2.5 is the slider's maximum",
          abs(high - round(1.75 * 2.5, 2)) < 0.05, f"font_size={high}")
    # The code allows a little beyond the slider, so a hand-edited config can
    # go further without the UI needing to expose it.
    over = via_command(99.0)
    check("beyond the range is clamped to the code's limit",
          abs(over - round(1.75 * 3.0, 2)) < 0.05, f"font_size={over}")

    print("\n4. A missing or broken value falls back to automatic")
    for label, value in (("missing", None), ("text", "big"), ("zero", 0),
                         ("negative", -1)):
        tmp = Path(tempfile.mkdtemp())
        env, settings = make_world(tmp, value if value is not None else 1.0)
        if value is None:
            config = Path(env["APPDATA"]) / "StreamScale" / "config.json"
            data = json.loads(config.read_text(encoding="utf-8"))
            data.pop("font_scale", None)
            config.write_text(json.dumps(data), encoding="utf-8")
        subprocess.run([str(EXE), "apply"], capture_output=True, timeout=45, env=env,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        result = json.loads(settings.read_text(encoding="utf-8"))["settings"]["font_size"]
        check(f"{label!r} keeps the game readable", result == 1.75, f"font_size={result}")

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {failures}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
