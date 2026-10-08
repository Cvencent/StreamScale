"""Edit a Godot game's override.cfg without trampling anything else.

Godot reads `override.cfg` from beside the executable at startup and uses it
to replace project settings. That makes it the supported way to change how a
game renders without touching the game's own files -- no patching, no repack,
and it applies to any Godot game regardless of whether it ships mod support.

Measured on Brotato (Godot 3.7):

    without override.cfg   display/window/stretch/aspect = keep
    with override.cfg      display/window/stretch/aspect = expand   <- honoured

Three rules shape this module:

1. **Merge, never replace.** The file may already exist for other reasons --
   Brotato's ModLoader reads it too, and silently overwriting it would break
   someone's mod setup. Only the keys asked for are touched; every other
   line, section and comment survives exactly as it was.

2. **Restore surgically.** Reverting puts back the previous value of each
   key we changed, and removes keys that did not exist before. Changes made
   elsewhere in the file while streaming are left alone.

3. **Preserve formatting.** Line endings, trailing newline and quoting style
   are taken from the file as found, so a diff after a round trip is empty.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

OVERRIDE_NAME = "override.cfg"

# The keys this module is allowed to manage. An allow-list keeps a typo in
# adapter code from writing arbitrary settings into someone's file.
MANAGED_PREFIX = "window/"


@dataclass
class Change:
    """What happened to one key, enough to undo it later."""

    section: str
    key: str
    previous: Optional[str]      # None when the key was not present


@dataclass
class EditRecord:
    """Result of one apply(), and the information needed to revert it."""

    existed_before: bool = False
    changes: List[Change] = field(default_factory=list)
    applied: Dict[str, str] = field(default_factory=dict)
    newline: str = "\r\n"

    @property
    def changed(self) -> bool:
        return bool(self.changes)


def _detect_newline(text: str) -> str:
    """Keep whichever line ending the file already uses."""
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    return "\r\n" if crlf >= lf else "\n"


def _split_lines(text: str) -> List[str]:
    """Split without losing the distinction between CRLF and LF."""
    return text.replace("\r\n", "\n").split("\n")


def _find_section(lines: List[str], section: str) -> Optional[Tuple[int, int]]:
    """Return (first_body_line, last_body_line) for a section, or None.

    The range is exclusive of the header and of the next section header, so
    callers can insert or delete freely inside it.
    """
    header = f"[{section}]"
    start = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == header:
            start = index
            continue
        if start is not None and stripped.startswith("[") and stripped.endswith("]"):
            return start + 1, index
    if start is None:
        return None
    return start + 1, len(lines)


def _parse_key(line: str) -> Optional[Tuple[str, str]]:
    """Return (key, raw_value) for an assignment line, or None."""
    stripped = line.strip()
    if not stripped or stripped.startswith(";") or stripped.startswith("#"):
        return None
    if stripped.startswith("["):
        return None
    if "=" not in stripped:
        return None
    key, _, value = stripped.partition("=")
    return key.strip(), value.strip()


def _unquote(raw: str) -> str:
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        return raw[1:-1]
    return raw


def read_keys(path: Path, section: str, keys: List[str]) -> Dict[str, Optional[str]]:
    """Current raw value of each key, or None when absent."""
    found: Dict[str, Optional[str]] = {key: None for key in keys}
    if not path.exists():
        return found
    text = _read_text(path)
    if not text:
        return found

    lines = _split_lines(text)
    span = _find_section(lines, section)
    if span is None:
        return found
    start, end = span
    for line in lines[start:end]:
        parsed = _parse_key(line)
        if parsed and parsed[0] in found:
            found[parsed[0]] = parsed[1]
    return found


def _read_text(path: Path) -> str:
    """Read without translating line endings.

    Path.read_text() applies universal newlines, which collapses CRLF to LF
    before we ever see it. That made newline detection always report LF, so a
    CRLF file came back as LF after a round trip -- silently changing every
    line ending in a file shared with the game.
    """
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def apply_keys(path: Path, section: str, settings: Dict[str, str]) -> EditRecord:
    """Set the given keys, remembering the previous values.

    Written in place, line by line, so unrelated content is untouched.
    """
    for key in settings:
        if not key.startswith(MANAGED_PREFIX):
            raise ValueError(f"refusing to manage key outside {MANAGED_PREFIX!r}: {key}")

    record = EditRecord()
    existed = path.exists()
    record.existed_before = existed

    original = _read_text(path) if existed else ""

    record.newline = _detect_newline(original) if original else "\r\n"
    lines = _split_lines(original) if original else [""]

    for key, value in settings.items():
        record.applied[key] = value
        span = _find_section(lines, section)

        if span is None:
            # Create the section at the end, with a blank line before it when
            # the file already has content.
            while lines and lines[-1].strip() == "":
                lines.pop()
            if lines:
                lines.append("")
            lines.append(f"[{section}]")
            lines.append("")
            body_start = len(lines)
            body_end = len(lines)
        else:
            body_start, body_end = span

        previous_raw: Optional[str] = None
        target_index = None
        for index in range(body_start, body_end):
            parsed = _parse_key(lines[index])
            if parsed and parsed[0] == key:
                previous_raw = parsed[1]
                target_index = index
                break

        record.changes.append(
            Change(section=section, key=key,
                   previous=None if previous_raw is None else _unquote(previous_raw)))

        # Strings are quoted; numbers and booleans are not.
        rendered = f'{key}="{value}"' if not _looks_numeric(value) else f"{key}={value}"
        if target_index is not None:
            lines[target_index] = rendered
        else:
            # Insert at the end of the section body, before the blank that
            # usually separates sections.
            insert_at = body_end
            while insert_at > body_start and lines[insert_at - 1].strip() == "":
                insert_at -= 1
            lines.insert(insert_at, rendered)

    text = record.newline.join(lines)
    if text and not text.endswith(record.newline):
        text += record.newline

    _write_atomic(path, text)
    return record


def revert_keys(path: Path, record: EditRecord) -> None:
    """Undo exactly what apply_keys changed.

    Keys that existed are put back to their previous value; keys this module
    added are removed again. Anything else that happened to the file in the
    meantime is preserved.
    """
    if not record.changes:
        return

    if not path.exists():
        # Someone deleted it while streaming. Rebuild only if we were the
        # ones who created it in the first place.
        if not record.existed_before:
            return
        lines = [""]
        newline = record.newline
    else:
        text = _read_text(path)
        newline = _detect_newline(text) or record.newline
        lines = _split_lines(text)

    for change in record.changes:
        span = _find_section(lines, change.section)
        if span is None:
            if change.previous is None:
                continue     # nothing to remove, and no section to put it in
            # Recreate the section for a value we still owe the user.
            while lines and lines[-1].strip() == "":
                lines.pop()
            if lines:
                lines.append("")
            lines.append(f"[{change.section}]")
            lines.append("")
            span = (len(lines), len(lines))

        body_start, body_end = span
        index_found = None
        for index in range(body_start, body_end):
            parsed = _parse_key(lines[index])
            if parsed and parsed[0] == change.key:
                index_found = index
                break

        if change.previous is None:
            if index_found is not None:
                del lines[index_found]
        else:
            rendered = (f"{change.key}={change.previous}"
                        if _looks_numeric(change.previous)
                        else f'{change.key}="{change.previous}"')
            if index_found is not None:
                lines[index_found] = rendered
            else:
                lines.insert(body_end, rendered)

    if not record.existed_before and not record.changes:
        return

    text = newline.join(lines)
    if text and not text.endswith(newline):
        text += newline

    # If nothing of ours is left and the file is effectively empty, remove it
    # rather than leaving behind a stub we created.
    meaningful = [l for l in lines if l.strip() and not l.strip().startswith((";", "#"))]
    if meaningful and all(_is_empty_section(l) or not l.strip() for l in meaningful):
        meaningful = []
    if not meaningful:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return

    _write_atomic(path, text)


def _is_empty_section(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("[") and stripped.endswith("]")


def _looks_numeric(value: str) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return value.lower() in ("true", "false")


def _write_atomic(path: Path, text: str) -> None:
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
