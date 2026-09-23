# 给 M4 WorkBuddy 的部署指令（直接粘贴本文件内容即可）

你是 Mac（Apple Silicon M4）上的 WorkBuddy。用户交给你一个 Quant Workbench 部署包，
请按以下步骤完成部署并回传验收证据。**不要修改 `skill/`、`golden/`（除 vipdoc 外）、
`ui/ui_v2.html` 的任何内容**——它们是冻结基线。

## 包内容（三个包必须配套使用，勿混用旧包）
| 包 | 大小 | sha256 | 内容 |
|---|---|---|---|
| `qwb_m4_deploy_20260923.zip` | 见 SHA256SUMS | 见 `dist/SHA256SUMS_20260923.txt` | 代码 + Skill + UI + Golden 结果表 + 部署脚本 + mac 双击启动器（不含 `app/config.yaml`，不含任何 `.day`） |
| `qwb_market_pack_20260923.zip` | 932.9 MB / 11705 文件 | `c7f8d78d9cca9c93c671a99c0ac2d2a5c6ad9ca027822da384dcba9fd804afd8` | 标准本地行情 `appdata/market`（11704 个 `.day`，截止 **2026-09-22**）+ `stock_names.csv` |
| `qwb_state_pack_20260923.zip` | 3.5 MB / 81 文件 | `2dc359075c61dae0dc58d1779cc62f722e6be463bdf657d1b41a382d7167825d` | **工作台状态 `appdata/state`**：21 个模型定义 `state.json` + 80 个结果表文件（各模型 `current/previous` 的 `.json`/`.xlsx`） |

> **`state` 包是「打开就有内容」的关键**：不带它，界面首页是空工作台（只有 golden 期望表，
> 需自己逐条跑规则）。它只含相对路径、零绝对路径（已扫描确认），可直接跨机使用。
> 前端**卡片分组/排序/改名**存在浏览器 `localStorage`（键 `qw_state_v3`），不随包交付；
> 若要与开发机完全一致，需在 M4 浏览器控制台注入（见文末「可选的界面布局迁移」）。

> **2026-09-23 版（当前唯一有效版本）**：三个包均已对齐 09-22 行情与 10cm 新口径。
> 旧 `*_20260921.zip` 两包**作废**——代码包内 10cm 池/golden 口径过时，行情包止于 09-21。
> 以 `sha256` 全量校验为准。

**行情数据截止 2026-09-22**。两端行情必须**完全一致**，否则 P9 第一道关（输入资产哈希）
会直接 ABORT —— 因此请使用本页列出的这一版行情包，不要用更早的副本。

## 部署步骤
```bash
# 1. 解压三个包到同一目录（保持相对结构）
mkdir -p ~/quant_workbench_package && cd ~/quant_workbench_package
unzip -q ~/Downloads/qwb_m4_deploy_20260923.zip -d .
unzip -q ~/Downloads/qwb_market_pack_20260923.zip -d .   # 解出 appdata/market 与 stock_names.csv
unzip -q ~/Downloads/qwb_state_pack_20260923.zip -d .    # 解出 appdata/state（模型定义 + 结果表）

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

# 5. 【先做验收，后装自启】P9 右端采集（见下方「部署后验收」第 3 步）
#    务必在本步完成后再装自启 —— 自启后工作日 15:45 会自动增量更新行情，
#    行情一旦领先开发机，P9 输入哈希即不一致（ABORT），必须重打行情包才能重验。

# 6. 装「双击即用」入口（见下方第 5 节；让用户以后不碰终端）
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

## 可选的界面布局迁移（分组/排序/卡片名）
首页的**分组、排序、卡片重命名、卡片↔模型绑定**存在浏览器 `localStorage['qw_state_v3']`，
属浏览器本地数据，不随包交付。M4 首次打开会走内置种子布局（种子只预设了少数卡片，
后端已有的 21 个模型不会自动全部成卡 —— 可在界面里手动新建卡片并绑定模型）。

若要与开发机布局完全一致：在**开发机浏览器**控制台执行
`copy(localStorage.getItem('qw_state_v3'))` 复制到剪贴板，把内容存成文本随 M4 一起传；
在 **M4 浏览器**控制台执行 `localStorage.setItem('qw_state_v3', '<粘贴内容>')` 后刷新页面。
（这一步纯 UI 层，不影响任何业务口径与 P9 判定。）

## 日常使用与数据来源
- 三包解压后，**历史行情完全离线自足**（11704 个 `.day`，含沪深主板/创业板/科创板/北交所，
  截止 2026-09-22）：回测、复核、golden 对账都不需要网络。
- **每天新增的那一根日线需要联网**：工作日 15:45 自动增量（或首页「一键更新」），
  数据源优先级 东方财富 → 雪球 → 逐只 K 线。若 M4 网络无法访问这两个行情接口，
  当日数据进不来，需从开发机同步 `appdata/market/vipdoc` 的增量文件（会导致两端行情哈希
  漂移，之后重跑 P9 须同步重打行情包）。

## 故障排查
见 `deploy/README_DEPLOY.md`（含 akshare 硬依赖、行情目录缺失、P9 ABORT/FAIL 的处置）。

## 版本
- 代码版本：git `main`（含 2026-09-21 四批改动：区间最大振幅不带 % / 每日增量快照快速路径 /
  雪球备源快照 + 水位落后防空洞 + 成交额 f32 口径归一 / **macOS 双击启动器 `deploy/mac/`**）。
- **2026-09-22 间隔口径切换（重要）**：间隔 `N1/N2` 统一定义为
  「两段涨停之间、**不含两端涨停 K 线**的交易日间隔天数」，相邻涨停 `N = 0`；
  跨间隔 `N = 各相邻间隔之和 + 中间锚点个数`。工作台执行器已改为与 Skill 一致
  （原先按「相差 N 个交易日」= 不含两端根数 + 1，与 Skill 差 1）。
  - 定义已写入 `skill/tdx-stock-backtest-master/tdx-stock-backtest.md` 第九节与 `README.md` 数据规约。
  - 影响：带间隔的规则命中数会变小（实测 `N1∈[3,8]/N2∈[1,5]` 由 1356 → 388，
    与 Skill 侧 388 行逐字一致；`N1∈[1,3]/N2∈[1,4]` 由 3842 → 254）。
  - M4 侧部署后如库内已有带间隔模型的旧结果，请重跑一次（`/api/daily/run` 或逐模型重跑），
    否则界面会一直显示旧口径结果（每日管线只在数据日期变化时才自动重跑）。
- **2026-09-23 10cm 口径裁定（重要，kk 定稿）**：10cm 池纳入**创业板 300/301 的 10% 时代**
  （信号日 < 2020-08-24，含反向门）；688 不进 10cm；`both` = 各板块全时代并集（无门槛）。
  skill 与 app 双实现同步改，golden 0824/0827A/0909A 三例已按新口径重造（gold_test 全 PASS），
  12 个 10cm 模型已重跑（行数全部增加，复核 0 违例）。
  证据与明细：包内 `artifacts/verification/gem10_ruling/CHANGES.md`。
- 三包对齐：代码包（10cm 新口径 + mac 启动器）/ 行情包（`.day` 截止 09-22）/ **state 包（21 个模型 + 结果表）**。
- 行情包 tree_hash 以包内 `appdata/market` 实测为准；两端必须一致（P9 第一道关）。
