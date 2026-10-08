# Change log

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
