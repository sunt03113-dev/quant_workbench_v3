# 质询回答错误修复：新增「结果构成核查」意图（2026-09-23）

## 问题（kk 截图）
在 111A 详情页质询「这个结果中有没有包含30开头的股票的10cm阶段的吗？」，
回答掉入【命中统计】兜底（722 行/644 只/最近命中日期），答非所问。

## 根因
意图路由表（app/ask.py `_INTENTS`）没有「结果构成」类意图；问题里的「结果」命中 stats 兜底。

## 修复（仅 app/ask.py，UI 零改动）
- 新增 `_detect_prefixes`：识别「30开头/688开头/创业板/科创板/主板」等前缀意图；
- 新增 `_answer_composition`：确定性扫描——池内该前缀股票数（`_collect_stock_files`）×
  已存结果表该前缀股票数（附名称示例，来源 stock_names.csv），三种结论分支：
  ① 结果里有 → 数量 + 示例；② 在池但无 → 从未满足条件（非遗漏）；
  ③ 不在池 → 属预期（板块过滤），点明 universe 语义；
- 10cm × 创业板特判补充：引擎已按 2020-08-24 分段，但 10cm 池整个板块排除（含 10% 时代），
  覆盖该阶段属口径变更（待 kk 裁定），工作台不擅自改；
- `_result_stats` 补 codes 字段；兜底能力清单加④构成类。

## 验收
- API 7 用例全过（ask_composition/summary.json）：111A+30开头=0 只属预期 ✓、
  20cm 模型 30 开头 1294 只带示例 ✓、688 开头 497 只 ✓、命中统计/涨停口径回归 ✓、
  个股路径回归（一致性 OK）✓、无法归类清单 ✓；
- UI 浏览器验收 3/3 PASS（ui_verify_results.json + ui_composition_111A.png）：
  用户原句在 111A 详情页内出【结果构成核查】正确回答；
- 测试环境坑（已记档）：UI 的 `API="http://127.0.0.1:8000"` 写死，测试若从 localhost 加载页面
  则所有 fetch 跨域失败（Failed to fetch）——真实用户不受影响（从 127.0.0.1 打开）。

## 改动面
- app/ask.py（before/after 哈希见 EVIDENCE_MANIFEST.json）；ui/app 其余、skill/golden/executor 零改动。
- 本轮 UI 未改（ui_v2.html 哈希与上轮一致）。
