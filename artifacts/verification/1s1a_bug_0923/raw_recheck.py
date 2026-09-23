# -*- coding: utf-8 -*-
"""原始 .day 逐条件复算：解释为什么 A 比 B 多 143 行。
对给定 (code, D-0日期) 打印 i-12..i+8 的原始 K 线 + 三个标志，并列出 2..11 中哪些 x 满足全部 7 条件。
"""
import struct
import sys
import pathlib

APP = pathlib.Path(r"D:\09work\quant_workbench_v3\quant_workbench_package\app")
SKILL = pathlib.Path(r"D:\09work\quant_workbench_v3\quant_workbench_package\skill\tdx-stock-backtest-master")
VIP = pathlib.Path(r"D:\09work\quant_workbench_v3\quant_workbench_package\appdata\market\vipdoc")
OUT = pathlib.Path(r"D:\09work\quant_workbench_v3\quant_workbench_package\artifacts\verification\1s1a_bug_0923")
sys.path.insert(0, str(APP)); sys.path.insert(0, str(SKILL))
import numpy as np
from backtest_common import compute_limit_flags

def read_day(code):
    c = str(code).zfill(6)
    mkt = "sh" if c[0] in "6" else "sz" if c[0] in "03" else "sh"
    p = VIP / mkt / "lday" / f"{mkt}{c}.day"
    bars = []
    with open(p, "rb") as fh:
        while True:
            b = fh.read(32)
            if len(b) < 32:
                break
            d, o, h, l, cl = struct.unpack("<IIIII", b[:20])
            amt = struct.unpack("<f", b[20:24])[0]
            bars.append((d, o / 100.0, h / 100.0, l / 100.0, cl / 100.0, float(amt)))
    return p, bars

def max20_window(vals, j, kind):
    if j < 19:
        return None
    w = vals[j - 19:j + 1]
    return ("max=%.6g" % max(w)), (vals[j] == max(w))

def analyse(code, d0):
    p, bars = read_day(code)
    dates = np.array([b[0] for b in bars], dtype=np.int64)
    O = np.array([b[1] for b in bars]); H = np.array([b[2] for b in bars])
    L = np.array([b[3] for b in bars]); C = np.array([b[4] for b in bars])
    A = np.array([b[5] for b in bars])
    lf = compute_limit_flags(dates, np.round(C * 100).astype(np.int64), np.round(H * 100).astype(np.int64), code)
    amtmax = np.zeros(len(bars), dtype=bool); hihtmax = np.zeros(len(bars), dtype=bool)
    for j in range(19, len(bars)):
        amtmax[j] = A[j] == A[j - 19:j + 1].max()
        hihtmax[j] = H[j] == H[j - 19:j + 1].max()
    i = int(np.where(dates == int(d0.replace("-", "")))[0][0]) if len(np.where(dates == int(d0.replace("-", "")))[0]) else None
    out = []
    out.append("=" * 100)
    out.append("file=%s  bars=%d  last=%d  D-0 index=%s" % (p, len(bars), dates[-1], i))
    if i is None:
        return out
    out.append("bar idx  date      open   high   low    close   chg%   amt        涨停  量20max 价20max")
    for j in range(max(0, i - 13), min(len(bars), i + 9)):
        chg = "+%.2f" % ((C[j] / C[j - 1] - 1) * 100) if j > 0 else "-"
        out.append("%6d  %d  %6.2f %6.2f %6.2f %6.2f  %-7s %-11.4g  %-5s %-7s %-7s%s" % (
            j, dates[j], O[j], H[j], L[j], C[j], chg, A[j], lf[j], amtmax[j], hihtmax[j],
            "   <== D-0" if j == i else ("   <- D%d" % (j - i) if j != i else "")))
    out.append("")
    # 逐 x 试
    def chk(j, spec):
        ok = True; why = []
        if spec.get("lu") is not None and bool(lf[j]) != spec["lu"]:
            ok = False; why.append("涨停=%s≠%s" % (lf[j], spec["lu"]))
        if spec.get("am") is not None and bool(amtmax[j]) != spec["am"]:
            ok = False; why.append("量max=%s≠%s" % (amtmax[j], spec["am"]))
        if spec.get("hi") is not None and bool(hihtmax[j]) != spec["hi"]:
            ok = False; why.append("价max=%s≠%s" % (hihtmax[j], spec["hi"]))
        return ok, ",".join(why)
    C7 = [
        (-1, {"lu": False, "am": False, "hi": False}, "D-1"),
        (0,  {"lu": True,  "am": True,  "hi": True},  "D-0"),
    ]
    out.append("x  | 各条件判定")
    sat = []
    for x in range(2, 12):
        specs = [
            (i - 1, C7[0][1], "D-1"),
            (i,     C7[1][1], "D-0"),
            (i - x,     {"lu": False, "am": False, "hi": False}, "D-x"),
            (i - x - 1, {"lu": False, "am": True,  "hi": True},  "D-(x+1)"),
            (i - x - 2, {"lu": True,  "am": True,  "hi": True},  "D-(x+2)"),
            (i - x - 3, {"lu": False, "am": False}, "D-(x+3)"),
            (i - x - 4, {"lu": False, "am": False}, "D-(x+4)"),
        ]
        msgs = []
        allok = True
        for j, sp, tag in specs:
            if j < 0:
                allok = False; msgs.append("%s:越界" % tag); continue
            ok, why = chk(j, sp)
            if not ok:
                allok = False; msgs.append("%s@%d:%s" % (tag, dates[j], why))
        if allok:
            sat.append(x)
        out.append("x=%-2d %s  %s" % (x, "满足" if allok else "不满足", "" if allok else " | ".join(msgs)))
    out.append("满足的 x 集合 = %s" % sat)
    return out


CASES = [
    ("603156", "2026-05-18"),   # kk 点名“错得非常离谱”
    ("000695", "2026-08-25"),   # A 独有
    ("003022", "2026-05-14"),   # A 独有
    ("000831", "2026-08-14"),   # A 独有
    ("600021", "2015-01-26"),   # A/B 共有（对照）
    ("603020", "2026-09-21"),   # B 有、A 也有？
]
L = []
for code, d0 in CASES:
    L.extend(analyse(code, d0))
(OUT / "raw_recheck.txt").write_text("\n".join(L) + "\n", encoding="utf-8")
print("ok")
