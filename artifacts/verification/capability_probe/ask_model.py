# -*- coding: utf-8 -*-
"""「询问模型」核验工具 —— 消费模型卡片「询问模型」按钮产出的质询。

铁律（kk 2026-09-22 定稿）：
  - 只调用现有 recognizer / executor / Skill 函数，零新增业务结构、零结论码表；
  - 单股路径 = monkeypatch executor._collect_stock_files 收窄宇宙，执行主体仍是原 run_plan；
  - 重跑与已存结果逐日期比对：不一致 → 只报异常（RERUN_VS_STORED_MISMATCH），不自行解释；
  - 只读：不写 current/previous、不改任何状态。

用法：
  python ask_model.py --stem 121_r1_v1 --code 688037 --date 20200117
  python ask_model.py --model 111b --code 000001            # stem 模糊匹配
  python ask_model.py --stem xxx --code 688037              # 不带日期 → 只列命中日与结果表比对
"""
import argparse
import json
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path

APP = Path(__file__).resolve().parents[3] / "app"
sys.path.insert(0, str(APP))

import numpy as np                      # noqa: E402
import executor                         # noqa: E402
import store                            # noqa: E402
from paths import STOCK_NAMES_FILE      # noqa: E402

OUT = Path(__file__).resolve().parent


def find_stem(keyword):
    state = store.load_state()
    models = state.get("models", {})
    if keyword in models:
        return keyword
    hits = [s for s in models if keyword.lower() in s.lower()]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise SystemExit(f"未找到匹配模型: {keyword}（在库 {len(models)} 个）")
    raise SystemExit("模糊匹配命中多个，请用完整 stem:\n  " + "\n  ".join(hits))


def code_from_query(query):
    """从质询串里提取 6 位代码与日期（如 688037 20200117 / 2020-01-17）。"""
    code = re.search(r"\b(\d{6})\b", query or "")
    date = re.search(r"\b(20\d{6}|20\d{2}[-/]\d{1,2}[-/]\d{1,2})\b", query or "")
    name = re.search(r"([\u4e00-\u9fa5]{2,8})", query or "")
    return (code.group(1) if code else None,
            date.group(1).replace("-", "").replace("/", "") if date else None,
            name.group(1) if name else None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stem", help="模型 stem（或 --model 模糊关键词）")
    ap.add_argument("--model", help="stem 模糊匹配关键词")
    ap.add_argument("--query", help="质询串，如「芯源微 688037 20200117」")
    ap.add_argument("--code")
    ap.add_argument("--date")
    a = ap.parse_args()

    stem = find_stem(a.stem or a.model)
    q_code, q_date, q_name = code_from_query(a.query) if a.query else (None, None, None)
    code = a.code or q_code
    date = int((a.date or q_date or "").replace("-", "")) if (a.date or q_date) else None

    got = store.get_rule(stem)
    if not got:
        raise SystemExit(f"模型无规则: {stem}")
    plan = got["strategy"]["plan"]
    rule_text = (got["strategy"].get("rule_text") or "").strip()
    sp = plan.get("strategy_plan") or {}
    universe = sp.get("universe") or "both"

    rep = {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
           "stem": stem, "universe": universe, "query": {"code": code, "date": date, "name": q_name},
           "data_source": "通达信本地 vipdoc 日线（appdata/market/vipdoc）"}

    # 名称反查（stock_names.csv 正扫，一行结论）
    if code is None and q_name:
        for ln in STOCK_NAMES_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
            p = ln.strip().split(",")
            if len(p) >= 2 and q_name in p[1]:
                code = p[0].strip()
                rep["name_resolved"] = {"name": q_name, "code": code,
                                        "source": "appdata/stock_names.csv"}
                break
    if code is None:
        raise SystemExit("未提供股票代码且质询串中无可识别代码/名称")

    # 1) 池内判定（_collect_stock_files，禁止"sh 优先"搜索）
    pool = dict((c, f) for c, f in executor._collect_stock_files(universe))
    day_file = pool.get(code)
    rep["in_pool"] = day_file is not None
    if not rep["in_pool"]:
        rep["verdict"] = ("该股不在本模型宇宙内：universe=%s 的池子不含该代码"
                          "（_collect_stock_files 板块过滤），结果中无该股属预期。" % universe)
        finish(rep, stem)
        return

    # 2) 该股日线 + 目标日位置（read_day_file）
    res = executor.read_day_file(day_file)
    dates, opens, highs, lows, closes, amounts, volumes = res
    amounts = amounts.astype(np.float64, copy=False)
    i = int(np.searchsorted(dates, date)) if date else None
    on_day = i is not None and i < len(dates) and int(dates[i]) == date if date else None
    rep["day_file"] = {"path": str(day_file), "first": int(dates[0]),
                       "last": int(dates[-1]), "n_bars": len(dates)}
    if date:
        rep["target_day"] = {"date": date, "present": bool(on_day),
                             "bar_index": i if on_day else None,
                             "in_first_5_nolimit_window": bool(i is not None and i < 5),
                             "listing_first_day": int(dates[0])}

    # 3) 目标日实际数值（全部来自现有 Skill/executor 函数）
    if date and on_day:
        close_c = np.round(closes * 100).astype(np.int64)
        high_c = np.round(highs * 100).astype(np.int64)
        limits = executor.compute_limit_flags(dates, close_c, high_c, code)
        amt_max20 = executor.rolling_max20(amounts)
        high_max20 = executor.rolling_max20(highs)
        with np.errstate(invalid="ignore"):
            is_amtmax = np.zeros(len(dates), dtype=bool)
            is_highmax = np.zeros(len(dates), dtype=bool)
            is_amtmax[19:] = amounts[19:] == amt_max20[19:]
            is_highmax[19:] = highs[19:] == high_max20[19:]
        y = float(closes[i - 1]) if i > 0 else None
        scal10 = bool(executor._bc.is_limit_up_sealed_decimal(
            closes[i], highs[i], y, executor._bc.Decimal("0.10"))) if y else False
        scal20 = bool(executor._bc.is_limit_up_sealed_decimal(
            closes[i], highs[i], y, executor._bc.Decimal("0.20"))) if y else False
        prev5 = [int(dates[j]) for j in range(max(0, i - 5), i) if limits[j]]
        rep["values_at_date"] = {
            "open": float(opens[i]), "high": float(highs[i]), "low": float(lows[i]),
            "close": float(closes[i]), "prev_close": y,
            "limit_price_20pct": round(y * 1.2, 2) if y else None,
            "limit_price_10pct": round(y * 1.1, 2) if y else None,
            "vector_limit_up": bool(limits[i]),
            "scalar_limit_up_10pct": scal10, "scalar_limit_up_20pct": scal20,
            "amount": float(amounts[i]), "amt_max20": float(amt_max20[i]),
            "amount_is_20d_max": bool(is_amtmax[i]),
            "high_is_20d_max": bool(is_highmax[i]),
            "prev5_limit_days": prev5,
        }

    # 4) 单股重跑（原 run_plan，收窄宇宙）+ 复核
    orig = executor._collect_stock_files
    try:
        executor._collect_stock_files = lambda u: [(code, day_file)]
        rows, columns, meta = executor.run_plan(plan, end_date=executor.data_latest_payload()["latest_date"])
    finally:
        executor._collect_stock_files = orig
    viol = executor.validate_rows(plan, rows, columns)
    d0col = next((c for c in columns if c.endswith("日期")), None)
    hit_dates = sorted({str(r.get(d0col)) for r in rows}) if d0col else []
    rep["rerun"] = {"n_rows": len(rows), "n_hit_dates": len(hit_dates),
                    "hit_dates": hit_dates, "recheck_violations": len(viol),
                    "date_col": d0col,
                    "sample_row": rows[0] if rows else None}

    # 5) 与已存结果逐日期比对（不一致 → 异常，不解释）
    cur = store.load_result(stem, "current")
    if cur:
        c_d0 = next((c for c in cur["columns"] if c.endswith("日期")), None)
        rows_code = [r for r in cur["rows"] if r.get("股票代码") == code]
        stored = sorted({str(r.get(c_d0)) for r in rows_code}) if c_d0 else []
        rep["stored_table"] = {"n_rows_total": len(cur["rows"]),
                               "n_rows_this_stock": len(rows_code),
                               "this_stock_dates": stored}
        if date:
            rep["target_in_rerun"] = (f"{date // 10000:04d}-{date % 10000 // 100:02d}-{date % 100:02d}") in hit_dates
            rep["target_in_stored"] = (f"{date // 10000:04d}-{date % 10000 // 100:02d}-{date % 100:02d}") in stored
        only_rerun = [d for d in hit_dates if d not in stored]
        only_stored = [d for d in stored if d not in hit_dates]
        rep["diff"] = {"rerun_only": only_rerun, "stored_only": only_stored}
        rep["consistency"] = "OK" if not (only_rerun or only_stored) else "RERUN_VS_STORED_MISMATCH"
    else:
        rep["consistency"] = "NO_STORED_RESULT"

    # 6) 人话结论（事实拼装，不用码表；不一致只报异常）
    rep["verdict"] = build_verdict(rep)
    finish(rep, stem)


def build_verdict(rep):
    v = rep["values_at_date"] if "values_at_date" in rep else None
    if not rep["in_pool"]:
        return rep["verdict"]
    if rep["consistency"] == "RERUN_VS_STORED_MISMATCH":
        return ("⚠️ 异常：单股重跑与已存结果不一致（rerun_only=%s, stored_only=%s）。"
                "按约定只报异常、不自行解释，请回传开发机核查。"
                % (rep["diff"]["rerun_only"], rep["diff"]["stored_only"]))
    d = rep.get("target_day") or {}
    if d.get("present") is False:
        return f"该股当日无行情数据（{d.get('date')} 不在其日线内，区间 {d.get('listing_first_day')}~{rep['day_file']['last']}）。"
    if v is None:
        return (f"在池（universe={rep['universe']}）。该股共命中 {rep['rerun']['n_hit_dates']} 个日期，"
                f"与已存结果{'一致' if rep['consistency'] == 'OK' else rep['consistency']}。")
    lp = v["limit_price_20pct"]
    if not (v["vector_limit_up"] or v["scalar_limit_up_10pct"] or v["scalar_limit_up_20pct"]):
        why = f"当日收盘 {v['close']} / 最高 {v['high']}，均不等于涨停价（20% 口径 {lp}）→ 未封死涨停"
        if d.get("in_first_5_nolimit_window"):
            why = "该日处于上市前 5 个交易日（无涨跌幅限制），严格 == 口径剔除无涨跌幅限制日"
        extra = []
        if v["amount_is_20d_max"]:
            extra.append("但成交额为近20日最大")
        if v["high_is_20d_max"]:
            extra.append("最高价为近20日最高")
        if v["prev5_limit_days"]:
            extra.append(f"且前5日内有涨停日 {v['prev5_limit_days']}")
        base = f"{why}；对要求「该日为涨停」的条件不成立 → 不是遗漏"
        if extra:
            return base + "；但" + "、".join(extra) + "。"
        return base + "。"
    return (f"当日为封死涨停（收=高=涨停价 {lp}）。该股在重跑中{'命中' if rep['target_in_rerun'] else '未命中'}该日期，"
            f"已存结果{'含' if rep['target_in_stored'] else '不含'}该行"
            + ("；两者一致。" if rep["consistency"] == "OK" else f"；一致性={rep['consistency']}。"))


def finish(rep, stem):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = OUT / f"ask_{stem}_{ts}.json"
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    print(f"\n[报告] {out}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(1)
