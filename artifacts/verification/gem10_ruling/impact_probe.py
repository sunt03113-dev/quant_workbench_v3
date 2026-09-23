# -*- coding: utf-8 -*-
"""量化评估：10cm 池若放开 sz300/301，三个 10cm golden case（0824/0827A/0909A）新增多少命中行。
只调现有 recognizer/executor，monkeypatch 池子；不落盘、不改引擎。"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "app"))

import numpy as np  # noqa: E402
import executor  # noqa: E402
import recognizer  # noqa: E402

GEM = 20200824
GOLDEN = ROOT / "golden"

def load_rules():
    raw = (GOLDEN / "rule.txt").read_text(encoding="utf-8").splitlines()
    sections, cur_name, cur = {}, None, []
    for ln in raw:
        if re.fullmatch(r"\d{4}[A-E]?", ln.strip()):
            if cur_name:
                sections[cur_name] = "\n".join(cur)
            cur_name, cur = ln.strip(), []
        elif cur_name is not None:
            cur.append(ln)
    if cur_name:
        sections[cur_name] = "\n".join(cur)
    return sections

def golden_end(rule):
    """golden CSV 最大 D-0 日期（与 golden_test 协议一致）。"""
    d0 = None
    for cand in GOLDEN.glob(f"{rule}_backtest/*.csv"):
        import csv
        with open(cand, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                for k, v in row.items():
                    if k and k.endswith("日期") and v:
                        d = int(str(v).replace("-", ""))
                        d0 = d if d0 is None or d > d0 else d0
    return d0

out = []
orig = executor._collect_stock_files
try:
    base = {c: f for c, f in orig("10cm")}
    gem = {c: f for c, f in orig("20cm") if c.startswith(("300", "301"))}
    merged = dict(base)
    merged.update(gem)
    print(f"pool: 主板 {len(base)} + 创业板 {len(gem)} = {len(merged)}")

    for rule in ("0824", "0827A", "0909A"):
        text = load_rules()[rule]
        res = recognizer.recognize(text)
        if res["status"] != "READY":
            out.append({"rule": rule, "recognize": res["status"]})
            continue
        plan = res["plan"]
        end = golden_end(rule)
        executor._collect_stock_files = lambda u: list(merged.items())
        rows, columns, meta = executor.run_plan(plan, end_date=str(end))
        d0col = next((c for c in columns if c.endswith("日期")), None)
        total = len(rows)
        gem_rows = [r for r in rows if str(r.get("股票代码", "")).startswith(("300", "301"))]
        gem_pre = [r for r in gem_rows if int(str(r.get(d0col)).replace("-", "")) < GEM]
        gem_post = len(gem_rows) - len(gem_pre)
        stocks = sorted({str(r.get("股票代码")) for r in gem_pre})
        out.append({"rule": rule, "end_date": end, "total_rows": total,
                    "gem_rows_all": len(gem_rows),
                    "gem_rows_pre_0824": len(gem_pre), "gem_rows_post_0824_excluded_by_gate": gem_post,
                    "gem_stocks_pre": stocks[:15], "n_gem_stocks_pre": len(stocks)})
        print(rule, json.dumps(out[-1], ensure_ascii=False)[:200])
finally:
    executor._collect_stock_files = orig

ev = ROOT / "artifacts" / "verification" / "gem10_ruling"
ev.mkdir(parents=True, exist_ok=True)
(ev / "impact_estimate.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print("saved")
