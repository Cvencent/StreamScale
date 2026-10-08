"""End-to-end test with a fake Brotato settings file.

Runs the real CLI in a subprocess with SUNSHINE_* variables set, pointed at
a temporary %APPDATA%. Verifies the three things that matter:

  1. not streaming  -> nothing happens
  2. streaming      -> font_size scales up, original is backed up
  3. revert         -> the exact original file comes back

Run with:  python tests/test_endtoend.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = ROOT / "src"

ORIGINAL = {
    "current_profile_id": 0,
    "settings": {
        "font_size": 1,
        "fullscreen": True,
        "language": "zh",
        "volume": {"master": 0.5, "music": 0.25, "sound": 0.75},
        "tier_0_color": "ffe6e6e6",
    },
}

failures = []


def check(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"  [{mark}] {label}" + (f"  -- {detail}" if detail else ""))
    if not condition:
        failures.append(label)


def run_cli(appdata: Path, cmd: str, session: dict) -> subprocess.CompletedProcess:
    env_vars = dict(os.environ)
    env_vars.update(session)
    env_vars["APPDATA"] = str(appdata)
    env_vars["PYTHONPATH"] = str(SRC)
    return subprocess.run(
        [sys.executable, "-m", "streamscale.cli", cmd, "--config",
         str(appdata / "streamscale" / "config.json")],
        capture_output=True, text=True, env=env_vars, timeout=60,
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        appdata = tmp / "appdata"
        settings = appdata / "Brotato" / "76561198139548430"
        settings.mkdir(parents=True)
        target = settings / "settings.json"
        target.write_text(json.dumps(ORIGINAL, ensure_ascii=False), encoding="utf-8")

        print("\n1. Not streaming -> must do nothing")
        r = run_cli(appdata, "apply", {})
        after = json.loads(target.read_text(encoding="utf-8"))
        check("exit code 0", r.returncode == 0, f"rc={r.returncode}")
        check("file untouched", after == ORIGINAL)

        # Backups default to ~/.streamscale unless config overrides state_dir.
        # Write a config pointing them inside the temp tree so the test can
        # find them and so the developer's real home stays untouched.
        cfg_dir = appdata / "streamscale"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        (cfg_dir / "config.json").write_text(
            json.dumps({"state_dir": str(cfg_dir / "backups")}), encoding="utf-8")

        print("\n2. Streaming a small client -> font_size should grow")
        session = {
            "SUNSHINE_APP_NAME": "Brotato",
            "SUNSHINE_CLIENT_NAME": "X35S",
            "SUNSHINE_CLIENT_WIDTH": "1280",
            "SUNSHINE_CLIENT_HEIGHT": "960",
            "SUNSHINE_CLIENT_FPS": "60",
        }
        r = run_cli(appdata, "apply", session)
        after = json.loads(target.read_text(encoding="utf-8"))
        check("exit code 0", r.returncode == 0, f"rc={r.returncode}")
        check("font_size raised", after["settings"]["font_size"] > 1,
              f"font_size={after['settings']['font_size']}")
        check("other keys preserved",
              after["settings"]["volume"] == ORIGINAL["settings"]["volume"])
        check("language preserved", after["settings"]["language"] == "zh")

        backup = cfg_dir / "backups" / "Brotato.json"
        check("backup written", backup.exists())

        print("\n3. Revert -> original must come back exactly")
        r = run_cli(appdata, "revert", session)
        after = json.loads(target.read_text(encoding="utf-8"))
        check("exit code 0", r.returncode == 0, f"rc={r.returncode}")
        check("font_size restored", after["settings"]["font_size"] == 1,
              f"font_size={after['settings']['font_size']}")
        check("file identical to original", after == ORIGINAL)

        print("\n4. Big client -> must be left alone")
        big = {"SUNSHINE_APP_NAME": "Brotato", "SUNSHINE_CLIENT_NAME": "TV",
               "SUNSHINE_CLIENT_WIDTH": "3840", "SUNSHINE_CLIENT_HEIGHT": "2160"}
        r = run_cli(appdata, "apply", big)
        after = json.loads(target.read_text(encoding="utf-8"))
        check("exit code 0", r.returncode == 0, f"rc={r.returncode}")
        check("font_size untouched", after["settings"]["font_size"] == 1,
              f"font_size={after['settings']['font_size']}")

        print("\n5. Unknown app -> no adapter, no error")
        unknown = {"SUNSHINE_APP_NAME": "SomeOtherGame",
                   "SUNSHINE_CLIENT_WIDTH": "1280", "SUNSHINE_CLIENT_HEIGHT": "960"}
        r = run_cli(appdata, "apply", unknown)
        check("exit code 0", r.returncode == 0, f"rc={r.returncode}")

        print("\n6. show -> reports without writing")
        r = run_cli(appdata, "show", session)
        after = json.loads(target.read_text(encoding="utf-8"))
        check("exit code 0", r.returncode == 0, f"rc={r.returncode}")
        check("file untouched", after == ORIGINAL)
        check("reports the change", "font_size" in r.stdout,
              r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "no output")

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {failures}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
