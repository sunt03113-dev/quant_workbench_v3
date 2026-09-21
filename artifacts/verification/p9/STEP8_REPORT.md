# STEP 8 报告｜Windows → Apple Silicon M4 跨平台一致性与可移植部署

- run_id: `step8_p9_crossplatform`
- 证据目录: `artifacts/verification/p9/`
- 左端标签: `win`（本机，Windows 11 AMD64）｜右端标签: `mac`（M4，**待执行**）

---

## 0. 结论摘要

| 项 | 结论 |
|---|---|
| **S8-1 跨平台路径层** | **PASS** — 消除硬编码盘符依赖；无 `config.yaml` 时回退平台默认应用数据目录，实测 exit 0 |
| **S8-2 证据采集器** | **PASS** — 左端证据已完整产出（环境/输入资产/26 条规则业务输出/Excel） |
| **S8-3 比对器** | **PASS** — 三用例自校验全通过（正向 PASS、负向 FAIL 且定位、输入门禁 ABORT） |
| **S8-4 部署包** | **已就位** — `bootstrap.sh`（setup/check/serve/p9）+ 依赖清单 + 手册 |
| **S8-5 左端基线** | **PASS** — P0 26 条 7592 行、38.0s，行数与 STEP 7 逐条一致 |
| **S8-6 手册与报告** | **本文件 + `deploy/README_DEPLOY.md`** |
| **P9 最终判定** | **未执行（左端就绪，右端待采）** — 判定逻辑与工具链已就绪并自证可靠 |

**我无法代跑右端**：P9 要求在另一台 Apple Silicon M4 上复跑 P0。本机是 Windows，
因此本步交付的是「**左端基线 + 可移植包 + 一键采集脚本 + 判定器**」，
右端执行由你在 M4 上完成（见 §8，一条命令）。

---

## 1. 本步做了什么（以及为什么这么做）

P9 的判据是「输入资产哈希一致 **且** 业务输出 canonical diff = 0」。
要让这条判据在任何机器上都成立，必须先解决三件事：

1. **路径不能写死**——否则 M4 上根本起不来，谈不上比对；
2. **证据必须可机器比对**——不能靠"看起来一样"；
3. **判据本身要经得起检验**——比对器只在一处正例上返回 PASS 是没有说服力的。

对应产出 S8-1 ~ S8-6。

---

## 2. S8-1 跨平台路径层整改

`CONSTRAINTS.md` 要求「禁止无必要硬编码 C:/D:/、vipdoc 绝对路径；
路径必须来自配置或平台应用数据目录」。整改前 `app/config.yaml` 写死了三个
`D:/09work/...` 绝对路径，M4 上必然要手改。

**新解析优先级**（`app/paths.py`）：

```
环境变量 QWB_APPDATA_DIR / QWB_SKILL_DIR / QWB_UI_FILE / QWB_HOST / QWB_PORT
    ↓ 未提供
app/config.yaml（本机覆盖，仅开发机存在）
    ↓ 未提供
平台默认应用数据目录 / 包内相对路径
    macOS   ~/Library/Application Support/QuantWorkbench
    Windows %LOCALAPPDATA%\QuantWorkbench
    Linux   ${XDG_DATA_HOME:-~/.local/share}/QuantWorkbench
```

每个路径的解析来源记录在 `PATH_SOURCES`，并进入 `paths.describe()` 与 P9 证据。

**实测（三段）**：

| 场景 | appdata 解析结果 | 来源标记 |
|---|---|---|
| 保留 `config.yaml`（开发机） | `D:\...\quant_workbench_package\appdata` | `config:appdata_dir` |
| 设 `QWB_APPDATA_DIR`（env 优先） | 环境变量值 | `env:QWB_APPDATA_DIR` |
| **移除 `config.yaml`（模拟 M4）** | `C:\Users\...\AppData\Local\QuantWorkbench` | `platform-default`，**exit 0** |

第三段是关键：模拟 M4 时**不崩、不静默写错位置**，而是干净回退并如实标注来源。

新增 `deploy/config.example.yaml`（无盘符模板）；`bootstrap.sh check` 在检测到
「随包携带的 `app/config.yaml` 且其路径在本机不存在」时直接报错并给出处置指引。

---

## 3. S8-2 / S8-3 双端证据链工具

### 3.1 采集器 `app/p9_evidence.py`

在**任一端**运行，产出 ACCEPTANCE P9 要求的全部字段：

| 文件 | 对应 ACCEPTANCE 要求 |
|---|---|
| `ENV_<label>.json` | Python/运行时版本、关键依赖版本、标准行情 schema/version、运行方式 |
| `INPUTS_<label>.json` | Skill 目录 / Golden 文件 / 固定测试行情包 / 名称缓存 的 SHA-256 清单根哈希 |
| `INPUT_*.manifest.txt` | 逐文件 `路径⇥字节数⇥SHA-256`（可直接 diff 定位差异文件） |
| `P0_<label>_CANONICAL.json` | 结构化结果的 canonical 形式（列集合 + 量化行集合 + 行哈希） |
| `P0_<label>_VERDICTS.json` | 逐规则判定与命中集差异 |
| `EXCEL_<label>.json` | 结果 Excel 二进制 SHA-256 + 同源结构化结果行哈希 |

清单根哈希算法自描述地在证据里：
`sha256 over sorted('relpath|sha256\n')`。

### 3.2 判定器 `app/p9_compare.py`

四道关，顺序即优先级：

1. **证据自洽性**——`rows_sha256` 必须等于其 `canonical_rows` 的重算哈希，
   `n_rows` 必须等于行数。不自洽 → `EVIDENCE_INCONSISTENT`（证据被手工编辑过时能识别）。
2. **输入一致性**——Skill / Golden / 行情包 / 名称缓存四项指纹必须完全一致。
   不一致 → `ABORT`（两端不是同一套东西，业务 diff 无意义）。
3. **业务输出**——逐规则比较列集合与量化行集合；任一不同 → `FAIL`，
   并给出差异规则与具体差异行（左独有/右独有各多少行）。
4. **Excel**——二进制哈希**不参与** PASS/FAIL，只记录；另比对其同源结构化结果行哈希。

### 3.3 比对器自校验 `app/p9_selfcheck.py`

**三方用例**，全部实测通过（`P9_SELFCHECK.json`）：

| 用例 | 构造 | 期望 | 实际 | 结果 |
|---|---|---|---|---|
| T1 正向 | 证据 vs 自身副本 | PASS | PASS（diff = 0，26 条规则全比） | ✅ |
| T2 负向 | 删掉副本中 `0818A` 的一行并重算哈希 | FAIL + 定位 | FAIL，diff = 1，**定位到 `0818A`，only_left=1 / only_right=0** | ✅ |
| T3 门禁 | 篡改副本的行情包 `tree_hash` | ABORT | ABORT | ✅ |

T2 是重点：它证明比对器**能**报出差异并指出是哪条规则、差在哪几行，
而不是"永远返回 PASS"。

---

## 4. 左端（Windows）证据摘要

**运行环境**：Windows 11 / AMD64 ｜ Python 3.13.14 ｜
numpy 2.5.3、pandas 3.0.6、openpyxl 3.1.5、fastapi 0.141.1、uvicorn 0.53.0、PyYAML 6.0.3

**输入资产指纹**（右端必须逐项一致）：

| 资产 | 文件数 | 字节数 | 清单根哈希（SHA-256） |
|---|---|---|---|
| Skill `tdx-stock-backtest-master` | 53 | 543,797 | `96892acb3b63447bfe24b33934e9bf8e5ce109eabc19beb91911b6809c5996c5` |
| Golden（规则 + 结果表） | 56 | 2,107,499 | `347fcb1ef0a7dc440294724a0bdacb71e5a97f96576c46caa25b59da560af15f` |
| **固定测试行情包** `market_pack` | **11,704** | **930,491,840** | `792ba13f1de359b79c652bb1df939cedc47725dc086b00cd4f51d78354e26e59` |
| 名称缓存 `stock_names.csv` | — | 171,943 | `aa21e8ef9140efeedbcda33180ca492688c2ee5a1b24984558b892350d269b10` |

行情包构成：`sh/lday` 5,900 + `sz/lday` 5,804；物理格式 `tdx-day-compat-32B`，
schema `v1`；上证指数文件最后交易日 `2026-07-16`（见 §7 说明）。

**P0 业务输出**（`P0_win_CANONICAL.json`，38.0s，共 7,592 行）：

```
14 PASS ｜ 8 已知 T+0 取整差异 ｜ 3 CONFLICT（已由《口径裁定》处置）｜ 1 能力缺口(0814)
```

各行数与 STEP 7 逐条一致（0824=1979、0827A=869、0909A=130、0918A=1018、0918B=1488 …），
说明采集链与验收链同源、结果可复现。

**Excel 证据**：`7579e21f…`，5,053 字节，`n_hits=1`，`data_date=2026-09-18`，
同源结构化行哈希 `cff32a8e…`。

---

## 5. 判据有效性实证：Excel 二进制哈希不能用

ACCEPTANCE P9 预见「Excel 文件可能因元数据导致二进制哈希不同」。
我用实测把这件事坐实，而不是仅凭断言（`P9_EXCEL_STABILITY.json`）：

**同一端、同一进程、同一输入，连续导出 4 次**：

| 次数 | Excel SHA-256（前 16 位） | 字节数 | 业务 canonical 行哈希（前 16 位） |
|---|---|---|---|
| 1 | `26c74d71689b3e6d` | 5054 | `cff32a8e14d02fda` |
| 2 | `9b9f965c7c236ccf` | 5054 | `cff32a8e14d02fda` |
| 3 | `4f6e182cf8931735` | **5053** | `cff32a8e14d02fda` |
| 4 | `d0ce3ebf8593932f` | 5054 | `cff32a8e14d02fda` |

**Excel 哈希 4 次全不同（唯一值 4），业务 canonical 哈希 4 次全同（唯一值 1）。**

结论：若以 Excel 二进制 SHA 判跨平台一致性，**同一台机器都会 FAIL**。
故 P9 以 canonical diff 为判据、Excel 二进制哈希仅作记录，是**必要而非可选**的设计
（`p9_compare.py` 的 `excel.gate = INFO`）。

---

## 6. canonical 规则（v2）与两处修正记录

规则自描述于证据 `canon_rule` 字段：

- **数值量化**：统一转 Python `float` 后 `round(4)`，格式化为 `%.4f`；
  去前导 `+`；`-0.0 → 0.0`。
- **标识符/日期列不量化**：`股票代码`、`股票名称` 及任何含「日期」的列**原样保留**，
  并加前导零保护（`000001` 这类不当作数量）。
- **空值**：`None` / `NaN` / `""` / `"N/A"` / `"--"` 统一为 `"N/A"`。
- **行序不敏感**：行按规范化字符串排序后参与哈希。

### 两处被自校验抓出的缺陷（已修，如实记录）

| # | 现象 | 根因 | 修正 |
|---|---|---|---|
| 1 | T1 同源自比对误报 FAIL | 能力缺口规则（0814）无结果行，`rows_sha256` 为 `None`，被 `None == None` 判为不等 | `None/None → no_rows_both` 视为一致，由 `n_rows` 与 `verdict` 佐证 |
| 2 | 股票代码被量化成 `1.0000`（`000001` 丢前导零） | `canon_scalar` 对所有值尝试 `float()` | 增加文本列白名单 + 前导零保护；`canon_version` 升到 2 并重采全部证据 |

第 2 条尤其值得记：它**不改变 PASS/FAIL 结论**（两端同样被量化，仍相等），
但会让证据不可读、并存在不同代码碰撞去重的隐患。**自校验的价值正在于此**
——先证明工具会失败，再信任它的通过。

---

## 7. 数据完整性核查（含一次误报的自我修正）

P9 要求比对"固定测试行情包"，我顺手核了一遍行情包内部一致性。

**过程中我先得出过一个错误结论**：初版统计报「4,066 只股票停在 2026-07-16」。
复核发现该统计把**指数（`sh000xxx`）、基金（`sh5xxxxx`）、深市债/基金（`sz1xxxxx`）、
北交所（`sh88xxxx`）**一并当成了 A 股个股。修正口径后：

| 项 | 真实值 |
|---|---|
| A 股个股文件 | **5,545** |
| 更新到 2026-09-18 | **5,198（93.8%）** |
| 落后个股 | **347**，抽样全为退市/长期停牌股（`神城A退`、`新都退`、`*ST康佳A`） |

**结论：行情数据健康**，落后项属"确实没有新行情"的可解释边界。

顺带确认的设计事实：指数文件（`sh000001` 等）**不参与增量更新**——
`provider.update` 的 `universe_filter` 按名称前缀过滤个股，指数不在其中。
影响面有限：指数文件仅被 `golden_test.trading_dates()` 用作交易日历，
而该日历只服务于 Golden 复现路径（`end_date` 锁定 + `data_end` 截断）；
正常回测路径不经过它。**已登记为已知边界，未改动代码。**

（这条误报与 STEP 7 那次「清单键不匹配导致假阳性」是同类问题——
识别信号一样：**异常数字先查统计口径，再怀疑数据本身**。）

---

## 8. 待你执行：M4 右端（一条命令 + 一次回传）

详见 `deploy/README_DEPLOY.md`。最小流程：

```bash
# M4 上
cd /path/to/quant_workbench_package
export QWB_APPDATA_DIR="$PWD/appdata"
export QWB_SKILL_DIR="$PWD/skill/tdx-stock-backtest-master"
export QWB_UI_FILE="$PWD/ui/ui_v2.html"

./deploy/bootstrap.sh setup          # 建 venv + 装依赖 + 自检
./deploy/bootstrap.sh serve &        # 启动后端（Excel 证据需要）
./deploy/bootstrap.sh p9 collect --label mac
```

把 M4 的 `artifacts/verification/p9/mac/` 整个目录回传到本机同名位置，
然后在 Windows 端：

```bash
python app/p9_compare.py --left win --right mac
```

**判定三种可能**：
- `PASS` —— 输入哈希一致且 canonical diff = 0（跨平台通过）；
- `FAIL` —— 给出差异规则与差异行；先看 `runtime.packages` 是否版本不一致；
- `ABORT` —— 输入资产不一致，先用 `INPUT_win_market_pack.manifest.txt` 逐行 diff 定位。

**必须先满足的前置**：M4 上的四项输入指纹（§4 表格）与左端**逐位一致**。

---

## 9. 传递与依赖注意项

1. **行情包 930 MB / 11,704 文件**，跨机器传输的瓶颈在这里。
   另有一条「最小充分集」路径：仅传 P0 命中涉及的 3,496 个代码（约 30% 体积），
   但**两端必须改用同一个包定义**（即左端也要用最小包重采），否则 `tree_hash` 必然不一致而 ABORT。
   **当前判定基准用的是完整包。**
2. **`app/config.yaml` 不得随包分发**（含开发机盘符路径）。M4 上用环境变量。
3. **`akshare` 是硬依赖**：`StockBacktest_TdxAutoRun0630.py` 顶层 `import akshare`，
   而该模块是 `executor` 的顶层依赖——缺了它整个产品起不来。
   它是纯 Python 包，arm64 有 wheel；若 M4 安装失败，**不得修改 Skill 源码绕过**。
4. 依赖版本已 pin 在 `deploy/requirements.txt`（对齐左端）。
   完整冻结见 `deploy/requirements.lock.win.txt`（45 项）。
   若 M4 上 numpy/pandas 版本被迫不同，且业务 diff ≠ 0，**先对齐版本再判定**。

---

## 10. 证据清单与复现命令

```
artifacts/verification/p9/
├── win/                                  # 左端证据（本文档 §4 全部数字来源）
│   ├── ENV_win.json                      # 环境 + 路径解析来源 + canonical 规则
│   ├── INPUTS_win.json                   # 四项输入资产指纹
│   ├── INPUT_win_{skill,golden,market_pack}.manifest.txt
│   ├── P0_win_CANONICAL.json             # 26 条规则 canonical 业务输出
│   ├── P0_win_VERDICTS.json              # 逐规则判定与命中集差异
│   └── EXCEL_win.json / EXCEL_win_p9_excel_probe.xlsx
├── P9_SELFCHECK.json                     # 比对器三用例自校验（T1/T2/T3）
├── P9_EXCEL_STABILITY.json               # Excel 哈希不稳定性实证
├── collect_win.log / selfcheck.log       # 采集与自校验日志
└── restart_record.txt / server_runtime.log   # 后端重启记录
```

复现：

```bash
# 左端重采 + 自校验（约 60s）
python app/p9_evidence.py collect --label win
python app/p9_selfcheck.py --label win
# Excel 判据实证（需后端在跑）
python app/p9_excel_stability.py --runs 4
# 双端判定（右端就绪后）
python app/p9_compare.py --left win --right mac
```

---

## 11. 未决 / 风险

| 项 | 状态 |
|---|---|
| P9 最终判定 | **待右端**（左端与工具链已就绪并自证可靠） |
| P0 的 3 项 CONFLICT | 已按《口径裁定》登记为「已裁定差异」，未改 Golden/Skill/比较器 |
| 指数文件不参与增量更新 | 已知边界，影响面限于 Golden 复现路径的交易日历；未改代码 |
| 347 只落后个股 | 退市/长期停牌，可解释 |
| `skill/dev/` 探针脚本与 `rule.txt` 补列 | 仍待你定优先级（STEP 7 已提出） |
| M4 上 akshare arm64 安装 | 未实测（本机无该环境），已写入故障排查 |

> 本报告所有行情数据依据通达信本地日线（标准本地行情，TDX `.day` 兼容格式），
> 仅用于回测口径与跨平台一致性核对，不构成投资建议。
