"""Self-check: the Brotato adapter writes the file the game actually reads.

Guards a defect that made every font change invisible. There are two
settings.json files under %APPDATA%/Brotato:

    <steamid>/settings.json    the one the game reads
    user/settings.json         the mod loader's

The adapter picked the newest by modification time, and `user/` was usually
newer, so writes went to a file the game never opens. Everything looked
healthy: the write succeeded, the value was correct in the file that was
written, and the log said a profile had been applied. Reported, accurately,
as "the font does not change no matter what I do".

The game names its own file in its log, which is where the answer came from:

    ProgressData: Saved current profile id 0 to
        user://76561198139548430/settings.json

So this check builds both directories, makes the wrong one newer, and asserts
the adapter still chooses the right one. A test that only created one
directory would have passed throughout.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

from streamscale import env, registry  # noqa: E402
from streamscale.cli import apply_font_scale  # noqa: E402

failures = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f"  -- {detail}" if detail else ""))
    if not condition:
        failures.append(label)


STEAM_ID = "76561198139548430"


def make_world(tmp: Path, *, mod_loader_newer: bool = True) -> Path:
    """Both settings files, with the mod loader's optionally the newer one."""
    appdata = tmp / "appdata"
    steam_dir = appdata / "Brotato" / STEAM_ID
    user_dir = appdata / "Brotato" / "user"
    steam_dir.mkdir(parents=True)
    user_dir.mkdir(parents=True)

    payload = json.dumps({"current_profile_id": 0,
                          "settings": {"font_size": 1, "language": "zh"}})
    (steam_dir / "settings.json").write_text(payload, encoding="utf-8")
    (user_dir / "settings.json").write_text(payload, encoding="utf-8")

    # mtime is what the old code sorted on, so make the ordering explicit.
    now = time.time()
    if mod_loader_newer:
        os.utime(steam_dir / "settings.json", (now - 600, now - 600))
        os.utime(user_dir / "settings.json", (now, now))
    else:
        os.utime(user_dir / "settings.json", (now - 600, now - 600))
        os.utime(steam_dir / "settings.json", (now, now))

    return appdata


def adapter(tmp: Path):
    session = env.Session(app_id="1942280", app_name="Brotato",
                          client_name="X35S", client_id="a",
                          client_unique_id="b", width=1280, height=960, fps=60)
    cls = next(c for c in registry.ADAPTERS if c.name == "Brotato")
    return cls(session)


def main() -> int:
    print("\n1. The Steam ID file wins, even when the other is newer")
    tmp = Path(tempfile.mkdtemp())
    appdata = make_world(tmp, mod_loader_newer=True)
    os.environ["APPDATA"] = str(appdata)

    ad = adapter(tmp)
    chosen = ad.settings_path()
    check("chose the Steam ID directory", chosen.parent.name == STEAM_ID,
          str(chosen.parent.name))
    check("not the mod loader's directory", chosen.parent.name != "user")

    print("\n2. Still correct when the Steam ID file happens to be newer")
    tmp = Path(tempfile.mkdtemp())
    appdata = make_world(tmp, mod_loader_newer=False)
    os.environ["APPDATA"] = str(appdata)
    ad = adapter(tmp)
    check("chose the Steam ID directory", ad.settings_path().parent.name == STEAM_ID,
          ad.settings_path().parent.name)

    print("\n3. A change lands in the game's file, not the other one")
    tmp = Path(tempfile.mkdtemp())
    appdata = make_world(tmp, mod_loader_newer=True)
    os.environ["APPDATA"] = str(appdata)
    ad = adapter(tmp)
    apply_font_scale(ad, 1.4)
    ad.apply()

    game_file = appdata / "Brotato" / STEAM_ID / "settings.json"
    other_file = appdata / "Brotato" / "user" / "settings.json"
    game_size = json.loads(game_file.read_text(encoding="utf-8"))["settings"]["font_size"]
    other_size = json.loads(other_file.read_text(encoding="utf-8"))["settings"]["font_size"]

    check("the game's file changed", game_size != 1, f"font_size={game_size}")
    check("the mod loader's file did not", other_size == 1, f"font_size={other_size}")
    # 1280 wide is the handheld case: a base of 1.75, times 1.4.
    check("scaled the automatic size rather than replacing it",
          abs(game_size - 2.45) < 0.05, f"font_size={game_size}")

    print("\n4. Revert puts the game's file back")
    ad.revert()
    restored = json.loads(game_file.read_text(encoding="utf-8"))["settings"]["font_size"]
    check("restored to the original", restored == 1, f"font_size={restored}")

    print("\n5. A single directory still works")
    tmp = Path(tempfile.mkdtemp())
    appdata = tmp / "appdata"
    only = appdata / "Brotato" / STEAM_ID
    only.mkdir(parents=True)
    (only / "settings.json").write_text(
        json.dumps({"settings": {"font_size": 1}}), encoding="utf-8")
    os.environ["APPDATA"] = str(appdata)
    ad = adapter(tmp)
    check("found the only candidate", ad.settings_path().parent.name == STEAM_ID)

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {failures}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
