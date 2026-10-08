# Adding support for a new game

The whole point of the adapter design is that supporting a new game should
not require touching the core. Here is the process.

## 1. Find the game's settings file

Most games keep settings in one of these places:

| Location | Typical engine |
|---|---|
| `%APPDATA%/<Game>/...` | Unity, Godot, most indie titles |
| `%USERPROFILE%/Documents/My Games/<Game>/` | Unreal, older titles |
| `<Steam>/steamapps/common/<Game>/` | games that write next to the exe |
| Windows registry (`HKCU\Software\<Game>`) | older / engine-less games |

Steam install path comes from:

```
<Steam>/steamapps/libraryfolders.vdf
```

`E:\SteamLibrary`, `D:\SteamLibrary` etc. are common secondary libraries.

## 2. Identify what controls UI size

Play the game at a low resolution and watch what changes. Three cases:

**A. The game has a UI scale / font size option.**
The ideal case. Find the key in the settings file and write to it. The
in-game slider may cap below what the engine accepts — check before
assuming the slider's range is the real limit. Brotato's slider stops at
125% while the stored value is a free multiplier.

**B. The UI scales with resolution (like Brotato).**
Detectable by finding `stretch/mode` in a Godot `.pck`, or by simply
observing that a lower resolution shrinks everything proportionally. In
this case lowering the render resolution does **not** help; you must find
the scale value.

**C. The UI uses fixed pixel sizes.**
Then rendering at a lower resolution genuinely makes the UI bigger
relative to the screen. There is often nothing to write — the correct
action may be to change the *display* resolution instead, which is
Sunshine's job rather than this tool's. Consider whether an adapter is
warranted at all.

## 3. Write the adapter

Create `src/streamscale/games/<game>.py`:

```python
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

from ..adapter import JsonFileAdapter


class MyGameAdapter(JsonFileAdapter):
    name = "My Game"
    aliases = ("MyGame",)

    settings_path_template = "%APPDATA%/MyGame"
    container_key = None          # or "settings" if nested

    def settings_path(self) -> Path:
        # Override only if the path needs discovery (per-user subfolder etc.)
        return Path(os.path.expandvars(self.settings_path_template)) / "settings.json"

    def target_state(self, current: Dict[str, Any]) -> Dict[str, Any]:
        return {**current, "ui_scale": self._scaled(current)}

    def _scaled(self, current: Dict[str, Any]) -> float:
        w = self.session.width
        if w >= 1920:
            return 1.0
        return 2.0
```

Key points:

* `read_state` / `write_state` come from `JsonFileAdapter` and already do
  atomic writes. Only override them for non-JSON formats.
* Return `{**current, ...}` so untouched keys survive.
* Use `self.session.width` / `.height` / `.client_name` to vary by client.
* Raise `AdapterError` for anything unrecoverable. The caller logs it and
  lets the game run unmodified — never let an exception escape.

## 4. Register it

In `src/streamscale/registry.py`:

```python
from .games.mygame import MyGameAdapter

ADAPTERS = [
    BrotatoAdapter,
    MyGameAdapter,          # add here
]
```

## 5. Test

Add a case to `tests/test_endtoend.py` following the Brotato pattern:
build a fake settings file in a temp `%APPDATA%`, run apply, assert the
value changed and other keys survived, run revert, assert the file is
byte-identical to the original.

```bat
python tests\test_endtoend.py
```

## Non-JSON settings files

For INI, XML, registry or binary formats, subclass `GameAdapter` directly
and implement `read_state` / `write_state`. Reuse the backup and dry-run
machinery in the base class rather than reimplementing it.

If you need to shell out to a tool (e.g. `reg.exe`), keep the same
contract: `read_state` returns a dict, `write_state` accepts one, and both
raise `AdapterError` on failure.

## Reporting findings

When you work out a game's mechanism, note it in the README's supported
games table with the *mechanism*, not just the file path. The mechanism is
what saves the next person the investigation.
