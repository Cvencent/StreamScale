"""Read the Sunshine session context from the environment.

Sunshine runs prep commands with a set of SUNSHINE_* variables describing
the session. We rely on this instead of polling: at the moment our script
runs, the launch is already in flight, so we can ask "which app, which
client" and act immediately.

When run outside Sunshine (a normal desktop launch) the variables are
absent, which is the signal to do nothing at all.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional

# Variables Sunshine injects. Names are taken verbatim from the Sunshine
# binary so a rename upstream fails loudly here rather than silently.
ENV_APP_ID = "SUNSHINE_APP_ID"
ENV_APP_NAME = "SUNSHINE_APP_NAME"
ENV_CLIENT_NAME = "SUNSHINE_CLIENT_NAME"
ENV_CLIENT_ID = "SUNSHINE_CLIENT_ID"
ENV_CLIENT_UNIQUE_ID = "SUNSHINE_CLIENT_UNIQUE_ID"
ENV_CLIENT_WIDTH = "SUNSHINE_CLIENT_WIDTH"
ENV_CLIENT_HEIGHT = "SUNSHINE_CLIENT_HEIGHT"
ENV_CLIENT_FPS = "SUNSHINE_CLIENT_FPS"


@dataclass(frozen=True)
class Session:
    """A single Sunshine streaming session."""

    app_id: str
    app_name: str
    client_name: str
    client_id: str
    client_unique_id: str
    width: int
    height: int
    fps: int

    @property
    def aspect(self) -> float:
        if not self.height:
            return 0.0
        return self.width / self.height


def _to_int(value: Optional[str], default: int = 0) -> int:
    if not value:
        return default
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def from_environ(environ: Optional[Mapping[str, str]] = None) -> Optional[Session]:
    """Build a Session from the environment, or None if not streaming.

    Sunshine defines SUNSHINE_APP_NAME for the launched process. Its
    presence is what distinguishes "we are inside a stream" from "the user
    launched the game normally on the desktop" -- the latter must not be
    touched, so we return None and the caller exits quietly.
    """
    env = os.environ if environ is None else environ

    app_name = (env.get(ENV_APP_NAME) or "").strip()
    if not app_name:
        return None

    return Session(
        app_id=(env.get(ENV_APP_ID) or "").strip(),
        app_name=app_name,
        client_name=(env.get(ENV_CLIENT_NAME) or "").strip(),
        client_id=(env.get(ENV_CLIENT_ID) or "").strip(),
        client_unique_id=(env.get(ENV_CLIENT_UNIQUE_ID) or "").strip(),
        width=_to_int(env.get(ENV_CLIENT_WIDTH)),
        height=_to_int(env.get(ENV_CLIENT_HEIGHT)),
        fps=_to_int(env.get(ENV_CLIENT_FPS)),
    )


def describe(session: Session) -> str:
    """One-line human summary, used in logs."""
    res = f"{session.width}x{session.height}@{session.fps}" if session.width else "?"
    return (
        f"app={session.app_name!r} client={session.client_name or '?'!r} "
        f"res={res} aspect={session.aspect:.3f}"
    )
