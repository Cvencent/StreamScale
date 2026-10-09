# Change log

## 0.7.1

* **Fixed: the text-size slider did nothing.** The one control the settings
  window exists for was a no-op, and the measurement showed it plainly:

  ```
  font_scale=1.0  ->  font_size=1.75
  font_scale=1.4  ->  font_size=1.75
  font_scale=2.0  ->  font_size=1.75
  ```

  The multiplier was stored in the config and applied by the tray, but the
  process that actually writes a game's settings is the one Sunshine launches
  as a prep-command — a separate invocation that never loads the tray's code.
  So the slider wrote a value nothing read. Reported as "I dragged it to 1.75
  and nothing changed", with nothing in the log to explain why.

  The logic now lives in one place both paths call, and the log records the
  multiplier whenever it is applied. Verified end to end on both paths: a
  handheld at 1280 wide gets a base of 1.75, so 1.4 lands at 2.45.

  This also caught a smaller mismatch: the slider topped out at 2.5 while the
  code allowed 3.0, leaving a range unreachable from the interface.

* **The slider shows what it produces.** It displayed the multiplier alone —
  "1.75" — which reads as a font size rather than a factor applied to one.
  It now shows both, e.g. `1.40x (on top of automatic) -> about 2.45 in the
  game`, since seeing the result is the point of the control.

* **Fixed: the log file was never closed.** Its handle stayed open until the
  process was torn down, which locks the file: any attempt to clean up the
  directory holding it fails with a permission error on Windows, and the
  error points at the cleaner rather than the leaker. Handlers are closed
  explicitly now.

* Fixed: a `font_scale` of 0, or a negative value, was treated as a request
  to shrink text to the minimum. It is treated as "not set" instead — a
  zero font size is not something anyone wants.

## 0.7.0


* **The interface is available in Chinese and English.** Chosen from
  Settings, applied immediately, and remembered. Nothing had to be set up:
  a Chinese Windows shows Chinese on first run, and the drop-down switches
  back at any time.

  The settings window is rebuilt rather than repainted when the language
  changes. Tk fixes a widget's text when it is created, so rebuilding is
  both simpler and less likely to leave a stray untranslated label behind
  than tracking every widget to update in place. The tab you were on is
  restored, and the tray menu follows.

  **Log files and command-line output stay English.** They are read while
  diagnosing something -- usually pasted into a search engine or a bug
  report -- and translated log lines are harder to search for and harder to
  match against library documentation. Keeping them in one language also
  means the same wording appears whichever language the interface is in.

* **Fixed: a broken text-size slider label.** The value shown was the
  multiplier on its own, which reads as the final size and is not. It now
  says what it is a multiplier *of*.

* **Fixed: the language could revert when saving.** Saving from any tab
  writes the whole config, and the language was not among the values being
  written, so it would have been reset to the default. It is written from
  both the drop-down and Save now.

* **Added a self-test**, run as `StreamScale.exe selftest`. It confirms
  every component loads and writes a report beside the log. This exists
  because the packaged build imports several modules lazily -- tkinter for
  the settings window, the translations, the log tailer -- and PyInstaller
  only bundles what it can see statically. A module missing from the bundle
  therefore fails only when that feature is first used, which is how the
  missing translations nearly shipped unnoticed.

* Five modules are now named explicitly in the build config for the same
  reason: they are imported from inside functions, where static analysis
  cannot follow.

* **The checks no longer interfere with each other.** Each one starts by
  clearing any tray left behind by an earlier check. Two checks passed alone
  and failed in a batch, because a surviving instance held the
  single-instance lock -- a check that only passes in isolation is not much
  use, so they are now order-independent.

## 0.6.2


* **Fixed: the tray could fail to appear at all.** Every start asks "am I the
  installed build, or a package someone just opened?" An earlier version
  answered by comparing where the process runs from against the *recorded*
  install path, and treated any difference as an upgrade attempt. The
  recorded path pointed at a build output directory that still existed, so
  every launch looked like "install this build over that one", the versions
  matched, and the process exited without showing anything. Reported as
  simply "your icon is not there".

  The question is now whether the running copy *is* the installation — the
  same file, or the same folder in an onedir layout — which a stale record
  cannot confuse. A copy that is already installed no longer touches the
  update path at all.

* **Fixed: the black bars were never actually removed.** The screen-fill
  setting defaults to off, and a config file written before the setting
  existed has no key for it, so the default applied and nothing changed.
  Saving from Settings would have added it; the defaults are now merged in
  on read, so an older config picks up new settings without the user having
  to open the window.

* The self-checks now give a launched copy a temporary environment *and* an
  install record naming itself. Without the record it decided it was an
  upgrade candidate and exited, so checks failed for a reason unrelated to
  what they were testing — the same confusion as the first bug above.

* A start that finds no installation anywhere no longer exits silently; it
  starts normally, since a tray is more useful than nothing.

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
