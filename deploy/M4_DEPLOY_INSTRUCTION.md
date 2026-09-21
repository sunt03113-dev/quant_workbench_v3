# 给 M4 WorkBuddy 的部署指令（直接粘贴本文件内容即可）

你是 Mac（Apple Silicon M4）上的 WorkBuddy。用户交给你一个 Quant Workbench 部署包，
请按以下步骤完成部署并回传验收证据。**不要修改 `skill/`、`golden/`（除 vipdoc 外）、
`ui/ui_v2.html` 的任何内容**——它们是冻结基线。

## 包内容（两个包必须配套使用，勿混用旧包）
| 包 | 大小 | sha256（前 16 位） | 内容 |
|---|---|---|---|
| `qwb_m4_deploy_20260921.zip` | 4.8 MB / 294 文件 | `ae210c6cfc396fca` | 代码 + Skill + UI + Golden 结果表 + 部署脚本（不含 `app/config.yaml`，不含任何 `.day`） |
| `qwb_market_pack_20260921.zip` | 889.5 MB / 11705 文件 | `e4ac139e0c6bcf8f` | 标准本地行情 `appdata/market` + `stock_names.csv` |

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
  无需额外自动化。建议部署后 `nohup ./deploy/bootstrap.sh serve &` 或加入登录项。
- M4 上若东财接口正常（不被限流），主源快照会生效，行情阶段通常 <1 分钟。

## 故障排查
见 `deploy/README_DEPLOY.md`（含 akshare 硬依赖、行情目录缺失、P9 ABORT/FAIL 的处置）。

## 版本
- 代码版本：git `main`（含 2026-09-21 三批修复：区间最大振幅不带 % / 每日增量快照快速路径 /
  雪球备源快照 + 水位落后防空洞 + 成交额 f32 口径归一）。
- 行情包 tree_hash 以包内 `appdata/market` 实测为准；两端必须一致（P9 第一道关）。
