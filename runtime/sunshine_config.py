"""Read and modify Sunshine's apps.json safely.

Installing the prep-cmd by hand is the fiddliest part of setting StreamScale
up: the user has to find apps.json, understand its shape, and add a nested
array to every app they want scaled. This module does it for them.

Two rules govern every write here:

1. **Never destroy what we do not understand.** Sunshine supports many app
   fields and forks add more. We load the JSON, modify only the `prep-cmd`
   key, and write everything else back untouched.
2. **Always leave a backup.** The file is recreated by Sunshine from the web
   UI, but users often have a lot of hand-written entries in it.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# The key Sunshine reads for per-app press commands.
PREP_KEY = "prep-cmd"


def find_apps_json() -> Optional[Path]:
    """Locate Sunshine's apps.json on this machine."""
    candidates: List[Path] = []
    for env in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(env)
        if base:
            candidates.append(Path(base) / "Sunshine" / "config" / "apps.json")
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "Sunshine" / "config" / "apps.json")

    for path in candidates:
        if path.exists():
            return path
    return None


def load_apps(path: Path) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    data.setdefault("apps", [])
    if not isinstance(data["apps"], list):
        raise ValueError(f"{path}: 'apps' is not a list")
    return data


def app_names(data: Dict[str, Any]) -> List[str]:
    return [str(a.get("name", "")) for a in data.get("apps", []) if isinstance(a, dict)]


def _atomic_write(path: Path, data: Dict[str, Any]) -> None:
    """Write via a temp file so a crash cannot truncate the real one."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def backup(path: Path) -> Optional[Path]:
    """Copy apps.json aside before the first modification."""
    if not path.exists():
        return None
    target = path.with_suffix(path.suffix + ".streamscale.bak")
    shutil.copy2(path, target)
    return target


def build_prep_commands(apply_command: str, revert_command: str) -> List[Dict[str, str]]:
    return [{"do": apply_command, "undo": revert_command}]


def install_prep(
    path: Path,
    apply_command: str,
    revert_command: str,
    apps: Optional[List[str]] = None,
    dry_run: bool = False,
) -> Tuple[int, List[str]]:
    """Add the prep-cmd to the given apps (or all of them).

    Appends rather than replaces. An app may already carry press commands for
    something else entirely -- discarding those would silently break a user's
    existing setup, so any existing entries are preserved and ours is added
    alongside them.

    Returns (number of apps changed, names of the apps changed). An app that
    already carries our command is left alone and not counted, so running
    this twice is harmless.
    """
    data = load_apps(path)
    wanted = [a.strip().casefold() for a in apps] if apps else None
    ours = build_prep_commands(apply_command, revert_command)

    changed: List[str] = []
    for entry in data.get("apps", []):
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", ""))
        if wanted is not None and name.strip().casefold() not in wanted:
            continue
        if _already_installed(entry, apply_command):
            continue

        existing = entry.get(PREP_KEY)
        if isinstance(existing, list) and existing:
            # Keep whatever the user already had, then add ours.
            entry[PREP_KEY] = list(existing) + ours
        else:
            entry[PREP_KEY] = ours
        changed.append(name)

    if changed and not dry_run:
        backup(path)
        _atomic_write(path, data)

    return len(changed), changed


def uninstall_prep(path: Path, apply_command: str,
                   dry_run: bool = False) -> Tuple[int, List[str]]:
    """Remove our prep-cmd, leaving any other press commands intact."""
    data = load_apps(path)
    removed: List[str] = []

    for entry in data.get("apps", []):
        if not isinstance(entry, dict):
            continue
        existing = entry.get(PREP_KEY)
        if not isinstance(existing, list):
            continue
        kept = [c for c in existing if not _is_ours(c, apply_command)]
        if len(kept) == len(existing):
            continue
        if kept:
            entry[PREP_KEY] = kept
        else:
            entry.pop(PREP_KEY, None)
        removed.append(str(entry.get("name", "")))

    if removed and not dry_run:
        backup(path)
        _atomic_write(path, data)

    return len(removed), removed


def _already_installed(entry: Dict[str, Any], apply_command: str) -> bool:
    existing = entry.get(PREP_KEY)
    if not isinstance(existing, list):
        return False
    return any(_is_ours(c, apply_command) for c in existing)


def _is_ours(entry: Any, apply_command: str) -> bool:
    """Recognise our own command, tolerating path case and quoting changes.

    Comparing the full string is brittle: the user may have reinstalled to a
    different folder, or Windows may return a different case. Matching on
    the distinctive tail is enough to identify our entry without ever
    matching somebody else's press command.
    """
    if not isinstance(entry, dict):
        return False
    text = str(entry.get("do", "")).replace("/", "\\").lower()
    return "streamscale" in text and "apply" in text


def status_of(path: Path, apply_command: str) -> Dict[str, Any]:
    """Summarise how many apps currently carry our command."""
    data = load_apps(path)
    apps = [a for a in data.get("apps", []) if isinstance(a, dict)]
    installed = [str(a.get("name", "")) for a in apps
                 if _already_installed(a, apply_command)]
    return {
        "total": len(apps),
        "installed": len(installed),
        "installed_names": installed,
        "all_names": [str(a.get("name", "")) for a in apps],
    }
