# -*- coding: utf-8 -*-
"""STEP1 实测脚本3：东方财富日线K线 HTTP API 探针（增量Provider候选）。
验证 DATA.md 最低 schema、复权口径(fqt=0)、volume/amount单位、pre_close、
证券属性（名称/ST、上市日期）、时间范围、当日完整性。
原始样本保存到 artifacts/verification/step1/。
"""
import json
import urllib.request
from datetime import date
from pathlib import Path

WS = Path(r"D:\09work\quant_workbench_v3\quant_workbench_package")
OUT = WS / "artifacts" / "verification" / "step1"
OUT.mkdir(parents=True, exist_ok=True)

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def kline(secid, beg, end, fqt="0"):
    url = ("https://push2his.eastmoney.com/api/qt/stock/kline/get"
           f"?secid={secid}&fields1=f1,f2,f3,f4,f5,f6"
           "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
           f"&klt=101&fqt={fqt}&beg={beg}&end={end}")
    return fetch(url)


def quote(secid):
    url = (f"https://push2.eastmoney.com/api/qt/stock/get?secid={secid}"
           "&fields=f57,f58,f26,f60,f84,f85,f116,f117,f162,f167")
    return fetch(url)


samples = {}
# fqt=0 不复权（冻结口径）；多只样本股
for name, secid in [("sh600519", "1.600519"), ("sz300010", "0.300010"),
                    ("sh688006", "1.688006"), ("sz000001", "0.000001")]:
    d = kline(secid, "20260901", "20260918")
    samples[f"kline_{name}_fqt0"] = d
    q = quote(secid)
    samples[f"quote_{name}"] = q

# 复权口径对照：同一股票 fqt=1 前复权 vs fqt=0，验证单位差异
samples["kline_sh600519_fqt1_5d"] = kline("1.600519", "20260901", "20260918", fqt="1")

# 指数行情 → 交易日历来源候选（sh000001 上证指数）
samples["kline_index_sh000001"] = kline("1.000001", "20260901", "20260918")

# 保存原始样本
(OUT / "eastmoney_raw_samples.json").write_text(
    json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8")

# ---- 结构化验证摘要 ----
report = {"probe_date": str(date.today()), "checks": {}}
k = samples["kline_sh600519_fqt0"]["data"]
kl = k["klines"][-3:]
name = k["name"]
code = k["code"]
report["meta"] = {"code": code, "name": name, "prePrice_field_present": "prePrice" in k}

# 字段语义（东方财富 klt=101 fields2 定义）：
# f51日期 f52开 f53收 f54高 f55低 f56成交量(手) f57成交额(元) f58振幅 f59涨跌幅 f60涨跌额 f61换手率
row = kl[-1]
parts = row.split(",")
d0, o, c, h, l, vol, amt, amp, pct, chg, turn = parts
report["checks"]["schema_map"] = {
    "trade_date": d0, "open": o, "close": c, "high": h, "low": l,
    "volume_raw": vol + " (假设:手)", "amount_raw": amt + " (假设:元)",
    "amplitude": amp, "pct_chg": pct, "chg": chg,
}
pre_close_calc = float(c) - float(chg)
report["checks"]["pre_close_derived"] = pre_close_calc
# 昨日收盘对照
prev = samples["kline_sh600519_fqt0"]["data"]["klines"][-2].split(",")
report["checks"]["prev_day_close"] = prev[2]
report["checks"]["pre_close_matches_prev_close"] = abs(pre_close_calc - float(prev[2])) < 0.01

# 复权对照
fqt1 = samples["kline_sh600519_fqt1_5d"]["data"]["klines"][-1].split(",")
report["checks"]["fqt0_last_close"] = c
report["checks"]["fqt1_last_close"] = fqt1[2]
report["checks"]["fqt_differs"] = c != fqt1[2]

# 当日完整性判断素材：最新K线日期 vs 今天
report["latest_kline_date"] = d0
report["today"] = str(date.today())

# 证券属性样本
q = samples["quote_sh600519"]["data"]
report["security_master_sample"] = {
    "code": q.get("f57"), "name": q.get("f58"),
    "listing_date_raw": q.get("f26"),
    "note": "f26=上市日期(YYYYMMDD)；名称含ST前缀可判ST状态",
}
q2 = samples["quote_sz300010"]["data"]
report["security_master_sample_2"] = {"code": q2.get("f57"), "name": q2.get("f58"),
                                      "listing_date_raw": q2.get("f26")}

(OUT / "eastmoney_probe_report.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
