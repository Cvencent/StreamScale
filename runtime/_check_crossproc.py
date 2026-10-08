"""Self-check: the aspect change survives a process boundary, and reverses.

The CLI runs `apply` and `revert` as two separate processes. An earlier
version kept the undo information in memory, so a revert -- running fresh,
with an empty memory -- found nothing to restore and silently left
override.cfg in the game directory. The checks here run apply and revert in
genuinely separate interpreters to prove the record reaches disk.

Also covers dry-run: `streamscale.bat show` must not write anything.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
SRC = PROJECT / "src"

failures = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f"  -- {detail}" if detail else ""))
    if not condition:
        failures.append(label)


# Runs in a child process: no shared state with the parent.
CHILD = r"""
import json, os, sys
sys.path.insert(0, r"{src}")
from pathlib import Path
from streamscale import registry, env

cls = registry.find("Brotato")
session = env.Session(app_id="", app_name="Brotato", client_name="X35S",
                      client_id="", client_unique_id="",
                      width=1280, height=960, fps=60)
adapter = cls(session, state_dir=Path(r"{state}"))
result = adapter.{method}()
print("RESULT|changed=%s|%s" % (result.changed, result.detail.replace("\n", " ")))
"""


def child(method: str, src: Path, state: Path, env: dict) -> str:
    code = CHILD.format(src=str(src), state=str(state), method=method)
    proc = subprocess.run([sys.executable, "-c", code], env=env,
                          capture_output=True, text=True, timeout=120)
    out = (proc.stdout or "").strip()
    for line in out.splitlines():
        if line.startswith("RESULT|"):
            return line
    return f"NO RESULT (rc={proc.returncode}) {out[-200:]}{(proc.stderr or '')[-200:]}"


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        gdir = root / "game"
        gdir.mkdir()
        (gdir / "Brotato.exe").write_bytes(b"")

        cfg_dir = root / "appdata" / "Brotato" / "123"
        cfg_dir.mkdir(parents=True)
        settings = cfg_dir / "settings.json"
        original = b'{\r\n  "settings": {\r\n    "font_size": 1\r\n  }\r\n}\r\n'
        settings.write_bytes(original)

        state_dir = root / "state"
        override = gdir / "override.cfg"

        env = dict(os.environ)
        env["APPDATA"] = str(root / "appdata")
        env["STREAMSCALE_GAME_DIR"] = str(gdir)
        env["LOCALAPPDATA"] = str(root / "local")

        print("\n1. show (dry-run) must not write anything")
        dry = r"""
import sys
sys.path.insert(0, r"{src}")
from pathlib import Path
from streamscale import registry, env
cls = registry.find("Brotato")
session = env.Session(app_id="", app_name="Brotato", client_name="X35S",
                      client_id="", client_unique_id="",
                      width=1280, height=960, fps=60)
adapter = cls(session, dry_run=True, state_dir=Path(r"{state}"))
r = adapter.apply()
print("RESULT|changed=%s|%s" % (r.changed, r.detail.replace(chr(10), " ")))
""".format(src=str(SRC), state=str(state_dir))
        proc = subprocess.run([sys.executable, "-c", dry], env=env,
                              capture_output=True, text=True, timeout=120)
        check("dry-run did not create override.cfg", not override.exists(),
              str(override))
        check("dry-run left settings untouched",
              settings.read_bytes() == original)
        check("dry-run left no undo record",
              not (state_dir / "Brotato.aspect.json").exists())

        print("\n2. apply in one process")
        line = child("apply", SRC, state_dir, env)
        print(f"    {line[:160]}")
        check("apply reported a change", "changed=True" in line, line[:80])
        check("override.cfg now exists", override.exists())
        check("font size raised",
              json.loads(settings.read_text(encoding="utf-8"))["settings"]["font_size"] > 1)
        check("undo record written to disk",
              (state_dir / "Brotato.aspect.json").exists(),
              str(state_dir))

        text = override.read_text(encoding="utf-8")
        check("aspect written", 'window/stretch/aspect="expand"' in text, text.strip())

        print("\n3. revert in a *different* process")
        line = child("revert", SRC, state_dir, env)
        print(f"    {line[:160]}")
        check("revert reported a change", "changed=True" in line, line[:80])
        check("override.cfg removed", not override.exists())
        check("settings byte-for-byte restored",
              settings.read_bytes() == original,
              f"{len(original)} -> {len(settings.read_bytes())}")
        check("undo record cleaned up",
              not (state_dir / "Brotato.aspect.json").exists())

        print("\n4. An existing override.cfg is merged, not destroyed")
        gdir.joinpath("override.cfg").write_text(
            '; someone else uses this\n[display]\n\nwindow/stretch/aspect="keep"\n\n'
            '[their_mod]\nsetting="keep me"\n', encoding="utf-8")
        before = override.read_bytes()

        line = child("apply", SRC, state_dir, env)
        merged = override.read_text(encoding="utf-8")
        check("other content survived the apply",
              'setting="keep me"' in merged and "someone else" in merged, merged)
        check("our key changed", 'window/stretch/aspect="expand"' in merged)

        line = child("revert", SRC, state_dir, env)
        check("restored to the file's prior text",
              override.read_bytes() == before,
              f"{len(before)} -> {len(override.read_bytes())}")

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {failures}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
