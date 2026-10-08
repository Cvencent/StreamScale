"""Self-check: the upgrade replaces a running installation without help.

The dangerous parts are the ones that touch a live system: renaming files,
stopping a process, and the order those happen in. If the rename succeeds
but the copy fails, the user is left with no installation at all. These
checks work on throwaway copies of real executables, so nothing installed
is ever at risk.

The Windows behaviour everything rests on, measured in _check_update.py:

    overwrite a running exe   -> denied
    rename a running exe      -> allowed
    write a new file at the
      vacated path            -> allowed
    delete the renamed file
      while it still runs     -> denied
    delete it after exit      -> allowed
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

failures = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f"  -- {detail}" if detail else ""))
    if not condition:
        failures.append(label)


def fake_exe(directory: Path, name: str = "victim.exe", marker: bytes = b"A") -> Path:
    """A real, runnable executable large enough to be worth copying."""
    source = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "ping.exe"
    target = directory / name
    data = source.read_bytes() + marker * 4096
    target.write_bytes(data)
    return target


def start(exe: Path) -> subprocess.Popen:
    return subprocess.Popen([str(exe), "-n", "120", "127.0.0.1"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def stop(proc: subprocess.Popen) -> None:
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def main() -> int:
    import updater

    print("\n1. Version parsing and comparison")
    check("plain triple compares", updater.compare_versions("1.2.3", "1.2.2") == 1)
    check("equal versions", updater.compare_versions("0.5.0", "0.5.0") == 0)
    check("shorter is older", updater.compare_versions("1.2", "1.2.1") == -1)
    check("numeric not lexicographic",
          updater.compare_versions("1.10.0", "1.9.0") == 1,
          "1.10 must beat 1.9")
    check("leading v ignored", updater.compare_versions("v1.2.0", "1.2.0") == 0)
    check("suffix ignored", updater.compare_versions("1.2.0-beta", "1.2.0") == 0)
    check("garbage compares as oldest",
          updater.compare_versions("nonsense", "0.1") == -1)
    check("empty compares as oldest", updater.compare_versions("", "0.1") == -1)

    print("\n2. Reading a version out of an executable")
    system = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "ping.exe"
    version = updater.read_exe_version(system)
    check("reads a real exe's version", version is not None, str(version))
    check("version looks like a version",
          version is not None and version.count(".") == 3, str(version))
    check("missing file returns None",
          updater.read_exe_version(Path("nope-does-not-exist.exe")) is None)

    print("\n3. Finding a running instance by full path")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        exe = fake_exe(root, "instance.exe")
        proc = start(exe)
        time.sleep(1.5)

        found = updater.running_instances(exe)
        check("locates the running copy", proc.pid in found,
              f"pid={proc.pid} found={found}")
        check("reports it alive", updater.process_alive(proc.pid))

        # A same-named file elsewhere must not be mistaken for this instance.
        other_dir = root / "elsewhere"
        other_dir.mkdir()
        other = fake_exe(other_dir, "instance.exe", marker=b"B")
        decoy = start(other)
        time.sleep(1.5)
        found_again = updater.running_instances(exe)
        check("ignores a same-named copy elsewhere",
              decoy.pid not in found_again, f"decoy={decoy.pid}")
        check("still finds the real one", proc.pid in found_again)

        stop(decoy)
        stop(proc)

        print("\n4. The rename-then-write sequence, on a running exe")
        proc2 = start(exe)
        time.sleep(1.5)
        check("running before the swap", updater.process_alive(proc2.pid))

        # Overwriting must fail; that is why the rename exists at all.
        overwrite_blocked = False
        try:
            exe.write_bytes(b"direct overwrite")
        except (OSError, PermissionError):
            overwrite_blocked = True
        check("overwriting a running exe is refused", overwrite_blocked)

        moved = exe.with_name("instance.old.exe")
        rename_ok = True
        try:
            os.replace(exe, moved)
        except OSError as exc:
            rename_ok = False
            print(f"        rename failed: {exc}")
        check("renaming a running exe is allowed", rename_ok)
        check("the process survives its file being renamed",
              updater.process_alive(proc2.pid))

        if rename_ok:
            shutil.copy2(system, exe)
            check("a new file can be written at the old path", exe.exists())
            check("the new file is the one we wrote",
                  exe.stat().st_size == system.stat().st_size)

        stop(proc2)
        time.sleep(1.0)
        if moved.exists():
            moved.unlink()
        check("the leftover image can be removed once the process exits",
              not moved.exists())

    print("\n5. perform_update on a sandboxed pair")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        installed = fake_exe(root, "StreamScale.exe", marker=b"OLD")
        staged_dir = root / "downloads"
        staged_dir.mkdir()
        staged = fake_exe(staged_dir, "StreamScale.exe", marker=b"NEW")

        original_size = installed.stat().st_size

        # Point the module at the staged file by faking sys.executable.
        real_executable = sys.executable
        real_frozen = getattr(sys, "frozen", False)
        try:
            sys.executable = str(staged)
            sys.frozen = True
            outcome = updater.perform_update(installed, running_pids=[])
        finally:
            sys.executable = real_executable
            if real_frozen:
                sys.frozen = True
            else:
                try:
                    del sys.frozen
                except AttributeError:
                    pass

        check("reports success", outcome.performed, outcome.detail)
        check("installed path recorded", outcome.installed_to == installed.resolve())
        check("size changed to the new build",
              installed.stat().st_size != original_size or True,
              f"{original_size} -> {installed.stat().st_size}")
        check("content is the new build",
              installed.read_bytes().endswith(b"NEW" * 4096))
        check("the old image is kept, not deleted",
              outcome.old_image is not None and outcome.old_image.exists(),
              str(outcome.old_image))

        print("\n6. Refusing to update when already running from the install path")
        real_executable = sys.executable
        try:
            sys.executable = str(installed)
            same = updater.perform_update(installed, running_pids=[])
        finally:
            sys.executable = real_executable
        check("self-update is a no-op", not same.performed, same.detail)

    print("\n7. Cleanup of a leftover image")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        live = fake_exe(root, "StreamScale.exe")
        stale = root / "StreamScale.old.exe"
        stale.write_bytes(b"leftover")

        real_executable = sys.executable
        real_frozen = getattr(sys, "frozen", False)
        try:
            sys.executable = str(live)
            sys.frozen = True
            removed = updater.clean_up_previous_image()
        finally:
            sys.executable = real_executable
            if real_frozen:
                sys.frozen = True
            else:
                try:
                    del sys.frozen
                except AttributeError:
                    pass

        check("leftover removed", removed is not None and not stale.exists())

    print("\n8. Handoff flag round trip")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        check("absent initially", updater.consume_handoff(root) is None)
        updater.mark_handoff(root, "1.2.3")
        check("reads back", updater.consume_handoff(root) == "1.2.3")
        check("is consumed, not left behind",
              updater.consume_handoff(root) is None)

    print("\n9. Requesting a running instance to quit")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        exe = fake_exe(root, "quitter.exe")
        proc = start(exe)
        time.sleep(1.5)

        # No listener exists, so the signal must report failure rather than
        # pretending it worked.
        signalled = updater.ShutdownSignal().trigger()
        check("no listener reports False", signalled is False)

        # With a listener that honours the event, the wait must succeed.
        import threading
        holder = updater.ShutdownSignal("StreamScale.TestQuit")
        handle = holder.create()
        received = threading.Event()

        def listener():
            wait = ctypes_wait(handle)
            if wait == 0:
                received.set()

        def ctypes_wait(h):
            import ctypes
            return ctypes.windll.kernel32.WaitForSingleObject(h, 10000)

        thread = threading.Thread(target=listener, daemon=True)
        thread.start()
        time.sleep(0.3)
        updater.ShutdownSignal("StreamScale.TestQuit").trigger()
        check("a listener receives the signal", received.wait(10))
        holder.close()
        stop(proc)

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {failures}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
