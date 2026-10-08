"""Logging setup.

Streaming prep commands run hidden and their output is usually discarded,
so a file log is the only practical way to debug. Everything also goes to
stderr for the case where someone runs the CLI by hand.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

LOG_NAME = "streamscale.log"


def default_log_path() -> Path:
    if os.name == "nt":
        base = Path(os.path.expandvars("%LOCALAPPDATA%/StreamScale"))
    else:
        base = Path.home() / ".local" / "state" / "streamscale"
    return base / LOG_NAME


def setup(verbose: bool = False, log_path: Optional[Path] = None) -> logging.Logger:
    logger = logging.getLogger("streamscale")
    if logger.handlers:          # already configured (CLI + adapter share one)
        logger.setLevel(logging.DEBUG if verbose else logging.INFO)
        return logger

    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")

    # File handler -- the primary channel, since prep-cmd output is hidden.
    try:
        path = log_path or default_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(path, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except OSError:
        pass                     # unwritable location: fall back to stderr only

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    return logger
