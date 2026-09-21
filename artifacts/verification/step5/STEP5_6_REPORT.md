# STEP 5+6 验证报告 —— Market Data Provider 与每日更新管线

日期：2026-09-20　环境：Windows / qwb venv / 127.0.0.1:8000
复现：`app/step5_test.py`、`app/step6_test.py`（经 `run_step5.py`/`run_step6.py` 落 UTF-8 日志）

## STEP 5 结论：13 检查 0 FAIL（T5 新股补建因东财清单限流 SKIP，机制为优雅降级）

**架构**（Provider 与 Skill 完全解耦，Skill 零感知）：

```
东财 push2his kline(fqt=0, 主源)  ─┐
                                  ├→ 标准化(手→股×100/分/元) → 硬校验 → 追加 .day(带回滚日志) → 标准本地行情 → Skill
雪球 chart/kline(type=normal,备源) ┘
```

| # | 检查 | 结果 |
|---|---|---|
| T0 | 雪球备源 vs TDX .day 逐字段交叉验证（2 股×14 交易日） | PASS，OHLC 分级精确、amount f32 一致、volume 逐股一致 |
| T1a | 沙箱截断至 09-16 → 自动检出缺失 [09-17, 09-18] 并增量补齐 5 标的 | PASS |
| T1b | 增量后业务字段与 TDX 基线逐字段一致（OHLC/amount 精确；volume ±100 股容差） | PASS |
| T2 | 复跑幂等（UP_TO_DATE） | PASS |
| T3a/b | 目标文件只读 → 写失败 → **RuntimeError + 全部追加回滚**，历史零破坏 | PASS |
| T4a/b/c | 注入坏数据（H<L）→ 仅该股被校验拦截，其余正常入库，坏数据不落盘 | PASS |
| T5 | 新股补建（EM 全A清单 diff → 补建完整历史 → Skill 可读） | SKIP：东财 clist 被限流；核心增量链路不受影响 |
| T6 | 线上 no-op：周末调用 `/api/daily/run` → done，真实行情校验和不变，data_date 保持 2026-09-18 | PASS |

**过程中发现并修复的缺陷（均有实证）**
1. `encode_record` 少传 reserved 字段（pack 8 项只给 7）→ 已修
2. 雪球 count 语义：负数=截止 begin，正数=从 begin 起 → 修正后增量窗口正确
3. 测试自身取整 bug（round 元 vs 分）→ 修正后 T0 全对齐
4. EM 间歇黑洞连接 → 日历探测快速失败（timeout=8s/tries=1），整轮自动切雪球
5. **自愈设计**：抓取/校验失败的个股按"个股自身水位"（而非全局 max）决定下次 beg，漏补自动补齐
6. 保留位：TDX 基线 0/65536 混杂且 Skill 不读取 → 定版写 0

**已知边界（记录，非冲突）**
- EM kline volume 只有整数**手**（±100 股舍入）；Skill 全部业务原子**不使用 volume**（grep 全部 26 个脚本证实：volume 仅解包/过滤），对业务零影响
- 新股补建依赖东财 clist；限流期间优雅降级，历史增量不受影响

## STEP 6 结论：7 检查 0 FAIL —— 每日管线 + 轻量调度

**每日管线**（`server._daily_pipeline`，手动按钮与定时共用，pipeline_lock 防重入）：
增量更新 → 逐模型重跑（data_date 落后才重跑）→ 成功才轮换/Excel → new_hits diff → 状态

| # | 检查 | 结果 |
|---|---|---|
| T1 | 数据未变 → 模型 kept，不无意义轮换 | PASS |
| T2 | 模型落后（伪造 data_date=09-17）→ 重跑 + 轮换正确（previous=旧 current） | PASS |
| T3 | 注入重跑异常 → **仅该模型保持旧结果**，其余与状态不受影响（fail-closed） | PASS |
| T4 | 调度决策：`_next_run_ts()` = 2026-09-21 17:05（下一工作日） | PASS |
| T5 | `/api/daily/run`（UI"更新数据"按钮）→ done | PASS |

**自动更新实现**（冻结允许的最简可靠方案：应用内轻量调度）：
- 工作日 17:05 自动执行每日管线（daemon 线程）
- 启动补偿：若已过 17:05 且模型结果落后于最新行情 → 启动后自动补跑
- 无新增依赖、无 OS 级任务计划、随工作台启停

## 可验证记录

- `artifacts/verification/step5/`：step5_results.json、test_run_utf8.log、STEP5_6_REPORT.md
- `artifacts/verification/step6/`：step6_results.json、test_run_utf8.log
- 复现脚本：app/step5_test.py、app/step6_test.py（runner: run_step5.py / run_step6.py）

## 下一步

STEP 7：Windows 完整验收 —— 逐项执行 ACCEPTANCE.md（P0-P8），artifacts/verification/<run_id>/ 留机器可复核记录（含 SHA-256 清单）。
