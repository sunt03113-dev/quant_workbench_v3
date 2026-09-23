# -*- coding: utf-8 -*-
"""摊开两个 xlsx 的结构与差异：工作台 1S1A 结果 vs kk 的 0923 对照结果。"""
import pathlib
import pandas as pd

OUT = pathlib.Path(r"D:\09work\quant_workbench_v3\quant_workbench_package\artifacts\verification\1s1a_bug_0923")
OUT.mkdir(parents=True, exist_ok=True)

A_P = pathlib.Path(r"C:\Users\21412\Desktop\temp仅0827\1S1A_回测结果.xlsx")   # 工作台
B_P = pathlib.Path(r"D:\09work\0923_backtest\0923_backtest.xlsx")              # kk 对照

lines = []
for tag, p in (("A=workbench", A_P), ("B=0923", B_P)):
    lines.append("=" * 70)
    lines.append("%s  %s  exists=%s" % (tag, p, p.exists()))
    if not p.exists():
        continue
    xl = pd.ExcelFile(p)
    lines.append("sheets: %s" % xl.sheet_names)
    for sh in xl.sheet_names:
        df = xl.parse(sh, dtype=str)
        lines.append("-" * 60)
        lines.append("sheet=%s shape=%s" % (sh, df.shape))
        lines.append("columns: %s" % list(df.columns))
        lines.append("head 3:")
        for _, r in df.head(3).iterrows():
            lines.append("   " + " | ".join("%s=%r" % (c, r[c]) for c in df.columns))
lines.append("")
(OUT / "inspect.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("ok")
