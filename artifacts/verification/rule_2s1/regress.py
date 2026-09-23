# -*- coding: utf-8 -*-
"""2S1 修复回归：golden 26/26 + 门禁负例 + 2S1 端到端实跑。证据落 regression_result.json。"""
import json
import pathlib
import re
import subprocess
import sys

WS = pathlib.Path(r"D:\09work\quant_workbench_v3\quant_workbench_package")
EV = WS / "artifacts" / "verification" / "rule_2s1"
sys.path.insert(0, str(WS / "app"))

out = {}

# ---- 1) golden 26/26（golden_test.py 子进程，解析判定映射） ----
py = r"C:\Users\21412\.workbuddy\binaries\python\envs\qwb\Scripts\python.exe"
r = subprocess.run([py, "-X", "utf8", str(WS / "app" / "golden_test.py")],
                   capture_output=True, text=True, encoding="utf-8", errors="replace",
                   cwd=str(WS / "app"))
golden_txt = r.stdout
(EV / "golden_after_2s1fix.txt").write_text(golden_txt, encoding="utf-8")
verdicts = dict(re.findall(r"=== (\S+) ===\s*-> (\S+)", golden_txt))
out["golden_n"] = len(verdicts)
out["golden_verdicts"] = verdicts
base = (WS / "artifacts/verification/rule_10cm/golden_after_notation_skip.txt").read_text(encoding="utf-8")
base_verdicts = dict(re.findall(r"=== (\S+) ===\s*-> (\S+)", base))
out["golden_match_baseline"] = verdicts == base_verdicts
if verdicts != base_verdicts:
    out["golden_diff"] = {k: (base_verdicts.get(k), verdicts.get(k))
                          for k in set(base_verdicts) | set(verdicts)
                          if base_verdicts.get(k) != verdicts.get(k)}

# ---- 2) 门禁负例 ----
import recognizer  # noqa: E402

neg = {
    "yang_residue_failclosed": "【20cm】\n【筛选条件】\nD-0：不涨停，旭阳\n",
    "t_walk_needs_zoushi": "【20cm】\n【筛选条件】\nD-0：涨停\n【输出指标】\nT+0~T+6：振幅\n",
}
pos = {
    "candle_variants": ["K线为阴", "收盘为阳", "收为阴", "定为阴", "收定为阴线", "收阳", "阴线"],
    "amt_huanbi_range": "【20cm】\n【筛选条件】\nD-0：涨停\n【输出指标】\nD-0/D-1：成交额环比\n",
    "t_wave_tilde": "【20cm】\n【筛选条件】\nD-0：涨停\n【输出指标】\nT+0~T+6：价格走势\n",
}
out["neg"] = {}
for k, t in neg.items():
    out["neg"][k] = recognizer.recognize(t)["status"]
out["pos"] = {}
for i, c in enumerate(pos["candle_variants"]):
    text = f"【20cm】\n【筛选条件】\nD-0：不涨停，{c}\n"
    res = recognizer.recognize(text)
    ok = res["status"] == "READY"
    candle = None
    if ok:
        for d in res["plan"]["strategy_plan"]["days"]:
            if d.get("offset") == 0:
                candle = d.get("candle")
    out["pos"][f"candle_{i}_{c}"] = {"status": res["status"], "candle": candle}
for k in ("amt_huanbi_range", "t_wave_tilde"):
    res = recognizer.recognize(pos[k])
    atoms = None
    if res["status"] == "READY":
        atoms = [o["atom"] for o in res["plan"]["strategy_plan"]["outputs"]]
    out["pos"][k] = {"status": res["status"], "atoms": atoms}
# t_wave 正例必须真实产出 t_walk（空输出兜底是 [date,t_walk]，混不出来）
out["pos"]["t_wave_tilde"]["strict_pass"] = (
    out["pos"]["t_wave_tilde"]["status"] == "READY"
    and out["pos"]["t_wave_tilde"]["atoms"] is not None
    and "t_walk" in out["pos"]["t_wave_tilde"]["atoms"]
    and out["pos"]["t_wave_tilde"]["atoms"] != ["date", "t_walk"])

# ---- 3) 2S1 全文识别 + 端到端实跑 ----
text = (EV / "rule_2s1_ui.txt").read_text(encoding="utf-8").replace("\ufeff", "")
res = recognizer.recognize(text)
out["rule_2s1"] = {"status": res["status"]}
if res["status"] == "READY":
    plan = res["plan"]
    out["rule_2s1"]["summary"] = recognizer._plan_summary(plan)
    import executor  # noqa: E402
    rows, columns, meta = executor.run_plan(plan)
    viol = executor.validate_rows(plan, rows, columns)
    out["rule_2s1"]["e2e"] = {"n_rows": len(rows), "n_cols": len(columns),
                              "recheck_violations": len(viol),
                              "sample": rows[0] if rows else None}
(EV / "regression_result.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
print("done")
