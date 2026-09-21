# 交付资料清单

## 已整理
- PRODUCT.md：冻结产品需求
- BUSINESS.md：业务定义边界
- DATA.md：历史全量 + 可替换增量 Provider + 最低 schema/实测门禁
- ACCEPTANCE.md：Golden、Provider、持久化、更新、Windows→M4 验收与证据要求
- CONSTRAINTS.md：工程/跨平台/安全边界
- WORKBUDDY_INSTRUCTION.md：直接发送给 WorkBuddy 的总开发指令
- ui/ui_v2.html：当前会话中已有的 UI 基准副本
- docs/SOURCE_business_baseline_README.md：当前会话中已有的冻结业务基线索引副本

## 仍需你从本地补入，不能由文档猜造
1. `skill/tdx-stock-backtest/`：最终冻结 Skill 完整目录。
2. `golden/`：最终 Golden 包，至少包含固定自然语言规则、正确结果 Excel、固定测试行情/其不可变版本说明；以真实文件为准。
3. `market_seed/`（建议目录名）：TDX 全量历史数据或转换前源数据。大文件不要进 Git。
4. 若 UI 基准以你本地更新版为准，请用最终本地版覆盖 `ui/ui_v2.html`。

## 开发开始前建议生成 BASELINE_MANIFEST.json
对以下输入生成 SHA-256：
- UI 基准
- Skill 关键文件/目录清单
- Golden 文件
- 固定测试行情
并记录生成时间、文件大小、版本/commit（若有）。之后任何基线变化都必须显式记录。

---

## 开发完成后已就位（STEP 1–8）

### 应用代码 `app/`
| 文件 | 职责 |
|---|---|
| `paths.py` | 路径层：环境变量 > `app/config.yaml` > 平台默认应用数据目录；记录每个路径的解析来源 |
| `recognizer.py` | 自然语言规则 → plan schema；不支持的表达 fail-closed |
| `executor.py` | 调 Skill 业务原子执行回测（零业务公式），带确定性复核 |
| `store.py` | 模型卡片、current/previous 轮换、失败保护、损坏恢复 |
| `server.py` | FastAPI 后端，托管冻结 UI |
| `provider.py` | 双源增量 Provider（东财主源 / 雪球备源），标准化后追加标准行情 |
| `build_stock_names.py` | 股票名称缓存构建 |
| `p9_evidence.py` | **P9 跨平台证据采集**（任一端运行） |
| `p9_compare.py` | **P9 双端判定**（输入哈希一致 + 业务 canonical diff = 0） |
| `p9_selfcheck.py` | **比对器自校验**（正向 / 负向 / 输入门禁三用例） |
| `golden_test.py` / `step*_test.py` / `step7_*.py` | 各阶段验证脚本 |

### 部署 `deploy/`
- `README_DEPLOY.md`：M4 部署与 P9 操作手册（含故障排查）
- `bootstrap.sh`：`setup` / `check` / `serve` / `p9` 四个子命令
- `requirements.txt` / `requirements.lock.win.txt`：依赖清单与 Windows 完整冻结
- `config.example.yaml`：跨平台配置模板（**无盘符**）

### 验证记录
`artifacts/verification/{step1…step7_win_acceptance,p9}/`：manifest、日志、
输入/输出哈希、diff、测试报告与必要样本。口头结论不算证据。

### 分发注意
`app/config.yaml` 含开发机绝对路径，**不得随分发包传递**；
最终用户环境用环境变量 `QWB_APPDATA_DIR` / `QWB_SKILL_DIR` / `QWB_UI_FILE`
或平台默认应用数据目录（macOS: `~/Library/Application Support/QuantWorkbench`）。
