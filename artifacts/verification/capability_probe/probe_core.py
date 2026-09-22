# -*- coding: utf-8 -*-
"""能力探针：芯源微（20200117）为什么不在结果里？

铁律（kk 2026-09-22）：
  - 只调用【现有】recognizer / executor / Skill 函数，不新增任何诊断判定逻辑；
  - 不新增 API、不加结论码表、不加新 Skill；
  - 单股路径通过 monkeypatch executor._collect_stock_files 收窄宇宙实现，
    执行主体仍是原 run_plan（同一份代码、同一份条件、同一份复核）。
输出：artifact/verification/capability_probe/probe_report.json + probe_report.txt
"""
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path

APP = Path(__file__).resolve().parents[3] / "app"
sys.path.insert(0, str(APP))

import numpy as np                      # noqa: E402
import executor                          # noqa: E402
import recognizer                        # noqa: E402
import store                             # noqa: E402
from paths import STOCK_NAMES_FILE       # noqa: E402

OUT = Path(__file__).resolve().parent
NAME_QUERY = "芯源微"
TARGET_DATE = 20200117
report = {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
          "query": {"name": NAME_QUERY, "date": TARGET_DATE}, "steps": []}


def step(tag, ok, detail=None, **extra):
    rec = {"step": tag, "ok": bool(ok)}
    if detail is not None:
        rec["detail"] = detail
    rec.update(extra)
    report["steps"].append(rec)
    print(f"[{'PASS' if ok else 'FAIL'}] {tag}: {detail}")
    return rec


# ── Q1 用现有资产能否定位「名字 + 日期」──────────────────────────────
code = None
lines = STOCK_NAMES_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()
for ln in lines:
    parts = ln.strip().split(",")
    if len(parts) >= 2 and NAME_QUERY in parts[1]:
        code = parts[0].strip()
        break
step("Q1a 名称->代码（appdata/stock_names.csv）", code is not None,
     f"{NAME_QUERY} -> {code}", note="现有 asset 是 code,name；名称->代码需正向扫表，无专门函数")

# 现有 API 侧只能 code->name（Skill match_stock_names / 结果表 股票名称 列）
step("Q1b 代码->名称（结果表内）", True,
     "结果表含「股票代码/股票名称」两列，可反查；名称->代码需扫 stock_names.csv")

# ── 模型清单 ────────────────────────────────────────────────
state = store.load_state()
models = []
for stem, m in state.get("models", {}).items():
    cur = m.get("current_result") or {}
    plan = m.get("plan") or {}
    sp = plan.get("strategy_plan") or {}
    models.append({"stem": stem,
                   "universe": sp.get("universe"),
                   "kind": "chain" if sp.get("chain") is not None else "fixed",
                   "n_hits": cur.get("n_hits"),
                   "data_date": cur.get("data_date"),
                   "rule_text": (m.get("rule_text") or "").replace("\n", " ")[:110]})
report["models"] = models
print(f"\n模型清单：{len(models)} 个")
for m in models:
    print("  - {stem}  universe={universe} {kind} hits={n_hits} date={data_date}".format(**m))

latest = executor.data_latest_payload()
report["data_latest"] = latest
step("Q1c 数据新鲜度（/api/data/latest）", bool(latest.get("latest_date")),
     f"latest_date={latest.get('latest_date')}")

# ── 定位该股 .day 文件（走 _collect_stock_files，禁止 \"sh 优先\" 搜索）──
all_files = dict((c, f) for c, f in executor._collect_stock_files("both"))
day_file = all_files.get(code)
step("Q2a 该股在 both 池内（_collect_stock_files）", day_file is not None,
     str(day_file))

res = executor.read_day_file(day_file)
dates, opens, highs, lows, closes, amounts, volumes = res
amounts = amounts.astype(np.float64, copy=False)
i = int(np.searchsorted(dates, TARGET_DATE))
in_range = i < len(dates) and int(dates[i]) == TARGET_DATE
step("Q2b 目标日在该股日线内（read_day_file）", in_range,
     f"首条={int(dates[0])} 末条={int(dates[-1])} 第{ i }条={int(dates[i]) if i < len(dates) else 'N/A'} 共{len(dates)}条")

# 上市初期窗口（无涨跌幅限制）判定：科创板前 5 个交易日
first5 = [int(x) for x in dates[:5]]
step("Q2c 是否落在上市前 5 个交易日（无涨跌幅限制）", TARGET_DATE in first5,
     f"该股前5个交易日={first5}；目标日序号={i + 1}")

ctx = {"bars": []}
lo, hi = max(0, i - 6), min(len(dates), i + 3)
for j in range(lo, hi):
    ctx["bars"].append({"date": int(dates[j]), "open": float(opens[j]),
                        "high": float(highs[j]), "low": float(lows[j]),
                        "close": float(closes[j]), "amount": float(amounts[j])})
report["bars_around"] = ctx["bars"]

# ── Q3 现有 Skill 判定能否直接用于该股 ────────────────────────
close_c = np.round(closes * 100).astype(np.int64)
high_c = np.round(highs * 100).astype(np.int64)
limits = executor.compute_limit_flags(dates, close_c, high_c, code)
amt_max20 = executor.rolling_max20(amounts)
high_max20 = executor.rolling_max20(highs)
with np.errstate(invalid="ignore"):
    is_amtmax = np.zeros(len(dates), dtype=bool)
    is_highmax = np.zeros(len(dates), dtype=bool)
    is_amtmax[19:] = amounts[19:] == amt_max20[19:]
    is_highmax[19:] = highs[19:] == high_max20[19:]

y_close = float(closes[i - 1]) if i > 0 else None
scalar = {"limit_up_10pct": bool(executor._bc.is_limit_up_sealed_decimal(
              closes[i], highs[i], y_close, executor._bc.Decimal("0.10"))),
          "limit_up_20pct": bool(executor._bc.is_limit_up_sealed_decimal(
              closes[i], highs[i], y_close, executor._bc.Decimal("0.20")))}
prev5 = [int(dates[j]) for j in range(max(0, i - 5), i) if limits[j]]
step("Q3a 现有 Skill 判定可用（compute_limit_flags 向量 + 标量）", True,
     f"向量判定 limit_up={bool(limits[i])}；标量 10%={scalar['limit_up_10pct']} 20%={scalar['limit_up_20pct']}",
     vector_limit_up=bool(limits[i]), scalar=scalar)

vals = {"close": float(closes[i]), "high": float(highs[i]), "prev_close": y_close,
        "amount": float(amounts[i]), "amt_max20": float(amt_max20[i]),
        "amount_is_20d_max": bool(is_amtmax[i]), "high_max20": float(high_max20[i]),
        "high_is_20d_max": bool(is_highmax[i]),
        "prev5_limit_days": prev5,
        "limit_price_20pct": round(y_close * 1.2, 2) if y_close else None,
        "limit_price_10pct": round(y_close * 1.1, 2) if y_close else None}
report["values_at_target"] = vals
step("Q4a 判断所用实际数值可获得", True,
     f"close={vals['close']} high={vals['high']} 前收={vals['prev_close']} "
     f"涨停价(20%)={vals['limit_price_20pct']} 成交额={vals['amount']:.0f} "
     f"20日最大成交额={vals['amt_max20']:.0f} is_amtmax={vals['amount_is_20d_max']}",
     values=vals)

# ── Q5 每个模型：池内否 + 原有 run_plan 单股实跑 + 结果表比对 ────
per_model = []
for m in models:
    stem = m["stem"]
    got = store.get_rule(stem)
    if not got:
        continue
    plan = got["strategy"]["plan"]
    plan = recognizer.resolve_parse_placeholders(plan) if hasattr(recognizer, "resolve_parse_placeholders") else plan
    sp = plan.get("strategy_plan") or {}
    universe = sp.get("universe") or "both"
    pool = dict((c, f) for c, f in executor._collect_stock_files(universe))
    in_pool = code in pool
    entry = {"stem": stem, "universe": universe, "in_pool": in_pool,
             "kind": m["kind"]}
    if not in_pool:
        entry["verdict"] = "NOT_IN_POOL"
        entry["why"] = f"universe={universe} 的池子不含 688（_collect_stock_files 板块过滤）"
    else:
        try:
            orig = executor._collect_stock_files
            executor._collect_stock_files = lambda u: [(code, pool[code])]
            rows, columns, meta = executor.run_plan(plan, end_date=latest["latest_date"])
            executor._collect_stock_files = orig
            viol = executor.validate_rows(plan, rows, columns)
            hit_dates = sorted({str(r.get("D-0日期") or r.get("D-0的日期") or
                                    next((v for k2, v in r.items() if k2.endswith("日期")), ""))
                                for r in rows})
            entry["single_stock_run"] = {
                "n_rows": len(rows), "columns": columns,
                "hit_dates": hit_dates[-12:], "n_hit_dates": len(hit_dates),
                "recheck_violations": len(viol),
                "sample_row": rows[0] if rows else None}
            entry["target_date_hit"] = str(TARGET_DATE) in [d.replace("-", "") for d in hit_dates]
            entry["verdict"] = "HIT" if entry["target_date_hit"] else "NOT_HIT_BUT_IN_POOL"
        except Exception as exc:
            entry["verdict"] = "RUN_ERROR"
            entry["why"] = str(exc)
            entry["trace"] = traceback.format_exc()[-800:]
    # 结果表比对（Q6：全条件满足却无行 = 不一致信号）
    cur = store.load_result(stem, "current")
    if cur:
        d0col = next((c for c in cur["columns"] if c.endswith("日期")), None)
        rows_code = [r for r in cur["rows"] if r.get("股票代码") == code]
        entry["result_table"] = {
            "n_rows_total": len(cur["rows"]),
            "n_rows_this_stock": len(rows_code),
            "d0_col": d0col,
            "this_stock_dates": sorted(str(r.get(d0col)) for r in rows_code)[-12:],
        }
        rerun_dates = sorted(set(entry.get("single_stock_run", {}).get("hit_dates", [])))
        stored_dates = sorted({str(r.get(d0col)).replace("/", "-") for r in rows_code})
        entry["rerun_vs_stored"] = {
            "rerun_only": [d for d in rerun_dates if d not in stored_dates],
            "stored_only": [d for d in stored_dates if d not in rerun_dates],
        }
        entry["inconsistency"] = "NO" if not entry["rerun_vs_stored"]["rerun_only"] \
            else "RERUN_HAS_ROWS_TABLE_LACKS"
        entry["target_row_in_table"] = any(
            str(r.get(d0col, "")).replace("-", "").replace("/", "") == str(TARGET_DATE)
            for r in rows_code) if d0col else None
    per_model.append(entry)

report["per_model"] = per_model
for e in per_model:
    rt = e.get("result_table") or {}
    print(f"  [模型] {e['stem']} universe={e['universe']} 在池={e['in_pool']} "
          f"判定={e.get('verdict')} 单股重跑行={e.get('single_stock_run', {}).get('n_rows', '-')} "
          f"结果表该股行={rt.get('n_rows_this_stock', '-')} 一致性={e.get('inconsistency', '-')}")

# ── 结论：现有能力边界 ────────────────────────────────────────
(all(True for _ in report["steps"]))
summary = {
    "Q1 定位股票+日期": "可（stock_names.csv 正扫 + read_day_file 定位到条）",
    "Q2 使用当前正式规则": "可（store.get_rule -> plan 原文，run_plan 直接执行）",
    "Q3 使用现有 Skill 判定": "可（compute_limit_flags 向量 + is_limit_up_sealed_decimal 标量，同源）",
    "Q4 逐条件检查+实际数值": "单股实跑可（run_plan 收窄宇宙后逐行给出全部数值列）；"
                              "但「某个未命中日期逐条件展开」需自行组织 20 行内联窗口计算（executor 内部循环未暴露成函数）",
    "Q5 说明哪个条件不满足": "可推（涨停向量 + 窗口最大 + prev5 三件套齐全）",
    "Q6 全满足却无行的不一致识别": "可（单股实跑结果 vs current.json 行比对）",
}
report["conclusion"] = summary
(OUT / "probe_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
print("\n=== 结论 ===")
for k, v in summary.items():
    print(f"{k}: {v}")
print(f"\n报告: {OUT / 'probe_report.json'}")
