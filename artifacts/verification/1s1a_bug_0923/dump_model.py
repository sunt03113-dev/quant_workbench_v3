# -*- coding: utf-8 -*-
"""查 1S1A 模型定义（plan/universe/rule_text）与结果目录历史文件。"""
import json
import pathlib

ROOT = pathlib.Path(r"D:\09work\quant_workbench_v3\quant_workbench_package")
OUT = ROOT / "artifacts" / "verification" / "1s1a_bug_0923"
st = json.loads((ROOT / "appdata" / "state" / "state.json").read_text(encoding="utf-8"))

L = []
L.append("--- 所有模型 ---")
target = []
for stem, m in st["models"].items():
    name = m.get("name") or ""
    cr = m.get("current_result") or {}
    L.append("%-34s | %-10s | universe=%-6s | data_date=%s | n=%s | created=%s" % (
        stem, name, m.get("universe"), cr.get("data_date"), cr.get("n_hits"), m.get("created_at")))
    if "1S1A" in name.upper().replace(" ", "") or "1s1a" in stem.lower():
        target.append(stem)

L.append("")
L.append("target stems = %s" % target)
for stem in target:
    m = st["models"][stem]
    L.append("=" * 70)
    L.append("STEM %s" % stem)
    L.append("keys: %s" % list(m))
    L.append("universe=%s" % m.get("universe"))
    L.append("rule_text:")
    L.append(str(m.get("rule_text") or m.get("text") or "")[:2000])
    L.append("plan:")
    L.append(json.dumps(m.get("plan"), ensure_ascii=False, indent=1)[:4000])
    L.append("current_result: %s" % json.dumps(m.get("current_result"), ensure_ascii=False)[:600])
    d = ROOT / "appdata" / "state" / "results" / stem
    L.append("result dir exists=%s" % d.exists())
    if d.exists():
        for f in sorted(d.rglob("*")):
            if f.is_file():
                L.append("   %-30s %10d  %s" % (f.name, f.stat().st_size,
                                                __import__("datetime").datetime.fromtimestamp(f.stat().st_mtime).strftime("%m-%d %H:%M")))
    d2 = ROOT / "appdata" / "state" / stem
    L.append("state-stem dir exists=%s" % d2.exists())
    if d2.exists():
        for f in sorted(d2.rglob("*")):
            if f.is_file():
                L.append("   %-30s %10d  %s" % (f.name, f.stat().st_size,
                                                __import__("datetime").datetime.fromtimestamp(f.stat().st_mtime).strftime("%m-%d %H:%M")))

(OUT / "model_def.txt").write_text("\n".join(L) + "\n", encoding="utf-8")
print("ok")
