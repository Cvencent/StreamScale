"""Verify the folder-based self-update, end to end.

An upgrade now replaces a folder rather than a file, so the property that
matters is: with a tray running from inside the installed folder, a newer
copy can take its place and the installed copy ends up current.

Uses real copies of the built application, run for real -- the mechanism
depends on Windows' file locking, which cannot be simulated.
"""

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
import updater  # noqa: E402
sys.path.insert(0, str(HERE))
from _testenv import self_install_record  # noqa: E402


def _sweep_stale_trays() -> None:
    """Kill any tray left behind by an earlier check.

    Checks share the machine, so a surviving instance holds the
    single-instance lock and tails the real log. Sweeping before starting
    makes each check independent of the order it runs in.
    """
    try:
        subprocess.run(["taskkill", "/F", "/IM", "StreamScale.exe"],
                       capture_output=True, text=True,
                       encoding="gbk", errors="replace", timeout=20,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        pass
    time.sleep(1.0)


BUILT = HERE / "dist" / "StreamScale"
failures = []


def check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  -- {detail}" if detail else ""))
    if not ok:
        failures.append(label)


if not (BUILT / "StreamScale.exe").exists():
    raise SystemExit(f"not built: {BUILT}")

tmp = Path(tempfile.mkdtemp())
env = dict(os.environ)
env["LOCALAPPDATA"] = str(tmp / "local")
env["APPDATA"] = str(tmp / "appdata")
# The tray tails this to decide a stream has begun. Left pointing at the
# real file, a launched copy applies profiles for real -- which once changed
# the user's game settings outside a stream.
sunshine_log = Path(tmp) / "sunshine.log"
sunshine_log.write_text("", encoding="utf-8")
env["STREAMSCALE_SUNSHINE_LOG"] = str(sunshine_log)
env["STREAMSCALE_LOG_DIR"] = str(Path(tmp) / "local" / "StreamScale")
env["SUNSHINE_APP_NAME"] = "Brotato"
env["SUNSHINE_CLIENT_NAME"] = "X35S"
env["SUNSHINE_CLIENT_WIDTH"] = "1280"
env["SUNSHINE_CLIENT_HEIGHT"] = "960"
game = tmp / "game"
game.mkdir(parents=True)
(game / "Brotato.exe").write_bytes(b"")
env["STREAMSCALE_GAME_DIR"] = str(game)

print("=== 1. install_root 能区分文件夹布局 ===")
# install_root reads sys.executable, so point it at a real onedir exe.
real_exe, real_frozen = sys.executable, getattr(sys, "frozen", False)
try:
    sys.executable = str(BUILT / "StreamScale.exe")
    sys.frozen = True
    root = updater.install_root()
finally:
    sys.executable = real_exe
    if real_frozen:
        sys.frozen = True
    else:
        sys.__dict__.pop("frozen", None)
check("识别为文件夹安装", root == BUILT.resolve(), str(root))
check("_internal 存在", (BUILT / "_internal").is_dir())

print()
print("=== 2. 启动已安装的托盘，并找到它 ===")
installed = tmp / "install" / "StreamScale"
shutil.copytree(BUILT, installed)
exe = installed / "StreamScale.exe"

# Tell the copy under test that it *is* the installation. Without this it
# decides it is a package opened from elsewhere and exits rather than
# showing a tray.
self_install_record(tmp, exe)
_sweep_stale_trays()
proc = subprocess.Popen([str(exe)], env=env,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(6)
check("托盘已启动", proc.poll() is None, f"pid={proc.pid}")

found = updater.running_from_root(installed, "StreamScale.exe")
check("按文件夹找到运行实例", proc.pid in found, f"found={found}")

print()
print("=== 3. 请求它退出 ===")
signalled = updater.ShutdownSignal().trigger()
check("退出信号已发出", signalled)
exited = updater.wait_for_exit([proc.pid], 25)
check("托盘已退出", exited)

print()
print("=== 4. 替换整个文件夹 ===")
# Stage a "new version" by copying the build elsewhere, so the source and
# target are genuinely different paths.
staged = tmp / "downloads" / "StreamScale"
shutil.copytree(BUILT, staged)

real_exe, real_frozen = sys.executable, getattr(sys, "frozen", False)
try:
    sys.executable = str(staged / "StreamScale.exe")
    sys.frozen = True
    outcome = updater.perform_update(installed / "StreamScale.exe", running_pids=[])
finally:
    sys.executable = real_exe
    if real_frozen:
        sys.frozen = True
    else:
        sys.__dict__.pop("frozen", None)

check("替换成功", outcome.performed, outcome.detail)
check("安装位置是新文件夹", (installed / "StreamScale.exe").exists())
check("_internal 一并复制", (installed / "_internal").is_dir())
check("旧文件夹被保留待清理",
      outcome.old_image is not None and outcome.old_image.exists(),
      str(outcome.old_image))

print()
print("=== 5. 安装后的副本可以启动 ===")
proc2 = subprocess.Popen([str(installed / "StreamScale.exe")], env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(6)
alive = proc2.poll() is None
check("新副本运行正常", alive)
if alive:
    proc2.terminate()
    try:
        proc2.wait(timeout=8)
    except Exception:
        proc2.kill()
time.sleep(1.5)

print()
print("=== 6. 下次启动清理旧文件夹 ===")
# clean_up_previous_image looks beside sys.executable.
real_exe, real_frozen = sys.executable, getattr(sys, "frozen", False)
try:
    sys.executable = str(installed / "StreamScale.exe")
    sys.frozen = True
    removed = updater.clean_up_previous_image()
finally:
    sys.executable = real_exe
    if real_frozen:
        sys.frozen = True
    else:
        sys.__dict__.pop("frozen", None)
check("旧文件夹已删除", removed is not None, str(removed))
check("目录只剩当前版本",
      sorted(p.name for p in installed.parent.iterdir()) == ["StreamScale"],
      str([p.name for p in installed.parent.iterdir()]))

print()
if failures:
    print(f"FAILED: {len(failures)}: {failures}")
    sys.exit(1)
print("全部通过")
