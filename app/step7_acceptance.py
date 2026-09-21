# -*- coding: utf-8 -*-
"""STEP 7 Windows 完整验收 —— 验收执行器。

子命令：
  manifest   生成 INPUT_MANIFEST.json（UI/Skill/Golden/固定测试行情 SHA-256 + 运行时环境）
  p0         P0 Golden 全量重跑（真实链：recognizer -> executor -> Skill -> 标准本地行情）
  p4         P4 轮换与失败保护 + P2 结构化结果/Excel + P8 new_hits（经运行中后端 API）
  p6p7       P6/P7 手动每日管线（周末 no-op + 行情校验和不变）+ 状态留证

fail-closed 原则：任何冲突只记录上报，不修改 Golden/Skill/比较器。
"""
import hashlib
import json
import platform
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "verification" / "step7_win_acceptance"
OUT.mkdir(parents=True, exist_ok=True)

results = []


def check(name, ok, detail=""):
    results.append({"check": name, "ok": bool(ok), "detail": str(detail)})
    print(("PASS " if ok else "FAIL ") + name + (" | " + detail if detail else ""), flush=True)


def sha256_file(p: Path, buf=1 << 20) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while True:
            b = f.read(buf)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def call(method, path, body=None, raw=False, timeout=300):
    req = urllib.request.Request("http://127.0.0.1:8000" + path, method=method)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, data=data, timeout=timeout) as r:
        payload = r.read()
        return (r.status, payload) if raw else (r.status, json.loads(payload))


# ───────────────────────── manifest ─────────────────────────

def stage_manifest():
    targets = {}

    ui = ROOT / "ui" / "ui_v2.html"
    targets[str(ui.relative_to(ROOT))] = {"size": ui.stat().st_size, "sha256": sha256_file(ui)}

    for sub in ("rule.txt",):
        p = ROOT / "golden" / sub
        targets["golden/" + sub] = {"size": p.stat().st_size, "sha256": sha256_file(p)}

    gdirs = [d for d in (ROOT / "golden").iterdir() if d.is_dir() and d.name.endswith("_backtest")]
    for d in sorted(gdirs):
        for p in sorted(d.iterdir()):
            targets["golden/" + d.name + "/" + p.name] = {"size": p.stat().st_size,
                                                          "sha256": sha256_file(p)}

    skill = ROOT / "skill" / "tdx-stock-backtest-master"
    for p in sorted(skill.rglob("*")):
        if p.is_file():
            targets["skill/" + p.relative_to(skill).as_posix()] = {
                "size": p.stat().st_size, "sha256": sha256_file(p)}

    vipdoc = ROOT / "golden" / "vipdoc"
    n = 0
    t0 = time.time()
    for p in sorted(vipdoc.rglob("*.day")):
        rel = "golden/vipdoc/" + p.relative_to(vipdoc).as_posix().replace("\\", "/")
        targets[rel] = {"size": p.stat().st_size, "sha256": sha256_file(p)}
        n += 1
        if n % 5000 == 0:
            print(f"  hashed {n} market files ({time.time()-t0:.0f}s)", flush=True)

    manifest = {
        "run_id": "step7_win_acceptance",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "os": f"{platform.system()} {platform.release()} {platform.version()}",
        "python": sys.version,
        "packages": _pkg_versions(),
        "n_files": len(targets),
        "files": targets,
    }
    (OUT / "INPUT_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"manifest done: {len(targets)} files -> {OUT / 'INPUT_MANIFEST.json'}", flush=True)


def _pkg_versions():
    out = {}
    for m in ("fastapi", "uvicorn", "pandas", "numpy", "openpyxl", "pyyaml", "requests"):
        try:
            out[m] = __import__(m).__version__
        except Exception:
            out[m] = "N/A"
    return out


# ───────────────────────── P0 golden ─────────────────────────

def stage_p0():
    sys.path.insert(0, str(ROOT / "app"))
    import golden_test
    golden_test.OUT = OUT  # 结果落 step7 目录
    rules = golden_test.load_rule_texts()
    summary = {"total": 0, "by_verdict": {}}
    all_results = []
    for name in sorted(rules):
        print(f"=== {name} ===", flush=True)
        try:
            r = golden_test.run_rule(name, rules[name], [])
            golden_test.classify(r)
        except Exception as e:  # noqa: BLE001
            import traceback
            r = {"rule": name, "verdict": "ERROR",
                 "detail": {"error": str(e), "traceback": traceback.format_exc()}}
        all_results.append(r)
        summary["total"] += 1
        summary["by_verdict"].setdefault(r["verdict"], []).append(name)
        print(f"  -> {r['verdict']}", flush=True)
    (OUT / "p0_golden_results.json").write_text(
        json.dumps({"summary": summary, "results": all_results},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


# ───────────────────────── P4(+P2/P8) ─────────────────────────

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
PLAN_BAD = {"schema_version": 1, "kind": "day_pattern_backward", "strategy_plan": {
    "universe": "20cm", "days": [{"offset": 0, "limit_up": True}],
    "outputs": [{"atom": "no_such_atom", "day": 0}]}}

STEM = "step7_model_a"


def stage_p4():
    import io
    import shutil
    import urllib.parse

    st, r1 = call("POST", "/api/plan/backtest",
                  {"plan": PLAN_A, "rule_text": "STEP7规则X：D-2涨停，D-1非涨停且非20日成交额最大，"
                                              "D-0涨停且20日成交额最大且最高价非20日最高", "stem": STEM})
    check("P4a 规则X回测成功", st == 200 and r1["status"] == "OK", f"n_hits={r1.get('n_hits')}")
    n1 = r1["n_hits"]

    st, r2 = call("POST", "/api/plan/backtest",
                  {"plan": PLAN_B, "rule_text": "STEP7规则Y：D-0涨停且20日成交额最大", "stem": STEM})
    check("P4b 规则Y回测成功", st == 200 and r2["status"] == "OK", f"n_hits={r2.get('n_hits')}")
    n2 = r2["n_hits"]

    _, sd = call("GET", "/api/daily/state")
    m = sd["models"].get(STEM, {})
    check("P4c current=规则Y", m.get("n_hits") == n2 and m.get("data_date") == r2["data_date"])

    prev_file = ROOT / "appdata" / "state" / "results" / STEM / "previous.json"
    prev_n = len(json.loads(prev_file.read_text(encoding="utf-8"))["rows"]) if prev_file.exists() else -1
    check("P4d previous=规则X结果", prev_n == n1, f"previous={prev_n} 旧current={n1}")

    # P8 new_hits = current - previous，且带名称（UI 绿色高亮数据源）
    _, cur = call("GET", f"/api/backtest/{STEM}/candidates?limit=10000")
    prev_codes = {r["股票代码"] for r in json.loads(prev_file.read_text(encoding="utf-8"))["rows"]}
    cur_codes = {r["股票代码"] for r in cur["rows"]}
    expect_new = cur_codes - prev_codes
    got = {h["code"] for h in m.get("new_hits", [])}
    names_ok = all(h.get("name") for h in m.get("new_hits", []))
    check("P8a new_hits=current-previous", got == expect_new,
          f"expect={sorted(expect_new)} got={sorted(got)}")
    check("P8b new_hits 含名称", names_ok and len(got) > 0)

    # P2 结构化结果 + Excel
    check("P2a 结构化结果列集完整", bool(cur["columns"]) and len(cur["rows"]) == n2,
          f"columns={cur['columns'][:6]}... rows={len(cur['rows'])}")
    q = urllib.parse.quote("STEP7验收模型")
    st, blob = call("GET", f"/api/backtest/{STEM}/candidates/export?model_name={q}", raw=True)
    import pandas as pd
    ok_x, rows_x = False, -1
    try:
        df = pd.read_excel(io.BytesIO(blob))
        rows_x = len(df)
        ok_x = rows_x == n2
    except Exception as exc:  # noqa: BLE001
        check("P2b Excel 打开", False, str(exc))
    check("P2b Excel 有效且行数=n_hits", ok_x, f"rows={rows_x} n_hits={n2}")
    xh = hashlib.sha256(blob).hexdigest()
    (OUT / "p2_export_excel.sha256").write_text(
        f"{xh}  step7_model_a_current.xlsx\n", encoding="utf-8")

    # 失败保护
    before = json.dumps({"n": m.get("n_hits"), "nh": sorted(got)}, sort_keys=True)
    st, bad = call("POST", "/api/plan/backtest",
                   {"plan": PLAN_BAD, "rule_text": "STEP7非法输出原子", "stem": STEM})
    _, sd2 = call("GET", "/api/daily/state")
    m2 = sd2["models"].get(STEM, {})
    after = json.dumps({"n": m2.get("n_hits"),
                        "nh": sorted(h["code"] for h in m2.get("new_hits", []))}, sort_keys=True)
    check("P4e 非法plan返回FAILED", st == 200 and bad.get("status") == "FAILED",
          f"violations={len(bad.get('validation', {}).get('violations', []))}")
    check("P4f 失败后 current/new_hits 不变", before == after)
    _, rr = call("GET", f"/api/rules/{STEM}")
    strat = rr.get("strategy") or {}
    check("P4g 失败后规则文本与执行计划保留",
          "STEP7规则Y" in (strat.get("rule_text") or "") and bool(strat.get("plan")),
          f"rule_text[:30]={(strat.get('rule_text') or '')[:30]} plan={'有' if strat.get('plan') else '无'}")

    # 清理测试模型
    sf = ROOT / "appdata" / "state" / "state.json"
    sj = json.loads(sf.read_text(encoding="utf-8"))
    sj["models"].pop(STEM, None)
    sf.write_text(json.dumps(sj, ensure_ascii=False, indent=1), encoding="utf-8")
    rd = ROOT / "appdata" / "state" / "results" / STEM
    if rd.exists():
        shutil.rmtree(rd)
    print("cleanup: step7_model_a removed", flush=True)


# ───────────────────────── P2 UI 模型 Excel 复核 ─────────────────────────

def stage_p2():
    import io
    summary = json.loads((OUT / "p1_e2e_summary.json").read_text(encoding="utf-8"))
    stem = summary.get("stem")
    n_hits = summary.get("n_hits", summary.get("nHits"))
    if not stem:
        check("P2c UI回测 stem 可得", False, "p1_e2e_summary.json 无 stem")
        return
    st, cur = call("GET", f"/api/backtest/{stem}/candidates?limit=10000")
    check("P2c UI模型结构化结果可取回", st == 200 and len(cur["rows"]) == n_hits,
          f"rows={len(cur.get('rows', []))} n_hits={n_hits}")
    import urllib.parse
    q = urllib.parse.quote(summary.get("model_name") or stem)
    st, blob = call("GET", f"/api/backtest/{stem}/candidates/export?model_name={q}", raw=True)
    ok, rows_x = False, -1
    try:
        import pandas as pd
        df = pd.read_excel(io.BytesIO(blob))
        rows_x = len(df)
        ok = rows_x == n_hits
    except Exception as exc:  # noqa: BLE001
        check("P2d UI模型Excel可打开", False, str(exc))
    check("P2d UI模型Excel可打开且行数一致", ok, f"rows={rows_x} n_hits={n_hits}")
    (OUT / "p2_ui_model_excel.sha256").write_text(
        hashlib.sha256(blob).hexdigest() + f"  {stem}_current.xlsx\n", encoding="utf-8")
    (OUT / "p2_ui_model_columns.json").write_text(
        json.dumps({"stem": stem, "columns": cur["columns"], "n_rows": len(cur["rows"])},
                   ensure_ascii=False, indent=1), encoding="utf-8")


# ───────────────────────── P3 持久化（重启前后） ─────────────────────────

def _persist_snapshot():
    _, ds = call("GET", "/api/daily/state")
    snap = {"daily_state": ds, "models": {}}
    for stem in ds["models"]:
        try:
            _, r = call("GET", f"/api/rules/{stem}")
            snap["models"][stem] = {"rule": r}
        except Exception:  # noqa: BLE001
            snap["models"][stem] = {"rule": None}
        try:
            _, c = call("GET", f"/api/backtest/{stem}/candidates?limit=10000")
            snap["models"][stem]["n_rows"] = len(c["rows"])
            snap["models"][stem]["columns"] = c["columns"]
            snap["models"][stem]["rows_sha"] = hashlib.sha256(
                json.dumps(c["rows"], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        except Exception as exc:  # noqa: BLE001
            snap["models"][stem]["error"] = str(exc)
    return snap


def stage_p3_before():
    (OUT / "p3_before_restart.json").write_text(
        json.dumps(_persist_snapshot(), ensure_ascii=False, indent=1), encoding="utf-8")
    print("P3 before-restart snapshot saved", flush=True)


def stage_p3_after():
    after = _persist_snapshot()
    (OUT / "p3_after_restart.json").write_text(
        json.dumps(after, ensure_ascii=False, indent=1), encoding="utf-8")
    before = json.loads((OUT / "p3_before_restart.json").read_text(encoding="utf-8"))
    check("P3a 模型清单一致", set(before["models"]) == set(after["models"]),
          f"before={sorted(before['models'])} after={sorted(after['models'])}")
    diffs = []
    for stem in before["models"]:
        b, a = before["models"][stem], after["models"].get(stem, {})
        if b.get("rule") != a.get("rule"):
            diffs.append(stem + ":rule")
        if b.get("rows_sha") != a.get("rows_sha"):
            diffs.append(stem + ":rows")
        if b.get("n_rows") != a.get("n_rows"):
            diffs.append(stem + ":n_rows")
    check("P3b 规则/结果逐模型一致", not diffs, "diffs=" + ",".join(diffs) if diffs else "全部一致")
    check("P3c data_date 一致",
          before["daily_state"].get("data_date") == after["daily_state"].get("data_date"),
          f"data_date={after['daily_state'].get('data_date')}")


# ───────────────────────── P6/P7 ─────────────────────────

def market_checksum_sample(n=12):
    from paths import DAY_DIRS
    out = {}
    for d in DAY_DIRS:
        dp = Path(d)
        if not dp.exists():
            continue
        files = sorted(dp.glob("*.day"))[:n]
        for f in files:
            out[f.name] = sha256_file(f)
    return out


def stage_p6p7():
    _, latest = call("GET", "/api/data/latest")
    check("P7a 行情新鲜度端点可用", latest.get("latest_date") not in (None, ""),
          f"latest_date={latest.get('latest_date')}")

    before_cs = market_checksum_sample()
    _, dd_state = call("GET", "/api/daily/state")
    data_date_before = dd_state.get("data_date")

    st, job = call("POST", "/api/daily/run", {})
    check("P7b 手动更新任务已受理", st == 200 and bool(job.get("job_id")))
    jid = job["job_id"]
    for _ in range(180):
        time.sleep(2)
        _, jd = call("GET", f"/api/daily/jobs/{jid}")
        if jd.get("status") in ("done", "failed"):
            break
    check("P7c 手动更新完成", jd.get("status") == "done", jd.get("message", "")[:120])

    _, dd2 = call("GET", "/api/daily/state")
    check("P7d 周末/无新交易日不产生伪最新", dd2.get("data_date") == data_date_before,
          f"data_date={data_date_before}（周日调用保持不变）")
    after_cs = market_checksum_sample()
    check("P7e 真实行情校验和不变", before_cs == after_cs,
          f"{len(after_cs)} 个样本文件 sha256 全部一致")
    check("P7f 模型结果保持", all(
        mm.get("data_date") == data_date_before for mm in dd2["models"].values()),
        f"models={list(dd2['models'])}")

    (OUT / "p6p7_state_snapshot.json").write_text(
        json.dumps({"before": dd_state, "after": dd2, "job": jd,
                    "checksums_match": before_cs == after_cs},
                   ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else ""
    if stage == "manifest":
        stage_manifest()
    elif stage == "p0":
        stage_p0()
    elif stage == "p2":
        stage_p2()
    elif stage == "p3_before":
        stage_p3_before()
    elif stage == "p3_after":
        stage_p3_after()
    elif stage == "p4":
        stage_p4()
    elif stage == "p6p7":
        stage_p6p7()
    else:
        print("usage: step7_acceptance.py [manifest|p0|p4|p6p7]")
        sys.exit(2)
    if results:
        (OUT / f"step7_{stage}_results.json").write_text(
            json.dumps({"stage": stage, "results": results}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        n_fail = sum(1 for r in results if not r["ok"])
        print(f"\nSTAGE {stage}: {len(results)} checks, {n_fail} FAIL", flush=True)
        sys.exit(1 if n_fail else 0)
