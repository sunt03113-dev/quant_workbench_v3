# -*- coding: utf-8 -*-
"""① 对 10cm_v6 的行做区间口径复核；② 列出 111a 的非创业板多余行。"""
import sys
import pathlib
import pandas as pd

APP = pathlib.Path(r"D:\09work\quant_workbench_v3\quant_workbench_package\app")
SKILL = pathlib.Path(r"D:\09work\quant_workbench_v3\quant_workbench_package\skill\tdx-stock-backtest-master")
VIP = pathlib.Path(r"D:\09work\quant_workbench_v3\quant_workbench_package\appdata\market\vipdoc")
ROOT = pathlib.Path(r"D:\09work\quant_workbench_v3\quant_workbench_package")
OUT = ROOT / "artifacts" / "verification" / "1s1a_bug_0923"
sys.path.insert(0, str(APP)); sys.path.insert(0, str(SKILL))
import numpy as np
from backtest_common import compute_limit_flags

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


L = []
# ① 10cm_v6（0921A 规则）：D-0 非涨停+量max+价max；区间 [D-x, D-1] 全部 非涨停+非量max+非价max
mod = pd.read_excel(ROOT / "appdata" / "state" / "results" / "strategy_10cm_v6" / "current.xlsx", dtype=str)
ref = pd.read_excel(r"D:\09work\0921A_backtest\0921A_backtest.xlsx", dtype=str)
rk = set(zip(ref["股票代码"].astype(str).str.strip().str.zfill(6), ref["D-0日期"].astype(str).str.strip()))
cnt = {"OK": 0, "VIOL": 0}
ok_main, ok_gem, viol_main, viol_gem = 0, 0, 0, 0
b_ok, b_viol = 0, 0
detail = []
for _, r in mod.iterrows():
    code = str(r["股票代码"]).strip().zfill(6)
    d0 = str(r["D-0日期"]).strip()
    x = int(str(r["x"]).strip())
    if code not in cache:
        cache[code] = load(code)
    dates, lf, am, hm = cache[code]
    idx = np.nonzero(dates == int(d0.replace("-", "")))[0]
    if not len(idx):
        continue
    i = int(idx[0])
    bad = []
    for j in range(i - x, i):
        v = []
        if lf[j]: v.append("涨停")
        if am[j]: v.append("量max")
        if hm[j]: v.append("价max")
        if v:
            bad.append("%s(%s)" % (dates[j], "+".join(v)))
    isgem = code.startswith("30")
    inref = (code, d0) in rk
    if bad:
        cnt["VIOL"] += 1
        viol_gem += isgem; viol_main += (not isgem)
        b_viol += inref
        if len(detail) < 12:
            detail.append("VIOL %s %s x=%d %s" % (code, d0, x, ";".join(bad)))
    else:
        cnt["OK"] += 1
        ok_gem += isgem; ok_main += (not isgem)
        b_ok += inref

L.append("=== 10cm_v6（=0921A 规则）区间口径复核 ===")
L.append("工作台总行 %d : 区间口径 OK=%d（主板 %d / 创业板 %d）VIOL=%d（主板 %d / 创业板 %d）"
         % (len(mod), cnt["OK"], ok_main, ok_gem, cnt["VIOL"], viol_main, viol_gem))
L.append("kk 0921A=%d 行；其中落在区间 OK 集合内 = %d，落在 VIOL = %d" % (len(rk), b_ok, b_viol))
L.append("VIOL 样例:")
L.extend("  " + d for d in detail)

# ② 111a 非创业板多余行
L.append("")
L.append("=== 111a 多余行（非创业板） ===")
m111 = pd.read_excel(ROOT / "appdata" / "state" / "results" / "strategy_111a_r1_v1" / "current.xlsx", dtype=str)
r111 = pd.read_excel(r"D:\09work\111A_backtest\111A_backtest.xlsx", dtype=str)
mk = set(zip(m111["股票代码"].astype(str).str.strip().str.zfill(6), m111["D-0的日期"].astype(str).str.strip()))
k111 = set(zip(r111["股票代码"].astype(str).str.strip().str.zfill(6), r111["D-0日期"].astype(str).str.strip()))
extra = sorted(mk - k111)
for e in extra:
    row = m111[(m111["股票代码"].astype(str).str.strip().str.zfill(6) == e[0]) &
               (m111["D-0的日期"].astype(str).str.strip() == e[1])]
    L.append("  %s %s | N1=%s N2=%s D-y振幅=%s D-x振幅=%s 区间涨幅=%s"
             % (e[0], e[1], row["N1"].iloc[0], row["N2"].iloc[0], row["D-y振幅"].iloc[0],
                row["D-x振幅"].iloc[0], row["D-y~D-0区间涨幅"].iloc[0]))

(OUT / "interval_10cm_v6.txt").write_text("\n".join(L) + "\n", encoding="utf-8")
print("ok")
