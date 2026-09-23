# 首页改造：2S 拆分 + 降序排序 + 拖拽/重命名 + hover 修复（2026-09-23）

## 需求（kk，均有截图）
1. 默认排序：2S 系列垫底，其他类别按数字降序，新增类别也按规则插入。
2. 2S 类别拆为 2S1 与 2S2/2S3 两类。
3. 新增：拖动调整顺序（类别 + 卡片）；点击类别名/模型名重命名。
4. ＋号 hover 菜单鼠标移过去经常消失，微调修复。

## 排序口径（kk 选项确认）
「数字从大到小」：4 → 3 → 1/2 → 1Z → 1S，2S 系列垫底且内部升序（2S1 → 2S2/2S3，
与手工建立顺序一致）。`N/M` 读作 N.M 档位参与比较；新增类别按规则插入对应位置，
不整体重排（保留用户拖拽结果）。

## 实现（全部在 ui/ui_v2.html，纯前端，零后端改动）
- 排序/迁移：`is2sName / catTokens / cmpCatDesc / defaultSortGroups / insertGroupByRule /
  migrateState`；迁移幂等（`state.mig2sSplit` 标记）：老「2S」组拆分（2S1 卡 → 2S1 组，
  其余 → 2S2/2S3 组，复用已存在的同名空组），ruleStem 绑定保留，随后应用默认排序。
  seedState 同步更新为新结构（新装环境/M4 直接正确）。
- 拖拽修复：原卡片 dragstart 冒泡到组 div 后被 `preventDefault` 抵消（拖不动）；
  现卡片 drag 直接返回不再吞掉；类别拖拽把手 = 左侧类别头（draggable），
  matrix 级 dragover 决定插入位置；卡片支持跨类别移动（DOM 归属为准重新分组）。
- 重命名：点击类别名 / 卡片上的模型名 → prompt（重名校验、空名校验）；
  ⋯ 菜单同时新增「重命名」入口；点模型名不会进详情，点卡片其余区域仍进详情。
- hover 修复：`.plus-menu` top 36px→31px（消除与 31px 高按钮之间的 5px 缝隙）+
  `::before` 透明过桥（-8px 覆盖）＋点击 ＋ 号可切换菜单（点外部关闭）。

## 验收（playwright-core + Edge，headless，11/11 PASS）
- A 迁移：老状态（2S 17卡 + 手建空组 2S1/2S2-2S3 + 空组4）→ 拆分正确、
  顺序 4→3→1/2→1Z→1S→2S1→2S2/2S3、ruleStem 保留。
- B hover：菜单 hover 显示，鼠标穿缝到「增加模型」仍显示，点击可弹新增弹窗。
- C/D 重命名：类别名、模型名 prompt 改名生效且持久化；点模型名不进详情。
- E 类别拖拽：「3」拖到「4」之上，DOM 与 localStorage 均持久化。
- F 卡片跨组拖拽：1Z 卡片拖入 1S，状态完整一致。

## 影响面
- 仅 `ui/ui_v2.html`；`app/**`、`skill/**`、`golden/**` 零改动，无需重跑模型。
- localStorage 结构向后兼容（旧 state 自动迁移），用户浏览器下次打开即生效。
- UI 哈希：before 见 `ui_v2.before.sha256`，after 见 `EVIDENCE_MANIFEST.json`；
  改动前副本 `ui_v2.before.html`。
