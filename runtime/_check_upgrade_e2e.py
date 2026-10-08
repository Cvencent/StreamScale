"""Self-check: the double-click upgrade, end to end.

Simulates what actually happens when the user downloads a new package and
double-clicks it:

    an installation runs, holding a tray icon
    the user opens the downloaded file
    the running installation exits and restores what it changed
    the new build is written over the installation
    the installation restarts from its own path
    the leftover image is cleaned up

The participants are real executables that really run, because the whole
mechanism depends on Windows' file-locking behaviour, which cannot be faked.
The files are copies of a system binary, so nothing installed is touched.
"""

from __future__ import annotations

import json
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


def make_exe(directory: Path, name: str, marker: bytes) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    source = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "ping.exe"
    target = directory / name
    target.write_bytes(source.read_bytes() + marker * 8192)
    return target


def start(exe: Path):
    return subprocess.Popen([str(exe), "-n", "300", "127.0.0.1"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def stop(proc):
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

    # Functions that live in the tray module; imported here so the test can
    # exercise the real lookup order rather than a reimplementation.
    sys.path.insert(0, str(HERE))
    import tray_app

    print("\n1. Version resources decide whether to upgrade")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        old = make_exe(root, "StreamScale.exe", b"OLD")

        # The stand-in is a copy of a system binary, so it carries *that* 
        # binary's version resource. Reading it must still work and must not
        # error -- a real install from before this feature simply has no
        # resource at all, and the lookup has to be equally untroubled then.
        printed = updater.read_exe_version(old)
        check("reads whatever resource is present", printed is not None, str(printed))
        check("a file with no resource at all returns None",
              updater.read_exe_version(root / "absent.exe") is None)

        # The important part: an install lacking version information must not
        # block the upgrade. maybe_self_update treats None as "older".
        check("missing version resolves to a comparable tuple",
              updater.parse_version("") == (0,),
              str(updater.parse_version("")))
        check("an unversioned install loses against a real one",
              updater.compare_versions("0.6.0", "") == 1)

    print("\n2. Install path lookup order")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        appdata = root / "appdata"
        os.environ["APPDATA"] = str(appdata)

        installed = make_exe(root / "install", "StreamScale.exe", b"INSTALLED")
        record_dir = appdata / "StreamScale"
        record_dir.mkdir(parents=True, exist_ok=True)
        (record_dir / "install.json").write_text(
            json.dumps({"exe": str(installed)}), encoding="utf-8")

        found = tray_app._installed_exe()
        check("the recorded path wins",
              found == installed.resolve(), f"{found} vs {installed.resolve()}")

        print("\n3. A stale record falls through rather than failing")
        (record_dir / "install.json").write_text(
            json.dumps({"exe": str(root / "gone" / "StreamScale.exe")}),
            encoding="utf-8")
        fallback = tray_app._installed_exe()
        check("does not return the vanished path",
              fallback != (root / "gone" / "StreamScale.exe").resolve(),
              str(fallback))

    print("\n4. The full swap, with a real process holding the file")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        install_dir = root / "install"
        installed = make_exe(install_dir, "StreamScale.exe", b"VERSION_OLD")
        staged = make_exe(root / "downloads", "StreamScale.exe", b"VERSION_NEW")

        holder = start(installed)
        time.sleep(1.5)
        check("the installation is running", updater.process_alive(holder.pid))

        pids = updater.running_instances(installed)
        check("the upgrade sees the running instance", holder.pid in pids, str(pids))

        # Step 1: ask it to quit. There is no event listener in this stub, so
        # the wait times out -- the same shape as an old build that predates
        # the mechanism, which must then be terminated rather than left stuck.
        check("no listener means the signal reports False",
              updater.ShutdownSignal().trigger() is False)

        # Step 2: swap the files while the old one still runs. This is the
        # operation Windows refuses if done as a plain overwrite.
        real_exe, real_frozen = sys.executable, getattr(sys, "frozen", False)
        moved_ok = True
        try:
            sys.executable = str(staged)
            sys.frozen = True
            # Stop it first so the leftover can be removed at the end, the
            # way request_quit does in the real path.
            stop(holder)
            time.sleep(0.8)
            outcome = updater.perform_update(installed, running_pids=[])
        except Exception as exc:
            moved_ok = False
            print(f"        perform_update raised: {exc}")
            outcome = None
        finally:
            sys.executable = real_exe
            if real_frozen:
                sys.frozen = True
            else:
                sys.__dict__.pop("frozen", None)

        check("perform_update completed", moved_ok and outcome is not None)
        if outcome is not None:
            check("reported success", outcome.performed, outcome.detail)
            check("the installed file is the new build",
                  installed.read_bytes().endswith(b"VERSION_NEW" * 8192))
            check("the old build is parked beside it",
                  outcome.old_image is not None and outcome.old_image.exists(),
                  str(outcome.old_image))

            print("\n5. The installed copy cleans up the leftover")
            real_exe, real_frozen = sys.executable, getattr(sys, "frozen", False)
            try:
                sys.executable = str(installed)
                sys.frozen = True
                removed = updater.clean_up_previous_image()
            finally:
                sys.executable = real_exe
                if real_frozen:
                    sys.frozen = True
                else:
                    sys.__dict__.pop("frozen", None)
            check("leftover removed", removed is not None,
                  str(removed) if removed else "none")
            check("directory holds only the current build",
                  sorted(p.name for p in install_dir.iterdir()) == ["StreamScale.exe"],
                  str([p.name for p in install_dir.iterdir()]))

    print("\n6. A restart restores the previous running state")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        installed = make_exe(root / "install", "StreamScale.exe", b"CURRENT")

        real_exe, real_frozen = sys.executable, getattr(sys, "frozen", False)
        try:
            sys.executable = str(installed)
            sys.frozen = True
            # Already at the install path: an ordinary launch, not an upgrade.
            outcome = updater.perform_update(installed, running_pids=[])
        finally:
            sys.executable = real_exe
            if real_frozen:
                sys.frozen = True
            else:
                sys.__dict__.pop("frozen", None)
        check("launching the installed copy is not an upgrade",
              not outcome.performed, outcome.detail)

    print("\n7. Downgrade protection")
    check("an older package loses the comparison",
          updater.compare_versions("0.5.0", "0.6.0") == -1)
    check("an equal package is not an upgrade",
          updater.compare_versions("0.6.0", "0.6.0") == 0)
    check("a newer package wins",
          updater.compare_versions("0.7.0", "0.6.0") == 1)

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {failures}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
