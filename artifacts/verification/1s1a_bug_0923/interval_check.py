# -*- coding: utf-8 -*-
"""验证：A 的 143 行独有是否全部由「区间中间日违规」解释。
独立复算 kk 0923 口径（区间 [D-x, D-1] 每一天都要 非涨停 & 非量max & 非价max），
对 A 的 274 行逐行判定，并与 B 的 131 行键集比对。
"""
import struct
import sys
import json
import pathlib
import collections

APP = pathlib.Path(r"D:\09work\quant_workbench_v3\quant_workbench_package\app")
SKILL = pathlib.Path(r"D:\09work\quant_workbench_v3\quant_workbench_package\skill\tdx-stock-backtest-master")
VIP = pathlib.Path(r"D:\09work\quant_workbench_v3\quant_workbench_package\appdata\market\vipdoc")
OUT = pathlib.Path(r"D:\09work\quant_workbench_v3\quant_workbench_package\artifacts\verification\1s1a_bug_0923")
sys.path.insert(0, str(APP)); sys.path.insert(0, str(SKILL))
import numpy as np
from backtest_common import compute_limit_flags

_DT = np.dtype([("d", "<i4"), ("o", "<i4"), ("h", "<i4"), ("l", "<i4"),
                ("c", "<i4"), ("amt", "<f4"), ("v", "<i4"), ("r", "<i4")])


def load(code):
    c = str(code).zfill(6)
    mkt = "sh" if c[0] == "6" else "sz"
    p = VIP / mkt / "lday" / f"{mkt}{c}.day"
    raw = np.fromfile(p, dtype=np.uint8)
    n = len(raw) // 32
    r = raw[: n * 32].view(_DT)
    dates = r["d"].astype(np.int64)
    H = r["h"].astype(np.float64) / 100.0
    L = r["l"].astype(np.float64) / 100.0
    C = r["c"].astype(np.float64) / 100.0
    A = r["amt"].astype(np.float64)
    lf = compute_limit_flags(dates, r["c"].astype(np.int64), r["h"].astype(np.int64), c)
    amtmax = np.zeros(n, dtype=bool); hmax = np.zeros(n, dtype=bool)
    for j in range(19, n):
        amtmax[j] = A[j] == A[j - 19:j + 1].max()
        hmax[j] = H[j] == H[j - 19:j + 1].max()
    return dates, H, L, C, A, lf, amtmax, hmax


import pandas as pd
A = pd.read_excel(r"C:\Users\21412\Desktop\temp仅0827\1S1A_回测结果.xlsx", dtype=str)
B = pd.read_excel(r"D:\09work\0923_backtest\0923_backtest.xlsx", dtype=str)
Bkeys = set(zip(B["股票代码"].astype(str).str.strip(), B["D-0日期"].astype(str).str.strip()))

cache = {}
rows = []
for _, r in A.iterrows():
    code = str(r["股票代码"]).strip().zfill(6)
    d0 = str(r["D-0日期"]).strip()
    x = int(str(r["x"]).strip())
    if code not in cache:
        cache[code] = load(code)
    dates, H, L, C, Am, lf, amtmax, hmax = cache[code]
    key = int(d0.replace("-", ""))
    idx = np.nonzero(dates == key)[0]
    if len(idx) == 0:
        rows.append((code, d0, x, "NO_BAR", "", ""))
        continue
    i = int(idx[0])
    # 区间 [i-x, i-1] 每一天
    bad = []
    for j in range(i - x, i):
        v = []
        if lf[j]: v.append("涨停")
        if amtmax[j]: v.append("量max")
        if hmax[j]: v.append("价max")
        if v:
            bad.append("%s(%s)" % (dates[j], "+".join(v)))
    verdict = "OK" if not bad else "VIOL"
    rows.append((code, d0, x, verdict, ";".join(bad), "B有" if (code, d0) in Bkeys else "B无"))

cnt = collections.Counter(r[3] for r in rows)
okset = set((r[0], r[1]) for r in rows if r[3] == "OK")
violset = set((r[0], r[1]) for r in rows if r[3] == "VIOL")
L_ = []
L_.append("A 总行 %d；区间口径 OK=%d VIOL=%d 其他=%s" % (len(rows), cnt["OK"], cnt["VIOL"], dict(cnt)))
L_.append("OK 集合 vs B(131) : 仅OK不在B = %d ; 仅B不在OK = %d" % (len(okset - Bkeys), len(Bkeys - okset)))
L_.append("VIOL 集合与 B 交集 = %d" % len(violset & Bkeys))
L_.append("")
L_.append("--- VIOL 明细（前 50） ---")
for r in rows:
    if r[3] == "VIOL":
        L_.append("%s %s x=%-2d %-6s %s" % (r[0], r[1], r[2], r[5], r[4]))
L_.append("")
L_.append("--- 区间口径 OK 但 B 没有的（应为 0 或仅 300） ---")
for r in rows:
    if r[3] == "OK" and (r[0], r[1]) not in Bkeys:
        L_.append("%s %s x=%-2d %s" % (r[0], r[1], r[2], r[5]))
L_.append("")
L_.append("--- B 有但区间口径 VIOL 的（应为 0） ---")
for r in rows:
    if r[3] == "VIOL" and (r[0], r[1]) in Bkeys:
        L_.append("%s %s x=%-2d %s" % (r[0], r[1], r[2], r[4]))
L_.append("")
L_.append("--- 分开统计主板/创业板 ---")
mb = [r for r in rows if not r[0].startswith("30")]
gem = [r for r in rows if r[0].startswith("30")]
L_.append("主板 %d 行：OK=%d VIOL=%d" % (len(mb), sum(1 for r in mb if r[3] == "OK"), sum(1 for r in mb if r[3] == "VIOL")))
L_.append("创业板 %d 行：OK=%d VIOL=%d" % (len(gem), sum(1 for r in gem if r[3] == "OK"), sum(1 for r in gem if r[3] == "VIOL")))
(OUT / "interval_check.txt").write_text("\n".join(L_) + "\n", encoding="utf-8")
print("ok")
