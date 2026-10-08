"""Detect whether a Sunshine stream is active, by tailing its log.

Why the log and not the API
---------------------------
Sunshine exposes a web API, but reaching it needs the user's credentials and
a TLS session, and the endpoint set differs between upstream Sunshine and
the forks people actually run. The log file is plain text, needs no auth,
and is written by every build. Reading it is boring and it works.

The monitor tails the file and applies a simple state machine:

    CLIENT CONNECTED        -> streaming
    stream stopped / quit   -> idle

It also notices the resolution line, so the tray tooltip can show what the
client asked for -- useful when a user wants to know whether their handheld
is really requesting the mode they configured.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

# Lines that mean "a session started".
_START_PATTERNS = [
    re.compile(r"CLIENT CONNECTED", re.I),
    re.compile(r"New streaming session started", re.I),
]

# Lines that mean "a session finished".
_STOP_PATTERNS = [
    re.compile(r"CLIENT DISCONNECTED", re.I),
    re.compile(r"Stopping streaming session", re.I),
    re.compile(r"stopping all streaming sessions", re.I),
]

# The resolution the client asked for, e.g.
# "Client requested stream resolution (clientViewport): 1280x960"
_RESOLUTION = re.compile(r"Client requested stream resolution.*?:\s*(\d+)x(\d+)", re.I)

# Which app is streaming, e.g. 'Executing: [steam://open/bigpicture]'
_APP = re.compile(r"Executing:\s*\[([^\]]+)\]", re.I)


@dataclass
class StreamState:
    """Everything the tray needs to render and describe the current state."""

    streaming: bool = False
    width: int = 0
    height: int = 0
    app: str = ""
    last_change: float = field(default_factory=time.time)

    @property
    def resolution(self) -> str:
        if self.width and self.height:
            return f"{self.width}x{self.height}"
        return ""

    def same_as(self, other: "StreamState") -> bool:
        return (self.streaming == other.streaming
                and self.width == other.width
                and self.height == other.height
                and self.app == other.app)


class LogMonitor:
    """Tail a log file and report state changes.

    Tailing starts at the end of the file: we care about what happens from
    now on, not about the history that was already there when the app
    started. That avoids showing "streaming" on launch just because a
    session happened yesterday.

    The file is re-opened when its inode or size shrinks, which is what
    happens when Sunshine rotates or truncates it.
    """

    def __init__(self, log_path: Path, on_change: Callable[[StreamState], None],
                 poll_interval: float = 1.0):
        self.log_path = Path(log_path)
        self.on_change = on_change
        self.poll_interval = poll_interval

        self._state = StreamState()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._handle = None
        self._size = 0

    # ------------------------------------------------------------------

    @property
    def state(self) -> StreamState:
        return self._state

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="log-monitor",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=3)
        self._close()

    # ------------------------------------------------------------------

    def _close(self) -> None:
        if self._handle:
            try:
                self._handle.close()
            except OSError:
                pass
            self._handle = None

    def _open_at_end(self) -> bool:
        """Open the log, positioned at its current end."""
        self._close()
        try:
            self._handle = open(self.log_path, "r", encoding="utf-8", errors="replace")
        except OSError:
            return False
        try:
            self._handle.seek(0, 2)
            self._size = self._handle.tell()
        except OSError:
            self._size = 0
        return True

    def scan_once(self) -> bool:
        """Read whatever is new and update state. Returns True if it changed.

        Exposed separately from the loop so tests can drive it directly
        without waiting on threads.
        """
        if not self.log_path.exists():
            self._close()
            return self._set_state(streaming=False)

        if self._handle is None:
            if not self._open_at_end():
                return False

        changed = False
        try:
            where = self._handle.tell()
            self._handle.seek(0, 2)
            size = self._handle.tell()
            if size < where:
                # Truncated or rotated: restart from the beginning.
                self._handle.seek(0)
            self._handle.seek(where)

            for line in self._handle:
                if self._apply_line(line):
                    changed = True
        except OSError:
            self._close()
            return False

        return changed

    def _apply_line(self, line: str) -> bool:
        if any(p.search(line) for p in _START_PATTERNS):
            width, height = self._state.width, self._state.height
            app = self._state.app
            return self._set_state(streaming=True, width=width,
                                   height=height, app=app)

        if any(p.search(line) for p in _STOP_PATTERNS):
            return self._set_state(streaming=False)

        m = _RESOLUTION.search(line)
        if m:
            return self._set_state(streaming=self._state.streaming,
                                   width=int(m.group(1)), height=int(m.group(2)),
                                   app=self._state.app)

        m = _APP.search(line)
        if m:
            return self._set_state(streaming=self._state.streaming,
                                   app=m.group(1).strip())

        return False

    def _set_state(self, **kwargs) -> bool:
        """Mutate state and notify if anything actually changed."""
        candidate = StreamState(
            streaming=kwargs.get("streaming", self._state.streaming),
            width=kwargs.get("width", self._state.width),
            height=kwargs.get("height", self._state.height),
            app=kwargs.get("app", self._state.app),
        )
        if candidate.same_as(self._state):
            return False
        self._state = candidate
        try:
            self.on_change(self._state)
        except Exception:
            # A failing callback must not kill the monitor thread.
            pass
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.scan_once()
            except Exception:
                pass
            self._stop.wait(self.poll_interval)


def find_sunshine_log() -> Optional[Path]:
    """Locate Sunshine's log on this machine.

    The installer puts it under Program Files; portable builds keep it beside
    the executable. Both are checked.

    STREAMSCALE_SUNSHINE_LOG overrides the search. That exists for testing
    (point the app at a scratch file so a self-check never touches the real
    log) and for unusual installs the search would not find.
    """
    import os

    override = os.environ.get("STREAMSCALE_SUNSHINE_LOG")
    if override:
        path = Path(override)
        return path if path.exists() else None

    candidates: List[Path] = []

    for env in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(env)
        if base:
            candidates.append(Path(base) / "Sunshine" / "config" / "sunshine.log")

    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "Sunshine" / "sunshine.log")

    for path in candidates:
        if path.exists():
            return path
    return None
