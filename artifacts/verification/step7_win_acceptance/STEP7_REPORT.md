# STEP 7 验收报告 —— Windows 完整验收（ACCEPTANCE.md P0–P8）

- run_id：`step7_win_acceptance`
- 执行时间：2026-09-20（周日）16:34–17:40 GMT+8
- 环境：Windows / Python `qwb` venv / FastAPI `127.0.0.1:8000` / MS Edge（Playwright playwright-core，真实浏览器驱动冻结 UI）
- 证据根目录：`artifacts/verification/step7_win_acceptance/`
- 输入资产哈希：`INPUT_MANIFEST.json`（24439 个文件：UI + Skill + Golden 规则/Excel + 固定测试行情 24329 个 .day + 运行时环境）
- 证据哈希：`EVIDENCE_MANIFEST.json`（64 个文件）

## 0. 结论总览

| 项 | 内容 | 判定 |
|---|---|---|
| P0 | Golden 全量一致性（26 条规则，真实链重跑） | **PARTIAL / FAIL-CLOSED**：14 PASS、8 已知 T+0 取整冲突、3 真实 CONFLICT、1 能力缺口 —— 已按协议停止并上报（见 §2） |
| P1 | 真实 UI 入口 E2E | **PASS** |
| P2 | 结构化结果 + 可打开 Excel | **PASS** |
| P3 | 持久化（后端重启 + 浏览器环境重启） | **PASS**（修复 1 处 UI 缺陷后，见 §5） |
| P4 | current/previous 轮换 + 失败保护 | **PASS**（11/11） |
| P5 | Provider 实测（双源 + 字段/单位/复权/范围验证） | **PASS（降级）**：雪球源实时实测通过并与 TDX 逐字段一致；东财主源在验收时段被限流（前端到端降级验证通过，见 §6） |
| P6 | 增量数据（补新交易日 + 失败回滚） | **PASS**（12 PASS / 1 SKIP） |
| P7 | 主动 + 自动更新（周末不造伪数据） | **PASS**（13/13） |
| P8 | 新增股票 new_hit + 卡片高亮 + 名称 | **PASS** |
| P9 | Windows → M4 一致性 | 未执行（Windows 侧 P0 未全绿前不进入，见 §9） |

**本次验收额外发现并修复 2 处缺陷**（§5）：UI 不持久化卡片→策略关联（阻断 P3）；名称缓存覆盖不足（影响结果可读性与 P8 名称）。两处均有 before/after 哈希与回归证据。

---

## 1. 输入资产与运行时（可复核基线）

| 资产 | SHA-256（前 16） | 说明 |
|---|---|---|
| `ui/ui_v2.html`（修复后） | `4f0fe3ef16378163` | 冻结 UI 基准 + 最小持久化修复 |
| `ui/ui_v2.baseline.html`（原始） | `6f4dc5fa6b99ccf6` | 修复前原文备份，可一键回滚 |
| `golden/rule.txt` | 见 INPUT_MANIFEST | 26 条冻结规则文本 |
| `golden/*_backtest/*.csv|xlsx` | 见 INPUT_MANIFEST | Golden 结果（未修改） |
| `golden/vipdoc/**/*.day` | 见 INPUT_MANIFEST | 固定测试行情 24329 个文件（未修改） |
| `skill/tdx-stock-backtest-master/**` | 见 INPUT_MANIFEST | Skill 全量文件（零修改，仅经其自带 `config.yaml` 注入路径） |
| `appdata/stock_names.csv` | 见 EVIDENCE_MANIFEST | 名称缓存（本次由 3446 → 8011 代码） |

运行时：Python 3.13.12（venv `qwb`）、fastapi/uvicorn/pandas/numpy/openpyxl/pyyaml 版本见 `INPUT_MANIFEST.json` 的 `packages` 字段；OS 版本见 `os` 字段（P9 跨平台比对用）。

---

## 2. P0 Golden 一致性 —— FAIL-CLOSED，等待裁决

复现：`app/step7_acceptance.py p0` → `p0_golden_results.json`、`p0_run.log`
链路：识别器 → 执行计划 → Skill 业务原子（原样 import）→ 标准本地行情 → 回测 → 比较器（未放宽）。

| 判定 | 条数 | 规则 |
|---|---|---|
| PASS | 14 | 0911、0912、0913A、0913B、0915A、0915B、0915C、0917A–E、0918A、0918B |
| PASS（含已知 T+0 取整冲突） | 8 | 0818A、0818B、0822、0827B、0908、0908B、0908C、0910A |
| **CONFLICT（真实冲突，未消除）** | 3 | 0824、0827A、0909A |
| **CAPABILITY_GAP** | 1 | 0814（前向窗口 `D+1日：涨停`，schema v1 不支持，识别器 fail-closed 提示） |

CONFLICT 明细（本次实测数值）：

| 规则 | Golden 命中 | 本实现 | 差异特征 |
|---|---|---|---|
| 0824 | 1980 | 1979 | 缺 4 / 多 3 —— 命中集边界差异 |
| 0827A | 870 | 869 | 缺 1；且 `T+2最高价` 1 行值不同 |
| 0909A | 10 | 130 | 缺 0 / 多 120 —— **Golden ⊂ 本实现**（与 C3「Golden 只扫沪市」一致） |

按协议：**未修改 Golden、未修改 Skill、未放宽比较器**；冲突细节与根因待裁决（沿用 STEP 3 `CONFLICT_REPORT.md` 的 C1–C5）。因此 P0 不能宣布全绿；M4（P9）应在 C1–C5 裁决后再执行，否则需在双端同时复现同一组已知冲突。

---

## 3. P1 真实 UI 入口 E2E —— PASS

真实浏览器（MS Edge）打开 `http://127.0.0.1:8000`，全部交互均为真实点击/输入，API 调用链完整留证：

`p1_api_trace.json`、`p1_run_log.txt`、`p1_e2e_summary.json`、截图 `p1_step1…p1_step4_result.png`

流程与实测：
1. `＋` → 增加模型 → 名称 `STEP7验收模型C` → 创建；
2. 点击卡片进入详情（`#detailPage`）；
3. 输入整段自然语言规则（`#ruleTextarea`）；
4. 提交识别 → 后端返回 `NEED_CONFIRMATION`（板块范围歧义）→ UI 弹澄清项（默认 20cm）→ 点击「应用所选解释并继续」；
5. 点击「确认并回测」→ `POST /api/plan/backtest` → `status=OK`、`stem=strategy_c1789894283086_r1_v1`、`n_hits=1`；
6. 结果表渲染成功（`candThead` 列头 + 数据行）。

另记录一次**识别器 fail-closed 实测**：首次输入含「T+0 **到** T+6 价格走势」（前向窗口表述）时，后端返回 `FAILED / MISSING_BUSINESS_ATOM` 并给出可执行提示，UI 未产生任何伪结果 —— 符合"能力缺口不得猜测"的要求。

---

## 4. P2 结构化结果与 Excel —— PASS

| 检查 | 结果 | 证据 |
|---|---|---|
| UI 模型结构化结果可取回，行数 = n_hits | PASS | `p2_ui_model_columns.json` |
| UI 模型 Excel 可打开，行数 = n_hits | PASS | `p2_ui_model_excel.sha256` |
| 结果列集合与冻结 UI 契约一致（股票代码/股票名称/D-0日期/T+0(低/高)/T+1…T+6最高价） | PASS | 同上 |
| 7214 行级 Excel 有效性（P4 大结果集） | PASS | `step7_p4_results.json`（P2a/P2b，rows=7240） |
| UI 只展示 current_result 前 10 行 | PASS | `p1_step4_result.png`、`p3ui_p2_detail_after_restart.png` |

---

## 5. P3 持久化 —— PASS（含 1 处缺陷修复）

### 5.1 后端重启

`p3_restart_record.txt`：验收前进程 PID 17504/30848 → 全部终止 → 重新启动 → 服务 200。
`p3_before_restart.json` / `p3_after_restart.json` 逐模型比对：

| 检查 | 结果 |
|---|---|
| P3a 模型清单一致 | PASS |
| P3b 规则文本 / 结果行数 / 结果行哈希 逐模型一致 | PASS（全部一致） |
| P3c data_date 一致（2026-09-18） | PASS |

### 5.2 浏览器环境重启（真实用户闭环）

`p3ui_p1_after_run.png` / `p3ui_p2_home_after_restart.png` / `p3ui_p2_detail_after_restart.png`、`p3ui_phase1.json`、`p3ui_phase2.json`
流程：新建模型 → 输入规则 → 回测成功（命中 6334 条）→ **关闭浏览器** → 重新打开：

| 检查 | 结果 |
|---|---|
| 卡片仍在，且携带 stem（`data-stem=strategy_c1789895695594_r1_v1`） | PASS |
| 规则原文从 `/api/rules/{stem}` 完整回填 | PASS |
| 结果表恢复（10 行预览 + 完整列头） | PASS |

### 5.3 修复的缺陷：UI 未持久化卡片→策略关联（阻断 P3）

- 现象：回测成功后 `currentRuleStem` 只写内存，**卡片 `ruleStem` 始终为 `null`**；环境重启后该模型详情页显示「该模型尚未提交过规则」，规则/结果无法再打开。证据：`p3ui_debug.json`（`ruleStem: null`、`ruleStem` 在 UI 中仅用于种子数据）。
- 修复（最小、追加式，见 `UI_BASELINE_CHANGE.json`）：
  - 成功分支回写 `currentCard.ruleStem = d.stem` + `saveState()` + `renderHome()`；
  - `_submitGenericPlan` 增加 `persistStem`（默认 `true`）；批量路径传 `false`（避免 N 条规则互相覆盖同一卡片）。
- 影响：`ui/ui_v2.html` SHA-256 `6f4dc5fa…` → `4f0fe3ef…`；原文已备份为 `ui/ui_v2.baseline.html`（同哈希），可一键回滚。
- 回归：§5.2 全部 PASS。

---

## 6. P5 Provider 实测 —— PASS（含主源限流降级说明）

证据：`p5_provider_evidence.json`（原始样本 + 逐字段交叉验证）、`artifacts/verification/step1/*`（16:00 前东财可用时的实测）

| 检查 | 结果 | 说明 |
|---|---|---|
| P5a 东财主源实时可用 | **FAIL（环境级限流）** | 验收时段 `push2his.eastmoney.com` 及镜像 `21./92.` 与 `push2` 清单接口均 `RemoteDisconnected`；三次重试（17:00/17:20/17:25）一致 |
| P5b 雪球备源实时可用 | PASS 3/3 | 原始响应已存证 |
| P5c OHLC 与标准本地行情逐日一致 | PASS 3/3（各 10 个交易日，0 差异） | 雪球 ↔ TDX `.day` |
| P5d 成交额一致（f32 容差） | PASS 3/3 | |
| P5e 成交量一致 | PASS 3/3 | 雪球大数走 JSON float，实测 ≤2 股舍入差（105212750 vs 105212752），已在证据中标注；东财口径为整数手（±100 股） |
| P5f 交易日历覆盖 | PASS | 20260901–20260918，n=14（本时段自动由东财切雪球） |
| P5g Skill 必需字段齐全 | PASS | 依据 `backtest_common.read_day_file` 源码核对 open/high/low/close/amount/volume 全部齐备 |
| P5h 证券属性/板块覆盖 | PASS | 沪主板/创业板/深主板样本均已记录 |

**东财已有可用时段实测留证（可追溯）**：STEP 1 `eastmoney_probe_report.json`（字段映射、`fqt=0` 不复权、`pre_close` 可由前收盘还原、证券属性字段）、`tdx_vs_eastmoney_crosscheck.json`（逐日 OHLC 一致、`vol_ratio_tdx_over_em = 100.0` 证实「手→股」换算）；STEP 5 `T1b`（增量写入后与 TDX 基线逐字段一致）。

结论：**双源架构的"主源不可用即整轮切备源、且备源与标准行情逐字段一致"已被端到端实测**；东财可用性属于外部服务限流，不是实现缺陷。若需东财主源当日实时证据，可在限流解除后重跑 `app/step7_provider_probe.py`（脚本幂等）。

---

## 7. P6 增量数据 / P7 更新 —— PASS

复现：`app/run_step5.py`、`app/run_step6.py`（新鲜重跑）、`app/step7_acceptance.py p6p7`

P6（`artifacts/verification/step5/step5_results.json`，12 PASS / 1 SKIP）：

| 检查 | 结果 |
|---|---|
| T0 备源（雪球）vs TDX `.day` 逐字段（2 股 × 14 交易日） | PASS |
| T1a 沙箱截断至 09-16 → 自动补 09-17/09-18 | PASS（days=[20260917, 20260918]，files=5，skipped=0） |
| T1b 增量后业务字段与 TDX 基线一致 | PASS |
| T2 复跑幂等（UP_TO_DATE） | PASS |
| T3a/b 写入失败 → 全部回滚、历史零破坏 | PASS |
| T4a/b/c 注入坏数据（H<L）→ 仅该股被拦截，其余入库 | PASS |
| T5 新股补建 | SKIP（东财清单限流，优雅降级；核心增量链路不受影响） |
| T6a/b/c 线上 no-op + 行情校验和不变 + data_date 保持 09-18 | PASS |

P7：
- `step6_results.json`（7 PASS）：管线 no-op 不轮换；落后模型重跑并正确轮换（previous=旧 current）；**逐模型失败保护**（异常模型保持旧结果）；`_next_run_ts()` = **2026-09-21 17:05**（下一工作日）；手动更新 API → done。
- `step7_p6p7_results.json`（6 PASS）：`/api/data/latest` 可用；手动 `/api/daily/run` 完成；**周末调用 data_date 保持 2026-09-18（不生成伪"最新完整数据"）**；行情文件 SHA-256 前后完全一致（24 个样本）；模型结果未被无意义刷新。

---

## 8. P8 新增股票 new_hit —— PASS

| 层 | 检查 | 结果 | 证据 |
|---|---|---|---|
| 数据层 | new_hits = current − previous（A/B/C → A/B/C/D 时 D 入列） | PASS | `step7_p4_results.json`（P8a：expect==got；P8b：含名称） |
| 数据层 | 当日新增命中名称覆盖率 | PASS **1790/1790** | `p8_newhits_name_coverage.json` |
| UI 层 | 卡片绿色高亮 + 显示名称 | PASS | `p8_ui_highlight.json`：`active=true`、`stock_text="XD华兴源、睿创微纳 +1788"`、截图 `p8ui_card_highlight.png` |

附：本次同时修复名称覆盖不足问题 —— 名称缓存由 3446 → **8011** 个代码（新增雪球批量行情补名作为第三源，见 §5 变更记录）；`688175` 由「未找到标的」修正为「高凌信息」。剩余未命名代码均为 **退市/长期停牌** 标的（如 600001 邯郸钢铁、000003），实时行情源本身无此数据，属可解释边界（已在 `p8_namecheck.json` 标注）。

---

## 9. P9 前置条件（已解锁）

**裁决已于 2026-09-20 完成**，详见同目录 `DISPOSITION_RULING.md`。3 条 CONFLICT（0824 / 0827A / 0909A）连同
C1–C6 全部裁定为**口径登记**，P0 未解释差异归零，已满足进入 P9 的条件。

ACCEPTANCE 要求 Windows 全量通过后再在 M4 复跑 P0 并留双端证据链。跨平台判据为「输入资产哈希一致 +
业务输出 canonical diff = 0」，且双端须复现**同一差异集合**（11 条已裁定口径差异 + 1 条 C6 能力缺口）。
本次已为 P9 预置两端的可比对基线：`INPUT_MANIFEST.json`（输入资产哈希）与 `EVIDENCE_MANIFEST.json`（证据哈希）。

---

## 10. 变更与回滚

| 变更 | 文件 | before → after | 回滚方式 |
|---|---|---|---|
| UI 卡片持久化修复（P3 阻断项） | `ui/ui_v2.html` | `6f4dc5fa…` → `4f0fe3ef…` | `cp ui/ui_v2.baseline.html ui/ui_v2.html` |
| 名称缓存补名（新增雪球源） | `app/build_stock_names.py`、`appdata/stock_names.csv` | 3446 → 8011 代码 | 重跑 `app/build_stock_names.py`（旧源仍保留） |
| 验收脚本（新增） | `app/step7_acceptance.py`、`app/step7_provider_probe.py`、`app/step7_namecheck.py` | 新增 | 直接删除 |

`skills/tdx-stock-backtest-master`、`golden/**` **零修改**（哈希见 INPUT_MANIFEST，可逐文件校验）。

---

## 11. 复现命令

```bash
# 输入资产哈希（24439 文件）
python app/step7_acceptance.py manifest
# P0 Golden 全量（26 条）
python app/step7_acceptance.py p0
# P5 Provider 双源实测
python app/step7_provider_probe.py
# P2/P8 名称回填核验
python app/step7_namecheck.py
# P3 后端重启前后快照（重启进程后各跑一次）
python app/step7_acceptance.py p3_before && python app/step7_acceptance.py p3_after
# P4 轮换/失败保护 + P2 Excel + P8 diff
python app/step7_acceptance.py p4
# P6/P7 手动更新管线
python app/step7_acceptance.py p6p7
# P6/P7 深度链路（沙箱增量、调度、失败保护）
python app/run_step5.py && python app/run_step6.py
# P1/P3/P8 真实 UI（Playwright + Edge，脚本在 node workspace）
node p1_run.js && node p3_ui.js && node p8_ui.js
```

---

## 12. 裁定收口（2026-09-20 追加）

本报告 §2 的 P0 判定原为「FAIL-CLOSED，等待裁决」。裁决已完成，收口如下：

| 项 | 内容 |
|---|---|
| 裁定人 / 方式 | kk / 按 pp 建议一次性定稿 |
| 裁定记录 | `DISPOSITION_RULING.md` + `RULING.json` |
| P0 判定（裁定后） | 14 `PASS` + 11 `PASS_WITH_RULED_DELTA` + 1 `CAPABILITY_GAP` + **0 `UNEXPLAINED`** |
| 裁定后视图 | `p0_with_ruling.json`（原始判定 `p0_golden_results.json` 保持原样，未被覆盖） |
| 未篡改证明 | `UNTOUCHED_PROOF.json`：golden 24385 文件、SKILL 本体 53 文件，变更 0 / 缺失 0，`all_unchanged = true` |
| 输入清单 | `INPUT_MANIFEST.json` 更新为 24444 文件（补录 `skill/dev/` 5 个本项目探针为独立键） |

裁定要点：**C1** 取整认现行 Skill；**C2** 涨停判定认现行 Skill 严格 `==`；**C3** 认沪深两市（标准答案漏扫深市）；
**C4** 豁免（标准答案生成时行情版本不一致）；**C5** 以标准答案列集为准、`rule.txt` 不动仅登记；
**C6** 排入后续版本（`forward_window`）。

**任一项均未修改 Golden 结果表、行情快照、Skill 源码或比较器代码** —— 全部为口径登记，
故"我方与标准答案的差异"仍可被独立复算。

新增验收脚本：`app/step7_disposition.py`（`ruling` / `untouched` 两阶段）。

遗留两项待确认优先级：`rule.txt` 补写 C5 缺失列、`skill/dev/` 迁出 Skill 目录。
