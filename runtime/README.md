# Building the tray app

`StreamScale.exe` is published as a GitHub Release asset, not committed to
the repository — at ~19 MB it would bloat every clone forever. This folder
holds the source and the build recipe.

## Layout

```
runtime/
  tray_app.py          entry point: tray icon, menu, log monitor, autostart
  settings_window.py   the tkinter settings UI
  sunshine_config.py   safe reading/writing of Sunshine's apps.json
  stream_monitor.py    tails sunshine.log to detect stream state
  process_watcher.py   watches for games launched from inside Steam
  tray_icons.py        draws the status icons programmatically
  StreamScale.spec     PyInstaller recipe
  build.py             one-command build
  _check_*.py          self-checks (run them, see below)
  _smoke_exe.py        launches the built exe and confirms the tray appears
  _e2e_exe.py          end-to-end: fake log, real exe, real detection
  _live_midstream.py   live: real exe, stand-in game process, real scaling
  _check_godot.py      override.cfg editing safety
  _check_crossproc.py  apply/revert across separate processes
```

## Build

Needs a Python with **tkinter** (the standard python.org installer includes
it; some minimal distributions strip it).

```bat
cd runtime
python build.py
```

The script creates a virtual environment, installs the dependencies,
regenerates the icon, runs PyInstaller, and copies the result to
`..\StreamScale.exe`.

Or by hand:

```bat
python -m venv .buildvenv
.buildvenv\Scripts\python.exe -m pip install pillow pystray pyinstaller
.buildvenv\Scripts\python.exe -m PyInstaller --noconfirm --clean StreamScale.spec
copy dist\StreamScale.exe ..
```

## Verify

Do not ship a build you have not verified. The checks are independent and
repeatable; each cleans up after itself.

```bat
.buildvenv\Scripts\python.exe _check_runtime.py     REM icons, log parser, config
.buildvenv\Scripts\python.exe _check_settings.py    REM apps.json editing safety
.buildvenv\Scripts\python.exe _check_singleton.py   REM second instance refused
.buildvenv\Scripts\python.exe _check_autostart.py   REM registry round-trip
.buildvenv\Scripts\python.exe _check_watcher.py     REM process detection
.buildvenv\Scripts\python.exe _check_midstream.py   REM apply/revert wiring
.buildvenv\Scripts\python.exe _smoke_exe.py         REM the tray window appears
.buildvenv\Scripts\python.exe _e2e_exe.py           REM detects a stream end to end
.buildvenv\Scripts\python.exe _live_midstream.py    REM applies when a game launches
.buildvenv\Scripts\python.exe _check_godot.py       REM override.cfg safety
.buildvenv\Scripts\python.exe _check_crossproc.py   REM apply/revert across processes
```

191 assertions across twelve checks. Two of them carry the most weight,
and either can pass while the packaged app is quietly broken:

* `_e2e_exe.py` runs the real executable against a scratch log and asserts
  it notices a session begin and end. A missing import, an unbundled
  resource, or a monitor thread that never starts would all be caught here
  and nowhere else.
* `_live_midstream.py` covers the case press commands cannot: it feeds the
  running app a stream start, launches a renamed system utility as a
  stand-in for the game, and asserts the settings file changes and then
  returns to its original state exactly.

Run both before shipping a build.

Two environment variables make that isolation possible, and also help with
unusual installs:

| Variable | Effect |
|---|---|
| `STREAMSCALE_SUNSHINE_LOG` | use this log file instead of searching |
| `STREAMSCALE_LOG_DIR` | write `tray.log` here instead of `%LOCALAPPDATA%` |

## Things that will bite you

Recorded here because each cost real debugging time.

**`icon.run()` must be on the main thread.** pystray's Win32 backend owns a
message loop. Calling it from a worker thread fails outright. The tray
blocks the main thread; the monitor thread and the settings window run
beside it.

**`console=False` means there is no `sys.stdout`.** Any stray `print` in
this process or a library raises. `tray_app.setup_logging()` replaces
stdout and stderr with a file stream before anything else runs. If the log
file does not appear at all, the crash happened before that call.

**PyInstaller cannot see imports built from strings.** `pystray` picks its
backend by importing a name assembled at runtime, so `pystray._win32` is
listed in `hiddenimports` by hand. For the same reason the `streamscale`
package is added to `datas` rather than discovered.

**In onefile mode the process forks.** The PID `Popen` returns is the
extractor; the Python code runs in a child. Enumerating windows by that PID
finds nothing and looks like "the tray never started". `_smoke_exe.py`
searches by window class name instead.

**Tooltips are capped at 127 characters.** Windows silently refuses to show
a longer one, which looks like the tooltip feature is broken. The string is
truncated to 120.

**Subprocesses flash a console window.** A GUI process spawning
`notepad.exe` or `taskkill` shows a black window each time without
`CREATE_NO_WINDOW`.
