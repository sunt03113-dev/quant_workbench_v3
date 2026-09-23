# -*- coding: utf-8 -*-
"""按 (代码, D-0日期) 键比对 A(工作台) 与 B(0923 对照)；按板块前缀拆解差异。"""
import pathlib
import collections
import pandas as pd

OUT = pathlib.Path(r"D:\09work\quant_workbench_v3\quant_workbench_package\artifacts\verification\1s1a_bug_0923")
A = pd.read_excel(r"C:\Users\21412\Desktop\temp仅0827\1S1A_回测结果.xlsx", dtype=str)
B = pd.read_excel(r"D:\09work\0923_backtest\0923_backtest.xlsx", dtype=str)

SHARED = ["股票代码", "D-0日期", "D-(x+2)振幅", "D-(x+1)振幅", "x",
          "D-x~D-1区间涨幅", "D-x~D-1区间振幅", "D-x~D-1区间最大振幅",
          "D-0振幅", "D+1(低/高)", "D+2最高价", "D+3最高价", "D+4最高价",
          "D+5最高价", "D+6最高价", "D+7最高价", "D+8最高价"]

def key(df, c, d):
    return df[c].astype(str).str.strip() + "@" + df[d].astype(str).str.strip()

for df in (A, B):
    for c in ("股票代码", "D-0日期", "x"):
        df[c] = df[c].astype(str).str.strip()

A["_k"] = key(A, "股票代码", "D-0日期")
B["_k"] = key(B, "股票代码", "D-0日期")

L = []
L.append("A rows=%d  B rows=%d" % (len(A), len(B)))
L.append("A dup keys=%d  B dup keys=%d" % (len(A) - A["_k"].nunique(), len(B) - B["_k"].nunique()))

def board(code):
    c = str(code).zfill(6)
    if c.startswith("688") or c.startswith("689"): return "688科创"
    if c.startswith("30"): return "300创业"
    if c.startswith("60"): return "60沪主板"
    if c.startswith("00"): return "00深主板"
    return "其他(%s)" % c[:2]

L.append("")
L.append("--- 板块分布 ---")
ca = collections.Counter(board(c) for c in A["股票代码"])
cb = collections.Counter(board(c) for c in B["股票代码"])
for k in sorted(set(ca) | set(cb)):
    L.append("  %-10s A=%-5d B=%-5d" % (k, ca.get(k, 0), cb.get(k, 0)))

onlyA = sorted(set(A["_k"]) - set(B["_k"]))
onlyB = sorted(set(B["_k"]) - set(A["_k"]))
both = sorted(set(A["_k"]) & set(B["_k"]))
L.append("")
L.append("--- 键集 ---")
L.append("  共同=%d  仅A=%d  仅B=%d" % (len(both), len(onlyA), len(onlyB)))
L.append("  仅A 板块分布: %s" % dict(collections.Counter(board(k.split("@")[0]) for k in onlyA)))
L.append("  仅B 板块分布: %s" % dict(collections.Counter(board(k.split("@")[0]) for k in onlyB)))
L.append("")
L.append("  仅A 按年份: %s" % dict(sorted(collections.Counter(k.split("@")[1][:4] for k in onlyA).items())))
L.append("  仅B 按年份: %s" % dict(sorted(collections.Counter(k.split("@")[1][:4] for k in onlyB).items())))
L.append("")
L.append("  仅A 全部键（前 80）:")
for k in onlyA[:80]:
    L.append("     %s" % k)
L.append("  仅B 全部键（前 80）:")
for k in onlyB[:80]:
    L.append("     %s" % k)

# 共同键上的字段差异
L.append("")
L.append("--- 共同键字段差异 ---")
ai = A.set_index("_k")
bi = B.set_index("_k")
diffcnt = collections.Counter()
sampled = []
for k in both:
    ra, rb = ai.loc[k], bi.loc[k]
    for c in SHARED:
        if c in ("股票代码", "D-0日期"):
            continue
        va = str(ra[c]).strip() if not pd.isna(ra[c]) else ""
        vb = str(rb[c]).strip() if not pd.isna(rb[c]) else ""
        if va != vb:
            diffcnt[c] += 1
            if len(sampled) < 40:
                sampled.append("  %s  [%s] A=%r  B=%r" % (k, c, va, vb))
L.append("  差异计数: %s" % dict(diffcnt))
L.append("  样本:")
L.extend(sampled)

# 603156 专项
L.append("")
L.append("--- 603156 专项 ---")
for tag, df in (("A", A), ("B", B)):
    sub = df[df["股票代码"].astype(str).str.zfill(6) == "603156"]
    L.append("%s: %d 行" % (tag, len(sub)))
    for _, r in sub.iterrows():
        L.append("   " + " | ".join("%s=%s" % (c, r[c]) for c in df.columns if c != "_k"))

# 所有 300/301 行
L.append("")
L.append("--- A 中 300/301 行 ---")
for _, r in A[A["股票代码"].astype(str).str.zfill(6).str.startswith(("30",))].iterrows():
    L.append("   " + " | ".join("%s=%s" % (c, r[c]) for c in ["股票代码", "股票名称", "D-0日期", "x", "D-0振幅", "D+1(低/高)", "D+8最高价"]))

(OUT / "compare_AB.txt").write_text("\n".join(L) + "\n", encoding="utf-8")
print("ok")
