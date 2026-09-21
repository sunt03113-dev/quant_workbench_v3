# Quant Workbench 部署与跨平台（M4）操作手册

本文档面向 **Apple Silicon M4（macOS）** 部署与 **P9 跨平台一致性** 采集。
Windows 开发端同构，仅路径与启动方式不同。

---

## 1. 目录约定

```
quant_workbench_package/
├── app/                    # 后端与工具（唯一应用代码）
│   ├── paths.py            # 路径层：env > app/config.yaml > 平台默认
│   ├── server.py           # FastAPI 后端，托管冻结 UI
│   ├── executor.py         # 调 Skill 业务原子（零公式）
│   ├── recognizer.py       # 自然语言规则 -> plan schema
│   ├── store.py            # 模型卡片/结果持久化与轮换
│   ├── provider.py         # 双源增量 Provider（东财/雪球）
│   ├── p9_evidence.py      # P9 证据采集（任一端运行）
│   └── p9_compare.py       # P9 双端判定
├── skill/tdx-stock-backtest-master/   # 冻结业务定义（不得修改）
├── ui/ui_v2.html           # 冻结 UI
├── golden/                 # 固定规则 + 期望结果（56 文件，~2 MB，随包）
├── deploy/                 # 部署脚本与依赖清单（本目录）
└── appdata/                # 产品数据（行情/状态/结果，与程序分离）
    ├── market/vipdoc/{sh,sz}/lday/*.day   # 标准本地行情（P9 固定测试行情包）
    └── stock_names.csv                    # 名称缓存（输出「股票名称」列）
```

**不得随包分发 `app/config.yaml`**：它含开发机绝对路径。M4 上用环境变量或
复制 `deploy/config.example.yaml` 生成本机配置。

---

## 2. 首次部署（macOS / M4）

```bash
# 2.1 取到包（代码 + skill + ui + golden + appdata 行情包）
cd /path/to/quant_workbench_package

# 2.2 指定数据与 Skill 位置（若无 app/config.yaml 则走平台默认目录）
export QWB_APPDATA_DIR="$PWD/appdata"
export QWB_SKILL_DIR="$PWD/skill/tdx-stock-backtest-master"
export QWB_UI_FILE="$PWD/ui/ui_v2.html"

# 2.3 建 venv 装依赖 + 自检
./deploy/bootstrap.sh setup

# 2.4 启动后端（前台）
./deploy/bootstrap.sh serve
#   浏览器打开 http://127.0.0.1:8000
```

`bootstrap.sh check` 会打印：Python 版本、依赖自检结果、`paths.describe()`
（含**每个路径的解析来源**）、行情目录是否存在。

---

## 3. P9 跨平台一致性采集

**判据**（ACCEPTANCE.md P9）：输入资产哈希一致 **且** 业务输出 canonical diff = 0。
Excel 二进制哈希不参与判定（容器元数据易变），仅记录。

### 3.1 M4 端采集

```bash
cd /path/to/quant_workbench_package
export QWB_APPDATA_DIR="$PWD/appdata"
export QWB_SKILL_DIR="$PWD/skill/tdx-stock-backtest-master"
export QWB_UI_FILE="$PWD/ui/ui_v2.html"

# 先启动后端（Excel 证据需要 /api/plan/backtest 与导出接口）
./deploy/bootstrap.sh serve &      # 或用另一个终端

# 采集（含行情包哈希 + P0 全量 + Excel）
./deploy/bootstrap.sh p9 collect --label mac
```

产出在 `artifacts/verification/p9/mac/`：

| 文件 | 内容 |
|---|---|
| `ENV_mac.json` | OS/架构/Python/依赖版本、路径解析来源、canonical 规则 |
| `INPUTS_mac.json` | Skill / Golden / 行情包 / 名称缓存 的清单根哈希 |
| `INPUT_*_*.manifest.txt` | 逐文件 `路径<TAB>字节数<TAB>SHA-256`（可 diff） |
| `P0_mac_CANONICAL.json` | 26 条规则的列集合 + 量化后行集合 + 行集合哈希 |
| `P0_mac_VERDICTS.json` | 逐规则判定（PASS / 已知差异 / 冲突 / 能力缺口） |
| `EXCEL_mac.json` | 结果 Excel 二进制 SHA-256 + 同源结构化结果行哈希 |

M4 若暂时无法访问行情源、只想快速自检，可加 `--skip-market --skip-excel`。

### 3.2 回传与判定

把 `artifacts/verification/p9/mac/` 整个目录回传到 Windows 端同名位置
（`artifacts/verification/p9/mac/`，目录名即 label），然后在 Windows 端运行：

```bash
python app/p9_compare.py --left win --right mac
```

输出 `artifacts/verification/p9/P9_COMPARE_win_mac.json`，顶层 `verdict` 为
`PASS` / `FAIL` / `ABORT`：

- `ABORT` —— 输入资产哈希不一致（两端不是同一套 Skill/Golden/行情包），业务 diff 无意义；
- `FAIL` —— 业务 canonical diff ≠ 0，会给出差异规则与具体差异行；
- `PASS` —— 输入一致且 canonical diff = 0。

### 3.3 工具自校验（比对器本身的可靠性）

比对器**不得**只在一处正例上验证。标准做法（Windows 端已执行，见 STEP8 报告）：

```bash
# 正向：同一份证据 vs 自身副本 -> 期望 PASS
cp -r artifacts/verification/p9/win artifacts/verification/p9/win_selfcheck
python app/p9_compare.py --left win --right win_selfcheck

# 负向：篡改副本中一行 -> 期望 FAIL 且定位到具体规则
#   （脚本见 app/p9_selfcheck.py，会同时给出正/负两个结论）
```

---

## 4. 故障排查

| 现象 | 处置 |
|---|---|
| `ImportError: No module named 'akshare'` | akshare 是 Skill `StockBacktest_TdxAutoRun0630.py` 的**顶层**依赖，必须安装（`deploy/requirements.txt` 已含）。**不得**修改 Skill 源码绕过。 |
| `ModuleNotFoundError: yaml / tqdm / pandas` | 未用 venv 解释器。统一用 `./deploy/bootstrap.sh serve` 启动。 |
| 行情目录不存在 | `QWB_APPDATA_DIR` 指向错误，或行情包未落位。检查 `<appdata>/market/vipdoc/{sh,sz}/lday/*.day`。 |
| P9 `ABORT`：market_pack tree_hash 不一致 | 两端行情包不是同一份。用左端 `INPUT_win_market_pack.manifest.txt` 逐行 diff 定位缺/多/改的文件。 |
| P9 `FAIL`：个别规则 rows 不同 | 先看 `runtime.packages` 是否 `packages_all_identical=false`。数值库版本不同（numpy/pandas）可能改变舍入或排序；对齐版本后重采再判定。 |
| Excel 阶段 `skipped` | 后端未启动或端口不通。P0 与输入部分仍有效；Excel 仅记录项，不影响 PASS/FAIL。 |

---

## 5. 数据授权提示

历史行情作为独立部署资产提供，是否可再分发须在最终确定数据来源后核对
相应授权/许可（见 `DATA.md`）。部署包应记录数据版本、截止交易日、记录数与文件哈希
——P9 的 `INPUTS_*.json` 已包含这些字段（`index_last_trade_date`、`n_files`、
`total_bytes`、`tree_hash`）。

---

## 6. 最终用户体验边界

产品日常使用**不应**需要：安装 Windows 通达信、手工维护 vipdoc、改源码、
配 Python 开发环境、每天复制行情、手工启动多个终端服务。
`bootstrap.sh setup/serve` 与后端内置的轻量调度（`/api/daily/run`）即为此设计。

---

## 7. 最终用户的「双击即用」入口（macOS）

后端必须有人启动，所以给最终用户提供**双击入口**，用户不接触命令行：

```bash
bash deploy/mac/install_mac_launcher.sh            # ~/Applications/QuantWorkbench.app + 桌面快捷方式
bash deploy/mac/install_mac_launcher.sh --login    # 另加 LaunchAgent 登录自启
bash deploy/mac/install_mac_launcher.sh --dock     # 另加 Dock 图标
```

- `.app` 双击 → 后台起后端（无终端窗口）→ 自动打开 `http://127.0.0.1:8000`；
  后端已在跑则只开浏览器（不会起第二个进程）。首次双击若缺 venv，会自弹提示并自动
  `bootstrap.sh setup`。
- `--login` 生成 `~/Library/LaunchAgents/com.qwb.workbench.server.plist`，登录即起、由 launchd 守护；
  配合后端内置的 15:45 调度，用户第二天看到的已经是齐的数据。
- 手工兜底：`bash deploy/mac/qwb_launch.sh open | status | stop`。
- 详细说明与排障：`deploy/mac/README_MAC_LAUNCHER.md`。
