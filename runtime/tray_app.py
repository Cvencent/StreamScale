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
import traceback
from pathlib import Path

APP_NAME = "StreamScale"
APP_VERSION = "0.3.0"

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
        text = f"{APP_NAME} - {tray_icons.STATUS_TEXT.get(self._status, self._status)}"
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
            # Only worth scanning the process list while a stream is live.
            self._set_watching(True)
        else:
            # A stream ending must undo anything we applied mid-session.
            self._release_all()
            self._set_watching(False)
            # Distinguish "never started" from "just finished": the latter is
            # worth showing in blue so the user sees the restore happened.
            self._set_status("restored" if self._status == "active" else "idle")

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
        return cls(session, state_dir=Path(cfg["state_dir"]) if cfg.get("state_dir") else None)

    def _on_game_started(self, game_name: str) -> None:
        """A watched game appeared while streaming -- apply its profile."""
        cfg = load_config()
        if not cfg.get("enabled", True):
            log(f"{game_name} started, but scaling is disabled")
            return
        if game_name in self._applied:
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
        """The game closed. Put its settings back right away."""
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
        log(f"{game_name} exited -> {result.detail}")

    def _release_all(self) -> None:
        """Undo every profile we applied, e.g. when the stream ends."""
        for game_name in list(self._applied):
            self._on_game_exited(game_name)
        self._applied.clear()

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
            Item("Settings...", self._open_settings, default=True),
            Menu.SEPARATOR,
            Item("Start with Windows", self._toggle_autostart,
                 checked=autostart_checked),
            Item("Open config folder", self._open_config_folder),
            Item("View log", self._open_log),
            Menu.SEPARATOR,
            Item("Quit", self._quit),
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


def main() -> int:
    setup_logging()
    log("=" * 56)
    log(f"starting {APP_NAME} {APP_VERSION}")

    guard = SingleInstance()
    if guard.already_running:
        log("another instance is already running; exiting")
        try:
            ctypes.windll.user32.MessageBoxW(
                None,
                f"{APP_NAME} is already running.\n\n"
                "Look for its icon in the notification area.",
                APP_NAME, 0x40)
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
                f"{APP_NAME} failed to start.\n\n"
                f"See the log for details:\n{log_path()}",
                APP_NAME, 0x10)
        except Exception:
            pass
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
