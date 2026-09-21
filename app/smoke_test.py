# -*- coding: utf-8 -*-
"""STEP 2 冒烟测试：import 链 / 识别器 / 小样本执行 / 复核。"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.resolve()))

import logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

print("=== 1. import executor（含 Skill 加载与路径注入）===")
import executor
print("  DAY_DIRS =", sys.modules["backtest_common"].DAY_DIRS)
assert "appdata" in executor._bc.DAY_DIRS[0], "Skill 未指向标准行情目录"
print("  PASS: Skill 已指向标准本地行情")

print("=== 2. 识别器：UI 占位规则 ===")
import recognizer
ui_rule = ("基准日(D-0)涨停且成交额为近20日最大且最高价非近20日最高；\n"
           "前1日(D-1)非涨停且成交额非20日最大；前2日(D-2)涨停。")
r = recognizer.recognize(ui_rule, universe="20cm")
assert r["status"] == "READY", r
plan = r["plan"]
print("  plan =", json.dumps(plan["strategy_plan"], ensure_ascii=False))
assert plan["strategy_plan"]["days"] == [
    {"offset": -2, "limit_up": True},
    {"offset": -1, "limit_up": False, "amount_max20": False},
    {"offset": 0, "limit_up": True, "amount_max20": True, "high_max20": False},
], "days 解析错误"
print("  PASS")

print("=== 3. 识别器：golden 0818A 规则原文 ===")
golden_rule = """0818A
【20cm】

【筛选条件】
D-0：涨停，成交额最大，股价最高。
D-1：不是涨停，成交额最大
D-2：不是涨停，成交额最大
D-3：不是涨停，成交额不是最大
D-4：不是涨停，成交额不是最大

【输出指标】
D-0：日期
D-2：振幅
D-1：振幅
D-2/D-1：区间涨幅；区间振幅
D-0：振幅
D-0/D-1：成交额百分比
T+0/T+6：价格走势
"""
r2 = recognizer.recognize(golden_rule)
assert r2["status"] == "READY", json.dumps(r2, ensure_ascii=False)
sp = r2["plan"]["strategy_plan"]
assert sp["universe"] == "20cm"
atoms = [o["atom"] for o in sp["outputs"]]
print("  atoms =", atoms)
assert atoms == ["date", "amplitude", "amplitude", "range_change", "range_amplitude",
                 "amplitude", "amount_pct", "t_walk"], atoms
cols = executor._compute_columns(sp["outputs"])
expect_cols = ["D-0日期", "D-2振幅", "D-1振幅", "D-2/D-1区间涨幅", "D-2/D-1区间振幅",
               "D-0振幅", "D-0/D-1成交额百分比", "T+0(低/高)",
               "T+1最高价", "T+2最高价", "T+3最高价", "T+4最高价", "T+5最高价", "T+6最高价"]
assert cols == expect_cols, cols
print("  PASS（列名与 Skill 0818A OUTPUT_COLUMNS 一致）")

print("=== 4. 识别器：无板块 -> NEED_CONFIRMATION ===")
r3 = recognizer.recognize("基准日(D-0)涨停；前1日非涨停。")
assert r3["status"] == "NEED_CONFIRMATION", r3
r3b = recognizer.resolve_ambiguity(r3["plan_draft"], "基准日(D-0)涨停；前1日非涨停。",
                                   [{"item_id": "universe_scope", "candidate_id": "10cm", "custom_text": ""}])
assert r3b["status"] == "READY" and r3b["plan"]["strategy_plan"]["universe"] == "10cm"
print("  PASS")

print("=== 5. 识别器：fail-closed（词汇表外）===")
r4 = recognizer.recognize("D-0：净利润为正；D-1：涨停。")
assert r4["status"] == "FAILED" and r4["failure"]["code"] == "MISSING_BUSINESS_ATOM"
print("  PASS")

print("=== 6. 小样本执行（前 80 只 20cm 标的，规则=UI占位）===")
orig_collect = executor._collect_stock_files
files = orig_collect("20cm")[:80]
executor._collect_stock_files = lambda u: files
t0 = time.time()
rows, columns, meta = executor.run_plan(plan)
print(f"  rows={len(rows)} cols={len(columns)} elapsed={time.time()-t0:.1f}s meta={meta}")
executor._collect_stock_files = orig_collect
v = executor.validate_rows(plan, rows, columns)
print("  violations =", v[:5], "total:", len(v))
assert not v, "确定性复核未通过"
if rows:
    print("  sample =", json.dumps(rows[0], ensure_ascii=False)[:300])
print("  PASS")

print("\nSMOKE ALL PASS")
