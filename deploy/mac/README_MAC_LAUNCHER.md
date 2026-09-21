# macOS 使用体验（给 M4 用户）：双击打开即用

> 目标：M4 用户**不需要**记命令、不需要开终端、不需要懂 Python。
> 部署完成后，留给用户的东西只有一件事：**双击**。

---

## 1. 先明确一件事：只开浏览器是不够的

工作台是「本机后端 + 浏览器前端」结构：

- 后端 `app/server.py`（FastAPI，`http://127.0.0.1:8000`）负责行情增量、跑模型、出结果表；
- 浏览器只是它的界面。

所以**必须有人把后端启起来**。三种做法，任选其一（推荐 A）：

| 方案 | 用户每天的动作 | 终端窗口 | 适合 |
|---|---|---|---|
| **A. 登录自启**（LaunchAgent） | **什么都不用做**，直接点浏览器书签 | 无 | 这台机器天天用 |
| **B. 双击 .app** | 双击桌面「量化工作台」图标 | 无 | 不想让它一直后台跑 |
| **C. 双击 .command** | 双击 `start_workbench_mac.command` | 有一个（可关） | 应急/排查用 |

macOS 上**没有 `.bat`**（那是 Windows 的）。对应的双击入口是 `.command` 或 `.app`；本包里给的是更干净的 `.app`。

---

## 2. 安装（在 M4 上执行一次）

```bash
cd ~/quant_workbench_package          # 部署解压后的根目录

# 2.1 依赖与环境（首次）
export QWB_APPDATA_DIR="$PWD/appdata"
export QWB_SKILL_DIR="$PWD/skill/tdx-stock-backtest-master"
export QWB_UI_FILE="$PWD/ui/ui_v2.html"
./deploy/bootstrap.sh setup

# 2.2 装「双击即用」入口（默认：.app + 桌面快捷方式）
bash deploy/mac/install_mac_launcher.sh

# 2.3（推荐）再加一项：登录自启，开机后台就绪
bash deploy/mac/install_mac_launcher.sh --login

# 2.4（可选）加到 Dock
bash deploy/mac/install_mac_launcher.sh --dock
```

安装脚本会产出：

```
~/Applications/QuantWorkbench.app     # 真正的双击入口（无终端窗口）
~/Desktop/量化工作台.app               # 指向上面的桌面快捷方式
~/Library/LaunchAgents/com.qwb.workbench.server.plist   # --login 时生成
```

首次双击 `.app` 时如果没有 venv，它会自己跑一次 `bootstrap.sh setup`（弹窗提示，约 2–5 分钟），完成后自动打开浏览器——**用户全程只需要双击一次**。

---

## 3. 日常怎么用

- **装了 `--login`**：开机什么都不用做。浏览器打开 `http://127.0.0.1:8000`（建议存书签）。要补充当日增量就在首页点「一键更新」。
- **只想用 .app**：双击桌面「量化工作台」→ 后端起来 + 浏览器自动打开。
- 两个都装了也不会冲突：`.app` 发现后端已在跑就只开浏览器，不会起第二个进程。

常用排查命令（用户也可以直接双击 `.app` 看有没有反应）：

```bash
bash deploy/mac/qwb_launch.sh status   # 看状态 / 端口 / PID
bash deploy/mac/qwb_launch.sh stop     # 停后端（--login 模式下 launchd 会拉起，需先卸载自启）
bash deploy/mac/install_mac_launcher.sh --uninstall   # 全部卸载
```

---

## 4. 与后端内置调度的关系

后端自带「工作日 15:45 增量更新 + 启动补偿」（`server.py` 内调度，无需外部自动化）。
因此只要后端在跑（方案 A 就是全天在跑），当天收盘数据会在 15:45 自动补齐并重跑模型；
用户第二天开机看到的已经是齐的数据。**不需要再配任何 WorkBuddy 定时任务。**

方案 B（双击 .app）也一样：双击时后端启动，启动补偿会检查"模型结果是否落后于行情"，
落后就补跑一次，因此隔夜后第一次双击也会自愈。

---

## 5. 已知边界

| 现象 | 原因 / 处置 |
|---|---|
| 双击 .app 没反应 | 看 `appdata/logs/server.log`；常见是 8000 端口被占（先 `qwb_launch.sh stop`）。启动失败会弹窗提示。 |
| 提示"无法验证开发者" | 首次需右键 → 打开 → 仍要打开（安装脚本已尽量 `xattr -dr com.apple.quarantine`）。 |
| 换了目录又双击 | `.app` 里记的是安装时的绝对路径；换目录后重跑一次 `install_mac_launcher.sh`。 |
| 15:45 没自动更新 | 后端不在运行。检查 `launchctl print gui/$(id -u)/com.qwb.workbench.server`。 |
| 电脑休眠/关机 | 服务随之停止，属正常。开机自动恢复（方案 A）。今日数据不会丢：增量是幂等的，会自愈补上。 |
