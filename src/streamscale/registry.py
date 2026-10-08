"""Adapter registry: map a Sunshine app name to the adapter that handles it.

Keeping this as a table (rather than a chain of if/elif) is what makes the
project extensible: a new game is one import plus one entry.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Type

from .adapter import GameAdapter
from .games.brotato import BrotatoAdapter

# Registry of known adapters. Order matters only for tie-breaking.
ADAPTERS: List[Type[GameAdapter]] = [
    BrotatoAdapter,
]


def _norm(text: str) -> str:
    """Normalise a name for matching.

    Sunshine app names are user-controlled and often contain decorations
    ("Brotato (Steam)"). We compare case-folded and stripped of surrounding
    whitespace, and also try a prefix match so decorations do not break it.
    """
    return text.strip().casefold()


_LOOKUP: Dict[str, Type[GameAdapter]] = {}
for _cls in ADAPTERS:
    for _name in (_cls.name, *_cls.aliases):
        _LOOKUP[_norm(_name)] = _cls


def find(app_name: str) -> Optional[Type[GameAdapter]]:
    """Return the adapter class for a Sunshine app name, or None.

    Tries an exact match first, then a prefix match so a trailing suffix
    ("Brotato (Steam)") still resolves. Returns None when nothing matches --
    an unsupported game is normal, not an error.
    """
    if not app_name:
        return None

    key = _norm(app_name)
    if key in _LOOKUP:
        return _LOOKUP[key]

    for known, cls in _LOOKUP.items():
        if key.startswith(known):
            return cls
    return None


def known_names() -> List[str]:
    return sorted(_LOOKUP.keys())


# ----------------------------------------------------------------------
# Lookup by executable name
# ----------------------------------------------------------------------

_PROCESS_LOOKUP: Dict[str, Type[GameAdapter]] = {}
for _cls in ADAPTERS:
    for _proc in getattr(_cls, "process_names", ()) or ():
        _PROCESS_LOOKUP[_proc.strip().lower()] = _cls


def find_by_process(process_name: str) -> Optional[Type[GameAdapter]]:
    """Return the adapter whose game runs as this executable, or None.

    Used by the tray: a game launched from inside Steam Big Picture is
    already running by the time anyone can tell, so matching on the process
    is the only reliable signal. Press commands cannot help there because
    they fire before the game exists.
    """
    if not process_name:
        return None
    return _PROCESS_LOOKUP.get(process_name.strip().lower())


def watched_processes() -> List[str]:
    """Every executable name that any adapter wants watched."""
    return sorted(_PROCESS_LOOKUP)
