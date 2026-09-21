"""雪球快照快速路径 / 水位落后转逐只 / 雪球 kline 空数据 —— 验证脚本。

用法：
  python verify_snapshot_xq.py unit     # 离线单测（mock 网络，无外部依赖）
  python verify_snapshot_xq.py real     # 真实数据跨源交叉验证（雪球快照 vs 雪球 kline）
"""
import sys
import struct
import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "app"))
import provider  # noqa: E402

TZ8 = timezone(timedelta(hours=8))
TD = 20260921
FAIL = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    if not cond:
        FAIL.append(name)


def _ms(yyyymmdd, hh=15, mm=0):
    return int(datetime.strptime(str(yyyymmdd), "%Y%m%d")
               .replace(hour=hh, minute=mm, tzinfo=TZ8).timestamp() * 1000)


def _mk_vipdoc(root, specs):
    """specs: [(stem, last_date)] -> 建出最小 .day 文件"""
    for mkt in ("sh", "sz"):
        (root / mkt / "lday").mkdir(parents=True, exist_ok=True)
    for stem, last in specs:
        mkt = stem[:2]
        rec = struct.pack("<5ifii", last, 1000, 1100, 900, 1050, 1.0e7, 100000, 0)
        (root / mkt / "lday" / f"{stem}.day").write_bytes(rec)
    return sorted(root.glob("*/lday/*.day"))


# ───────────────────────────── unit ─────────────────────────────

def unit():
    print("== U1 离线单测：_fetch_snapshot_xq 字段映射 / 停牌-退市-陈旧行情过滤 ==")
    canned = {"data": {"items": [
        None,                                                     # 退市：item 为 null
        {"quote": {"symbol": "SH600301", "open": 10.0, "high": 10.5, "low": 9.9,
                   "current": 10.2, "volume": 1000000, "amount": 10200000.0,
                   "timestamp": _ms(TD)}},                        # 正常
        {"quote": {"symbol": "SZ000005", "status": 3, "open": 5.0, "high": 5.0,
                   "low": 5.0, "current": 0.5, "volume": None,
                   "amount": None, "timestamp": _ms(TD)}},        # 停牌：无量额
        {"quote": {"symbol": "SZ000006", "open": 5.0, "high": 5.0, "low": 5.0,
                   "current": 5.0, "volume": 100, "amount": 500.0,
                   "timestamp": _ms(20260918)}},                  # 陈旧：非目标交易日
    ]}}
    orig = provider._http_json
    provider._http_json = lambda url, timeout=30, tries=None: canned
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "vipdoc"
            _mk_vipdoc(root, [("sh600301", 20260918), ("sz000005", 20260918),
                              ("sz000006", 20260918)])
            files = sorted(root.glob("*/lday/*.day"))
            snap = provider._fetch_snapshot_xq(files, TD)
    finally:
        provider._http_json = orig

    check("仅 1 只通过（退市/停牌/陈旧均被剔除）", len(snap) == 1, f"got={len(snap)}")
    rec = snap.get(("sh", "600301"))
    check("键为 (market, code6)", rec is not None, str(list(snap)))
    check("价格 元→分 换算 ×100", rec and rec[1:5] == (1000, 1050, 990, 1020), str(rec))
    check("volume 保持股（不 ×100）", rec and rec[6] == 1000000, str(rec))
    check("amount 元原值", rec and abs(rec[5] - 10200000.0) < 1, str(rec))
    check("date == 目标交易日", rec and rec[0] == TD, str(rec))

    print()
    print("== U2 离线单测：_snapshot_plan 水位落后 → 转逐只（防空洞） ==")
    prev_td = 20260918
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "vipdoc"
        files = _mk_vipdoc(root, [
            ("sh600301", prev_td),      # 正常：水位=前一交易日 → 直接补
            ("sz000001", prev_td),      # 正常
            ("sh600200", 20260911),     # 水位落后（停牌） → 转逐只
            ("sh600000", prev_td),      # 停牌今日无成交 → 缺失
        ])
        snap = {
            ("sh", "600301"): (TD, 1000, 1050, 990, 1020, 1.0e7, 100000),
            ("sz", "000001"): (TD, 500, 510, 495, 505, 1.0e7, 200000),
            ("sh", "600200"): (TD, 100, 110, 99, 105, 1.0e6, 5000),
        }
        plan, errors, gaps = provider._snapshot_plan(
            files, provider._last_date_of, TD, snap, prev_trade_date=prev_td)
        names = sorted(f.name for f in plan)
        gnames = sorted(f.name for f in gaps)
    check("正常水位 2 只入 plan", names == ["sh600301.day", "sz000001.day"], str(names))
    check("无成交 1 只不计入 plan", "sh600000.day" not in names, str(names))
    check("水位落后 1 只转 gaps", gnames == ["sh600200.day"], str(gnames))
    check("无校验错误", not errors, str(errors))

    print()
    print("== U3 离线单测：_fetch_daily_xq 遇 data:{}（退市）优雅返回 [] ==")
    orig = provider._http_json
    provider._http_json = lambda url, timeout=30, tries=None: {
        "data": {}, "error_code": 0, "error_description": ""}
    try:
        r = provider._fetch_daily_xq("sh", "600304", TD)
    except Exception as exc:                                    # noqa: BLE001
        r = exc
    finally:
        provider._http_json = orig
    check("返回空列表而非抛 KeyError", r == [], f"got={r!r}")

    print()
    print("== U4 离线单测：_prev_trade_date ==")
    cal = [20260915, 20260916, 20260917, 20260918, 20260921]
    check("取日历中前一交易日", provider._prev_trade_date(cal, 20260921) == 20260918)
    check("首个交易日无前值 → None", provider._prev_trade_date(cal, 20260915) is None)

    print()
    print("== U5 单测：_amt_yuan 成交额归一（对齐 kline 的整数元口径） ==")
    check("30888377.63 → 30888377.0", provider._amt_yuan(30888377.63) == 30888377.0)
    check("954184678.71 → 954184678.0", provider._amt_yuan(954184678.71) == 954184678.0)
    check("归一后与 kline 整数值落盘字节相同",
          provider.encode_record((TD, 1, 1, 1, 1, provider._amt_yuan(30888377.63), 1))
          == provider.encode_record((TD, 1, 1, 1, 1, 30888377.0, 1)))
    check("未归一的小数值确实会改变字节（证明归一必要）",
          provider.encode_record((TD, 1, 1, 1, 1, 30888377.63, 1))
          != provider.encode_record((TD, 1, 1, 1, 1, 30888377.0, 1)))


# ───────────────────────────── real ─────────────────────────────

def real(n=60):
    print(f"== R1 真实数据跨源校验：雪球批量快照 vs 雪球逐只 kline（{n} 只，{TD}） ==")
    import paths
    vip = Path(paths.VIPDOC_DIR)
    files = []
    for mkt in ("sh", "sz"):
        for f in sorted((vip / mkt / "lday").glob("*.day")):
            if f.name[:5].startswith(tuple(provider.STOCK_PREFIXES)):
                files.append(f)
    print(f"  股票池 {len(files)} 只")
    import time
    t0 = time.time()
    snap = provider._fetch_snapshot_xq(files, TD)
    dt = time.time() - t0
    print(f"  快照 {len(snap)} 只，耗时 {dt:.1f}s（{(len(files)+99)//100} 批 / 批 100 只）")

    # 分层抽样：沪主板/深主板/创业板/科创板各取若干
    buckets = {"sh60": [], "sz00": [], "sz30": [], "sh68": []}
    for f in files:
        st = f.name[:4]
        for k in buckets:
            if st.startswith(k):
                buckets[k].append(f)
                break
    picks = []
    per = max(1, n // 4)
    for k, lst in buckets.items():
        step = max(1, len(lst) // per)
        picks += lst[::step][:per]
    print(f"  抽样 {len(picks)} 只（沪主板/深主板/创业板/科创板）")

    bad, byte_bad, both_missing, one_sided, amt_raw = [], [], 0, [], 0
    for f in picks:
        mkt, code6 = f.parent.parent.name, f.stem[2:]
        s = snap.get((mkt, code6))
        try:
            kl = [r for r in provider.fetch_daily(mkt, code6, TD, source="xq")
                  if r[0] == TD]
        except Exception as exc:                                # noqa: BLE001
            kl = []
            print(f"    {f.name}: kline 抓取异常 {type(exc).__name__}")
        k = kl[0] if kl else None
        if s is None and k is None:
            both_missing += 1
            continue
        if s is None or k is None:
            one_sided.append((f.name, s, k))
            continue
        # 分层判据：① 日期/OHLC/量 必须逐字段全等（硬）；② 落盘字节必须全等（决定性）
        if s[0] != k[0] or s[1:5] != k[1:5] or s[6] != k[6]:
            bad.append((f.name, s, k))
            print(f"    HARD MISMATCH {f.name}\n      snap ={s}\n      kline={k}")
            continue
        if provider.encode_record(s) != provider.encode_record(k):
            byte_bad.append((f.name, s, k))
            print(f"    BYTE MISMATCH {f.name}\n      snap ={s}\n      kline={k}")
            continue
        if s[5] != k[5]:
            amt_raw += 1            # amount 原值有别但经 f32 后字节相同（预期内）
    check(f"日期/OHLC/成交量 逐字段全等（硬不匹配 {len(bad)}）", not bad)
    check(f"落盘 .day 字节全等（字节不匹配 {len(byte_bad)}）", not byte_bad)
    check(f"单侧缺失样本为 0（缺失 {len(one_sided)}）", not one_sided,
          str(one_sided[:3]))
    print(f"  amount 原值有别但 f32 字节等价：{amt_raw} 只"
          f"（.day 的 amount 为 f32，1e9 元量级量化间距 64 元）")
    print(f"  两侧均缺失（停牌/退市）：{both_missing} 只")
    print(f"  快照覆盖率：{len(snap)}/{len(files)} = {len(snap)/len(files)*100:.1f}%")

    print()
    print("== R2 集合结构：快照可交易集 vs 本地水位分组 ==")
    prev_td = provider._prev_trade_date(
        provider.trade_dates(beg=20260901, source="xq"), TD)
    norm, gap = set(), set()
    for f in files:
        key = (f.parent.parent.name, f.stem[2:])
        (norm if provider._last_date_of(f) == prev_td else gap).add(key)
    keys = set(snap)
    print(f"  本地水位=前一交易日({prev_td})：{len(norm)} 只")
    print(f"  本地水位落后：{len(gap)} 只")
    print(f"  快照可交易：{len(keys)} 只")
    print(f"  → 正常组∩快照 = {len(norm & keys)} / {len(norm)}")
    print(f"  → 落后组∩快照 = {len(gap & keys)} / {len(gap)}（今日复牌/恢复交易者）")
    check("水位正常组基本全部可交易（≥99%）",
          len(norm & keys) >= 0.99 * len(norm),
          f"{len(norm & keys)}/{len(norm)}")
    print(f"  落后组中今日有成交的样例：{sorted(gap & keys)[:8]}")


def negative():
    """比对器负向自校验：必须先证明它会失败，才能信任它的 PASS。"""
    print("== N1 落盘字节比对器：负向用例 ==")
    a = (TD, 1000, 1050, 990, 1020, 1.0e7, 100000)
    check("收盘价 +1 分 → 字节不等",
          provider.encode_record(a)
          != provider.encode_record((TD, 1000, 1050, 990, 1021, 1.0e7, 100000)))
    check("最高价 +1 分 → 字节不等",
          provider.encode_record(a)
          != provider.encode_record((TD, 1000, 1051, 990, 1020, 1.0e7, 100000)))
    check("成交量 +100 股 → 字节不等",
          provider.encode_record(a)
          != provider.encode_record((TD, 1000, 1050, 990, 1020, 1.0e7, 100100)))
    check("日期 +1 交易日 → 字节不等",
          provider.encode_record(a)
          != provider.encode_record((20260922, 1000, 1050, 990, 1020, 1.0e7, 100000)))
    check("成交额 +1000 元 → 字节不等（远超 f32 量化间距）",
          provider.encode_record(a)
          != provider.encode_record((TD, 1000, 1050, 990, 1020, 1.01e7, 100000)))
    check("成交额 +0.5 元 → 字节相同（f32 量化死区内，属预期等价）",
          provider.encode_record(a)
          == provider.encode_record((TD, 1000, 1050, 990, 1020, 1.0e7 + 0.5, 100000)))
    check("成交额 +32 元 → 字节相同（1e9 量级 f32 间距 64 元）",
          provider.encode_record((TD, 1, 1, 1, 1, 954184678.0, 1))
          == provider.encode_record((TD, 1, 1, 1, 1, 954184678.0 + 32, 1)))
    check("成交额 +64 元 → 字节不等",
          provider.encode_record((TD, 1, 1, 1, 1, 954184678.0, 1))
          != provider.encode_record((TD, 1, 1, 1, 1, 954184678.0 + 64, 1)))


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "unit"
    if mode in ("unit", "all"):
        unit()
    if mode in ("neg", "all"):
        negative()
    if mode in ("real", "all"):
        real()
    print()
    print("RESULT:", "ALL PASS" if not FAIL else f"FAILED -> {FAIL}")
    sys.exit(1 if FAIL else 0)
