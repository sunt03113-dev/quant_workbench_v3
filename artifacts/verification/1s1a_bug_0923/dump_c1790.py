# -*- coding: utf-8 -*-
import json
import pathlib
import datetime

ROOT = pathlib.Path(r"D:\09work\quant_workbench_v3\quant_workbench_package")
OUT = ROOT / "artifacts" / "verification" / "1s1a_bug_0923"
STEM = "strategy_c1790145091328_r1_v1"
st = json.loads((ROOT / "appdata" / "state" / "state.json").read_text(encoding="utf-8"))
m = st["models"][STEM]

L = []
L.append("keys = %s" % list(m))
L.append("")
for k, v in m.items():
    s = json.dumps(v, ensure_ascii=False, indent=1) if isinstance(v, (dict, list)) else str(v)
    L.append("--- %s ---" % k)
    L.append(s[:6000])
L.append("")
for base in ("results", ""):
    d = ROOT / "appdata" / "state" / base / STEM if base else ROOT / "appdata" / "state" / STEM
    L.append("dir %s exists=%s" % (d, d.exists()))
    if d.exists():
        for f in sorted(d.rglob("*")):
            if f.is_file():
                L.append("   %-28s %10d  %s" % (f.name, f.stat().st_size,
                         datetime.datetime.fromtimestamp(f.stat().st_mtime).strftime("%m-%d %H:%M:%S")))
(OUT / "model_c1790_full.txt").write_text("\n".join(L) + "\n", encoding="utf-8")
print("ok")
