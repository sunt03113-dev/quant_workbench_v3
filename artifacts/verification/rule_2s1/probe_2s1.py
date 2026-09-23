# -*- coding: utf-8 -*-
"""2S1 识别失败复现：UI 原文逐字 + 逐行隔离。证据落 probe_result.json。"""
import json
import pathlib
import sys

WS = pathlib.Path(r"D:\09work\quant_workbench_v3\quant_workbench_package")
sys.path.insert(0, str(WS / "app"))
import recognizer  # noqa: E402

EV = WS / "artifacts" / "verification" / "rule_2s1"
text = (EV / "rule_2s1_ui.txt").read_text(encoding="utf-8").replace("\ufeff", "")

res = recognizer.recognize(text)
out = {"status": res["status"]}
if res["status"] == "FAILED":
    out["problems"] = res["failure"]["detail"]["problems"]
# 逐行隔离：单行条件/输出各自能否被解析
lines = [l.strip() for l in text.splitlines() if l.strip()]
per_line = []
for l in lines:
    if l.startswith("【"):
        continue
    r = recognizer.recognize(l)
    per_line.append({
        "line": l,
        "ok": r["status"] != "FAILED",
        "fragments": [] if r["status"] != "FAILED" else
            [p["fragment"] for p in r["failure"]["detail"]["problems"]],
    })
out["per_line"] = per_line
(EV / "probe_result.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print("status =", out["status"])
for p in out.get("problems", []):
    print("PROBLEM:", p.get("fragment"), "|", str(p.get("reason"))[:100])
print("---- per-line ----")
for e in per_line:
    print(("OK  " if e["ok"] else "FAIL"), e["line"], e["fragments"] or "")
