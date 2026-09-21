# -*- coding: utf-8 -*-
"""STEP 7 P8 名称回填核验：回测结果中「股票名称」必须来自名称缓存而非兜底文案。"""
import json
import shutil
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "verification" / "step7_win_acceptance"
FALLBACKS = ("未找到标的", "", "N/A", "None")
STEM = "step7_namecheck"

PLAN = {"schema_version": 1, "kind": "day_pattern_backward", "strategy_plan": {
    "universe": "both", "days": [{"offset": 0, "limit_up": True, "amount_max20": True}],
    "outputs": [{"atom": "date", "day": 0}, {"atom": "t_walk", "t0": 0, "t1": 6}]}}


def call(method, path, body=None, timeout=600):
    req = urllib.request.Request("http://127.0.0.1:8000" + path, method=method)
    data = json.dumps(body).encode() if body is not None else None
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, data=data, timeout=timeout) as r:
        return r.status, json.loads(r.read())


def main():
    t0 = time.time()
    st, d = call("POST", "/api/plan/backtest",
                 {"plan": PLAN, "rule_text": "STEP7 名称回填核验：D-0涨停且20日成交额最大", "stem": STEM})
    rows = d.get("rows", [])
    named = [r for r in rows if str(r.get("股票名称", "")).strip() not in FALLBACKS]
    missing = [r for r in rows if str(r.get("股票名称", "")).strip() in FALLBACKS]
    # 覆盖此前缺失的 688175
    target = [r for r in rows if str(r.get("股票代码")) == "688175"]
    check_ok = bool(rows) and len(missing) == 0
    ev = {
        "stem": STEM, "status": d.get("status"), "n_hits": d.get("n_hits"),
        "n_rows_returned": len(rows), "n_named": len(named), "n_missing_name": len(missing),
        "missing_samples": [{"code": r.get("股票代码")} for r in missing[:10]],
        "sample_named": [{"code": r.get("股票代码"), "name": r.get("股票名称")} for r in named[:6]],
        "target_688175": [{"code": r.get("股票代码"), "name": r.get("股票名称"),
                           "date": r.get("D-0日期")} for r in target[:3]],
        "elapsed_sec": round(time.time() - t0, 1),
    }
    (OUT / "p8_namecheck.json").write_text(json.dumps(ev, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
    print(("PASS " if check_ok else "FAIL ") + "P8c 回测结果股票名称全部来自名称缓存"
          + f" | named={len(named)}/{len(rows)} missing={len(missing)}", flush=True)

    # 清理临时模型
    sf = ROOT / "appdata" / "state" / "state.json"
    sj = json.loads(sf.read_text(encoding="utf-8"))
    sj["models"].pop(STEM, None)
    sf.write_text(json.dumps(sj, ensure_ascii=False, indent=1), encoding="utf-8")
    rd = ROOT / "appdata" / "state" / "results" / STEM
    if rd.exists():
        shutil.rmtree(rd, ignore_errors=True)
    print("cleanup done", flush=True)
    sys.exit(0 if check_ok else 1)


if __name__ == "__main__":
    main()
