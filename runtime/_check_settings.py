"""Self-check: settings window imports, and apps.json editing safety.

The apps.json tests matter most: this code rewrites a file that belongs to
another program and may hold a lot of hand-written entries. The checks below
are about what is *preserved*, not just what is changed.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

failures = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f"  -- {detail}" if detail else ""))
    if not condition:
        failures.append(label)


APPLY = r'"E:\StreamScale\streamscale.bat" apply'
REVERT = r'"E:\StreamScale\streamscale.bat" revert'

# A realistic file: several apps, hand-written fields, one app that already
# has an unrelated press command that must survive untouched.
ORIGINAL = {
    "env": {"PATH": "$(PATH)"},
    "apps": [
        {"name": "Desktop", "image-path": "desktop.png"},
        {
            "name": "Steam Big Picture",
            "cmd": "steam://open/bigpicture",
            "auto-detach": True,
            "wait-all": True,
            "image-path": "steam.png",
        },
        {
            "name": "Brotato",
            "cmd": "F:\\steam\\steamapps\\common\\Brotato\\Brotato.exe",
            "working-dir": "F:\\steam\\steamapps\\common\\Brotato",
            "prep-cmd": [{"do": "echo unrelated", "undo": "echo undo"}],
            "elevated": False,
        },
        {"name": "RetroArch", "cmd": "retroarch.exe"},
    ],
}


def main() -> int:
    print("\n1. Imports")
    import sunshine_config
    import tray_app
    check("sunshine_config", True)
    check("tray_app", True)
    try:
        import settings_window
        check("settings_window", True)
    except Exception as exc:
        check("settings_window", False, repr(exc))

    print("\n2. Known games list")
    from settings_window import known_games
    games = known_games()
    check("non-empty", len(games) > 0, str(games))

    print("\n3. apps.json install (dry run leaves the file alone)")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "apps.json"
        path.write_text(json.dumps(ORIGINAL, ensure_ascii=False, indent=2), encoding="utf-8")
        before = path.read_text(encoding="utf-8")

        count, names = sunshine_config.install_prep(path, APPLY, REVERT, dry_run=True)
        check("dry run reports changes", count == 4, f"count={count}")
        check("dry run does not write", path.read_text(encoding="utf-8") == before)

        print("\n4. Real install")
        count, names = sunshine_config.install_prep(path, APPLY, REVERT)
        after = json.loads(path.read_text(encoding="utf-8"))
        check("all apps updated", count == 4, f"count={count}")

        check("backup created", (Path(tmp) / "apps.json.streamscale.bak").exists())

        by_name = {a["name"]: a for a in after["apps"]}
        check("Desktop has prep-cmd",
              by_name["Desktop"]["prep-cmd"][0]["do"] == APPLY)
        check("Steam launch cmd preserved",
              by_name["Steam Big Picture"]["cmd"] == "steam://open/bigpicture")
        check("Steam flags preserved",
              by_name["Steam Big Picture"]["auto-detach"] is True
              and by_name["Steam Big Picture"]["wait-all"] is True)
        check("working-dir preserved",
              by_name["Brotato"]["working-dir"] == "F:\\steam\\steamapps\\common\\Brotato")
        check("elevated flag preserved", by_name["Brotato"]["elevated"] is False)
        check("top-level env preserved", after.get("env") == {"PATH": "$(PATH)"})
        check("image-path preserved", by_name["Desktop"]["image-path"] == "desktop.png")

        print("\n5. Unrelated press command on Brotato must survive")
        brotato_prep = by_name["Brotato"]["prep-cmd"]
        check("both entries present", len(brotato_prep) == 2, str(brotato_prep))
        unrelated = [c for c in brotato_prep if c["do"] == "echo unrelated"]
        check("unrelated entry kept", len(unrelated) == 1)

        print("\n6. Idempotent: installing twice changes nothing")
        count2, _ = sunshine_config.install_prep(path, APPLY, REVERT)
        check("second install is a no-op", count2 == 0, f"count={count2}")

        print("\n7. Status reporting")
        info = sunshine_config.status_of(path, APPLY)
        check("total counted", info["total"] == 4, str(info["total"]))
        check("installed counted", info["installed"] == 4, str(info["installed"]))

        print("\n8. Uninstall removes only our entry")
        removed, names = sunshine_config.uninstall_prep(path, APPLY)
        final = json.loads(path.read_text(encoding="utf-8"))
        by_name2 = {a["name"]: a for a in final["apps"]}
        check("all removed", removed == 4, f"removed={removed}")
        check("Desktop prep gone", "prep-cmd" not in by_name2["Desktop"])
        brotato_after = by_name2["Brotato"].get("prep-cmd")
        check("unrelated entry still there",
              brotato_after == [{"do": "echo unrelated", "undo": "echo undo"}],
              str(brotato_after))
        check("other fields intact",
              by_name2["Brotato"]["working-dir"] == "F:\\steam\\steamapps\\common\\Brotato")

    print("\n9. Malformed input is refused, not clobbered")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "apps.json"
        path.write_text("{ this is not json", encoding="utf-8")
        try:
            sunshine_config.install_prep(path, APPLY, REVERT)
            check("raises on bad JSON", False, "no exception")
        except Exception as exc:
            check("raises on bad JSON", True, type(exc).__name__)
        check("file untouched after failure",
              path.read_text(encoding="utf-8") == "{ this is not json")

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {failures}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
