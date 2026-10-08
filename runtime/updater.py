"""Self-update: replace this executable while it is running.

How Windows behaves, measured rather than assumed
-------------------------------------------------
Renaming a running executable is allowed; overwriting it is not:

    overwrite a running exe   -> PermissionError (file in use)
    rename a running exe      -> succeeds, process keeps running
    write a new file at the
      now-vacant original path-> succeeds
    delete the renamed file
      while the process lives -> access denied
    delete it after exit      -> succeeds

That asymmetry is what makes a one-double-click upgrade possible. The
running process names itself out of the way, drops the new executable into
place, and then restarts from the new file. It cannot delete its own old
image, so the leftover is cleaned up by the next launch, which can.

The sequence
------------
    1. new exe starts, sees no other instance -> nothing to update
    1. new exe starts, finds a running one    -> asks it to quit
    2. old exe acknowledges, stops the tray, exits
    3. new exe renames the old file aside, writes itself into place
    4. new exe launches the file it just installed and exits
    5. the installed copy cleans up the leftover image

Nothing here needs administrator rights: everything happens in the folder
the executable already lives in, and the autostart entry is per-user.

Why a relaunch rather than continuing
-------------------------------------
The new process is still the downloaded file, running from wherever the
user saved it (often Downloads). Continuing from there would leave the
installed copy untouched and the two would drift apart. Relaunching from
the installed path is what makes "just double-click the package" work.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

#: Named event the running instance waits on. Signalling it means "shut down
#: so you can be replaced".
SHUTDOWN_EVENT = "StreamScale.QuitForUpdate"

#: Written by the updater before it exits, so the installed copy knows it was
#: just upgraded and can report that rather than looking like a fresh install.
HANDOFF_FLAG = "just-updated.flag"

_MUTEX_NAME = "Global\\StreamScaleTraySingleton"
_MUTEX_ALREADY_EXISTS = 183

#: How long to wait for the old instance to exit after asking politely.
QUIT_TIMEOUT = 20.0

_k32 = ctypes.windll.kernel32

_k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
_k32.OpenProcess.restype = wt.HANDLE
_k32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD,
                                            ctypes.c_wchar_p, ctypes.POINTER(wt.DWORD)]
_k32.QueryFullProcessImageNameW.restype = wt.BOOL
_k32.CreateEventW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.BOOL, ctypes.c_wchar_p]
_k32.CreateEventW.restype = wt.HANDLE
_k32.OpenEventW.argtypes = [wt.DWORD, wt.BOOL, ctypes.c_wchar_p]
_k32.OpenEventW.restype = wt.HANDLE
_k32.SetEvent.argtypes = [wt.HANDLE]
_k32.SetEvent.restype = wt.BOOL
_k32.CloseHandle.argtypes = [wt.HANDLE]

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
EVENT_MODIFY_STATE = 0x0002
STILL_ACTIVE = 259


# ----------------------------------------------------------------------
# Process helpers
# ----------------------------------------------------------------------

def process_image_path(pid: int) -> Optional[Path]:
    """Full path of a running process's executable, or None."""
    handle = _k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = wt.DWORD(len(buf))
        if _k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return Path(buf.value)
        return None
    finally:
        _k32.CloseHandle(handle)


def process_alive(pid: int) -> bool:
    handle = _k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        code = wt.DWORD()
        if _k32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return code.value == STILL_ACTIVE
        return False
    finally:
        _k32.CloseHandle(handle)


_k32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
_k32.GetExitCodeProcess.restype = wt.BOOL


def list_pids(image_name: str) -> List[int]:
    """PIDs of every process with this image name.

    tasklist rather than a toolhelp snapshot: it is always present, and the
    output is small. Decoded as GBK because that is what a Chinese Windows
    emits -- UTF-8 would raise and look like a broken parser.
    """
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, encoding="gbk", errors="replace",
            creationflags=CREATE_NO_WINDOW, timeout=20,
        ).stdout or ""
    except (OSError, subprocess.SubprocessError):
        return []

    pids: List[int] = []
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) >= 2 and parts[0].lower() == image_name.lower():
            try:
                pids.append(int(parts[1]))
            except ValueError:
                continue
    return pids


def running_instances(exe_path: Path) -> List[int]:
    """PIDs of processes running from exactly this path (excluding us).

    Compares the full image path, not just the name: a user may have kept an
    older copy in Downloads, and signalling that one would shut down an
    unrelated installation.
    """
    wanted = str(exe_path.resolve()).lower()
    ours = os.getpid()
    found = []
    for pid in list_pids(exe_path.name):
        if pid == ours:
            continue
        image = process_image_path(pid)
        if image is not None and str(image).lower() == wanted:
            found.append(pid)
    return found


# ----------------------------------------------------------------------
# Asking the running instance to step aside
# ----------------------------------------------------------------------

class ShutdownSignal:
    """Named event used to ask a running instance to exit."""

    def __init__(self, name: str = SHUTDOWN_EVENT):
        self.name = name
        self._handle = None

    def create(self):
        """Create (or open) the event and hand back a waitable handle."""
        self._handle = _k32.CreateEventW(None, True, False, self.name)
        return self._handle

    def wait_handle(self):
        return self._handle

    def trigger(self) -> bool:
        """Signal a running instance to quit. True if one was listening."""
        handle = _k32.OpenEventW(EVENT_MODIFY_STATE, False, self.name)
        if not handle:
            return False
        try:
            return bool(_k32.SetEvent(handle))
        finally:
            _k32.CloseHandle(handle)

    def clear(self) -> None:
        if self._handle:
            _k32.ResetEvent(self._handle)

    def close(self) -> None:
        if self._handle:
            _k32.CloseHandle(self._handle)
            self._handle = None


_k32.ResetEvent.argtypes = [wt.HANDLE]


def wait_for_exit(pids: List[int], timeout: float = QUIT_TIMEOUT) -> bool:
    """Block until every pid is gone, or the timeout expires."""
    deadline = time.time() + timeout
    remaining = list(pids)
    while remaining and time.time() < deadline:
        remaining = [p for p in remaining if process_alive(p)]
        if remaining:
            time.sleep(0.25)
    return not remaining


# ----------------------------------------------------------------------
# The upgrade itself
# ----------------------------------------------------------------------

@dataclass
class UpdateOutcome:
    performed: bool = False
    detail: str = ""
    installed_to: Optional[Path] = None
    old_image: Optional[Path] = None   # leftover, deleted by the next launch
    restart: bool = False


def request_quit(pids: List[int]) -> bool:
    """Signal, then wait. Falls back to a terminate if the app ignores us."""
    signal = ShutdownSignal()
    signalled = signal.trigger()
    if not signalled:
        # No event object: an instance from an older build that predates this
        # mechanism. Wait it out, then ask Windows to close it.
        return False

    if wait_for_exit(pids, QUIT_TIMEOUT):
        return True

    # Still alive after a polite request. Terminate rather than leave the
    # user stuck -- they asked for an upgrade by double-clicking.
    for pid in pids:
        if process_alive(pid):
            subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           capture_output=True, text=True,
                           encoding="gbk", errors="replace",
                           creationflags=CREATE_NO_WINDOW)
    return wait_for_exit(pids, 10.0)


def perform_update(target: Path, running_pids: Optional[List[int]] = None) -> UpdateOutcome:
    """Replace `target` with the currently running executable.

    Returns what happened. Nothing is deleted that cannot be recreated: the
    old image is renamed, not removed, and it is left for the next launch to
    clean up because a process cannot delete its own running image.
    """
    source = Path(sys.executable).resolve()
    target = Path(target).resolve()

    if source == target:
        return UpdateOutcome(detail="already running from the install path")

    outcome = UpdateOutcome()

    if running_pids:
        if not request_quit(running_pids):
            return UpdateOutcome(
                detail="the running copy did not exit; close it from its "
                       "tray menu and try again")
        outcome.restart = True

    if not target.parent.exists():
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return UpdateOutcome(detail=f"cannot create {target.parent}: {exc}")

    # Renaming is permitted for a running image; overwriting is not. If the
    # rename fails the old file is gone for another reason and we can simply
    # write in its place.
    old_image = None
    if target.exists():
        old_image = target.with_name(target.stem + ".old" + target.suffix)
        try:
            if old_image.exists():
                old_image.unlink()
        except OSError:
            pass
        try:
            os.replace(target, old_image)
        except OSError as exc:
            outcome.detail = f"cannot move the old version aside: {exc}"
            return outcome

    try:
        _copy_self_safely(source, target)
    except OSError as exc:
        # Put the original back so the user is not left without an install.
        if old_image is not None and not target.exists():
            try:
                os.replace(old_image, target)
            except OSError:
                pass
        outcome.detail = f"cannot write the new version: {exc}"
        return outcome

    outcome.performed = True
    outcome.installed_to = target
    outcome.old_image = old_image
    outcome.detail = f"updated {target.name}"
    return outcome


def _copy_self_safely(source: Path, target: Path) -> None:
    """Copy bytes rather than using shutil.copy2.

    copy2 also copies metadata, and on an exe that can fail or preserve a
    read-only attribute that would block the next upgrade. Only the data and
    the executable bit matter here.
    """
    import shutil

    with open(source, "rb") as src, open(target, "wb") as dst:
        shutil.copyfileobj(src, dst, length=1024 * 1024)
    try:
        shutil.copymode(source, target)
    except OSError:
        pass


def relaunch(path: Path, wait_for_pid: Optional[int] = None) -> None:
    """Start the freshly installed copy, detached from this process."""
    if wait_for_pid:
        wait_for_exit([wait_for_pid], 5.0)

    creation = 0x00000008 | 0x00000200        # DETACHED_PROCESS | NEW_PROCESS_GROUP
    subprocess.Popen([str(path)], cwd=str(path.parent),
                     creationflags=creation | CREATE_NO_WINDOW,
                     close_fds=True,
                     stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)


# ----------------------------------------------------------------------
# Leftover cleanup, run by the installed copy
# ----------------------------------------------------------------------

def clean_up_previous_image() -> Optional[Path]:
    """Delete the `.old` file left by a previous upgrade.

    Called on startup by the installed copy. It can do what the upgrading
    process could not: a process may delete a file that is not its own
    running image.
    """
    if not getattr(sys, "frozen", False):
        return None
    me = Path(sys.executable).resolve()
    stale = me.with_name(me.stem + ".old" + me.suffix)
    if not stale.exists():
        return None
    for _ in range(10):
        try:
            stale.unlink()
            return stale
        except PermissionError:
            # The upgrading process may still be shutting down.
            time.sleep(0.5)
        except OSError:
            return None
    return None


def mark_handoff(directory: Path, version: str) -> None:
    """Record that we started the installed copy, so it can say so."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / HANDOFF_FLAG).write_text(version, encoding="utf-8")
    except OSError:
        pass


def consume_handoff(directory: Path) -> Optional[str]:
    """Read and remove the handoff flag. Returns the version it carried."""
    path = directory / HANDOFF_FLAG
    if not path.exists():
        return None
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        value = ""
    try:
        path.unlink()
    except OSError:
        pass
    return value or "unknown"


# ----------------------------------------------------------------------
# Version comparison
# ----------------------------------------------------------------------

def read_exe_version(path: Path) -> Optional[str]:
    """The version recorded in an executable's Windows version resource.

    PyInstaller writes one when given `--version-file`, and Windows exposes
    it without running the binary. That matters: the whole point is to
    compare against an executable we must not start.
    """
    if not path.exists():
        return None
    version = ctypes.windll.version
    version.GetFileVersionInfoSizeW.argtypes = [ctypes.c_wchar_p,
                                                ctypes.POINTER(wt.DWORD)]
    version.GetFileVersionInfoSizeW.restype = wt.DWORD
    version.GetFileVersionInfoW.argtypes = [ctypes.c_wchar_p, wt.DWORD, wt.DWORD,
                                            ctypes.c_void_p]
    version.GetFileVersionInfoW.restype = wt.BOOL
    version.VerQueryValueW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                                       ctypes.POINTER(ctypes.c_void_p),
                                       ctypes.POINTER(wt.UINT)]
    version.VerQueryValueW.restype = wt.BOOL

    handle = wt.DWORD(0)
    size = version.GetFileVersionInfoSizeW(str(path), ctypes.byref(handle))
    if not size:
        return None
    buffer = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(str(path), 0, size, buffer):
        return None

    value = ctypes.c_void_p()
    length = wt.UINT()
    if not version.VerQueryValueW(buffer, "\\", ctypes.byref(value),
                                  ctypes.byref(length)):
        return None

    class FIXEDFILEINFO(ctypes.Structure):
        _fields_ = [("signature", wt.DWORD), ("struct_version", wt.DWORD),
                    ("file_version_ms", wt.DWORD), ("file_version_ls", wt.DWORD),
                    ("product_version_ms", wt.DWORD), ("product_version_ls", wt.DWORD)]

    info = ctypes.cast(value, ctypes.POINTER(FIXEDFILEINFO)).contents
    if not info.signature:
        return None
    ms, ls = info.file_version_ms, info.file_version_ls
    return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"


def parse_version(text: str) -> tuple:
    """Turn "1.2.3" into a comparable tuple, ignoring any suffix.

    Deliberately forgiving: a version string that cannot be parsed should
    not crash an upgrade, it should just compare as older.
    """
    if not text:
        return (0,)
    cleaned = str(text).strip().lstrip("vV")
    for separator in ("-", "+", " "):
        cleaned = cleaned.split(separator)[0]
    parts = []
    for chunk in cleaned.split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def compare_versions(a: str, b: str) -> int:
    """1 if a is newer than b, -1 if older, 0 if equal."""
    left, right = parse_version(a), parse_version(b)
    length = max(len(left), len(right))
    left += (0,) * (length - len(left))
    right += (0,) * (length - len(right))
    return (left > right) - (left < right)

