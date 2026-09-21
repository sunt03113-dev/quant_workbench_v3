# 每日增量更新提速 + UI 卡死修复 + 调度时间提前（2026-09-21）

## 问题（kk 16:28 报告：首页一直显示「正在更新…」）
1. 手动更新任务 `347dd6b25ab5`（16:07 发起）在「抓取 5544 个标的」阶段实际爬行：
   21 分钟不足 500 只，60 秒观测窗口零进度。根因 = 东财 push2his kline 逐只请求
   （5544 次 × 6 并发）触发整站限流（RemoteDisconnected；`_http_json` 5 镜像 × 5 次
   退避重试放大为每只最坏 ~100s）→ 单轮行情增量可达数小时。
2. 16:45 起 Windows **Smart App Control 转为强制开启**（事件日志 1381，VerifiedAndReputable
   PolicyState=1），拦截 pandas `_libs/join.pyd` → 后端/冒烟测试均无法再启动（numpy 正常、
   pandas 被拦）。**环境级阻塞，待 kk 关闭 SAC 后做端到端实测**。

## 修复（app/provider.py、app/server.py、ui/ui_v2.html、app/step6_test.py）
- **快照快速路径**（provider.py）：单日增量 + 该日=今天 + 已过 15:05（SNAPSHOT_EARLIEST）+
  主源为东财 → 走东财 push2 clist 全A批量快照（100 只/页，约 56 请求替代 5544 请求）。
  停牌股（f2='-'）自动缺失，与 kline 路径「当日无 bar 不写」语义一致；任何分页失败自动
  回退逐只 kline 路径；多日缺口/盘中/force_beg 强制重建不走快照。
- **调度时间 17:05 → 15:45**（server.py SCHEDULE_HOUR/MIN）：主源东财日线收盘（15:00）后
  即定型，不依赖 tushare 15~16 点入库窗口。启动补偿逻辑同步生效。
- **UI 卡死修复**（ui_v2.html）：更新按钮轮询 catch 分支原先只 clearInterval 不恢复按钮，
  后端重启/断网后永远停在「正在更新…」→ 现在恢复按钮并 toast 提示。备份
  `ui/ui_v2.before_dailyui.html`。
- step6_test.py T4 改读 server.SCHEDULE_HOUR/MIN（不再硬编码 17:05）。

## 验证
- 代码备份：provider.v1.baseline.py（修改前 SHA 见 provider_before.sha256）。
- 离线单测 PASS：mock 快照 → `_snapshot_plan` 记录换算（分/元/股口径）、停牌跳过、
  未写文件不动，均正确。
- 快照 vs kline 双源交叉验证：**待 SAC 解除后补做**（东财限流冷却 + SAC 拦截两重阻塞）。
- 全量每日管线实测耗时：**待 SAC 解除后补测**。

## 回答 kk 的时序问题（依据）
- 东财主源日线收盘（15:00）后定型，无 tushare 15~16 点入库约束 → 一键更新最早约
  15:30-15:45 可拿全当日增量；保守 16:00。
- 快照路径行情阶段预计 <2 分钟（56 请求）；模型重跑约 40 个 ≈ 1-3 分钟（golden 26 条
  全历史回测实测 40s）；单次全管线预计 3-5 分钟（待实测确认）。
