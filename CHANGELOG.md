# Change log

## 0.6.1

* **The exe now works as a Sunshine prep-command, wherever it sits.** It
  understands `apply` / `revert` / `show` itself, so the batch launcher is no
  longer needed. This fixes a failure that cost a real session:

  ```
  "C:\...\Downloads\StreamScale.exe" apply
  ```

  That copy did not understand the verb. It treated `apply` as an ordinary
  launch, started a second tray, and hit the single-instance guard. Sunshine
  waits for its prep-command to exit, so the session teardown stalled for
  five and a half minutes: the client showed an empty desktop, and the
  display configuration was never restored — leaving a phantom second
  monitor behind. An unknown verb now exits non-zero with a message instead
  of silently becoming a tray.

* **Start-up is ~125× faster: 0.2s instead of 25s.** The onefile build
  unpacked ~19 MB into a temporary directory on every single run. Sunshine
  calls the prep-command twice per stream, so that was ~50 seconds of dead
  waiting, and slow enough to look like a hang. The build is now onedir, so
  the payload stays unpacked and only the interpreter boot remains.

  ```
  onefile   25 s per start   (measured)
  onedir   0.2 s per start   (measured)
  ```

  The cost moves to install time, paid once per version: 40 MB across 1020
  files, about 1.4 seconds to copy.

* Self-update handles the folder layout. The same Windows rules apply — a
  folder holding a running program can be *renamed* but not overwritten, and
  the leftover cannot be deleted until the process exits. Verified against a
  genuinely running installation, not a simulation.

* Fixed: the installed command was validated by reading the exe's output,
  which a GUI build never produces (no stdout handle), so the check could
  not match anything. It now judges by behaviour — a command-line build
  returns in ~0.2s, a tray-only build keeps running — and kills a process
  that fails to return, since a stray tray is what the check exists to
  prevent.

* Fixed: listing running instances matched on the caller's own image name,
  so an upgrade staged in another folder looked for the wrong process and
  could not stop the installed copy. It now takes the installed executable's
  name. Path comparison is also case-insensitive, because Windows reports
  the same folder as both `Temp` and `TEMP` depending on the caller.

* The batch launcher points at the onedir folder; it previously launched a
  bare exe that no longer exists.

## 0.6.0

* **Upgrading is now a double-click.** Download the new package, open it, and
  it replaces the installed copy and restarts it. No manual "quit first",
  no dialogs: the icon disappears for about a second and comes back.
* What makes that possible, measured rather than assumed — Windows refuses to
  overwrite a running executable but permits renaming it:
  ```
  overwrite a running exe   -> denied (file in use)
  rename a running exe      -> allowed, the process keeps running
  write a new file at the
    now-vacant path         -> allowed
  ```
  So the old build renames itself aside and the new build takes its place.
  A process cannot delete its own running image, so the leftover is removed
  by the next launch, which can.
* The running instance is asked to step aside through a named event, and
  restores the game settings it changed on the way out — an upgrade must not
  leave a game stuck at handheld font sizes.
* The build now carries a **Windows version resource**, so an upgrade can
  compare versions without launching anything. Opening an older package is
  refused with an explanation instead of silently downgrading. This also
  fills a gap: previously the packaged exe had no version information at all,
  and the version string inside the bundle was compressed and unreadable.
* Autostart is repointed after an upgrade, so enabling it keeps working even
  when the install moves.
* Whether the tray restarts matches how it was before: running stays running,
  closed stays closed.
* The install location is remembered on first run, so an upgrade launched
  from the Downloads folder can find what to replace.

## 0.5.0

* **Black bars on a 4:3 screen can now be removed.** Brotato is laid out for
  16:9 and keeps its own aspect ratio, so on a 1280x960 handheld it is
  letterboxed. Godot reads an `override.cfg` beside the executable and lets
  those project settings be replaced without touching the game. Verified
  against the engine itself, not just the documentation: a probe script
  reports `keep` without the file and `expand` with it.
* Selectable in Settings: keep the game's shape, fill the screen at the same
  scale (`expand`, no distortion, more play area visible), or stretch to fit
  exactly (`ignore`, distorted).
* The override file is **merged, not overwritten** — Brotato's ModLoader also
  reads it, and other sections, comments and line endings are preserved
  exactly. Reverting restores the file byte-for-byte and deletes it when we
  created it.
* The undo information is written to disk, because the CLI runs apply and
  revert as separate processes; keeping it in memory meant the aspect change
  was never undone.
* Capabilities are composed as mixins rather than baked into one base class:
  `GodotAspectMixin` adds aspect control to any adapter, which is what
  supporting further games will build on.
* Fixed: reverting rewrote settings files in a different shape (indentation
  collapsed) because it re-serialised the parsed values. The original text is
  now captured on apply and restored verbatim — byte-for-byte in all six
  formatting variants tested.
* Fixed: `show` (dry-run) wrote `override.cfg`, because the aspect step
  ignored the dry-run flag. A dry run now touches nothing.
* Fixed: a transient `tasklist` failure silently looked like "no processes
  running", and the transient failure is now retried and recorded in
  `last_error` instead of being swallowed.

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
