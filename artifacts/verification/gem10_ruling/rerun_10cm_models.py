# -*- coding: utf-8 -*-
"""口径裁定（kk 2026-09-23：10cm 池纳入创业板 10% 时代）后，重跑全部 10cm 模型。

与 _daily_pipeline 第 2 步同路径：run_plan → validate_rows → save_success_result。
复核不通过则跳过该模型（保留旧结果，fail-closed）。
"""
import sys, json, time
sys.path.insert(0, 'app')
import executor, store

state = store.load_state()
latest = executor.data_latest_payload()["latest_date"]
targets = [s for s, m in state["models"].items()
           if (m.get("plan") or {}).get("strategy_plan", {}).get("universe") == "10cm"]
print(f'data_date={latest}  10cm 模型 {len(targets)} 个: {targets}\n')

report = []
for stem in targets:
    m = state["models"][stem]
    before = m.get("current_result", {}).get("n_hits")
    t0 = time.time()
    try:
        rows, columns, meta = executor.run_plan(m["plan"], end_date=latest)
        v = executor.validate_rows(m["plan"], rows, columns)
        if v:
            raise RuntimeError(f"复核未通过 {len(v)} 项: {v[:2]}")
        store.save_success_result(stem, columns, rows, len(rows), latest, meta)
        line = f'{stem:32s} {before} -> {len(rows)} 行  复核 0 违例  {time.time()-t0:.1f}s'
        print(line)
        report.append({"stem": stem, "before": before, "after": len(rows), "violations": 0})
    except Exception as e:
        line = f'{stem:32s} FAILED, 保留旧结果: {e}'
        print(line)
        report.append({"stem": stem, "before": before, "after": None, "error": str(e)})
json.dump(report, open('artifacts/verification/gem10_ruling/rerun_report.json', 'w',
                       encoding='utf-8'), ensure_ascii=False, indent=2)
print('report saved')
