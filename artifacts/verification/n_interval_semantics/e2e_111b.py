# -*- coding: utf-8 -*-
"""111B 原文端到端：新口径（N = 不含两端 K 线根数）下重跑，导出 CSV 供与 skill 侧对照。"""
import sys, time, json, csv
sys.path.insert(0, 'app')
import recognizer
import executor

RULE = 'artifacts/verification/dvar_chain/rule_121_ui.txt'
OUT = 'artifacts/verification/n_interval_semantics/workbench_111b_new.csv'

text = open(RULE, encoding='utf-8').read()
plan, summary, problems = recognizer.parse_single_rule(text)
assert not problems, problems
t0 = time.time()
res = executor.run_plan(plan)
rows, columns = res[0], res[1]
t1 = time.time()
if hasattr(rows, 'to_dict'):
    rows = rows.to_dict('records')
print(f'rows: {len(rows)}  耗时 {t1-t0:.1f}s')
with open(OUT, 'w', encoding='utf-8-sig', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=columns)
    w.writeheader()
    for r in rows:
        w.writerow({c: r.get(c, '') for c in columns})
v = executor.validate_rows(plan, rows, columns)
print('violations:', len(v))
for x in v[:8]:
    print('  ', json.dumps(x, ensure_ascii=False))
json.dump({'rows': len(rows), 'violations': len(v), 'seconds': round(t1-t0, 1),
           'columns': columns}, open('artifacts/verification/n_interval_semantics/e2e_111b_new.json', 'w', encoding='utf-8'),
          ensure_ascii=False, indent=2)
