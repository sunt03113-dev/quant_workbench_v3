# -*- coding: utf-8 -*-
"""区间语义（方案A）上线重跑：重识别 -> 更新模型定义 -> run_plan -> validate_rows -> 落库。

要点：
  1) 受影响的 6 个「含变量 x + D-1/D-x 同组条件」模型，其**库内计划**必须一并换成新计划，
     否则下一次每日管线用旧计划（端点式）重跑，结果会回退。
  2) f120ccad35 / 676e25bb91 / 99b11761e0 的库内计划是历史遗留的错位翻译（固定 -1..-4、缺
     var 条件），本次用 rule_text 重新识别纠正（任务 #12）。
  3) 与 server.plan_backtest 同路径：save_rule -> run_plan -> validate_rows -> save_success_result
     -> 落 current.xlsx。复核不通过则跳过该模型（fail-closed，保留旧结果）。
"""
import sys, io, json, time
import pathlib
sys.path.insert(0, 'app')
import pandas as pd
import recognizer, executor, store

ART = pathlib.Path('artifacts/verification/1s1a_bug_0923')
BUF = io.StringIO()


def p(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    print(s, file=BUF)


TARGETS = [
    "strategy_c1790145091328_r1_v1",   # 1S1A
    "strategy_10cm_v6",
    "strategy_13b34ebf3a_v1",
    "strategy_f120ccad35_v1",
    "strategy_676e25bb91_v1",
    "strategy_99b11761e0_v1",
]

state = store.load_state()
latest = executor.data_latest_payload()["latest_date"]
p(f"### 区间语义上线重跑   data_date={latest}   目标 {len(TARGETS)} 个模型\n")

report = []
for stem in TARGETS:
    m = state["models"].get(stem)
    p("=" * 92)
    if m is None:
        p(f"### {stem}: 库中不存在，跳过")
        continue
    rt = m.get("rule_text") or ""
    if not rt:
        p(f"### {stem}: rule_text 缺失，跳过（fail-closed）")
        report.append({"stem": stem, "error": "rule_text 缺失"})
        continue
    old_plan = m.get("plan") or {}
    old_sp = old_plan.get("strategy_plan") or {}
    before_rows = (m.get("current_result") or {}).get("n_hits")
    before_has_ranges = bool(old_sp.get("ranges"))
    before_days = json.dumps(old_sp.get("days"), ensure_ascii=False)

    plan, summ, problems = recognizer.parse_single_rule(rt)
    if problems:
        p(f"### {stem}: 重识别失败 -> 跳过 {json.dumps(problems, ensure_ascii=False)}")
        report.append({"stem": stem, "error": "recognize_failed", "problems": problems})
        continue
    sp = plan["strategy_plan"]
    ranges = sp.get("ranges") or []
    p(f"### {stem}   原 {before_rows} 行  旧计划含区间条件={before_has_ranges}")
    p(f"    旧 days: {before_days[:150]}")
    p(f"    新 days: {json.dumps(sp.get('days'), ensure_ascii=False)[:150]}")
    p(f"    新 ranges: {json.dumps(ranges, ensure_ascii=False)}")

    t0 = time.time()
    try:
        rows, columns, meta = executor.run_plan(plan, end_date=latest)
        viol = executor.validate_rows(plan, rows, columns)
        if viol:
            raise RuntimeError(f"复核未通过 {len(viol)} 项: {viol[:2]}")
        # 模型定义（计划 + base_rules）一并更新，防下一次管线条目回退
        store.save_rule(stem, rt, plan, recognizer.plan_to_base_rules(plan))
        store.save_success_result(stem, columns, rows, len(rows), latest, meta)
        rd = store.result_dir(stem)
        df = pd.DataFrame(rows)
        for c in columns:
            if c not in df.columns:
                df[c] = "N/A"
        df.reindex(columns=columns).to_excel(rd / "current.xlsx", index=False)
        line = (f"    OK: {before_rows} -> {len(rows)} 行  复核 0 违例  "
                f"{time.time() - t0:.1f}s  列 {len(columns)}")
        p(line)
        report.append({"stem": stem, "before": before_rows, "after": len(rows),
                       "violations": 0, "ranges": ranges,
                       "plan_updated": True, "elapsed_s": round(time.time() - t0, 1)})
    except Exception as e:
        p(f"    FAILED，保留旧结果: {e}")
        report.append({"stem": stem, "before": before_rows, "error": str(e)})

# 落盘后回读校验：新状态里 6 个模型的计划都含 ranges，且结果行数一致
state2 = store.load_state()
p("")
p("=" * 92)
p("### 落库回读校验")
for stem in TARGETS:
    m = state2["models"].get(stem) or {}
    sp = (m.get("plan") or {}).get("strategy_plan") or {}
    cur = m.get("current_result") or {}
    ok = bool(sp.get("ranges")) and cur.get("data_date") == latest
    p(f"  {stem:<34} ranges={'有' if sp.get('ranges') else '无'}  "
      f"n_hits={cur.get('n_hits')}  data_date={cur.get('data_date')}  "
      f"{'OK' if ok else '!! 异常'}")

ART.joinpath("rerun_interval_models.txt").write_text(BUF.getvalue(), encoding="utf-8")
ART.joinpath("rerun_interval_models.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print("\n-> rerun_interval_models.txt / .json 已落盘")
