"""每日增量端到端实测：走真实 HTTP 管线（/api/daily/run），全程留证。

用法：python run_daily_update.py            # 干跑：仅记录基线清单
      python run_daily_update.py run        # 实测：触发管线 + 前后比对 + 抽样复核
"""
import json
import struct
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "app"))
import executor  # noqa: E402
import paths      # noqa: E402
import provider   # noqa: E402

OUT = Path(__file__).resolve().parent
API = "http://127.0.0.1:8000"
FAIL = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    if not cond:
        FAIL.append(name)


def scan():
    """全量 .day 清单：{相对路径: 字节数}。"""
    m = {}
    for d in executor.DAY_DIRS:
        for f in sorted(Path(d).glob("*.day")):
            if f.name[:5].startswith(tuple(provider.STOCK_PREFIXES)):
                m[f"{f.parent.parent.name}/{f.name}"] = f.stat().st_size
    return m


def last_rec(path):
    with open(path, "rb") as fh:
        b = fh.read()
    if len(b) < 32:
        return None
    return struct.unpack("<5ifii", b[-32:])[:7]


def post(path, payload=None):
    req = urllib.request.Request(
        API + path, method="POST",
        data=json.dumps(payload or {}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def get(path):
    with urllib.request.urlopen(API + path, timeout=60) as r:
        return json.loads(r.read())


def sample_verify(keys, n=60, seed=20260921):
    """独立抽样复核：落盘末条记录 vs 雪球逐只 kline 当日 bar。

    严格语义：对照侧（kline）取不到数据一律计为失败——**不允许「拿不到就跳过」**，
    否则比对器会空转（本脚本首版曾因 code6 截断成 4 位导致 40/40 全跳过而假 PASS）。
    """
    import random
    random.seed(seed)
    picks = random.sample(sorted(keys), min(n, len(keys)))
    byte_bad, hard_bad, kline_empty, exc = [], [], [], []
    for k in picks:
        mkt, name = k.split("/")
        code6 = name[2:8]                       # 'sh600301.day' -> '600301'
        assert len(code6) == 6 and code6.isdigit(), f"代码提取错误: {name}->{code6}"
        f = Path(paths.VIPDOC_DIR) / mkt / "lday" / name
        rec = last_rec(f)
        try:
            kl = [r for r in provider.fetch_daily(mkt, code6, 20260921, source="xq")
                  if r[0] == 20260921]
        except Exception as e:                                  # noqa: BLE001
            exc.append((k, f"{type(e).__name__}: {e}"))
            continue
        if not kl:
            kline_empty.append(k)
            continue
        if rec[:5] != kl[0][:5] or rec[6] != kl[0][6]:
            hard_bad.append((k, rec, kl[0]))
        elif provider.encode_record(rec) != provider.encode_record(kl[0]):
            byte_bad.append((k, rec, kl[0]))
    check(f"抽样 {len(picks)} 只：对照侧取到数据（空 {len(kline_empty)}）",
          not kline_empty, str(kline_empty[:5]))
    check("对照侧无抓取异常", not exc, str(exc[:3]))
    check("日期/OHLC/成交量 逐字段全等（硬不符 0）", not hard_bad, str(hard_bad[:3]))
    check("落盘 .day 字节逐字节全等（字节不符 0）", not byte_bad, str(byte_bad[:3]))
    for row in (hard_bad + byte_bad)[:3]:
        print("   MISMATCH", row)
    return len(picks)


def main(mode):
    before = scan()
    total_before = sum(before.values())
    print(f"基线：{len(before)} 个 .day，合计 {total_before} 字节")
    if mode == "verify":
        base = json.loads((OUT / "manifest_before.json").read_text(encoding="utf-8"))
        b = base["files"]
        grew = {k: v for k, v in before.items() if v > b.get(k, -1)}
        print(f"对照 manifest_before：增长 {len(grew)} 只")
        print()
        print("== 独立抽样复核：落盘字节 vs 雪球逐只 kline（严格模式）==")
        sample_verify(grew, n=int(sys.argv[2]) if len(sys.argv) > 2 else 60)
        print()
        print("RESULT:", "ALL PASS" if not FAIL else f"FAILED -> {FAIL}")
        sys.exit(1 if FAIL else 0)

    if mode == "run":
        (OUT / "manifest_before.json").write_text(
            json.dumps({"count": len(before), "total_bytes": total_before,
                        "files": before}, ensure_ascii=False, indent=1),
            encoding="utf-8")
    else:
        print("（干跑模式，未触发管线）")
        return

    print()
    print("== 触发每日管线 POST /api/daily/run ==")
    t0 = time.time()
    job = post("/api/daily/run").get("job_id")
    print(f"  job_id={job}  起始 {time.strftime('%H:%M:%S')}")

    seen, last = [], None
    while True:
        time.sleep(2)
        j = get(f"/api/daily/jobs/{job}")
        m = j.get("message")
        el = time.time() - t0
        if m != last:
            print(f"  [{el:6.1f}s] {m}")
            seen.append({"t": round(el, 1), "msg": m})
            last = m
        if j.get("status") in ("done", "failed"):
            break
        if el > 3600:
            print("  超时中止"); break
    elapsed = time.time() - t0
    print(f"  结束 {time.strftime('%H:%M:%S')}  status={j.get('status')}"
          f"  总耗时 {elapsed:.1f}s ({elapsed/60:.2f} 分钟)")
    if j.get("error"):
        print("  error:", j["error"])

    after = scan()
    total_after = sum(after.values())
    (OUT / "manifest_after.json").write_text(
        json.dumps({"count": len(after), "total_bytes": total_after,
                    "files": after}, ensure_ascii=False, indent=1),
        encoding="utf-8")

    print()
    print("== 落盘前后比对 ==")
    shrunk = [k for k in before if k in after and after[k] < before[k]]
    grew = {k: after[k] - before[k] for k in before
            if k in after and after[k] > before[k]}
    added = [k for k in after if k not in before]
    lost = [k for k in before if k not in after]
    bad_growth = {k: v for k, v in grew.items() if v % 32 or v <= 0}
    check("无文件缩短", not shrunk, str(shrunk[:5]))
    check("无文件新增/丢失", not added and not lost, f"+{len(added)} -{len(lost)}")
    check("增量均为 32 字节的整数倍（记录粒度）", not bad_growth, str(bad_growth))
    print(f"  增长文件 {len(grew)} 只，合计 +{sum(grew.values())} 字节"
          f"（{sum(grew.values())//32} 条记录）")

    print()
    print("== 增量后水位分布 ==")
    from collections import Counter
    lasts = Counter()
    for d in executor.DAY_DIRS:
        for f in sorted(Path(d).glob("*.day")):
            if f.name[:5].startswith(tuple(provider.STOCK_PREFIXES)):
                lasts[provider._last_date_of(f)] += 1
    print("  Top6:", lasts.most_common(6))
    check("主体已到最新交易日 20260921", lasts[20260921] >= 5000,
          f"20260921 共 {lasts[20260921]} 只")

    print()
    print("== 独立抽样复核：落盘字节 vs 雪球逐只 kline ==")
    n_checked = sample_verify(grew)

    payload = get("/api/daily/state")
    (OUT / "state_after_update.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print()
    print("== 更新后每日状态 ==")
    print(f"  data_date={payload.get('data_date')}"
          f"  模型数={len(payload.get('models', {}))}"
          f"  day_new_hits 非空={sum(1 for v in payload.get('day_new_hits', {}).values() if v)}")

    print()
    print("RESULT:", "ALL PASS" if not FAIL else f"FAILED -> {FAIL}")
    (OUT / "run_result.json").write_text(json.dumps(
        {"elapsed_s": round(elapsed, 1), "status": j.get("status"),
         "job_id": job, "progress": seen, "failures": FAIL,
         "files_grown": len(grew), "records_appended": sum(grew.values()) // 32,
         "samples_checked": n_checked}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "dry")
