"""Shared test isolation for the self-checks.

Why this module exists
----------------------
The self-checks launch the real tray executable to see how it behaves. A
launched tray does not stay passive: it tails Sunshine's log, and when it
decides a stream has started it *applies* the scaling profile -- writing to
the real game configuration under %APPDATA%.

Setting only STREAMSCALE_GAME_DIR is not enough. One check did that, the tray
found a session in the real Sunshine log, and the user's Brotato settings
were changed to handheld font sizes while they were not streaming. Nothing
reported an error; it was noticed only because a later check compared the
value.

So every check that starts a process must point the app away from the real
machine. `isolated_env()` does that in one place, and any variable the tray
can act on belongs in it.

Usage:
    from _testenv import isolated_env

    tmp = Path(tempfile.mkdtemp())
    env = isolated_env(tmp)
    subprocess.Popen([str(exe)], env=env, ...)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional


def isolated_env(tmp: Path, sunshine_log: Optional[Path] = None) -> Dict[str, str]:
    """An environment in which a launched copy cannot touch the real machine.

    Every path the application can write to is redirected under `tmp`:

        APPDATA            game settings and the config file
        LOCALAPPDATA       logs
        STREAMSCALE_GAME_DIR   adapter target, when a Sunshine app name is set
        STREAMSCALE_SUNSHINE_LOG   the log it tails to detect a session
        STREAMSCALE_LOG_DIR        this app's own log

    The Sunshine log matters most. It is what the tray watches to decide a
    stream has begun, and leaving it pointed at the real file makes the tray
    apply profiles for real.

    A Sunshine app name is also set, because the interesting code paths only
    run when the tray believes a client is connected -- and a test that
    exercises nothing proves nothing.
    """
    tmp = Path(tmp)
    appdata = tmp / "appdata"
    localappdata = tmp / "local"
    gamedir = tmp / "game"
    for directory in (appdata, localappdata, gamedir):
        directory.mkdir(parents=True, exist_ok=True)

    # An empty log: no session, so nothing is applied unless the test says so.
    if sunshine_log is None:
        sunshine_log = tmp / "sunshine.log"
        sunshine_log.write_text("", encoding="utf-8")

    # A stand-in game so an adapter has somewhere to write.
    (gamedir / "Brotato.exe").write_bytes(b"")
    game_cfg = appdata / "Brotato" / "123"
    game_cfg.mkdir(parents=True, exist_ok=True)
    (game_cfg / "settings.json").write_text(
        '{"settings": {"font_size": 1, "fullscreen": true}}', encoding="utf-8")

    env = dict(os.environ)
    env["APPDATA"] = str(appdata)
    env["LOCALAPPDATA"] = str(localappdata)
    env["STREAMSCALE_GAME_DIR"] = str(gamedir)
    env["STREAMSCALE_SUNSHINE_LOG"] = str(sunshine_log)
    env["STREAMSCALE_LOG_DIR"] = str(localappdata / "StreamScale")

    env["SUNSHINE_APP_NAME"] = "Brotato"
    env["SUNSHINE_CLIENT_NAME"] = "X35S"
    env["SUNSHINE_CLIENT_WIDTH"] = "1280"
    env["SUNSHINE_CLIENT_HEIGHT"] = "960"

    return env


def game_settings(env: Dict[str, str]) -> Path:
    """The settings file the adapter writes, for the given environment."""
    return Path(env["APPDATA"]) / "Brotato" / "123" / "settings.json"


def real_game_settings() -> Path:
    """Where the adapter writes on the real machine.

    Only for asserting that a test did *not* touch it.
    """
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    return Path(appdata) / "Brotato"

def self_install_record(tmp: Path, exe: Path) -> Path:
    """Make a launched copy believe it *is* the installation.

    Every start asks "am I the installed build, or a package someone opened?"
    and an unanswered question has consequences: a copy that thinks it is an
    upgrade candidate either installs itself somewhere or exits to avoid
    downgrading. Either way it does not show a tray, which is what the
    behaviour checks are trying to observe.

    Writing the record so it names the executable under test removes the
    ambiguity, and keeps the check focused on the behaviour it means to test
    rather than on the update logic.

    Returns the path of the record written.
    """
    import json

    appdata = Path(env_appdata(tmp))
    target = Path(exe).resolve()
    record = appdata / "StreamScale" / "install.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps({"exe": str(target),
                                  "folder": str(target.parent)}, indent=2),
                      encoding="utf-8")
    return record


def env_appdata(tmp: Path) -> Path:
    """The APPDATA that isolated_env() would use for this temporary root."""
    return Path(tmp) / "appdata"
