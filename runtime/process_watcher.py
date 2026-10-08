"""Watch for game processes starting and stopping.

Why this exists
---------------
Sunshine's press commands fire exactly once, when a stream begins. If the
user reaches a game through Steam Big Picture, that moment arrives while
Steam is still starting up -- the game has not launched, so there is nothing
to configure yet. Applying the profile then would do nothing.

The tray is already resident, so it can watch instead: poll the process list
while a stream is running and apply the profile when the game appears,
reverting when it exits.

Why polling rather than WMI or ETW
----------------------------------
Enumerating process names is a few milliseconds and runs at a one-second
interval. WMI event subscriptions are heavier, need a COM apartment on the
right thread, and behave inconsistently across systems; the simplicity here
is worth far more than the CPU it saves.

Restarts are handled deliberately
---------------------------------
If the game is closed and reopened inside the same stream (a common thing to
do after changing a setting), the watcher applies again. The revert only
happens when the stream ends or the game exits, whichever comes first.
"""

from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Poll cadence. One second is responsive enough for "I launched the game and
# want the text readable", and imperceptible in CPU terms.
POLL_INTERVAL = 1.0


def running_processes() -> Set[str]:
    """Return the lower-case names of all running processes.

    Uses tasklist because it ships with Windows. Note the encoding: on a
    Chinese Windows the output is GBK, and decoding it as UTF-8 raises
    UnicodeDecodeError -- which would look like the watcher is broken
    rather than like an encoding mismatch.
    """
    try:
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True,
            encoding="gbk", errors="replace",
            creationflags=CREATE_NO_WINDOW,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return set()

    names: Set[str] = set()
    for line in (result.stdout or "").splitlines():
        # CSV rows look like: "Brotato.exe","1234","Console","1","123,456 K"
        line = line.strip()
        if not line.startswith('"'):
            continue
        end = line.find('"', 1)
        if end > 1:
            names.add(line[1:end].lower())
    return names


@dataclass
class GameWatch:
    """Tracks which watched games are currently running."""

    processes: Dict[str, Callable[[str], None]] = field(default_factory=dict)
    running: Set[str] = field(default_factory=set)


class ProcessWatcher:
    """Polls for watched processes and reports appearances and exits.

    Only active while `active` is True, so it costs nothing when no stream is
    running -- there is no reason to scan the process list while the user is
    at their desk.
    """

    def __init__(self,
                 on_start: Callable[[str], None],
                 on_exit: Callable[[str], None],
                 poll_interval: float = POLL_INTERVAL):
        self.on_start = on_start
        self.on_exit = on_exit
        self.poll_interval = poll_interval

        self._watched: Dict[str, str] = {}     # lower-case exe -> display name
        self._running: Set[str] = set()
        self._active = False
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------

    def watch(self, process_name: str, display_name: str) -> None:
        self._watched[process_name.strip().lower()] = display_name

    @property
    def watched(self) -> List[str]:
        return sorted(self._watched)

    def set_active(self, active: bool) -> None:
        """Enable or disable scanning. Entering idle clears the seen set so
        a later stream starts from a clean slate."""
        with self._lock:
            if active == self._active:
                return
            self._active = active
            if not active:
                self._running.clear()

    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="proc-watcher",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=3)
        self._stop.clear()

    # ------------------------------------------------------------------

    def poll_once(self) -> None:
        """One scan. Separated from the loop so tests can drive it."""
        with self._lock:
            if not self._active or not self._watched:
                return
            watched = dict(self._watched)

        present = running_processes() & set(watched)
        newly_running = present - self._running
        stopped = self._running - present

        for name in sorted(newly_running):
            try:
                self.on_start(watched[name])
            except Exception:
                pass
        for name in sorted(stopped):
            try:
                self.on_exit(watched[name])
            except Exception:
                pass

        self._running = present

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception:
                pass
            self._stop.wait(self.poll_interval)
