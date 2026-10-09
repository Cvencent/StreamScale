"""
StreamScale - per-game UI scaling automation for Sunshine/Moonlight streaming.

Problem
-------
A game's UI is laid out for the resolution it renders at. If you stream a
3D game built around a 1440p desktop onto a 640x480 handheld, the HUD and
text become unreadable. The same game on the desktop is fine, so changing
the setting globally would ruin the desktop experience.

What this does
--------------
When a Sunshine session starts, Sunshine injects environment variables
(SUNSHINE_APP_NAME, SUNSHINE_CLIENT_NAME, ...) into the launched process.
StreamScale is invoked as a Sunshine "prep-cmd", reads those variables,
and applies a per-game / per-client scaling profile. On session end the
"undo" command restores the original state.

Design notes
------------
* Detection is free: no window polling, no screen scraping. Sunshine
  already tells us which app and which client are involved.
* Games are handled by small pluggable "adapters". An adapter knows how to
  read, write and revert one game's settings. Adding a game means adding a
  JSON profile, not patching this module.
* Every write is preceded by a backup; undo restores from it. If anything
  fails the game is left untouched.
"""

__version__ = "0.7.3"
__all__ = ["__version__"]
