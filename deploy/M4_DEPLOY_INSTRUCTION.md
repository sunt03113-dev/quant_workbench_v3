# 给 M4 WorkBuddy 的部署指令（直接粘贴本文件内容即可）

你是 Mac（Apple Silicon M4）上的 WorkBuddy。用户交给你一个 Quant Workbench 部署包，
请按以下步骤完成部署并回传验收证据。**不要修改 `skill/`、`golden/`（除 vipdoc 外）、
`ui/ui_v2.html` 的任何内容**——它们是冻结基线。

## 包内容
- `qwb_m4_deploy_20260921.zip` —— 代码 + Skill + UI + Golden 结果表 + 部署脚本（约 15MB）
- `qwb_market_pack_20260921.zip` —— 标准本地行情包 `appdata/market` + `stock_names.csv`
  （约 900MB，解压后约 890MB / 11700 个 .day 文件；数据截止 2026-09-18）

## 部署步骤
```bash
# 1. 解压两个包到同一目录（保持相对结构）
mkdir -p ~/quant_workbench_package && cd ~/quant_workbench_package
unzip -q ~/Downloads/qwb_m4_deploy_20260921.zip -d .
unzip -q ~/Downloads/qwb_market_pack_20260921.zip -d .   # 解出 appdata/market 与 stock_names.csv

# 2. 环境变量指路（不要创建 app/config.yaml；开发机配置不得随包传递）
export QWB_APPDATA_DIR="$PWD/appdata"
export QWB_SKILL_DIR="$PWD/skill/tdx-stock-backtest-master"
export QWB_UI_FILE="$PWD/ui/ui_v2.html"

# 3. 建 venv + 装依赖 + 自检
chmod +x deploy/bootstrap.sh
./deploy/bootstrap.sh setup

# 4. 启动后端（前台即可；Ctrl+C 停止）
./deploy/bootstrap.sh serve
#   浏览器打开 http://127.0.0.1:8000
```

## 部署后验收（依次执行，全部留证）
1. `./deploy/bootstrap.sh check` —— 记录 Python 版本、依赖自检、paths.describe() 输出。
2. UI 打开 http://127.0.0.1:8000 ，用规则 `0921A`（ golden/rule.txt 中同名段落）跑一次回测，
   确认：能出结果、确定性复核通过（无 ROW_INVALID）、结果表「区间最大振幅」列为
   **纯数字（不带 %）**、「区间涨幅/区间振幅」列**带 %**。
3. P9 右端采集（需后端在另一终端保持运行）：
```bash
export QWB_APPDATA_DIR="$PWD/appdata"; export QWB_SKILL_DIR="$PWD/skill/tdx-stock-backtest-master"
export QWB_UI_FILE="$PWD/ui/ui_v2.html"
./deploy/bootstrap.sh p9 collect --label mac
```
   产出在 `artifacts/verification/p9/mac/`，**整个目录回传给 Windows 端**。

## 故障排查
见 `deploy/README_DEPLOY.md`（含 akshare 硬依赖、行情目录缺失、P9 ABORT/FAIL 的处置）。

## 版本
- 代码版本：git `main`，含修复「区间最大振幅不带 %」（2026-09-21）。
- 行情包 tree_hash 以包内 `appdata/market` 实测为准；两端必须一致（P9 第一道关）。
