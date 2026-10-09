"""Self-check: the autostart registry entry round-trips correctly.

The entry lives in HKCU, so this needs no administrator rights and can run
anywhere. Two things it must not do:

  * leave an entry behind, which would be a surprising side effect of running
    a check; and
  * overwrite a correct entry with a wrong one.

The second is subtler and was happening. The check recorded only whether
autostart was enabled, then restored it by calling `set_autostart(True)` --
which builds the command from *the running process*. Run from a checkout,
that is `pythonw.exe tray_app.py`, so a working install that pointed at
`StreamScale.exe` came back pointing at the source tree. The entry still read
as "enabled", so the check passed while quietly breaking autostart for
anyone who ran it.

The original command is captured and written back verbatim now, so the check
restores what was there rather than what it would have created.
"""

from __future__ import annotations

import sys
import winreg
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "StreamScale"


def read_command() -> str | None:
    """The exact command string, or None when the entry is absent."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return winreg.QueryValueEx(key, RUN_VALUE)[0]
    except OSError:
        return None


def write_command(command: str | None) -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if command is None:
            try:
                winreg.DeleteValue(key, RUN_VALUE)
            except OSError:
                pass
        else:
            winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, command)


def main() -> int:
    import tray_app

    failures = []

    print("1. Capture the entry exactly as it is")
    original = read_command()
    print(f"   {original!r}")

    print("\n2. The command this process would build looks sane")
    cmd = tray_app._command_path()
    looks_ok = "StreamScale" in cmd or "tray_app" in cmd
    print(f"  [{'PASS' if looks_ok else 'FAIL'}] {cmd}")
    if not looks_ok:
        failures.append("command path")

    # Run the whole round-trip inside a try/finally: an assertion or a crash
    # halfway through must not leave the user's autostart changed.
    try:
        print("\n3. Enable -> reads back as enabled")
        tray_app.set_autostart(True)
        enabled = tray_app.autostart_enabled()
        print(f"  [{'PASS' if enabled else 'FAIL'}] enabled={enabled}")
        if not enabled:
            failures.append("enable")

        print("\n4. Disable -> reads back as disabled")
        tray_app.set_autostart(False)
        disabled = tray_app.autostart_enabled()
        print(f"  [{'PASS' if not disabled else 'FAIL'}] enabled={disabled}")
        if disabled:
            failures.append("disable")
    finally:
        print("\n5. Restore the original command verbatim")
        write_command(original)
        restored = read_command()
        ok = restored == original
        print(f"  [{'PASS' if ok else 'FAIL'}] restored={restored!r}")
        if not ok:
            failures.append("restore")

    print("\n6. A pre-existing entry was not rewritten")
    # The regression that made this necessary: restoring via set_autostart()
    # replaced a correct command with this process's own. Restoring verbatim
    # means an entry pointing at the installed build survives the check.
    print(f"   original : {original!r}")
    print(f"   restored : {restored!r}")
    same = restored == original
    print(f"  [{'PASS' if same else 'FAIL'}] unchanged")
    if not same:
        failures.append("entry rewritten")

    print()
    if failures:
        print(f"FAILED: {failures}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
