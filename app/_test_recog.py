import json, sys
sys.path.insert(0, "app")
import recognizer

text = open("app/_test_rule_1s1.txt", encoding="utf-8").read()
r = recognizer.recognize(text)
print("status:", r["status"])
if r["status"] == "READY":
    sp = r["plan"]["strategy_plan"]
    print("quantifier:", sp.get("quantifier"))
    print("days:", json.dumps(sp["days"], ensure_ascii=False))
    print("outputs:", json.dumps(sp["outputs"], ensure_ascii=False))
    print("summary_events:", json.dumps([e["id"] for e in r["plan_summary"]["events"]], ensure_ascii=False))
else:
    print(json.dumps(r.get("failure", r), ensure_ascii=False, indent=1))
