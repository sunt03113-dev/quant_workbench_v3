# CHANGES —— 10cm 口径裁定全链路（kk 2026-09-23 裁定 + 开工执行）

## 裁定内容（唯一事实源）
1. **10cm 池纳入创业板 10% 时代**：`sz300/301` 进入 10cm 池，仅限信号日 < `GEM_20CM_DATE = 20200824`
   （反向门：信号日 ≥ 2020-08-24 的 300/301 一律排除，彼时创业板已改 20% 制度）。
2. **688 仍不进 10cm**（科创板任何时代都是 20%）。
3. **`universe="both"` 改为各板块全时代并集**：不再有任何门槛；limit flags 由
   `compute_limit_flags` 按日期自动分段（300/301 在 2020-08-24 前 10%、之后 20%）。
4. **方案A：skill + app 双实现同步改**——skill 三个 10cm 规则脚本按新口径改写后重跑生成新
   golden，保留双实现独立性；app executor 改为同口径，golden_test 逐位对账。

## 变更文件（旧版全部有备份 + 哈希）
| 文件 | 变更 | 备份 |
|---|---|---|
| `app/executor.py` | `_collect_stock_files` 10cm 收 300/301；变量日/固定/链式三条路径加反向门；`validate_rows` 加 `BOARD_DATE_FILTER` 抽验 | `executor.before.py` + `.sha256` |
| `skill/.../0824_backtest.py` | `compute_limit_flags(code)` 分段判定 + collect 收 300/301 + `np.searchsorted` 反向门 | `skill_backup/` + `before.sha256` |
| `skill/.../0827A_backtest.py` | 同上 | 同上 |
| `skill/.../0909A_backtest.py` | 同上 | 同上 |
| `app/ask.py` | 构成核查意图（`_answer_composition`）+ 10cm×创业板/universe 文案同步新口径 | git eb9f746 及本轮 |
| `golden/0824_backtest/`、`0827A_backtest/`、`0909A_backtest/` | CSV(+xlsx) 以 skill 新口径输出替换 | `golden_backup/` + `before_manifest.json` |
| `deploy/M4_DEPLOY_INSTRUCTION.md` | 新包哈希、行情截止 09-22、10cm 裁定版本说明 | git 历史 |

> 铁律遵守：golden/Skill 改动仅因 kk 显式裁定（方案A），走登记 + 备份 + 哈希；比较器零改动。

## 影响量化（monkeypatch 探针，`impact_probe.py` / `impact_estimate.json`）
- 0824：老 golden 1980 行 → 新 2142 行（+166；其中 163 行为创业板 10% 时代，3 行为数据演化漂移）。
- 0827A：870 → 954（+85，全部为创业板 10% 时代）。
- 0909A：老 golden 10 行（CONFLICT 陈旧态）→ 新 139 行（+9 创业板 10% 时代，其余为主板数据演化修复）。
- **反向门必要性**：无门控时 20% 时代的 300/301 假命中达 249/163/13 行（按各脚本实测），已全部阻断。

## 双实现一致性验证
- skill 新口径输出 vs app 新引擎：0824 / 0827A / 0909A 三例 **逐位一致**
  （`new_csv_stats.json`、`keydiff_new_vs_old.json`）。
- `golden_test` 全量 26 例（`golden_test_run.txt`）：0824 / 0827A / 0909A 由改动前的
  **CONFLICT（数据演化漂移）修为 PASS**；其余 23 例判定零变化。

## 12 个 10cm 模型手动重跑（`rerun_10cm_models.py` / `rerun_report.json`）
范式：`run_plan → validate_rows → save_success_result`，失败 fail-closed 保留旧结果。
**12/12 成功，复核 0 违例**：

| 模型 | 行数 old → new |
|---|---|
| strategy_1z1a_r1_v1 | 137 → 146 |
| strategy_13b34ebf3a_v1 | 330 → 377 |
| strategy_f120ccad35_v1 | 51 → 55 |
| strategy_676e25bb91_v1 | 51 → 55 |
| strategy_23e908c510_v1 | 254 → 297 |
| strategy_99b11761e0_v1 | 51 → 55 |
| strategy_ed26408c68_v1 | 254 → 297 |
| strategy_111a_r1_v1 | 722 → 805 |
| strategy_111b_r1_v1 | 388 → 436 |
| strategy_121_r1_v1 | 388 → 436 |
| 111B_verify_0922 | 388 → 436 |
| strategy_10cm_v6 | 574 → 622 |

## 行情包（先决条件，随本轮重打）
- `dist/qwb_market_pack_20260923.zip`：11705 文件，原始 931.0 MB / zip 932.9 MB，
  sha256 `c7f8d78d9cca9c93c671a99c0ac2d2a5c6ad9ca027822da384dcba9fd804afd8`
  （`dist/SHA256SUMS_market_20260923.txt`）；行情数据截止 **2026-09-22**。

## 发包
- `dist/qwb_m4_deploy_20260923.zip`（302+ 文件，含本轮 executor/skill/golden/ask 变更与
  `gem10_ruling/CHANGES.md`）；校验见 `dist/SHA256SUMS_20260923.txt`。
- 旧代码包 `qwb_m4_deploy_20260921.zip` **作废**（其内 golden/池口径已过时）。

## 未做 / 后续
- git push 需 kk 手动（沙箱拒读 .ssh）；本地积压含 `54ffc1e` `53cb3c1` `eb9f746` + 本轮提交。
- M4 右端验收待跑（bootstrap.sh setup + p9 collect）。
- Defender 给 vipdoc 加排除项（落盘 44ms/文件是增量瓶颈）仍待办。
