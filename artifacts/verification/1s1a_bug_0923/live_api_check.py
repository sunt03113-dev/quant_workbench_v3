# -*- coding: utf-8 -*-
"""区间语义（方案A）**活体**验收：不 import 模块，全部走真实 HTTP API。

为什么必须做这一步：
  rerun_interval_models.py 是进程内直接调 recognizer/executor —— 只能证明「磁盘上的代码」是对的，
  证明不了「正在 127.0.0.1:8000 服务的那个进程」加载的是新代码。旧后端没重启 = 用户点按钮还是错结果。
  本脚本就是对运行中的后端发真实请求。

覆盖：
  1) GET  /api/data/latest                        -> 数据新鲜度
  2) POST /api/plan/recognize                     -> 回执含 ranges + notes「已按区间语义翻译」
  3) POST /api/plan/backtest (1S1A 真实计划)       -> n_hits == 148（端点式为 274）
  4) 反证：把 plan 里的 ranges 摘掉再回测          -> 行数必须显著多于 148（证明差异确实由区间条件产生）

注意：本机有 HTTP_PROXY=http://127.0.0.1:53209，urllib 默认会走代理导致 502，必须显式绕过。
"""
import io
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

ART = pathlib.Path("artifacts/verification/1s1a_bug_0923")
BUF = io.StringIO()
BASE = "http://127.0.0.1:8000"

# 强制绕过 HTTP(S)_PROXY，否则本地请求被代理吞掉
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def p(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    print(s, file=BUF)


def call(method, path, payload=None, timeout=600):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    t0 = time.time()
    with opener.open(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8")
    return json.loads(raw), round(time.time() - t0, 2)


sys.path.insert(0, "app")
import store  # noqa: E402

report = {}

p("=" * 92)
p("### 区间语义（方案A）活体 API 验收")
p("=" * 92)

# ── 1) 数据新鲜度 ────────────────────────────────────────────────
acc, dt = call("GET", "/api/data/latest")
p(f"\n[1] GET /api/data/latest  ({dt}s)")
p(f"    latest_date={acc['latest_date']}  today={acc['today']}  "
  f"stale={acc['stale']}  file_count={acc['file_count']}")
report["data_latest"] = acc

# ── 2) 识别：回执必须带区间条件 ──────────────────────────────────
state = store.load_state()
m = state["models"]["strategy_c1790145091328_r1_v1"]
rt = m["rule_text"]

p(f"\n[2] POST /api/plan/recognize   (1S1A, rule_text {len(rt)} 字)")
r, dt = call("POST", "/api/plan/recognize", {"natural_text": rt})
sp = (r.get("plan") or {}).get("strategy_plan") or r.get("strategy_plan") or {}
ranges = sp.get("ranges") or []
p(f"    status={r.get('status')}  ({dt}s)")
p(f"    ranges = {json.dumps(ranges, ensure_ascii=False)}")
summary = r.get("summary") or {}
for n in (summary.get("notes") or []):
    p(f"    note   : {n}")
for ev in (summary.get("events") or []):
    p(f"    event  : {ev}")
report["recognize_ranges"] = ranges
report["recognize_notes"] = summary.get("notes")

# ── 3) 真实回测 ──────────────────────────────────────────────────
p(f"\n[3] POST /api/plan/backtest  (1S1A 真实计划，写回库内)")
plan = r.get("plan") or r
acc, dt = call("POST", "/api/plan/backtest",
               {"plan": plan, "rule_text": rt,
                "stem": "strategy_c1790145091328_r1_v1", "with_names": True})
n_live = acc.get("n_hits")
p(f"    n_hits={n_live}   data_date={acc.get('data_date')}   ({dt}s)")
p(f"    columns={len(acc.get('columns') or [])}   "
  f"validate={acc.get('validate') or acc.get('violations') or 'n/a'}")
report["live_backtest"] = {"n_hits": n_live, "data_date": acc.get("data_date")}

# ── 4) 对照：用 HEAD 版识别器（端点式）重建旧计划，再喂给活体后端 ──
#  说明：不能简单从新计划里 pop('ranges') —— 识别器升级时已把 days 里的 D-1/D-x 条目删除，
#  摘掉 ranges 得到的是一个「退化计划」（行长反而暴涨到 1239），它不是旧口径，拿它当对照是错的。
#  必须用变更前的识别器源码重新识别同一段 rule_text，才能得到真正的「端点式」计划。
import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location("rec_v5_baseline",
                                              "app/recognizer.v5.baseline.py")
base_rec = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base_rec)
old_plan, _old_summ, old_problems = base_rec.parse_single_rule(rt)
old_sp = old_plan["strategy_plan"]
p(f"\n[4] 对照：HEAD 版识别器（端点式）重建的旧计划")
p(f"    problems={old_problems}   has_ranges={'ranges' in old_sp}")
p(f"    旧 days = {json.dumps(old_sp.get('days'), ensure_ascii=False)}")
acc2, dt = call("POST", "/api/plan/backtest",
                {"plan": old_plan, "rule_text": rt,
                 "stem": "strategy_zz_probe_endpoint_v1", "with_names": True})
n_ep = acc2.get("n_hits")
p(f"    端点式 n_hits={n_ep}   ({dt}s)")
p(f"    区间式 {n_live}  vs  端点式 {n_ep}   虚增 {n_ep - n_live} 行")
report["probe_endpoint"] = {"n_hits": n_ep, "stem": "strategy_zz_probe_endpoint_v1"}

# ── 5) 退化对照（附带说明用）：摘掉 ranges 的计划 ────────────────
import copy  # noqa: E402

plan_nr = copy.deepcopy(plan)
plan_nr["strategy_plan"].pop("ranges", None)
acc3, dt = call("POST", "/api/plan/backtest",
                {"plan": plan_nr, "rule_text": rt,
                 "stem": "strategy_zz_probe_degraded_v1", "with_names": True})
n_dg = acc3.get("n_hits")
p(f"\n[5] 附带：同一新计划摘掉 ranges（退化计划，非旧口径，仅证明 ranges 是行数决定因子）")
p(f"    n_hits={n_dg}   ({dt}s)")
report["probe_degraded"] = {"n_hits": n_dg, "stem": "strategy_zz_probe_degraded_v1"}

# ── 判定 ────────────────────────────────────────────────────────
ok = bool(ranges) and n_live == 148 and n_ep == 274 and n_dg != n_live
p("\n" + "=" * 92)
p(f"### 判定：{'PASS' if ok else 'FAIL'}")
p(f"    ranges 非空                : {bool(ranges)}")
p(f"    活体回测 == 148            : {n_live} ({'OK' if n_live == 148 else '!!'})")
p(f"    端点式 == 274（修复前值）   : {n_ep} ({'OK' if n_ep == 274 else '!!'})")
p(f"    ranges 为行数决定因子       : {n_dg} != {n_live} ({'OK' if n_dg != n_live else '!!'})")
p("=" * 92)
report["verdict"] = "PASS" if ok else "FAIL"

ART.joinpath("live_api_check.txt").write_text(BUF.getvalue(), encoding="utf-8")
ART.joinpath("live_api_check.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print("-> live_api_check.txt / .json 已落盘")
