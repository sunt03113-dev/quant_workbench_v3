# STEP 3 报告 — Golden 一致性测试

日期：2026-09-20 ｜ 环境：Windows 11，qwb venv（Python 3.13.12，numpy/pandas 版本见 step1）
Harness：`app/golden_test.py` ｜ 原始结果：`golden_test_results.json` ｜ 冲突裁决：`CONFLICT_REPORT.md`

## 测试协议

1. 规则文本：`golden/rule.txt`（0908B 取自 Skill 0908B_backtest.py docstring 权威时间线重建）
2. 识别：`app/recognizer.py`（冻结词汇表 → plan，fail-closed）
3. 复现参数：`end_date` = golden CSV 最大 D-0 日期（锁定命中集）；`data_end` = 之后第 6 个交易日（复现 Golden 生成时 T 视野，T+0~T+7 全覆盖）
4. 比对：命中集 (code, D-0) 精确；列名归一化（`~`→`/`，Skill 各脚本分隔符本不一致）；数值列 float 容差 1e-9；golden N/A（生成时点无未来数据）单独归类豁免
5. fail-closed：任何真实冲突 → CONFLICT，报告见 CONFLICT_REPORT.md

## 结果总览（26 条）

| 判定 | 数量 | 规则 |
|---|---|---|
| PASS | 13 | 0911 0912 0913A 0913B 0915A 0915B 0915C 0917A 0917B 0917C 0917D 0917E 0918A 0918B* |
| PASS_WITH_KNOWN_T0_CONFLICT | 8 | 0818A 0818B 0822 0827B 0908 0908B 0908C 0910A |
| CONFLICT（已根因定位） | 3 | 0824 0827A 0909A |
| CAPABILITY_GAP | 1 | 0814（前向+可变间隔窗口，schema v1 不支持） |

*0918A 首轮 CONFLICT（成交额百分比 ±0.01%），根因为执行器沿用 float32 而 Skill 脚本内部 float64，修复后 PASS。

## 关键数字

- 命中集：除 C2（7 行 1997/2006 边界 bar）与 C3/C4（0909A 股票池、000995 数据差异）外，**25 条规则命中集 100% 一致**
- 业务列值（振幅/涨幅/区间/成交额百分比/T+1~T+7）：float64 修复后 **全部规则 0 diff**（时点豁免除外）
- T+0(低/高)：golden 向上取整 vs Skill 向下取整，8 条规则共约 1140 行（C1，待裁决）
- golden N/A 时点豁免：最大 7 行/规则，均位于快照末期，符合生成时点逻辑

## 工程修正记录（权限内）

- `executor.run_plan` 增加 `data_end` 数据截断（Golden 历史时点复现必需，产品路径不用）
- amounts 统一 `astype(float64)`，对齐 Skill 规则脚本自身读取口径（0909A/0824 的 read_day_raw 均如此）
- 识别器剔除 `【【...】】` 编辑批注（0918B 规则文本内含批注，非业务内容）

## 复现方式

```bash
cd app && C:/Users/21412/.workbuddy/binaries/python/envs/qwb/Scripts/python.exe golden_test.py            # 全部
... golden_test.py 0818A                                                                                  # 单规则
```

## 结论

主链（识别 → 执行 → 输出）与 Golden 的一致性在现行 Skill 口径下已达到：**除 5 类已定位冲突（C1-C5）外零差异**。
冲突不影响 STEP 4 产品行为开发（以现行 Skill 口径实现，裁决后如需切换一次完成）。
