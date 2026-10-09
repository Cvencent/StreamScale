"""StreamScale tray application.

What this is, and what it deliberately is not
---------------------------------------------
StreamScale's actual work happens in Sunshine press-commands: Sunshine runs
`streamscale apply` when a stream starts and `streamscale revert` when it
ends. That mechanism needs no resident process, which is why it is the
primary design.

This tray app is a companion, not a replacement:

  * it shows whether a stream is running, so the user can tell at a glance
    that the hooks fired;
  * it edits config.json, which is otherwise a hand-edited file;
  * it installs the prep-cmd into Sunshine's apps.json, which is the step
    people find most fiddly.

The hooks keep working when this app is closed. That is on purpose.

Threading model
---------------
pystray's Win32 backend owns a message loop, so `icon.run()` must execute on
the main thread. It blocks there for the lifetime of the process. Everything
else -- log tailing, the settings window -- runs off the main thread.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import threading
import time
import traceback

import i18n

t = i18n.t
from pathlib import Path

APP_NAME = "StreamScale"
APP_VERSION = "0.7.1"

# Suppress console windows for any child process. On non-Windows this is 0,
# which is a no-op, so the constant is safe to use unconditionally.
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE = "StreamScale"


# ----------------------------------------------------------------------
# Paths
# ----------------------------------------------------------------------

def runtime_dir() -> Path:
    """Where our modules live, packaged or not."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def bundle_root() -> Path:
    """The folder the user sees -- beside the exe, or the project root."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / APP_NAME


def config_path() -> Path:
    return config_dir() / "config.json"


def log_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / APP_NAME


def log_path() -> Path:
    return log_dir() / "tray.log"


# ----------------------------------------------------------------------
# Logging (the tray has no console, so a file is the only channel)
# ----------------------------------------------------------------------

class _LogStream:
    """Minimal file-backed stdout replacement.

    With console=False there is no stdout. Any stray print() in this
    process or a library would raise, so stdout/stderr are redirected into
    the log before anything else runs.
    """

    def __init__(self, handle):
        self._handle = handle
        self._lock = threading.Lock()

    def write(self, text):
        if not text:
            return 0
        with self._lock:
            try:
                self._handle.write(text)
                self._handle.flush()
            except Exception:
                pass
        return len(text)

    def flush(self):
        with self._lock:
            try:
                self._handle.flush()
            except Exception:
                pass

    def isatty(self):
        return False

    def fileno(self):
        raise OSError("no fileno in windowed mode")


def setup_logging() -> Path:
    """Point stdout/stderr at a rotating log file. Returns the path.

    STREAMSCALE_LOG_DIR overrides the destination, which lets tests keep
    their output separate from a real installation's.
    """
    override = os.environ.get("STREAMSCALE_LOG_DIR")
    directory = Path(override) if override else log_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "tray.log"

    # Rotate at 2 MB. A long-running tray app that logs every poll would
    # otherwise grow without bound.
    if path.is_file() and path.stat().st_size > 2 * 1024 * 1024:
        rotated = directory / "tray.log.1"
        try:
            if rotated.exists():
                rotated.unlink()
            path.replace(rotated)
        except OSError:
            pass

    handle = open(path, "a", encoding="utf-8", buffering=1)
    sys.stdout = _LogStream(handle)
    sys.stderr = sys.stdout
    return path


def log(message: str) -> None:
    import datetime
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        print(f"{stamp} {message}")
    except Exception:
        pass


# ----------------------------------------------------------------------
# Single instance
# ----------------------------------------------------------------------

class SingleInstance:
    """Named mutex so a second launch cannot create a second tray icon.

    Two instances fight over the same config file and both drive a tray
    icon; the visible symptom is status flipping between icons, which is
    very hard to diagnose. A mutex turns that into a clear message.
    """

    _ERROR_ALREADY_EXISTS = 183
    _NAME = "Global\\StreamScaleTraySingleton"

    def __init__(self):
        self._handle = None
        self.already_running = False
        try:
            k32 = ctypes.windll.kernel32
            self._handle = k32.CreateMutexW(None, True, self._NAME)
            if self._handle:
                self.already_running = k32.GetLastError() == self._ERROR_ALREADY_EXISTS
        except Exception:
            log("single-instance check failed:\n" + traceback.format_exc())


# ----------------------------------------------------------------------
# Autostart (HKCU: no administrator rights needed)
# ----------------------------------------------------------------------

def _command_path() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    # Running from source: prefer pythonw so no console flashes on boot.
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = pythonw if pythonw.is_file() else Path(sys.executable)
    return f'"{exe}" "{Path(__file__).resolve()}"'


def autostart_enabled() -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.QueryValueEx(key, _RUN_VALUE)
            return True
    except OSError:
        return False


def set_autostart(enabled: bool) -> None:
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, _RUN_VALUE, 0, winreg.REG_SZ, _command_path())
        else:
            try:
                winreg.DeleteValue(key, _RUN_VALUE)
            except OSError:
                pass


# ----------------------------------------------------------------------
# Config access (shared with the CLI's format)
# ----------------------------------------------------------------------

DEFAULT_CONFIG = {
    "enabled": True,
    "excluded_apps": ["Desktop"],
    "max_client_width": 1600,
    "state_dir": "",
    "clients": {},
    # Apply profiles the moment a stream starts, rather than waiting to see
    # the game process. A game reads its settings within milliseconds of
    # launching, which a one-second poll cannot beat. See _preapply_all.
    "preapply": True,
    # Multiplier applied to the computed font size, so the user can fine-tune
    # without editing adapters. 1.0 keeps the built-in heuristic.
    "font_scale": 1.0,
    # Fill the screen instead of keeping the game's own aspect ratio, for
    # games whose 16:9 layout is letterboxed on a 4:3 handheld.
    #   "off"    - leave the game's aspect alone (black bars)
    #   "expand" - enlarge the render area at the same scale: fills the
    #              screen, adds visible play area, no cropping or distortion
    #   "stretch"- scale to fill exactly, which distorts the image
    "aspect_fill": "off",
    # Interface language. Empty means "not chosen yet", in which case the
    # system language is used -- a better guess than assuming English, and
    # it keeps the setting honest about whether the user picked one.
    "language": "",
}


def load_config() -> dict:
    import json
    path = config_path()
    if not path.exists():
        return dict(DEFAULT_CONFIG)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        merged = dict(DEFAULT_CONFIG)
        merged.update({k: v for k, v in data.items() if k in DEFAULT_CONFIG})
        return merged
    except Exception:
        log("config unreadable, using defaults:\n" + traceback.format_exc())
        return dict(DEFAULT_CONFIG)


def save_config(cfg: dict) -> Path:
    import json
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = {k: cfg.get(k, v) for k, v in DEFAULT_CONFIG.items()}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(clean, fh, ensure_ascii=False, indent=2)
    return path


# ----------------------------------------------------------------------
# Tray application
# ----------------------------------------------------------------------

class TrayApp:
    """Owns the icon, the menu and the log monitor."""

    def __init__(self):
        self._icon = None
        self._monitor = None
        self._watcher = None
        self._status = "idle"
        self._settings_window = None
        self._applied: set = set()      # games whose profile is currently applied
        # Games still running when the stream ended. Their settings cannot be
        # restored until they exit, or the game would write its in-memory
        # (modified) values back over our restore.
        self._pending_release: set = set()

    # -- state ---------------------------------------------------------

    @property
    def status(self) -> str:
        return self._status

    def _set_status(self, status: str) -> None:
        if status == self._status:
            return
        self._status = status
        self._refresh_icon()

    def _refresh_icon(self) -> None:
        icon = self._icon
        if icon is None:
            return
        try:
            import tray_icons
            icon.icon = tray_icons.make_tray_image(self._status)
            icon.title = self._tooltip()
        except Exception:
            log("icon refresh failed:\n" + traceback.format_exc())

    def _tooltip(self) -> str:
        import tray_icons
        # Translated on call: the language can change while running.
        text = tray_icons.status_text(self._status)
        if self._applied:
            text += " [" + ", ".join(sorted(self._applied)) + "]"
        monitor = self._monitor
        if monitor and monitor.state.streaming:
            state = monitor.state
            parts = []
            if state.resolution:
                parts.append(state.resolution)
            if state.app:
                parts.append(state.app)
            if parts:
                text += " (" + ", ".join(parts) + ")"
        # Windows silently drops tooltips longer than 127 characters.
        return text[:120]

    # -- monitor -------------------------------------------------------

    def _on_stream_change(self, state) -> None:
        log(f"stream state changed: streaming={state.streaming} "
            f"res={state.resolution or '-'} app={state.app or '-'}")
        if state.streaming:
            self._set_status("active")
            # Apply before any game can launch. See _preapply_all for why
            # waiting for the process is too late to be useful.
            self._preapply_all()
            self._set_watching(True)
        else:
            # The stream ending is what ends the session, so this is where
            # everything goes back.
            self._release_all()
            # Keep watching if a game is still running: its settings can only
            # be restored once it exits.
            if not self._pending_release:
                self._set_watching(False)
            # Distinguish "never started" from "just finished": the latter is
            # worth showing in blue so the user sees the restore happened.
            self._set_status("restored" if self._status == "active" else "idle")

    # -- applying profiles ---------------------------------------------

    def _adapters_worth_preapplying(self):
        """Adapters to apply at stream start, as (name, adapter) pairs.

        Only games that declare `process_names` are included: those are the
        ones reachable from inside a launcher like Steam Big Picture, where
        the stream starts long before the game does.
        """
        try:
            import sys as _sys
            _sys.path.insert(0, str(bundle_root() / "src"))
            from streamscale import env, registry
        except Exception:
            log("adapter load failed:\n" + traceback.format_exc())
            return []

        monitor_state = self._monitor.state if self._monitor else None
        session = env.Session(
            app_id="", app_name="(stream)",
            client_name="", client_id="", client_unique_id="",
            width=monitor_state.width if monitor_state else 0,
            height=monitor_state.height if monitor_state else 0,
            fps=0,
        )
        cfg = load_config()
        state_dir = Path(cfg["state_dir"]) if cfg.get("state_dir") else None

        pairs = []
        for cls in registry.ADAPTERS:
            if not getattr(cls, "process_names", ()):
                continue
            adapter = cls(session, state_dir=state_dir)
            self._apply_font_scale(adapter, cfg)
            self._apply_aspect_choice(adapter, cfg)
            pairs.append((cls.name, adapter))
        return pairs

    def _preapply_all(self) -> None:
        """Apply every launchable game's profile as soon as the stream starts.

        Why not wait for the game process
        ---------------------------------
        A game reads its settings file within milliseconds of starting. Our
        process list is polled once a second, so by the time we notice the
        game and write the file, the game has already loaded the old values
        into memory -- the write lands but has no effect, and the game then
        overwrites our change on exit. Observed exactly that: process started
        at 18:19:30, the write landed at 18:19:33, and the game had already
        read font_size=1.

        Applying at stream start sidesteps the race entirely. The user spends
        seconds or minutes in Steam before launching anything, which is ample
        time, and there is nothing to race against.

        The cost is touching config files for games the user may not play
        this session. Those files are only read when their game launches, and
        everything is reverted when the stream ends, so the effect is
        invisible. Set "preapply": false in config.json to use the old
        watch-only behaviour instead.
        """
        cfg = load_config()
        if not cfg.get("enabled", True):
            return
        if not cfg.get("preapply", True):
            log("preapply disabled; will only act when a game process appears")
            return

        for name, adapter in self._adapters_worth_preapplying():
            if name in self._applied:
                continue
            try:
                result = adapter.apply()
            except Exception as exc:
                log(f"{name}: preapply failed: {exc}")
                continue
            self._applied.add(name)
            log(f"{name}: preapplied at stream start -> {result.detail}")

    # -- process watching ----------------------------------------------

    def _set_watching(self, active: bool) -> None:
        watcher = self._watcher
        if watcher is not None:
            watcher.set_active(active)

    def _start_watcher(self) -> None:
        """Begin watching for games launched from inside Steam Big Picture.

        Sunshine's press commands run once, when the stream starts. When the
        user reaches a game through Steam, that moment is before the game
        exists, so nothing can be applied then. Watching for the process is
        the only way to catch it.
        """
        try:
            import process_watcher
            import sys as _sys
            _sys.path.insert(0, str(bundle_root() / "src"))
            from streamscale import registry
        except Exception:
            log("process watching unavailable:\n" + traceback.format_exc())
            return

        names = registry.watched_processes()
        if not names:
            log("no adapters declare process names; watching disabled")
            return

        self._watcher = process_watcher.ProcessWatcher(
            on_start=self._on_game_started,
            on_exit=self._on_game_exited,
        )
        for proc in names:
            cls = registry.find_by_process(proc)
            if cls:
                self._watcher.watch(proc, cls.name)
        log(f"watching for processes: {', '.join(self._watcher.watched)}")
        self._watcher.start()

    def _game_adapter(self, game_name: str):
        """Build an adapter for a running game, or None."""
        try:
            import sys as _sys
            _sys.path.insert(0, str(bundle_root() / "src"))
            from streamscale import env, registry
        except Exception:
            log("adapter load failed:\n" + traceback.format_exc())
            return None

        cls = None
        for candidate in registry.ADAPTERS:
            if candidate.name == game_name:
                cls = candidate
                break
        if cls is None:
            return None

        state = self._monitor.state if self._monitor else None
        session = env.Session(
            app_id="", app_name=game_name,
            client_name="", client_id="", client_unique_id="",
            width=state.width if state else 0,
            height=state.height if state else 0,
            fps=0,
        )
        cfg = load_config()
        adapter = cls(session,
                      state_dir=Path(cfg["state_dir"]) if cfg.get("state_dir") else None)
        self._apply_font_scale(adapter, cfg)
        self._apply_aspect_choice(adapter, cfg)
        return adapter

    @staticmethod
    def _apply_font_scale(adapter, cfg: dict) -> None:
        """Fold the user's font_scale multiplier into the adapter's choice.

        Delegates to the shared implementation so the tray and the
        prep-command cannot drift apart. They did once: the tray applied the
        multiplier while the command Sunshine actually runs ignored it, so
        moving the slider had no effect on a stream and nothing said why.
        """
        from streamscale.cli import apply_font_scale

        applied = apply_font_scale(adapter, cfg.get("font_scale", 1.0))
        if applied is not None:
            log(f"font size will be scaled by {applied:.2f}x")

    @staticmethod
    def _apply_aspect_choice(adapter, cfg: dict) -> None:
        """Fold the user's aspect preference into the adapter's behaviour.

        Delegates to the shared implementation, for the same reason as
        _apply_font_scale.
        """
        from streamscale.cli import apply_aspect_choice

        apply_aspect_choice(adapter, cfg.get("aspect_fill", "off"))

    def _on_game_started(self, game_name: str) -> None:
        """A watched game appeared while streaming.

        Usually a no-op: the profile was already applied when the stream
        started, which is the only way to beat the game to its own settings
        file. This path still matters when preapply is disabled, and when a
        game is relaunched after being closed mid-stream.
        """
        cfg = load_config()
        if not cfg.get("enabled", True):
            log(f"{game_name} started, but scaling is disabled")
            return
        if game_name in self._applied:
            log(f"{game_name} started (profile already in place)")
            return

        adapter = self._game_adapter(game_name)
        if adapter is None:
            return
        try:
            result = adapter.apply()
        except Exception as exc:
            log(f"{game_name}: apply failed: {exc}")
            self._set_status("error")
            return

        self._applied.add(game_name)
        log(f"{game_name} started -> {result.detail}")
        self._set_status("active")
        self._refresh_icon()

    def _on_game_exited(self, game_name: str) -> None:
        """The game closed. Put its settings back.

        Reverting here matters even when the stream is still running: the
        game writes its settings file on exit using the values it loaded, so
        without this the modified values would persist into the next desktop
        session.
        """
        if game_name not in self._applied:
            return
        adapter = self._game_adapter(game_name)
        if adapter is None:
            return
        try:
            result = adapter.revert()
        except Exception as exc:
            log(f"{game_name}: revert failed: {exc}")
            return
        self._applied.discard(game_name)
        self._pending_release.discard(game_name)
        log(f"{game_name} exited -> {result.detail}")
        self._maybe_stop_watching()

    def _release_all(self) -> None:
        """A stream ended. Undo every profile we applied.

        A game that is still running is dealt with later: it holds the
        modified values in memory and will write them back to disk when it
        exits, so reverting now would simply be overwritten. Those games are
        parked in `_pending_release` and reverted by _on_game_exited once
        their process disappears, which is why the watcher is deliberately
        left running past the end of the stream.
        """
        if not self._applied:
            return
        try:
            import process_watcher
            live = process_watcher.running_processes()
        except Exception:
            live = set()

        for game_name in list(self._applied):
            adapter = self._game_adapter(game_name)
            still_running = False
            if adapter is not None:
                # Read from the instance, not the class, so a per-session
                # override is honoured and callers can substitute names.
                procs = getattr(adapter, "process_names", ()) or ()
                still_running = any(p.lower() in live for p in procs)

            if still_running:
                self._pending_release.add(game_name)
                log(f"{game_name} still running at stream end; "
                    f"will restore when it exits")
                continue
            self._on_game_exited(game_name)

        if self._pending_release:
            log(f"waiting for {sorted(self._pending_release)} to exit before restoring")

    def _maybe_stop_watching(self) -> None:
        """Stop scanning once nothing is left to watch for."""
        if self._applied or self._pending_release:
            return
        if not (self._monitor and self._monitor.state.streaming):
            self._set_watching(False)

    def _start_monitor(self) -> None:
        import stream_monitor
        path = stream_monitor.find_sunshine_log()
        if path is None:
            log("Sunshine log not found; status reporting limited to config state")
            cfg = load_config()
            self._set_status("idle" if cfg.get("enabled") else "disabled")
            return
        log(f"monitoring {path}")
        self._monitor = stream_monitor.LogMonitor(path, self._on_stream_change)
        self._monitor.start()
        self._start_watcher()
        self._refresh_icon()
        self._start_menu_watch()

    def _start_menu_watch(self) -> None:
        """Rebuild the menu when the language changes.

        The settings window runs on its own thread, so it cannot touch the
        tray. It leaves a flag instead and this picks it up. Checking once a
        second costs nothing -- it reads a boolean -- and the alternative,
        rebuilding the menu from the other thread, risks a race in pystray.
        """

        def worker():
            while True:
                time.sleep(1.0)
                if not _take_menu_refresh():
                    continue
                try:
                    # Re-read the language before rebuilding, since the
                    # config is the shared source of truth.
                    i18n.set_language(i18n.initial_language(load_config()))
                    if self._icon is not None:
                        self._icon.menu = self._build_menu()
                        self._icon.title = self._tooltip()
                        self._icon.update_menu()
                    log(f"menu rebuilt for language {i18n.current_language()}")
                except Exception:
                    log("menu refresh failed:\n" + traceback.format_exc())

        threading.Thread(target=worker, name="menu-watch", daemon=True).start()

    # -- menu actions --------------------------------------------------

    def _open_settings(self, _icon=None, _item=None) -> None:
        """Open the settings window on its own thread.

        tkinter needs its own main loop, which cannot take over the thread
        pystray is blocking on. Running it detached is the simplest correct
        arrangement; the window is modal to itself rather than to the tray.
        """
        if self._settings_window is not None and self._settings_window.alive():
            self._settings_window.focus()
            return
        try:
            import settings_window
            self._settings_window = settings_window.open_window(on_saved=self._on_config_saved)
        except Exception:
            log("settings window failed:\n" + traceback.format_exc())
            self._set_status("error")

    def _on_config_saved(self, cfg: dict) -> None:
        log(f"config saved: enabled={cfg.get('enabled')}")
        if not cfg.get("enabled"):
            self._set_status("disabled")
        elif self._status == "disabled":
            self._set_status("idle")

    def _open_log(self, _icon=None, _item=None) -> None:
        try:
            subprocess.Popen(["notepad.exe", str(log_path())],
                             creationflags=CREATE_NO_WINDOW)
        except Exception:
            log("cannot open log:\n" + traceback.format_exc())

    def _open_config_folder(self, _icon=None, _item=None) -> None:
        try:
            config_dir().mkdir(parents=True, exist_ok=True)
            os.startfile(str(config_dir()))
        except Exception:
            log("cannot open config folder:\n" + traceback.format_exc())

    def _toggle_autostart(self, _icon=None, _item=None) -> None:
        try:
            set_autostart(not autostart_enabled())
        except Exception:
            log("autostart toggle failed:\n" + traceback.format_exc())

    def _quit(self, icon=None, _item=None) -> None:
        log("quit requested")
        # Restore anything still applied before disappearing: leaving a
        # game stuck at handheld font sizes would be a nasty surprise.
        self._release_all()
        if self._watcher:
            self._watcher.stop()
        if self._monitor:
            self._monitor.stop()
        target = icon or self._icon
        if target is not None:
            target.stop()

    # -- lifecycle -----------------------------------------------------

    def _build_menu(self):
        import pystray
        Item, Menu = pystray.MenuItem, pystray.Menu

        def autostart_checked(_item):
            return autostart_enabled()

        return Menu(
            Item(t("tray.menu.settings"), self._open_settings, default=True),
            Menu.SEPARATOR,
            Item(t("tray.menu.autostart"), self._toggle_autostart,
                 checked=autostart_checked),
            Item(t("tray.menu.open_config"), self._open_config_folder),
            Item(t("tray.menu.view_log"), self._open_log),
            Menu.SEPARATOR,
            Item(t("tray.menu.quit"), self._quit),
        )

    def run(self) -> None:
        import pystray
        import tray_icons

        cfg = load_config()
        self._status = "idle" if cfg.get("enabled", True) else "disabled"

        self._icon = pystray.Icon(
            APP_NAME,
            icon=tray_icons.make_tray_image(self._status),
            title=self._tooltip(),
            menu=self._build_menu(),
        )
        # Blocks on the main thread; the setup callback is where background
        # work is allowed to start.
        self._icon.run(setup=self._on_ready)

    def _on_ready(self, icon) -> None:
        icon.visible = True
        log(f"{APP_NAME} {APP_VERSION} ready (frozen={getattr(sys, 'frozen', False)})")
        self._start_monitor()
        self._watch_for_update_request()

    def _watch_for_update_request(self) -> None:
        """Exit cleanly when a new build asks us to step aside.

        An upgrade cannot overwrite a running executable, so it renames us
        and restarts from the new file -- which needs this process gone
        first, and needs the settings it changed put back on the way out.
        Polling a named event is how the message arrives; the tray's own
        loop owns the main thread, so this runs beside it.
        """
        try:
            import updater
        except Exception:
            return

        def worker():
            signal = updater.ShutdownSignal()
            handle = signal.create()
            if not handle:
                return
            try:
                while True:
                    # 1 s slices so closing the app does not wait on the wait.
                    result = ctypes.windll.kernel32.WaitForSingleObject(handle, 1000)
                    if result == 0:
                        log("an upgrade is replacing this build; quitting")
                        self._quit(self._icon)
                        return
                    if self._icon is None:
                        return
            except Exception:
                log("update watcher stopped:\n" + traceback.format_exc())
            finally:
                signal.close()

        threading.Thread(target=worker, name="update-watch", daemon=True).start()


def _install_record_path() -> Path:
    return config_dir() / "install.json"


def _notify_upgrade_declined(installed: Path, new_version: str, old_version: str) -> None:
    """Tell the user a package was opened but the installed build is current.

    Only reached when the process really is running from outside the install
    location -- not on an ordinary launch.
    """
    try:
        ctypes.windll.user32.MessageBoxW(
            None,
            t("tray.no_upgrade.body", app=APP_NAME, new=new_version,
              old=old_version, path=installed),
            t("tray.no_upgrade.title", app=APP_NAME), 0x40)
    except Exception:
        pass


def record_install_path(exe: Path | None = None) -> None:
    """Remember where this app lives, for the next upgrade to find.

    Without a record, an upgrade launched from Downloads has nothing to go
    on: it sees only itself, concludes there is no installation, and does
    nothing. The autostart entry is one source of truth but exists only if
    the user enabled it, so a dedicated record covers the rest.

    Both the executable and its containing folder are stored. The folder is
    what an upgrade actually replaces in an onedir layout.

    Only written when the record would change, so a normal start does not
    touch the file every time.
    """
    import json

    target = exe or (Path(sys.executable).resolve()
                     if getattr(sys, "frozen", False) else None)
    if target is None:
        return
    target = Path(target).resolve()

    path = _install_record_path()
    payload = {"exe": str(target), "folder": str(target.parent)}

    try:
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if (existing.get("exe") == payload["exe"]
                    and existing.get("folder") == payload["folder"]):
                return          # already correct; leave the file alone
    except (OSError, ValueError, json.JSONDecodeError):
        pass

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        pass


def _installed_exe() -> Path:
    """Where this app is meant to live, whether or not it runs from there.

    Checked in order of reliability:

      1. the recorded install path, written on first run;
      2. the autostart entry, which names the executable Windows launches;
      3. this process's own location.

    (1) before (2) matters when the user moved the app: the record follows
    the move, whereas the registry would still point at the old place until
    the next run repairs it.
    """
    import json

    record = _install_record_path()
    if record.exists():
        try:
            recorded = json.loads(record.read_text(encoding="utf-8")).get("exe")
            if recorded:
                candidate = Path(recorded)
                if candidate.exists():
                    return candidate.resolve()
        except (OSError, ValueError, json.JSONDecodeError):
            pass

    from_registry = _autostart_target()
    if from_registry is not None:
        return from_registry.resolve()

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()

    # Running from source: treat the project-root exe as the install.
    return (Path(__file__).resolve().parent.parent / "StreamScale.exe")


def _autostart_target() -> Path | None:
    """The executable path recorded in the autostart entry, if any."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, _RUN_VALUE)
    except OSError:
        return None
    text = str(value).strip()
    if text.startswith('"'):
        end = text.find('"', 1)
        if end > 1:
            candidate = Path(text[1:end])
            return candidate if candidate.exists() else None
    return None


def _repair_autostart(installed: Path) -> None:
    """Point the autostart entry at the new location after an upgrade.

    Without this an upgrade into a different folder silently breaks
    autostart: the registry would keep pointing at a path that no longer
    holds the current build.
    """
    if not autostart_enabled():
        return
    import winreg
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.SetValueEx(key, _RUN_VALUE, 0, winreg.REG_SZ, f'"{installed}"')
        log(f"autostart repointed to {installed}")
    except OSError as exc:
        log(f"could not update the autostart entry: {exc}")


def maybe_self_update() -> int | None:
    """Handle a double-clicked package: install it over the existing copy.

    Returns an exit code when this process should stop (the upgrade ran, and
    the freshly installed copy was launched in its place), or None to carry
    on starting normally.

    An important distinction
    ------------------------
    This runs on *every* start, so it must recognise the ordinary case --
    launching the installed copy -- and get out of the way. An earlier
    version compared "where I am running from" against "the recorded install
    path" and treated any difference as an upgrade attempt. That broke normal
    startup: while the build output still existed, the record pointed at it,
    every launch looked like "install this build over that one", the versions
    matched, and the process exited without ever showing a tray. The user's
    report was simply "your icon is not there".

    The reliable question is whether the running copy *is* the installation.
    Comparing that one fact cannot be confused by a stale record.
    """
    if not getattr(sys, "frozen", False):
        return None

    running = Path(sys.executable).resolve()
    try:
        installed = _installed_exe().resolve()
    except Exception:
        return None

    # Same file, or the same folder in an onedir layout: this is a normal
    # start of the installed copy, not an upgrade.
    if running == installed or running.parent == installed.parent:
        return None

    # Running from somewhere else. Is this a newer build to install, or a
    # stray copy the user happens to have opened?
    try:
        import updater
    except Exception:
        return None

    new_version = updater.read_exe_version(running) or APP_VERSION
    old_version = updater.read_exe_version(installed)

    if not installed.exists():
        # Nothing to replace. Treat as an ordinary start so the user still
        # gets a tray rather than silence.
        log(f"no installation found at {installed}; starting normally")
        return None

    if old_version is None:
        # An install from before versions were embedded. Treat the incoming
        # build as newer: it is the one that has version information at all.
        log(f"installed copy has no version resource; assuming {new_version} is newer")
    elif updater.compare_versions(new_version, old_version) <= 0:
        log(f"upgrade declined: {new_version} is not newer than {old_version}")
        _notify_upgrade_declined(installed, new_version, old_version)
        return 0

    log(f"upgrading {installed} from {old_version or 'unknown'} to {new_version}")

    # Match on the install folder rather than one exact exe path: in onedir
    # the running process lives inside it, and the layout may gain a level.
    # The name comes from the installed copy, not from this process, because
    # an upgrade runs from elsewhere and must find the *installed* tray.
    pids = updater.running_from_root(installed.parent, installed.name)
    if not pids:
        pids = updater.running_instances(installed)
    if pids:
        log(f"asking the running instance to exit (pid {pids})")
    else:
        log("no running instance to stop")

    outcome = updater.perform_update(installed, pids)
    if not outcome.performed:
        log(f"upgrade failed: {outcome.detail}")
        try:
            ctypes.windll.user32.MessageBoxW(
                None,
                t("tray.update_failed.body", detail=outcome.detail),
                t("tray.update_failed.title", app=APP_NAME), 0x10)
        except Exception:
            pass
        return 1

    log(f"installed {new_version} to {installed}")

    # The installed copy cleans up the leftover image; tell it what happened
    # so it can report the upgrade instead of looking like a fresh start.
    try:
        updater.mark_handoff(log_dir(), new_version)
    except Exception:
        pass

    _repair_autostart(installed)

    should_restart = outcome.restart or autostart_enabled()
    if should_restart:
        log("starting the installed copy")
        try:
            updater.relaunch(installed)
        except Exception as exc:
            log(f"could not start the installed copy: {exc}")
            return 1
    else:
        log("the tray was not running before the upgrade; leaving it closed")
    return 0


def request_menu_refresh() -> None:
    """Ask the running tray to rebuild its menu and tooltip.

    The language lives in the config, and the tray builds its menu once at
    startup, so changing the language from the settings window would leave
    the menu in the old one until the next restart. The settings window runs
    on its own thread and cannot touch the tray directly, so it leaves a
    request here and the tray picks it up.

    A module-level flag rather than a queue: only the latest request matters,
    and rebuilding twice from one change would be wasteful but harmless.
    """
    global _menu_refresh_requested
    _menu_refresh_requested = True


def _take_menu_refresh() -> bool:
    global _menu_refresh_requested
    if _menu_refresh_requested:
        _menu_refresh_requested = False
        return True
    return False


_menu_refresh_requested = False


def _selftest() -> int:
    """Check that everything the app needs is present, and report.

    Exists because the packaged build imports several modules lazily --
    tkinter for the settings window, the translations, the log tailer -- and
    PyInstaller only bundles what it can see statically. A module missing
    from the bundle therefore fails only when that feature is first used,
    which is exactly the kind of break that ships unnoticed.

    Writes a report next to the log and prints it, so it is usable both from
    a terminal and by asking someone to run it.

    Exit code 0 means everything loaded; 1 means something is missing.
    """
    import importlib

    checks = [
        ("tkinter (settings window)", "tkinter"),
        ("tkinter widgets", "tkinter.ttk"),
        ("translations", "i18n"),
        ("settings window", "settings_window"),
        ("tray icons", "tray_icons"),
        ("stream monitor", "stream_monitor"),
        ("process watcher", "process_watcher"),
        ("self-update", "updater"),
        ("adapter registry", "streamscale.registry"),
        ("Brotato adapter", "streamscale.games.brotato"),
        ("image library", "PIL.Image"),
        ("tray backend", "pystray._win32"),
    ]

    lines = [f"{APP_NAME} {APP_VERSION} self-test", "=" * 40]
    failed = []

    if getattr(sys, "frozen", False):
        sys.path.insert(0, str(runtime_dir()))
    sys.path.insert(0, str(bundle_root() / "src"))

    for label, module in checks:
        try:
            importlib.import_module(module)
            lines.append(f"  ok    {label}  ({module})")
        except Exception as exc:
            lines.append(f"  FAIL  {label}  ({module}): {exc}")
            failed.append(module)

    # The translation tables are data, so a missing key would not raise.
    try:
        import i18n
        gaps = i18n.missing_keys()
        broken = gaps["missing_chinese"] + gaps["missing_english"]
        if broken:
            lines.append(f"  FAIL  translations incomplete: {broken[:5]}")
            failed.append("i18n-keys")
        else:
            lines.append(f"  ok    translations  ({len(i18n.ENGLISH)} keys, both languages)")
        lines.append(f"  ok    language detected: {i18n.current_language()}")
    except Exception as exc:
        lines.append(f"  FAIL  translations unusable: {exc}")
        failed.append("i18n-tables")

    lines.append("")
    lines.append("result: " + ("FAILED: " + ", ".join(failed) if failed
                               else "all components present"))

    report = "\n".join(lines)
    try:
        path = log_dir() / "selftest.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report, encoding="utf-8")
        report += f"\n\nwritten to {path}"
    except OSError:
        pass

    log(report)
    try:
        sys.stdout.write(report + "\n")
        sys.stdout.flush()
    except Exception:
        pass
    return 1 if failed else 0


def run_cli(argv: list) -> int | None:
    """Handle `StreamScale.exe apply|revert|show` and exit.

    Why this lives in the tray executable
    -------------------------------------
    Sunshine's prep-commands need a program to run. Previously that was a
    batch launcher sitting beside the project (`streamscale.bat`), which meant
    the packaged exe could not serve as a prep-command on its own. Anyone who
    copied the exe somewhere else -- Downloads, a USB stick -- and pointed
    Sunshine at it got a disaster rather than an error:

        "C:\\...\\StreamScale.exe" apply

    The tray executable treated `apply` as an ordinary launch, started a
    second tray, hit the single-instance guard and displayed a modal "already
    running" dialog. Sunshine waits for its prep-command to *exit*, so the
    session's teardown stalled indefinitely: the encoder kept its virtual
    display alive, the client showed a black screen, and the display
    configuration was never restored.

    Recognising the verbs here removes the whole failure mode. The exe is now
    a valid prep-command wherever it happens to live, and an unknown argument
    is reported rather than silently starting a tray.

    Returns an exit code, or None when this is not a CLI invocation.
    """
    # No arguments means "start the tray", which is the normal double-click.
    if len(argv) < 2:
        return None

    # Any argument at all signals a command-line invocation. Never fall back
    # to starting a tray: a prep-command that becomes a tray instead of
    # exiting is what stalls Sunshine's session teardown, and if Sunshine is
    # configured with a verb we do not know, failing loudly is far better
    # than hanging.
    known = {"apply", "revert", "show", "selftest"}
    raw = argv[1]
    verb = raw.lstrip("-/").lower()

    if raw.startswith(("-", "/")):
        if verb in ("h", "help", "?", "version", "v"):
            # Let argparse print usage or the version; it exits on its own.
            known_flag = True
        else:
            known_flag = False
    else:
        known_flag = verb in known

    if not known_flag:
        log(f"unrecognised argument {raw!r}; not a valid command")
        sys.stderr.write(
            f"{APP_NAME}: unknown command {raw!r}\n"
            f"Valid commands: apply, revert, show, selftest\n"
            f"Run with no arguments to start the tray.\n")
        return 2

    if verb == "selftest":
        return _selftest()

    # No dialogs on this path. A modal box blocks until a human clicks it,
    # and Sunshine waits on this process the entire time.
    try:
        import sys as _sys
        _sys.path.insert(0, str(bundle_root() / "src"))
        if getattr(sys, "frozen", False):
            _sys.path.insert(0, str(runtime_dir()))
        from streamscale import cli
    except Exception:
        log("CLI dispatch failed:\n" + traceback.format_exc())
        return 2

    code = cli.main(argv[1:])
    log(f"CLI {raw} finished with code {code}")
    return code


def main() -> int:
    setup_logging()

    # Before anything else: a prep-command invocation must not become a tray.
    cli_code = run_cli(sys.argv)
    if cli_code is not None:
        return cli_code

    log("=" * 56)
    log(f"starting {APP_NAME} {APP_VERSION}")

    # Double-clicking a downloaded package lands here: install over the
    # existing copy, then hand off to it.
    code = maybe_self_update()
    if code is not None:
        return code

    try:
        import updater
        stale = updater.clean_up_previous_image()
        if stale is not None:
            log(f"removed the previous version's image: {stale.name}")
        handoff = updater.consume_handoff(log_dir())
        if handoff:
            log(f"upgraded to {APP_VERSION} (handover from {handoff})")
    except Exception:
        log("update housekeeping skipped:\n" + traceback.format_exc())

    # Remember where we live, so a future upgrade launched from Downloads
    # knows which installation to replace.
    record_install_path()

    guard = SingleInstance()
    if guard.already_running:
        log("another instance is already running; exiting")
        try:
            ctypes.windll.user32.MessageBoxW(
                None,
                t("tray.already_running.body", app=APP_NAME),
                t("tray.already_running.title", app=APP_NAME), 0x40)
        except Exception:
            pass
        return 0

    try:
        TrayApp().run()
    except Exception:
        log("fatal:\n" + traceback.format_exc())
        try:
            ctypes.windll.user32.MessageBoxW(
                None,
                t("tray.start_failed.body", app=APP_NAME, path=log_path()),
                t("tray.update_failed.title", app=APP_NAME), 0x10)
        except Exception:
            pass
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
