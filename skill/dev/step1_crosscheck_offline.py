# -*- coding: utf-8 -*-
"""STEP1 实测脚本5：离线交叉校验——已保存的东财样本 vs golden TDX .day。
覆盖 sh600519 / sz300010（样本文件里有 300010 的 kline fqt0 数据）。
"""
import json
import struct
from pathlib import Path

WS = Path(r"D:\09work\quant_workbench_v3\quant_workbench_package")
OUT = WS / "artifacts" / "verification" / "step1"

raw = json.loads((OUT / "eastmoney_raw_samples.json").read_text(encoding="utf-8"))

REC = struct.Struct("<IIIII f I I")


def tdx_tail(path, n=5):
    rows = []
    with open(path, "rb") as f:
        while True:
            b = f.read(REC.size)
            if len(b) < REC.size:
                break
            rows.append(REC.unpack(b))
    return rows[-n:]


report = {}
cases = [
    ("sh600519", WS / "golden/vipdoc/sh/lday/sh600519.day", raw["kline_sh600519_fqt0"]),
    ("sz300010", WS / "golden/vipdoc/sz/lday/sz300010.day", raw["kline_sz300010_fqt0"]),
]
for name, dayf, emjson in cases:
    em_rows = {r.split(",")[0]: r.split(",") for r in emjson["data"]["klines"]}
    tdx = tdx_tail(dayf, 10)
    per_day = []
    for d, o, h, l, c, amt, vol, _r in tdx:
        ds = f"{d//10000:04d}-{d%10000//100:02d}-{d%100:02d}"
        if ds not in em_rows:
            continue
        e = em_rows[ds]
        em_amt = float(e[6])
        em_vol = float(e[5])
        per_day.append({
            "date": ds,
            "ohlc_match": all(abs(a - float(b)) < 0.005 for a, b in
                              [(o/100, e[1]), (c/100, e[2]), (h/100, e[3]), (l/100, e[4])]),
            "amount_rel_diff": round(abs(amt - em_amt) / max(em_amt, 1), 5),
            "vol_ratio_tdx_over_em": round(vol / em_vol, 2) if em_vol else None,
        })
    report[name] = {
        "em_rows": len(em_rows), "tdx_matched_days": per_day,
        "summary": {
            "all_ohlc_match": all(x["ohlc_match"] for x in per_day),
            "amount_within_1pct": all(x["amount_rel_diff"] < 0.01 for x in per_day),
            "vol_ratio": per_day[-1]["vol_ratio_tdx_over_em"] if per_day else None,
        },
    }

(OUT / "tdx_vs_eastmoney_crosscheck.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
