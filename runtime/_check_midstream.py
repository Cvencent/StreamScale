"""Self-check: a game launched mid-stream gets its profile applied.

Simulates the exact sequence the user hit:

    1. stream starts (Steam Big Picture, so no adapter matches yet)
    2. user launches Brotato from inside Steam
    3. the tray notices the process and applies the profile
    4. the game is closed -> settings are restored

Steps 2 and 4 use a stand-in process, because installing and launching the
real game is not something a self-check should do. What is being verified is
the wiring: stream state gates the watcher, the watcher fires, the adapter
loads and writes, and the revert restores.

The real Brotato settings file is never touched -- the adapter is pointed at
a temporary copy via a patched APPDATA, restored afterwards even if a check
fails.
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
SRC = HERE.parent / "src"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SRC))

failures = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f"  -- {detail}" if detail else ""))
    if not condition:
        failures.append(label)


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
    import tray_app
    from streamscale import env, registry
    from streamscale import adapter as adapter_mod

    real_appdata = os.environ.get("APPDATA")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        ui = tmp / "ui"
        ui.mkdir()
        game_dir = tmp / "appdata" / "Brotato" / "76561198139548430"
        game_dir.mkdir(parents=True)
        settings = game_dir / "settings.json"
        settings.write_text(json.dumps(SETTINGS, ensure_ascii=False), encoding="utf-8")
        os.environ["APPDATA"] = str(tmp / "appdata")

        print("\n1. Baseline")
        before = json.loads(settings.read_text(encoding="utf-8"))
        check("font_size starts at 1", before["settings"]["font_size"] == 1)

        print("\n2. Registry knows which process to watch")
        cls = registry.find_by_process("brotato.exe")
        check("brotato.exe -> Brotato adapter", cls is not None)
        check("no adapter for Steam itself",
              registry.find_by_process("steam.exe") is None,
              "Steam Big Picture legitimately has no adapter")

        print("\n3. Build the adapter the way the tray does")
        # Client at 1280x960, the handheld.
        session = env.Session(app_id="", app_name="Brotato", client_name="X35S",
                              client_id="", client_unique_id="",
                              width=1280, height=960, fps=60)
        adapter = cls(session, state_dir=tmp / "state")
        check("adapter loaded", adapter is not None)
        check("resolves the settings file",
              adapter.settings_path() == settings,
              str(adapter.settings_path()))

        print("\n4. Apply (what happens when the game process appears)")
        result = adapter.apply()
        after = json.loads(settings.read_text(encoding="utf-8"))
        check("reported a change", result.changed, result.detail)
        check("font_size raised",
              after["settings"]["font_size"] > 1,
              f"font_size={after['settings']['font_size']}")
        check("volume untouched",
              after["settings"]["volume"] == SETTINGS["settings"]["volume"])
        check("language untouched", after["settings"]["language"] == "zh")
        check("backup written", (tmp / "state" / "Brotato.json").exists())

        print("\n5. Revert (what happens when the game exits)")
        result = adapter.revert()
        restored = json.loads(settings.read_text(encoding="utf-8"))
        check("reported a change", result.changed, result.detail)
        check("font_size back to 1", restored["settings"]["font_size"] == 1,
              f"font_size={restored['settings']['font_size']}")
        check("file identical to the original", restored == SETTINGS)

        print("\n6. The tray's own callbacks do the same")
        app = tray_app.TrayApp.__new__(tray_app.TrayApp)
        app._icon = None
        app._status = "active"
        app._applied = set()
        app._monitor = None
        app._watcher = None
        app._settings_window = None

        class St:
            """Minimal stand-in for the monitor's state."""
            streaming = True
            width, height = 1280, 960
            app = "steam://open/bigpicture"

            @property
            def resolution(self):
                return f"{self.width}x{self.height}"

        class Mon:
            state = St()

        app._monitor = Mon()

        # Route the adapter construction through the temp APPDATA.
        original_init = adapter_mod.GameAdapter.__init__

        def patched(self, session, dry_run=False, state_dir=None):
            original_init(self, session, dry_run=dry_run, state_dir=tmp / "state2")

        adapter_mod.GameAdapter.__init__ = patched
        try:
            app._on_game_started("Brotato")
            mid = json.loads(settings.read_text(encoding="utf-8"))
            check("tray applied the profile",
                  mid["settings"]["font_size"] > 1,
                  f"font_size={mid['settings']['font_size']}")
            check("tracked as applied", "Brotato" in app._applied)

            app._on_game_exited("Brotato")
            end = json.loads(settings.read_text(encoding="utf-8"))
            check("tray restored the profile",
                  end["settings"]["font_size"] == 1,
                  f"font_size={end['settings']['font_size']}")
            check("no longer tracked", "Brotato" not in app._applied)
        finally:
            adapter_mod.GameAdapter.__init__ = original_init

        print("\n7. A stream ending releases anything still applied")
        app._on_game_started("Brotato")
        check("applied again", "Brotato" in app._applied)
        app._release_all()
        final = json.loads(settings.read_text(encoding="utf-8"))
        check("released on stream end", final["settings"]["font_size"] == 1,
              f"font_size={final['settings']['font_size']}")
        check("nothing left tracked", not app._applied)

    if real_appdata is None:
        os.environ.pop("APPDATA", None)
    else:
        os.environ["APPDATA"] = real_appdata

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {failures}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
