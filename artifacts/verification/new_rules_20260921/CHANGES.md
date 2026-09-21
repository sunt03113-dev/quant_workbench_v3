# 新规则能力上线登记（2026-09-21）

## 需求
kk 两张模型卡片报「存在暂不支持的表达」：
1. **0921A**：`D-(x+k)` 括号变量日、`D-x~D-1` 变量起点区间输出（存量能力只认 `D-x+k` 无括号写法、区间末端只支持 `D+未来`）。
2. **111A3**：间隔链规则 —— T_0→T_1→T_2 锚点 + 间隔 N1∈[1,3]、N2∈[1,4] 双变量存在量词（全新能力）。

## 语义裁定（kk 确认，AskUserQuestion）
- **间隔 N = 相差 N 个交易日**（N=1 相邻，同 D-0/D-1 关系）；N1+N2 组合 → 三板跨度 3~8 个交易日。
- **每个满足的 (N1,N2) 组合各出一行**（与 1S1「每个 x 各出一行」口径一致）。
- 方向由规则自身逻辑锁定：T_0 最早（首板+前4日无涨停，若 T_0 最新则与 T_1 涨停矛盾），T_2 为信号日（输出其日期）。

## 实现
### recognizer.py
- `_RE_DAY` 变量日支持 `D-(x+k)` / `D-(x-k)` / `D-(x)` 括号写法。
- `_RE_OUT_KEY` / `_RE_OUT_VAR_PAREN` / `_RE_OUT_VAR_RANGE`：括号变量日输出键；变量区间末端支持 `D-b`（历史端），如 `D-x~D-1`。
- 新增间隔链解析器 `_parse_chain_rule`：间隔声明（`T_0-T_1间隔N1∈[1,3]`）、锚点条件（首板/前N日无涨停/成交额不小于锚点/成交额和股价20日最高/仅锚点涨停）、间隔无涨停（共享谓词「A与B间、B与C间无涨停」自动拆分）、输出段（顿号连接单行多指标逐项匹配：chain_date/chain_gap/chain_range/chain_amplitude 等）。拓扑校验：锚点 T_0 起连续编号、间隔仅连相邻锚点、变量 N1..Nk 连续编号。fail-closed 不变。
- `plan_to_base_rules` 支持链式计划（t_0/t_1/t_2 键）。

### executor.py
- 新增 `_run_chain` 链式回测路径：`strategy_plan.chain`（anchors/gaps/anchor_conds/gap_conds）；T_0 条件先快检，再对每个 (N1..Nk) 组合验证锚点条件、amount_ge、间隔无涨停；每个满足组合出一行，行内带 N 数值列。信号日（末锚点）应用板块生效日过滤与日期范围。
- `validate_rows` 链式复核分支：由 T_2 日期 + N 值独立重建锚点位置，重验涨停/前N日无涨停/间隔无涨停/20日窗口最大/成交额不小于。
- **涨停复核口径修正（重要）**：复核器原用标量 `is_strong_limit_up`（`>=` 口径），与执行器 `compute_limit_flags`（严格 `==`，Skill 唯一权威实现）在「超涨停价脏点」（如 000557@2002-02-07，收 3.79 > 涨停价 3.78）上分歧。按 **C2 裁定（2026-09-20 kk）** 统一为严格 `==`（compute_limit_flags）；复核独立性体现在「由日期+N重建位置后逐行重验」。此修正同样作用于日条件路径（消除潜在脏点误报）。
- 修复：链式执行器间隔检查误用锚点序号而非日索引（`limits[js[pa]+1:js[pb]]`）——被确定性复核抓出后修复，验证了复核器价值。

## 验证
- 0921A：READY → 405 行（3483 只 10cm），复核 0 违规，API e2e ~4.5s。
- 111A3：NEED_CONFIRMATION(板块) → 10cm → 3840 行，复核 0 违规，API e2e ~15.4s。
- smoke_test ALL PASS；golden 26 条 = 14 PASS + 3 CONFLICT(已裁定) + 8 PASS_WITH_KNOWN_T0_CONFLICT + 1 CAPABILITY_GAP，与裁定基线逐条一致，零回归。
- 修改后 SHA-256 见 after.sha256。

## 附带
- `deploy/start_workbench.bat`：双击启动后端（无需打开 WorkBuddy）。
