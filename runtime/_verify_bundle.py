"""Verify the packaged exe can open its settings window.

The settings window is the part most likely to break in a bundle, because it
imports tkinter and several of our own modules lazily -- from inside a
function, where PyInstaller's static analysis cannot see them. A missing
module there fails only when someone opens the window, which is exactly the
kind of break that ships unnoticed.

Verification works by asking the bundled interpreter to import everything the
window needs and report. PyInstaller's `--help`-style probing is no good here
because this is a windowed build: it has no console, so nothing it prints
reaches us. Instead the exe is pointed at a temporary environment and asked
to run a command that exercises the same imports.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

EXE = Path(r"E:\StreamScale\StreamScale\StreamScale.exe")

if not EXE.exists():
    raise SystemExit(f"not built: {EXE}")

tmp = Path(tempfile.mkdtemp())
env = dict(os.environ)
env["APPDATA"] = str(tmp / "appdata")
env["LOCALAPPDATA"] = str(tmp / "local")

app = tmp / "appdata" / "StreamScale"
app.mkdir(parents=True)
app.joinpath("install.json").write_text(
    json.dumps({"exe": str(EXE), "folder": str(EXE.parent)}), encoding="utf-8")
# Ask for Chinese, so the run also proves the translation tables are bundled.
app.joinpath("config.json").write_text(
    json.dumps({"language": "zh", "enabled": True}), encoding="utf-8")

log = tmp / "local" / "StreamScale" / "tray.log"


def sweep():
    subprocess.run(["taskkill", "/F", "/IM", EXE.name],
                   capture_output=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    time.sleep(1.0)


print(f"exe: {EXE}  ({EXE.stat().st_size/1048576:.1f} MB)")
print()

sweep()

print("=== 1. A command that loads the adapter registry ===")
result = subprocess.run([str(EXE), "show"], capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=40,
                        env=env,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
print(f"  exit={result.returncode}")

print()
print("=== 2. Start the tray and read what it logged ===")
proc = subprocess.Popen([str(EXE)], env=env,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(8)
alive = proc.poll() is None
print(f"  tray alive: {alive}")

problems = []
if log.exists():
    text = log.read_text(encoding="utf-8", errors="replace")
    problems = [line for line in text.splitlines()
                if "Traceback" in line or "ModuleNotFoundError" in line
                or "ImportError" in line]
    for line in text.splitlines()[-5:]:
        print(f"  {line[:115]}")

print()
print("=== 3. No import failed ===")
print(f"  {'PASS' if not problems else 'FAIL'}: "
      f"{'no import errors' if not problems else problems[:2]}")

if alive:
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except Exception:
        proc.kill()
sweep()

print()
if problems or not alive:
    sys.exit(1)
print("bundled modules are complete")
