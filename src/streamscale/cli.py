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
        log.info("apply: using per-client font_size override %s", override)

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


if __name__ == "__main__":
    sys.exit(main())
