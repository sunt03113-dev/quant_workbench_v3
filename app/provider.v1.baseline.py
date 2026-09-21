# -*- coding: utf-8 -*-
"""Market Data Provider 增量日线（东财 HTTP → 标准化/校验 → 标准本地行情）。

Skill 不感知 Provider：只写 Skill 可读的 TDX .day 兼容 32 字节记录
  date i32 | open i32分 | high | low | close | amount f32元 | volume i32股 | reserved
单位口径（STEP 1 实测）：东财 volume=手 → ×100=股；amount=元（原样）。

安全设计（冻结要求）：
  - 全部增量先取齐+校验，再统一追加；追加阶段用回滚日志（原尺寸截断），
    任一写入失败 → 已追加部分全部回滚 → 历史行情零破坏。
  - 校验失败的个股跳过（不写入），不影响其他个股。
  - data_date 由扫描 .day 文件得出（executor.data_latest_payload），
    不单独维护"最新完整"标记；回滚保证文件与 data_date 一致。
"""
import json
import logging
import struct
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

logger = logging.getLogger("qwb.provider")

EM_KLINE = ("https://push2his.eastmoney.com/api/qt/stock/kline/get?"
            "secid={secid}&fields1=f1,f2,f3,f4,f5,f6"
            "&fields2=f51,f52,f53,f54,f55,f56,f57&klt=101&fqt=0&beg={beg}&end=20500101")
EM_INDEX = "1.000001"  # 上证指数 → 交易日历
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# 仅覆盖股票（Skill 回测 universe 均为股票）；基金/债券/北交所不在标准行情范围
STOCK_PREFIXES = ("sh600", "sh601", "sh603", "sh605", "sh688",
                  "sz000", "sz001", "sz002", "sz003", "sz300", "sz301")

RETRY = 5
# 东财多镜像轮换（限流/瞬断时自动切换）
_MIRRORS = ("", "21.", "92.", "48.", "7.")


def _url_variants(url):
    if "push2his.eastmoney.com" in url:
        for m in _MIRRORS:
            yield url.replace("push2his.", m + "push2his.") if m else url
    elif "push2.eastmoney.com" in url:
        for m in _MIRRORS:
            yield url.replace("push2.", m + "push2.") if m else url
    else:
        yield url


def _http_json(url, timeout=30, tries=None):
    last = None
    tries = tries or RETRY
    for u in _url_variants(url):
        for i in range(tries):
            try:
                req = urllib.request.Request(u, headers=UA)
                if "xueqiu.com" in u:
                    resp = _xq_opener_().open(req, timeout=timeout)
                else:
                    resp = urllib.request.urlopen(req, timeout=timeout)
                with resp:
                    return json.loads(resp.read().decode("utf-8"))
            except Exception as exc:  # 网络限流/瞬断：退避重试
                last = exc
                time.sleep(1.0 + 1.5 * i)
    raise last


def _secid(market, code6):
    return ("1." if market == "sh" else "0.") + code6


# ───────────────────────── 数据源 ─────────────────────────
# 主源：东财 push2his kline（fqt=0 不复权，volume 手→×100 股）
# 备源：雪球 chart/kline（type=normal 不复权，volume 已为股，amount 元）
# 两源均与 TDX .day 口径做交叉验证（见 STEP 5 测试）。


def trade_dates(beg=20250101, source="em"):
    """交易日列表（升序 int YYYYMMDD）。东财不可用时自动切换雪球。"""
    if source == "em":
        try:
            return _trade_dates_em(beg)
        except Exception as exc:
            logger.warning("东财交易日历不可用(%s)，切换雪球", exc)
    return _trade_dates_xq(beg)


def _trade_dates_em(beg):
    d = _http_json(EM_KLINE.format(secid=EM_INDEX, beg=beg),
                   timeout=8, tries=1)  # 探测用快速失败，慢/挂起立即切备源
    return [int(line.split(",")[0].replace("-", ""))
            for line in d["data"]["klines"]]


def _trade_dates_xq(beg):
    from datetime import datetime, timezone, timedelta
    tz8 = timezone(timedelta(hours=8))
    begin_ms = int(datetime.strptime(str(beg), "%Y%m%d")
                   .replace(tzinfo=tz8).timestamp() * 1000)
    url = ("https://stock.xueqiu.com/v5/stock/chart/kline.json"
           f"?symbol=SH000001&begin={begin_ms}&period=day&type=normal"
           "&count=300&indicator=kline")  # 正count：从 begin 起向后
    d = _http_json(url)
    i_ts = d["data"]["column"].index("timestamp")
    return [int(datetime.fromtimestamp(row[i_ts] / 1000, tz=tz8)
                .strftime("%Y%m%d")) for row in d["data"]["item"]]


# ───────────────────────── 抓取 + 标准化 ─────────────────────────


def fetch_daily(market, code6, beg, source="em"):
    """抓取某标的 beg(int YYYYMMDD) 起日线 → [(date,o分,h分,l分,c分,amount元,vol股)]。"""
    if source == "xq":
        return _fetch_daily_xq(market, code6, beg)
    return _fetch_daily_em(market, code6, beg)


def _fetch_daily_em(market, code6, beg):
    d = _http_json(EM_KLINE.format(secid=_secid(market, code6), beg=beg))
    kl = (d.get("data") or {}).get("klines") or []
    out = []
    for line in kl:
        dt, o, c, h, low, vol, amt = line.split(",")  # f51..f57 顺序
        # 东财价格元(2位小数) → 分；volume 手 → 股(×100)；amount 元
        out.append((int(dt.replace("-", "")),
                    int(round(float(o) * 100)), int(round(float(h) * 100)),
                    int(round(float(low) * 100)), int(round(float(c) * 100)),
                    float(amt), int(round(float(vol) * 100))))
    return out


_xq_opener = None


def _xq_opener_():
    global _xq_opener
    if _xq_opener is None:
        import http.cookiejar
        cj = http.cookiejar.CookieJar()
        _xq_opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cj))
        _xq_opener.open(urllib.request.Request(
            "https://xueqiu.com/hq", headers=UA), timeout=20).read()
    return _xq_opener


def _fetch_daily_xq(market, code6, beg):
    from datetime import datetime, timezone, timedelta
    tz8 = timezone(timedelta(hours=8))
    begin_ms = int(datetime.strptime(str(beg), "%Y%m%d")
                   .replace(tzinfo=tz8).timestamp() * 1000)
    symbol = market.upper() + code6
    url = ("https://stock.xueqiu.com/v5/stock/chart/kline.json"
           f"?symbol={symbol}&begin={begin_ms}&period=day&type=normal"
           "&count=250&indicator=kline")  # 正count：从 beg 起向后（覆盖约1年）
    d = _http_json(url)
    it = d["data"]
    cols = it["column"]
    i = {k: cols.index(k) for k in
         ("timestamp", "volume", "open", "high", "low", "close", "amount")}
    out = []
    for row in it["item"]:
        if row[i["open"]] is None:
            continue
        dt = int(datetime.fromtimestamp(row[i["timestamp"]] / 1000, tz=tz8)
                 .strftime("%Y%m%d"))
        out.append((dt,
                    int(round(row[i["open"]] * 100)),
                    int(round(row[i["high"]] * 100)),
                    int(round(row[i["low"]] * 100)),
                    int(round(row[i["close"]] * 100)),
                    float(row[i["amount"]]),
                    int(round(row[i["volume"]]))))  # 雪球 volume 已为股
    return out


def validate_records(recs, last_local_date):
    """逐条硬校验；返回 (ok_recs, problems)。任一问题 → 整个个股跳过。"""
    problems = []
    prev_date = last_local_date or 0
    for (dt, o, h, low, c, amt, vol) in recs:
        if dt <= prev_date:
            problems.append(f"日期未递增: {dt} <= {prev_date}")
        if o <= 0 or h <= 0 or low <= 0 or c <= 0:
            problems.append(f"{dt} 非正价格")
        if not (h >= low and h >= max(o, c) and low <= min(o, c)):
            problems.append(f"{dt} OHLC 不自洽 H={h} L={low} O={o} C={c}")
        if amt < 0 or vol < 0:
            problems.append(f"{dt} 量额为负")
        prev_date = dt
    return recs, problems


def encode_record(rec):
    dt, o, h, low, c, amt, vol = rec
    # 保留位写 0：TDX 基线本身 0/65536 混杂（该字段无语义，Skill 不读取）
    return struct.pack("<5ifii", dt, o, h, low, c, amt, vol, 0)


# ───────────────────────── 增量更新 ─────────────────────────


def _last_date_of(path):
    import numpy as np
    n = path.stat().st_size // 32
    if n == 0:
        return 0
    with open(path, "rb") as f:
        f.seek((n - 1) * 32)
        return struct.unpack("<i", f.read(4))[0]


def update(day_dirs, universe_filter=True, max_workers=6, progress_cb=None,
           force_beg=None):
    """检查本地最新交易日 → 抓缺失交易日 → 校验 → 追加（带回滚）。

    返回 summary dict。任何失败保证不破坏既有历史（回滚追加段）。
    """
    dirs = [Path(d) for d in day_dirs]
    files = []
    for d in dirs:
        for f in sorted(d.glob("*.day")):
            if universe_filter and not f.name[:5].startswith(
                    tuple(STOCK_PREFIXES)):
                continue
            files.append(f)
    if not files:
        return {"status": "NO_DATA", "detail": "标准行情目录为空"}

    # 1) 本地最新交易日（全股票池最大值）
    local_last = max(_last_date_of(f) for f in files)
    if progress_cb:
        progress_cb(f"本地行情截至 {local_last}，查询交易日历…")
    # 源选择：东财优先，不可用自动切雪球（整轮统一，保证口径一致）
    src = "em"
    try:
        cal = _trade_dates_em(beg=local_last)
    except Exception as exc:
        logger.warning("东财不可用(%s)，整轮切换雪球源", exc)
        src = "xq"
        cal = _trade_dates_xq(beg=local_last)
    missing_days = [d for d in cal if d > local_last]
    if force_beg:
        beg = force_beg
        missing_days = [d for d in cal if d >= force_beg]
    else:
        beg = local_last + 1 if missing_days else None
    if not missing_days:
        return {"status": "UP_TO_DATE", "local_last": local_last,
                "latest_trade_date": cal[-1] if cal else local_last,
                "updated_files": 0}

    if progress_cb:
        progress_cb(f"缺失 {len(missing_days)} 个交易日，抓取 {len(files)} 个标的…")

    # 2) 并发抓取 + 校验（失败个股跳过，不入库；下次运行按个股自身 beg 自愈补齐）
    plan = {}      # file -> bytes to append
    errors = []
    done = [0]

    def work(f):
        market = f.parent.parent.name  # .../vipdoc/sh/lday
        code6 = f.stem[2:]
        own_last = _last_date_of(f)
        beg_own = max(own_last + 1, 19901219)  # 个股自身水位，自愈历史漏补
        recs = fetch_daily(market, code6, beg_own, source=src)
        return f, recs, own_last

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(work, f): f for f in files}
        for fut in as_completed(futs):
            f = futs[fut]
            try:
                _f, recs, own_last = fut.result()
                recs = [r for r in recs if r[0] >= max(own_last + 1,
                                                       force_beg or 0)]
                ok, probs = validate_records(recs, own_last)
                if probs:
                    errors.append({"file": f.name, "skipped": True,
                                   "problems": probs[:3]})
                elif ok:
                    plan[f] = b"".join(encode_record(r) for r in ok)
            except Exception as exc:
                errors.append({"file": f.name, "skipped": True,
                               "problems": [f"抓取失败: {exc}"]})
            done[0] += 1
            if progress_cb and done[0] % 500 == 0:
                progress_cb(f"抓取进度 {done[0]}/{len(files)}")

    # 3) 追加（回滚日志保护）
    journal = []
    try:
        for f, blob in plan.items():
            if not blob:
                continue
            size0 = f.stat().st_size
            journal.append((f, size0))
            with open(f, "ab") as fh:
                fh.write(blob)
    except Exception as exc:
        # 回滚：截回原尺寸
        for f, size0 in journal:
            try:
                with open(f, "r+b") as fh:
                    fh.truncate(size0)
            except OSError:
                logger.exception("回滚失败 %s", f)
        raise RuntimeError(f"写入失败，已回滚全部追加（历史行情未破坏）: {exc}")

    new_last = max(_last_date_of(f) for f in plan) if plan else local_last
    return {"status": "OK", "local_last_before": local_last,
            "appended_days": missing_days, "new_last": new_last,
            "updated_files": len(plan), "source": src,
            "skipped": len(errors), "errors": errors[:50]}


# ───────────────────────── 新股补建（可选能力） ─────────────────────────


def fetch_new_stocks(day_dirs, max_workers=6, progress_cb=None):
    """东财全A清单 - 本地已有 = 新上市标的，补建完整历史 .day 文件。"""
    url = ("https://push2.eastmoney.com/api/qt/clist/get?pn={pn}&pz=100&po=1&np=1"
           "&fltt=2&fid=f12&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
           "&fields=f12,f13,f14")
    existing = set()
    for d in day_dirs:
        for f in Path(d).glob("*.day"):
            existing.add(f.name[:2] + f.stem[2:])
    new_list = []
    pn = 1
    while True:
        d = _http_json(url.format(pn=pn))
        diff = d["data"]["diff"]
        if not diff:
            break
        for it in diff:
            mk = it["f13"]  # 1=SH 0=SZ
            code = it["f12"]
            pref = "sh" if mk == 1 else "sz"
            if (pref + code) not in existing and (pref + code).startswith(
                    tuple(STOCK_PREFIXES)):
                new_list.append((pref, code, it.get("f14", "")))
        if len(diff) < 100:
            break
        pn += 1
        if pn > 80:
            break
    created = []
    for pref, code, name in new_list:
        try:
            recs = fetch_daily(pref, code, 19901219)
            if not recs:
                continue
            target = None
            for d in day_dirs:
                if Path(d).parent.name == pref:
                    target = Path(d) / (pref + code + ".day")
                    break
            if target is None or target.exists():
                continue
            ok, probs = validate_records(recs, 0)
            if probs:
                continue
            target.write_bytes(b"".join(encode_record(r) for r in ok))
            created.append({"code": pref + code, "name": name,
                            "bars": len(ok)})
        except Exception as exc:
            logger.warning("新股补建失败 %s%s: %s", pref, code, exc)
    return created
