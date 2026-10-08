"""Brotato adapter.

Brotato is a Godot game. Its project uses

    display/window/stretch/mode   = 2d
    display/window/stretch/aspect = keep

which means the whole UI is laid out at a reference resolution and then
scaled uniformly to the window. Consequence worth knowing: *lowering the
render resolution does not help*. The UI shrinks along with everything
else, so text stays exactly as small relative to the screen. The only
lever that changes UI size is `font_size`.

`font_size` is a plain multiplier used in the game scripts, e.g.

    var w = 20 * ProgressData.settings.font_size

The in-game slider exposes 0.8-1.25, but nothing clamps the stored value,
so a larger number works when written directly.

Settings file:
    %APPDATA%/Brotato/<steamid>/settings.json

The file is a single object with a top-level "settings" key holding every
option, so we swap only the keys we care about and leave the rest intact.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

from ..adapter import AdapterError, ApplyResult, JsonFileAdapter
from ..godot import OVERRIDE_NAME
from ..godot_mixin import GodotAspectMixin


class BrotatoAdapter(GodotAspectMixin, JsonFileAdapter):
    name = "Brotato"
    aliases = ("Brotato", "土豆兄弟")

    # Executable names, for the case where the game is launched from inside
    # Steam Big Picture rather than as its own Sunshine app entry. Sunshine's
    # press commands only run at the moment a stream starts (when Steam is
    # starting and the game has not launched yet), so the tray watches for
    # these processes instead and applies the profile when one appears.
    process_names = ("brotato.exe",)

    # The <steamid> folder varies per user, so resolve it at runtime.
    settings_path_template = "%APPDATA%/Brotato"
    container_key = "settings"

    # Keys we touch. Everything else in the file is preserved untouched.
    MANAGED_KEYS = ("font_size", "fullscreen", "screenshake",
                    "damage_display", "projectile_opacity")

    # ------------------------------------------------------------------

    def settings_path(self) -> Path:
        """Find the settings.json, discovering the Steam ID directory.

        Layout is %APPDATA%/Brotato/<steamid>/settings.json. Rather than
        guess the Steam ID, scan for the directory that actually contains
        the file. Falls back to the newest match if several exist (e.g. the
        user switched Steam accounts).
        """
        # expandvars must happen here, not at import time: %APPDATA% is
        # resolved per-invocation, and tests point it at a temp directory.
        root = Path(os.path.expandvars(self.settings_path_template))
        if not root.exists():
            raise self._missing(root)

        direct = root / "settings.json"
        if direct.exists():
            return direct

        candidates = [p / "settings.json" for p in root.iterdir()
                      if p.is_dir() and (p / "settings.json").exists()]
        if not candidates:
            raise self._missing(root)
        if len(candidates) > 1:
            candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return candidates[0]

    @staticmethod
    def _missing(root: Path):
        from ..adapter import AdapterError
        return AdapterError(f"no settings.json under {root}")

    # ------------------------------------------------------------------

    def game_dir(self) -> Path:
        """Where the executable lives, for the Godot aspect override.

        override.cfg must sit beside the .exe -- that is where the engine
        looks. The install path is recorded by Steam, but reading Steam's
        library config is a lot of machinery for one string, so this checks
        the usual locations and reports honestly when it cannot find one.
        """
        override = os.environ.get("STREAMSCALE_GAME_DIR")
        if override:
            return Path(override)

        candidates: List[Path] = []
        for drive in ("C", "D", "E", "F", "G"):
            for lib in ("steam", "Steam", "SteamLibrary", "Games/Steam",
                        "Program Files (x86)/Steam", "Program Files/Steam"):
                candidates.append(
                    Path(f"{drive}:/{lib}/steamapps/common/Brotato"))

        for path in candidates:
            try:
                if (path / "Brotato.exe").exists():
                    return path
            except OSError:
                continue

        raise AdapterError(
            "cannot locate the Brotato install directory; "
            "set STREAMSCALE_GAME_DIR to it")

    # ------------------------------------------------------------------
    # Combined apply / revert
    # ------------------------------------------------------------------

    def apply(self) -> ApplyResult:
        """Apply every lever this game offers.

        Two independent mechanisms, deliberately kept independent: the font
        size lives in the game's JSON settings, the aspect ratio in a Godot
        project setting. Either can fail without taking the other down -- a
        missing install directory must not stop the text from being enlarged.
        """
        results = []
        warnings = []

        font = super().apply()
        results.append(("font", font))
        warnings.extend(font.warnings)

        try:
            aspect = self.aspect_apply()
            results.append(("aspect", aspect))
            warnings.extend(aspect.warnings)
        except AdapterError as exc:
            warnings.append(f"aspect skipped: {exc}")
            results.append(("aspect", ApplyResult(changed=False,
                                                  detail=f"skipped ({exc})")))

        changed = [name for name, r in results if r.changed]
        detail = "; ".join(f"{name}: {r.detail}" for name, r in results)
        return ApplyResult(changed=bool(changed), detail=detail, warnings=warnings)

    def revert(self) -> ApplyResult:
        results = []
        warnings = []

        font = super().revert()
        results.append(("font", font))
        warnings.extend(font.warnings)

        try:
            aspect = self.aspect_revert()
            results.append(("aspect", aspect))
            warnings.extend(aspect.warnings)
        except AdapterError as exc:
            warnings.append(f"aspect not restored: {exc}")
            results.append(("aspect", ApplyResult(changed=False,
                                                  detail=f"skipped ({exc})")))

        changed = [name for name, r in results if r.changed]
        detail = "; ".join(f"{name}: {r.detail}" for name, r in results)
        return ApplyResult(changed=bool(changed), detail=detail, warnings=warnings)

    def capabilities(self) -> List[Dict[str, Any]]:
        """What this adapter can change, for the settings UI and logs."""
        return [
            {
                "kind": "json-settings",
                "available": True,
                "keys": list(self.MANAGED_KEYS),
                "target": str(self.settings_path()),
            },
            self.aspect_capability(),
        ]

    # ------------------------------------------------------------------

    def target_state(self, current: Dict[str, Any]) -> Dict[str, Any]:
        return {**current, "font_size": self._scaled_font_size(current)}

    def _scaled_font_size(self, current: Dict[str, Any]) -> float:
        """Pick a font multiplier from the client's resolution.

        What actually drives the need to scale up is the *physical* size of
        the screen, which we cannot detect. Resolution is the available
        proxy: a 4K client is almost always a TV across the room, while a
        640x480 or 1280x960 client is a handheld held at arm's length.

        Caveat worth knowing: streaming at a supersampled resolution (e.g.
        1280x960 onto a 640x480 panel for sharper downscaling) does not
        make the text physically bigger, because downscaling preserves
        relative proportions. Such a client still gets scaled up here --
        the threshold is deliberately generous so that case is covered.

        Clients that fall into a gap can be pinned exactly via config.json:
            {"clients": {"X35S": {"brotato_font_size": 2.0}}}
        """
        w, h = self.session.width, self.session.height
        if not w or not h:
            return 2.0

        # A large client is already comfortable; leave it alone.
        if w >= 2560 or h >= 1440:
            return 1.0
        if w >= 1920:
            return 1.25
        # Handheld class: arm's length, small panel. Scale up properly.
        if w >= 1280:
            return 1.75
        if w >= 960:
            return 2.0
        return 2.25
