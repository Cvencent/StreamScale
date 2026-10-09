"""Self-check: profiles are in place before a game can read them.

The bug this guards against: a game reads its settings file within
milliseconds of starting, while the process list is polled once a second.
Observed live -- process started 18:19:30, the write landed 18:19:33, and
the game had long since loaded font_size=1 into memory. The write succeeded
and had no effect.

Applying at stream start removes the race. These checks pin that behaviour
down, along with the exit-ordering rule that a game still running at stream
end must be restored only once it actually exits -- otherwise the game
writes its in-memory values back over the restore.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

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


class FakeState:
    streaming = True
    app = "steam://open/bigpicture"

    def __init__(self, w=1280, h=960):
        self.width, self.height = w, h

    @property
    def resolution(self):
        return f"{self.width}x{self.height}"


class FakeMonitor:
    def __init__(self, state):
        self.state = state


def make_app(state, appdata: Path):
    """A TrayApp with just the attributes the callbacks touch."""
    import tray_app

    os.environ["APPDATA"] = str(appdata)
    app = tray_app.TrayApp.__new__(tray_app.TrayApp)
    app._icon = None
    app._status = "idle"
    app._monitor = FakeMonitor(state)
    app._watcher = None
    app._settings_window = None
    app._applied = set()
    app._pending_release = set()
    return app


def main() -> int:
    import tray_app

    real_appdata = os.environ.get("APPDATA")
    real_localappdata = os.environ.get("LOCALAPPDATA")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # Keep logs out of the user's real directory.
        os.environ["LOCALAPPDATA"] = str(tmp / "local")
        (tmp / "local").mkdir(parents=True, exist_ok=True)

        appdata = tmp / "appdata"
        game_dir = appdata / "Brotato" / "76561198139548430"
        game_dir.mkdir(parents=True)
        settings_file = game_dir / "settings.json"
        settings_file.write_text(json.dumps(SETTINGS, ensure_ascii=False), encoding="utf-8")

        state = FakeState()
        app = make_app(state, appdata)

        print("\n1. Defaults include the new keys")
        cfg = tray_app.load_config()
        check("preapply defaults on", cfg.get("preapply") is True)
        check("font_scale defaults to 1.0", cfg.get("font_scale") == 1.0)
        check("known keys persisted",
              set(cfg) == set(tray_app.DEFAULT_CONFIG), str(sorted(cfg)))

        print("\n2. Stream start applies before any game launches")
        before = json.loads(settings_file.read_text(encoding="utf-8"))
        check("baseline font_size is 1", before["settings"]["font_size"] == 1)

        app._on_stream_change(state)
        after = json.loads(settings_file.read_text(encoding="utf-8"))
        check("profile applied at stream start",
              after["settings"]["font_size"] > 1,
              f"font_size={after['settings']['font_size']}")
        check("tracked as applied", "Brotato" in app._applied, str(app._applied))
        check("nothing pending", not app._pending_release)

        print("\n3. A game starting later finds the profile already in place")
        app._on_game_started("Brotato")
        # Already applied, so this must be a no-op rather than a second write.
        check("still exactly one application", "Brotato" in app._applied)

        print("\n4. Game exit restores immediately")
        app._on_game_exited("Brotato")
        end = json.loads(settings_file.read_text(encoding="utf-8"))
        check("font_size restored", end["settings"]["font_size"] == 1,
              f"font_size={end['settings']['font_size']}")
        check("file identical to the original", end == SETTINGS)
        check("no longer tracked", not app._applied)

        print("\n5. preapply=false falls back to waiting for the process")
        cfg = tray_app.load_config()
        cfg["preapply"] = False
        tray_app.save_config(cfg)

        settings_file.write_text(json.dumps(SETTINGS, ensure_ascii=False), encoding="utf-8")
        app._applied.clear()
        app._pending_release.clear()
        app._on_stream_change(state)
        untouched = json.loads(settings_file.read_text(encoding="utf-8"))
        check("nothing applied at stream start",
              untouched["settings"]["font_size"] == 1,
              f"font_size={untouched['settings']['font_size']}")
        app._on_game_started("Brotato")
        applied = json.loads(settings_file.read_text(encoding="utf-8"))
        check("applied when the process appears",
              applied["settings"]["font_size"] > 1,
              f"font_size={applied['settings']['font_size']}")
        app._on_game_exited("Brotato")

        cfg["preapply"] = True
        tray_app.save_config(cfg)

        print("\n6. A game still running at stream end is parked, not clobbered")
        settings_file.write_text(json.dumps(SETTINGS, ensure_ascii=False), encoding="utf-8")
        app._applied.clear()
        app._pending_release.clear()
        app._on_stream_change(state)
        check("applied", "Brotato" in app._applied)

        # Make the game look like it is still running. Brotato declares
        # process_names=("brotato.exe",), so point the check at a process
        # that genuinely exists -- this interpreter.
        import process_watcher
        orig_set = process_watcher.ProcessWatcher.set_active

        real_running = process_watcher.running_processes

        def fake_running():
            return {"python.exe"}

        def fake_adapter(self, name):
            adapter = orig_adapter(self, name)
            if adapter is not None:
                # Instance-level override: ABCMeta refuses class assignment.
                adapter.process_names = ("python.exe",)
            return adapter

        orig_adapter = tray_app.TrayApp._game_adapter
        tray_app.TrayApp._game_adapter = fake_adapter
        process_watcher.running_processes = fake_running
        # _release_all imports the module fresh, so patch the module global
        # that the import will find.
        tray_app.__dict__.setdefault("_", None)
        try:
            class EndedState(FakeState):
                streaming = False

            app._on_stream_change(EndedState())
        finally:
            tray_app.TrayApp._game_adapter = orig_adapter
            process_watcher.running_processes = real_running

        mid = json.loads(settings_file.read_text(encoding="utf-8"))
        check("not restored while the game runs",
              mid["settings"]["font_size"] > 1,
              f"font_size={mid['settings']['font_size']}")
        check("parked for later", "Brotato" in app._pending_release,
              str(app._pending_release))

        print("\n7. Once it exits, the restore finally happens")
        app._on_game_exited("Brotato")
        # _on_game_exited only acts on applied games; parked ones go through
        # the same path.
        final = json.loads(settings_file.read_text(encoding="utf-8"))
        check("restored after exit", final["settings"]["font_size"] == 1,
              f"font_size={final['settings']['font_size']}")
        check("pending cleared", not app._pending_release, str(app._pending_release))

        print("\n8. font_scale multiplies the computed size")
        settings_file.write_text(json.dumps(SETTINGS, ensure_ascii=False), encoding="utf-8")
        cfg = tray_app.load_config()
        cfg["font_scale"] = 1.5
        tray_app.save_config(cfg)

        app._applied.clear()
        app._pending_release.clear()
        app._on_stream_change(FakeState())
        scaled = json.loads(settings_file.read_text(encoding="utf-8"))
        # 1280x960 normally yields 1.75; with 1.5x that is 2.62 (rounded).
        check("font_scale applied", scaled["settings"]["font_size"] > 1.75,
              f"font_size={scaled['settings']['font_size']}")

        print("\n9. Absurd font_scale values are clamped")
        for raw, label in ((99.0, "too large"), (0.01, "too small")):
            cfg["font_scale"] = raw
            tray_app.save_config(cfg)
            settings_file.write_text(json.dumps(SETTINGS, ensure_ascii=False),
                                     encoding="utf-8")
            app._applied.clear()
            app._pending_release.clear()
            app._on_stream_change(FakeState())
            val = json.loads(settings_file.read_text(encoding="utf-8"))["settings"]["font_size"]
            within = 0.5 <= val <= 12      # 2.25 base * 3.0 clamp, with room above
            check(f"{label} ({raw}) clamped to a sane value", within, f"font_size={val}")

        cfg["font_scale"] = 1.0
        tray_app.save_config(cfg)

        # Close the log before leaving the temporary directory, or its
        # handle keeps the file locked and the cleanup fails with a
        # permission error. Importing tray_app opens it, and nothing else
        # closes it: this process is the last user.
        try:
            from streamscale import log as log_mod

            log_mod.close_handlers()
        except Exception:
            pass

    if real_appdata is None:
        os.environ.pop("APPDATA", None)
    else:
        os.environ["APPDATA"] = real_appdata
    if real_localappdata is None:
        os.environ.pop("LOCALAPPDATA", None)
    else:
        os.environ["LOCALAPPDATA"] = real_localappdata

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {failures}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
