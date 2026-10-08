# Change log

## 0.3.0

* **Games launched from inside Steam Big Picture now work.** Press commands
  fire once, when a stream starts — which, if the user goes through Steam,
  is before the game exists. The tray now watches for the game's process
  during a stream and applies the profile when it appears, reverting when
  the game closes or the stream ends. Adapters declare what to watch via
  `process_names`.
* Process watching is only active while a stream is running, so there is no
  cost while the user is at their desk.
* Fixed a noisy tkinter shutdown error: `Variable.__del__` ran after the
  main loop had exited and printed a traceback per variable, filling the
  log with what looked like real faults.

## 0.2.0

* Tray companion: status icon, settings window, autostart, single instance.
  The tray is optional — the scaling hooks keep working when it is closed.
* Settings window installs the press commands into Sunshine's `apps.json`,
  appending to any existing entries rather than replacing them.
* Stream detection by tailing `sunshine.log`; no credentials or API needed.
* 18.7 MB self-contained executable published as a Release asset.

## 0.1.0

Initial release.

* Detect the active Sunshine session from `SUNSHINE_*` environment
  variables. No polling or window scraping.
* Adapter architecture: one module per game, registered in a table. The
  core never changes when support for a game is added.
* Brotato adapter: scales `font_size`, backed by the finding that the game
  uses Godot's `stretch/mode = 2d`, which means reducing the render
  resolution cannot enlarge the UI — only `font_size` can.
* Safety: automatic backup before every write, atomic file replacement,
  and a per-game failure that never breaks the stream.
* Config file with per-client overrides and an app exclusion list.
* `install/setup.py` generates a launcher and prints the Sunshine prep-cmd
  snippet, so nothing outside the project folder needs editing.
* End-to-end test covering the non-streaming, streaming, revert and
  oversized-client paths.
