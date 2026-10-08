"""Self-check: the process watcher detects games launched via Steam.

This covers the case the press commands cannot handle. Sunshine runs its
commands when the stream starts, which -- when the user goes through Steam
Big Picture -- is before the game exists. Watching for the process is the
only way to catch it, so this logic carries the whole feature.

The fake process is a real one (a sleeping Python), renamed only in the
watcher's view, so nothing needs to be installed.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

failures = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f"  -- {detail}" if detail else ""))
    if not condition:
        failures.append(label)


def main() -> int:
    import process_watcher

    print("\n1. Process enumeration works")
    names = process_watcher.running_processes()
    detail = f"{len(names)} processes"
    if not names and process_watcher.last_error:
        # A failure here used to just say "0 processes", which is
        # indistinguishable from a broken parser. Surface the reason.
        detail += f"  [last_error: {process_watcher.last_error}]"
    check("found processes", len(names) > 0, detail)
    check("names are lower case", all(n == n.lower() for n in names))
    check("includes our own interpreter",
          any("python" in n for n in names),
          next((n for n in names if "python" in n), "none"))

    print("\n2. GBK decoding on a Chinese Windows")
    # tasklist emits GBK here; decoding as UTF-8 would raise and look like a
    # watcher bug rather than an encoding mismatch.
    result = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                            capture_output=True, text=True,
                            encoding="gbk", errors="replace", timeout=15)
    check("tasklist decoded without error", result.returncode == 0)
    check("no replacement characters leaked into names",
          "\ufffd" not in result.stdout[:2000])

    print("\n3. Registry exposes process names")
    from streamscale import registry
    procs = registry.watched_processes()
    check("at least one process watched", len(procs) > 0, str(procs))
    cls = registry.find_by_process("brotato.exe")
    check("brotato.exe resolves", cls is not None and cls.name == "Brotato",
          getattr(cls, "name", None))
    check("lookup is case insensitive",
          registry.find_by_process("BROTATO.EXE") is cls)
    check("unknown process returns None",
          registry.find_by_process("definitely-not-a-game.exe") is None)

    print("\n4. Watcher fires on start and exit")
    started, exited = [], []
    watcher = process_watcher.ProcessWatcher(
        on_start=started.append, on_exit=exited.append, poll_interval=0.3)

    # Watch for python.exe, which is running right now (this test).
    watcher.watch("python.exe", "TestGame")

    print("   inactive: must not fire")
    watcher.poll_once()
    check("silent while inactive", not started and not exited)

    print("   activate: the process already exists, so it should be seen")
    watcher.set_active(True)
    watcher.poll_once()
    check("started reported", started == ["TestGame"], str(started))

    print("   second poll: no duplicate event")
    watcher.poll_once()
    check("no duplicate start", started == ["TestGame"], str(started))

    print("   deactivate: seen set is cleared")
    watcher.set_active(False)
    watcher.set_active(True)
    watcher.poll_once()
    check("re-reported after a fresh activation",
          len(started) == 2, str(started))

    print("\n5. Exit is detected when the process goes away")
    exited.clear()
    watcher._watched = {"no-such-process-xyz.exe": "Ghost"}
    watcher._running = {"no-such-process-xyz.exe"}
    watcher.poll_once()
    check("exit reported", exited == ["Ghost"], str(exited))

    print("\n6. Threaded mode starts and stops cleanly")
    watcher2 = process_watcher.ProcessWatcher(lambda n: None, lambda n: None,
                                              poll_interval=0.2)
    watcher2.watch("python.exe", "TestGame")
    watcher2.set_active(True)
    watcher2.start()
    time.sleep(0.6)
    alive = watcher2._thread.is_alive() if watcher2._thread else False
    check("thread running", alive)
    watcher2.stop()
    time.sleep(0.3)
    stopped = not (watcher2._thread and watcher2._thread.is_alive())
    check("thread stopped", stopped)

    print("\n7. A failing callback must not kill the watcher")
    def boom(_name):
        raise RuntimeError("deliberate")
    watcher3 = process_watcher.ProcessWatcher(boom, boom, poll_interval=0.2)
    watcher3.watch("python.exe", "TestGame")
    watcher3.set_active(True)
    try:
        watcher3.poll_once()
        survived = True
    except Exception as exc:
        survived = False
        print(f"        raised {exc!r}")
    check("exception swallowed", survived)

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {failures}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
