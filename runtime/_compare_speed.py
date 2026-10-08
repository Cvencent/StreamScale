"""Compare startup cost: onefile vs onedir.

This is the measurement that decides how the app should ship.

onefile unpacks its ~19 MB payload into a temporary directory on *every*
run, then deletes it. Onedir leaves the files unpacked, so only the
interpreter start remains.

Two calls happen per stream (apply at the start, revert at the end), and the
tray itself is launched by hand, so a slow start is felt constantly. Sunshine
also waits for its prep-command, which makes a slow start a correctness
problem, not just an annoyance.
"""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ONEFILE = HERE / "dist" / "StreamScale.exe"
ONEDIR = HERE / "dist_onedir" / "StreamScale" / "StreamScale.exe"


def measure(exe: Path, args, env, runs=3):
    times = []
    for _ in range(runs):
        start = time.time()
        try:
            subprocess.run([str(exe)] + args, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120,
                           env=env,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            times.append(float("inf"))
            continue
        times.append(time.time() - start)
    return times


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
(cfg / "settings.json").write_text('{"settings":{"font_size":1}}', encoding="utf-8")
env["STREAMSCALE_GAME_DIR"] = str(game)

print("=== 启动耗时对比（各 3 次）===")
print()

for label, exe in (("onefile", ONEFILE), ("onedir", ONEDIR)):
    if not exe.exists():
        print(f"  {label}: 不存在 ({exe})")
        continue
    size = exe.stat().st_size / 1048576
    print(f"{label}  ({exe.parent.name}/)  exe {size:.1f} MB")

    for name, args in (("--version", ["--version"]), ("show", ["show"])):
        times = measure(exe, args, env)
        pretty = ", ".join(f"{t:.1f}s" if t != float("inf") else "超时" for t in times)
        best = min(times)
        print(f"    {name:10} {pretty}   最快 {best:.1f}s")
    print()

print("=== 完整目录大小 ===")
for label, p in (("onefile 单文件", ONEFILE), ("onedir 文件夹", ONEDIR.parent)):
    if p.exists():
        if p.is_file():
            print(f"  {label}: {p.stat().st_size/1048576:.1f} MB (单文件)")
        else:
            total = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
            count = sum(1 for f in p.rglob("*") if f.is_file())
            print(f"  {label}: {total/1048576:.1f} MB, {count} 个文件")
