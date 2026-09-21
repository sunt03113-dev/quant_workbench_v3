# Quant Workbench｜冻结产品需求 v1

## 当前开发范围
本轮只完整开发「量化模型 / 回测」。大盘分析、题材分析、个股分析仅保留一级入口，不开发内部功能。

## 用户主流程
打开工作台 → 创建/选择模型卡片 → 输入或修改一条“完整自然语言规则” → 提交 → WorkBuddy 使用 tdx-stock-backtest Skill 执行真实数据提取/回测 → 返回结构化结果和 Excel → UI 展示当前成功结果前 10 条并支持下载。

## 模型卡片
每张卡片至少具有：模型名称、当前完整规则、运行状态、当前成功结果、上一个成功结果、最近成功时间、行情截止日期、命中数量、新增股票、最近错误。空卡片不得自动执行。

## 成功结果轮换
仅成功运行改变成功结果：previous_result = 原 current_result；current_result = 新成功结果。失败不得覆盖 current_result 或 previous_result。

## 结果展示
“10 条结果”指 current_result 的前 10 行，不是 10 次历史运行。完整结果通过 Excel 下载。0 命中是合法成功结果，不得视为系统失败。

## 持久化
浏览器、WorkBuddy 或本地应用重启后，模型卡片、完整规则、current/previous、最近状态、data_date、新增股票信息仍应存在。具体持久化技术由 WorkBuddy 决定。

## 数据更新
产品必须支持主动更新和自动保持行情更新。运行回测前必须明确本地行情截止日期；不得把不完整行情伪装为最新完整交易日。具体 Provider 和调度技术不冻结。

## 新增股票
新一次成功结果与旧 current_result 比较；new_hits = new current - old current。存在新增股票时模型卡片绿色高亮并显示股票名称。失败运行不参与 diff。

## 最终交付
开发环境为 Windows；最终生产环境为 Apple Silicon M4 macOS。最终目标是老板日常使用不依赖开发者手工维护，不要求安装 Windows 通达信、修改源码路径、配置 Python 开发环境或每日手工复制数据。
