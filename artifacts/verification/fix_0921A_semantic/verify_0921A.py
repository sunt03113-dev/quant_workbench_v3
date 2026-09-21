# -*- coding: utf-8 -*-
"""0921A 语义修复验收：重跑回测并与老系统正确结果全量比对。"""
import sys, json
sys.path.insert(0, "app")
import recognizer, executor

text = open("artifacts/verification/new_rules_20260921/rule_0921A.txt", encoding="utf-8").read()
plan, summary, problems = recognizer.parse_single_rule(text)
print("recognize problems:", problems)
sp = plan["strategy_plan"]
print("days:", json.dumps(sp["days"], ensure_ascii=False))

rows, cols, meta = executor.run_plan(plan)
print("our columns:", cols)
print("our rows:", len(rows))
viol = executor.validate_rows(plan, rows, cols)
print("validation violations:", len(viol), viol[:3])

# —— 与老系统正确结果比对 ——
import openpyxl
wb = openpyxl.load_workbook(
    r"C:\Users\21412\Documents\xwechat_files\wxid_7sttvfp6a58i12_bdb3\msg\file\2026-09\0921A_backtest.xlsx",
    read_only=True)
ws = wb.worksheets[0]
grows = list(ws.iter_rows(values_only=True))
wb.close()
ghdr = list(grows[0])
good = [dict(zip(ghdr, r)) for r in grows[1:]]
print("good columns:", ghdr)
print("good rows:", len(good))

gset = {(str(r["股票代码"]), str(r["D-0日期"]), str(r["x"])) for r in good}
oset = {(str(r["股票代码"]), str(r["D-0日期"]), str(r["x"])) for r in rows}
print("key overlap:", len(gset & oset), "only-good:", len(gset - oset), "only-ours:", len(oset - gset))

# 共同键逐列数值比对（数值容差 0.01，文本原样）
def num(v):
    try:
        return float(str(v).replace("%", "").replace("+", ""))
    except Exception:
        return None

od = {(str(r["股票代码"]), str(r["D-0日期"]), str(r["x"])): r for r in rows}
gd = {k: r for k, r in zip([(str(r["股票代码"]), str(r["D-0日期"]), str(r["x"])) for r in good], good)}
common = sorted(gset & oset)[:200]
diff_cnt = {}
for k in common:
    gr, orow = gd[k], od[k]
    for c in ghdr:
        if c in ("股票代码", "股票名称", "D-0日期"):
            continue
        # 列名映射：老系统 D-(x+2)振幅 / D-x~D-1区间涨幅 / D+2最高价 == 我们同名列
        v1, v2 = gr.get(c), orow.get(c)
        if v2 is None:
            diff_cnt.setdefault(c + " [缺列]", 0); diff_cnt[c + " [缺列]"] += 1; continue
        n1, n2 = num(v1), num(v2)
        if n1 is not None and n2 is not None:
            if abs(n1 - n2) > 0.011:
                diff_cnt.setdefault(c, 0); diff_cnt[c] += 1
        elif str(v1) != str(v2):
            diff_cnt.setdefault(c, 0); diff_cnt[c] += 1
print("共同键逐列差异统计（前200行）:", diff_cnt if diff_cnt else "无差异")
# 展示 3 行样例
for k in common[:3]:
    print("sample", k)
    print("  good:", {c: gd[k].get(c) for c in ghdr[3:9]})
    print("  ours:", {c: od[k].get(c) for c in ghdr[3:9]})
