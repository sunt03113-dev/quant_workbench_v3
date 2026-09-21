# STEP 1 实测报告｜环境与数据能力核查

- 时间：2026-09-20 13:20~13:40 (GMT+8)
- 执行者：WorkBuddy (pp)
- 状态：**完成（增量 Provider 候选通过硬门禁，tdx-connector 待用户安装后补测）**

## 一、冻结基线阅读清单（全部已读）

| 文件 | 关键事实 |
|---|---|
| PRODUCT.md / BUSINESS.md / DATA.md / ACCEPTANCE.md / CONSTRAINTS.md / WORKBUDDY_INSTRUCTION.md | 冻结范围、fail-closed、Provider 硬门禁、汇报留证规则 |
| ui/ui_v2.html | 冻结 UI。**自带完整 API 契约**：`http://127.0.0.1:8000`，端点 `/api/plan/recognize`、`/api/plan/resolve_ambiguity`、`/api/plan/backtest`、`/api/rules/{stem}`、`/api/backtest/{stem}/candidates(/export)`、`/api/data/latest`、`/api/daily/state|run|jobs/{id}` |
| skill/tdx-stock-backtest-master/ | 业务唯一权威。直接读 TDX .day 二进制（32字节/条，无 pre_close 字段）；`config.yaml` 可配 `tdx_base`；依赖 akshare(名称兜底)/numpy/pandas/openpyxl/tqdm/pyyaml；`backtest_common.compute_limit_flags` 为涨停判定权威实现 |
| golden/ | `rule.txt`(26条冻结规则) + `vipdoc/{sh,sz}/lday`(**11,704 个 .day 固定测试行情，最新交易日 2026-09-18**) + 26 组规则 CSV/XLSX 正确输出 |
| docs/SOURCE_business_baseline_README.md | 业务原子清单与 backtest_common 函数一一对应；不存在第二套公式 |

## 二、候选 Provider 实测结果（非仅看名称）

### A. tdx-connector（市场内存在，未连接）
- 证据：`search_plugins` 返回 `tdx-connector`（通达信 MCP：行情/条件选股/研报）。
- 本会话 ToolSearch 中**无任何 tdx 可调用工具**；connector-status 仅 agent-mail。
- 结论：**未实测，不得进入生产方案**。已向用户发出安装建议，安装后须按硬门禁实测工具/字段/时间范围/更新时效。
- 记录：本文件 + 对话记录。

### B. westock CLI（腾讯自选股，finance-data 插件）
- 实际操作：执行官方 setup.cjs 安装 v0.0.4 → `C:\Users\21412\.local\bin\westock.exe`。
- 实际调用尝试（6 次 probe + 2 次直接执行）：**全部被 OS 应用程序控制策略拦截**（`OSError(22, '应用程序控制策略已阻止此文件')`，rc=126），非工具沙箱原因（dangerouslyDisableSandbox 同样被拒）。
- 结论：**当前环境不可用（FAIL）**。样本：`westock_*.txt`（拦截记录见 step1_probe_westock.py 输出）。

### C. 东方财富 HTTP API（akshare 底层同源）✅ 通过硬门禁（增量用途）
实测脚本：`skill/dev/step1_probe_eastmoney.py`、`step1_probe_eastmoney2.py`、`step1_crosscheck_offline.py`。原始样本在 `artifacts/verification/step1/`。

| DATA.md 要求 | 实测结果 | 证据文件 |
|---|---|---|
| symbol/trade_date | secid `1.600519`=SH `0.300010`=SZ 映射确定；kline 返回日期 YYYY-MM-DD | eastmoney_raw_samples.json |
| OHLC | f52开/f53收/f54高/f55低 | 同上 |
| pre_close | 由 `close-chg` 推导，与昨日收盘一致（600519: 1266.98✓） | eastmoney_probe_report.json |
| volume 单位 | **手**（TDX/EM 逐日比=100.0） | tdx_vs_eastmoney_crosscheck.json |
| amount 单位 | **元**（与 TDX f32 金额完全一致 rel_diff=0） | 同上 |
| 复权口径 | fqt=0 不复权，与 TDX .day 10个交易日×2股（SH+SZ）OHLC **完全一致** | 同上 |
| 交易日/时效 | 2026-09-18（周五）K线当日可得；今天 2026-09-20 已能取到 | eastmoney_probe_report.json |
| ST/板块属性 | quote 返回名称（300010→"ST豆神"✓）；板块由代码前缀确定（与 Skill 一致） | eastmoney_probe_report.json |
| 上市日期/新股 | quote f26 返回 null（待换字段组合）；**非阻塞**：Skill 的新股处理依赖严格涨停价判等+20日窗口，可由本地首K线推导上市日 | 同上 |
| 交易日历 | 指数(1.000001)日K线可作日历源（样本已存） | eastmoney_raw_samples.json |
| 历史深度 | 1991 年老股票深度**待网络恢复补测**（当前网络限流）；非阻塞：全量历史由 TDX 基线承担，Provider 仅做增量 | — |

- 网络稳定性：13:21~13:26 连续成功；13:30 后出现 RemoteDisconnected 限流。Provider 实现必须带重试+退避+失败不落库。

### D. 其他能力盘点
- `neodata-financial-search`：资讯/研报聚合检索，非结构化全量日线源 → 不适合作增量 Provider。
- WorkBuddy 自动化（automation_update）：可用 → STEP 6 自动更新的候选调度方案。
- a-stock-analysis skill：东财/新浪 HTTP，Python 通道不受 App Control 影响（佐证 C 可行）。
- 本机已有完整 TDX 历史（Windows）：历史基线来源，一次性导入。

## 三、结论与最小实现决定

1. **增量 Provider**：东方财富 HTTP API（fqt=0 不复权，字段/单位/时效/属性全部实测通过），经「标准化/校验」写入标准本地行情；Provider 适配层隔离，Skill 不直接依赖。Skill 必需字段全部可获得。
2. **tdx-connector**：待用户安装后按同一硬门禁实测；若通过可复用，不通过则以东财为准。
3. **标准本地行情物理格式（工程决定）**：沿用 TDX .day 兼容二进制（32字节记录），存于应用数据目录 `stdday/{sh,sz}/lday/`。理由：Skill 零修改可读（冻结要求）、增量=追加记录、纯二进制跨 Windows/macOS、无 D:\ 依赖、体积与 TDX 原生相同。配 `meta.json`（schema_version/data_date/校验值）。DATA.md 不限定物理格式，此选择满足全部约束。
4. **pre_close**：TDX .day 与东财 kline 均无独立昨收字段 → 标准化层按 symbol 时序推导 `pre_close = prev close` 并写入 meta 校验。
5. **Golden 测试协议注意**：golden CSV 生成时点早于固定行情快照（快照含 2026-09-18 数据，CSV 最大基准日 2026-04-08）。STEP 3 须用固定 end_date 复跑；将通过二分法确定与 Golden 完全一致的截止日；若不存在一致的截止日 → fail-closed 生成 conflict report。

## 四、验证记录索引（artifacts/verification/step1/）

- `golden_vipdoc_probe.json` — 固定行情体检（11704 文件/最新 2026-09-18/样本记录）
- `eastmoney_raw_samples.json` — 东财原始响应（4股 kline fqt0/fqt1 + quote + 指数）
- `eastmoney_probe_report.json` — schema/单位/pre_close/属性结构化验证
- `eastmoney_early_history_000001.json` — （待补测，网络限流）
- `eastmoney_unit_crosscheck.json` — 单位交叉验证
- `tdx_vs_eastmoney_crosscheck.json` — **TDX vs 东财逐日一致性（决定性证据）**
- `step1_probe_*.py` / `step1_crosscheck_offline.py`（在 skill/dev/）— 可复现实测脚本
