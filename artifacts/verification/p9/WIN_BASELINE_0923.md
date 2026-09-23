# P9 Windows 端基线（2026-09-23 重采）

> 用途：M4 回传 `artifacts/verification/p9/mac/` 后，用本页数值即可肉眼初判；
> 正式判定以 `python app/p9_compare.py --left win --right mac` 为准。
> 旧证据（step8 期：行情止 09-21、10cm 旧口径）已归档 `p9/archive/win_step8/`。

## 采集结果（`p9/collect_win_0923.log`）
- 环境：Windows/AMD64，py 3.13.14，numpy 2.5.3，pandas 3.0.6
- P0 全 26 规则：**耗时 131.3s，总行数 7849**
- Excel 探针：`structured_rows_sha256 = 25c57e5e5b7a3917…`（后端真实回测产出，未 skipped）

## 输入资产哈希（M4 必须逐项一致，否则 P9 第一道关 ABORT）

| 资产 | n | tree_hash（sha256） |
|---|---|---|
| skill（冻结业务定义） | 53 | `2443c6208aaf6007db2718ba5369ae4c89e2753d8d152afe7bf4ba84c74d552b` |
| golden（规则+期望结果表） | 58 | `606d714f98042fa7397668eb79112d8e976196fc506f3bbfbd755e5c3564c40c` |
| market_pack（.day 行情） | 11704 | `7a7d3571891217ef4959b9e4de2572f72cf402ccf88653ab43251f8f6acd9019` |
| stock_names.csv | 1 | sha256 `aa21e8ef9140efee…`，size 171943 |

> `index_last_trade_date = 2026-07-16` 是**已知正常**：工作台指数文件（sh000xxx/sz399xxx）
> 不参与每日增量更新，该字段仅记录、非业务输出；两端同包必然一致。

## 26 规则判定（win 端）
- **PASS**：0824(2142) / 0827A(954) / 0909A(139) / 0911(100) / 0912(188) / 0913A(52) /
  0913B(12) / 0915A(78) / 0915B(41) / 0915C(14) / 0917A(16) / 0917B(53) / 0917C(250) /
  0917D(27) / 0917E(155) / 0918A(1018) / 0918B(1488) ← 共 17 条
- **PASS_WITH_KNOWN_T0_CONFLICT**（T+0 取整方向已知冲突豁免，与 Skill 侧台账一致）：
  0818A / 0818B / 0822 / 0827B / 0908 / 0908B / 0908C / 0910A ← 共 8 条
- **CAPABILITY_GAP**：0814（能力缺口用例，预期）
- 10cm 三例（0824/0827A/0909A）由改动前的 CONFLICT **转为 PASS** —— 本轮改动的直接证据。

## 比对器自校验（`p9/selfcheck_win_0923.log`）
`--left win --right win` → 输入门 PASS、26 规则 diff=0/26、**VERDICT = PASS**
（证明比对器在"同一份输入"下不会假报差异 → 跨端出现差异即为真差异）

## M4 侧待执行
```bash
./deploy/bootstrap.sh setup
./deploy/bootstrap.sh serve                 # 另开终端保持运行（Excel 探针依赖后端）
./deploy/bootstrap.sh p9 collect --label mac
# 回传 artifacts/verification/p9/mac/ 整个目录
```
Windows 端收件后：`python app/p9_compare.py --left win --right mac`
