# -*- coding: utf-8 -*-
"""第二个/第三个实例的量化：10cm_v6 vs kk 0921A；111a vs kk 111A。"""
import pathlib
import json
import pandas as pd

ROOT = pathlib.Path(r"D:\09work\quant_workbench_v3\quant_workbench_package")
OUT = ROOT / "artifacts" / "verification" / "1s1a_bug_0923"
st = json.loads((ROOT / "appdata" / "state" / "state.json").read_text(encoding="utf-8"))

L = []
PAIRS = [
    ("0921A", r"D:\09work\0921A_backtest\0921A_backtest.xlsx", "strategy_10cm_v6"),
    ("111A",  r"D:\09work\111A_backtest\111A_backtest.xlsx",   "strategy_111a_r1_v1"),
    ("0923",  r"D:\09work\0923_backtest\0923_backtest.xlsx",   "strategy_c1790145091328_r1_v1"),
    ("111B",  r"D:\09work\111B_backtest\111B_backtest.xlsx",   "strategy_111b_r1_v1"),
]
for tag, rp, stem in PAIRS:
    ref = pd.read_excel(rp, dtype=str)
    mp = ROOT / "appdata" / "state" / "results" / stem / "current.xlsx"
    mod = pd.read_excel(mp, dtype=str)
    rc = [c for c in ref.columns if "日期" in c][0]
    mc = [c for c in mod.columns if "日期" in c][0]
    def k(df, c):
        return list(zip(df["股票代码"].astype(str).str.strip().str.zfill(6), df[c].astype(str).str.strip()))
    rkeys = k(ref, rc); mkeys = k(mod, mc)
    rs, ms = set(rkeys), set(mkeys)
    onlym = sorted(ms - rs); onlyr = sorted(rs - ms)
    gem_m = [x for x in onlym if x[0].startswith("30")]
    gem_r = [x for x in onlyr if x[0].startswith("30")]
    L.append("=" * 90)
    L.append("%s : kk=%d 行  工作台(%s)=%d 行" % (tag, len(rkeys), stem, len(mkeys)))
    L.append("   共同=%d  仅工作台=%d（其中创业板=%d）  仅kk=%d（其中创业板=%d）"
             % (len(rs & ms), len(onlym), len(gem_m), len(onlyr), len(gem_r)))
    L.append("   重复键: kk=%d 工作台=%d" % (len(rkeys) - len(rs), len(mkeys) - len(ms)))
    # 共同行上的列值差异（取公共列，忽略名称/日期列）
    if rs & ms:
        comm = [c for c in ref.columns if c in mod.columns
                and c not in ("股票名称", rc, mc, "股票代码", "D-0日期", "D-0的日期")]
        ri = {(r["股票代码"].strip().zfill(6), r[rc].strip()): r for _, r in ref.iterrows()}
        mi = {(r["股票代码"].strip().zfill(6), r[mc].strip()): r for _, r in mod.iterrows()}
        diff = 0; samples = []
        for key in (rs & ms):
            a, b = ri[key], mi[key]
            for c in comm:
                va = str(a[c]).strip(); vb = str(b[c]).strip()
                if va != vb:
                    diff += 1
                    if len(samples) < 8:
                        samples.append("%s [%s] kk=%r 工作台=%r" % (key, c, va, vb))
        L.append("   共同行字段差异=%d  %s" % (diff, samples[:4]))
    else:
        L.append("   共同行为 0 —— 规则不同（非同一规则）")
    L.append("   仅工作台样例: %s" % onlym[:8])
    L.append("   仅kk样例:    %s" % onlyr[:8])

(OUT / "pair_quant.txt").write_text("\n".join(L) + "\n", encoding="utf-8")
print("ok")
