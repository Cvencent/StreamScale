"""Adapter mixin for games built on Godot.

Why a mixin rather than a base class
------------------------------------
A game may need more than one mechanism. Brotato, for example, has its UI
size in a JSON settings file *and* its aspect ratio in a Godot project
setting -- two unrelated levers in two different places. Forcing one into
the other's inheritance chain would mean picking a winner.

So capabilities are composed: `class BrotatoAdapter(GodotAspectMixin,
JsonFileAdapter)`. Each mixin handles its own file and its own apply/revert
step, and the combined adapter reports whatever changed. A second Godot game
reuses the mixin as-is; a game on another engine writes its own.

What the mixin does
-------------------
Sets `display/window/stretch/aspect` through override.cfg so a game designed
for a 16:9 screen fills a 4:3 one instead of being letterboxed. See
`streamscale.godot` for why the file is edited surgically.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import godot
from .adapter import ApplyResult


class GodotAspectMixin:
    """Adds aspect-ratio control via Godot's override.cfg.

    Expects to be mixed with a GameAdapter. The adapter must provide
    `game_dir` (where the executable lives) and should call
    `aspect_apply` / `aspect_revert` from its own apply/revert.

    Attributes to set on the subclass:

        aspect_section      project settings section, usually "display"
        aspect_key          the key to write
        aspect_stream_value value to use while streaming

    Leave `aspect_key` as None to opt out -- some games letterbox for good
    reasons, and a user may simply prefer the black bars.
    """

    aspect_section: str = "display"
    aspect_key: Optional[str] = "window/stretch/aspect"

    #: Value used while streaming. "expand" enlarges the render area at the
    #: same scale, so nothing is cropped and nothing is distorted -- it suits
    #: a game whose art is not authored for a fixed pixel grid. "ignore"
    #: stretches to fill exactly, which distorts; it is the fallback for a
    #: game that positions UI relative to the screen edges.
    aspect_stream_value: str = "expand"

    def aspect_override_path(self) -> Path:
        return self.game_dir() / godot.OVERRIDE_NAME

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    @property
    def _aspect_record_path(self) -> Path:
        """Where the undo information is kept.

        It has to be on disk, not in memory: the CLI runs `apply` and
        `revert` as separate processes, so a revert has nothing in memory to
        work from. Without this the aspect change would survive the stream
        and never be undone.
        """
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in self.name)
        return self.state_dir / f"{safe}.aspect.json"

    def _save_aspect_record(self, record: godot.EditRecord) -> None:
        import json

        self.state_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "existed_before": record.existed_before,
            "newline": record.newline,
            "changes": [
                {"section": c.section, "key": c.key, "previous": c.previous}
                for c in record.changes
            ],
        }
        tmp = self._aspect_record_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, self._aspect_record_path)

    def _load_aspect_record(self) -> Optional[godot.EditRecord]:
        import json

        path = self._aspect_record_path
        if not path.exists():
            return None
        try:
            with open(path, encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return None
        record = godot.EditRecord(
            existed_before=bool(payload.get("existed_before")),
            newline=payload.get("newline", "\r\n"),
        )
        for item in payload.get("changes", []):
            record.changes.append(godot.Change(section=item["section"],
                                               key=item["key"],
                                               previous=item.get("previous")))
        return record

    def _clear_aspect_record(self) -> None:
        try:
            self._aspect_record_path.unlink()
        except FileNotFoundError:
            pass

    # ------------------------------------------------------------------

    def aspect_apply(self) -> ApplyResult:
        if not self.aspect_key:
            return ApplyResult(changed=False, detail="aspect control disabled")

        path = self.aspect_override_path()
        settings = {self.aspect_key: self.aspect_stream_value}
        previous = godot.read_keys(path, self.aspect_section, [self.aspect_key])

        if previous.get(self.aspect_key) == f'"{self.aspect_stream_value}"':
            return ApplyResult(changed=False, detail="aspect already set")

        before = previous.get(self.aspect_key) or "(unset)"
        # --show / dry-run must not touch anything. This was missed once and
        # left an override.cfg behind in a real game directory, which is
        # exactly the kind of surprise dry-run exists to prevent.
        if getattr(self, "dry_run", False):
            return ApplyResult(
                changed=False,
                detail=f"[dry-run] would set aspect {before} -> "
                       f"\"{self.aspect_stream_value}\"")

        try:
            record = godot.apply_keys(path, self.aspect_section, settings)
        except OSError as exc:
            return ApplyResult(changed=False,
                               detail=f"aspect: cannot write override.cfg ({exc})",
                               warnings=[str(exc)])

        try:
            self._save_aspect_record(record)
        except OSError as exc:
            # The write succeeded but cannot be undone automatically. Say so
            # rather than reporting a clean success.
            return ApplyResult(
                changed=True,
                detail=f"aspect {before} -> \"{self.aspect_stream_value}\" "
                       f"(cannot record undo: {exc})",
                warnings=[f"aspect override will not be reverted: {exc}"])

        self._aspect_record = record
        return ApplyResult(
            changed=True,
            detail=f"aspect {before} -> \"{self.aspect_stream_value}\"")

    def aspect_revert(self) -> ApplyResult:
        # Prefer the on-disk record: the CLI reverts in a different process
        # from the one that applied.
        record = self._load_aspect_record() or getattr(self, "_aspect_record", None)
        if record is None or not record.changes:
            return ApplyResult(changed=False, detail="aspect: nothing to restore")

        if getattr(self, "dry_run", False):
            return ApplyResult(changed=False,
                               detail="[dry-run] would restore aspect")

        path = self.aspect_override_path()
        try:
            godot.revert_keys(path, record)
        except OSError as exc:
            return ApplyResult(changed=False,
                               detail=f"aspect: cannot restore override.cfg ({exc})",
                               warnings=[str(exc)])
        self._clear_aspect_record()
        self._aspect_record = None
        return ApplyResult(changed=True, detail="aspect restored")

    # ------------------------------------------------------------------
    # Capability reporting, for the settings UI and the log
    # ------------------------------------------------------------------

    def aspect_capability(self) -> Dict[str, Any]:
        available = bool(self.aspect_key)
        try:
            game_dir = self.game_dir()
        except Exception:
            game_dir = None
        return {
            "kind": "godot-override",
            "available": available,
            "value": self.aspect_stream_value if available else None,
            "target": str(game_dir / godot.OVERRIDE_NAME) if game_dir else None,
        }
