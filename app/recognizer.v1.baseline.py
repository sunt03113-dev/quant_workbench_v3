# -*- coding: utf-8 -*-
"""冻结自然语言规则 → Strategy Plan 识别器。

只翻译冻结词汇表到 Skill 已实现业务原子，不定义任何新公式：
  涨停/非涨停            -> Skill compute_limit_flags / is_strong_limit_up
  成交额(为/非)20日最大   -> Skill rolling_max20 + 相等比较（含并列，窗口含自身）
  (最高)价(为/非)20日最高 -> 同上
  K线为阳/阴             -> Skill candle_form 口径（收>开为阳；板优先）
  振幅/涨幅/区间/成交额百分比/T走势 -> Skill 对应输出原子

识别不出 -> fail-closed（MISSING_BUSINESS_ATOM），绝不猜测。
"""
import re

_NEG = r"(?:非|不是|并非)"
_RE_DAY = re.compile(
    r"(基准日(?:\(D-?0\))?|D-0|D0|基准日T|前\s*(\d+)\s*日(?:\(D-(\d+)\))?|D-(\d+)|D\+(\d+)|当日)"
)
_RE_LIMIT_UP = re.compile(r"涨停")
_RE_LIMIT_UP_NEG = re.compile(_NEG + r"(?:是)?涨停")
_RE_AMT = re.compile(r"成交额")
_RE_AMT_MAX = re.compile(r"成交额(?:为)?(?:近)?20日最大|成交额最大")
_RE_AMT_NOT = re.compile(_NEG + r"(?:为)?(?:是)?(?:近)?(?:20日)?最大")
_RE_HIGH_MAX = re.compile(r"(?:最高价|股价)(?:为)?(?:近)?20日最高|(?:最高价|股价)最高")
_RE_HIGH_NOT = re.compile(r"(?:最高价|股价)" + _NEG + r"(?:为)?(?:是)?(?:近)?(?:20日)?最高")
_RE_HIGH = re.compile(r"最高价|股价")
_RE_CANDLE = re.compile(r"K线为(阳|阴)")
_RE_UNIVERSE = re.compile(r"【?\s*(20|10)\s*cm\s*】?", re.IGNORECASE)

_RE_OUT_KEY = re.compile(r"^(D-?\d+|T\+\d+\s*/\s*T\+\d+|D-?\d+\s*/\s*D-?\d+)\s*[：:]\s*(.*)$")
_RE_OUT_DAY = re.compile(r"^D-?(\d+)$")
_RE_OUT_RANGE = re.compile(r"^D-?(\d+)\s*/\s*D-?(\d+)$")
_RE_OUT_T = re.compile(r"^T\+(\d+)\s*/\s*T\+(\d+)$")

NOT_SUPPORTED_HINT = (
    "当前版本支持「以 D-0 为基准日、向前回看若干交易日」的日条件规则"
    "（如：D-0 涨停；D-1 非涨停…），暂不支持带前向窗口/间隔窗口的表达。"
)


def _norm(s):
    return re.sub(r"\s+", "", s)


def _day_offset(tok, m):
    t = _norm(tok).lower()
    if t.startswith("基准日") or t in ("d-0", "d0", "当日"):
        return 0
    if t.startswith("前") or t.startswith("d-"):
        digits = m and (m.group(2) or m.group(3) or m.group(4))
        if digits is None:
            digits = re.search(r"\d+", t).group()
        return -int(digits)
    if t.startswith("d+"):
        return int(m.group(5))
    return None


def _parse_conditions(clause):
    """解析单日条件子句 -> dict 或 None（词汇表外 -> fail-closed）。"""
    c = _norm(clause)
    cond = {}
    if _RE_LIMIT_UP_NEG.search(c):
        cond["limit_up"] = False
    elif _RE_LIMIT_UP.search(c):
        cond["limit_up"] = True
    if _RE_AMT.search(c):
        if _RE_AMT_NOT.search(c):
            cond["amount_max20"] = False
        elif _RE_AMT_MAX.search(c):
            cond["amount_max20"] = True
        else:
            return None
    if _RE_HIGH_MAX.search(c):
        cond["high_max20"] = True
    elif _RE_HIGH_NOT.search(c):
        cond["high_max20"] = False
    elif _RE_HIGH.search(c):
        return None
    mc = _RE_CANDLE.search(c)
    if mc:
        cond["candle"] = mc.group(1)
    return cond if cond else None


def _split_clauses(text):
    """条件段：按 ；;\n。 切分（同日多条件用逗号连接，不能在逗号处切断）。"""
    text = text.replace("【筛选条件】", "\n")
    text = re.sub(r"^\s*\d+[\.、]\s*", "", text, flags=re.M)
    parts = re.split(r"[；;\n。]+", text)
    return [p.strip() for p in parts if p.strip()]


def _strip_annotations(text):
    """剔除编辑批注（形如【【...的括注），非业务内容。按行截断，不影响正常【】标记。"""
    lines = []
    for ln in text.splitlines():
        p = ln.find("【【")
        lines.append(ln[:p] if p >= 0 else ln)
    return "\n".join(lines)


def _parse_outputs(out_text):
    """解析输出段 -> outputs 列表；返回 [] 表示存在无法映射的输出（fail-closed）。"""
    out_text = _strip_annotations(out_text)
    outputs = []
    cur = None  # (kind, params) 当前输出键上下文
    for clause in _split_clauses(out_text.replace("【输出指标】", "\n")):
        cn = _norm(clause)
        mk = _RE_OUT_KEY.match(clause)
        if mk:
            key = _norm(mk.group(1))
            rest_items = [s for s in re.split(r"[；;，,]", mk.group(2)) if s.strip()] if mk.group(2) else []
        else:
            if cur is None:
                continue  # 标题/说明行
            key, rest_items = None, [clause]
        items = rest_items if rest_items else [""]
        for it in items:
            itn = _norm(it)
            if key is not None:
                mr = _RE_OUT_RANGE.match(key)
                mt = _RE_OUT_T.match(key)
                md = _RE_OUT_DAY.match(key)
                if mr:
                    a, b = -int(mr.group(1)), -int(mr.group(2))
                    cur = ("range", (a, b))
                elif mt:
                    cur = ("t", (0, int(mt.group(2))))
                elif md:
                    cur = ("day", -int(md.group(1)))
                else:
                    cur = None
                    continue
            kind, params = cur
            if kind == "range":
                a, b = params
                if "区间涨幅" in itn:
                    outputs.append({"atom": "range_change", "days": [a, b]})
                elif "区间最大振幅" in itn:
                    outputs.append({"atom": "range_max_amplitude", "days": [a, b]})
                elif "区间振幅" in itn:
                    outputs.append({"atom": "range_amplitude", "days": [a, b]})
                elif "成交额百分比" in itn:
                    outputs.append({"atom": "amount_pct", "days": [a, b]})
                else:
                    return []
            elif kind == "t":
                if "走势" in itn:
                    outputs.append({"atom": "t_walk", "t0": 0, "t1": params[1]})
                else:
                    return []
            else:
                d = params
                if "日期" in itn:
                    outputs.append({"atom": "date", "day": d})
                elif "成交额百分比" in itn:
                    outputs.append({"atom": "amount_pct", "days": [d, d - 1]})
                elif "区间涨幅" in itn:
                    outputs.append({"atom": "range_change", "days": [d, d + 1]})
                elif "区间振幅" in itn:
                    outputs.append({"atom": "range_amplitude", "days": [d, d + 1]})
                elif "振幅" in itn:
                    outputs.append({"atom": "amplitude", "day": d})
                elif "涨幅" in itn:
                    outputs.append({"atom": "change", "day": d})
                elif "最低价" in itn:
                    outputs.append({"atom": "rel_low", "day": d})
                elif "最高价" in itn:
                    outputs.append({"atom": "rel_high", "day": d})
                else:
                    return []
    if not outputs:
        outputs = [{"atom": "date", "day": 0}, {"atom": "t_walk", "t0": 0, "t1": 6}]
    return outputs


def parse_single_rule(text, universe_hint=None):
    """解析单条规则文本 -> (plan, plan_summary, problems)。problems 非空 = fail-closed。"""
    sections = text.split("【输出指标】")
    cond_text = _strip_annotations(sections[0])
    out_text = sections[1] if len(sections) > 1 else ""

    problems = []
    days = {}
    for clause in _split_clauses(cond_text):
        m = _RE_DAY.search(clause)
        if not m:
            if _RE_UNIVERSE.search(clause) or len(_norm(clause)) <= 6:
                continue
            problems.append({"fragment": clause[:60], "reason": "未找到交易日锚点"})
            continue
        off = _day_offset(m.group(1), m)
        if off is None:
            problems.append({"fragment": clause[:60], "reason": "交易日锚点无法解析"})
            continue
        if off > 0:
            problems.append({"fragment": clause[:60], "reason": NOT_SUPPORTED_HINT})
            continue
        rest = clause[m.end():]
        if not _norm(rest):
            continue  # 纯锚点行
        cond = _parse_conditions(rest)
        if cond is None:
            problems.append({"fragment": clause[:60], "reason": "存在暂不支持的条件表述"})
            continue
        if off in days:
            for k, v in cond.items():
                days[off].setdefault(k, v)
        else:
            days[off] = cond

    if 0 not in days:
        problems.append({"fragment": "（全局）", "reason": "未找到基准日 D-0 的条件"})

    mu = _RE_UNIVERSE.search(text)
    universe = (mu.group(1) + "cm") if mu else (universe_hint or None)
    outputs = _parse_outputs(out_text)

    plan = {
        "schema_version": 1,
        "kind": "day_pattern_backward",
        "strategy_plan": {
            "universe": universe,
            "days": [{"offset": o, **days[o]} for o in sorted(days)],
            "outputs": outputs,
        },
    }
    return plan, _plan_summary(plan), problems


def _cond_text(c):
    parts = []
    if "limit_up" in c:
        parts.append("涨停" if c["limit_up"] else "非涨停")
    if c.get("amount_max20") is True:
        parts.append("成交额20日最大")
    elif c.get("amount_max20") is False:
        parts.append("成交额非20日最大")
    if c.get("high_max20") is True:
        parts.append("最高价20日最高")
    elif c.get("high_max20") is False:
        parts.append("最高价非20日最高")
    if c.get("candle"):
        parts.append("K线为" + c["candle"])
    return parts


def _plan_summary(plan):
    sp = plan["strategy_plan"]
    events = []
    for d in sorted(sp["days"], key=lambda x: x["offset"]):
        off = d["offset"]
        eid = f"D-{abs(off)}" if off <= 0 else f"D+{off}"
        conds = _cond_text(d)
        if conds:
            events.append({"id": eid, "conditions": conds, "is_condition_event": True})
    outs = [o["atom"] for o in sp["outputs"]]
    return {"universe": sp.get("universe") or "未指明", "events": events, "outputs": outs}


def plan_to_base_rules(plan):
    """plan -> UI rulesToNL 兼容的 base_rules（key 形如 d_0 / d_1）。"""
    br = {}
    for d in plan["strategy_plan"]["days"]:
        off = d["offset"]
        c = {}
        if "limit_up" in d:
            c["limit_up"] = d["limit_up"]
        if d.get("amount_max20") is True:
            c["amount_max20"] = True
        elif d.get("amount_max20") is False:
            c["amount_not_max20"] = True
        if d.get("high_max20") is True:
            c["high_max20"] = True
        elif d.get("high_max20") is False:
            c["high_not_max20"] = True
        br[f"d_{abs(off)}"] = c
    return br


UNIVERSE_AMBIGUITY_ID = "universe_scope"


def recognize(natural_text, universe=None):
    """主入口：返回 /api/plan/recognize 响应结构（单条规则）。"""
    plan, summary, problems = parse_single_rule(natural_text, universe_hint=universe)
    if problems:
        return {
            "status": "FAILED",
            "n_rules": 1,
            "failure": {
                "code": "MISSING_BUSINESS_ATOM",
                "title": "存在暂不支持的表达",
                "message": "以下片段无法映射到已实现的业务能力，请修改表述：",
                "hint": NOT_SUPPORTED_HINT,
                "source_fragment": problems[0]["fragment"],
                "detail": {"problems": problems},
            },
        }
    if plan["strategy_plan"]["universe"] is None:
        plan_t = {**plan, "strategy_plan": {**plan["strategy_plan"], "universe": "both"}}
        return {
            "status": "NEED_CONFIRMATION",
            "n_rules": 1,
            "plan_draft": plan_t,
            "ambiguity_report": {
                "items": [{
                    "id": UNIVERSE_AMBIGUITY_ID,
                    "description": "规则未指明适用的涨跌幅板块范围",
                    "location": {"snippet": ""},
                    "candidates": [
                        {"id": "20cm", "label": "20cm（创业板/科创板）",
                         "business_meaning": "仅在 688/300/301 标的中回测",
                         "result_impact": "涨停价按 20% 计算"},
                        {"id": "10cm", "label": "10cm（沪/深主板）",
                         "business_meaning": "仅在沪深主板标的中回测",
                         "result_impact": "涨停价按 10% 计算"},
                        {"id": "both", "label": "全部A股",
                         "business_meaning": "主板与 20cm 板块一起回测",
                         "result_impact": "按各自板块口径计算"},
                    ],
                    "default_candidate_id": "20cm",
                }],
            },
        }
    return {"status": "READY", "n_rules": 1, "plan": plan,
            "review": {"coverage": [{"item": e["id"], "status": "covered"} for e in summary["events"]],
                       "possible_misinterpretations": []},
            "plan_summary": summary}


def resolve_ambiguity(plan, rule_text, choices, universe_hint=None):
    """应用澄清选择后重新识别（一次性，不反复追问）。"""
    universe = universe_hint or None
    for ch in choices or []:
        if ch.get("item_id") == UNIVERSE_AMBIGUITY_ID:
            cand = ch.get("candidate_id")
            if cand in ("10cm", "20cm", "both") and cand != "__custom__":
                universe = cand
    return recognize(rule_text, universe=universe)


def split_multi_rules(text):
    """按【筛选条件】分块；>=2 块时返回 [(rule_name, rule_text), ...]。"""
    if text.count("【筛选条件】") < 2:
        return []
    parts = re.split(r"\n(?=[^\n]*【筛选条件】)", text)
    rules = []
    for blk in parts:
        blk = blk.strip()
        if "【筛选条件】" not in blk:
            continue
        first_line = blk.splitlines()[0].strip()
        name = re.sub(r"[\s【】]", "", first_line) or None
        rules.append((name, blk))
    return rules if len(rules) >= 2 else []
