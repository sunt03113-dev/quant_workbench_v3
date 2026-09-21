import json, sys, time
sys.path.insert(0, "app")
import recognizer, executor

text = open("app/_test_rule_1s1.txt", encoding="utf-8").read()
r = recognizer.recognize(text)
assert r["status"] == "READY", r
plan = r["plan"]

t0 = time.time()
rows, columns, meta = executor.run_plan(plan, end_date="2026-09-18")
print("elapsed: %.1fs  rows: %d" % (time.time() - t0, len(rows)))
print("columns:", columns)
print("meta:", meta)
if rows:
    print("sample:", json.dumps(rows[0], ensure_ascii=False))
    print("sample:", json.dumps(rows[1], ensure_ascii=False))
v = executor.validate_rows(plan, rows, columns)
print("violations:", len(v), v[:3])
