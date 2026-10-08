# StreamScale

Per-game UI scaling automation for Sunshine + Moonlight streaming.

Stream a PC game to a handheld and the UI becomes unreadable. A HUD laid
out for a 1440p desktop turns into 6-pixel text on a 3.5" 640×480 panel.
Changing the setting globally is not an option either — it would ruin the
game on the desktop.

StreamScale applies a per-game, per-client scaling profile when a stream
starts and restores the previous state when it ends. Your desktop and your
TV keep the original settings.

```
Sunshine session starts
        │
        ▼
StreamScale reads SUNSHINE_APP_NAME / SUNSHINE_CLIENT_NAME
        │
        ▼
Picks the adapter for that game → backs up → writes stream-friendly values
        │
        ▼
   You play, text readable
        │
        ▼
Stream ends → StreamScale restores the exact original state
```

## Why not just use an upscaler?

Tools like [Magpie](https://github.com/Blinue/Magpie) or Lossless Scaling
enlarge **pixels**. They make a 6-pixel glyph into a 12-pixel glyph — but
the screen is twice as large too, so the text is exactly as hard to read.
Relative size never changes.

Making text *bigger* requires the game to lay out its UI differently, which
only the game itself can do. That is what this project automates.

## Quick start

```bat
git clone https://github.com/Cvencent/StreamScale.git StreamScale
cd StreamScale
python install\setup.py
```

`setup.py` writes a launcher and prints the exact snippet to paste into
Sunshine. Then verify detection — this changes nothing:

```bat
streamscale.bat show
```

Once that looks right, add the printed `prep-cmd` to your app in the
Sunshine web UI (Applications → your app → Prep Commands).

## How detection works

Sunshine injects environment variables into the process it launches. Two
of them are all StreamScale needs:

| Variable | Meaning |
|---|---|
| `SUNSHINE_APP_NAME` | which game is being streamed |
| `SUNSHINE_CLIENT_NAME` | which device is streaming (e.g. `X35S`, `TV`) |
| `SUNSHINE_CLIENT_WIDTH` / `_HEIGHT` | what the client asked for |

No window polling, no screen scraping, no guessing. If
`SUNSHINE_APP_NAME` is absent the user launched the game normally on the
desktop, and StreamScale does nothing at all.

## Configuration

Optional. With no config file the adapter's built-in heuristic is used.
To override, create `%APPDATA%\StreamScale\config.json`:

```json
{
  "enabled": true,
  "excluded_apps": ["Desktop"],
  "max_client_width": 1600,
  "state_dir": "",
  "clients": {
    "X35S": { "brotato_font_size": 2.0 }
  }
}
```

| Key | Effect |
|---|---|
| `enabled` | master switch |
| `excluded_apps` | never touch these apps |
| `max_client_width` | skip clients wider than this (leaves the TV alone) |
| `state_dir` | where backups live; empty = `~/.streamscale` |
| `clients` | per-client overrides, beat the heuristic |

## Supported games

| Game | Mechanism | Notes |
|---|---|---|
| Brotato | `font_size` multiplier | Godot `stretch/mode = 2d`, so lowering the render resolution does **not** help — only `font_size` changes UI size |

Adding a game means adding a module under `src/streamscale/games/` and one
line in `registry.py`. The base class handles atomic writes, backups and
dry-run, so an adapter only describes *what* to change.

## Safety

* Every write is preceded by a backup of the full prior state.
* Writes are atomic (temp file + replace) — a crash cannot corrupt a save.
* If a settings file is missing or unparseable the game is skipped and the
  stream proceeds normally; a bad config never breaks gameplay.
* Backups are keyed by app name, so several games can be in flight without
  colliding.

**Back up your saves.** This tool edits game settings files. It is
conservative and tested, but you should still keep your own backups.

## Limitations

* Windows only for now. Detection is portable; the path resolution and
  launcher are not.
* One adapter per game. There is no universal mechanism — each game exposes
  its UI scale differently, if at all. Games with no such setting cannot be
  helped by this approach.
* The resolution→scale heuristic cannot see physical screen size. Pin an
  exact value in `clients` when the default looks wrong.

## Testing

```bat
python tests\test_endtoend.py
```

Runs the real CLI against a temporary `%APPDATA%` and checks that
non-streaming launches are untouched, streaming raises the value, revert
restores the file byte-for-byte, and oversized clients are skipped.

## License

MIT
