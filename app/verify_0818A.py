# -*- coding: utf-8 -*-
"""0818A 精准验证：对 golden 命中个股集合跑执行器 plan，比对命中与数值。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.resolve()))
import logging
logging.basicConfig(level=logging.WARNING)

import pandas as pd
import numpy as np

import executor
import recognizer

g = pd.read_csv("../golden/0818A_backtest/0818A_backtest.csv", dtype={"股票代码": str})
codes = set(g["股票代码"].str.zfill(6))

raw = Path("../golden/rule.txt").read_text(encoding="utf-8")
seg = raw.split("0818A", 1)[1].split("0818B", 1)[0]
r = recognizer.recognize("0818A\n" + seg)
assert r["status"] == "READY", r
plan = r["plan"]

all_files = executor._collect_stock_files("20cm")
subset = [(c, f) for c, f in all_files if c in codes]
print(f"subset stocks: {len(subset)}")
executor._collect_stock_files = lambda u: subset

t0 = time.time()
rows, columns, meta = executor.run_plan(plan)
print(f"executor rows: {len(rows)} in {time.time()-t0:.1f}s")

ours = pd.DataFrame(rows)
if len(ours):
    ours["股票代码"] = ours["股票代码"].astype(str).str.zfill(6)
    ours_set = set(zip(ours["股票代码"], ours["D-0日期"]))
    gold_set = set(zip(g["股票代码"], g["D-0日期"]))
    only_gold = gold_set - ours_set
    only_ours = ours_set - gold_set
    print(f"hit sets: golden={len(gold_set)} ours={len(ours_set)}")
    print(f"missing vs golden: {len(only_gold)}  extra: {len(only_ours)}")
    print("missing sample:", sorted(only_gold)[:5])
    print("extra sample:", sorted(only_ours)[:5])

    # 数值比对（交集行）
    mg = ours.merge(g, on=["股票代码", "D-0日期"], suffixes=("_o", "_g"))
    print(f"merged rows for value compare: {len(mg)}")
    checks = ["D-2振幅", "D-1振幅", "D-0振幅"]
    for c in checks:
        if c + "_o" in mg.columns:
            diff = (mg[c + "_o"].astype(float) - mg[c + "_g"].astype(float)).abs()
            print(f"  {c}: max_diff={diff.max():.4f}")
    for c in ["D-2/D-1区间涨幅", "D-2/D-1区间振幅", "D-0/D-1成交额百分比"]:
        a = mg[c + "_o"].astype(str).str.rstrip("%").astype(float)
        b = mg[c + "_g"].astype(str).str.rstrip("%").astype(float)
        print(f"  {c}: max_diff={(a - b).abs().max():.4f}")
    for c in ["T+0(低/高)", "T+1最高价", "T+6最高价"]:
        eq = (mg[c + "_o"].astype(str) == mg[c + "_g"].astype(str)).mean()
        print(f"  {c}: exact_match={eq:.4f}")
else:
    print("NO ROWS - BUG")
