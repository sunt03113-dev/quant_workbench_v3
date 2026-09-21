# Business Definition Baseline（V1 冻结版）

> 本目录是 **V2 Agent Architecture 迁移前的业务定义基线**。
> 内容**只提取当前冻结版本的事实**，不含优化建议、不含新设计、不含重构方案。
>
> - 冻结分支：`v2-agent-architecture`（自 `v1-baseline-20260915` 切出）
> - 事实来源：`rule_engine/skills.py`（业务定义唯一登记处）、`rule_engine/operators.py`（权威算子）、
>   `rule_engine/event_matcher.py`、`rule_engine/generic_runtime.py`、`ir/strategy_plan.py`、
>   `docs/GATE5_MATCHING_SEMANTICS.md`
> - 提取方式：静态扫描 + 源码引用，未运行任何修改

## 文档索引

| # | 业务 | Skill ref / 结构 | 文档 |
|---|---|---|---|
| 1 | 涨停 | `limit_up_v1` | [01-limit-up.md](01-limit-up.md) |
| 2 | 首个涨停事件（首板角色） | `first_limit_up_event_in_pattern` | [02-first-limit-up-event.md](02-first-limit-up-event.md) |
| 3 | 成交额 20 日最大 | `is_amount_max20_v1` | [03-amount-max20.md](03-amount-max20.md) |
| 4 | 最高价 20 日最大 | `is_high_max20_v1` | [04-price-max20.md](04-price-max20.md) |
| 5 | 振幅（单日 / 区间 / 平均） | `daily_amplitude_v1` / `interval_amplitude_v1` / `average_daily_amplitude_v1` | [05-amplitude.md](05-amplitude.md) |
| 6 | 区间谓词 | `IntervalConstraint`（3 种 type） | [06-interval-predicate.md](06-interval-predicate.md) |
| 7 | T+n 价格走势 | `price_trend_t0_t6_v1` / `price_trend_t0_t7_v1` | [07-t-plus-n.md](07-t-plus-n.md) |

## 全局事实（跨规则适用）

**Skill Registry 是业务定义的唯一来源**（`rule_engine/skills.py:52`）。任何业务原子必须先在
`SKILL_REGISTRY` 登记，再在 `SKILL_BACKENDS` 注册 backend；Runtime **不得**复制公式
（`rule_engine/event_matcher.py:12`，由 `tests/test_gate5_generic_runtime.py::test_matcher_has_no_formula_constants` 断言）。

**校验链 fail closed**（`rule_engine/event_matcher.py:149-161`）：
原子未登记 / `status != "implemented"` / 无 backend / `backend.verified is False`
→ 抛 `BusinessAtomUnavailable`。`sql` backend 当前**全部** `impl=None, verified=False`
（`rule_engine/skills.py:150-154, 193-195`），生产只走 `numpy`。

**当前原子状态一览**（`rule_engine/skills.py`）

| ref | kind | status | numpy backend | verified |
|---|---|---|---|---|
| `limit_up_v1` | metric | implemented | `operators.compute_limits` | ✅ |
| `rolling_max20_v1` | metric | implemented | `operators.rolling_max20` | ✅ |
| `is_amount_max20_v1` | metric | implemented | `operators.is_amount_max20` | ✅ |
| `is_high_max20_v1` | metric | implemented | `operators.is_high_max20` | ✅ |
| `daily_amplitude_v1` | metric | implemented | `operators.daily_amplitude` | ✅ |
| `interval_amplitude_v1` | metric | implemented | `operators.calc_range_amplitude` | ✅ |
| `range_return_v1` | metric | implemented | `operators.calc_range_increase` | ✅ |
| `price_trend_t0_t6_v1` | macro | implemented | `operators.generate_t_fields` | ✅ |
| `price_trend_t0_t7_v1` | macro | implemented | `operators.generate_t_fields(t_count=8)` | ✅ |
| `average_daily_amplitude_v1` | metric | **pending_semantic_confirmation** | **None** | ❌ |

**输出层统一格式化**（`rule_engine/generic_runtime.py:44-54`）：
`None` → 字面 `"N/A"`；`NaN` → `"N/A"`；float → `round(v, 2)`（`OUTPUT_ROUND_DIGITS = 2`，L38）；
bool / int 原样。**未来未发生 / 无前收 / 越界一律 `N/A`，绝不填 0**（S11）。

## 本基线的边界

- 本目录**不定义**新语义，**不修改**任何现有行为。
- 文中若出现「声明与实现不一致」的表述，属**事实记录**，本轮不做修复。
- V2 迁移时，本目录所列「Agent 禁止修改项」为硬约束。
