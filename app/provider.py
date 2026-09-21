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
# 全A批量快照（收盘后）：一次请求 100 只，约 56 页拉完 5560 只。
# 用于「单日增量」快速路径：收盘后当日日线定型，无需逐只 kline（5544 请求，
# 东财限流下可达数小时）。fs 覆盖沪深主板/创业板/科创板，与 STOCK_PREFIXES 同一股票池。
EM_CLIST = ("https://push2.eastmoney.com/api/qt/clist/get?"
            "pn={pn}&pz=100&po=0&np=1&fltt=2&invt=2&fid=f12"
            "&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
            "&fields=f12,f13,f2,f5,f6,f15,f16,f17")
# 快照口径：f2=最新价(收盘) f5=成交量(手) f6=成交额(元) f15/f16/f17=高/低/开，单位与
# kline 主源一致（价格元、量手、额元）→ 复用 kline 的换算（×100 分、量×100 股）。
SNAPSHOT_EARLIEST = (15, 5)  # 快照仅收盘后可信：最早 15:05 才允许走快速路径
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
    it = d.get("data") or {}
    # 退市/无数据标的一律返回 {"data":{},"error_code":0}——必须显式消费该"空"信号
    # （fail-closed：返回空列表而非抛 KeyError，避免被上层当成"抓取异常"淹没真实原因）
    if not it.get("column"):
        return []
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


def _amt_yuan(x):
    """成交额归一为整数元（向下取整）——与逐只 kline 路径口径对齐。

    逐只 kline 的 amount 为整数元；快照接口（东财 f6 / 雪球 quote.amount）带小数。
    .day 的 amount 是 f32：1e7 元量级量化间距 1 元、1e8 量级 8 元、1e9 量级 64 元。
    带小数值与整数值在 f32 下可能落到**相邻**值——实测 30888377.63 与 30888377
    相差仅 0.63 元却相差 1 ulp（2 元）。统一向下取整可保证「快照快路径」与
    「逐只 kline 路径」写出的 .day **字节完全一致**，即增量来源可互换而不产生差异。
    """
    return float(int(float(x)))


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


def fetch_snapshot_day(trade_date, progress_cb=None):
    """收盘后全A当日快照 → {(market, code6): (date,o分,h分,l分,c分,amount元,vol股)}。

    停牌/无成交（f2='-'）标的自动缺失——与 kline 路径「当日无 bar 则不写」语义一致。
    任一页拉取失败抛异常，由调用方回退逐只 kline 路径。
    """
    out = {}
    pn, total = 1, None
    while True:
        d = _http_json(EM_CLIST.format(pn=pn), timeout=10, tries=3)
        data = d.get("data") or {}
        diff = data.get("diff") or []
        if total is None:
            total = int(data.get("total") or 0)
        if not diff:
            break
        for it in diff:
            if it.get("f2") in ("-", None) or it.get("f5") in ("-", None):
                continue
            mkt = "sh" if it.get("f13") == 1 else "sz"
            code6 = str(it.get("f12", "")).zfill(6)
            o, h, low, c = (float(it["f17"]), float(it["f15"]),
                            float(it["f16"]), float(it["f2"]))
            vol, amt = float(it["f5"]), _amt_yuan(it["f6"])
            out[(mkt, code6)] = (
                trade_date,
                int(round(o * 100)), int(round(h * 100)),
                int(round(low * 100)), int(round(c * 100)),
                amt, int(round(vol * 100)))  # 量 手→股
        if progress_cb and pn % 10 == 0:
            progress_cb(f"快照进度 {len(out)}/{total}")
        if total and len(out) >= total and pn * 100 >= total:
            break
        pn += 1
        if pn > 200:  # 防御：分页异常终止
            raise RuntimeError(f"快照分页异常：pn={pn} total={total}")
    return out


def _prev_trade_date(cal, trade_date):
    """交易日历中 trade_date 的前一交易日（无则 None）。"""
    prev = [d for d in cal if d < trade_date]
    return max(prev) if prev else None


def _fetch_snapshot_xq(files, trade_date, progress_cb=None, batch=100):
    """雪球批量报价快照（备源快速路径）→ 与 fetch_snapshot_day 同构的 dict。

    东财被整站限流时使用（东财约 56 请求；雪球约 28 请求，200 只/批）。
    口径：quote.open/high/low/current → 分；volume 已为股（不像东财需 ×100）；amount 元。
    停牌（无量额）、退市（item 为 null）、非目标交易日行情（时间戳日期不符）一律判缺失，
    与 kline 路径「当日无 bar 则不写」语义一致。
    """
    from datetime import datetime, timezone, timedelta
    tz8 = timezone(timedelta(hours=8))
    syms = []
    for f in files:
        mkt = f.parent.parent.name          # .../vipdoc/sh/lday
        syms.append(mkt.upper() + f.stem[2:])
    out = {}
    for i in range(0, len(syms), batch):
        chunk = syms[i:i + batch]
        url = ("https://stock.xueqiu.com/v5/stock/batch/quote.json"
               "?symbol=" + ",".join(chunk) + "&extend=detail")
        d = _http_json(url, timeout=20)
        for it in ((d.get("data") or {}).get("items")) or []:
            if not it:
                continue                    # 退市：item 为 null
            q = it.get("quote") or {}
            sym = q.get("symbol") or ""
            if len(sym) < 8:
                continue
            o, h, low, c = q.get("open"), q.get("high"), q.get("low"), q.get("current")
            vol, amt, ts = q.get("volume"), q.get("amount"), q.get("timestamp")
            if None in (o, h, low, c, ts) or not vol or not amt:
                continue                    # 停牌/无成交
            if int(datetime.fromtimestamp(ts / 1000, tz=tz8)
                   .strftime("%Y%m%d")) != trade_date:
                continue                    # 陈旧行情（非目标交易日）
            out[(sym[:2].lower(), sym[2:])] = (
                trade_date,
                int(round(float(o) * 100)), int(round(float(h) * 100)),
                int(round(float(low) * 100)), int(round(float(c) * 100)),
                _amt_yuan(amt), int(round(float(vol))))   # 雪球 volume 已为股
        if progress_cb:
            progress_cb(f"雪球快照进度 {min(i + batch, len(syms))}/{len(syms)}")
    return out


def _snapshot_eligible(missing_days):
    """单日增量且该日=今天且已过收盘定型时间 → 可走快照快速路径。"""
    if len(missing_days) != 1:
        return False
    from datetime import datetime
    now = datetime.now()
    today = int(now.strftime("%Y%m%d"))
    if missing_days[0] != today:
        return False
    return (now.hour, now.minute) >= SNAPSHOT_EARLIEST


def _kline_plan(files, own_last_of, missing_days, src, force_beg=None,
                max_workers=6, progress_cb=None):
    """逐只 kline 抓取路径（多日缺口/盘中；旧实现抽离）。返回 (plan, errors)。"""
    plan, errors = {}, []
    done = [0]

    def work(f):
        market = f.parent.parent.name  # .../vipdoc/sh/lday
        code6 = f.stem[2:]
        own_last = own_last_of(f)
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
    return plan, errors


def _snapshot_plan(files, own_last_of, trade_date, snap, prev_trade_date=None,
                   progress_cb=None):
    """快照快速路径：单日增量。返回 (plan, errors, gap_files)。

    gap_files：个股自身水位落后于「前一交易日」的标的（长期停牌/退市/本地缺 bar）。
    这类标的**不能**直接补今天一根 bar——否则会在 .day 里留下无法自愈的空洞
    （逐只路径只按 own_last+1 向后补，永不回填水位以下的缺口）。
    故交由调用方用逐只 kline 路径按个股自身水位补齐，停牌股自然无新增。
    """
    plan, errors, skipped, gaps = {}, [], 0, []
    for f in files:
        market = f.parent.parent.name
        code6 = f.stem[2:]
        rec = snap.get((market, code6))
        if rec is None:
            skipped += 1          # 停牌/当日无成交：与 kline 路径语义一致
            continue
        own_last = own_last_of(f)
        if rec[0] <= own_last:
            continue              # 已有该日数据（不应发生，防御）
        if prev_trade_date and own_last < prev_trade_date:
            gaps.append(f)        # 水位落后 → 转逐只路径按自身水位补齐
            continue
        ok, probs = validate_records([rec], own_last)
        if probs:
            errors.append({"file": f.name, "skipped": True,
                           "problems": probs[:3]})
        elif ok:
            plan[f] = b"".join(encode_record(r) for r in ok)
    if progress_cb:
        progress_cb(f"快照完成：有效 {len(plan)}，停牌/缺失 {skipped}，"
                    f"水位落后转逐只 {len(gaps)}")
    return plan, errors, gaps


def update(day_dirs, universe_filter=True, max_workers=6, progress_cb=None,
           force_beg=None):
    """检查本地最新交易日 → 抓缺失交易日 → 校验 → 追加（带回滚）。

    返回 summary dict。任何失败保证不破坏既有历史（回滚追加段）。
    """
    t_start = time.time()
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
    t_cal = time.time()                       # 阶段①：日历就绪
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

    # 2) 抓取 + 校验（失败个股跳过，不入库；下次运行按个股自身 beg 自愈补齐）
    #    快速路径：单日增量 + 该日=今天 + 已收盘定型 → 全A批量快照（约 56 请求），
    #    替代逐只 kline（5544 请求，东财限流下可达数小时）。快照失败自动回退旧路径。
    own_last_of = _last_date_of
    plan, errors, used_snapshot, gap_files = None, [], "", []
    t_gap = 0.0
    if not force_beg and _snapshot_eligible(missing_days):
        td = missing_days[0]
        prev_td = _prev_trade_date(cal, td)
        # 快速路径源优先级：东财快照（主源，约 56 请求）→ 雪球快照（备源，约 28 请求）。
        # 任一不可用则尝试下一路径；全部失败回退逐只 kline（原慢路径）。
        tries = []
        if src == "em":
            tries.append(("em_snapshot",
                          lambda: fetch_snapshot_day(td, progress_cb=progress_cb)))
        tries.append(("xq_snapshot",
                      lambda: _fetch_snapshot_xq(files, td, progress_cb=progress_cb)))
        for label, fetch in tries:
            try:
                snap = fetch()
                p, e, g = _snapshot_plan(files, own_last_of, td, snap,
                                         prev_trade_date=prev_td,
                                         progress_cb=progress_cb)
            except Exception as exc:
                logger.warning("%s 快速路径失败(%s)，尝试下一路径", label, exc)
                continue
            plan, errors, gap_files, used_snapshot = p, e, g, label
            break
    if plan is None:
        plan, errors = _kline_plan(files, own_last_of, missing_days, src,
                                   force_beg=force_beg,
                                   max_workers=max_workers,
                                   progress_cb=progress_cb)
    elif gap_files:
        # 水位落后个股按自身水位逐只补齐（停牌/退市自然无新增），避免空洞
        if progress_cb:
            progress_cb(f"水位落后 {len(gap_files)} 只，转逐只路径补齐…")
        _tg = time.time()
        gplan, gerr = _kline_plan(gap_files, own_last_of, missing_days, src,
                                  max_workers=max_workers,
                                  progress_cb=progress_cb)
        t_gap = time.time() - _tg
        plan.update(gplan)
        errors.extend(gerr)
    t_plan = time.time()          # 阶段②：抓取计划就绪（快照/逐只 + 水位补齐）

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
    t_end = time.time()           # 阶段③：落盘完成
    return {"status": "OK", "local_last_before": local_last,
            "appended_days": missing_days, "new_last": new_last,
            "updated_files": len(plan),
            "source": (used_snapshot or src),
            "gap_repaired": len(gap_files),
            "timings": {"calendar_s": round(t_cal - t_start, 1),
                        "plan_s": round(t_plan - t_cal, 1),
                        "gap_repair_s": round(t_gap, 1),
                        "append_s": round(t_end - t_plan, 1),
                        "total_s": round(t_end - t_start, 1)},
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
