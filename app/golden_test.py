# -*- coding: utf-8 -*-
"""STEP 3: Golden 一致性测试 harness。

协议（fail-closed）：
  1. 每条规则用冻结规则文本（rule.txt；0908B 取自 Skill 脚本 docstring 的权威时间线）识别成 plan。
     识别失败 = 能力缺口（FAIL_CLOSED capability gap），不猜测。
  2. 截止日 C = golden CSV 中最大 D-0 日期（end_date=C 锁定命中集）。
     数据截断 = C 之后的第 6 个交易日（覆盖 T+6/T+7 视野；实际可用数据为准）。
  3. 比对：
     - 命中集 (code, D-0) 必须完全一致；
     - D-* 列值必须完全一致（列名归一化 ~ -> /，Skill 各脚本分隔符本就不一致，非业务差异）；
     - T 列：golden N/A（生成时点无未来数据）为时点差异，单独归类；
       双方均有值但不一致 = 真实冲突（fail-closed）；
       T+0(低/高) 的取整方向差异为 STEP 2 已发现的已知冲突，单独聚合上报裁决。
  4. 任何真实冲突 -> 生成 conflict report，停止，不修改 Golden / Skill / comparator。

用法： python golden_test.py [rule_name ...]   # 缺省跑全部
"""
import csv
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
OUT = ROOT / "artifacts" / "verification" / "step3"
OUT.mkdir(parents=True, exist_ok=True)

import numpy as np  # noqa: E402
import executor  # noqa: E402
import recognizer  # noqa: E402

SKILL = ROOT / "skill" / "tdx-stock-backtest-master"

# 0908B 规则文本：来自 Skill 0908B_backtest.py docstring（业务权威定义）逐条重建
RULE_0908B = """0908B
【20cm】

【筛选条件】
D-0：涨停，成交额最大，股价最高。
D-1：不是涨停，成交额不是最大
D-2：不是涨停，成交额不是最大
D-3：不是涨停，成交额不是最大
D-4：不是涨停，成交额非20日最大
D-5：不是涨停，成交额最大
D-6：不是涨停，成交额最大
D-7：不是涨停，成交额不是最大
D-8：不是涨停，成交额不是最大

【输出指标】
D-0：日期
D-6：振幅
D-5：振幅
D-6/D-5：区间涨幅；区间振幅
D-4/D-1：区间涨幅；区间振幅；区间最大振幅
D-0：振幅
D-0/D-5：成交额百分比
T+0/T+6：价格走势
"""


def load_rule_texts():
    """rule.txt -> {rule_name: rule_text}；0908B 用 docstring 重建文本。"""
    raw = (ROOT / "golden" / "rule.txt").read_text(encoding="utf-8").splitlines()
    sections = {}
    cur_name, cur = None, []
    for ln in raw:
        if re.fullmatch(r"\d{4}[A-E]?", ln.strip()):
            if cur_name:
                sections[cur_name] = "\n".join(cur)
            cur_name, cur = ln.strip(), []
        elif cur_name is not None:
            cur.append(ln)
    if cur_name:
        sections[cur_name] = "\n".join(cur)
    sections["0908B"] = RULE_0908B
    return sections


def load_golden(name):
    f = ROOT / "golden" / f"{name}_backtest" / f"{name}_backtest.csv"
    with open(f, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    header, data = rows[0], rows[1:]
    recs = []
    for r in data:
        if not r or not r[0].strip():
            continue
        rec = {header[i]: (r[i].strip() if i < len(r) else "") for i in range(len(header))}
        rec["股票代码"] = rec["股票代码"].zfill(6)
        recs.append(rec)
    return header, recs


def _is_na(v):
    return v is None or str(v).strip() in ("", "N/A", "nan", "NaN", "None", "--")


def _val_eq(a, b):
    """数值化比较（容忍 5% vs 5.0%）；否则字符串精确比较。"""
    sa, sb = str(a).strip(), str(b).strip()
    if sa == sb:
        return True
    pa = re.fullmatch(r"([+-]?\d+(?:\.\d+)?)%?", sa.replace(" ", ""))
    pb = re.fullmatch(r"([+-]?\d+(?:\.\d+)?)%?", sb.replace(" ", ""))
    if pa and pb:
        return abs(float(pa.group(1)) - float(pb.group(1))) < 1e-9
    return False


def norm_col(c):
    return c.replace("~", "/")


def trading_dates():
    """用上证指数 .day 构建交易日历（升序 int）。"""
    import struct
    from paths import DAY_DIRS
    for d in DAY_DIRS:
        p = Path(d) / "sh000001.day"
        if p.exists():
            data = p.read_bytes()
            n = len(data) // 32
            out = []
            for k in range(n):
                out.append(struct.unpack("<I", data[k * 32:k * 32 + 4])[0])
            return out
    raise RuntimeError("无交易日历来源 sh000001.day")


def run_rule(name, rule_text, log):
    res = {"rule": name, "recognize": None, "verdict": None, "detail": {}}
    rec = recognizer.recognize(rule_text)
    if rec["status"] != "READY":
        res["recognize"] = "FAIL_CLOSED"
        res["verdict"] = "CAPABILITY_GAP"
        res["detail"]["failure"] = rec.get("failure", {})
        return res
    res["recognize"] = "READY"
    plan = rec["plan"]

    header, golden = load_golden(name)
    if "D-0日期" not in header:
        res["verdict"] = "CAPABILITY_GAP"
        res["detail"]["note"] = "golden 列结构与向后日模式不同（前向/间隔窗口规则），当前 plan schema 未覆盖"
        res["detail"]["golden_columns"] = header
        return res
    d0i = header.index("D-0日期")
    C = max(r["D-0日期"] for r in golden)
    cal = trading_dates()
    c_int = int(C.replace("-", ""))
    pos = cal.index(c_int) if c_int in cal else -1
    ext = cal[min(pos + 6, len(cal) - 1)] if pos >= 0 else c_int
    ext_s = f"{ext:04d}-{ext // 100 % 100:02d}-{ext % 100:02d}"
    res["detail"]["cutoff_d0"] = C
    res["detail"]["data_end"] = ext_s
    has_t = any(c.startswith("T+") for c in header)

    t0 = time.time()
    rows, columns, meta = executor.run_plan(plan, end_date=C, data_end=ext_s)
    res["detail"]["run_seconds"] = round(time.time() - t0, 1)
    res["detail"]["our_rows"] = len(rows)

    # ---- 命中集 ----
    g_keys = {(r["股票代码"], r["D-0日期"]) for r in golden}
    o_keys = {(str(r["股票代码"]).zfill(6), r["D-0日期"]) for r in rows}
    res["detail"]["hits"] = {
        "golden": len(g_keys), "ours": len(o_keys),
        "missing": sorted(g_keys - o_keys)[:20], "n_missing": len(g_keys - o_keys),
        "extra": sorted(o_keys - g_keys)[:20], "n_extra": len(o_keys - g_keys),
    }

    # ---- 列值 ----
    g_by_key = {(r["股票代码"], r["D-0日期"]): r for r in golden}
    o_by_key = {(str(r["股票代码"]).zfill(6), r["D-0日期"]): r for r in rows}
    col_stats = {}
    for col in header:
        if col in ("股票代码", "股票名称", "D-0日期"):
            continue
        ncol = norm_col(col)
        stats = {"n": 0, "diff": 0, "golden_na": 0, "ours_na": 0, "ours_missing_col": False,
                 "samples": []}
        for key in g_keys & o_keys:
            gv = g_by_key[key].get(col, "")
            ov = o_by_key[key].get(ncol)
            if ov is None and ncol not in columns:
                stats["ours_missing_col"] = True
                continue
            ov = "" if ov is None else str(ov)
            stats["n"] += 1
            g_na, o_na = _is_na(gv), _is_na(ov)
            if g_na and o_na:
                continue
            if g_na:
                stats["golden_na"] += 1  # 时点差异（golden 生成时无未来数据）
            elif o_na:
                stats["ours_na"] += 1
                if len(stats["samples"]) < 5:
                    stats["samples"].append({"key": key, "golden": gv, "ours": ov})
            elif not _val_eq(gv, ov):
                stats["diff"] += 1
                if len(stats["samples"]) < 5:
                    stats["samples"].append({"key": key, "golden": gv, "ours": ov})
        col_stats[col] = stats
    res["detail"]["columns"] = col_stats
    res["detail"]["our_columns"] = columns
    return res


def classify(res):
    if res["verdict"] == "CAPABILITY_GAP":
        return res["verdict"]
    d = res["detail"]
    h = d["hits"]
    conflicts = []
    notes = []
    if h["n_missing"] or h["n_extra"]:
        conflicts.append(f"命中集不一致: 缺失{h['n_missing']} 多余{h['n_extra']}")
    for col, st in d["columns"].items():
        if st["ours_missing_col"]:
            notes.append(f"{col}: 本实现无此列（golden 附加列）")
            continue
        if st["diff"]:
            if col == "T+0(低/高)":
                notes.append(f"T+0(低/高): {st['diff']} 行取整方向差异（STEP 2 已知冲突）")
            else:
                conflicts.append(f"{col}: {st['diff']} 行值不一致")
        if st["ours_na"]:
            conflicts.append(f"{col}: {st['ours_na']} 行 golden 有值而本实现 N/A（数据视野异常）")
        if st["golden_na"]:
            notes.append(f"{col}: {st['golden_na']} 行 golden N/A（生成时点差异，时序性豁免）")
    if conflicts:
        res["verdict"] = "CONFLICT"
        res["detail"]["conflicts"] = conflicts
    elif any("取整方向差异" in n for n in notes):
        res["verdict"] = "PASS_WITH_KNOWN_T0_CONFLICT"
        res["detail"]["notes"] = notes
    else:
        res["verdict"] = "PASS"
        res["detail"]["notes"] = notes
    return res["verdict"]


def main():
    rules = load_rule_texts()
    targets = sys.argv[1:] or sorted(rules)
    log = []
    results = []
    for name in targets:
        if name not in rules:
            print(f"SKIP {name}: rule.txt 无此规则文本")
            continue
        print(f"=== {name} ===", flush=True)
        try:
            r = run_rule(name, rules[name], log)
            classify(r)
        except Exception as e:  # noqa: BLE001
            import traceback
            r = {"rule": name, "verdict": "ERROR", "detail": {"error": str(e),
                 "traceback": traceback.format_exc()}}
        results.append(r)
        print(f"  -> {r['verdict']}", flush=True)

    summary = {"total": len(results),
               "by_verdict": {}}
    for r in results:
        summary["by_verdict"].setdefault(r["verdict"], []).append(r["rule"])
    (OUT / "golden_test_results.json").write_text(
        json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
