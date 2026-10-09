"""Translations for everything a person reads.

The interface ships in Chinese and English, chosen from Settings and stored
in the config file.

Deliberately not translated
---------------------------
Log files and command-line output stay English. They are read while
diagnosing something, usually pasted into a search engine or a bug report,
and translated log lines are harder to search for and harder to match
against library documentation. Keeping them in one language also means the
same wording appears whether the interface is Chinese or English.

How a lookup works
------------------
`t(key)` returns the string for the active language. A key missing from the
active table falls back to English rather than showing a raw identifier, so
adding a setting never leaves a gap in the interface -- English appears
instead, which reads fine and is obviously a gap to fill.

Keys name where they appear, so call sites read without the table:

    t("settings.tab.general")
    t("tray.menu.quit")

Strings with `{name}` placeholders take those as keyword arguments:

    t("general.text_label", value=1.75)
"""

from __future__ import annotations

import threading
from typing import Dict, Optional, Tuple

DEFAULT_LANGUAGE = "en"

# (code, name shown in the drop-down)
LANGUAGES: Tuple[Tuple[str, str], ...] = (
    ("zh", "中文"),
    ("en", "English"),
)

_lock = threading.Lock()
_active = DEFAULT_LANGUAGE


ENGLISH: Dict[str, str] = {
    # window chrome
    "settings.title": "{app} Settings",
    "settings.button.save": "Save",
    "settings.button.close": "Close",
    "settings.button.browse": "Browse...",
    "settings.button.reset": "Reset",
    "settings.button.add": "Add",
    "settings.button.remove": "Remove",
    "settings.button.refresh": "Refresh",

    # tabs
    "settings.tab.install": "Install",
    "settings.tab.general": "General",
    "settings.tab.overrides": "Overrides",
    "settings.tab.status": "Status",

    # install tab
    "install.heading": "Add the press commands to Sunshine",
    "install.intro": (
        "Sunshine runs a command when a stream starts and another when it\n"
        "ends. Adding those here is what makes scaling automatic."
    ),
    "install.apps_json": "apps.json:",
    "install.not_found": "(not found - use Browse)",
    "install.dialog_title": "Select Sunshine's apps.json",
    "install.which_apps": "Which apps",
    "install.all_apps": "All apps",
    "install.only_these": "Only these:",
    "install.explainer": (
        "Revert restores your settings when the stream ends. Without it the\n"
        "scaled-up text stays until you change it back by hand."
    ),
    "install.status_checking": "Checking...",
    "install.status_present": "Installed on {count} app(s).",
    "install.status_absent": "Not installed.",

    # general tab
    "general.enable": "Enable scaling",
    "general.enable_note": "Turn this off to leave every game untouched.",
    "general.language": "Language",
    "general.language_note": (
        "Applies immediately. Log files stay in English either way."
    ),
    "general.text_title": "Text size",
    "general.text_note": (
        "The automatic size cannot see how large your screen physically is."
    ),
    "general.text_hint": "If the text is still too small, raise this.",
    "general.text_makes": "Makes text",
    "general.text_auto": "1.0x = automatic. Applies the next time a stream starts.",
    "general.text_label_auto": "{value:.2f}x  (automatic)",
    "general.text_label": "{value:.2f}x  (on top of automatic)",
    "general.text_estimate": "  \u2192 about {size} in the game",
    "general.fill_title": "Screen fill",
    "general.fill_note": (
        "Most games are laid out for a 16:9 screen, so on a 4:3\n"
        "handheld they leave black bars above and below."
    ),
    "general.fill.off": "Keep the game's own shape",
    "general.fill.off_note": "black bars, nothing distorted",
    "general.fill.expand": "Fill the screen (recommended)",
    "general.fill.expand_note": "no distortion, and you see more of the play area",
    "general.fill_scope": (
        "Works on Godot games (Brotato). Other games are left alone."
    ),
    "general.preapply": "Apply at stream start (recommended)",
    "general.preapply_note": (
        "Needed for games launched from Steam, where the game starts\n"
        "after the profile would otherwise have been applied."
    ),
    "general.width": "Skip clients wider than:",
    "general.width_unit": "px",
    "general.width_note": (
        "A 4K TV is comfortable already, so it is skipped by default."
    ),
    "general.excluded": "Never touch these apps:",
    "general.excluded_add": "Add",
    "general.excluded_remove": "Remove selected",

    # overrides tab
    "overrides.heading": "Pin an exact value for a specific client",
    "overrides.intro": (
        "By default the scale is picked from the client's resolution.\n"
        "That cannot tell two devices apart, so an exact value can be\n"
        "pinned here for one game and client."
    ),
    "overrides.client": "Client name",
    "overrides.key": "Key",
    "overrides.value": "Value",
    "overrides.add": "Add / update",
    "overrides.current": "Current overrides:",
    "overrides.remove": "Remove selected",
    "overrides.need_name": "Client name and key are both required.",
    "overrides.not_number": "'{value}' is not a number.",

    # status tab
    "status.heading": "What is installed, and where the files are",
    "status.open_log": "Open log",
    "status.open_config": "Open config folder",
    "status.install_state": "Install state",
    "status.apply_cmd": "Apply command",
    "status.revert_cmd": "Revert command",
    "status.enabled_short": "Enabled",
    "status.disabled_short": "Disabled",
    "status.log_hint": (
        "The log records every decision, including why a game was skipped.\n"
        "It is kept in English so it stays searchable."
    ),

    # messages
    "msg.bad_apps_json": "Select a valid apps.json first.",
    "msg.pick_one_app": "Select at least one app.",
    "msg.install_failed": "Install failed:\n{detail}",
    "msg.remove_failed": "Remove failed:\n{detail}",
    "msg.already_installed": "Already installed - nothing to change.",
    "msg.installed_ok": (
        "Done. {count} app(s) updated.\n\n"
        "A backup was saved next to apps.json.\n"
        "Restart Sunshine for the change to take effect."
    ),
    "msg.removed_ok": "Removed from {count} app(s).",
    "msg.width_not_number": "Width must be a number.",
    "msg.saved": "Settings saved.",
    "msg.save_failed": "Could not save:\n{detail}",
    "msg.saved_to": "Saved to\n{path}",

    # tray
    "tray.tooltip.idle": "StreamScale - waiting for a stream",
    "tray.tooltip.active": "StreamScale - streaming, profile applied",
    "tray.tooltip.reverted": "StreamScale - restored",
    "tray.tooltip.error": "StreamScale - error, see the log",
    "tray.tooltip.disabled": "StreamScale - off in settings",
    "tray.menu.settings": "Settings...",
    "tray.menu.autostart": "Start with Windows",
    "tray.menu.open_config": "Open config folder",
    "tray.menu.view_log": "View log",
    "tray.menu.quit": "Quit",
    "tray.already_running.title": "{app} - already running",
    "tray.already_running.body": (
        "A copy is already running.\n\n"
        "Look for its icon in the notification area."
    ),
    "tray.no_upgrade.title": "{app} - no upgrade needed",
    "tray.no_upgrade.body": (
        "You are opening {app} {new}, but {old} is already installed.\n\n"
        "Nothing was changed.\n\nInstalled at:\n{path}"
    ),
    "tray.start_failed.body": (
        "{app} failed to start.\n\nSee the log for details:\n{path}"
    ),
    "tray.update_failed.title": "{app} - update failed",
    "tray.update_failed.body": "{detail}",

    # shared
    "common.ok": "OK",
    "common.cancel": "Cancel",
    "common.error": "Error",
}


CHINESE: Dict[str, str] = {
    # window chrome
    "settings.title": "{app} 设置",
    "settings.button.save": "保存",
    "settings.button.close": "关闭",
    "settings.button.browse": "浏览…",
    "settings.button.reset": "重置",
    "settings.button.add": "添加",
    "settings.button.remove": "移除",
    "settings.button.refresh": "刷新",

    # tabs
    "settings.tab.install": "安装",
    "settings.tab.general": "常规",
    "settings.tab.overrides": "手动指定",
    "settings.tab.status": "状态",

    # install tab
    "install.heading": "把预处理命令装到 Sunshine",
    "install.intro": (
        "Sunshine 会在串流开始时执行一条命令、结束时再执行一条。\n"
        "把这两条装好，缩放就全自动了。"
    ),
    "install.apps_json": "apps.json：",
    "install.not_found": "（未找到，请点「浏览」）",
    "install.dialog_title": "选择 Sunshine 的 apps.json",
    "install.which_apps": "装到哪些应用",
    "install.all_apps": "所有应用",
    "install.only_these": "只装这些：",
    "install.explainer": (
        "「还原」会在串流结束时把设置改回去。\n"
        "不装它的话，放大后的字会一直留着，得手动改回来。"
    ),
    "install.status_checking": "检查中…",
    "install.status_present": "已装到 {count} 个应用。",
    "install.status_absent": "尚未安装。",

    # general tab
    "general.enable": "启用自动缩放",
    "general.enable_note": "关掉后不碰任何游戏（已安装的命令会保留）。",
    "general.language": "界面语言",
    "general.language_note": "立即生效。日志无论选哪种都保持英文。",
    "general.text_title": "文字大小",
    "general.text_note": "自动倍率看不到你屏幕的物理尺寸，所以这里可以再手动补一点。",
    "general.text_hint": "如果字还是小，就把这里调大。",
    "general.text_makes": "把文字放大",
    "general.text_auto": "1.0x = 自动。下次串流开始时生效。",
    "general.text_label_auto": "{value:.2f}x（自动）",
    "general.text_label": "{value:.2f}x（在自动值基础上再放大）",
    "general.text_estimate": "  \u2192 游戏里约为 {size}",
    "general.fill_title": "铺满屏幕",
    "general.fill_note": (
        "多数游戏是按 16:9 排版的，所以在 4:3 的掌机上\n"
        "上下会留出黑边。"
    ),
    "general.fill.off": "保持游戏原本比例",
    "general.fill.off_note": "有黑边，但画面不变形",
    "general.fill.expand": "铺满屏幕（推荐）",
    "general.fill.expand_note": "画面不变形，还能多看到一些场景",
    "general.fill_scope": "目前对 Godot 引擎的游戏有效（如 Brotato），其他游戏不动。",
    "general.preapply": "串流开始时立即应用（推荐）",
    "general.preapply_note": (
        "从 Steam 启动的游戏需要这一项——游戏会在配置该应用的时候\n"
        "才开始运行，只有提前应用才来得及。"
    ),
    "general.width": "宽度超过此值则不处理：",
    "general.width_unit": "像素",
    "general.width_note": "4K 电视本来就看得清，所以默认跳过。",
    "general.excluded": "永不处理这些应用：",
    "general.excluded_add": "添加",
    "general.excluded_remove": "删除选中",

    # overrides tab
    "overrides.heading": "为某台设备固定一个精确值",
    "overrides.intro": (
        "默认倍率由客户端的请求分辨率决定，无法区分两台设备。\n"
        "这里可以为「某个游戏 + 某台设备」固定一个精确值。"
    ),
    "overrides.client": "客户端名称",
    "overrides.key": "键名",
    "overrides.value": "值",
    "overrides.add": "添加或更新",
    "overrides.current": "已保存的条目：",
    "overrides.remove": "删除选中",
    "overrides.need_name": "客户端名称和键名都必须填写。",
    "overrides.not_number": "「{value}」不是数字。",

    # status tab
    "status.heading": "当前安装状态与文件位置",
    "status.open_log": "打开日志",
    "status.open_config": "打开配置文件夹",
    "status.install_state": "安装状态",
    "status.apply_cmd": "应用命令",
    "status.revert_cmd": "还原命令",
    "status.enabled_short": "已启用",
    "status.disabled_short": "已关闭",
    "status.log_hint": (
        "日志记录每一次判断，包括某个游戏为什么被跳过。\n"
        "日志保持英文，方便搜索。"
    ),

    # messages
    "msg.bad_apps_json": "请先选择一个有效的 apps.json。",
    "msg.pick_one_app": "请至少选一个应用。",
    "msg.install_failed": "安装失败：\n{detail}",
    "msg.remove_failed": "移除失败：\n{detail}",
    "msg.already_installed": "已经装好了，无需改动。",
    "msg.installed_ok": (
        "完成。已更新 {count} 个应用。\n\n"
        "备份已保存在 apps.json 旁边。\n"
        "重启 Sunshine 后生效。"
    ),
    "msg.removed_ok": "已从 {count} 个应用中移除。",
    "msg.width_not_number": "宽度必须是数字。",
    "msg.saved": "设置已保存。",
    "msg.save_failed": "保存失败：\n{detail}",
    "msg.saved_to": "已保存到\n{path}",

    # tray
    "tray.tooltip.idle": "StreamScale - 等待串流",
    "tray.tooltip.active": "StreamScale - 串流中，配置已应用",
    "tray.tooltip.reverted": "StreamScale - 已还原",
    "tray.tooltip.error": "StreamScale - 出错，请查看日志",
    "tray.tooltip.disabled": "StreamScale - 已在设置中关闭",
    "tray.menu.settings": "设置…",
    "tray.menu.autostart": "开机自动启动",
    "tray.menu.open_config": "打开配置文件夹",
    "tray.menu.view_log": "查看日志",
    "tray.menu.quit": "退出",
    "tray.already_running.title": "{app} - 已在运行",
    "tray.already_running.body": (
        "已经有一个副本在运行了。\n\n"
        "请在右下角通知区域找它的图标。"
    ),
    "tray.no_upgrade.title": "{app} - 无需升级",
    "tray.no_upgrade.body": (
        "你打开的是 {app} {new}，但已安装的是 {old}。\n\n"
        "没有做任何改动。\n\n已安装位置：\n{path}"
    ),
    "tray.start_failed.body": (
        "{app} 启动失败。\n\n详情见日志：\n{path}"
    ),
    "tray.update_failed.title": "{app} - 升级失败",
    "tray.update_failed.body": "{detail}",

    # shared
    "common.ok": "确定",
    "common.cancel": "取消",
    "common.error": "错误",
}


TABLES: Dict[str, Dict[str, str]] = {"en": ENGLISH, "zh": CHINESE}


def normalise(code: Optional[str]) -> str:
    """Map a stored or detected language onto one this module supports.

    Accepts the forms a config file or the system might hold -- `zh-CN`,
    `zh_CN`, `ZH` -- and falls back to the default rather than raising, since
    a bad value should not stop the application from starting.
    """
    if not code:
        return DEFAULT_LANGUAGE
    text = str(code).strip().lower().replace("_", "-")
    if text.startswith("zh"):
        return "zh"
    if text.startswith("en"):
        return "en"
    return DEFAULT_LANGUAGE


def system_language() -> str:
    """The language Windows is set to, as a code this module knows.

    Only an initial guess, for when nothing has been chosen yet; once the
    user picks a language that choice wins.
    """
    try:
        import ctypes

        # GetUserDefaultUILanguage returns a LANGID. The low ten bits are the
        # primary language, and 0x04 is Chinese.
        langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        if (langid & 0x03FF) == 0x04:
            return "zh"
        return "en"
    except Exception:
        return DEFAULT_LANGUAGE


def set_language(code: Optional[str]) -> str:
    """Choose the active language. Returns the code actually in use."""
    global _active
    resolved = normalise(code)
    with _lock:
        _active = resolved
    return resolved


def current_language() -> str:
    with _lock:
        return _active


def t(key: str, **fields) -> str:
    """The text for `key` in the active language.

    A key missing from the active table falls back to English, and one
    missing everywhere returns the key itself -- visible rather than blank,
    and easy to search the source for.
    """
    with _lock:
        language = _active
    table = TABLES.get(language, ENGLISH)
    text = table.get(key) or ENGLISH.get(key) or key
    if not fields:
        return text
    try:
        return text.format(**fields)
    except (KeyError, IndexError, ValueError):
        # A formatting mistake should not take the interface down; the
        # unformatted text is still more useful than a traceback.
        return text


def available_languages():
    """(code, display name) pairs for the language drop-down."""
    return LANGUAGES


def initial_language(config: Optional[dict] = None) -> str:
    """What to use before there is an explicit choice.

    A stored setting wins. Otherwise the system language is a better guess
    than assuming English.
    """
    if config:
        stored = config.get("language")
        if stored:
            return normalise(stored)
    return system_language()


def missing_keys() -> Dict[str, list]:
    """Keys present in one table but not the other, for a coverage check."""
    english = set(ENGLISH)
    chinese = set(CHINESE)
    return {
        "missing_chinese": sorted(english - chinese),
        "missing_english": sorted(chinese - english),
    }
