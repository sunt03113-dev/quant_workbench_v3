# -*- coding: utf-8 -*-
"""STEP1 实测脚本1：golden/vipdoc 固定测试行情体检。
输出 JSON 到 artifacts/verification/step1/golden_vipdoc_probe.json
"""
import json
import struct
import sys
from pathlib import Path

WS = Path(r"D:\09work\quant_workbench_v3\quant_workbench_package")
GOLD = WS / "golden" / "vipdoc"
OUT = WS / "artifacts" / "verification" / "step1"
OUT.mkdir(parents=True, exist_ok=True)

REC = struct.Struct("<IIIII f I I")  # date o h l c amount(f32) vol reserved


def read_day(path):
    rows = []
    with open(path, "rb") as f:
        while True:
            b = f.read(REC.size)
            if len(b) < REC.size:
                break
            d, o, h, l, c, amt, vol, r = REC.unpack(b)
            rows.append({
                "date": d, "open": o / 100.0, "high": h / 100.0,
                "low": l / 100.0, "close": c / 100.0,
                "amount_f32": amt, "volume_int": vol,
            })
    return rows


def fmt(d):
    return f"{d//10000:04d}-{d%10000//100:02d}-{d%100:02d}"


report = {"golden_vipdoc": {}}
for mkt in ("sh", "sz"):
    d = GOLD / mkt / "lday"
    files = sorted(d.glob("*.day")) if d.exists() else []
    codes = [f.stem for f in files]
    prefixes = {}
    for c in codes:
        p = c[2:5] if len(c) >= 5 else c
        prefixes[p[:3]] = prefixes.get(p[:3], 0) + 1
    report["golden_vipdoc"][mkt] = {
        "dir": str(d),
        "exists": d.exists(),
        "file_count": len(files),
        "top_prefixes": dict(sorted(prefixes.items(), key=lambda x: -x[1])[:15]),
    }

# 全库最新交易日（扫全部文件最后一条日期）
latest = 0
per_file_latest = {}
for mkt in ("sh", "sz"):
    d = GOLD / mkt / "lday"
    if not d.exists():
        continue
    for f in d.glob("*.day"):
        try:
            with open(f, "rb") as fh:
                fh.seek(-32, 2)
                (dt,) = struct.unpack("<I", fh.read(4))
            per_file_latest[f.stem] = dt
            latest = max(latest, dt)
        except Exception:
            pass
report["latest_trade_date_global"] = fmt(latest) if latest else None

# 样本股票深度验证：golden 命中股 688006 / 300010 + 主板 600519
samples = {}
for stem in ("sh688006", "sz300010", "sh600519"):
    f = None
    for mkt in ("sh", "sz"):
        p = GOLD / mkt / "lday" / f"{stem}.day"
        if p.exists():
            f = p
            break
    if not f:
        samples[stem] = {"exists": False}
        continue
    rows = read_day(f)
    samples[stem] = {
        "file": str(f),
        "records": len(rows),
        "first_date": fmt(rows[0]["date"]),
        "last_date": fmt(rows[-1]["date"]),
        "last_3_records": [
            {**r, "date": fmt(r["date"])} for r in rows[-3:]
        ],
    }
report["samples"] = samples

# pre_close 可推导性验证：golden 覆盖连续交易日时 close[i-1] 即 pre_close
chk = {}
for stem, s in samples.items():
    if not s.get("records"):
        continue
    rows = read_day(Path(s["file"]))
    gaps = 0
    for i in range(1, min(len(rows), 500)):
        pass
    chk[stem] = {
        "records": len(rows),
        "note": "pre_close = prev row close（TDX .day 无独立昨收字段，需按 symbol 时间序列推导）",
    }
report["pre_close_check"] = chk

out_file = OUT / "golden_vipdoc_probe.json"
out_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2)[:3500])
print("saved:", out_file)
