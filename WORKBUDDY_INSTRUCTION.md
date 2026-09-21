# 给 WorkBuddy 的总开发指令

你负责从零完整开发 Quant Workbench 当前版本。这是新的开发工作区，不要恢复任何旧 CodeBuddy/V1/V2 架构。

## 先读取并冻结输入
完整阅读：PRODUCT.md、BUSINESS.md、DATA.md、ACCEPTANCE.md、CONSTRAINTS.md，以及 ui/、skill/、golden/、历史行情资产。

这些是冻结基线。工程实现由你决定，产品行为/业务定义/Golden 不由你改写。

## 当前范围
只完整开发「量化模型 / 回测」。大盘分析、题材分析、个股分析只保留入口。

完整闭环：UI模型卡片 → 完整自然语言规则 → WorkBuddy → tdx-stock-backtest Skill → 最新完整标准行情 → 回测 → 结构化结果 + Excel → 持久化 → current/previous → 前10条预览 → 主动/自动数据更新 → 新旧成功结果 diff → 新增股票绿色高亮。

## STEP 1：环境与数据能力必须“实测”，禁止只看名字
检查当前 WorkBuddy 实际可用的 Skill、MCP、Connector、自动化和金融数据能力。

对于任何候选 Market Data Provider（包括名称中出现 TDX/通达信/行情/金融的数据能力）：
1. 列出真实可调用 tool/action；
2. 实际调用样本，不得只阅读名称/说明；
3. 保存原始样本响应或可复核摘要；
4. 验证 DATA.md 最低 schema；
5. 验证复权口径、volume/amount单位、pre_close、交易日、股票代码映射、ST/板块/上市状态、时间范围和更新时效；
6. 明确哪些 Skill 必需字段能够/不能够获得。

只有上述实测通过，Provider 才可进入生产方案。字段不完整或语义未确认时，不允许“先硬跑”。

增量 Provider 当前不写死 Tushare。优先复用 WorkBuddy 中实际验证可满足要求的现成能力；不满足再提出最小备选。

STEP 1 输出必须附验证记录位置，不能只有文字结论。

## STEP 2：历史行情标准化 + 第一条纵向 E2E
现有 Windows TDX 全量历史数据只作为历史导入来源。建立最小跨平台标准本地行情，使最终 M4 不依赖 Windows 通达信或 D:\ 路径。

标准行情至少满足 DATA.md 的最低 schema，并补齐 Skill 实际需要的证券属性。物理格式由你选择，不要过度设计。

随后立即跑：UI → 自然语言 → WorkBuddy → Skill → 标准历史行情 → 回测 → 结构化结果 → Excel → UI。

## STEP 3：Golden 硬门禁
使用 golden/ 中固定规则、固定测试行情和正确输出做逐字段一致性比较。

如果 Golden、Skill、当前实现之间出现冲突：
- 立即停止该链路；
- 不修改 Golden；
- 不修改 Skill；
- 不放宽比较标准；
- 生成 conflict report，记录文件、版本/哈希、差异和影响；
- 等待用户确认。

Golden 未 PASS，不开发外围功能。

## STEP 4：完整产品行为
Golden PASS 后补齐：持久化、current/previous、失败保护、前10条预览、Excel下载、diff、新增股票提醒。

## STEP 5：增量 Provider 与更新
使用 STEP 1 已实测合格的 Provider。流程必须经过标准化/校验后写入标准本地行情；Skill 不得直接绑定具体 Provider。

实现主动更新和自动保持更新。调度方式由你根据 WorkBuddy 实际能力选择最小可靠方案，不预先写死 17:05 本地 Scheduler 或 Tushare。

## STEP 6：Windows 完整验收
逐项执行 ACCEPTANCE.md。每项必须留下机器可复核 artifacts。

## STEP 7：M4 迁移
准备最终部署资产：工作台、UI、Skill、必要运行组件、初始化历史行情数据包、产品状态初始化、Provider配置方式、启动方式。

在 Apple Silicon M4 使用同一固定测试输入重新执行 Golden。

必须记录 Windows/M4 两端：Skill/Golden/测试行情 SHA-256、代码 commit、运行时与依赖版本、标准行情 schema/version、结果哈希和 canonical diff。输入资产不一致不得宣称跨平台一致性；业务输出 diff 非 0 不得 PASS。

## 工程权限
你可以自行决定 Backend、持久化、MCP/Connector、API、标准行情物理格式、调度和最终打包方式。原则是满足冻结需求的最小可靠实现。

未经真实验收失败证明，不要增加第二套 Agent、多 Agent、Planner/Reviewer、自定义 DSL、第二套规则引擎、微服务、Redis、消息队列、向量数据库或知识图谱。

## 汇报与证据规则
每个阶段只汇报：
1. 完成内容；
2. 实际执行的测试/调用；
3. PASS/FAIL；
4. 可验证记录路径（日志、manifest、hash、diff、样本响应、测试报告）；
5. 真实阻塞；
6. 下一步。

没有可验证记录，不得写“已验证”“已通过”“已完成”。

只有以下情况向用户确认：改变冻结产品行为；改变 Skill 业务定义；Golden/Skill真实冲突；数据源无法满足必需字段；WorkBuddy实际能力与假设不同；跨平台存在无法绕过的限制。普通工程实现自行决定。

现在开始。
