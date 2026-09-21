# Quant Workbench｜冻结业务边界 v1

## 唯一权威来源
tdx-stock-backtest Skill 是量化业务定义的唯一权威来源。本文不复制量化公式，避免形成第二套定义。

## WorkBuddy 可以做
- 理解用户自然语言意图；
- 使用 Skill；
- 调用必要的数据/工具；
- 执行回测任务；
- 返回、解释和展示结果。

## WorkBuddy 不可以做
- 修改或重定义 Skill 中的冻结业务规则；
- 在 UI、Backend、Prompt、数据层再复制一套公式；
- 静默忽略用户条件；
- 用“相似规则”替换未支持规则；
- 为了测试通过修改 Golden 或 Skill。

## 不支持能力
若自然语言包含 Skill 尚未支持的业务能力，应明确返回缺少能力/待补能力，不得猜测实现。

## 业务能力事实来源
随包提供的 `docs/SOURCE_business_baseline_README.md` 是此前冻结业务基线的参考索引；真正执行定义仍以实际交付的 tdx-stock-backtest Skill 为准。

## 冲突处理
若 Skill、Golden、产品文档出现冲突：立即停止该测试并记录冲突证据，不允许自行修改任何一方来“跑通”。向用户报告：冲突文件、版本/哈希、具体差异、影响范围，等待确认。
