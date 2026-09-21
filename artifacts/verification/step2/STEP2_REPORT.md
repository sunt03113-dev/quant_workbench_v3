# STEP 2 验证报告 —— 标准本地行情 + 第一条纵向 E2E

日期：2026-09-20  环境：Windows / Python 3.13.12 (venv `qwb`) / FastAPI 127.0.0.1:8000

## 交付物

| 组件 | 位置 | 说明 |
|---|---|---|
| 标准本地行情 | `appdata/market/vipdoc/{sh,sz}/lday/` | TDX .day 兼容二进制，初始基线从 golden 快照复制（11,704 标的，最新 2026-09-18），不入 Git |
| 后端（冻结 UI 契约） | `app/server.py` | 9 个端点全部实现并托管冻结 UI |
| 识别器 | `app/recognizer.py` | 冻结词汇表 NL → Strategy Plan；fail-closed；板块歧义 → NEED_CONFIRMATION |
| 执行器 | `app/executor.py` | **零公式**：涨停/窗口/振幅/区间/T走势 全部调用 Skill 函数（compute_limit_flags、rolling_max20、daily_amplitude、calc_range_increase、calc_range_amplitude、generate_t_fields、is_strong_limit_up、match_stock_names） |
| 确定性复核 | `executor.validate_rows` | Skill 标量权威口径逐行重验（涨停/成交额20日最大/最高价20日最大/板块生效日），不一致 → 结果不落库 |
| 持久化 | `appdata/state/` | state.json（规则+current/previous）+ results/<stem>/{current,previous}.{json,xlsx}；原子写（tmp+replace） |
| 路径注入 | `app/paths.py` + Skill 自带 `config.yaml` 机制 | 无硬编码盘符；Skill 代码零修改 |

## 实际测试（全部可复现，脚本在 `app/`）

| # | 测试 | 结果 |
|---|---|---|
| 1 | import 链：Skill 加载 + config 注入，DAY_DIRS 指向 appdata/market | PASS |
| 2 | 识别器：UI 占位规则（3 日条件） | PASS |
| 3 | 识别器：golden 0818A 原文 → 原子序列/列名与 Skill OUTPUT_COLUMNS 完全一致 | PASS |
| 4 | 板块歧义 → NEED_CONFIRMATION → resolve → READY(10cm) | PASS |
| 5 | 词汇表外表达 → FAILED(MISSING_BUSINESS_ATOM)，0814 前向窗口规则被正确拒绝 | PASS |
| 6 | golden 0818A 命中个股子集（211 只）复跑：命中集合 221/221 完全一致（缺 0 多 0）；振幅/区间涨幅/区间振幅/成交额百分比 max_diff = 0 | PASS |
| 7 | HTTP 全链路：recognize → backtest（全 20cm，4.2s）→ 复核 → 落库 → rules/candidates/export/daily/state/daily/run | PASS |
| 8 | Excel 落盘验证（300857 协创数据，名称匹配 OK）；跨服务器重启规则/结果持久化 | PASS |

## 发现的真实冲突（fail-closed，待决策 → STEP 3 conflict report）

**Golden 0818A `T+0(低/高)` 最高价取整方向与当前 Skill 不一致**：
- 当前 Skill `backtest_common.generate_t_fields`：T+0 最高价 = fmt_tn（**向下**取整，注释"均变小"）
- golden CSV 实际值：**向上**取整（例：688010@2024-10-30 golden `-2%/21%(板)` vs 现行 Skill 口径 `-2%/20%(板)`；221 行中该字段 exact_match=0）
- 其余全部字段（含 T+1~T+6 最高价，220/221 行）与 golden 完全一致
- 处置：不改 Skill、不改 Golden、不放宽 comparator；STEP 3 出 conflict report 请老板裁决（历史上 Skill 曾修改 T+0 取整规则，golden 生成于修改前）

## 数据时点差异（非冲突，STEP 3 处理）

300313@2026-08-17 行 golden 的 T+ 字段为空（golden 生成时数据未到 2026-08-18），当前数据可计算 → 用固定 end_date 复跑消除。

## 已知限制（记录，不阻塞）

- 前向窗口/间隔窗口规则（0814 型）识别器 fail-closed 拒绝；golden 0814 测试将直接用 Skill 脚本执行
- stock_names.csv 暂由 golden 结果合并生成（3,446 只，EM 全量清单待网络恢复后补全 10cm）
- `/api/daily/run` 当前只做行情完整性检查+状态刷新；增量 Provider 接入在 STEP 5
