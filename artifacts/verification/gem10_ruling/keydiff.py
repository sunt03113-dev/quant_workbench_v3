# -*- coding: utf-8 -*-
"""新引擎(10cm 放开) vs 旧 golden 键集精确比对：extra 应恰好 = 300/301 且 < 2020-08-24 的行。"""
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "app"))

import executor  # noqa: E402
import recognizer  # noqa: E402

GEM = 20200824


def load_rules():
    raw = (ROOT / "golden" / "rule.txt").read_text(encoding="utf-8").splitlines()
    sec, name, buf = {}, None, []
    for ln in raw:
        if re.fullmatch(r"\d{4}[A-E]?", ln.strip()):
            if name:
                sec[name] = "\n".join(buf)
            name, buf = ln.strip(), []
        elif name:
            buf.append(ln)
    if name:
        sec[name] = "\n".join(buf)
    return sec


out = {}
for rule, c_str in (("0824", "2026-08-19"), ("0827A", "2026-08-26"), ("0909A", "2025-09-18")):
    res = recognizer.recognize(load_rules()[rule])
    assert res["status"] == "READY", (rule, res["status"])
    rows, cols, meta = executor.run_plan(res["plan"], end_date=c_str, data_end=None)
    d0 = next(c for c in cols if c.endswith("日期"))
    new_keys = {(str(r["股票代码"]).zfill(6), str(r[d0])) for r in rows}
    with open(ROOT / "golden" / f"{rule}_backtest" / f"{rule}_backtest.csv",
              encoding="utf-8-sig", newline="") as fh:
        g = list(csv.DictReader(fh))
    old_keys = {(r["股票代码"].zfill(6), r["D-0日期"]) for r in g}
    extra = sorted(new_keys - old_keys)
    missing = sorted(old_keys - new_keys)
    extra_gem_pre = [k for k in extra
                     if k[0].startswith(("300", "301"))
                     and int(k[1].replace("-", "")) < GEM]
    out[rule] = {"n_new": len(new_keys), "n_old": len(old_keys),
                 "n_extra": len(extra), "n_extra_gem_pre": len(extra_gem_pre),
                 "extra_non_gem_pre": [k for k in extra if k not in extra_gem_pre][:10],
                 "n_missing": len(missing), "missing_sample": missing[:5]}
    print(rule, json.dumps(out[rule], ensure_ascii=False)[:220])

ev = ROOT / "artifacts" / "verification" / "gem10_ruling"
ev.mkdir(parents=True, exist_ok=True)
(ev / "keydiff_new_vs_old.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print("saved")
