# -*- coding: utf-8 -*-
"""① golden 各 case 头行是否含 x 列（判定冻结侧是否有变量日规则）
   ② 逐个含 x 的工作台模型打印计划条件，并按「区间=两端条件并集」复核当前结果。"""
import sys
import json
import pathlib
import pandas as pd

ROOT = pathlib.Path(r"D:\09work\quant_workbench_v3\quant_workbench_package")
APP = ROOT / "app"
SKILL = ROOT / "skill" / "tdx-stock-backtest-master"
VIP = ROOT / "appdata" / "market" / "vipdoc"
OUT = ROOT / "artifacts" / "verification" / "1s1a_bug_0923"
sys.path.insert(0, str(APP)); sys.path.insert(0, str(SKILL))
import numpy as np
from backtest_common import compute_limit_flags

L = []
L.append("=== golden case 头行（找 x 列） ===")
for d in sorted((ROOT / "golden").glob("*_backtest")):
    csvs = list(d.glob("*.csv"))
    for c in csvs:
        try:
            head = pd.read_csv(c, nrows=1, dtype=str)
            hasx = "x" in [str(x).strip() for x in head.columns]
            L.append("%-48s cols=%-3d 含x=%s  %s" % (c.name, len(head.columns), hasx, list(head.columns)[:8]))
        except Exception as e:
            L.append("%-48s ERR %s" % (c.name, e))

_DT = np.dtype([("d", "<i4"), ("o", "<i4"), ("h", "<i4"), ("l", "<i4"),
                ("c", "<i4"), ("amt", "<f4"), ("v", "<i4"), ("r", "<i4")])
cache = {}


def load(code):
    c = str(code).zfill(6)
    mkt = "sh" if c[0] == "6" else "sz"
    p = VIP / mkt / "lday" / f"{mkt}{c}.day"
    raw = np.fromfile(p, dtype=np.uint8)
    n = len(raw) // 32
    r = raw[: n * 32].view(_DT)
    dates = r["d"].astype(np.int64)
    H = r["h"].astype(np.float64) / 100.0
    C = r["c"].astype(np.float64) / 100.0
    A = r["amt"].astype(np.float64)
    lf = compute_limit_flags(dates, r["c"].astype(np.int64), r["h"].astype(np.int64), c)
    am = np.zeros(n, bool); hm = np.zeros(n, bool)
    for j in range(19, n):
        am[j] = A[j] == A[j - 19:j + 1].max()
        hm[j] = H[j] == H[j - 19:j + 1].max()
    return dates, lf, am, hm


st = json.loads((ROOT / "appdata" / "state" / "state.json").read_text(encoding="utf-8"))
L.append("")
L.append("=== 含 x 的工作台模型：计划条件 + 区间复核 ===")
for stem, m in st["models"].items():
    plan = m.get("plan") or {}
    sp = plan.get("strategy_plan") or {}
    if not sp or sp.get("chain") is not None or not sp.get("quantifier"):
        continue
    days = sp.get("days") or []
    L.append("-" * 90)
    L.append("MODEL %s  universe=%s quant=%s n=%s" % (
        stem, sp.get("universe"), sp.get("quantifier"), (m.get("current_result") or {}).get("n_hits")))
    for d in days:
        L.append("    %s" % json.dumps(d, ensure_ascii=False))
    # 区间端点：offset=-1 与 var0；区间条件 = 两者共有且同为 required 的字段
    c_m1 = next((d for d in days if d.get("offset") == -1), None)
    c_v0 = next((d for d in days if d.get("offset_var") == 0), None)
    if not c_m1 or not c_v0:
        L.append("    (无法定位端点，跳过复核)")
        continue
    span = {}
    for k in ("limit_up", "amount_max20", "high_max20"):
        a = c_m1.get(k); b = c_v0.get(k)
        if a is not None and a == b:
            span[k] = a
    L.append("    区间 [D-x, D-1] 共有条件 = %s" % span)
    p = ROOT / "appdata" / "state" / "results" / stem / "current.xlsx"
    if not p.exists() or not span:
        continue
    df = pd.read_excel(p, dtype=str)
    if "x" not in df.columns or "D-0日期" not in df.columns:
        L.append("    (结果无 x 列，跳过)")
        continue
    okc = violc = 0
    gem_ok = gem_viol = 0
    for _, r in df.iterrows():
        code = str(r["股票代码"]).strip().zfill(6)
        d0 = str(r["D-0日期"]).strip()
        x = int(float(str(r["x"]).strip()))
        if code not in cache:
            cache[code] = load(code)
        dates, lf, am, hm = cache[code]
        idx = np.nonzero(dates == int(d0.replace("-", "")))[0]
        if not len(idx):
            continue
        i = int(idx[0])
        bad = False
        for j in range(i - x, i):
            if span.get("limit_up") is False and lf[j]: bad = True
            if span.get("limit_up") is True and not lf[j]: bad = True
            if span.get("amount_max20") is False and am[j]: bad = True
            if span.get("amount_max20") is True and not am[j]: bad = True
            if span.get("high_max20") is False and hm[j]: bad = True
            if span.get("high_max20") is True and not hm[j]: bad = True
            if bad:
                break
        g = code.startswith("30")
        if bad:
            violc += 1; gem_viol += g
        else:
            okc += 1; gem_ok += g
    L.append("    区间复核: OK=%d（主板 %d/创业板 %d）  VIOL=%d（主板 %d/创业板 %d）"
             % (okc, okc - gem_ok, gem_ok, violc, violc - gem_viol, gem_viol))

(OUT / "span_scan.txt").write_text("\n".join(L) + "\n", encoding="utf-8")
print("ok")
