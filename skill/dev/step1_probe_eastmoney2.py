# -*- coding: utf-8 -*-
"""STEP1 实测脚本4：东财全A股票清单 + 深市 volume/amount 单位交叉验证。"""
import json
import struct
import urllib.request
from pathlib import Path

WS = Path(r"D:\09work\quant_workbench_v3\quant_workbench_package")
OUT = WS / "artifacts" / "verification" / "step1"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def fetch(url, tries=4):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            last = e
            import time
            time.sleep(1.5 * (i + 1))
    raise last


report = {}

# 1) 全A清单（沪深A股，含名称/代码）——stock_names 与 security master 来源候选
url = ("https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=5&po=1&np=1"
       "&fltt=2&invt=2&fid=f12&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
       "&fields=f12,f14,f26,f100")
try:
    d = fetch(url, tries=2)
    report["clist_sample"] = {"total": d["data"]["total"], "first5": d["data"]["diff"][:5]}
    (OUT / "eastmoney_clist_sample.json").write_text(
        json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
except Exception as e:  # noqa: BLE001
    report["clist_sample"] = {"error": repr(e)}

# 2) 深市单位验证：300010 2026-09-18 东财 vs TDX .day 原始记录
def kline(secid, beg, end):
    url = ("https://push2his.eastmoney.com/api/qt/stock/kline/get"
           f"?secid={secid}&fields1=f1,f2,f3,f4,f5,f6"
           "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
           f"&klt=101&fqt=0&beg={beg}&end={end}")
    return fetch(url)


em = kline("0.300010", "20260916", "20260918")["data"]["klines"]
report["em_300010"] = em

REC = struct.Struct("<IIIII f I I")
day_path = WS / "golden" / "vipdoc" / "sz" / "lday" / "sz300010.day"
rows = []
with open(day_path, "rb") as f:
    while True:
        b = f.read(REC.size)
        if len(b) < REC.size:
            break
        rows.append(REC.unpack(b))
tdx_last = rows[-1]
report["tdx_300010_last"] = {
    "date": tdx_last[0], "open": tdx_last[1] / 100, "high": tdx_last[2] / 100,
    "low": tdx_last[3] / 100, "close": tdx_last[4] / 100,
    "amount_f32_yuan": tdx_last[5], "volume_int_shares": tdx_last[6],
}
# 单位推断：amount/volume ≈ 每股均价
em_parts = em[-1].split(",")
em_amt, em_vol = float(em_parts[6]), float(em_parts[5])
report["unit_check"] = {
    "em_amount": em_amt, "em_volume": em_vol,
    "em_amount_per_volume": round(em_amt / (em_vol * 100), 3),
    "tdx_amount_per_volume": round(tdx_last[5] / tdx_last[6], 3),
    "close": float(em_parts[2]),
    "conclusion": "若 amount/(volume*100)≈每股均价 则 em volume=手; TDX volume=股",
}

# 3) TDX vs 东财 一致性（OHLC + amount）
tdx_o, tdx_h, tdx_l, tdx_c = tdx_last[1]/100, tdx_last[2]/100, tdx_last[3]/100, tdx_last[4]/100
report["consistency_300010"] = {
    "open_match": abs(tdx_o - float(em_parts[1])) < 0.005,
    "high_match": abs(tdx_h - float(em_parts[3])) < 0.005,
    "low_match": abs(tdx_l - float(em_parts[4])) < 0.005,
    "close_match": abs(tdx_c - float(em_parts[2])) < 0.005,
    "amount_match_rel": abs(tdx_last[5] - em_amt) / max(em_amt, 1) < 0.01,
}

(OUT / "eastmoney_unit_crosscheck.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
