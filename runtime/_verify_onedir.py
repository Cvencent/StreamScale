"""Final verification of the onedir build.

Checks the two things that matter, on the real artefact rather than a
re-implementation:

  1. Start-up is fast enough to be a Sunshine prep-command. The onefile
     build took 25 seconds, which Sunshine waited on twice per stream.
  2. Every verb exits instead of becoming a tray, and an unknown verb is
     refused rather than silently starting one. A prep-command that never
     returns is what stalled a real session and left the display
     configuration unrestored.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import updater  # noqa: E402

FOLDER = HERE / "dist" / "StreamScale"
EXE = FOLDER / "StreamScale.exe"

if not EXE.exists():
    raise SystemExit(f"not built: {EXE}")

files = [f for f in FOLDER.rglob("*") if f.is_file()]
total = sum(f.stat().st_size for f in files)
print(f"build: {EXE}")
print(f"  {len(files)} files, {total/1048576:.1f} MB, exe {EXE.stat().st_size/1048576:.1f} MB")
print(f"  version resource: {updater.read_exe_version(EXE)}")
print()

tmp = Path(tempfile.mkdtemp())
env = dict(os.environ)
env["LOCALAPPDATA"] = str(tmp / "local")
env["APPDATA"] = str(tmp / "appdata")
env["SUNSHINE_APP_NAME"] = "Brotato"
env["SUNSHINE_CLIENT_NAME"] = "X35S"
env["SUNSHINE_CLIENT_WIDTH"] = "1280"
env["SUNSHINE_CLIENT_HEIGHT"] = "960"
game = tmp / "game"
game.mkdir(parents=True)
(game / "Brotato.exe").write_bytes(b"")
cfg = tmp / "appdata" / "Brotato" / "123"
cfg.mkdir(parents=True)
settings = cfg / "settings.json"
settings.write_text('{"settings":{"font_size":1}}', encoding="utf-8")
env["STREAMSCALE_GAME_DIR"] = str(game)

failures = []


def check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  -- {detail}" if detail else ""))
    if not ok:
        failures.append(label)


print("=== 1. 启动耗时（Sunshine 每次串流等这个）===")
for args in (["--version"], ["show"], ["apply"], ["revert"]):
    times = []
    for _ in range(3):
        start = time.time()
        proc = subprocess.run([str(EXE)] + args, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=60, env=env,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        times.append(time.time() - start)
    best = min(times)
    worst = max(times)
    ok = worst < 5
    check(f"{args[0]:9} 最快 {best:.2f}s 最慢 {worst:.2f}s", ok)
    # Reset between cases so apply/revert do not interact.
    settings.write_text('{"settings":{"font_size":1}}', encoding="utf-8")

print()
print("=== 2. 未知命令必须拒绝（不再变成托盘）===")
for bad in ("nonsense", "--frobnicate", "apply2"):
    start = time.time()
    try:
        proc = subprocess.run([str(EXE), bad], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=15, env=env,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        elapsed = time.time() - start
        ok = proc.returncode not in (None, 0) and elapsed < 10
        check(f"{bad!r} 被拒绝 (rc={proc.returncode}, {elapsed:.2f}s)", ok)
    except subprocess.TimeoutExpired:
        check(f"{bad!r} 被拒绝", False, "超时 —— 可能启动了托盘")

print()
print("=== 3. apply/revert 真的改配置并还原 ===")
subprocess.run([str(EXE), "apply"], capture_output=True, timeout=60, env=env,
               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
after = json.loads(settings.read_text(encoding="utf-8"))
check("apply 提升了字号", after["settings"].get("font_size", 1) > 1,
      f"font_size={after['settings'].get('font_size')}")

subprocess.run([str(EXE), "revert"], capture_output=True, timeout=60, env=env,
               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
back = json.loads(settings.read_text(encoding="utf-8"))
check("revert 还原了字号", back["settings"].get("font_size") == 1,
      f"font_size={back['settings'].get('font_size')}")

print()
print("=== 4. 无参数仍启动托盘 ===")
proc = subprocess.Popen([str(EXE)], env=env,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(5)
alive = proc.poll() is None
check("托盘模式正常运行", alive)
if alive:
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except Exception:
        proc.kill()

print()
if failures:
    print(f"FAILED: {len(failures)}: {failures}")
    sys.exit(1)
print("全部通过")
