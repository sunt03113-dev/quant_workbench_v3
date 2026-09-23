# -*- coding: utf-8 -*-
"""回答 kk 的点名质询：603156@2026-05-18 在新结果里是什么状态？
并给出 148（新） vs 131（0923_backtest.xlsx 参考）的差集构成。

三条线：
  A) 新结果（区间式，148 行，data_date=2026-09-23）
  B) 0923 参考（131 行，kk 认定的 10cm 正确结果）
  C) 逐行核对：差集里每一行属于哪一类（主板 10cm / 创业板 20cm / 其他）
  D) 603156 单点追踪：旧口径为什么放行、新口径为什么剔除
"""
import io
import json
import pathlib
import sys
from collections import Counter

import pandas as pd

ART = pathlib.Path("artifacts/verification/1s1a_bug_0923")
ART_OLD = pathlib.Path("artifacts/verification/1s1a_check")
BUF = io.StringIO()


def p(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    print(s, file=BUF)


# ── 读三份结果 ──────────────────────────────────────────────────
new_x = ART / "new_strategy_c1790145091328_r1_v1.xlsx"
cands = sorted(ART.glob("*1S1A*.xlsx")) + sorted(ART.glob("*c179*.xlsx"))
p("### 候选结果文件")
for c in cands:
    p(f"    {c.name}  {c.stat().st_size} B")
ref = pathlib.Path("D:/09work/0923_backtest/0923_backtest.xlsx")
p(f"\n参考文件 {ref}  exists={ref.exists()}")

# 用库内最新结果（活体回测已写回）
sys.path.insert(0, "app")
import store  # noqa: E402

rd = store.result_dir("strategy_c1790145091328_r1_v1")
live = rd / "current.xlsx"
p(f"库内 current.xlsx = {live}  exists={live.exists()}  size={live.stat().st_size}")

A = pd.read_excel(live, dtype=str).fillna("")
B = pd.read_excel(ref, dtype=str).fillna("")
p(f"\nA（新/区间式）: {len(A)} 行 x {len(A.columns)} 列")
p(f"  columns: {list(A.columns)}")
p(f"B（0923 参考）: {len(B)} 行 x {len(B.columns)} 列")
p(f"  columns: {list(B.columns)}")


def key(df):
    cc = [c for c in df.columns if ("代码" in c or "code" in c.lower())]
    dd = [c for c in df.columns if ("日期" in c or "date" in c.lower())]
    if not cc or not dd:
        return None, None
    return cc[0], dd[0]


kc_a, kd_a = key(A)
kc_b, kd_b = key(B)
p(f"\nA key: code={kc_a!r} date={kd_a!r}")
p(f"B key: code={kc_b!r} date={kd_b!r}")


def norm_code(s):
    return str(s).strip().zfill(6)[-6:]


def norm_date(s):
    s = str(s).strip()
    return s.replace("-", "").replace("/", "")[:8]


def kset(df, kc, kd):
    return {(norm_code(r[kc]), norm_date(r[kd])) for _, r in df.iterrows()}


SA = kset(A, kc_a, kd_a)
SB = kset(B, kc_b, kd_b)
p(f"\n|SA|={len(SA)}  |SB|={len(SB)}")
p(f"交集            = {len(SA & SB)}")
p(f"仅 A（多出）    = {len(SA - SB)}")
p(f"仅 B（漏掉）    = {len(SB - SA)}")


def board(code):
    if code.startswith(("600", "601", "603", "605")):
        return "沪主板"
    if code.startswith(("000", "001", "002", "003")):
        return "深主板/中小"
    if code.startswith("300") or code.startswith("301"):
        return "创业板"
    if code.startswith(("688", "689")):
        return "科创板"
    if code.startswith(("8", "4")):
        return "北交所"
    return "其他"


onlyA = sorted(SA - SB)
onlyB = sorted(SB - SA)
p(f"\n### 仅 A 多出的 {len(onlyA)} 行，按板块：")
for k, v in Counter(board(c) for c, _ in onlyA).most_common():
    p(f"    {k:<12} {v}")
p("  ---- 明细（前 40） ----")
for c, d in onlyA[:40]:
    p(f"    {c}  {d}   {board(c)}")
if len(onlyA) > 40:
    p(f"    ... 余 {len(onlyA) - 40} 行")

p(f"\n### 仅 B 漏掉的 {len(onlyB)} 行，按板块：")
for k, v in Counter(board(c) for c, _ in onlyB).most_common():
    p(f"    {k:<12} {v}")
for c, d in onlyB[:40]:
    p(f"    {c}  {d}   {board(c)}")

# ── 603156 单点追踪 ─────────────────────────────────────────────
p("\n" + "=" * 92)
p("### 603156 单点追踪")
p("=" * 92)
tgt = ("603156", "20260518")
p(f"  603156@2026-05-18 在 A（新结果）: {'在' if tgt in SA else '不在'}")
p(f"  603156@2026-05-18 在 B（参考）  : {'在' if tgt in SB else '不在'}")
hits603156_A = sorted(d for c, d in SA if c == "603156")
hits603156_B = sorted(d for c, d in SB if c == "603156")
p(f"  A 中 603156 全部命中日: {hits603156_A}")
p(f"  B 中 603156 全部命中日: {hits603156_B}")

# ── 603156 原始行情复算（直接读 .day，不经工作台） ──────────────
import struct  # noqa: E402

fp = list(pathlib.Path("appdata/market/vipdoc/sh/lday").glob("sh603156.day"))
p(f"\n  行情文件: {[str(x) for x in fp]}")
if fp:
    recs = []
    raw = fp[0].read_bytes()
    for i in range(0, len(raw), 32):
        d, o, h, l, c, amt, vol, _ = struct.unpack("<IIIIIfII", raw[i:i + 32])
        recs.append((str(d), o / 100, h / 100, l / 100, c / 100, amt, vol))
    idx = {d: i for i, (d, *_r) in enumerate(recs)}
    D0 = "20260518"
    i0 = idx[D0]
    p(f"  D-0 = 20260518 收 {recs[i0][4]}  前收 {recs[i0-1][4]}")
    # 涨停价：60 开头 10cm，严格整数分
    def limit_px(prev_c):
        return ((round(prev_c * 100) * 11 + 5) // 10) / 100.0
    p(f"  D-0 涨停价 = {limit_px(recs[i0-1][4])}")
    p(f"  D-0 最高 {recs[i0][2]}  收盘 {recs[i0][4]}  -> "
      f"{'封死涨停' if abs(recs[i0][4]-limit_px(recs[i0-1][4]))<1e-9 and abs(recs[i0][2]-limit_px(recs[i0-1][4]))<1e-9 else '非封死涨停'}")
    # 打印 D-1 .. D-8 的序列
    p("\n  日期       开     高     低     收     昨收   涨停价  封死  20日量最大 20日价最高")
    amts = [r[5] for r in recs]
    highs = [r[2] for r in recs]
    for k in range(-8, 1):
        i = i0 + k
        if i < 0:
            continue
        d, o, h, l, c, amt, vol = recs[i]
        lp = limit_px(recs[i - 1][4]) if i > 0 else 0
        is_lu = (i > 0 and abs(h - lp) < 1e-9 and abs(c - lp) < 1e-9)
        w = amts[max(0, i - 19):i + 1]
        w2 = highs[max(0, i - 19):i + 1]
        is_am = (amt >= max(w)) if len(w) >= 20 else None
        is_hm = (h >= max(w2)) if len(w2) >= 20 else None
        p(f"  {d}  {o:>6.2f} {h:>6.2f} {l:>6.2f} {c:>6.2f} {recs[i-1][4] if i>0 else 0:>6.2f}"
          f" {lp:>7.2f}  {'是' if is_lu else '否':<4} "
          f"{('是' if is_am else '否') if is_am is not None else '窗口不足':<10} "
          f"{('是' if is_hm else '否') if is_hm is not None else '窗口不足':<10}")

ART.joinpath("diff_vs_0923_ref.txt").write_text(BUF.getvalue(), encoding="utf-8")
print("\n-> diff_vs_0923_ref.txt 已落盘")
