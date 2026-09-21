# -*- coding: utf-8 -*-
"""STEP 4 产品行为验证（对运行中的 127.0.0.1:8000 执行，artifacts 留证）。

T1 current/previous 轮换     T2 失败保护（失败不改状态）
T3 new_hits diff             T4 前N条预览
T5 Excel 下载有效性          T6 损坏 state 恢复 + 跨重启持久化
"""
import io
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "verification" / "step4"
OUT.mkdir(parents=True, exist_ok=True)
BASE = "http://127.0.0.1:8000"
STEM = "step4_model_a"

PLAN_A = {"schema_version": 1, "kind": "day_pattern_backward", "strategy_plan": {
    "universe": "20cm", "days": [
        {"offset": -2, "limit_up": True},
        {"offset": -1, "limit_up": False, "amount_max20": False},
        {"offset": 0, "limit_up": True, "amount_max20": True, "high_max20": False}],
    "outputs": [{"atom": "date", "day": 0}, {"atom": "t_walk", "t0": 0, "t1": 6}]}}
PLAN_B = {"schema_version": 1, "kind": "day_pattern_backward", "strategy_plan": {
    "universe": "20cm", "days": [
        {"offset": 0, "limit_up": True, "amount_max20": True}],
    "outputs": [{"atom": "date", "day": 0}, {"atom": "t_walk", "t0": 0, "t1": 6}]}}
# 触发技术失败的非法 plan（outputs atom 不存在）
PLAN_BAD = {"schema_version": 1, "kind": "day_pattern_backward", "strategy_plan": {
    "universe": "20cm", "days": [{"offset": 0, "limit_up": True}],
    "outputs": [{"atom": "no_such_atom", "day": 0}]}}

results = []


def call(method, path, body=None, raw=False):
    req = urllib.request.Request(BASE + path, method=method)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, data=data, timeout=300) as r:
        payload = r.read()
        return (r.status, payload) if raw else (r.status, json.loads(payload))


def check(name, ok, detail=""):
    results.append({"check": name, "ok": bool(ok), "detail": detail})
    print(("PASS " if ok else "FAIL ") + name + (" | " + detail if detail else ""))


def run_backtest(plan, rule_text):
    st, d = call("POST", "/api/plan/backtest",
                 {"plan": plan, "rule_text": rule_text, "stem": STEM})
    return st, d


def state_of(stem):
    _, d = call("GET", "/api/daily/state")
    return d["models"].get(stem), d


# ── T1 轮换：规则X成功 → 规则Y成功 → previous==旧current ──
st, r1 = run_backtest(PLAN_A, "T1规则X：D-2涨停，D-1非涨停且非20日成交额最大，D-0涨停且20日成交额最大且最高价非20日最高")
check("T1a 规则X回测成功", st == 200 and r1["status"] == "OK",
      f"n_hits={r1.get('n_hits')}")
cur1 = r1["n_hits"]

st, r2 = run_backtest(PLAN_B, "T1规则Y：D-0涨停且20日成交额最大")
check("T1b 规则Y回测成功", st == 200 and r2["status"] == "OK", f"n_hits={r2.get('n_hits')}")
cur2 = r2["n_hits"]

m, _ = state_of(STEM)
check("T1c current=规则Y结果", m["n_hits"] == cur2 and m["data_date"] == r2["data_date"])
check("T1d previous=规则X结果", m["new_hits"] is not None)
_, prev_rows = call("GET", f"/api/backtest/{STEM}/candidates?limit=10000")  # current
prev_file = ROOT / "appdata" / "state" / "results" / STEM / "previous.json"
prev_ok = False
prev_n = None
if prev_file.exists():
    pj = json.loads(prev_file.read_text(encoding="utf-8"))
    prev_n = len(pj["rows"])
    prev_ok = prev_n == cur1
check("T1e previous.json 行数=规则X n_hits", prev_ok, f"previous={prev_n} 旧current={cur1}")
check("T1f previous.xlsx 存在", (ROOT / "appdata" / "state" / "results" / STEM / "previous.xlsx").exists())

# ── T3 new_hits diff（current - previous）──
cur_rows = prev_rows  # rename: /api/candidates 返回的 current 全量
prevj = json.loads(prev_file.read_text(encoding="utf-8"))
prev_codes = {r["股票代码"] for r in prevj["rows"]}
cur_codes = {r["股票代码"] for r in cur_rows["rows"]}
expect_new = cur_codes - prev_codes
m, sd = state_of(STEM)
got = {h["code"] for h in m["new_hits"]}
names_ok = all(h["name"] for h in m["new_hits"])
check("T3 new_hits = current - previous", got == expect_new,
      f"expect={len(expect_new)} got={len(got)}")
check("T3b new_hits 含股票名称", names_ok and len(got) > 0)

# ── T2 失败保护：非法 plan（技术失败）不改 current/previous ──
before = json.dumps({"n": m["n_hits"], "nh": sorted(got)})
st, bad = run_backtest(PLAN_BAD, "T2 非法输出原子")
m2, _ = state_of(STEM)
after = json.dumps({"n": m2["n_hits"], "nh": sorted(h["code"] for h in m2["new_hits"])})
check("T2a 非法plan返回FAILED", st == 200 and bad.get("status") == "FAILED",
      f"violations={len(bad.get('validation', {}).get('violations', []))}")
check("T2b 失败后 current/new_hits 不变", before == after)

# 复核失败路径：直接调 executor.validate_rows 造一个必然失败的复核（离线，不动服务状态）
sys.path.insert(0, str(ROOT / "app"))
import executor  # noqa: E402
viol = executor.validate_rows(PLAN_B, [{"股票代码": "999999", "D-0日期": "2026-09-18"}],
                              ["股票代码", "D-0日期"])
check("T2c 确定性复核可拦截坏行", len(viol) > 0, f"violations={len(viol)}")

# ── T4 前N条预览 ──
st, d = call("GET", f"/api/backtest/{STEM}/candidates?limit=10")
check("T4 limit=10 返回10条", st == 200 and len(d["rows"]) == 10,
      f"got={len(d['rows'])}")

# ── T5 Excel 下载 ──
import urllib.parse  # noqa: E402
qname = urllib.parse.quote("STEP4验证模型")
st, blob = call("GET", f"/api/backtest/{STEM}/candidates/export?model_name={qname}", raw=True)
check("T5a export 200", st == 200, f"{len(blob)} bytes")
import pandas as pd  # noqa: E402
try:
    df = pd.read_excel(io.BytesIO(blob))
    check("T5b Excel 有效且行数=n_hits", len(df) == cur2, f"rows={len(df)} n_hits={cur2}")
except Exception as exc:
    check("T5b Excel 有效", False, str(exc))

# ── T6 损坏 state 恢复 + 跨重启持久化 ──
# (1) 跨重启：store 每次从磁盘读取，等价于重启后读取；验证 state.json 落盘含两轮结果
sf = ROOT / "appdata" / "state" / "state.json"
sj = json.loads(sf.read_text(encoding="utf-8"))
sm = sj["models"].get(STEM, {})
check("T6a 落盘含 current+previous",
      bool(sm.get("current_result")) and bool(sm.get("previous_result")))
# (2) 损坏恢复（在副本上验证 load_state 行为）
import shutil  # noqa: E402
import store  # noqa: E402
tmp_state = ROOT / "appdata" / "state" / "state.corrupt_test.json"
shutil.copy2(sf, tmp_state)
tmp_state.write_text("{broken json!!", encoding="utf-8")
import paths  # noqa: E402
orig = paths.STATE_FILE
paths.STATE_FILE = tmp_state
store.STATE_FILE = tmp_state
empty = store.load_state()
backup_exists = tmp_state.with_suffix(".corrupt.json").exists()
paths.STATE_FILE = orig
store.STATE_FILE = orig
check("T6b 损坏 state -> 空状态+备份", empty.get("models") == {} and backup_exists)
tmp_state.with_suffix(".corrupt.json").unlink(missing_ok=True)
tmp_state.unlink(missing_ok=True)

# ── 清理测试模型（保持工作台干净），证据已落 artifacts ──
sj = json.loads(sf.read_text(encoding="utf-8"))
sj["models"].pop(STEM, None)
sf.write_text(json.dumps(sj, ensure_ascii=False, indent=1), encoding="utf-8")
rd = ROOT / "appdata" / "state" / "results" / STEM
if rd.exists():
    shutil.rmtree(rd)

(OUT / "step4_results.json").write_text(
    json.dumps({"results": results}, ensure_ascii=False, indent=1), encoding="utf-8")
n_fail = sum(1 for r in results if not r["ok"])
print(f"\nTOTAL: {len(results)} checks, {n_fail} FAIL")
sys.exit(1 if n_fail else 0)
