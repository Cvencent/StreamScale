"""Settings window (tkinter).

Layout follows what the user actually came to do, in order of urgency:

    Tab 1  Install   - the one-time "make it work" step
    Tab 2  General   - exclusions and the master switch
    Tab 3  Overrides - per-client exact values
    Tab 4  Status    - what is installed, where the files are

Tabs rather than one long scrolling form: the install step is done once and
the user should not have to scroll past it every time they come back.

Threading note: tkinter owns a main loop, and pystray is already blocking
the real main thread. The window therefore runs on its own thread, which is
fine as long as all widget access happens on that thread -- hence every
callback here stays on the tkinter side and communicates out via plain
values.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import traceback
from pathlib import Path
from typing import Callable, Dict, List, Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import sunshine_config
import tray_app

# Games the CLI currently ships adapters for. Read from the package if it is
# importable so this list cannot go stale; fall back to a literal otherwise.
def known_games() -> List[str]:
    try:
        sys.path.insert(0, str(tray_app.bundle_root() / "src"))
        from streamscale import registry
        return [n.title() for n in registry.known_names()]
    except Exception:
        return ["Brotato"]


PAD = 10


class SettingsWindow:
    """Owns a Toplevel and its widgets."""

    def __init__(self, root: tk.Tk, on_saved: Optional[Callable[[dict], None]]):
        self.root = root
        self.on_saved = on_saved
        self.cfg = tray_app.load_config()

        root.title(f"{tray_app.APP_NAME} Settings")
        root.geometry("640x520")
        root.minsize(560, 460)

        style = ttk.Style(root)
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=PAD, pady=(PAD, 0))

        self._build_install_tab()
        self._build_general_tab()
        self._build_overrides_tab()
        self._build_status_tab()

        bar = ttk.Frame(root)
        bar.pack(fill="x", padx=PAD, pady=PAD)
        ttk.Button(bar, text="Close", command=self.close).pack(side="right")
        ttk.Button(bar, text="Save", command=self.save).pack(side="right", padx=(0, 6))

        root.protocol("WM_DELETE_WINDOW", self.close)

    # ------------------------------------------------------------------
    # Tab 1: install
    # ------------------------------------------------------------------

    def _build_install_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=PAD)
        self.notebook.add(tab, text="Install")

        ttk.Label(
            tab,
            text="Add the press commands to Sunshine",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w")

        ttk.Label(
            tab,
            text=(
                "Sunshine runs a command when a stream starts and another when it\n"
                "ends. Adding those here is what makes scaling automatic."
            ),
            justify="left",
            foreground="#555555",
        ).pack(anchor="w", pady=(4, 12))

        path_row = ttk.Frame(tab)
        path_row.pack(fill="x")
        ttk.Label(path_row, text="apps.json:").pack(side="left")
        self.apps_path_var = tk.StringVar()
        entry = ttk.Entry(path_row, textvariable=self.apps_path_var, state="readonly")
        entry.pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(path_row, text="Browse...", command=self._browse_apps).pack(side="left")

        if sunshine_config.find_apps_json():
            self.apps_path_var.set(str(sunshine_config.find_apps_json()))
        else:
            self.apps_path_var.set("(not found - use Browse)")

        pick = ttk.LabelFrame(tab, text="Which apps", padding=PAD)
        pick.pack(fill="both", expand=True, pady=12)

        self.install_all_var = tk.BooleanVar(value=True)
        ttk.Radiobutton(
            pick, text="All apps", variable=self.install_all_var,
            value=True, command=self._refresh_app_list,
        ).pack(anchor="w")

        row = ttk.Frame(pick)
        row.pack(anchor="w", fill="x")
        ttk.Radiobutton(
            row, text="Only these:", variable=self.install_all_var,
            value=False, command=self._refresh_app_list,
        ).pack(side="left")

        self.app_list = tk.Listbox(row, selectmode="extended", height=6,
                                   exportselection=False)
        self.app_list.pack(side="left", fill="both", expand=True, padx=6)
        scroll = ttk.Scrollbar(row, orient="vertical", command=self.app_list.yview)
        scroll.pack(side="left", fill="y")
        self.app_list.configure(yscrollcommand=scroll.set)

        buttons = ttk.Frame(tab)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Install", command=self._install).pack(side="left")
        ttk.Button(buttons, text="Remove", command=self._uninstall).pack(side="left", padx=6)
        ttk.Button(buttons, text="Refresh", command=self._refresh_app_list).pack(side="left")

        self.install_status = ttk.Label(tab, text="", foreground="#0A6E0A")
        self.install_status.pack(anchor="w", pady=(8, 0))

        self._refresh_app_list()

    def _browse_apps(self) -> None:
        chosen = filedialog.askopenfilename(
            title="Select Sunshine's apps.json",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
        )
        if chosen:
            self.apps_path_var.set(chosen)
            self._refresh_app_list()

    def _current_apps_path(self) -> Optional[Path]:
        raw = self.apps_path_var.get().strip()
        if not raw or raw.startswith("("):
            return None
        path = Path(raw)
        return path if path.exists() else None

    def _refresh_app_list(self) -> None:
        path = self._current_apps_path()
        self.app_list.delete(0, "end")
        if path is None:
            self.install_status.configure(text="apps.json not found.", foreground="#B00020")
            return
        try:
            data = sunshine_config.load_apps(path)
            for name in sunshine_config.app_names(data):
                self.app_list.insert("end", name)
            self.install_status.configure(
                text=f"{len(sunshine_config.app_names(data))} app(s) found.",
                foreground="#555555")
        except Exception as exc:
            self.install_status.configure(text=f"Cannot read: {exc}", foreground="#B00020")

        state = "disabled" if self.install_all_var.get() else "normal"
        self.app_list.configure(state=state)

    def _prep_commands(self):
        """The exact command strings to install.

        Reuse the launcher that install/setup.py wrote when it exists, so the
        tray and the manual instructions agree. Otherwise fall back to
        invoking this very executable, which is correct when frozen.
        """
        launcher = tray_app.bundle_root() / "streamscale.bat"
        if launcher.exists():
            return f'"{launcher}" apply', f'"{launcher}" revert'
        return f'"{sys.executable}" apply', f'"{sys.executable}" revert'

    def _install(self) -> None:
        path = self._current_apps_path()
        if path is None:
            messagebox.showerror(tray_app.APP_NAME, "Select a valid apps.json first.")
            return

        apps = None
        if not self.install_all_var.get():
            apps = [self.app_list.get(i) for i in self.app_list.curselection()]
            if not apps:
                messagebox.showinfo(tray_app.APP_NAME, "Select at least one app.")
                return

        apply_cmd, revert_cmd = self._prep_commands()
        try:
            count, names = sunshine_config.install_prep(path, apply_cmd, revert_cmd, apps)
        except Exception as exc:
            messagebox.showerror(tray_app.APP_NAME, f"Install failed:\n{exc}")
            tray_app.log("install failed:\n" + traceback.format_exc())
            return

        if count == 0:
            self.install_status.configure(
                text="Already installed - nothing to change.", foreground="#555555")
        else:
            self.install_status.configure(
                text=f"Installed on {count} app(s): {', '.join(names)}",
                foreground="#0A6E0A")
        messagebox.showinfo(
            tray_app.APP_NAME,
            f"Done. {count} app(s) updated.\n\n"
            f"A backup was saved next to apps.json.\n"
            f"Restart Sunshine for the change to take effect.",
        )

    def _uninstall(self) -> None:
        path = self._current_apps_path()
        if path is None:
            return
        apply_cmd, _ = self._prep_commands()
        try:
            count, names = sunshine_config.uninstall_prep(path, apply_cmd)
        except Exception as exc:
            messagebox.showerror(tray_app.APP_NAME, f"Remove failed:\n{exc}")
            return
        self.install_status.configure(
            text=f"Removed from {count} app(s)." if count else "Nothing to remove.",
            foreground="#555555")

    # ------------------------------------------------------------------
    # Tab 2: general
    # ------------------------------------------------------------------

    def _build_general_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=PAD)
        self.notebook.add(tab, text="General")

        self.enabled_var = tk.BooleanVar(value=bool(self.cfg.get("enabled", True)))
        ttk.Checkbutton(
            tab, text="Enable scaling", variable=self.enabled_var,
        ).pack(anchor="w")

        ttk.Label(
            tab,
            text="Turn this off to leave every game untouched.",
            foreground="#555555",
        ).pack(anchor="w", pady=(0, 14))

        row = ttk.Frame(tab)
        row.pack(fill="x")
        ttk.Label(row, text="Skip clients wider than:").pack(side="left")
        self.width_var = tk.StringVar(value=str(self.cfg.get("max_client_width", 1600)))
        ttk.Spinbox(row, from_=640, to=7680, increment=160, width=8,
                    textvariable=self.width_var).pack(side="left", padx=6)
        ttk.Label(row, text="px").pack(side="left")

        ttk.Label(
            tab,
            text=(
                "A 4K TV is comfortable already, so it is skipped by default.\n"
                "Set this to match the widest client you want scaled."
            ),
            justify="left",
            foreground="#555555",
        ).pack(anchor="w", pady=(2, 14))

        ttk.Label(tab, text="Never touch these apps:").pack(anchor="w")
        box = ttk.Frame(tab)
        box.pack(fill="both", expand=True, pady=(4, 0))
        self.excluded_list = tk.Listbox(box, height=6, exportselection=False)
        self.excluded_list.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(box, orient="vertical", command=self.excluded_list.yview)
        scroll.pack(side="left", fill="y")
        self.excluded_list.configure(yscrollcommand=scroll.set)

        for name in self.cfg.get("excluded_apps", []) or []:
            self.excluded_list.insert("end", name)

        add_row = ttk.Frame(tab)
        add_row.pack(fill="x", pady=(6, 0))
        self.new_excluded = tk.StringVar()
        entry = ttk.Entry(add_row, textvariable=self.new_excluded)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda _e: self._add_excluded())
        ttk.Button(add_row, text="Add", command=self._add_excluded).pack(side="left", padx=6)
        ttk.Button(add_row, text="Remove selected",
                   command=self._remove_excluded).pack(side="left")

    def _add_excluded(self) -> None:
        name = self.new_excluded.get().strip()
        if not name:
            return
        existing = list(self.excluded_list.get(0, "end"))
        if name.lower() in (e.lower() for e in existing):
            return
        self.excluded_list.insert("end", name)
        self.new_excluded.set("")

    def _remove_excluded(self) -> None:
        for index in reversed(self.excluded_list.curselection()):
            self.excluded_list.delete(index)

    # ------------------------------------------------------------------
    # Tab 3: overrides
    # ------------------------------------------------------------------

    def _build_overrides_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=PAD)
        self.notebook.add(tab, text="Overrides")

        ttk.Label(
            tab,
            text="Pin an exact value for a specific client",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            tab,
            text=(
                "By default the scale is picked from the client's resolution.\n"
                "That cannot see how large the screen physically is, so use this\n"
                "when the automatic value looks wrong."
            ),
            justify="left",
            foreground="#555555",
        ).pack(anchor="w", pady=(2, 12))

        form = ttk.Frame(tab)
        form.pack(fill="x")

        ttk.Label(form, text="Client name").grid(row=0, column=0, sticky="w", pady=3)
        self.override_client = tk.StringVar()
        ttk.Entry(form, textvariable=self.override_client, width=22).grid(
            row=0, column=1, sticky="w", padx=6)

        ttk.Label(form, text="Key").grid(row=1, column=0, sticky="w", pady=3)
        self.override_key = tk.StringVar(value="brotato_font_size")
        ttk.Combobox(
            form, textvariable=self.override_key, width=20,
            values=["brotato_font_size"],
        ).grid(row=1, column=1, sticky="w", padx=6)

        ttk.Label(form, text="Value").grid(row=2, column=0, sticky="w", pady=3)
        self.override_value = tk.StringVar(value="2.0")
        ttk.Entry(form, textvariable=self.override_value, width=22).grid(
            row=2, column=1, sticky="w", padx=6)

        ttk.Button(form, text="Add / update", command=self._add_override).grid(
            row=3, column=1, sticky="w", padx=6, pady=(8, 0))

        ttk.Label(tab, text="Current overrides:").pack(anchor="w", pady=(14, 0))
        box = ttk.Frame(tab)
        box.pack(fill="both", expand=True, pady=(4, 0))
        self.override_list = tk.Listbox(box, height=6, exportselection=False)
        self.override_list.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(box, orient="vertical", command=self.override_list.yview)
        scroll.pack(side="left", fill="y")
        self.override_list.configure(yscrollcommand=scroll.set)

        ttk.Button(tab, text="Remove selected",
                   command=self._remove_override).pack(anchor="w", pady=(6, 0))
        self._refresh_overrides()

    def _refresh_overrides(self) -> None:
        self.override_list.delete(0, "end")
        for client, entries in (self.cfg.get("clients") or {}).items():
            if isinstance(entries, dict):
                for key, value in entries.items():
                    self.override_list.insert("end", f"{client}  |  {key} = {value}")

    def _add_override(self) -> None:
        client = self.override_client.get().strip()
        key = self.override_key.get().strip()
        raw = self.override_value.get().strip()
        if not client or not key:
            messagebox.showinfo(tray_app.APP_NAME, "Client name and key are both required.")
            return
        try:
            value = float(raw)
        except ValueError:
            messagebox.showerror(tray_app.APP_NAME, f"'{raw}' is not a number.")
            return

        clients = dict(self.cfg.get("clients") or {})
        entry = dict(clients.get(client) or {})
        entry[key] = value
        clients[client] = entry
        self.cfg["clients"] = clients
        self._refresh_overrides()

    def _remove_override(self) -> None:
        selection = self.override_list.curselection()
        if not selection:
            return
        line = self.override_list.get(selection[0])
        try:
            client, rest = line.split("  |  ", 1)
            key = rest.split("=")[0].strip()
        except ValueError:
            return
        clients = dict(self.cfg.get("clients") or {})
        entry = dict(clients.get(client) or {})
        entry.pop(key, None)
        if entry:
            clients[client] = entry
        else:
            clients.pop(client, None)
        self.cfg["clients"] = clients
        self._refresh_overrides()

    # ------------------------------------------------------------------
    # Tab 4: status
    # ------------------------------------------------------------------

    def _build_status_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=PAD)
        self.notebook.add(tab, text="Status")

        text = tk.Text(tab, height=18, wrap="word", relief="flat",
                       background="#FAFAFA", font=("Consolas", 9))
        text.pack(fill="both", expand=True)

        path = self._current_apps_path()
        apply_cmd, revert_cmd = self._prep_commands()
        lines: List[str] = []
        lines.append(f"{tray_app.APP_NAME} {tray_app.APP_VERSION}")
        lines.append("")
        lines.append(f"Config file   : {tray_app.config_path()}")
        lines.append(f"Log file      : {tray_app.log_path()}")
        lines.append(f"Apply command : {apply_cmd}")
        lines.append(f"Revert command: {revert_cmd}")
        lines.append("")
        lines.append("Games with a bundled adapter:")
        for name in known_games():
            lines.append(f"  - {name}")
        lines.append("")

        if path:
            try:
                info = sunshine_config.status_of(path, apply_cmd)
                lines.append(f"Sunshine apps.json: {path}")
                lines.append(f"Apps total        : {info['total']}")
                lines.append(f"StreamScale ready : {info['installed']}")
                if info["installed_names"]:
                    lines.append("  " + ", ".join(info["installed_names"]))
                else:
                    lines.append("  (use the Install tab to add the press commands)")
            except Exception as exc:
                lines.append(f"Sunshine apps.json: unreadable ({exc})")
        else:
            lines.append("Sunshine apps.json: not found")

        lines.append("")
        lines.append("Sunshine log:")
        try:
            import stream_monitor
            found = stream_monitor.find_sunshine_log()
            lines.append(f"  {found}" if found else "  not found")
        except Exception as exc:
            lines.append(f"  error: {exc}")

        text.insert("1.0", "\n".join(lines))
        text.configure(state="disabled")

        row = ttk.Frame(tab)
        row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="Open log",
                   command=lambda: self._open_path(tray_app.log_path())).pack(side="left")
        ttk.Button(
            row, text="Open config folder",
            command=lambda: self._open_path(tray_app.config_dir()),
        ).pack(side="left", padx=6)

    def _open_path(self, path: Path) -> None:
        import os
        try:
            if path.is_dir():
                path.mkdir(parents=True, exist_ok=True)
                os.startfile(str(path))
            else:
                subprocess.Popen(["notepad.exe", str(path)],
                                 creationflags=tray_app.CREATE_NO_WINDOW)
        except Exception:
            tray_app.log("open path failed:\n" + traceback.format_exc())

    # ------------------------------------------------------------------

    def save(self) -> None:
        try:
            width = int(self.width_var.get())
        except ValueError:
            messagebox.showerror(tray_app.APP_NAME, "Width must be a number.")
            return

        self.cfg["enabled"] = bool(self.enabled_var.get())
        self.cfg["max_client_width"] = width
        self.cfg["excluded_apps"] = list(self.excluded_list.get(0, "end"))

        try:
            path = tray_app.save_config(self.cfg)
        except Exception as exc:
            messagebox.showerror(tray_app.APP_NAME, f"Could not save:\n{exc}")
            tray_app.log("save failed:\n" + traceback.format_exc())
            return

        tray_app.log(f"settings saved to {path}")
        if self.on_saved:
            try:
                self.on_saved(self.cfg)
            except Exception:
                tray_app.log("on_saved callback failed:\n" + traceback.format_exc())
        messagebox.showinfo(tray_app.APP_NAME, f"Saved to\n{path}")

    def alive(self) -> bool:
        try:
            return bool(self.root.winfo_exists())
        except tk.TclError:
            return False

    def focus(self) -> None:
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except tk.TclError:
            pass

    def close(self) -> None:
        """Tear down carefully to avoid tkinter's noisy __del__ errors.

        Tkinter variables garbage-collect after the interpreter has left the
        main loop, and their __del__ then raises
        "main thread is not in main loop". Each one prints a traceback,
        which fills the log and looks like a real fault. Dropping the
        variables explicitly, while the loop is still alive, avoids it.
        """
        try:
            # Drop references to every tk variable we created, so their
            # destructors run now rather than at interpreter shutdown.
            for name, value in list(vars(self).items()):
                if isinstance(value, tk.Variable):
                    try:
                        value.set("")
                    except tk.TclError:
                        pass
                    setattr(self, name, None)
            self.root.quit()
            self.root.destroy()
        except tk.TclError:
            pass


def open_window(on_saved: Optional[Callable[[dict], None]] = None) -> SettingsWindow:
    """Create the window and run its main loop.

    Called from a worker thread. tkinter requires that its main loop and all
    widget access happen on one thread, so the loop is entered here and the
    caller returns as soon as the window closes.
    """
    holder: Dict[str, SettingsWindow] = {}
    ready = threading.Event()

    def build() -> None:
        root = tk.Tk()
        holder["window"] = SettingsWindow(root, on_saved)
        ready.set()
        root.mainloop()

    thread = threading.Thread(target=build, name="settings-ui", daemon=True)
    thread.start()
    ready.wait(timeout=10)

    window = holder.get("window")
    if window is None:
        raise RuntimeError("settings window did not start")
    return window
