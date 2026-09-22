# 「询问模型」入口实装记录（2026-09-22 22:15）

## 改动范围（与定稿口径一致：产品层仅此一处，底层零新增业务结构）

| 文件 | 改动 | 状态 |
|---|---|---|
| `ui/ui_v2.html` | 详情页「示例数据」面板头部新增 **`? 询问模型`** 按钮 + `buildAskText`/点击处理（组装结构化质询 → 写剪贴板；剪贴板不可用时 prompt 兜底）；无 stem 的卡片自动隐藏 | **已实施** |
| `artifacts/verification/capability_probe/ask_model.py` | 新增核验工具（参数化探针）：`--stem/--model --code/--date/--query`；只调现有 `store.get_rule` + `_collect_stock_files` + `read_day_file` + `compute_limit_flags`/`is_limit_up_sealed_decimal`/`rolling_max20` + 原样 `run_plan`（monkeypatch 收窄单股）+ `validate_rows` + 结果表逐日期比对 | **已实施**（artifacts 下工具，非引擎） |
| `app/**`、`skill/**`、`golden/**` | **零改动** | — |
| 后端 API | **零新增**（无 diagnose、无 capabilities） | — |

## UI 变更哈希（冻结基准留证）
- before：`f63bbad22c2bcd15dbf52813823a0be90c575cf20d40504fa2b06799375c71a6`（= `ui_v2.before.html` 副本哈希，一致）
- after：`cbffc3dfecf720948f74dcc447f45f69a359ba7d70c8cb795c77313e31de075b`
- 完整清单：`EVIDENCE_MANIFEST.json`

## 「询问模型」按钮行为
1. 详情页点击 → prompt 输入质询对象（如 `688037 20200117`，可留空对整模型提问；支持中文名）。
2. 组装文本：`【工作台质询】` + 模型名 + stem + 质询对象 + **完整规则原文** + 四条核验要求
   （现有能力核验 / 返回实际数值 / 不一致只报异常不自行解释 / 只读不改数据规则引擎）。
3. 写入剪贴板 → 用户粘贴给 WorkBuddy 主 Agent；WorkBuddy 侧用 `ask_model.py` 同路径核验。
4. 判定权识别器/执行器/Skill；本按钮**不做任何判定**。

## ask_model.py 验收（三用例，报告 JSON 同目录）

| 用例 | 命令 | 预期 | 结果 |
|---|---|---|---|
| 10cm 池外 | `--model 121_r1_v1 --query "芯源微 688037 20200117"` | 不在池 → 属预期，无该股 | ✅ `ask_strategy_121_r1_v1_20260922_220703.json` |
| 20cm 命中日 | `--model c1789895695594 --code 688037 --date 20200116` | 封板（收=高=94.0=涨停价）→ 重跑 7 命中 == 结果表 7 行，consistency=OK | ✅ `ask_strategy_c1789895695594_r1_v1_20260922_220842.json` |
| 20cm 未封板日 | `--model c1789895695594 --code 688037 --date 20200117` | 未封死涨停（收 102.8/高 109.8 vs 涨停价 112.8）→ 不是遗漏，附近 20 日极值与前 5 日涨停事实 | ✅ `ask_strategy_c1789895695594_r1_v1_20260922_220935.json` |

三例 `validate_rows` 复核均 0 违例；只读，未触碰 `current/previous`。

## UI 验收（playwright-core + 系统 Edge，headless，证据同目录）

| 检查 | 结果 |
|---|---|
| 首页加载 + 卡片存在（`step1_home.png`） | ✅ |
| 打开卡片详情后「询问模型」按钮可见（`step2_detail.png`） | ✅ |
| 点击弹出质询对象输入框（prompt 文本留证 `prompt_text.txt`） | ✅ |
| 接受输入后质询全文写入剪贴板，含 `stem：…`（`clipboard_text.txt`） | ✅ |

结果 JSON：`ui_verify_results.json`（4/4 PASS）。脚本：`ui_verify.js`（`--stem` 自动取第一个带结果的卡片）。

## 回滚
```powershell
Copy-Item artifacts\verification\ui_ask_entry\ui_v2.before.html ui\ui_v2.html -Force
# 回滚后哈希应 = f63bbad2…
```

## 备注
- 本轮未动后端，部署包**代码包无需重打此改动之外的内容**；M4 交付前仍需重打行情包（09-22 已落后，见交接记录）。
- M4 侧使用同一工具链：`bootstrap.sh setup` 建 venv 后即可运行 `ask_model.py`；按钮产出的质询文本同样粘给 WorkBuddy。
- 数据来源：通达信本地 vipdoc 日线（截止 2026-09-22）。本记录为工程说明，不构成投资建议。
