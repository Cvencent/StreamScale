"""Self-check: override.cfg editing is surgical and reversible.

The riskiest property is that this must not damage a file it did not create.
Brotato's ModLoader reads override.cfg too, so overwriting it could break a
user's mod setup. Most of these checks are about what *survives* a round trip
rather than what changes.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

failures = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f"  -- {detail}" if detail else ""))
    if not condition:
        failures.append(label)


# A file as a user might already have it: comments, other sections, other
# keys in our own section, and values we must not touch.
EXISTING = """\
; ModLoader also reads this file -- do not clobber it.
[display]

window/size/resizable=true
window/stretch/aspect="keep"

[my_mod]
setting="do not touch"
number=42
"""


def main() -> int:
    from streamscale import godot

    print("\n1. Reading values")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "override.cfg"
        path.write_text(EXISTING, encoding="utf-8")
        values = godot.read_keys(path, "display",
                                 ["window/stretch/aspect", "window/missing"])
        check("finds an existing key",
              values["window/stretch/aspect"] == '"keep"', str(values))
        check("reports a missing key as None",
              values["window/missing"] is None)

    print("\n2. Missing file reads as absent")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "override.cfg"
        values = godot.read_keys(path, "display", ["window/stretch/aspect"])
        check("no file, no error", values["window/stretch/aspect"] is None)

    print("\n3. Editing an existing file preserves everything else")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "override.cfg"
        path.write_text(EXISTING, encoding="utf-8")

        record = godot.apply_keys(path, "display",
                                  {"window/stretch/aspect": "expand"})
        after = path.read_text(encoding="utf-8")

        check("target key updated",
              'window/stretch/aspect="expand"' in after)
        check("sibling key untouched",
              "window/size/resizable=true" in after)
        check("other section untouched",
              'setting="do not touch"' in after and "number=42" in after)
        check("comment preserved",
              "ModLoader also reads this file" in after)
        check("section header not duplicated",
              after.count("[display]") == 1, f"count={after.count('[display]')}")
        check("record remembers previous value",
              record.changes[0].previous == "keep",
              str(record.changes[0]))
        check("record notes the file existed", record.existed_before)

        print("\n4. Revert restores byte-for-byte")
        godot.revert_keys(path, record)
        restored = path.read_text(encoding="utf-8")
        check("identical to the original", restored == EXISTING,
              "differs" if restored != EXISTING else "")
        if restored != EXISTING:
            for i, (a, b) in enumerate(zip(EXISTING.splitlines(),
                                           restored.splitlines())):
                if a != b:
                    print(f"        line {i+1}: {a!r} != {b!r}")
                    break

    print("\n5. Adding a key that did not exist")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "override.cfg"
        path.write_text(EXISTING, encoding="utf-8")

        record = godot.apply_keys(path, "display",
                                  {"window/stretch/mode": "2d"})
        after = path.read_text(encoding="utf-8")
        check("key inserted", 'window/stretch/mode="2d"' in after)
        check("inserted into the right section",
              after.index("window/stretch/mode")
              < after.index("[my_mod]"))
        check("previous recorded as None",
              record.changes[0].previous is None)

        print("\n6. Revert removes the key it added, keeps the rest")
        godot.revert_keys(path, record)
        final = path.read_text(encoding="utf-8")
        check("added key gone", "window/stretch/mode" not in final)
        check("file identical to the original", final == EXISTING,
              "differs" if final != EXISTING else "")

    print("\n7. Creating the file from nothing")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "override.cfg"
        record = godot.apply_keys(path, "display",
                                  {"window/stretch/aspect": "ignore"})
        created = path.read_text(encoding="utf-8")
        check("file created", path.exists())
        check("section written", "[display]" in created)
        check("value written", 'window/stretch/aspect="ignore"' in created)
        check("noted as newly created", not record.existed_before)

        print("\n8. Revert deletes the file it created")
        godot.revert_keys(path, record)
        check("file removed", not path.exists())

    print("\n9. Line endings are preserved")
    for label, newline in (("CRLF", "\r\n"), ("LF", "\n")):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "override.cfg"
            body = newline.join(['[display]', '', 'window/stretch/aspect="keep"', ''])
            path.write_bytes(body.encode("utf-8"))

            record = godot.apply_keys(path, "display",
                                      {"window/stretch/aspect": "expand"})
            raw = path.read_bytes().decode("utf-8")
            expected = newline if newline == "\r\n" else "\n"
            crlf_count = raw.count("\r\n")
            lone_lf = raw.count("\n") - crlf_count
            if newline == "\r\n":
                ok = lone_lf == 0
            else:
                ok = crlf_count == 0
            check(f"{label} preserved", ok,
                  f"crlf={crlf_count} lf={lone_lf}")
            godot.revert_keys(path, record)

    print("\n10. Numeric values are not quoted")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "override.cfg"
        path.write_text("[display]\n\n", encoding="utf-8")
        godot.apply_keys(path, "display", {"window/size/width": "1280"})
        text = path.read_text(encoding="utf-8")
        check("number written bare", "window/size/width=1280" in text, text.strip())

    print("\n11. Keys outside the managed prefix are refused")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "override.cfg"
        try:
            godot.apply_keys(path, "display", {"audio/driver": "Dummy"})
            check("refuses foreign keys", False, "no exception")
        except ValueError:
            check("refuses foreign keys", True)
        check("no file created by a refused write", not path.exists())

    print("\n12. Missing section is created for a revert that needs it")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "override.cfg"
        path.write_text(EXISTING, encoding="utf-8")
        record = godot.apply_keys(path, "display",
                                  {"window/stretch/aspect": "expand"})
        # Simulate the user deleting the whole section while streaming.
        path.write_text("[my_mod]\nsetting=\"x\"\n", encoding="utf-8")
        godot.revert_keys(path, record)
        text = path.read_text(encoding="utf-8")
        check("section recreated with the old value",
              "[display]" in text and 'window/stretch/aspect="keep"' in text, text)
        check("unrelated content kept", 'setting="x"' in text)

    print("\n13. Adapter integration: aspect lever is wired up")
    import os
    sys.path.insert(0, str(HERE.parent / "src"))
    from streamscale import registry

    cls = registry.find("Brotato")
    check("adapter found", cls is not None)
    check("mixin is in the MRO",
          any(c.__name__ == "GodotAspectMixin" for c in cls.__mro__),
          str([c.__name__ for c in cls.__mro__[:4]]))
    check("declares the aspect key",
          cls.aspect_key == "window/stretch/aspect", str(cls.aspect_key))

    print("\n14. Adapter apply/revert round trip in a sandbox")
    import json as _json
    import shutil as _shutil
    import tempfile as _tempfile
    for label, original in (
        ("compact", b'{"settings":{"font_size":1,"fullscreen":true}}'),
        ("indented", _json.dumps({"settings": {"font_size": 1}}, indent=2).encode()),
        ("crlf", b'{\r\n  "settings": {\r\n    "font_size": 1\r\n  }\r\n}\r\n'),
    ):
        with _tempfile.TemporaryDirectory() as sandbox:
            root = Path(sandbox)
            gdir = root / "game"
            gdir.mkdir()
            (gdir / "Brotato.exe").write_bytes(b"")
            cfg = root / "appdata" / "Brotato" / "123"
            cfg.mkdir(parents=True)
            settings = cfg / "settings.json"
            settings.write_bytes(original)

            saved = {k: os.environ.get(k) for k in
                     ("APPDATA", "STREAMSCALE_GAME_DIR", "LOCALAPPDATA")}
            os.environ["APPDATA"] = str(root / "appdata")
            os.environ["STREAMSCALE_GAME_DIR"] = str(gdir)
            try:
                from streamscale import env as _env
                session = _env.Session(app_id="", app_name="Brotato", client_name="X35S",
                                       client_id="", client_unique_id="",
                                       width=1280, height=960, fps=60)
                adapter = cls(session, state_dir=root / "state")

                before = settings.read_bytes()
                adapter.apply()
                changed = _json.loads(settings.read_text(encoding="utf-8"))
                raised = changed["settings"]["font_size"] > 1
                override_written = (gdir / "override.cfg").exists()
                adapter.revert()
                after = settings.read_bytes()

                check(f"{label}: font raised", raised,
                      f"font_size={changed['settings']['font_size']}")
                check(f"{label}: override.cfg written", override_written)
                check(f"{label}: settings restored byte-for-byte",
                      before == after, f"{len(before)} -> {len(after)} bytes")
                check(f"{label}: override.cfg removed",
                      not (gdir / "override.cfg").exists())
            finally:
                for key, value in saved.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {failures}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
