# 通用问答：质询入口从「仅个股」升级为意图路由（2026-09-23）

## 起因（kk + 截图）
用户在「询问模型」输入「怎么计算区间涨幅的？」→ 报错「未提供股票代码且质询中无可识别代码/名称」。
kk 指示：询问不应局限于个股质询，不应一一列举，但应具备都能分析回答的能力。

## 方案：意图路由（确定性，零 LLM、零新增业务判定）
`/api/ask/row` 单一入口内部分流：
- **个股类**（query 含 6 位代码，或中文命中 stock_names.csv）→ 原单股核验路径，一行未动；
- **口径/模型/统计类** → `ask.answer_general()`：确定性回答；
- **无法归类** → 能力清单（个股格式 + 口径类示例 + 模型类示例），绝不猜。

## 通用回答的三个事实来源（全部随包、可复核）
1. **口径文档原文摘录**：`skill/tdx-stock-backtest-master/tdx-stock-backtest.md` 按标题摘录
   （§五 涨停判定、§六 T+n 基准价、§七 振幅与涨幅、§九 间隔定义），文档随包版本化 → 答案与引擎同源；
2. **模型/结果取数**：plan（rule_text/universe）与已存结果表（行数、股票数、日期范围、输出列）；
3. **能力清单**（兜底）。

意图表（正则，按序匹配）：间隔/振幅/涨停/涨幅/走势T+/成交额/池宇宙/命中统计，空输入=模型概览。

## 验收（8 API 用例 + 3 UI 用例，全 PASS）
- API：区间涨幅口径✓ 间隔定义✓ 涨停口径✓ 空输入概览✓ 命中统计✓ 无法归类清单✓
  个股回归（688037 20200116，封板但非信号日→未命中属预期，一致性 OK）✓ 池范围✓；毫秒级响应（个股路径 1.7s）。
- UI：口径问题原位解答（含本模型相关输出列）✓ 个股路径不受影响✓ 兜底清单✓。截图见本目录。

## 影响面
- `app/ask.py`（新增 answer_general + _doc_excerpt + _result_stats + _INTENTS）、
  `ui/ui_v2.html`（placeholder/loading 文案 + renderAskAnswer general 分支）。
- `app/skill/golden/executor` 零改动；recognizer/executor 未动；无需重跑模型。
- UI 哈希：before = ui_home_v3/EVIDENCE_MANIFEST 的 after，本轮 after 见本目录 EVIDENCE_MANIFEST.json。
