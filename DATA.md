# Quant Workbench｜行情数据契约 v1

## 总原则
数据架构只冻结一个边界：`Market Data Provider → 标准化/校验 → 标准本地行情 → tdx-stock-backtest Skill`。

增量 Provider 当前不写死为 Tushare。WorkBuddy 必须实测当前环境中可用的 TDX/通达信 MCP、金融 MCP/Connector 或其他 Provider；不能只看名称判断可用。

## 历史基线
当前 Windows 上已有 TDX 全量历史数据，可作为一次性历史导入来源。最终 M4 产品不得依赖 Windows 通达信安装、vipdoc 绝对路径或 D:\ 路径。应转换/导入为跨 Windows/macOS 的标准本地行情资产。大体量行情数据与代码/Git 分离。

## 标准本地行情最低 Schema
每条日线记录至少必须具备：
- `symbol`：规范化股票代码，且可区分交易所；
- `trade_date`：交易日，YYYY-MM-DD 或等价稳定日期类型；
- `open`；
- `high`；
- `low`；
- `close`；
- `pre_close`；
- `volume`；
- `amount`。

还必须能够提供 Skill 实际判断所需的证券属性，例如：交易所/板块、ST 状态、上市日期或新股状态等。具体字段可拆到 security master，但不能缺失 Skill 真正依赖的信息。

## 数据语义必须冻结/记录
Provider 接入前必须实际确认并记录：
- 价格是否复权；当前冻结口径为不复权；
- volume 单位；
- amount 单位；
- pre_close 语义；
- 股票代码/交易所映射；
- ST/板块/上市状态来源；
- 停牌日如何表示；
- 交易日历来源；
- 数据更新时间与“完整交易日”的判断方式。

字段名称相同但语义/单位未验证，视为 Provider 不可用。

## Provider 硬性验收
STEP 1 不允许只查看 MCP/Connector 名称或说明。候选 Provider 必须实际调用样本数据，并保存原始响应样例/字段清单/时间范围证据。

至少对若干真实股票和多个交易日验证上述最低 schema、单位、日期、证券属性和数据完整性。任何 Skill 必需字段无法可靠获得时，该 Provider 不得进入生产回测链。

## 增量更新
检查本地最新完整交易日 → 获取缺失交易日 → schema/单位/完整性校验 → 去重 → 按 symbol+trade_date 唯一写入 → 更新 data_date。

Provider 失败或数据不完整时：不得破坏历史基线，不得推进 data_date，不得触发会覆盖成功结果的错误回测。

## 初始化部署数据包
历史行情可以作为独立部署资产随首次部署提供，但是否允许分发必须在最终确定数据来源后核对相应授权/许可。部署包应记录数据版本、截止交易日、记录数和文件哈希。
