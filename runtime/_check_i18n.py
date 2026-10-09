"""Self-check: the interface is fully translated in both languages.

Guards against the ways a translation goes wrong quietly:

  * a key used in code but absent from a table -> the raw key shows up in the
    interface;
  * a key in one language but not the other -> that language falls back to
    English mid-sentence, which looks like a bug to whoever is reading it;
  * a placeholder that exists in one language and not the other -> a value
    silently disappears from the sentence;
  * a literal left in the source, so the interface shows English regardless
    of the setting.

The last one is the hardest to notice by eye, so it is checked mechanically:
every user-facing string in the settings window and the tray is expected to
come from `t(...)`.

Log messages and command-line output are deliberately English, so they are
excluded -- see i18n.py for why.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import i18n  # noqa: E402

failures = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f"  -- {detail}" if detail else ""))
    if not condition:
        failures.append(label)


TRANSLATED_SOURCES = ("settings_window.py", "tray_app.py", "tray_icons.py")


def keys_used(path: Path) -> set:
    """Every key passed to t("...") in a source file."""
    source = path.read_text(encoding="utf-8")
    return set(re.findall(r'\bt\(\s*"([^"]+)"', source))


def hardcoded_strings(path: Path) -> list:
    """User-facing literals that bypass translation.

    Looks for the argument of a widget's `text=`, a message box, or a menu
    item. Comments, log calls and argparse descriptions are skipped: those
    are meant to stay English.
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    findings = []

    def is_user_facing(node: ast.Call) -> str:
        fn = node.func
        name = (fn.attr if isinstance(fn, ast.Attribute)
                else fn.id if isinstance(fn, ast.Name) else "")
        if name in ("showerror", "showinfo", "showwarning"):
            return "dialog"
        if name in ("Label", "Button", "Checkbutton", "Radiobutton",
                    "LabelFrame", "Menuitem", "Item"):
            return "widget"
        return ""

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        kind = is_user_facing(node)
        if not kind:
            continue

        candidates = []
        if kind == "dialog" and len(node.args) >= 2:
            candidates.append(node.args[1])
        for kw in node.keywords:
            if kw.arg == "text":
                candidates.append(kw.value)

        for value in candidates:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                text = value.value
                # Empty strings are placeholders filled in later, and short
                # ones are usually units or symbols.
                if len(text.strip()) > 2:
                    findings.append((node.lineno, text))
            elif isinstance(value, ast.Call):
                fn = value.func
                name = (fn.attr if isinstance(fn, ast.Attribute)
                        else fn.id if isinstance(fn, ast.Name) else "")
                # `t(...)` is the whole point; `str(exc)` passes an exception
                # through, whose text comes from the system and is not ours
                # to translate.
                if name in ("t", "str"):
                    continue
                findings.append((node.lineno, f"<{name}()>"))
    return findings


def main() -> int:
    print("\n1. Every key used in code exists")
    all_used = set()
    for name in TRANSLATED_SOURCES:
        path = HERE / name
        if not path.exists():
            check(f"{name} present", False)
            continue
        used = keys_used(path)
        all_used |= used
        unknown = sorted(used - set(i18n.ENGLISH))
        check(f"{name}: {len(used)} keys all defined", not unknown, str(unknown))

    print("\n2. Both languages define the same keys")
    gaps = i18n.missing_keys()
    check("no key missing from Chinese", not gaps["missing_chinese"],
          str(gaps["missing_chinese"]))
    check("no key missing from English", not gaps["missing_english"],
          str(gaps["missing_english"]))
    check(f"{len(i18n.ENGLISH)} keys in each", len(i18n.ENGLISH) == len(i18n.CHINESE),
          f"en={len(i18n.ENGLISH)} zh={len(i18n.CHINESE)}")

    print("\n3. Placeholders match between languages")
    mismatched = []
    for key in sorted(set(i18n.ENGLISH) & set(i18n.CHINESE)):
        en = set(re.findall(r"\{(\w+)\}", i18n.ENGLISH[key]))
        zh = set(re.findall(r"\{(\w+)\}", i18n.CHINESE[key]))
        if en != zh:
            mismatched.append((key, sorted(en), sorted(zh)))
    check("placeholders identical", not mismatched, str(mismatched))

    print("\n4. No user-facing English left hardcoded")
    for name in TRANSLATED_SOURCES:
        path = HERE / name
        if not path.exists():
            continue
        found = hardcoded_strings(path)
        check(f"{name}: no literals bypass t()", not found,
              "; ".join(f"line {ln}: {txt[:40]!r}" for ln, txt in found[:4]))

    print("\n5. Switching language changes the output")
    i18n.set_language("zh")
    zh_tab = i18n.t("settings.tab.general")
    zh_hint = i18n.t("general.text_hint")
    zh_fmt = i18n.t("general.text_label", value=2.45)
    i18n.set_language("en")
    en_tab = i18n.t("settings.tab.general")
    en_hint = i18n.t("general.text_hint")
    en_fmt = i18n.t("general.text_label", value=2.45)

    check("tab name differs", zh_tab != en_tab, f"{zh_tab!r} vs {en_tab!r}")
    check("hint differs", zh_hint != en_hint)
    check("formatted value differs", zh_fmt != en_fmt)
    check("formatted value keeps the number",
          "2.45" in zh_fmt and "2.45" in en_fmt, f"{zh_fmt!r} / {en_fmt!r}")
    check("Chinese has Han characters", any("\u4e00" <= ch <= "\u9fff" for ch in zh_hint))
    check("English is ASCII", en_hint.isascii())

    print("\n6. A missing key degrades without breaking")
    check("unknown key returns the key", i18n.t("no.such.key") == "no.such.key")
    check("normalise handles zh-CN", i18n.normalise("zh-CN") == "zh")
    check("normalise handles ZH_CN", i18n.normalise("ZH_CN") == "zh")
    check("normalise handles junk", i18n.normalise("klingon") == "en")
    check("normalise handles None", i18n.normalise(None) == "en")

    print("\n7. The drop-down offers both languages")
    codes = [code for code, _name in i18n.available_languages()]
    check("zh and en offered", set(codes) == {"zh", "en"}, str(codes))

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {failures}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
