# -*- coding: utf-8 -*-
"""① 确认 A 是否等于当前结果；② 扫描所有模型的 plan/outputs，找 B(19列含D-0涨幅) 的出处。"""
import json
import pathlib
import pandas as pd

ROOT = pathlib.Path(r"D:\09work\quant_workbench_v3\quant_workbench_package")
OUT = ROOT / "artifacts" / "verification" / "1s1a_bug_0923"
STEM = "strategy_c1790145091328_r1_v1"

L = []
A = pd.read_excel(r"C:\Users\21412\Desktop\temp仅0827\1S1A_回测结果.xlsx", dtype=str)
cur = pd.read_excel(ROOT / "appdata" / "state" / "results" / STEM / "current.xlsx", dtype=str)
prev = pd.read_excel(ROOT / "appdata" / "state" / "results" / STEM / "previous.xlsx", dtype=str)
B = pd.read_excel(r"D:\09work\0923_backtest\0923_backtest.xlsx", dtype=str)


def same(a, b):
    if list(a.columns) != list(b.columns) or len(a) != len(b):
        return "cols/rows differ %s/%s vs %s/%s" % (list(a.columns), len(a), list(b.columns), len(b))
    na = a.fillna("N/A").astype(str)
    nb = b.fillna("N/A").astype(str)
    d = (na.values != nb.values).sum()
    return "identical" if d == 0 else "%d cell diffs" % d


L.append("A(desktop) vs current.xlsx : %s" % same(A, cur))
L.append("A(desktop) vs previous.xlsx: %s" % same(A, prev))
L.append("current.xlsx vs previous.xlsx: %s" % same(cur, prev))
L.append("")
L.append("--- A columns ---")
L.append(str(list(A.columns)))
L.append("--- B columns ---")
L.append(str(list(B.columns)))
L.append("")

st = json.loads((ROOT / "appdata" / "state" / "state.json").read_text(encoding="utf-8"))
BCOLS = set(B.columns)
L.append("--- 扫描所有模型的 columns / 条件 ---")


def condsig(plan):
    sp = plan.get("strategy_plan") or {}
    days = sp.get("days") or []
    parts = []
    for d in days:
        o = d.get("offset", d.get("offset_var"))
        f = []
        for k in ("limit_up", "amount_max20", "high_max20"):
            if k in d:
                f.append("%s=%s" % (k, d[k]))
        parts.append("%s[%s]" % (o, ",".join(f)))
    return " ".join(parts)


for stem, m in st["models"].items():
    plan = m.get("plan") or {}
    sp = plan.get("strategy_plan") or {}
    cols = (m.get("current_result") or {}).get("columns") or []
    mark = ""
    if set(cols) == BCOLS:
        mark += "  <== 列名与B完全一致"
    if set(cols) == set(A.columns):
        mark += "  <== 列名与A完全一致"
    L.append("%-32s n=%-6s universe=%-6s cols=%d%s" % (
        stem, (m.get("current_result") or {}).get("n_hits"), sp.get("universe"), len(cols), mark))
    L.append("      cols: %s" % cols)
    L.append("      cond: %s | quant=%s" % (condsig(plan), sp.get("quantifier")))

(OUT / "scan_models.txt").write_text("\n".join(L) + "\n", encoding="utf-8")
print("ok")
