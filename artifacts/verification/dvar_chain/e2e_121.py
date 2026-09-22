# -*- coding: utf-8 -*-
import sys, time, json
sys.path.insert(0, 'app')
import recognizer
import executor

text = open('artifacts/verification/dvar_chain/rule_121_dvar.txt', encoding='utf-8').read()
plan, summary, problems = recognizer.parse_single_rule(text)
assert not problems, problems
t0 = time.time()
result = executor.run_plan(plan, start_date='2025-01-01')
rows = result['rows'] if isinstance(result, dict) else result
t1 = time.time()
print(f'rows: {len(rows)}  耗时 {t1-t0:.1f}s')
v = executor.validate_rows(plan, rows, None)
print('violations:', len(v))
for x in v[:10]:
    print('  ', json.dumps(x, ensure_ascii=False))
if rows:
    print('columns:', list(rows[0].keys()))
    print('sample:', json.dumps(rows[0], ensure_ascii=False))
json.dump({'rows': len(rows), 'violations': len(v), 'seconds': round(t1-t0, 1)},
          open('artifacts/verification/dvar_chain/e2e_121_summary.json', 'w', encoding='utf-8'),
          ensure_ascii=False)
