# -*- coding: utf-8 -*-
"""111A3 间隔链回归：T- 连字符记号 + 链式执行 + 复核。"""
import sys, json
sys.path.insert(0, "app")
import recognizer, executor

text = """【筛选条件】
1. T_0首板，T_0前4日无涨停
2.T_0-T_1间隔N1∈[1,3]、T_1-T_2隔N2∈[1,4]，N1/N2自由组合；
3. T_2的成交额不小于T_0、T_1的成交额；
4. T_2的成交额和股价均是20日最高
5. T_0与T_1间、T_1与T_2间无涨停，仅T_0、T_1、T_2三日涨停；
【输出指标】
T_2的日期、T_0与T_1间隔交易日天数N1、T_1与T_2间隔的交易日天数N2、T_0~T_2区间涨幅、T_0~T_2区间振幅、T_2振幅
"""
# 用 T- 连字符写法重写一遍，验证等价性
text_dash = text.replace("T_0", "T-0").replace("T_1", "T-1").replace("T_2", "T-2")

p1 = recognizer.parse_single_rule(text)
p2 = recognizer.parse_single_rule(text_dash)
print("underscore problems:", p1[2])
print("dash      problems:", p2[2])
print("plan equal:", json.dumps(p1[0], ensure_ascii=False, sort_keys=True) ==
      json.dumps(p2[0], ensure_ascii=False, sort_keys=True))

rows, cols, meta = executor.run_plan(p1[0])
viol = executor.validate_rows(p1[0], rows, cols)
print("chain backtest rows:", len(rows), "violations:", len(viol))
print("cols:", cols)
print("row0:", json.dumps(rows[0], ensure_ascii=False)[:220] if rows else "-")
