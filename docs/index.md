# StreamScale

Per-game UI scaling automation for Sunshine + Moonlight streaming.

Stream a PC game to a handheld and the UI becomes unreadable — a HUD laid
out for a 1440p desktop turns into 6-pixel text on a 3.5" 640×480 panel.
Setting the scale globally would ruin the desktop, so this tool applies a
per-game, per-client profile while streaming and restores the original
state when the session ends.

## Why not use an upscaler?

Magpie and Lossless Scaling enlarge pixels, not interface elements. A
6-pixel glyph becomes 12 pixels, but the screen is twice as large too, so
relative size never changes. Only the game can re-lay-out its own UI.

## Quick start

```bat
git clone https://github.com/Cvencent/StreamScale.git StreamScale
cd StreamScale
python install\setup.py
```

`setup.py` writes a launcher and prints the exact prep-cmd JSON to paste
into Sunshine (Applications → your app → Prep Commands). Verify detection
first — this changes nothing:

```bat
streamscale.bat show
```

## Detection

Sunshine injects `SUNSHINE_APP_NAME` and `SUNSHINE_CLIENT_NAME` into the
launched process. No polling, no window scraping. Without
`SUNSHINE_APP_NAME` the game was launched normally on the desktop and
StreamScale does nothing.

## Configuration

Optional. `%APPDATA%\StreamScale\config.json`:

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
| Brotato | `font_size` multiplier | Godot `stretch/mode = 2d`, so lowering render resolution does **not** help — only `font_size` changes UI size |

## Safety

Every write is preceded by a backup and is atomic. A missing or corrupt
settings file causes the game to be skipped, never a broken stream.

**Back up your saves.** This tool edits game settings files.

## Limitations

Windows only. One adapter per game — there is no universal mechanism,
since each game exposes UI scaling differently, if at all. The heuristic
cannot see physical screen size, so pin an exact value in `clients` when
the default looks wrong.

## License

MIT
