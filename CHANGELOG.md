# Change log

## 0.4.0

* **Fixed: the profile was applied too late to matter.** A game reads its
  settings file within milliseconds of starting, but the process list is
  polled once a second. Measured live: the game started at 18:19:30, the
  write landed at 18:19:33, and the game had long since loaded `font_size=1`
  into memory — the file changed and nothing happened. The profile is now
  applied when the stream starts, which is seconds or minutes before any
  game launches. Set `"preapply": false` to restore the old behaviour.
* **Fixed: a backup could not be found when reverting.** The backup filename
  was derived from the session's app name, which differs by caller — the CLI
  sees the Sunshine entry name, while the tray, applying ahead of any launch,
  has no name at all. It wrote `(stream).json` and then looked for
  `Brotato.json`. Now keyed on the adapter's own name.
* **Fixed: a game still running at stream end could leave settings modified
  forever.** Reverting immediately would be overwritten when the game exited
  and wrote back its in-memory values. Such games are now restored once their
  process actually exits.
* New `font_scale` setting, adjustable from the Settings window with a
  slider, for when the automatic size is still too small. Clamped to a sane
  range so it cannot produce a HUD that covers the play area.

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
