"""Configuration: which games to touch, and how.

Config precedence (later wins):
    1. built-in defaults below
    2. %APPDATA%/StreamScale/config.json
    3. per-client overrides inside that file

The file is optional. With no config at all StreamScale still works using
the adapter's own heuristics, which is what makes first-run painless.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_CONFIG_DIR = Path(
    os.path.expandvars("%APPDATA%/StreamScale")
) if os.name == "nt" else Path.home() / ".config" / "streamscale"

DEFAULT_CONFIG_NAME = "config.json"


@dataclass
class Config:
    # Master switch. Handy for "turn it off for now" without uninstalling.
    enabled: bool = True

    # Apps listed here are never touched, even if an adapter matches.
    # Useful for players who want to keep the desktop look while streaming.
    excluded_apps: List[str] = field(default_factory=list)

    # Only apply when the client resolution is at or below this width.
    # Guards against scaling up a big-screen client by mistake.
    max_client_width: int = 1600

    # Per-client overrides: {"X35S": {"brotato_font_size": 2.0}}
    clients: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Where backups live. Empty means the default (~/.streamscale).
    state_dir: str = ""

    # Extra log verbosity.
    verbose: bool = False

    # Multiplier applied on top of the adapter's own font-size heuristic, so
    # the settings window can fine-tune without touching adapter code.
    # 1.0 keeps the heuristic as-is.
    #
    # This lives here, not in the tray, because the process that actually
    # applies a profile is the one Sunshine launches as a prep-command -- a
    # separate invocation that never loads the tray. Keeping it in the tray
    # meant the slider wrote a value nothing read, so dragging it did
    # nothing at all.
    font_scale: float = 1.0

    # How to handle a game whose layout does not match the client's shape:
    #   "off"     - leave the game's own aspect alone (black bars)
    #   "expand"  - enlarge the render area at the same scale: fills the
    #               screen, adds visible play area, no cropping or distortion
    #   "stretch" - scale to fill exactly, which distorts the image
    # Read by the same process as font_scale, for the same reason.
    aspect_fill: str = "off"

    # ------------------------------------------------------------------

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Config":
        path = path or (DEFAULT_CONFIG_DIR / DEFAULT_CONFIG_NAME)
        if not path.exists():
            return cls()

        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, json.JSONDecodeError):
            # A broken config must not break streaming; fall back to defaults
            # and let the caller log the problem.
            return cls()

        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def state_dir_path(self) -> Optional[Path]:
        return Path(os.path.expandvars(self.state_dir)) if self.state_dir else None

    # ------------------------------------------------------------------

    def is_excluded(self, app_name: str) -> bool:
        key = app_name.strip().casefold()
        return any(key == e.strip().casefold() for e in self.excluded_apps)

    def override_for(self, client_name: str, key: str) -> Any:
        """Look up a per-client override, e.g. client "X35S", key
        "brotato_font_size". Returns None when absent."""
        entry = self.clients.get(client_name)
        if not isinstance(entry, dict):
            return None
        return entry.get(key)

    def save(self, path: Optional[Path] = None) -> Path:
        """Write the config out, creating the directory if needed."""
        path = path or (DEFAULT_CONFIG_DIR / DEFAULT_CONFIG_NAME)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {k: getattr(self, k) for k in self.__dataclass_fields__}
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        return path
