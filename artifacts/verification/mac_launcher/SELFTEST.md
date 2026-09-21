# mac 双击启动器（deploy/mac）——自测记录

日期：2026-09-21　范围：`deploy/mac/`（macOS 双击即用入口）

## 1. 交付物

| 文件 | 作用 |
|---|---|
| `qwb_launch.sh` | 共用启动逻辑：`open` / `serve` / `status` / `stop` / `setup` |
| `install_mac_launcher.sh` | 生成 `~/Applications/QuantWorkbench.app` + 桌面快捷方式；`--login` 装 LaunchAgent；`--dock` 加 Dock；`--uninstall` 卸载 |
| `start_workbench_mac.command` | 兜底双击入口（会弹终端窗口） |
| `README_MAC_LAUNCHER.md` | 给最终用户/实施者的说明 |

不修改任何既有代码（`app/`、`ui/`、`skill/`、`golden/` 零改动），只在 `deploy/` 下新增。

## 2. 语法检查（bash -n，Git Bash 1.2.0 / bash 5.x）

```
qwb_launch.sh                    syntax OK
install_mac_launcher.sh          syntax OK
start_workbench_mac.command      syntax OK
```

行尾符：三个脚本均无 `CR`（纯 LF），避免 macOS 上 `bad interpreter`。

## 3. 功能自测（本地实测输出）

环境：Windows 开发机，后端以 2026-09-21 数据在跑（127.0.0.1:8000）。

正向 —— 应识别为"运行中"：
```
[qwb] PKG_ROOT = <pkgroot>
[qwb] URL      = http://127.0.0.1:8000
[qwb] APPDATA  = <pkgroot>/appdata
[qwb] 状态     = 运行中
```

负向 —— 换端口应识别为"未运行"（证明 ready 判据不是常量）：
```
QWB_PORT=8123 -> [qwb] URL = http://127.0.0.1:8123 ; [qwb] 状态 = 未运行
```

门禁 —— 未知子命令应非零退出：
```
[qwb] 未知子命令: bogus（可用 open | serve | status | stop | setup） ; exit=2
```

## 4. 设计要点（防止"双击了没反应"）

1. `.app` 内是可执行脚本 + `LSUIElement=true`，**不弹终端窗口**；
2. `ensure_venv`：首次双击若缺 `.venv`，自动跑 `deploy/bootstrap.sh setup` 并弹窗告知（约 2–5 分钟）；
3. 启动失败时用 `osascript` 弹窗提示去查 `appdata/logs/server.log`，而不是静默失败；
4. `PATH` 自行补全（`/opt/homebrew/bin` 等），因为 .app / launchd 的环境极简；
5. `serve` 模式在已有实例时**等待其退出再接管**，避免 `KeepAlive` 造成 10s 空转重启环；
6. `status/stop` 用 `lsof` 定位监听端口进程，不依赖 pid 文件是否陈旧。

## 5. 未在 macOS 实机验证的部分（交 M4 端验收）

以下依赖 macOS 专属能力，Windows 侧无法验证，需 M4 部署时确认：

- `launchctl bootstrap gui/$(id -u)` 加载 LaunchAgent（脚本已带 `load -w` 回退分支）；
- `~/Applications/QuantWorkbench.app` 双击行为与 Gatekeeper 提示；
- `defaults write com.apple.dock` 加 Dock 图标（`--dock`）。

失败也不影响主流程：`.command` 入口与 `qwb_launch.sh open` 均为纯 bash + curl，逻辑与已测部分一致。
