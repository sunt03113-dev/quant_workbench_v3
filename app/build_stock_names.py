# -*- coding: utf-8 -*-
"""构建 appdata/stock_names.csv（Skill StockNameTool 的本地名称缓存）。

策略：优先东财全A清单（一次拉取）；失败则回退——从 golden 各规则结果 CSV 中
合并已知的 代码/名称 对。两者都不成功则退出非零（由调用方决定后续）。
"""
import csv
import sys
import time
import urllib.request
import json
from pathlib import Path

WORKSPACE = Path(__file__).parent.parent.resolve()
OUT = WORKSPACE / "appdata" / "stock_names.csv"
GOLDEN = WORKSPACE / "golden"

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def fetch_em():
    names = {}
    pn = 1
    while True:
        url = (
            "https://push2.eastmoney.com/api/qt/clist/get?pn=%d&pz=1000&po=1&np=1"
            "&fltt=2&invt=2&fid=f12&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
            "&fields=f12,f14" % pn
        )
        req = urllib.request.Request(url, headers=UA)
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    d = json.loads(r.read().decode("utf-8"))
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))
        diff = (d.get("data") or {}).get("diff") or []
        if not diff:
            break
        for it in diff:
            names[str(it["f12"]).zfill(6)] = it["f14"]
        total = d["data"]["total"]
        if pn * 1000 >= total:
            break
        pn += 1
        time.sleep(0.3)
    return names


def from_golden():
    names = {}
    if not GOLDEN.exists():
        return names
    for f in GOLDEN.glob("*/*.csv"):
        try:
            with open(f, "r", encoding="utf-8-sig", newline="") as fh:
                rd = csv.DictReader(fh)
                if not rd.fieldnames or "股票代码" not in rd.fieldnames or "股票名称" not in rd.fieldnames:
                    continue
                for row in rd:
                    code = str(row.get("股票代码", "")).strip().zfill(6)
                    name = str(row.get("股票名称", "")).strip()
                    if code and name and code != "股票代码":
                        names[code] = name
        except Exception:
            continue
    return names


def local_codes():
    """标准本地行情中的全部标的代码（6 位）。"""
    import yaml
    cfg = yaml.safe_load((Path(__file__).parent / "config.yaml").read_text(encoding="utf-8"))
    appdata = Path(cfg["appdata_dir"]).expanduser().resolve()
    codes = set()
    for sub in ("sh", "sz"):
        d = appdata / "market" / "vipdoc" / sub / "lday"
        if d.exists():
            for f in d.glob("*.day"):
                codes.add(f.stem[2:])
    return codes


def fetch_xq(codes, batch=60, sleep=0.35):
    """雪球批量行情补名（东财不可用时的备用源，实测可用）。

    仅补 codes 中尚未命名的标的；单批失败仅跳过该批，不中断整体。
    """
    import provider  # 复用雪球的 cookie opener
    out = {}
    codes = sorted(codes)
    for i in range(0, len(codes), batch):
        chunk = codes[i:i + batch]
        symbols = ",".join(("SH" if c.startswith("6") else "SZ") + c for c in chunk)
        url = ("https://stock.xueqiu.com/v5/stock/batch/quote.json"
               f"?symbol={symbols}&extend=detail")
        try:
            d = provider._http_json(url, timeout=20, tries=2)
            for it in ((d.get("data") or {}).get("items") or []):
                q = it.get("quote") or {}
                sym = str(q.get("symbol") or ((it.get("market") or {}).get("symbol") or ""))
                nm = str(q.get("name") or "").strip()
                code = str(q.get("code") or "").zfill(6)
                if nm and (code.isdigit() and len(code) == 6):
                    out[code] = nm
                elif nm and len(sym) >= 8:
                    out[sym[-6:]] = nm
        except Exception as exc:  # noqa: BLE001
            print(f"xq batch {i // batch} failed: {exc}")
        time.sleep(sleep)
    return out


def main():
    names = {}
    src = "none"
    try:
        names = fetch_em()
        src = "eastmoney"
        print(f"EM clist: {len(names)} codes")
    except Exception as e:
        print(f"EM failed: {e}")
    if len(names) < 100:
        g = from_golden()
        print(f"golden fallback: {len(g)} codes")
        for k, v in g.items():
            names.setdefault(k, v)
        src = (src + "+golden") if names else "golden"
    # 第三源：雪球补名（本地行情中有、当前缓存缺失的标的）
    try:
        loc = local_codes()
        missing = {c for c in loc if c not in names}
        print(f"local codes={len(loc)} missing={len(missing)}")
        if missing:
            xq = fetch_xq(missing)
            print(f"xq filled: {len(xq)}")
            for k, v in xq.items():
                names.setdefault(k, v)
            src += "+xueqiu"
            still = {c for c in loc if c not in names}
            print(f"still missing after xq: {len(still)} {sorted(still)[:10]}")
    except Exception as e:
        print(f"xq fill failed: {e}")
    if not names:
        print("FAIL: no names available")
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["code", "name"])
        for k in sorted(names):
            w.writerow([k, names[k]])
    print(f"OK src={src} total={len(names)} -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
