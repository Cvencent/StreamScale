"""Self-check: the executable can serve as a Sunshine prep-command.

This guards a failure that cost a real streaming session. Sunshine was
pointed at a copy of the tray exe, which did not understand `apply`:

    "C:\\...\\Downloads\\StreamScale.exe" apply

The exe treated it as an ordinary launch, started a second tray, and hit the
single-instance guard. Sunshine waits for its prep-command to exit, so:

    the session teardown stalled for five and a half minutes
    the client showed an empty desktop (reported as a black screen)
    the virtual display was never torn down or restored (reported as a
    phantom second monitor)

None of it was visible as an error. The lesson is that "a command that runs
but never exits" is worse than "a command that fails", which is why an
unknown verb now exits non-zero instead of falling back to a tray.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(PROJECT / "src"))

failures = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f"  -- {detail}" if detail else ""))
    if not condition:
        failures.append(label)


# Runs in a child process, with an isolated log directory so a self-check
# never writes into a real installation's log.
#
# The child is invoked as a *script file*, not with -c, because `python -c
# prog args...` puts args in sys.argv[1:] only when there is no script --
# with -c the extra words land after the program text and argv comes out
# wrong, which silently made every case look like "no arguments".
CHILD = r"""
import sys, os
os.environ["LOCALAPPDATA"] = r"{localappdata}"
os.environ["APPDATA"] = r"{appdata}"
# Pretend Sunshine launched us, so the CLI does real work instead of
# taking the "no session" path and exiting immediately.
os.environ["SUNSHINE_APP_NAME"] = "Brotato"
os.environ["SUNSHINE_CLIENT_NAME"] = "X35S"
os.environ["SUNSHINE_CLIENT_WIDTH"] = "1280"
os.environ["SUNSHINE_CLIENT_HEIGHT"] = "960"
os.environ["STREAMSCALE_GAME_DIR"] = r"{gamedir}"
# Keep the tray away from the real Sunshine log, so a launched copy
# cannot decide a stream is running and apply profiles for real.
os.environ["STREAMSCALE_SUNSHINE_LOG"] = r"{sunshinelog}"
os.environ["STREAMSCALE_LOG_DIR"] = r"{logdir}"
sys.path.insert(0, r"{runtime}")
sys.path.insert(0, r"{src}")
import tray_app
code = tray_app.run_cli(sys.argv)
print("RESULT|%s" % ("tray" if code is None else code))
"""

_child_script: Path | None = None
_game_settings: Path | None = None


def run_cli(extra_args: list, localappdata: Path) -> str:
    """Drive run_cli in a fresh interpreter and report what it returned.

    `extra_args` are the words that follow the program name, i.e. what the
    child sees as sys.argv[1:]. Passing the program name too would shift
    everything by one and make every case look like an unknown verb.
    """
    global _child_script

    if _child_script is None or _child_script.parent != localappdata:
        appdata = localappdata / "appdata"
        appdata.mkdir(parents=True, exist_ok=True)
        # A stand-in game directory so the adapter has somewhere to write.
        gamedir = localappdata / "game"
        gamedir.mkdir(parents=True, exist_ok=True)
        (gamedir / "Brotato.exe").write_bytes(b"")

        # Give the adapter a settings file to modify.
        game_cfg = appdata / "Brotato" / "123"
        game_cfg.mkdir(parents=True, exist_ok=True)
        (game_cfg / "settings.json").write_text(
            '{"settings": {"font_size": 1, "fullscreen": true}}', encoding="utf-8")

        _child_script = localappdata / "_cli_child.py"
        _child_script.write_text(
            CHILD.format(localappdata=str(localappdata), appdata=str(appdata),
                         gamedir=str(gamedir),
                         sunshinelog=str(localappdata / "sunshine.log"),
                         logdir=str(localappdata / "StreamScale"),
                         runtime=str(HERE), src=str(PROJECT / "src")),
            encoding="utf-8")
        global _game_settings
        _game_settings = game_cfg / "settings.json"

    exe = os.environ.get("PYTHON_EXE") or sys.executable
    proc = subprocess.run([exe, str(_child_script)] + list(extra_args),
                          capture_output=True, text=True, timeout=90)
    for line in (proc.stdout or "").splitlines():
        if line.startswith("RESULT|"):
            return line.split("|", 1)[1]
    return f"NO-RESULT rc={proc.returncode} {(proc.stderr or '')[-180:]}"


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        logs = Path(tmp) / "localappdata"
        logs.mkdir()

        print("\n1. Verb recognition")
        # These must reach the CLI and exit. `--help` and `-h` leave through
        # argparse's SystemExit, which prints usage but never reaches the
        # RESULT line, so rc=0 with no RESULT is the correct outcome there.
        for args, label in ((["apply"], "apply is a command"),
                            (["revert"], "revert is a command"),
                            (["show"], "show is a command"),
                            (["--help"], "--help is handled"),
                            (["-h"], "-h is handled")):
            result = run_cli(args, logs)
            if result.startswith("NO-RESULT"):
                # Acceptable only when the child exited cleanly.
                good = "rc=0" in result
            else:
                good = result != "tray"
            check(label, good, f"{args} -> {result}")

        print("\n2. An unknown verb must fail, never start a tray")
        # This is the specific regression: falling through to "start the tray"
        # is what made Sunshine wait forever.
        for bad in ("nonsense", "--frobnicate", "-x", "APPLY2"):
            result = run_cli([bad], logs)
            became_tray = result == "tray"
            check(f"{bad!r} does not start a tray", not became_tray,
                  f"-> {result}")

        print("\n3. No arguments still starts the tray")
        # Deliberately run in a child that stops before the tray loop: the
        # recogniser returning None is what is being checked, not the icon.
        result = run_cli([], logs)
        check("bare launch reports 'tray'", result == "tray", f"-> {result}")
        if result != "tray":
            # Surface why, rather than leaving a bare number.
            print(f"        child script: {_child_script}")
            if _child_script and _child_script.exists():
                print("        --- child output ---")
                for line in _child_script.read_text(encoding="utf-8").splitlines()[:12]:
                    print("       ", line)
            print(f"        interpreter used: {os.environ.get('PYTHON_EXE') or sys.executable}")

        print("\n4. apply and revert do real work, then exit")
        # Exit code alone is weak: with no session the CLI exits 0 having
        # done nothing. These run with a Sunshine environment present, so a
        # working command must actually change the game's settings file.
        import json

        result = run_cli(["apply"], logs)
        check("apply exits cleanly", result == "0", f"exit={result}")
        after_apply = json.loads(_game_settings.read_text(encoding="utf-8"))
        raised = after_apply["settings"].get("font_size", 1) > 1
        check("apply changed the game settings", raised,
              f"font_size={after_apply['settings'].get('font_size')}")

        result = run_cli(["revert"], logs)
        check("revert exits cleanly", result == "0", f"exit={result}")
        after_revert = json.loads(_game_settings.read_text(encoding="utf-8"))
        check("revert put the settings back",
              after_revert["settings"].get("font_size") == 1,
              f"font_size={after_revert['settings'].get('font_size')}")

        result = run_cli(["show"], logs)
        check("show exits cleanly", result == "0", f"exit={result}")
        after_show = json.loads(_game_settings.read_text(encoding="utf-8"))
        check("show changed nothing", after_show == after_revert)

        print("\n5. The settings window generates a working command")
        sys.path.insert(0, str(HERE))
        import settings_window
        sys.argv = ["StreamScale.exe"]
        from streamscale import registry  # noqa: F401  (import path sanity)
        check("_supports_cli exists", hasattr(settings_window, "_supports_cli"))
        # A real system exe has no CLI verbs and must be reported as such.
        notepad = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "notepad.exe"
        if notepad.exists():
            check("a plain exe is rejected as a prep command",
                  settings_window._supports_cli(notepad) is False)
        check("a missing exe is rejected",
              settings_window._supports_cli(Path("nope.exe")) is False)

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {failures}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
