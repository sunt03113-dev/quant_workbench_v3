# 2026-09-23 改动记录：2S1 识别修复 + 质询回到工作台内问答

## 结论速览

- 2S1 规则原文识别失败根因三处：`成交额环比` 不在输出词汇表、`T+0~T+6` 波浪键无子匹配器（静默丢列）、
  `收/定为阴` 阴线条件被**静默丢弃**（比报错更危险）。
- 质询交互按 kk 新口径重做：**问与答都在工作台 UI 内完成**，废除剪贴板桥；
  WorkBuddy 只承担维修/部署支持。

## 改动清单

| 文件 | 改动 | 约束 |
|---|---|---|
| `app/recognizer.py` | ① 阴/阳线写法扩展（K线为/收盘为/收为/定为/收定为/收/定为 + 阴线/收阴）；② 出现阳/阴但未匹配 → fail-closed（堵静默丢弃）；③ 输出 T 键接受 `~`（`_RE_OUT_KEY`/`_RE_OUT_T`）；④ `成交额环比` 为 `成交额百分比` 别名（day/range/varrange 三分支） | before `recognizer.before.sha256`；备份 `recognizer.v4.baseline.py` |
| `app/ask.py`（新增） | 确定性核验模块：原 run_plan 收窄单股 + 结果表逐日期比对 + 人话结论；只读、零新增判定逻辑（capability probe 收编） | 无引擎改动 |
| `app/server.py` | 新增只读 `POST /api/ask/row`（AskReq：stem/code/date/query）；纯增量路由 | additive |
| `ui/ui_v2.html` | 「询问模型」改为内联问答面板：输入框+提交 → 回答区（结论+数值表+命中日期+一致性+可展开 JSON 证据）；删除 prompt/剪贴板桥 | before `f63…`（见 ui_ask_entry/ui_v2.before_0923.*）；备份 `ui_v2.before_0923.html` |

## 验收（证据在本目录）

1. **golden 26/26**：判定映射与 `rule_10cm/golden_after_notation_skip.txt` 基线逐条一致
   （`golden_after_2s1fix.txt` / `regression_result.json: golden_match_baseline=true`）。
2. **门禁负例**：`D-0：不涨停，旭阳`（阳/阴残留）→ FAILED；`T+0~T+6：振幅`（非走势）→ FAILED。
3. **门禁正例**：阴/阳线 7 种写法全 READY 且 candle 正确；`D-0/D-1：成交额环比` → amount_pct；
   `T+0~T+6：价格走势` → 真实 t_walk 原子（strict_pass，区别于空输出兜底假阳性）。
4. **2S1 原文端到端**：READY → run_plan 1490 行 / 16 列（走势列已回来）/ validate_rows 0 违例。
5. **ask API 三用例**（`ask_api_case*.json`）：121_r1_v1+688037 → 不在池属预期；
   c1789895695594+20200117 → 未封板不是遗漏（收 102.8/高 109.8 ≠ 涨停价 112.8）；
   同模型+20200116 → 封板命中、重跑 7==存表 7、复核 0 违例、consistency OK。
6. **UI 浏览器验收**（playwright-core + Edge，`ui_ask_verify_results.json`）6/6 PASS：
   内联面板展开（无 prompt/剪贴板）→ 提交 → 回答区渲染结论+证据 → 连续二次质询正常。
7. 后端已重启生效（127.0.0.1:8000，/api/data/latest 200）。

## 已知残留（登记不动）

- 输出键匹配失败时 `_parse_outputs` 对不认识键的行为仍是静默 continue（本次 T 键修复后 2S1 无此问题，
  但未知的键写法仍可能静默丢列）——待真实案例再议，避免盲目收紧破坏存量规则。
- 幽灵编辑：本轮三次 Edit 报成功但未落盘（_RE_CANDLE 首次、_RE_OUT_T 首次、测试脚本选择器），
  已全部通过 Grep 复验 + 重改解决。此后每次 Edit 后必须 Grep 校验落盘。
