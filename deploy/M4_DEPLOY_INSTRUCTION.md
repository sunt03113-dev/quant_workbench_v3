# 给 M4 WorkBuddy 的部署指令（直接粘贴本文件内容即可）

你是 Mac（Apple Silicon M4）上的 WorkBuddy。用户交给你一个 Quant Workbench 部署包，
请按以下步骤完成部署并回传验收证据。**不要修改 `skill/`、`golden/`（除 vipdoc 外）、
`ui/ui_v2.html` 的任何内容**——它们是冻结基线。

## 包内容（两个包必须配套使用，勿混用旧包）
| 包 | 大小 | sha256 | 内容 |
|---|---|---|---|
| `qwb_m4_deploy_20260921.zip` | 5.0 MB / 299 文件 | 见 `dist/SHA256SUMS_20260921.txt` | 代码 + Skill + UI + Golden 结果表 + 部署脚本 + **mac 双击启动器**（不含 `app/config.yaml`，不含任何 `.day`） |
| `qwb_market_pack_20260921.zip` | 889.5 MB / 11705 文件 | `e4ac139e0c6bcf8f…`（全量见 SHA256SUMS） | 标准本地行情 `appdata/market` + `stock_names.csv` |

> 代码包已在本轮追加 `deploy/mac/`（macOS 双击启动器），**请用新一版代码包**；
> 行情包未变，可继续用上一版。以 `sha256` 全量校验为准。

**行情数据截止 2026-09-21**（5197 只个股当日有成交；其余为退市/停牌标的）。
两端行情必须**完全一致**，否则 P9 第一道关（输入资产哈希）会直接 ABORT —— 因此请使用本页
列出的这一版行情包，不要用更早的副本。

## 部署步骤
```bash
# 1. 解压两个包到同一目录（保持相对结构）
mkdir -p ~/quant_workbench_package && cd ~/quant_workbench_package
unzip -q ~/Downloads/qwb_m4_deploy_20260921.zip -d .
unzip -q ~/Downloads/qwb_market_pack_20260921.zip -d .   # 解出 appdata/market 与 stock_names.csv

# 2. 环境变量指路（不要创建 app/config.yaml；开发机配置不得随包传递）
export QWB_APPDATA_DIR="$PWD/appdata"
export QWB_SKILL_DIR="$PWD/skill/tdx-stock-backtest-master"
export QWB_UI_FILE="$PWD/ui/ui_v2.html"

# 3. 建 venv + 装依赖 + 自检
chmod +x deploy/bootstrap.sh
./deploy/bootstrap.sh setup

# 4. 启动后端（前台即可；Ctrl+C 停止）
./deploy/bootstrap.sh serve
#   浏览器打开 http://127.0.0.1:8000

# 5. 装「双击即用」入口（见下方第 5 节；让用户以后不碰终端）
bash deploy/mac/install_mac_launcher.sh --login
```

## 部署后验收（依次执行，全部留证）
1. `./deploy/bootstrap.sh check` —— 记录 Python 版本、依赖自检、`paths.describe()` 输出。
2. UI 打开 http://127.0.0.1:8000 ，用规则 `0921A`（`golden/rule.txt` 中同名段落）跑一次回测，
   确认：能出结果、确定性复核通过（无 ROW_INVALID）、结果表「区间最大振幅」列为
   **纯数字（不带 %）**、「区间涨幅/区间振幅」列**带 %**。
3. P9 右端采集（需后端在另一终端保持运行）：
```bash
export QWB_APPDATA_DIR="$PWD/appdata"; export QWB_SKILL_DIR="$PWD/skill/tdx-stock-backtest-master"
export QWB_UI_FILE="$PWD/ui/ui_v2.html"
./deploy/bootstrap.sh p9 collect --label mac
```
   产出在 `artifacts/verification/p9/mac/`，**整个目录回传给 Windows 端**。

## 每日增量更新（本次新增能力，M4 上同样生效）
- UI 首页「一键更新」= 增量行情 → 重跑全部模型 → 刷新状态。
- 单日增量走**批量快照快速路径**：东财 `push2 clist`（主源，约 56 请求）→ 东财不可用时
  自动切雪球 `batch/quote`（备源，约 56 批 / 100 只一批，约 20s）→ 都不可用才回退逐只
  kline（约 5544 请求，最慢）。任一环节失败自动降级，**不会破坏既有历史**（追加带回滚日志）。
- 只有当日收盘定型后（`SNAPSHOT_EARLIEST = 15:05`）才允许走快照路径；多日缺口/盘中走逐只路径。
- **后端内置调度：工作日 15:45**（另有启动补偿：过 15:45 且模型结果落后于行情时补跑一次）。
  无需额外自动化。**用第 5 节的启动器 `--login` 装成登录自启即可**（不要再用裸 `nohup`）。
- M4 上若东财接口正常（不被限流），主源快照会生效，行情阶段通常 <1 分钟。

## 5. 让最终用户「双击即用」（本步骤必做，别让用户碰终端）

Mac 上没有 `.bat`。工作台是「本机后端 + 浏览器界面」，所以**必须有人把后端起起来**——
本轮的解法是给用户装一个双击入口，用户全程不接触命令行：

```bash
cd ~/quant_workbench_package
bash deploy/mac/install_mac_launcher.sh            # 生成 ~/Applications/QuantWorkbench.app + 桌面快捷方式
bash deploy/mac/install_mac_launcher.sh --login    # 额外：登录自启（开机后台就绪，用户连双击都不用）
```

产出与行为：

| 产物 | 作用 |
|---|---|
| `~/Applications/QuantWorkbench.app` | 双击 → 后台起后端 → 自动打开 `http://127.0.0.1:8000`；**不弹终端窗口**；后端已在跑则只开浏览器 |
| `~/Desktop/量化工作台.app` | 上述 .app 的桌面快捷方式 |
| `~/Library/LaunchAgents/com.qwb.workbench.server.plist` | `--login` 时生成：登录即起后端，由 launchd 守护 |

细节与排障见 `deploy/mac/README_MAC_LAUNCHER.md`（已随包）。
请把该文件**要点转述给最终用户**：日常只有两件事——开机（自启）或双击图标；要补当日数据就在首页点「一键更新」。

命令行兜底（无图形界面时）：
```bash
bash deploy/mac/qwb_launch.sh open | status | stop
```

## 故障排查
见 `deploy/README_DEPLOY.md`（含 akshare 硬依赖、行情目录缺失、P9 ABORT/FAIL 的处置）。

## 版本
- 代码版本：git `main`（含 2026-09-21 四批改动：区间最大振幅不带 % / 每日增量快照快速路径 /
  雪球备源快照 + 水位落后防空洞 + 成交额 f32 口径归一 / **macOS 双击启动器 `deploy/mac/`**）。
- 行情包 tree_hash 以包内 `appdata/market` 实测为准；两端必须一致（P9 第一道关）。
