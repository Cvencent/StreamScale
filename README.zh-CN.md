# StreamScale

[English](README.md) | **简体中文**

串流时按游戏自动调整 UI 缩放，退出后自动还原。

用 Sunshine + Moonlight 把电脑游戏串到掌机上时，界面往往看不清。一个为
1440p 桌面排版的 HUD，压到 3.5 寸、640×480 的掌机屏上就变成了 6 像素高的
小字。而把缩放设置全局调大又会毁掉电脑本地的游玩体验。

StreamScale 在串流开始时套用一份「按游戏、按客户端」的缩放配置，串流结束时
把设置还原。你的电脑和电视上跑的仍是原本的设置。

```
串流开始
        │
        ▼
StreamScale 读取 SUNSHINE_APP_NAME / SUNSHINE_CLIENT_NAME
        │
        ▼
匹配该游戏的适配器 → 备份 → 写入适合串流的值
        │
        ▼
   开玩，字看得清
        │
        ▼
串流结束 → StreamScale 还原到完全一致的原状态
```

## 为什么不直接用放大工具？

[Magpie](https://github.com/Blinue/Magpie)、Lossless Scaling 这类工具放大的
是**像素**。6 像素的字放大成 12 像素——但屏幕同时也大了一倍，所以字体相对
大小**完全没有变化**，还是一样看不清。

要让字真正变大，必须由**游戏自己重新排版 UI**，这只有游戏本身能做到。
StreamScale 就是把这件事自动化。

## 快速开始

```bat
git clone https://github.com/Cvencent/StreamScale.git StreamScale
cd StreamScale
python install\setup.py
```

`setup.py` 会生成一个启动器，并打印出可以直接粘贴到 Sunshine 的配置片段。
先验证识别是否正常——这一步**不会修改任何东西**：

```bat
streamscale.bat show
```

确认无误后，把打印出的 `prep-cmd` 填进 Sunshine 后台对应应用里
（Applications → 你的应用 → Prep Commands）。

### 或者用托盘程序

从 [Releases 页面](https://github.com/Cvencent/StreamScale/releases) 下载
`StreamScale.exe`，双击即可。它会常驻通知区域，并提供一个设置窗口——
可以改配置、也能**一键把预处理命令写进 `apps.json`**
（这一步原本最繁琐，现在点一下 Install 就行）。

托盘程序是配套工具，不是必需品：**关掉它，缩放功能照常工作。**
状态含义表、右键菜单逐项说明、排障表见
[StreamScale-托盘程序说明.md](StreamScale-托盘程序说明.md)。

想自己构建见 [runtime/README.md](runtime/README.md)。

## 识别原理

Sunshine 会向它启动的进程注入环境变量。StreamScale 只需要其中几个：

| 变量 | 含义 |
|---|---|
| `SUNSHINE_APP_NAME` | 当前串的是哪个游戏 |
| `SUNSHINE_CLIENT_NAME` | 哪个客户端在串（如 `X35S`、`TV`） |
| `SUNSHINE_CLIENT_WIDTH` / `_HEIGHT` | 客户端请求的分辨率 |

**不轮询窗口、不截屏分析、不猜。** 如果 `SUNSHINE_APP_NAME` 不存在，就说明
用户是在电脑上正常启动的游戏，StreamScale 什么都不做——这就是「不影响电脑
本地游玩」的机制保证。

## 配置

**可选**。没有配置文件时使用适配器内置的启发式规则。如需覆盖，创建
`%APPDATA%\StreamScale\config.json`：

```json
{
  "enabled": true,
  "excluded_apps": ["Desktop"],
  "max_client_width": 1600,
  "state_dir": "",
  "clients": {
    "X35S": { "brotato_font_size": 2.0 }
  }
}
```

| 键 | 作用 |
|---|---|
| `enabled` | 总开关 |
| `excluded_apps` | 这些应用永不处理 |
| `max_client_width` | 宽于此值的客户端跳过（例如放过电视） |
| `state_dir` | 备份存放位置；留空 = `~/.streamscale` |
| `clients` | 按客户端的精确覆盖，优先级高于启发式 |

## 已支持的游戏

| 游戏 | 机制 | 说明 |
|---|---|---|
| Brotato / 土豆兄弟 | `font_size` 倍率 | 该游戏用 Godot 的 `stretch/mode = 2d`，**降低渲染分辨率无效**——只有 `font_size` 能改变 UI 大小 |

新增一个游戏 = 在 `src/streamscale/games/` 下加一个模块 + 在 `registry.py`
里加一行。原子写入、备份、试运行都由基类处理，适配器只需描述**改什么**。

详见 [docs/adding-a-game.md](docs/adding-a-game.md)。

## 安全性

* 每次写入前都会备份完整的原状态。
* 写入是原子的（临时文件 + 替换），中途崩溃不会写坏存档。
* 配置文件缺失或无法解析时跳过该游戏，串流照常进行；**错误的配置永远不会
  导致游戏跑不起来**。
* 备份按应用名区分，多款游戏同时进行不会互相覆盖。

**请自行备份存档。** 本工具会修改游戏设置文件。它已经过测试且行为保守，
但仍建议你保留自己的备份。

## 已知限制

* **目前仅支持 Windows。** 识别逻辑本身是跨平台的，但路径解析和启动器不是。
* **一款游戏需要一个适配器。** 没有通用方案——每个游戏暴露 UI 缩放的方式
  都不同，有些甚至根本没有这个能力。没有该能力的游戏，本方案帮不上忙。
* **启发式看不到屏幕的物理尺寸**，只能按分辨率推断。默认值不合适时，在
  `clients` 里写死一个精确值。

## 测试

```bat
python tests\test_endtoend.py
```

测试会在临时目录中模拟 `%APPDATA%` 并调用真实的 CLI，验证：非串流启动不会
改动文件、串流时数值正确上调、还原后文件**逐字节一致**、超大客户端被跳过。

## 许可证

MIT
