# -*- coding: utf-8 -*-
"""把 kk 的 9 份对照结果与工作台模型做列签名映射，并逐键比对差异规模。"""
import pathlib
import pandas as pd

ROOT = pathlib.Path(r"D:\09work\quant_workbench_v3\quant_workbench_package")
OUT = ROOT / "artifacts" / "verification" / "1s1a_bug_0923"
REF = pathlib.Path(r"D:\09work")

L = []
refs = {}
for d in sorted(REF.glob("*_backtest")):
    f = d / (d.name + ".xlsx")
    if f.exists():
        try:
            df = pd.read_excel(f, dtype=str)
            refs[d.name] = df
            L.append("REF %-22s rows=%-6d cols=%d" % (d.name, len(df), len(df.columns)))
            L.append("     %s" % list(df.columns))
        except Exception as e:
            L.append("REF %-22s ERR %s" % (d.name, e))

L.append("")
L.append("=" * 90)
L.append("工作台模型：")
import json
st = json.loads((ROOT / "appdata" / "state" / "state.json").read_text(encoding="utf-8"))
models = {}
for stem, m in st["models"].items():
    p = ROOT / "appdata" / "state" / "results" / stem / "current.xlsx"
    if p.exists():
        try:
            df = pd.read_excel(p, dtype=str)
            models[stem] = df
            L.append("MODEL %-32s rows=%-6d cols=%d" % (stem, len(df), len(df.columns)))
            L.append("     %s" % list(df.columns))
        except Exception as e:
            L.append("MODEL %-32s ERR %s" % (stem, e))

L.append("")
L.append("=" * 90)
L.append("列签名匹配（同列集合）:")
for rn, rdf in refs.items():
    rc = set(rdf.columns)
    hits = [s for s, mdf in models.items() if set(mdf.columns) == rc]
    L.append("REF %-22s -> %s" % (rn, hits or "(无同列模型)"))

L.append("")
L.append("=" * 90)
L.append("逐键比对（按 代码+日期列 对齐）:")
for rn, rdf in refs.items():
    rc = set(rdf.columns)
    for s in [x for x, mdf in models.items() if set(mdf.columns) == rc]:
        mdf = models[s]
        # 找日期列
        dc = [c for c in rdf.columns if "日期" in c]
        if not dc or "股票代码" not in rdf.columns:
            L.append("  %s vs %s: 无日期列，跳过" % (rn, s))
            continue
        dcol = dc[0]
        rk = set(zip(rdf["股票代码"].astype(str).str.strip().str.zfill(6), rdf[dcol].astype(str).str.strip()))
        mk = set(zip(mdf["股票代码"].astype(str).str.strip().str.zfill(6), mdf[dcol].astype(str).str.strip()))
        only_r = rk - mk; only_m = mk - rk
        gem_only_r = [k for k in only_r if k[0].startswith("30")]
        gem_only_m = [k for k in only_m if k[0].startswith("30")]
        L.append("  REF %-20s vs %-30s  ref=%d model=%d 共同=%d 仅REF=%d(其中300=%d) 仅MODEL=%d(其中300=%d)"
                 % (rn, s, len(rk), len(mk), len(rk & mk), len(only_r), len(gem_only_r), len(only_m), len(gem_only_m)))
        if only_m:
            L.append("      仅MODEL 样例: %s" % sorted(only_m)[:6])
        if only_r:
            L.append("      仅REF   样例: %s" % sorted(only_r)[:6])

(OUT / "ref_vs_model.txt").write_text("\n".join(L) + "\n", encoding="utf-8")
print("ok")
