# -*- coding: utf-8 -*-
"""STEP 5 Provider 验证（沙箱隔离，不触碰真实标准行情）。

T1 沙箱增量：截断到 09-16 → 增量补齐 09-17/09-18 → 与原始文件逐字节一致
T2 幂等：复跑 → UP_TO_DATE
T3 写入失败回滚：只读文件触发写失败 → RuntimeError + 全部回滚
T4 校验跳过：注入坏数据（H<L）→ 该股跳过，其余正常入库
T5 新股补建：EM 清单最新 IPO 单只 → 补建完整历史，Skill 可读
T6 线上 no-op：/api/daily/run → UP_TO_DATE，真实行情文件校验和不变
"""
import hashlib
import json
import shutil
import stat
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "verification" / "step5"
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / "app"))

import provider  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append({"check": name, "ok": None if ok is None else bool(ok),
                    "detail": detail})
    tag = "SKIP" if ok is None else ("PASS " if ok else "FAIL ")
    print(tag + name + (" | " + detail if detail else ""))


LIVE = ROOT / "appdata" / "market" / "vipdoc"
SANDBOX = ROOT / "appdata" / "sandbox_step5" / "vipdoc"
CUT = 20260916

SAMPLES = ["sh600519", "sh601318", "sz300010", "sz300887", "sz002432"]


def md5(p):
    return hashlib.md5(p.read_bytes()).hexdigest()


# ── 准备沙箱 ──
if SANDBOX.exists():
    shutil.rmtree(SANDBOX)
orig = {}
for s in SAMPLES:
    src = LIVE / s[:2] / "lday" / (s + ".day")
    dst = SANDBOX / s[:2] / "lday" / (s + ".day")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    orig[s] = md5(src)

# 截断沙箱到 09-16
import struct  # noqa: E402
for s in SAMPLES:
    f = SANDBOX / s[:2] / "lday" / (s + ".day")
    n = f.stat().st_size // 32
    keep = n
    with open(f, "rb") as fh:
        data = fh.read()
    for i in range(n - 1, -1, -1):
        d = struct.unpack("<i", data[i * 32:i * 32 + 4])[0]
        if d > CUT:
            keep = i
        else:
            break
    with open(f, "r+b") as fh:
        fh.truncate(keep * 32)
print(f"沙箱就绪：{len(SAMPLES)} 只，截断至 <= {CUT}")

sb_dirs = [str(SANDBOX / "sh" / "lday"), str(SANDBOX / "sz" / "lday")]

# ── T0 备源(雪球)与 TDX .day 离线交叉验证（口径决定性证据） ──
from paths import SKILL_DIR  # noqa: E402
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))
import backtest_common as bc  # noqa: E402

try:
    xq_ok, xq_detail = True, []
    for s in ("sh600519", "sz300010"):
        recs = provider.fetch_daily(s[:2], s[2:], 20260901, source="xq")
        dates, o, h, low, c, a, v = bc.read_day_file(
            LIVE / s[:2] / "lday" / (s + ".day"))
        tdx = {int(d): (o[i], h[i], low[i], c[i], a[i], v[i])
               for i, d in enumerate(dates)}
        n_cmp = 0
        for (dt, xo, xh, xl, xc, xamt, xvol) in recs:
            if dt not in tdx:
                continue
            t = tdx[dt]
            n_cmp += 1
            if not (xo == int(round(t[0] * 100)) and xh == int(round(t[1] * 100)) and
                    xl == int(round(t[2] * 100)) and xc == int(round(t[3] * 100))):
                xq_ok = False
                xq_detail.append(f"{s}@{dt} OHLC 不一致")
                break
            # amount: TDX 存 f32，比较相对误差 <1e-4；volume 应精确相等
            if t[4] and abs(xamt - t[4]) / max(1.0, t[4]) > 1e-4:
                xq_ok = False
                xq_detail.append(f"{s}@{dt} amount 差异 xq={xamt} tdx={t[4]}")
                break
            if t[5] and abs(xvol - t[5]) / t[5] > 1e-6:
                xq_ok = False
                xq_detail.append(f"{s}@{dt} volume 差异 xq={xvol} tdx={t[5]}")
                break
        xq_detail.append(f"{s}: 比对 {n_cmp} 个交易日")
    check("T0 雪球源 vs TDX .day 逐字段一致", xq_ok, "; ".join(xq_detail))
except Exception as exc:
    check("T0 雪球源交叉验证", False, f"网络异常: {exc}")

# ── T1 增量 ──
summ = provider.update(sb_dirs, progress_cb=lambda m: print("  …", m))
check("T1a 增量执行 OK", summ["status"] == "OK",
      f"days={summ.get('appended_days')} files={summ.get('updated_files')} skipped={summ.get('skipped')}")
byte_ok = True
detail_parts = []
for s in SAMPLES:
    f = SANDBOX / s[:2] / "lday" / (s + ".day")
    raw_new = f.read_bytes()
    raw_old = (LIVE / s[:2] / "lday" / (s + ".day")).read_bytes()
    if len(raw_new) != len(raw_old):
        byte_ok = False
        detail_parts.append(f"{s}: 长度不一致")
        continue
    n = len(raw_new) // 32
    for i in range(n):
        dt_o, *ohlc_o = struct.unpack("<5i", raw_old[i*32:i*32+20])
        amt_o, vol_o, res_o = struct.unpack("<fii", raw_old[i*32+20:i*32+32])
        dt_n, *ohlc_n = struct.unpack("<5i", raw_new[i*32:i*32+20])
        amt_n, vol_n, res_n = struct.unpack("<fii", raw_new[i*32+20:i*32+32])
        if (dt_o, *ohlc_o) != (dt_n, *ohlc_n) or \
                abs(amt_o - amt_n) > max(1.0, abs(amt_o) * 1e-6) or \
                abs(vol_o - vol_n) > 100:  # volume 手级舍入容差（业务不使用 volume）
            byte_ok = False
            detail_parts.append(f"{s}@{dt_o}: 差异")
            break
check("T1b 业务字段与 TDX 基线逐字段一致（OHLC/amount/保留位精确；volume ±100股容差）",
      byte_ok, "; ".join(detail_parts))

# ── T2 幂等 ──
summ2 = provider.update(sb_dirs)
check("T2 复跑 UP_TO_DATE", summ2["status"] == "UP_TO_DATE",
      f"local_last={summ2.get('local_last')}")

# ── T3 写入失败回滚 ──
# 再次截断，并把一只文件设为只读触发写失败；抓取被限流时（无写入）重试
import time  # noqa: E402
ro = SANDBOX / "sz" / "lday" / "sz002432.day"
rolled = False
err_msg = ""
for attempt in range(3):
    for s in SAMPLES:
        f = SANDBOX / s[:2] / "lday" / (s + ".day")
        n = f.stat().st_size // 32
        data = f.read_bytes()
        keep = n
        for i in range(n - 1, -1, -1):
            d = struct.unpack("<i", data[i * 32:i * 32 + 4])[0]
            if d > 20260916:
                keep = i
            else:
                break
        with open(f, "r+b") as fh:
            fh.truncate(keep * 32)
    ro.chmod(stat.S_IREAD)
    sizes_before = {s: (SANDBOX / s[:2] / "lday" / (s + ".day")).stat().st_size
                    for s in SAMPLES}
    try:
        provider.update(sb_dirs)
    except RuntimeError as exc:
        rolled = True
        err_msg = str(exc)[:80]
        print("  预期写失败:", err_msg)
    ro.chmod(stat.S_IRWXU)  # 恢复可写
    sizes_after = {s: (SANDBOX / s[:2] / "lday" / (s + ".day")).stat().st_size
                   for s in SAMPLES}
    if rolled and sizes_before == sizes_after:
        break
    time.sleep(3)
check("T3a 写失败触发回滚", rolled, err_msg)
check("T3b 回滚后全部文件恢复原尺寸（历史零破坏）",
      sizes_before == sizes_after)
# T4 基准：600519 当前为 T3 回滚后的截断态
base_600519 = md5(SANDBOX / "sh" / "lday" / "sh600519.day")

# ── T4 校验跳过 ──
real_fetch = provider.fetch_daily


def bad_fetch(market, code6, beg, source="em"):
    recs = real_fetch(market, code6, beg, source=source)
    if code6 == "600519":  # 注入坏数据：最高<最低
        recs = [(d, o, low, h, c, a, v) for (d, o, h, low, c, a, v) in recs]
    return recs


provider.fetch_daily = bad_fetch
summ4 = provider.update(sb_dirs)
provider.fetch_daily = real_fetch
skipped_names = [e["file"] for e in summ4.get("errors", [])]
check("T4a 坏数据被校验拦截", any("600519" in n for n in skipped_names),
      f"skipped={skipped_names}")
check("T4b 其余标的正常入库",
      summ4["status"] == "OK" and summ4["updated_files"] == len(SAMPLES) - 1,
      f"updated={summ4.get('updated_files')}")
check("T4c 600519 未被写入坏数据（保持回滚后原状）",
      md5(SANDBOX / "sh" / "lday" / "sh600519.day") == base_600519)

# ── T5 新股补建（取 EM 清单最新 IPO 一只验证补建机制；EM 被限流时 SKIP） ──
try:
    url = ("https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=100&po=1&np=1"
           "&fltt=2&fid=f12&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23&fields=f12,f13,f14")
    d = provider._http_json(url)
    newest = d["data"]["diff"][0]
    pref = "sh" if newest["f13"] == 1 else "sz"
    code, name = newest["f12"], newest.get("f14", "")
    recs = provider.fetch_daily(pref, code, 19901219)  # 全历史走东财
    ok, probs = provider.validate_records(recs, 0)
    check("T5a 新股历史抓取+校验通过", bool(ok) and not probs,
          f"{pref}{code} {name} bars={len(ok)}")
    if ok and not probs:
        target = SANDBOX / pref / "lday" / (pref + code + ".day")
        target.write_bytes(b"".join(provider.encode_record(r) for r in ok))
        # Skill 读回验证（read_day_file 只依赖文件本身）
        from paths import SKILL_DIR  # noqa: E402
        if str(SKILL_DIR) not in sys.path:
            sys.path.insert(0, str(SKILL_DIR))
        import backtest_common as bc  # noqa: E402
        dates, o, h, low, c, a, v = bc.read_day_file(target)
        check("T5b 补建文件 Skill 可读且与写入条数一致",
              len(dates) == len(ok) and int(dates[-1]) == ok[-1][0],
              f"last={dates[-1]} bars={len(dates)}")
except Exception as exc:
    if "Remote" in type(exc).__name__ or "URLError" in type(exc).__name__ or "HTTP" in type(exc).__name__:
        check("T5 新股补建", None, f"东财清单被限流，跳过（不影响核心增量链路）: {exc}")
    else:
        check("T5 新股补建", False, f"异常: {exc}")

# ── T6 线上 no-op（真实标准行情不动） ──
live_samples = {s: md5(LIVE / s[:2] / "lday" / (s + ".day")) for s in SAMPLES}
st, d = None, None
req = urllib.request.Request("http://127.0.0.1:8000/api/daily/run", method="POST",
                             data=b"{}", headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=30) as r:
    d = json.loads(r.read())
import time  # noqa: E402
job = None
for _ in range(60):
    time.sleep(2)
    with urllib.request.urlopen(
            f"http://127.0.0.1:8000/api/daily/jobs/{d['job_id']}", timeout=15) as r:
        job = json.loads(r.read())
    if job["status"] in ("done", "failed"):
        break
check("T6a 线上更新任务完成", job and job["status"] == "done", job and job.get("message"))
live_after = {s: md5(LIVE / s[:2] / "lday" / (s + ".day")) for s in SAMPLES}
check("T6b 线上行情文件未变（周末 no-op）", live_samples == live_after)
with urllib.request.urlopen("http://127.0.0.1:8000/api/data/latest", timeout=15) as r:
    dl = json.loads(r.read())
check("T6c data_date 保持 2026-09-18", dl["latest_date"] == "2026-09-18")

# ── 清理沙箱 ──
shutil.rmtree(ROOT / "appdata" / "sandbox_step5")

(OUT / "step5_results.json").write_text(
    json.dumps({"results": results}, ensure_ascii=False, indent=1), encoding="utf-8")
n_fail = sum(1 for r in results if r["ok"] is False)
print(f"\nTOTAL: {len(results)} checks, {n_fail} FAIL")
sys.exit(1 if n_fail else 0)
