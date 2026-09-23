# -*- coding: utf-8 -*-
"""区间语义落地自查（方案A）：用库内真实 rule_text 原文逐字喂识别器，打印计划结构。

不跑回测、不写库；只看识别结果里 days / ranges / quantifier 与回执文案。
"""
import sys, json, io
sys.path.insert(0, 'app')
import recognizer, store

OUT = io.StringIO()


def p(*a):
    print(*a)
    print(*a, file=OUT)


state = store.load_state()
models = state.get("models", {})
targets = [s for s, m in models.items()
           if isinstance(m.get("plan"), dict)
           and (m["plan"].get("strategy_plan") or {}).get("quantifier")]
p(f"库内带变量量词的模型 {len(targets)} 个\n")

report = {}
for stem in sorted(targets):
    m = models[stem]
    rt = m.get("rule_text") or ""
    p("=" * 92)
    p(f"### {stem}   rule_text={'有' if rt else '缺失'}")
    if not rt:
        report[stem] = {"error": "rule_text 缺失"}
        continue
    plan, summary, problems = recognizer.parse_single_rule(rt)
    if problems:
        p(f"  problems: {json.dumps(problems, ensure_ascii=False)}")
        report[stem] = {"problems": problems}
        continue
    sp = plan["strategy_plan"]
    p(f"  universe      : {sp.get('universe')}")
    p(f"  quantifier    : {sp.get('quantifier')}")
    p(f"  days          : {json.dumps(sp.get('days'), ensure_ascii=False)}")
    p(f"  ranges        : {json.dumps(sp.get('ranges'), ensure_ascii=False)}")
    p(f"  outputs       : {json.dumps([o['atom'] for o in sp.get('outputs')], ensure_ascii=False)}")
    p(f"  回执事件      : {json.dumps(summary['events'], ensure_ascii=False)}")
    p(f"  回执 notes    : {json.dumps(summary.get('notes', []), ensure_ascii=False)}")
    p(f"  base_rules    : {json.dumps(recognizer.plan_to_base_rules(plan), ensure_ascii=False)}")
    report[stem] = {"universe": sp.get("universe"),
                    "quantifier": sp.get("quantifier"),
                    "days": sp.get("days"), "ranges": sp.get("ranges"),
                    "notes": summary.get("notes", [])}

# —— 合成用例：显式写法 + 固定日区间 + 不应触发自动升级的对照 ——
p("=" * 92)
p("### 合成用例 A：显式区间写法（无 D-1 单列）")
rtA = ("【10cm】\n【筛选条件】\nD-0：涨停，成交额最大，股价最高\n"
       "D-x~D-1：全部不是涨停，成交额不是最大，股价不是最高\n"
       "D-(x+1)：不是涨停，成交额最大，股价最高\n2≤x≤11\n"
       "【输出指标】\nD-0：日期\nx：数值\n")
pl, su, pr = recognizer.parse_single_rule(rtA)
p(f"  problems={pr}")
p(f"  ranges  ={json.dumps((pl['strategy_plan'] or {}).get('ranges'), ensure_ascii=False)}")
p(f"  days    ={json.dumps((pl['strategy_plan'] or {}).get('days'), ensure_ascii=False)}")
p(f"  events  ={json.dumps(su['events'], ensure_ascii=False)}")

p("=" * 92)
p("### 合成用例 B：固定日区间（D-5~D-1，无变量日）")
rtB = ("【10cm】\n【筛选条件】\nD-0：涨停\nD-5~D-1：不是涨停，成交额不是最大\n"
       "【输出指标】\nD-0：日期\n")
plB, suB, prB = recognizer.parse_single_rule(rtB)
p(f"  problems={prB}")
p(f"  ranges  ={json.dumps((plB['strategy_plan'] or {}).get('ranges'), ensure_ascii=False)}")
p(f"  days    ={json.dumps((plB['strategy_plan'] or {}).get('days'), ensure_ascii=False)}")

p("=" * 92)
p("### 合成用例 C（对照，不该升级）：D-1 与 D-x 条件不同 且 无区间输出")
rtC = ("【10cm】\n【筛选条件】\nD-0：涨停\nD-1：不是涨停，成交额不是最大\n"
       "D-x：不是涨停\n2≤x≤11\n【输出指标】\nD-0：日期\nx：数值\n")
plC, suC, prC = recognizer.parse_single_rule(rtC)
p(f"  problems={prC}")
p(f"  ranges  ={json.dumps((plC['strategy_plan'] or {}).get('ranges'), ensure_ascii=False)}")
p(f"  days    ={json.dumps((plC['strategy_plan'] or {}).get('days'), ensure_ascii=False)}")

with open('artifacts/verification/1s1a_bug_0923/interval_impl_check.txt', 'w',
          encoding='utf-8') as fh:
    fh.write(OUT.getvalue())
with open('artifacts/verification/1s1a_bug_0923/interval_impl_report.json', 'w',
          encoding='utf-8') as fh:
    json.dump(report, fh, ensure_ascii=False, indent=2)
print("\n-> interval_impl_check.txt / interval_impl_report.json 已落盘")
