# Quant Workbench｜开发与交付约束 v1

## Agent 与架构
WorkBuddy 是本产品唯一通用 Agent。不要再造第二套 Agent、多 Agent、Planner/Reviewer Agent、自定义 DSL、第二套量化规则引擎，除非某条真实验收无法通过且有证据证明需要。

工程实现由 WorkBuddy 自主选择：目录、Backend、持久化、MCP/Connector、API、标准行情物理格式、调度、打包方式均不预先写死。

每增加一个重要架构层，必须能指出它解决的具体产品需求或失败验收项，否则不增加。

## 跨平台
Windows 开发，Apple Silicon M4 macOS 生产。禁止无必要硬编码 C:/D:/、vipdoc 绝对路径、cmd.exe、.bat 或 Windows 专属组件。路径必须来自配置或平台应用数据目录。

## 最终用户体验
最终老板日常使用不应需要：安装 Windows 通达信、手工维护 vipdoc、修改源码、配置 Python 开发环境、每天复制行情、手工启动多个终端服务。

## Secret
任何 Token/API Key 不得进入源码、Git、日志、README、Golden 或可分发安装包。具体安全配置方式由实际 Provider/WorkBuddy 能力决定。

## 证据优先
不得把“代码已写”“工具已发现”“接口返回 200”“WorkBuddy 说成功”当作业务验收。以 ACCEPTANCE.md 的真实 E2E 和可验证 artifacts 为准。
