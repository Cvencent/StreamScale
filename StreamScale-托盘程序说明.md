# StreamScale 托盘程序说明

一个常驻通知区域的小工具，用来**配置 StreamScale** 和**查看串流状态**。

---

## 它是什么，以及它不是什么

**重要**：StreamScale 的实际工作**不依赖这个程序**。

真正干活的机制是 Sunshine 的「预处理命令」——串流开始时 Sunshine 调用
`streamscale apply`，结束时调用 `streamscale revert`。这套机制**不需要任何常驻进程**。

托盘程序是一个**配套工具**，负责三件事：

| 作用 | 说明 |
|---|---|
| **看状态** | 一眼看出串流有没有开始、配置有没有生效 |
| **改配置** | `config.json` 原本要手改，现在有界面 |
| **装命令** | 把预处理命令写进 Sunshine 的 `apps.json`（这步最繁琐） |

**关掉托盘程序，缩放功能照常工作。** 这是刻意设计的。

---

## 启动

双击 `StreamScale.exe`，或 `启动StreamScale.bat`。

启动后**没有窗口弹出**，图标出现在右下角通知区域（可能在折叠的「显示隐藏的图标」里）。

> 如果没看到图标，点通知区域那个小三角 `^` 展开。

---

## 两种串流方式，都支持

这一点很容易踩坑，单独说明。

### 方式一：掌机列表里直接选游戏

需要先在 Sunshine 后台给游戏建一个独立条目（名字要和适配器对得上，例如 `Brotato`）。

串流开始 → Sunshine 执行预处理命令 → 配置生效。**钩子直接搞定，不依赖托盘。**

### 方式二：从 Steam 大屏幕里点进去

**这是更常见的用法，但钩子单独做不到。**

原因：Sunshine 的预处理命令**只在串流开始那一刻执行一次**。而从 Steam 进游戏时，
那一刻 Steam 才刚启动、游戏根本还没起来——改什么配置都没意义。

所以托盘程序会**在串流期间持续监视游戏进程**：

```
串流开始（Steam 大屏幕）
        ↓
托盘开始监视（此时 font_size 不动，正确）
        ↓
你点了土豆兄弟，游戏进程起来
        ↓
托盘检测到 brotato.exe  →  立刻应用配置  ✓
        ↓
你退出游戏  →  立刻还原  ✓
```

**这是托盘程序存在的核心理由之一**——没有它，从 Steam 进去的方式永远不生效。

> 监视只在**串流期间**进行，不串流时完全不扫描进程，不占资源。

**日志里能看到这个过程**（`View log` 菜单）：

```
watching for processes: brotato.exe
Brotato started -> {... font_size: 1 -> 1.75 ...}
Brotato exited  -> restored {... font_size: 1 ...}
```

---

## 图标颜色含义

图标只有 16×16，所以**颜色是主要信息，图形只是辅助**。

| 颜色 | 图形 | 含义 |
|---|---|---|
| ⚪ **灰色** | 两条竖线 | 待机中，没有串流 |
| 🟢 **绿色** | 播放三角 | **正在串流**，缩放已生效 |
| 🔵 **蓝色** | 回转箭头 | 串流刚结束，设置已还原 |
| 🔴 **红色** | 感叹号 | 出错，请看日志 |
| ⚫ **深灰** | 横线 | 已在设置里关闭 |

**鼠标悬停**可以看到详细状态，例如：

```
StreamScale - Streaming - scaling applied (1280x960, steam://open/bigpicture)
```

---

## 右键菜单

右键点击图标：

| 菜单项 | 作用 |
|---|---|
| **Settings...** | 打开设置窗口（**双击图标也是这个**） |
| **Start with Windows** | 开机自动启动（勾选状态就是当前状态） |
| **Open config folder** | 打开配置文件所在目录 |
| **View log** | 用记事本打开日志 |
| **Quit** | 退出程序 |

---

## 设置窗口

四个标签页：

### Install（安装）

**最常用的一页**，做一次就行。

1. 程序会自动找到 Sunshine 的 `apps.json`（找不到就点 `Browse...` 手动选）
2. 选 `All apps`（全部应用）或 `Only these`（逐个挑）
3. 点 **Install**

完成后**需要重启 Sunshine** 才生效。

- 点 `Remove` 可以撤销，只会移除 StreamScale 自己的那行，**不会影响你已有的其他预处理命令**
- 每次修改前都会备份成 `apps.json.streamscale.bak`

### General（通用）

| 项目 | 说明 |
|---|---|
| **Enable scaling** | 总开关。关掉后任何游戏都不处理 |
| **Skip clients wider than** | 宽于此值的客户端跳过。默认 1600，**让 4K 电视不受影响** |
| **Never touch these apps** | 这些应用永不处理，例如 `Desktop` |

### Overrides（覆盖值）

**按客户端写死一个精确值**，优先级高于自动推断。

自动推断是**按分辨率**猜的，看不到屏幕的物理尺寸。如果猜得不准，在这里手动指定：

```
Client name : X35S
Key         : brotato_font_size
Value       : 2.0
```

点 `Add / update` 生效。

### Status（状态）

一页只读信息，排查问题时很有用：

- 配置文件、日志文件的实际路径
- 当前使用的 apply / revert 命令
- 已内置适配器的游戏列表
- Sunshine 里**有几个应用已经装好**了 StreamScale

---

## 排障

| 现象 | 先做什么 |
|---|---|
| **双击没反应** | 看日志 `%LOCALAPPDATA%\StreamScale\tray.log`。没生成说明启动就崩了 |
| **图标不变色** | ① 确认 `Sunshine 日志` 路径正确（见 Status 页）② 确认 `Enable scaling` 是开的 |
| **装了命令但没效果** | ① **重启 Sunshine**（不重启不生效）② Settings → Status 页确认该应用显示为已安装 |
| **提示"已在运行"** | 已有实例。看通知区域（可能被折叠了），别重复启动 |
| **设置保存了但没生效** | 配置是**串流开始时**读取的，当前这次串流不会改变；下一次串流生效 |
| **不确定装了什么** | Status 页会列出所有已安装的应用名 |

**日志位置**：`%LOCALAPPDATA%\StreamScale\tray.log`
**配置位置**：`%APPDATA%\StreamScale\config.json`

---

## 需要管理员权限吗？

**不需要。** 托盘程序只写两个用户目录：

- `%APPDATA%\StreamScale\`（配置）
- `%LOCALAPPDATA%\StreamScale\`（日志）

开机自启写在 `HKCU`（当前用户），同样不需要提权。

**唯一例外**：Sunshine 装在 `C:\Program Files\` 时，写它的 `apps.json` 可能被系统拒绝。如果 Install 页报权限错误，用管理员身份运行一次 EXE 即可。

---

## 与命令行版的关系

两者**共用同一份配置**（`%APPDATA%\StreamScale\config.json`），改一边另一边立刻生效。

同时运行不会冲突——托盘只管配置和状态，命令行只在串流那一刻被 Sunshine 调用。
