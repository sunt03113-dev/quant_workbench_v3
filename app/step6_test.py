# -*- coding: utf-8 -*-
"""STEP 6 验证：每日管线（增量→重跑→轮换→diff）+ 调度器。

T1 管线 no-op：数据未变 → 模型 kept，不轮换
T2 落后补偿：模型 data_date 落后 → 重跑+轮换（previous=旧 current）
T3 逐模型失败保护：重跑异常 → 该模型状态不变
T4 调度决策：_next_run_ts 落在未来工作日 17:05
T5 手动更新 API → done
"""
import json
import shutil
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "verification" / "step6"
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / "app"))

results = []


def check(name, ok, detail=""):
    results.append({"check": name, "ok": None if ok is None else bool(ok),
                    "detail": detail})
    print(("SKIP" if ok is None else ("PASS " if ok else "FAIL ")) + name
          + (" | " + detail if detail else ""))


STEM = "step6_model"
PLAN = {"schema_version": 1, "kind": "day_pattern_backward", "strategy_plan": {
    "universe": "20cm", "days": [
        {"offset": -2, "limit_up": True},
        {"offset": -1, "limit_up": False, "amount_max20": False},
        {"offset": 0, "limit_up": True, "amount_max20": True, "high_max20": False}],
    "outputs": [{"atom": "date", "day": 0}, {"atom": "t_walk", "t0": 0, "t1": 6}]}}

# 准备测试模型：经 API 正常回测落库
req = urllib.request.Request(
    "http://127.0.0.1:8000/api/plan/backtest", method="POST",
    data=json.dumps({"plan": PLAN, "rule_text": "STEP6 每日管线测试",
                     "stem": STEM}).encode(),
    headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=300) as r:
    bt = json.loads(r.read())
check("T0 测试模型回测落库", bt.get("status") == "OK", f"n_hits={bt.get('n_hits')}")

import store  # noqa: E402
import server  # noqa: E402
import executor  # noqa: E402

market = executor.data_latest_payload()
latest = market["latest_date"]
log = []


def state_of():
    return store.load_state()["models"][STEM]


# ── T1 no-op：数据已最新 → kept ──
out = server._daily_pipeline(log.append)
m = state_of()
check("T1 数据未变 → 模型 kept 不轮换",
      out["provider"] in ("UP_TO_DATE", "OK") and out["kept"] >= 1
      and m["current_result"]["data_date"] == latest,
      f"reran={out['reran']} kept={out['kept']}")

# ── T2 落后补偿：伪造 data_date 落后 → 重跑+轮换 ──
state = store.load_state()
state["models"][STEM]["current_result"]["data_date"] = "2026-09-17"
store.save_state(state)
prev_n_before = (store.load_state()["models"][STEM]
                 .get("previous_result", {}).get("n_hits"))
out2 = server._daily_pipeline(log.append)
m2 = state_of()
check("T2a 落后模型被重跑", out2["reran"] >= 1
      and m2["current_result"]["data_date"] == latest,
      f"reran={out2['reran']}")
check("T2b 轮换正确（previous=旧 current）",
      m2.get("previous_result", {}).get("n_hits") == bt["n_hits"],
      f"prev_n={m2.get('previous_result', {}).get('n_hits')} 旧current={bt['n_hits']}")

# ── T3 逐模型失败保护：重跑异常 → 状态不变 ──
state = store.load_state()
state["models"][STEM]["current_result"]["data_date"] = "2026-09-16"
store.save_state(state)
snap = json.dumps(store.load_state()["models"][STEM]["current_result"],
                  ensure_ascii=False)
real_run_plan = executor.run_plan


def boom(plan, **kw):
    raise RuntimeError("注入的重跑失败")


executor.run_plan = boom
try:
    out3 = server._daily_pipeline(log.append)
finally:
    executor.run_plan = real_run_plan
snap2 = json.dumps(store.load_state()["models"][STEM]["current_result"],
                   ensure_ascii=False)
check("T3 重跑失败 → 该模型状态不变（fail-closed）", snap == snap2,
      f"kept={out3['kept']}")

# ── T4 调度决策 ──
ts = server._next_run_ts()
dt = datetime.fromtimestamp(ts)
wd_ok = dt.weekday() < 5 and dt.hour == 17 and dt.minute == 5 and ts > time.time()
check("T4 _next_run_ts → 未来工作日 17:05", wd_ok, str(dt))

# ── T5 手动更新 API ──
req = urllib.request.Request("http://127.0.0.1:8000/api/daily/run", method="POST",
                             data=b"{}", headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=30) as r:
    job_id = json.loads(r.read())["job_id"]
job = None
for _ in range(90):
    time.sleep(2)
    with urllib.request.urlopen(
            f"http://127.0.0.1:8000/api/daily/jobs/{job_id}", timeout=15) as r:
        job = json.loads(r.read())
    if job["status"] in ("done", "failed"):
        break
check("T5 手动更新 API done", job and job["status"] == "done",
      job and job.get("message"))

# 清理测试模型
sf = ROOT / "appdata" / "state" / "state.json"
sj = json.loads(sf.read_text(encoding="utf-8"))
sj["models"].pop(STEM, None)
sf.write_text(json.dumps(sj, ensure_ascii=False, indent=1), encoding="utf-8")
rd = ROOT / "appdata" / "state" / "results" / STEM
if rd.exists():
    shutil.rmtree(rd)

(OUT / "step6_results.json").write_text(
    json.dumps({"results": results}, ensure_ascii=False, indent=1), encoding="utf-8")
n_fail = sum(1 for r in results if r["ok"] is False)
print(f"\nTOTAL: {len(results)} checks, {n_fail} FAIL")
sys.exit(1 if n_fail else 0)
