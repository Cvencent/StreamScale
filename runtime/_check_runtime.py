"""Self-check: import chain, icon generation, config round-trip, log parsing.

Runnable repeatedly; leaves nothing behind. Run with the build venv:

    runtime\\.buildvenv\\Scripts\\python.exe _check_runtime.py
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


def main() -> int:
    print("\n1. Import chain")
    import tray_icons
    import stream_monitor
    import tray_app
    check("tray_icons", True)
    check("stream_monitor", True)
    check("tray_app", True)

    print("\n2. Icons")
    for status in ("idle", "active", "restored", "error", "disabled"):
        img = tray_icons.make_tray_image(status)
        check(f"icon {status}", img.size == (64, 64), str(img.size))
    colors = {tray_icons.rgb_tuple(s) for s in
              ("idle", "active", "restored", "error", "disabled")}
    check("all 5 status colours distinct", len(colors) == 5, f"{len(colors)} unique")

    print("\n3. Tooltip length limit (Windows drops tooltips over 127 chars)")
    app = tray_app.TrayApp.__new__(tray_app.TrayApp)
    # Built via __new__ to skip the constructor, so every attribute the
    # methods touch has to be set by hand.
    app._icon = None
    app._status = "active"
    app._monitor = None
    app._applied = set()
    app._watcher = None
    app._settings_window = None
    long_tip = app._tooltip()
    check("idle tooltip within 120", len(long_tip) <= 120, f"{len(long_tip)} chars")

    class FakeState:
        streaming = True
        width, height = 1280, 960
        app = "x" * 200
        @property
        def resolution(self):
            return f"{self.width}x{self.height}"

    class FakeMonitor:
        state = FakeState()

    app._monitor = FakeMonitor()
    tip = app._tooltip()
    check("long tooltip truncated", len(tip) <= 120, f"{len(tip)} chars")

    print("\n4. Log state machine")
    with tempfile.TemporaryDirectory() as tmp:
        logfile = Path(tmp) / "sunshine.log"
        logfile.write_text("old session\nCLIENT CONNECTED\n", encoding="utf-8")

        seen = []
        monitor = stream_monitor.LogMonitor(logfile, lambda s: seen.append(s.streaming))

        # Historical lines must be ignored: the tail starts at EOF.
        monitor.scan_once()
        check("history ignored on start", len(seen) == 0, f"events={seen}")

        with open(logfile, "a", encoding="utf-8") as fh:
            fh.write("Executing: [steam://open/bigpicture] in []\n")
            fh.write("Client requested stream resolution (clientViewport): 1280x960\n")
            fh.write("CLIENT CONNECTED\n")
        monitor.scan_once()
        check("detects stream start", monitor.state.streaming is True)
        check("captures resolution", monitor.state.resolution == "1280x960",
              monitor.state.resolution)
        check("captures app", "steam://open" in monitor.state.app, monitor.state.app)

        with open(logfile, "a", encoding="utf-8") as fh:
            fh.write("CLIENT DISCONNECTED\n")
            fh.write("Stopping streaming session 1\n")
        monitor.scan_once()
        check("detects stream end", monitor.state.streaming is False)

        monitor.stop()

    print("\n5. Config round-trip (in a temp APPDATA, nothing real touched)")
    real_appdata = os.environ.get("APPDATA")
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["APPDATA"] = tmp
        try:
            cfg = tray_app.load_config()
            check("defaults when absent", cfg["enabled"] is True
                  and cfg["max_client_width"] == 1600)

            cfg["enabled"] = False
            cfg["clients"] = {"X35S": {"brotato_font_size": 2.0}}
            path = tray_app.save_config(cfg)
            check("config written", path.exists(), str(path))

            again = tray_app.load_config()
            check("enabled persisted", again["enabled"] is False)
            check("clients persisted",
                  again["clients"]["X35S"]["brotato_font_size"] == 2.0)

            # Unknown keys must not leak into the file.
            on_disk = json.loads(path.read_text(encoding="utf-8"))
            check("only known keys stored",
                  set(on_disk) == set(tray_app.DEFAULT_CONFIG),
                  str(sorted(on_disk)))
        finally:
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
