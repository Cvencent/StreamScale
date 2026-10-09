"""Main entry point: wire environment, config and adapters together.

Two commands mirror Sunshine's prep-cmd pair:

    apply   run when the stream starts
    revert  run when the stream ends

Both are safe to run when not streaming (they exit quietly), which matters
because Sunshine may invoke them in contexts we did not anticipate.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from . import __version__, config as config_mod, env, log as log_mod, registry
from .adapter import AdapterError

log = log_mod.setup()


# Clamping bounds for the user's multiplier. Above about 3 the HUD covers the
# play area, which is worse than small text; below 0.5 it is unreadable.
FONT_SCALE_MIN = 0.5
FONT_SCALE_MAX = 3.0


def apply_font_scale(adapter, scale) -> Optional[float]:
    """Fold the user's multiplier into the adapter's font-size choice.

    Returns the multiplier actually applied, or None when there was nothing
    to do -- which the caller logs, since "I moved the slider and nothing
    happened" is otherwise impossible to diagnose from the log.

    Wrapping the adapter's method rather than replacing its return value is
    what makes this work for any adapter: each one computes its size from
    whatever it knows (resolution, client, its own defaults), and the
    multiplier is applied to that result.
    """
    try:
        value = float(scale)
    except (TypeError, ValueError):
        return None

    # Zero, or anything that is not a positive number, means "not set". It
    # cannot mean "scale to nothing": a zero font size is not a readable
    # outcome, and a config written by an older version has no business
    # shrinking text to half size because the field defaulted to 0.
    if not value or value <= 0:
        return None

    if abs(value - 1.0) < 1e-9 or not hasattr(adapter, "_scaled_font_size"):
        return None

    value = max(FONT_SCALE_MIN, min(FONT_SCALE_MAX, value))
    original = adapter._scaled_font_size

    def scaled(current, _original=original, _factor=value):
        # _original may be a bound method or a plain callable, depending on
        # whether the adapter or a per-client override installed it.
        try:
            base = _original(current)
        except TypeError:
            base = _original
        try:
            return round(float(base) * _factor, 2)
        except (TypeError, ValueError):
            return base

    adapter._scaled_font_size = scaled
    return value


def apply_aspect_choice(adapter, choice) -> Optional[str]:
    """Pass the user's screen-fill preference to an adapter that supports it.

    The mapping from preference to engine value lives here rather than in the
    adapter, so the setting stays a user-facing choice ("fill the screen")
    instead of leaking engine vocabulary into every adapter that supports it.

    Adapters without an `aspect_key` are left alone: the setting is about how
    a 16:9 layout sits on a 4:3 screen, and a game that already fills it has
    nothing to fix.

    Returns the preference applied, or None.
    """
    if not hasattr(adapter, "aspect_key"):
        return None

    text = str(choice or "off").strip().lower()
    if text in ("expand", "fill"):
        adapter.aspect_key = "window/stretch/aspect"
        adapter.aspect_stream_value = "expand"
        return "expand"
    if text in ("stretch", "ignore"):
        adapter.aspect_key = "window/stretch/aspect"
        adapter.aspect_stream_value = "ignore"
        return "stretch"

    # "off" and anything unrecognised: leave the game's own aspect alone.
    adapter.aspect_key = None
    return None


def _resolve_adapter(session, cfg, dry_run: bool):
    """Find the adapter for this session, honouring config exclusions.

    Returns (adapter, None) on success or (None, reason) when the game is
    deliberately skipped. Skipping is normal and must not look like an
    error in the logs.
    """
    if not cfg.enabled:
        return None, "disabled in config"

    if cfg.is_excluded(session.app_name):
        return None, "app excluded in config"

    if cfg.max_client_width and session.width > cfg.max_client_width:
        return None, (f"client width {session.width} exceeds "
                      f"max_client_width {cfg.max_client_width}")

    cls = registry.find(session.app_name)
    if cls is None:
        return None, "no adapter for this app"

    state_dir = cfg.state_dir_path()
    adapter = cls(session, dry_run=dry_run, state_dir=state_dir)
    return adapter, None


def cmd_apply(args) -> int:
    session = env.from_environ()
    if session is None:
        log.debug("apply: not a Sunshine session (SUNSHINE_APP_NAME unset)")
        return 0

    cfg = config_mod.Config.load(Path(args.config) if args.config else None)
    log.info("apply: %s", env.describe(session))

    adapter, reason = _resolve_adapter(session, cfg, args.dry_run)
    if adapter is None:
        log.info("apply: skipped (%s)", reason)
        return 0

    # Per-client override beats the adapter's heuristic.
    override = cfg.override_for(session.client_name, "brotato_font_size")
    if override is not None and hasattr(adapter, "_scaled_font_size"):
        adapter._scaled_font_size = lambda _cur, v=float(override): v
        log.info("apply: using per-client font-size override %s", override)
    else:
        # No exact override, so fold in the user's global multiplier.
        # This is the value the settings slider writes, and it has to be
        # applied here rather than in the tray: Sunshine runs this command
        # as a separate process, which never loads the tray's code.
        applied = apply_font_scale(adapter, cfg.font_scale)
        if applied is not None:
            log.info("apply: font size scaled by %.2f (from settings)", applied)

    apply_aspect_choice(adapter, cfg.aspect_fill)

    try:
        result = adapter.apply()
    except AdapterError as exc:
        # A broken game config must not break the stream; the game simply
        # runs at its desktop settings.
        log.error("apply: %s failed: %s", adapter.name, exc)
        return 1

    log.info("apply: %s changed=%s %s", adapter.name, result.changed, result.detail)
    return 0


def cmd_revert(args) -> int:
    session = env.from_environ()
    if session is None:
        log.debug("revert: not a Sunshine session")
        return 0

    cfg = config_mod.Config.load(Path(args.config) if args.config else None)
    log.info("revert: %s", env.describe(session))

    cls = registry.find(session.app_name)
    if cls is None:
        log.info("revert: no adapter for this app")
        return 0

    adapter = cls(session, dry_run=args.dry_run,
                  state_dir=cfg.state_dir_path())
    try:
        result = adapter.revert()
    except AdapterError as exc:
        log.error("revert: %s failed: %s", adapter.name, exc)
        return 1

    log.info("revert: %s changed=%s %s", adapter.name, result.changed, result.detail)
    return 0


def cmd_show(args) -> int:
    """Print what would happen, without touching anything.

    This is the command to run first: it shows whether detection works and
    which adapter would fire, before the user trusts it with real files.
    """
    session = env.from_environ()
    if session is None:
        print("Not inside a Sunshine session.")
        print()
        print("This command is meant to be run by Sunshine. To test it by")
        print("hand, set these first (values are examples):")
        print()
        print("  set SUNSHINE_APP_NAME=Brotato")
        print("  set SUNSHINE_CLIENT_NAME=X35S")
        print("  set SUNSHINE_CLIENT_WIDTH=1280")
        print("  set SUNSHINE_CLIENT_HEIGHT=960")
        print("  streamscale show")
        return 0

    cfg = config_mod.Config.load(Path(args.config) if args.config else None)
    print(f"Detected session: {env.describe(session)}")
    print()

    adapter, reason = _resolve_adapter(session, cfg, dry_run=True)
    if adapter is None:
        print(f"Would skip: {reason}")
        return 0

    print(f"Adapter: {adapter.name}")
    try:
        current = adapter.read_state()
        want = adapter.target_state(current)
    except AdapterError as exc:
        print(f"Cannot read state: {exc}")
        return 1

    keys = sorted(set(current) | set(want))
    interesting = [k for k in keys
                   if current.get(k) != want.get(k)] or keys[:0]
    if not interesting:
        print("Nothing to change.")
        return 0

    print("Would change:")
    for k in interesting:
        print(f"    {k}: {current.get(k)}  ->  {want.get(k)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="streamscale",
        description="Per-game UI scaling for Sunshine/Moonlight streaming.",
    )
    p.add_argument("--version", action="version", version=f"streamscale {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    for name, fn, help_text in (
        ("apply", cmd_apply, "apply the streaming profile (session start)"),
        ("revert", cmd_revert, "restore the previous profile (session end)"),
        ("show", cmd_show, "show what apply would do, without changing anything"),
    ):
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("--config", help="path to config.json")
        sp.add_argument("--dry-run", action="store_true",
                        help="report actions without writing")
        sp.set_defaults(func=fn)

    return p


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "dry_run", False) or args.command == "show":
        log_mod.setup(verbose=True)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    finally:
        # Release the log file. It stays locked while the handle is open,
        # which stops the directory being cleaned up afterwards -- and a
        # locked file cannot be deleted on Windows at all, so cleanup fails
        # with a permission error that looks like the cleaner's fault.
        log_mod.close_handlers()


if __name__ == "__main__":
    sys.exit(main())
