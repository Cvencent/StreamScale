"""Adapter base class: the extension point for per-game support.

An adapter owns exactly one game (or one family of games that share a
settings file format) and knows three things:

    read()    -> current state, as a dict
    apply()   -> switch to the streaming profile
    revert()  -> restore the state captured before apply()

The base class handles the fiddly parts that every adapter would otherwise
re-implement: atomic writes, backups, and dry-run behaviour. Subclasses
only describe *what* to change, not *how* to write it safely.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from .env import Session


class AdapterError(RuntimeError):
    """Raised when an adapter cannot do its job; callers treat it as fatal
    for this game but never for the whole run."""


@dataclass
class ApplyResult:
    """Outcome of an apply()/revert() call, for logging and the CLI."""

    changed: bool = False
    detail: str = ""
    warnings: list = field(default_factory=list)


class GameAdapter(ABC):
    """Common behaviour for all game adapters.

    Subclasses implement `read_state` / `write_state` against a settings
    file plus the two abstract hooks below. That keeps atomicity, backups
    and dry-run in one place.
    """

    #: Human readable name, shown in logs.
    name: str = "unnamed"

    #: Other names the game may be listed under in Sunshine.
    aliases: tuple = ()

    #: Executable names this game runs as (lower case, e.g. "brotato.exe").
    #:
    #: Needed because Sunshine's press commands fire once, when the stream
    #: starts. If the user reaches the game through Steam Big Picture, that
    #: moment happens before the game has launched, so nothing can be applied
    #: yet. The tray watches for these processes instead and applies the
    #: profile once the game actually appears.
    process_names: tuple = ()

    def __init__(self, session: Session, dry_run: bool = False,
                 state_dir: Optional[Path] = None):
        self.session = session
        self.dry_run = dry_run
        self.state_dir = state_dir or Path.home() / ".streamscale"

    # ------------------------------------------------------------------
    # Hooks for subclasses
    # ------------------------------------------------------------------

    @abstractmethod
    def read_state(self) -> Dict[str, Any]:
        """Return the current, relevant settings as a plain dict."""

    @abstractmethod
    def write_state(self, state: Dict[str, Any]) -> None:
        """Persist `state` back to wherever it came from."""

    @abstractmethod
    def target_state(self, current: Dict[str, Any]) -> Dict[str, Any]:
        """Return the state this game should have while streaming."""

    # ------------------------------------------------------------------
    # Backup / restore plumbing
    # ------------------------------------------------------------------

    @property
    def backup_path(self) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in self.session.app_name)
        return self.state_dir / f"{safe}.json"

    def save_backup(self, state: Dict[str, Any]) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.backup_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"app": self.session.app_name, "state": state}, fh,
                      ensure_ascii=False, indent=2)
        os.replace(tmp, self.backup_path)

    def load_backup(self) -> Optional[Dict[str, Any]]:
        if not self.backup_path.exists():
            return None
        try:
            with open(self.backup_path, encoding="utf-8") as fh:
                return json.load(fh).get("state")
        except (OSError, json.JSONDecodeError):
            return None

    def clear_backup(self) -> None:
        try:
            self.backup_path.unlink()
        except FileNotFoundError:
            pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def apply(self) -> ApplyResult:
        """Switch to the streaming profile, remembering the previous state."""
        current = self.read_state()
        want = self.target_state(current)

        if current == want:
            return ApplyResult(changed=False, detail="already at target state")

        self.save_backup(current)
        if self.dry_run:
            return ApplyResult(changed=False,
                               detail=f"[dry-run] would set {want}")

        self.write_state(want)
        return ApplyResult(changed=True, detail=f"{current} -> {want}")

    def revert(self) -> ApplyResult:
        """Restore the state captured by the last apply()."""
        saved = self.load_backup()
        if saved is None:
            return ApplyResult(changed=False, detail="no backup to restore")

        if self.dry_run:
            return ApplyResult(changed=False,
                               detail=f"[dry-run] would restore {saved}")

        self.write_state(saved)
        self.clear_backup()
        return ApplyResult(changed=True, detail=f"restored {saved}")


# ----------------------------------------------------------------------
# JSON settings adapters (the common case)
# ----------------------------------------------------------------------

class JsonFileAdapter(GameAdapter):
    """Base for games whose settings live in a single JSON file.

    Subclasses point `settings_path` at the file and pick the keys they
    care about. Writes are atomic (temp file + replace) so a crash mid-write
    cannot leave a half-written save behind.
    """

    #: Path to the JSON file, resolved at call time (may use %APPDATA%).
    settings_path_template: str = ""

    def settings_path(self) -> Path:
        if not self.settings_path_template:
            raise AdapterError(f"{type(self).__name__} has no settings_path_template")
        return Path(os.path.expandvars(self.settings_path_template))

    # Which top-level object holds the interesting keys. Some games nest
    # under a "settings" key, others are flat.
    container_key: Optional[str] = None

    def _load(self) -> Dict[str, Any]:
        path = self.settings_path()
        if not path.exists():
            raise AdapterError(f"settings file not found: {path}")
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            raise AdapterError(f"cannot parse {path}: {exc}") from exc

    def read_state(self) -> Dict[str, Any]:
        data = self._load()
        if self.container_key:
            return dict(data.get(self.container_key, {}))
        return dict(data)

    def write_state(self, state: Dict[str, Any]) -> None:
        path = self.settings_path()
        data = self._load()
        if self.container_key:
            data[self.container_key] = state
        else:
            data = state
        self._atomic_write(path, data)

    @staticmethod
    def _atomic_write(path: Path, data: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=None,
                          separators=(",", ":"))
            shutil.copymode(path, tmp) if path.exists() else None
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
