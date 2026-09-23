# -*- coding: utf-8 -*-
"""工作台内置质询（ask）—— UI「询问模型」入口的确定性核验后端。

铁律（kk 2026-09-22 定稿，2026-09-23 起由剪贴板桥改为工作台内问答）：
  - 只调用现有 recognizer / executor / Skill 判定函数，零新增业务判定逻辑；
  - 单股路径 = monkeypatch executor._collect_stock_files 收窄宇宙，执行主体仍是原 run_plan；
  - 重跑与已存结果逐日期比对：不一致 → 只报异常（RERUN_VS_STORED_MISMATCH），不自行解释；
  - 只读：不写 current/previous、不改任何状态。

结论与数字均来自代码判定，本模块只做事实拼装；所有行情数据来源为通达信本地 vipdoc 日线。
"""
import re

import numpy as np

import executor
import store
from paths import SKILL_DIR, STOCK_NAMES_FILE

_DOC = SKILL_DIR / "tdx-stock-backtest.md"


def find_stem(keyword):
    state = store.load_state()
    models = state.get("models", {})
    if keyword in models:
        return keyword
    hits = [s for s in models if keyword.lower() in s.lower()]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise ValueError(f"未找到匹配模型: {keyword}（在库 {len(models)} 个）")
    raise ValueError("模糊匹配命中多个，请用完整 stem: " + "、".join(hits))


def parse_query(query):
    """质询串 -> (code, date, name)，如「芯源微 688037 20200117 / 2020-01-17」。"""
    code = re.search(r"\b(\d{6})\b", query or "")
    date = re.search(r"\b(20\d{6}|20\d{2}[-/]\d{1,2}[-/]\d{1,2})\b", query or "")
    name = re.search(r"([\u4e00-\u9fa5]{2,8})", query or "")
    return (code.group(1) if code else None,
            date.group(1).replace("-", "").replace("/", "") if date else None,
            name.group(1) if name else None)


def ask(stem_kw, code=None, date=None, query=None):
    """确定性核验。返回 dict（只读，不落盘）。抛 ValueError = 参数问题。"""
    stem = find_stem(stem_kw)
    q_code, q_date, q_name = parse_query(query) if query else (None, None, None)
    code = code or q_code
    date = int((date or q_date or "").replace("-", "")) if (date or q_date) else None

    got = store.get_rule(stem)
    if not got:
        raise ValueError(f"模型无规则: {stem}")
    plan = got["strategy"]["plan"]
    rule_text = (got["strategy"].get("rule_text") or "").strip()
    sp = plan.get("strategy_plan") or {}
    universe = sp.get("universe") or "both"

    rep = {"stem": stem, "universe": universe, "rule_text": rule_text,
           "query": {"code": code, "date": date, "name": q_name},
           "data_source": "通达信本地 vipdoc 日线（appdata/market/vipdoc）"}

    if code is None and q_name:
        for ln in STOCK_NAMES_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
            p = ln.strip().split(",")
            if len(p) >= 2 and q_name in p[1]:
                code = p[0].strip()
                rep["name_resolved"] = {"name": q_name, "code": code,
                                        "source": "appdata/stock_names.csv"}
                break
    if code is None:
        # 无代码/名称 → 通用问答（口径/规则/统计类，确定性回答，不猜）
        return answer_general(stem, plan, rule_text, universe, query or "")

    # 1) 池内判定（_collect_stock_files，禁止"sh 优先"搜索）
    pool = dict((c, f) for c, f in executor._collect_stock_files(universe))
    day_file = pool.get(code)
    rep["in_pool"] = day_file is not None
    if not rep["in_pool"]:
        rep["verdict"] = (f"该股不在本模型宇宙内：universe={universe} 的池子不含 {code}"
                          "（板块过滤），结果中无该股属预期。")
        return rep

    # 2) 该股日线 + 目标日位置
    dates, opens, highs, lows, closes, amounts, volumes = executor.read_day_file(day_file)
    amounts = amounts.astype(np.float64, copy=False)
    i = int(np.searchsorted(dates, date)) if date else None
    on_day = i is not None and i < len(dates) and int(dates[i]) == date if date else None
    rep["day_file"] = {"first": int(dates[0]), "last": int(dates[-1]), "n_bars": len(dates)}
    if date:
        rep["target_day"] = {"date": date, "present": bool(on_day),
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
        rep["values_at_date"] = {
            "open": float(opens[i]), "high": float(highs[i]), "low": float(lows[i]),
            "close": float(closes[i]), "prev_close": y,
            "limit_price_20pct": round(y * 1.2, 2) if y else None,
            "limit_price_10pct": round(y * 1.1, 2) if y else None,
            "limit_up": bool(limits[i]),
            "scalar_limit_up_10pct": scal10, "scalar_limit_up_20pct": scal20,
            "amount": float(amounts[i]),
            "amount_is_20d_max": bool(is_amtmax[i]),
            "high_is_20d_max": bool(is_highmax[i]),
        }

    # 4) 单股重跑（原 run_plan，收窄宇宙）+ 复核
    orig = executor._collect_stock_files
    try:
        executor._collect_stock_files = lambda u: [(code, day_file)]
        rows, columns, meta = executor.run_plan(
            plan, end_date=executor.data_latest_payload()["latest_date"])
    finally:
        executor._collect_stock_files = orig
    viol = executor.validate_rows(plan, rows, columns)
    d0col = next((c for c in columns if c.endswith("日期")), None)
    hit_dates = sorted({str(r.get(d0col)) for r in rows}) if d0col else []
    rep["rerun"] = {"n_rows": len(rows), "n_hit_dates": len(hit_dates),
                    "hit_dates": hit_dates, "recheck_violations": len(viol),
                    "date_col": d0col}

    # 5) 与已存结果逐日期比对（不一致 → 异常，不解释）
    cur = store.load_result(stem, "current")
    rep["consistency"] = "OK"
    if cur:
        c_d0 = next((c for c in cur["columns"] if c.endswith("日期")), None)
        rows_code = [r for r in cur["rows"] if r.get("股票代码") == code]
        stored = sorted({str(r.get(c_d0)) for r in rows_code}) if c_d0 else []
        rep["stored_table"] = {"n_rows_total": len(cur["rows"]),
                               "n_rows_this_stock": len(rows_code),
                               "this_stock_dates": stored}
        if date:
            iso = f"{date // 10000:04d}-{date % 10000 // 100:02d}-{date % 100:02d}"
            rep["target_in_rerun"] = iso in hit_dates
            rep["target_in_stored"] = iso in stored
        only_rerun = [d for d in hit_dates if d not in stored]
        only_stored = [d for d in stored if d not in hit_dates]
        rep["diff"] = {"rerun_only": only_rerun, "stored_only": only_stored}
        rep["consistency"] = ("OK" if not (only_rerun or only_stored)
                              else "RERUN_VS_STORED_MISMATCH")
    else:
        rep["consistency"] = "NO_STORED_RESULT"

    rep["verdict"] = _verdict(rep)
    return rep


def _verdict(rep):
    if rep["consistency"] == "RERUN_VS_STORED_MISMATCH":
        return ("⚠️ 异常：单股重跑与已存结果不一致（rerun_only=%s, stored_only=%s）。"
                "按约定只报异常、不自行解释，请回传开发机核查。"
                % (rep["diff"]["rerun_only"], rep["diff"]["stored_only"]))
    d = rep.get("target_day") or {}
    if d.get("present") is False:
        return (f"该股当日无行情数据（{d.get('date')} 不在其日线内，"
                f"区间 {d.get('listing_first_day')}~{rep['day_file']['last']}）。")
    v = rep.get("values_at_date")
    if v is None:
        return (f"在池（universe={rep['universe']}）。该股共命中 {rep['rerun']['n_hit_dates']} 个日期，"
                f"与已存结果{'一致' if rep['consistency'] == 'OK' else rep['consistency']}。")
    if not (v["limit_up"] or v["scalar_limit_up_10pct"] or v["scalar_limit_up_20pct"]):
        lp = v["limit_price_20pct"]
        why = (f"当日收盘 {v['close']} / 最高 {v['high']}，均不等于涨停价（20% 口径 {lp}）→ 未封死涨停；"
               "对要求「该日为涨停」的条件不成立 → 不是遗漏")
        extra = []
        if d.get("in_first_5_nolimit_window"):
            extra.append("该日处于上市前 5 个交易日（无涨跌幅限制），严格 == 口径剔除")
        if v["amount_is_20d_max"]:
            extra.append("但成交额为近20日最大")
        if v["high_is_20d_max"]:
            extra.append("最高价为近20日最高")
        return why + ("；" + "、".join(extra) + "。" if extra else "。")
    lp = v["limit_price_20pct"]
    return (f"当日为封死涨停（收=高=涨停价 {lp}）。该股在重跑中{'命中' if rep.get('target_in_rerun') else '未命中'}该日期，"
            f"已存结果{'含' if rep.get('target_in_stored') else '不含'}该行"
            + ("；两者一致。" if rep["consistency"] == "OK" else f"；一致性={rep['consistency']}。"))


# ===================== 通用问答（口径/规则/统计，确定性，不猜） =====================
# 答案三来源，全部随包、可复核：① skill/tdx-stock-backtest.md 原文摘录（口径文档）；
# ② 当前模型 plan 与已存结果表取数；③ 能力清单（兜底，绝不编造）。

def _doc_excerpt(heading_re, max_lines=45):
    """从随包口径文档按标题摘录原文（文件缺失/无匹配 → None）。"""
    try:
        lines = _DOC.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    out, on = [], False
    for ln in lines:
        if re.match(r"^#{2,4} ", ln):
            if on:
                break
            on = bool(re.search(heading_re, ln))
            if on:
                out.append(ln)
            continue
        if on:
            out.append(ln)
            if len(out) >= max_lines:
                break
    txt = "\n".join(out).strip()
    return txt or None


def _result_stats(stem):
    cur = store.load_result(stem, "current")
    if not cur:
        return None
    rows = cur.get("rows") or []
    d0 = next((c for c in cur.get("columns") or [] if c.endswith("日期")), None)
    dates = sorted({str(r.get(d0)) for r in rows if r.get(d0)}) if d0 else []
    codes = sorted({str(r.get("股票代码")) for r in rows if r.get("股票代码")})
    return {"n_rows": len(rows), "n_stocks": len(codes),
            "codes": codes,
            "date_min": dates[0] if dates else None, "date_max": dates[-1] if dates else None,
            "recent_dates": dates[-8:], "columns": list(cur.get("columns") or [])}


_INTENTS = [
    (r"间隔|N1|N2", "interval"),
    (r"振幅", "amplitude"),
    (r"涨停|封板|封死|涨跌幅限制|_limit", "limit"),
    (r"涨幅|涨跌|怎么算|如何计算|计算|什么意思|定义", "change"),
    (r"走势|前向|T\+|窗口", "walk"),
    (r"成交额|成交量|量能", "amount"),
    (r"池|宇宙|universe|范围|哪些股票|板块", "universe"),
    (r"命中|结果|统计|多少|最近", "stats"),
]


_BOARD_WORDS = [("科创板", ["688", "689"]), ("创业板", ["300", "301"]), ("主板", ["600", "000"])]


def _detect_prefixes(question):
    """从问题中提取代码前缀意图：『30开头』/『创业板』等 → ['30']；无 → None。"""
    q = question or ""
    m = re.findall(r"(301|300|688|689|605|603|601|600|003|002|001|000|30|60|00|68)开头", q)
    if m:
        seen, out = set(), []
        for x in m:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out
    for word, pref in _BOARD_WORDS:
        if word in q:
            return list(pref)
    return None


def _names_map():
    """code -> name（appdata/stock_names.csv，三源合一产物）。"""
    out = {}
    try:
        for ln in STOCK_NAMES_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
            p = ln.strip().split(",")
            if len(p) >= 2 and re.fullmatch(r"\d{6}", p[0].strip()):
                out.setdefault(p[0].strip(), p[1].strip())
    except OSError:
        pass
    return out


# ── 结果条件核验（2026-09-23：质询「结果是否满足/包含规则条件」类问题）──────────
_COND_TRIGGER = re.compile(r"没这个条件|条件吗|满足|符合|核实|核对|逐条|漏了|少了")


def _label_day(d):
    if "offset_var" in d:
        k = d["offset_var"]
        return "D-x" if k == 0 else f"D-(x+{k})"
    return f"D-{abs(d.get('offset', 0))}"


def _label_range_end(spec):
    """区间条件端点标签：变量端 {"var":k} -> D-x / D-(x+k)；固定端 int -> D-n / D+n。"""
    if isinstance(spec, dict):
        k = spec.get("var", 0)
        return "D-x" if k == 0 else (f"D-(x+{k})" if k > 0 else f"D-(x{k})")
    return f"D-{abs(spec)}" if spec <= 0 else f"D+{spec}"


def _cond_desc(d):
    parts = []
    if d.get("limit_up") is True:
        parts.append("涨停")
    elif d.get("limit_up") is False:
        parts.append("非涨停")
    if d.get("amount_max20") is True:
        parts.append("成交额为20日最大")
    elif d.get("amount_max20") is False:
        parts.append("成交额非20日最大")
    if d.get("high_max20") is True:
        parts.append("股价为20日最高")
    elif d.get("high_max20") is False:
        parts.append("股价非20日最高")
    return "、".join(parts) if parts else "（无该日条件）"


_CONDCHECK_CACHE = {}  # (stem, data_date, n_rows) -> violations


def _answer_condcheck(stem, plan, universe, question, stats):
    """条件核验：列出识别计划包含的日条件 + 引擎对已存结果的逐行复核结论。零新增判定。"""
    sp = (plan.get("strategy_plan") or {}) if isinstance(plan, dict) else {}
    days = sp.get("days") or []
    quant = sp.get("quantifier") or {}
    ranges = sp.get("ranges") or []
    paras = ["识别计划包含以下日条件（每行命中都必须逐条满足）："]
    for d in days:
        paras.append(f"· {_label_day(d)}：{_cond_desc(d)}")
    for rg in ranges:
        lb = rg.get("label") or f"{_label_range_end(rg.get('from'))}~{_label_range_end(rg.get('to'))}"
        paras.append(f"· {lb}（**整段区间**）：{_cond_desc(rg.get('conds') or {})}"
                     " ——区间内**每一天**都必须满足（2026-09-23 区间语义裁定）")
    if quant:
        paras.append(f"· 量词：x ∈ [{quant.get('min')}, {quant.get('max')}]"
                     "（范围内每个 x 单独取一行）")
    ev = {"conditions": [{"day": _label_day(d),
                          **{k: d[k] for k in ("limit_up", "amount_max20", "high_max20")
                             if k in d}} for d in days]}
    if ranges:
        ev["ranges"] = [{"label": (rg.get("label")
                                   or f"{_label_range_end(rg.get('from'))}"
                                      f"~{_label_range_end(rg.get('to'))}"),
                         "per_day_all": True,
                         **{k: v for k, v in (rg.get("conds") or {}).items()
                            if k in ("limit_up", "amount_max20", "high_max20")}}
                        for rg in ranges]
    cur = store.load_result(stem, "current")
    if not cur or not (cur.get("rows")):
        paras.append("该模型暂无已存结果，无法核验。")
        return {"answer": paras, "evidence": ev}
    rows = cur["rows"]
    columns = list(cur.get("columns") or [])
    key = (stem, (cur.get("meta") or {}).get("data_date"), len(rows))
    if key in _CONDCHECK_CACHE:
        viol = _CONDCHECK_CACHE[key]
    else:
        viol = executor.validate_rows(plan, rows, columns)
        _CONDCHECK_CACHE[key] = viol
    ev["n_rows_checked"] = len(rows)
    ev["violations"] = viol[:20]
    if not viol:
        paras.append(f"引擎已对全部 {len(rows)} 行已存结果**逐行复核：0 违例**——"
                     "每行都满足以上全部条件，不存在「满足条件却被漏掉」的行。")
    else:
        paras.append(f"引擎逐行复核发现 **{len(viol)} 项违例**（前 20 项见证据）——"
                     "结果与计划不一致，需排查，请勿使用该结果。")
    paras.append("口径：「成交额最大/股价最高」= 近 20 个交易日窗口内最大（rolling_max20）；"
                 "涨停 = 严格相等口径（收盘与最高都等于涨停价）。")
    return {"answer": paras, "evidence": ev}


def _answer_composition(universe, question, stats):
    """结果构成核查：某前缀/板块的股票在不在结果里、为什么。全部确定性取数。"""
    prefixes = _detect_prefixes(question)
    pool = dict(executor._collect_stock_files(universe))
    names = _names_map()
    rep = {"in_result": {}, "in_pool": {}}
    paras = []
    for p in prefixes:
        in_pool = sorted(c for c in pool if c.startswith(p))
        in_res = sorted(c for c in (stats["codes"] or []) if c.startswith(p))
        rep["in_pool"][p] = {"n": len(in_pool), "sample": in_pool[:10]}
        rep["in_result"][p] = {"n": len(in_res),
                               "sample": [f"{c}({names.get(c, '?')})" for c in in_res[:10]]}
        if in_res:
            paras.append(f"结果中**有** {p} 开头的股票：共 {len(in_res)} 只"
                         + ("（示例：" + "、".join(rep['in_result'][p]['sample']) + "）" if in_res else "") + "。")
        elif in_pool:
            paras.append(f"结果中**没有** {p} 开头的股票，但池内含 {len(in_pool)} 只该前缀股票"
                         " → 说明该部分从未满足规则条件（不是数据遗漏）；"
                         "可用「股票代码 日期」质询做逐股核查。")
        else:
            paras.append(f"结果中**没有** {p} 开头的股票——属预期而非遗漏："
                         f"本模型 universe={universe} 的池子不收该前缀（板块过滤），"
                         "从入口处即被排除。")
    # 10cm × 创业板：2026-09-23 kk 已裁定——10cm 池含 300/301，仅限 2020-08-24 前 10% 时代
    if universe == "10cm" and any(p in ("30", "300", "301") for p in prefixes):
        paras.append("补充：2026-09-23 口径裁定后，10cm 池已纳入创业板 300/301 的 **10% 时代**"
                     "（信号日 < 2020-08-24，含反向门）；2020-08-24 起创业板为 20% 制度，"
                     "该时段 300/301 仅进入 20cm 池。科创板 688 任何时代都不进 10cm。")
    rep["verdict"] = "【结果构成核查】"
    rep["answer"] = paras
    rep["question"] = question
    return rep


def answer_general(stem, plan, rule_text, universe, question):
    """非个股质询：意图路由 → 确定性回答。绝不编造，答不了的给能力清单。"""
    sp = (plan.get("strategy_plan") or {}) if isinstance(plan, dict) else {}
    stats = _result_stats(stem)
    rep = {"stem": stem, "universe": universe, "type": "general",
           "question": question or "(未输入问题 → 模型概览)",
           "rule_text": rule_text,
           "data_source": "通达信本地 vipdoc 日线（appdata/market/vipdoc）"}

    key = None
    q = question or ""
    if _detect_prefixes(q):
        key = "composition"
    elif _COND_TRIGGER.search(q):
        key = "condcheck"
    else:
        for pat, k in _INTENTS:
            if re.search(pat, q):
                key = k
                break
    if not q.strip():
        key = "overview"

    paras, ev = [], {}
    if key == "composition":
        comp = _answer_composition(universe, q, stats or {"codes": [], "n_rows": 0})
        paras = comp["answer"]
        ev.update({"in_result": comp["in_result"], "in_pool": comp["in_pool"],
                   "n_result_rows": stats["n_rows"] if stats else 0})
    elif key == "condcheck":
        cc = _answer_condcheck(stem, plan, universe, q, stats)
        paras = cc["answer"]
        ev.update(cc["evidence"])
    elif key == "interval":
        paras = ["间隔 N = 两段涨停之间、**不含两端涨停 K 线**的交易日天数；相邻涨停 N=0；"
                 "跨间隔（中间夹锚点）= 各相邻间隔之和 + 中间锚点个数。",
                 "区间写法 N1∈[a,b] 表示中间 K 线根数落在 a..b（含端点），[0,n] 才含「连续涨停」。"]
        ev["doc_section"] = _doc_excerpt(r"九、间隔")
    elif key == "amplitude":
        paras = ["单日振幅 =（最高 − 最低）÷ 前收 × 100，**不带 %**（如 3.45）。",
                 "区间振幅（多日区间）带 %（如 3.45%）；区间最大振幅 = 逐日单日振幅取最大，不带 %。"]
        ev["doc_section"] = _doc_excerpt(r"七、振幅与涨幅")
        ev["formula_fn"] = "backtest_common.daily_amplitude"
    elif key == "limit":
        paras = ["涨停判定为**严格相等口径**：收盘价与最高价都必须等于涨停价"
                 "（涨停价 = 前收 × (1 + 幅度)，四舍五入到分），即「封死」。",
                 "幅度分段：主板 10%；创业板 2020-08-24 前 10%、之后 20%；科创板 20%（不早于 2019-07-22）。",
                 "上市初期无涨跌幅限制的日子（如注册制新股前 5 日）不可能满足严格相等，自动剔除。"]
        ev["doc_section"] = _doc_excerpt(r"五、动态涨跌停判定")
        ev["impl"] = "executor.compute_limit_flags / backtest_common.is_strong_limit_up"
    elif key == "change":
        paras = ["**单日涨幅** =（当日收盘 − 前收）÷ 前收 × 100，带正负号、不带 %（如 +2.50 / -1.30）。",
                 "**区间涨幅**（多日区间，如 D-2~D-0）=（区间末收盘 − 区间首收盘）÷ 区间首收盘 × 100，**带 %**（如 3.45%）。",
                 "**T+0/T+n 走势列**：以信号日收盘为基准的百分比变化；T+0 负数直接取整、正数向上取整；"
                 "T+1~T+7 统一向下取整（即「变大/变小」规则）。"]
        ev["doc_section"] = _doc_excerpt(r"七、振幅与涨幅")
        ev["impl"] = "backtest_common.fmt_plus / fmt_t0 / fmt_tn"
    elif key == "walk":
        paras = ["前向走势窗口：T+0..T+7 对应规则文本的 D+1..D+8，**T+0 = 信号日的后一交易日**。",
                 "每格为相对信号日收盘的百分比变化（取整规则见「涨幅」条目）。"]
        ev["doc_section"] = _doc_excerpt(r"六、T\+n 基准价")
    elif key == "amount":
        paras = ["成交额单位为**元**，来源通达信 .day 文件 amount 字段（f32）；"
                 "与 skill 侧口径一致（向下取整对齐 f32 ulp）。",
                 "「成交额最大」条件 = 当日成交额为近 20 个交易日最大（rolling_max20）。"]
    elif key == "universe":
        n_pool = len(dict(executor._collect_stock_files(universe)))
        paras = [f"本模型 universe={universe}，池内共 {n_pool} 只股票。",
                 "10cm = 沪深主板（60/00 开头）+ 创业板 300/301 的 10% 时代（信号日 < 2020-08-24，2026-09-23 裁定）；"
                 "20cm = 创业板 300/301 + 科创板 688；both = 各板块全时代并集（无门槛）。"]
        ev["n_pool"] = n_pool
    elif key == "stats" and stats:
        paras = [f"当前已存结果共 {stats['n_rows']} 行、{stats['n_stocks']} 只股票；"
                 f"命中日期范围 {stats['date_min']} ~ {stats['date_max']}。",
                 f"最近命中日期：{'、'.join(stats['recent_dates']) or '—'}。"]
        ev.update({k: stats[k] for k in ("n_rows", "n_stocks", "date_min", "date_max")})
    elif key == "overview" or key is None and not q:
        paras = ["模型规则原文见下方证据；当前已存结果情况见统计。"]
        key = "overview"
    else:
        key = key or "unknown"

    if key == "overview":
        if stats:
            paras = paras or []
            paras.append(f"当前已存结果：{stats['n_rows']} 行 / {stats['n_stocks']} 只股票，"
                         f"日期 {stats['date_min']} ~ {stats['date_max']}；输出 {len(stats['columns'])} 列。")
        if not paras:
            paras = ["该模型暂无已存结果。"]
        ev["rule_text"] = rule_text
        ev["strategy_plan_keys"] = sorted(sp.keys())

    if key in ("change", "amplitude", "walk") and stats:
        cols = [c for c in stats["columns"]
                if ("幅" in c or "涨" in c or "走势" in c or c.startswith("T+"))]
        if cols:
            paras.append(f"本模型输出中的相关列：{'、'.join(cols)}。")

    if key == "unknown":
        rep["verdict"] = "未能归类该问题（确定性回答不做猜测）。当前可答的问题类型："
        paras = ["① 个股质询：输入「股票代码 日期」，如 688037 20200117（可写中文名）；",
                 "② 口径类：区间涨幅/振幅怎么算、涨停怎么判定、间隔 N 怎么定义、T+0 走势窗口；",
                 "③ 模型类：这个模型是什么规则、池子范围、命中统计（留空即模型概览）；",
                 "④ 构成类：结果里有没有 XX 开头/创业板/科创板的股票。"]
    else:
        titles = {"interval": "间隔定义", "amplitude": "振幅口径", "limit": "涨停判定口径",
                  "change": "涨幅/区间涨幅口径", "walk": "前向走势窗口", "amount": "成交额口径",
                  "universe": "模型股票池", "stats": "命中统计", "overview": "模型概览",
                  "composition": "结果构成核查", "condcheck": "结果条件核验"}
        rep["verdict"] = f"【{titles.get(key, key)}】"
    rep["answer"] = paras
    rep["evidence"] = ev
    return rep
