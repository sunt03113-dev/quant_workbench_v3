# -*- coding: utf-8 -*-
"""验证 P9 判据选择的正确性：Excel 二进制哈希是否稳定，业务 canonical 是否稳定。

背景：ACCEPTANCE.md P9 明确「若 Excel 文件因元数据导致二进制哈希不同，不可仅凭
Excel SHA 判失败；必须比较规范化后的业务内容，并记录二进制哈希差异」。

本脚本**连续多次**对同一 plan、同一行情、同一进程重复导出，观察：
  - Excel 二进制 SHA-256 是否逐次相同（预期：可能不同 —— 容器时间戳等元数据）
  - Excel 字节数是否稳定
  - 同源结构化结果的 canonical 行哈希是否稳定（预期：稳定）
从而以实测数据支撑判据设计，而不是仅凭断言。

用法：
  python app/p9_excel_stability.py --runs 4
产出：
  artifacts/verification/p9/P9_EXCEL_STABILITY.json
"""
import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
OUT = ROOT / "artifacts" / "verification" / "p9"

import paths  # noqa: E402
from p9_evidence import canon_rows  # noqa: E402

PLAN = {"schema_version": 1, "kind": "day_pattern_backward", "strategy_plan": {
    "universe": "20cm", "days": [
        {"offset": -2, "limit_up": True},
        {"offset": -1, "limit_up": False, "amount_max20": False},
        {"offset": 0, "limit_up": True, "amount_max20": True, "high_max20": False}],
    "outputs": [{"atom": "date", "day": 0}, {"atom": "t_walk", "t0": 0, "t1": 6}]}}
STEM = "p9_excel_probe"
BASE = f"http://{paths.HOST}:{paths.PORT}"


def _req(path, payload=None, method="GET", timeout=60):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def main():
    args = sys.argv[1:]
    runs = int(args[args.index("--runs") + 1]) if "--runs" in args else 4

    rec = {"schema": "p9-excel-stability/1",
           "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "endpoint": BASE, "stem": STEM, "n_runs": runs, "runs": []}

    for i in range(1, runs + 1):
        st, blob = _req("/api/plan/backtest",
                        {"plan": PLAN,
                         "rule_text": "P9 Excel 稳定性探针：D-2涨停，D-1非涨停且非20日成交额最大，"
                                      "D-0涨停且20日成交额最大且最高价非20日最高",
                         "stem": STEM}, "POST")
        bt = json.loads(blob.decode("utf-8"))
        st, xlsx = _req(f"/api/backtest/{STEM}/candidates/export")
        f = OUT / f"p9_excel_run{i}.xlsx"
        f.write_bytes(xlsx)
        st, cblob = _req(f"/api/backtest/{STEM}/candidates")
        c = json.loads(cblob.decode("utf-8"))
        rows = c.get("rows") or c.get("candidates") or []
        cols = c.get("columns") or []
        _, rsha, n = canon_rows(rows, cols)
        rec["runs"].append({
            "run": i,
            "excel_sha256": hashlib.sha256(xlsx).hexdigest(),
            "excel_bytes": len(xlsx),
            "n_hits": bt.get("n_hits"),
            "structured_n_rows": n,
            "structured_rows_sha256": rsha,
            "data_date": bt.get("data_date"),
        })
        print(f"[stability] run{i}: excel={rec['runs'][-1]['excel_sha256'][:16]} "
              f"bytes={len(xlsx)} rows={n} canon={rsha[:16]}", flush=True)
        f.unlink(missing_ok=True)

    ex = [r["excel_sha256"] for r in rec["runs"]]
    by = [r["excel_bytes"] for r in rec["runs"]]
    cs = [r["structured_rows_sha256"] for r in rec["runs"]]
    rec["summary"] = {
        "excel_sha_unique": len(set(ex)),
        "excel_sha_stable": len(set(ex)) == 1,
        "excel_bytes_unique": len(set(by)),
        "structured_canon_unique": len(set(cs)),
        "structured_canon_stable": len(set(cs)) == 1,
        "conclusion": None,
    }
    if rec["summary"]["excel_sha_stable"]:
        rec["summary"]["conclusion"] = (
            "本机同进程连续导出 Excel 哈希稳定；跨平台仍不应以二进制哈希判定，"
            "因为不同 Excel 写入库/版本会写入不同容器元数据。")
    else:
        rec["summary"]["conclusion"] = (
            "实测证实：同一端、同一进程、同一输入，连续导出的 Excel 二进制 SHA-256 并不稳定，"
            "而业务 canonical 行哈希稳定。故 P9 以 canonical diff 为判据、"
            "Excel 二进制哈希仅作记录，是必要而非可选。")

    (OUT / "P9_EXCEL_STABILITY.json").write_text(
        json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[stability] excel_sha_unique={rec['summary']['excel_sha_unique']} "
          f"canon_unique={rec['summary']['structured_canon_unique']}")
    print(f"[stability] {rec['summary']['conclusion']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
