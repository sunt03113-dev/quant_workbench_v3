# STEP 4 验证报告 —— 产品行为补齐

日期：2026-09-20　运行环境：Windows / qwb venv / 127.0.0.1:8000（复用已验证后端）
复现：`app/step4_test.py`（原始结果 `artifacts/verification/step4/step4_results.json`）

## 结论：16/16 检查全部 PASS

| # | 检查项 | 结果 | 证据 |
|---|---|---|---|
| T1a/b | 两条不同规则先后成功回测（stem=step4_model_a） | PASS | n_hits=1 → 7240 |
| T1c | current = 第二次成功结果 | PASS | daily/state n_hits=7240 |
| T1e | previous.json 行数 = 第一次结果（1 行） | PASS | 文件级比对 |
| T1f | previous.xlsx 同步轮换 | PASS | 文件存在 |
| T3 | new_hits = current − previous（逐代码集合比对） | PASS | 期望 1797 = 实得 1797 |
| T3b | new_hits 每项含股票名称 | PASS | — |
| T2a | 非法 plan → status=FAILED + violations | PASS | 20 项违规 |
| T2b | 失败后 current/new_hits **完全不变**（失败保护） | PASS | 前后 JSON 快照相等 |
| T2c | 确定性复核可拦截坏行（fail-closed 第二道闸） | PASS | 离线注入 1 坏行被拦 |
| T4 | candidates?limit=10 → 恰好 10 条（UI 前 10 预览数据源） | PASS | — |
| T5a/b | Excel 下载 200、pandas 可读、行数=n_hits | PASS | 380KB / 7240 行 |
| T6a | state.json 落盘含 current+previous（跨重启等价：store 每次自磁盘读） | PASS | — |
| T6b | 损坏 state.json → 空状态 + .corrupt.json 备份，不崩溃 | PASS | 副本注入测试 |

## 与冻结需求的对应

- **模型结果轮换**：成功 → previous←current、current←新；失败 → 两者均不变（T1/T2）
- **UI“10条结果”**：`/api/backtest/{stem}/candidates` 返回全量，冻结 UI 自行取前 10 渲染；Excel 承载完整结果（T4/T5）
- **新增股票**：new_hits = 新 current − 旧 current，失败运行不参与 diff（diff 仅取自已保存成功结果，T3）；冻结 UI 以 `new_hits` 非空为唯一绿色高亮判据，字段形状 `{code, name}` 与前端 `loadCardStocks()` 消费契约逐字段核对一致
- **持久化**：规则+结果双 JSON+双 XLSX 落 `appdata/state/`，损坏自愈带备份（T6）
- **UI 契约**：grep 冻结 UI 全部 `fetch` 调用 → 9 个端点全部实现且字段形状一致

## 说明

- 测试用 stem `step4_model_a` 已在验证后从 state 清理，工作台保持干净；证据 JSON 留档。
- `/api/daily/run` 的行情增量获取在 STEP 5 接入 Provider 后升级（当前仅完整性检查+状态刷新，UI 按钮链路已验证）。

## 下一步

STEP 5：Market Data Provider（东财已过 STEP 1 硬门禁）→ 标准化/校验 → 写入标准行情 → data_date 更新；失败不破坏历史。
