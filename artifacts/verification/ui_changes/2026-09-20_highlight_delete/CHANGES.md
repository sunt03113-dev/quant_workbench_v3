# UI 变更登记 — 2026-09-20 首页高亮语义 + 卡片管理菜单

## 变更 1：首页绿色高亮语义修正（kk 需求）

- **旧语义（废除）**：`new_hits = 本次成功回测 − 上次成功回测` 的股票代码 diff。
  缺陷：与"哪一天"无关——手动重跑（改规则、复核修复后重跑）产生的历史差异
  全部被标为"新增"并挂绿。例：1Z1A 重跑 diff=130 条全绿，但最新交易日
  （2026-09-18）当天实际新触发 0 条。
- **新语义**：`day_new_hits` = current 结果中「D-0 日期 == 全局最新交易日」的
  命中股票（去重保序）。绿色高亮唯一判据；卡片第二行副标题同步显示该名单。
  即"该模型在最新交易日当天有新触发的信号"。
- 实现：`app/store.py` 新增 `day_new_hits(state, stem, day)`，
  `daily_state_payload()` 每模型附加 `day_new_hits` 字段（附加式，原
  `new_hits` diff 字段保留不动，P8 验收语义不受影响）；UI
  `loadCardStocks()` 改用 `day_new_hits`。

## 变更 2：卡片「⋯」管理菜单修复（kk 需求）

- **缺陷**：卡片容器 click 处理器（openDetail 进入详情页）在冒泡阶段先于
  document 级菜单处理器执行，点击「⋯」直接进入卡片，菜单永远无法打开；
  菜单内"删除模型"（软删除→回收站，可恢复）功能实际存在但不可达。
- **修复**：`attachGroupEvents` 的 click 处理器开头增加
  `if (e.target.closest('.card-more') || e.target.closest('.card-menu')) return;`
  点击「⋯」现在正常弹出菜单（含删除模型）。

## 证据

- 修改前备份：`ui_v2.before.html`、`store.py.before`
- 哈希：`before.sha256` / `after.sha256`（SHA-256）
- 验证（2026-09-20，data_date=2026-09-18）：
  - 1Z1A：diff_new=130 → day_new=0 → 不再高亮 ✓
  - strategy_6f43c4300c_v1 / strategy_20cm_v1（2S1）：day_new=1（金石亚药）→ 高亮 ✓
  - strategy_c1789895695594_r1_v1：day_new=3 → 高亮 ✓
  - e2etest / c1789894283086：day_new=0 → 不高亮 ✓
- 注：名称缓存缺失的退市股显示"未找到标的"，属已知边界（见 MEMORY.md）。
