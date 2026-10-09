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

import i18n

t = i18n.t


def _supports_cli(exe: Path) -> bool:
    """Does this executable understand `apply` / `revert`?

    Determined by behaviour, because the output cannot be read: this is a
    GUI build (console=False), so Windows gives it no stdout handle and
    anything it prints is lost. An earlier version looked for "apply" in
    that output and therefore never matched anything.

    The distinguishing behaviour is whether the process returns at all.

        understands the verb -> parses it, does the work, exits in ~0.2s
        does not             -> treats it as a normal launch, becomes a
                                tray, and never exits

    So a prompt return is the answer, whatever the exit code. A process
    still alive at the timeout is killed rather than left running, since a
    stray tray is exactly what this check exists to prevent.

    This matters more than it looks. Sunshine waits for its prep-command to
    exit, so installing a command that becomes a tray stalls the session
    teardown: the client sees an empty desktop and the display configuration
    is never restored.
    """
    if not exe.exists():
        return False

    try:
        subprocess.run(
            [str(exe), "--help"],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True
    except subprocess.TimeoutExpired:
        # Still running: it started something that does not return.
        try:
            subprocess.run(["taskkill", "/F", "/IM", exe.name],
                           capture_output=True, text=True, encoding="gbk",
                           errors="replace",
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception:
            pass
        return False
    except OSError:
        return False

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

        # Apply the stored language before any widget is built, so the first
        # thing drawn is already in the right language rather than English
        # for a frame and then redrawn.
        i18n.set_language(i18n.initial_language(self.cfg))
        self._remembered_tab = 0

        self._build_window()

    def _build_window(self) -> None:
        """Lay the whole window out from scratch.

        Called once at startup and again whenever the language changes. Tk
        fixes a widget's text when it is created, so switching language means
        rebuilding rather than repainting -- and rebuilding is cheaper to get
        right than tracking every label to update in place.
        """
        root = self.root
        for child in root.winfo_children():
            child.destroy()

        root.title(t("settings.title", app=tray_app.APP_NAME))
        root.geometry("640x560")
        root.minsize(560, 480)

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

        # Same tab as before the rebuild, so changing the language does not
        # send the user back to the first one.
        try:
            self.notebook.select(self._remembered_tab)
        except tk.TclError:
            pass

        bar = ttk.Frame(root)
        bar.pack(fill="x", padx=PAD, pady=PAD)
        ttk.Button(bar, text=t("settings.button.close"),
                   command=self.close).pack(side="right")
        ttk.Button(bar, text=t("settings.button.save"),
                   command=self.save).pack(side="right", padx=(0, 6))

        root.protocol("WM_DELETE_WINDOW", self.close)

    def _on_language_change(self, _value=None) -> None:
        """Switch language and redraw.

        The choice is written to the config immediately rather than waiting
        for Save: the window is about to be rebuilt, and a rebuild that lost
        the choice would look like the drop-down did nothing.
        """
        code = self.language_var.get()
        chosen = None
        for candidate, label in i18n.available_languages():
            if label == code:
                chosen = candidate
                break
        if chosen is None:
            return

        try:
            self._remembered_tab = self.notebook.index(self.notebook.select())
        except (tk.TclError, AttributeError):
            self._remembered_tab = 0

        i18n.set_language(chosen)
        self.cfg["language"] = chosen
        try:
            tray_app.save_config(self.cfg)
        except Exception:
            tray_app.log("could not persist language:\n" + traceback.format_exc())

        self._build_window()
        # The tray's own menu is built once, so tell it to re-read.
        try:
            tray_app.request_menu_refresh()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Tab 1: install
    # ------------------------------------------------------------------

    def _build_install_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=PAD)
        self.notebook.add(tab, text=t("settings.tab.install"))

        ttk.Label(
            tab,
            text=t("install.heading"),
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w")

        ttk.Label(
            tab,
            text=t("install.intro"),
            justify="left",
            foreground="#555555",
        ).pack(anchor="w", pady=(4, 12))

        path_row = ttk.Frame(tab)
        path_row.pack(fill="x")
        ttk.Label(path_row, text=t("install.apps_json")).pack(side="left")
        self.apps_path_var = tk.StringVar()
        entry = ttk.Entry(path_row, textvariable=self.apps_path_var, state="readonly")
        entry.pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(path_row, text=t("settings.button.browse"), command=self._browse_apps).pack(side="left")

        if sunshine_config.find_apps_json():
            self.apps_path_var.set(str(sunshine_config.find_apps_json()))
        else:
            self.apps_path_var.set("(not found - use Browse)")

        pick = ttk.LabelFrame(tab, text=t("install.which_apps"), padding=PAD)
        pick.pack(fill="both", expand=True, pady=12)

        self.install_all_var = tk.BooleanVar(value=True)
        ttk.Radiobutton(
            pick, text=t("install.all_apps"), variable=self.install_all_var,
            value=True, command=self._refresh_app_list,
        ).pack(anchor="w")

        row = ttk.Frame(pick)
        row.pack(anchor="w", fill="x")
        ttk.Radiobutton(
            row, text=t("install.only_these"), variable=self.install_all_var,
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
        ttk.Button(buttons, text=t("settings.tab.install"), command=self._install).pack(side="left")
        ttk.Button(buttons, text=t("settings.button.remove"), command=self._uninstall).pack(side="left", padx=6)
        ttk.Button(buttons, text=t("settings.button.refresh"), command=self._refresh_app_list).pack(side="left")

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

        The frozen executable handles the verbs itself, so it is always
        usable as a prep-command -- wherever it sits. That matters more than
        it looks: pointing Sunshine at a copy of the exe in some other folder
        used to start a second tray instead, which blocked the session's
        teardown indefinitely.

        The batch launcher is used only when running from source, where
        there is no exe to call.
        """
        if getattr(sys, "frozen", False):
            return f'"{sys.executable}" apply', f'"{sys.executable}" revert'

        launcher = tray_app.bundle_root() / "streamscale.bat"
        if launcher.exists():
            return f'"{launcher}" apply', f'"{launcher}" revert'
        return f'"{sys.executable}" apply', f'"{sys.executable}" revert'

    def _verify_commands(self, apply_cmd: str) -> None:
        """Refuse to install a command that cannot work.

        An earlier build installed a command pointing at the tray exe, which
        did not understand `apply`. Sunshine then waited forever on a process
        that had become a tray, and the stream could not be shut down
        cleanly. Checking here turns that into a clear message.
        """
        exe = apply_cmd.split('"')[1] if apply_cmd.startswith('"') else apply_cmd.split()[0]
        if getattr(sys, "frozen", False) and str(Path(exe).resolve()) == str(Path(sys.executable).resolve()):
            return   # the running exe handles the verbs; nothing to check
        if _supports_cli(Path(exe)):
            return
        raise RuntimeError(
            f"{Path(exe).name} does not accept the 'apply' command.\n\n"
            "Sunshine would wait for it forever, leaving the stream unable "
            "to close.\n\nInstall the current version, which handles the "
            "command itself.")

    def _install(self) -> None:
        path = self._current_apps_path()
        if path is None:
            messagebox.showerror(tray_app.APP_NAME, t("msg.bad_apps_json"))
            return

        apps = None
        if not self.install_all_var.get():
            apps = [self.app_list.get(i) for i in self.app_list.curselection()]
            if not apps:
                messagebox.showinfo(tray_app.APP_NAME, t("msg.pick_one_app"))
                return

        apply_cmd, revert_cmd = self._prep_commands()

        # Refuse to install something Sunshine would wait on forever.
        try:
            self._verify_commands(apply_cmd)
        except RuntimeError as exc:
            messagebox.showerror(tray_app.APP_NAME, str(exc))
            return

        try:
            count, names = sunshine_config.install_prep(path, apply_cmd, revert_cmd, apps)
        except Exception as exc:
            messagebox.showerror(tray_app.APP_NAME,
                                 t("msg.install_failed", detail=exc))
            tray_app.log("install failed:\n" + traceback.format_exc())
            return

        if count == 0:
            self.install_status.configure(
                text=t("msg.already_installed"), foreground="#555555")
        else:
            self.install_status.configure(
                text=f"Installed on {count} app(s): {', '.join(names)}",
                foreground="#0A6E0A")
        messagebox.showinfo(
            tray_app.APP_NAME,
            t("msg.installed_ok", count=count),
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
            text=t("msg.removed_ok", count=count) if count else t("install.status_absent"),
            foreground="#555555")

    # ------------------------------------------------------------------
    # Tab 2: general
    # ------------------------------------------------------------------

    def _build_general_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=PAD)
        self.notebook.add(tab, text=t("settings.tab.general"))

        # Language first: it is the control someone reaches for when the
        # interface is in a language they cannot read, so it should not be
        # buried under options described in that language.
        lang_row = ttk.LabelFrame(tab, text=t("general.language"), padding=PAD)
        lang_row.pack(fill="x", pady=(0, 12))

        current = i18n.current_language()
        current_label = next(
            (label for code, label in i18n.available_languages() if code == current),
            i18n.available_languages()[0][1],
        )
        self.language_var = tk.StringVar(value=current_label)
        combo = ttk.Combobox(
            lang_row,
            textvariable=self.language_var,
            state="readonly",
            width=16,
            values=[label for _code, label in i18n.available_languages()],
        )
        combo.pack(anchor="w")
        combo.bind("<<ComboboxSelected>>", self._on_language_change)

        ttk.Label(
            lang_row,
            text=t("general.language_note"),
            foreground="#555555",
        ).pack(anchor="w", pady=(6, 0))

        self.enabled_var = tk.BooleanVar(value=bool(self.cfg.get("enabled", True)))
        ttk.Checkbutton(
            tab, text=t("general.enable"), variable=self.enabled_var,
        ).pack(anchor="w")

        ttk.Label(
            tab,
            text=t("general.enable_note"),
            foreground="#555555",
        ).pack(anchor="w", pady=(0, 12))

        print_row = ttk.LabelFrame(tab, text=t("general.text_title"), padding=PAD)
        print_row.pack(fill="x", pady=(0, 12))

        ttk.Label(
            print_row,
            text=t("general.text_note"),
            foreground="#555555",
        ).pack(anchor="w")
        ttk.Label(
            print_row,
            text=t("general.text_hint"),
            foreground="#555555",
        ).pack(anchor="w", pady=(0, 8))

        row = ttk.Frame(print_row)
        row.pack(fill="x")
        ttk.Label(row, text=t("general.text_makes")).pack(side="left")
        self.font_scale_var = tk.DoubleVar(value=float(self.cfg.get("font_scale", 1.0)))
        scale = ttk.Scale(row, from_=0.5, to=2.5, orient="horizontal",
                          variable=self.font_scale_var, command=self._on_scale_move)
        scale.pack(side="left", fill="x", expand=True, padx=8)
        self.font_scale_label = ttk.Label(row, text="", width=18)
        self.font_scale_label.pack(side="left")
        ttk.Button(row, text=t("settings.button.reset"), command=self._reset_font_scale).pack(side="left", padx=(8, 0))

        self._update_font_scale_label()

        ttk.Label(
            print_row,
            text=t("general.text_auto"),
            foreground="#555555",
        ).pack(anchor="w", pady=(6, 0))

        screen_row = ttk.LabelFrame(tab, text=t("general.fill_title"), padding=PAD)
        screen_row.pack(fill="x", pady=(0, 12))

        ttk.Label(
            screen_row,
            text=t("general.fill_note"),
            justify="left",
            foreground="#555555",
        ).pack(anchor="w", pady=(0, 8))

        self.aspect_var = tk.StringVar(value=str(self.cfg.get("aspect_fill", "off")))
        for value, label, note in (
            ("off", "Keep the game's own shape",
             "black bars, nothing distorted"),
            ("expand", "Fill the screen (recommended)",
             "no distortion, you also see more of the play area"),
            ("stretch", "Stretch to fill exactly",
             "no bars, but the picture is distorted"),
        ):
            row = ttk.Frame(screen_row)
            row.pack(anchor="w", fill="x")
            ttk.Radiobutton(row, text=label, variable=self.aspect_var,
                            value=value).pack(side="left")
            ttk.Label(row, text=f"  {note}", foreground="#888888").pack(side="left")

        ttk.Label(
            screen_row,
            text=t("general.fill_scope"),
            foreground="#555555",
        ).pack(anchor="w", pady=(6, 0))

        pre_row = ttk.Frame(tab)
        pre_row.pack(fill="x", pady=(0, 12))
        self.preapply_var = tk.BooleanVar(value=bool(self.cfg.get("preapply", True)))
        ttk.Checkbutton(
            pre_row, text=t("general.preapply"), variable=self.preapply_var,
        ).pack(anchor="w")
        ttk.Label(
            pre_row,
            text=t("general.preapply_note"),
            justify="left",
            foreground="#555555",
        ).pack(anchor="w", pady=(2, 0))

        row = ttk.Frame(tab)
        row.pack(fill="x")
        ttk.Label(row, text=t("general.width")).pack(side="left")
        self.width_var = tk.StringVar(value=str(self.cfg.get("max_client_width", 1600)))
        ttk.Spinbox(row, from_=640, to=7680, increment=160, width=8,
                    textvariable=self.width_var).pack(side="left", padx=6)
        ttk.Label(row, text=t("general.width_unit")).pack(side="left")

        ttk.Label(
            tab,
            text=t("general.width_note"),
            foreground="#555555",
        ).pack(anchor="w", pady=(2, 12))

        ttk.Label(tab, text=t("general.excluded")).pack(anchor="w")
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
        ttk.Button(add_row, text=t("general.excluded_add"),
                   command=self._add_excluded).pack(side="left", padx=6)
        ttk.Button(add_row, text=t("general.excluded_remove"),
                   command=self._remove_excluded).pack(side="left")

    def _on_scale_move(self, _value=None) -> None:
        self._update_font_scale_label()

    def _update_font_scale_label(self) -> None:
        try:
            value = float(self.font_scale_var.get())
        except (tk.TclError, ValueError):
            return
        if abs(value - 1.0) < 0.02:
            note = "  (automatic)"
        elif value > 1.0:
            note = "  larger"
        else:
            note = "  smaller"
        self.font_scale_label.configure(text=f"{value:.2f}×{note}")

    def _reset_font_scale(self) -> None:
        self.font_scale_var.set(1.0)
        self._update_font_scale_label()

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
        self.notebook.add(tab, text=t("settings.tab.overrides"))

        ttk.Label(
            tab,
            text=t("overrides.heading"),
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            tab,
            text=t("overrides.intro"),
            justify="left",
            foreground="#555555",
        ).pack(anchor="w", pady=(2, 12))

        form = ttk.Frame(tab)
        form.pack(fill="x")

        ttk.Label(form, text=t("overrides.client")).grid(row=0, column=0, sticky="w", pady=3)
        self.override_client = tk.StringVar()
        ttk.Entry(form, textvariable=self.override_client, width=22).grid(
            row=0, column=1, sticky="w", padx=6)

        ttk.Label(form, text=t("overrides.key")).grid(row=1, column=0, sticky="w", pady=3)
        self.override_key = tk.StringVar(value="brotato_font_size")
        ttk.Combobox(
            form, textvariable=self.override_key, width=20,
            values=["brotato_font_size"],
        ).grid(row=1, column=1, sticky="w", padx=6)

        ttk.Label(form, text=t("overrides.value")).grid(row=2, column=0, sticky="w", pady=3)
        self.override_value = tk.StringVar(value="2.0")
        ttk.Entry(form, textvariable=self.override_value, width=22).grid(
            row=2, column=1, sticky="w", padx=6)

        ttk.Button(form, text=t("overrides.add"), command=self._add_override).grid(
            row=3, column=1, sticky="w", padx=6, pady=(8, 0))

        ttk.Label(tab, text=t("overrides.current")).pack(anchor="w", pady=(14, 0))
        box = ttk.Frame(tab)
        box.pack(fill="both", expand=True, pady=(4, 0))
        self.override_list = tk.Listbox(box, height=6, exportselection=False)
        self.override_list.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(box, orient="vertical", command=self.override_list.yview)
        scroll.pack(side="left", fill="y")
        self.override_list.configure(yscrollcommand=scroll.set)

        ttk.Button(tab, text=t("overrides.remove"),
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
            messagebox.showinfo(tray_app.APP_NAME, t("overrides.need_name"))
            return
        try:
            value = float(raw)
        except ValueError:
            messagebox.showerror(tray_app.APP_NAME, t("overrides.not_number", value=raw))
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
        self.notebook.add(tab, text=t("settings.tab.status"))

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
        ttk.Button(row, text=t("status.open_log"),
                   command=lambda: self._open_path(tray_app.log_path())).pack(side="left")
        ttk.Button(
            row, text=t("status.open_config"),
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
            messagebox.showerror(tray_app.APP_NAME, t("msg.width_not_number"))
            return

        self.cfg["enabled"] = bool(self.enabled_var.get())
        self.cfg["max_client_width"] = width
        self.cfg["excluded_apps"] = list(self.excluded_list.get(0, "end"))
        self.cfg["preapply"] = bool(self.preapply_var.get())
        try:
            self.cfg["font_scale"] = round(float(self.font_scale_var.get()), 2)
        except (tk.TclError, ValueError):
            self.cfg["font_scale"] = 1.0
        self.cfg["aspect_fill"] = str(self.aspect_var.get() or "off")

        try:
            path = tray_app.save_config(self.cfg)
        except Exception as exc:
            messagebox.showerror(tray_app.APP_NAME,
                                 t("msg.save_failed", detail=exc))
            tray_app.log("save failed:\n" + traceback.format_exc())
            return

        tray_app.log(f"settings saved to {path}")
        if self.on_saved:
            try:
                self.on_saved(self.cfg)
            except Exception:
                tray_app.log("on_saved callback failed:\n" + traceback.format_exc())
        messagebox.showinfo(tray_app.APP_NAME, t("msg.saved_to", path=path))

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
