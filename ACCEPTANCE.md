# Quant Workbench｜验收基线 v1

## P0 Golden 一致性（最高优先级）
使用随包提供的固定自然语言规则、固定测试行情和 Golden 输出，通过真实 UI → WorkBuddy → Skill → 行情 → 回测链执行。

逐项比较：命中数量、股票代码、事件/基准日期、列集合及列顺序、所有输出值、行排序。不得只比较“看起来差不多”。

Golden/Skill/实现发生冲突时立即 FAIL-CLOSED：不得修改 Golden、不得修改 Skill、不得放宽比较器。生成 conflict report 后等待用户确认。

## P1 真实入口
必须从 UI 输入完整自然语言规则完成 E2E，不得仅以手工 Python 脚本通过代替。

## P2 Excel 与结构化结果
成功回测同时产生可供 UI 使用的结构化结果和完整可打开 Excel。UI 展示 current_result 前 10 行；0 命中合法。

## P3 持久化
成功运行后关闭并重新启动相关环境，规则、current_result、previous_result、data_date 等仍存在。

## P4 结果轮换与失败保护
连续两次成功后 current=第二次、previous=第一次。随后制造一次失败，current/previous 均不得改变，规则文本保留，错误可见。

## P5 数据 Provider 实测
不得以“发现某 MCP/Connector”作为 PASS。必须保存真实工具调用、样本响应、字段映射、单位/复权/时间范围/证券属性验证记录。缺少 Skill 必需字段即 FAIL。

## P6 增量数据
从已知 data_date 补充至少一个新交易日，验证去重、排序、schema、单位、完整性以及 data_date 正确推进。模拟 Provider 失败时历史数据与成功结果保持不变。

## P7 主动/自动更新
主动更新可用；自动保持更新可用。具体技术不限。非交易日或当日数据尚不完整时不得生成伪“最新完整数据”。

## P8 新增股票
old=A/B/C，new=A/B/C/D 时，D 被识别为 new_hit，卡片绿色高亮并显示名称。

## P9 Windows → M4 一致性
Windows 全量验收通过后，在 Apple Silicon M4 使用同一 Skill、同一 Golden 规则、同一固定测试行情再次执行 P0。

必须保存两端：
- Git commit（如有）；
- Skill 目录/关键文件 SHA-256；
- Golden 文件 SHA-256；
- 固定测试行情包 SHA-256；
- 标准行情 schema/version；
- Python/运行时版本；
- 关键依赖 lock/版本；
- 运行命令或启动方式；
- 结果 Excel SHA-256；
- 结构化结果 canonical diff。

跨平台 PASS 条件：输入资产哈希一致，业务输出 canonical diff 为 0。若 Excel 文件因元数据导致二进制哈希不同，不可仅凭 Excel SHA 判失败；必须比较规范化后的业务内容，并记录二进制哈希差异。

## 可验证记录
每项验收必须在 `artifacts/verification/<run_id>/` 或等价目录留下机器可复核记录，例如 manifest、日志、输入/输出哈希、diff、测试报告和必要样本。口头“已通过”不算验收证据。
