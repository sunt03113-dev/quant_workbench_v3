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

_NEG = r"(?:并非|不是|非|不)"
_RE_DAY = re.compile(
    r"(基准日(?:\(D-?0\))?|D-0|D0|基准日T|前\s*(\d+)\s*日(?:\(D-(\d+)\))?|D-(\d+)|D\+(\d+)|当日"
    r"|D-\(?\s*x(?:\s*([+\-])\s*(\d+))?\s*\)?)"   # 变量日：D-x / D-x+k / D-(x+k) / D-(x-k)
)
_RE_QUANT = re.compile(r"^(\d+)(?:≤|<=)x(?:≤|<=)(\d+)$")
_RE_LIMIT_UP = re.compile(r"涨停")
_RE_LIMIT_UP_NEG = re.compile(_NEG + r"(?:是)?涨停")
_RE_AMT = re.compile(r"成交额")
_RE_AMT_MAX = re.compile(r"成交额(?:为)?(?:近)?20日最大|成交额最大|成交额(?:为)?最高")
_RE_AMT_NOT = re.compile(_NEG + r"(?:为)?(?:是)?(?:近)?(?:20日)?(?:最大|最高)")
_RE_HIGH_MAX = re.compile(r"(?:最高价|股价)(?:为)?(?:近)?20日最高|(?:最高价|股价)最高")
_RE_HIGH_NOT = re.compile(r"(?:最高价|股价)" + _NEG + r"(?:为)?(?:是)?(?:近)?(?:20日)?最高")
_RE_HIGH = re.compile(r"最高价|股价")
# 作用域内（关键词之后的文本）的肯定/否定判定：无关键词前缀
_RE_AMT_MAX_SCOPE = re.compile(r"(?:为)?(?:是)?(?:近)?20日最大|最大")
_RE_AMT_NOT_SCOPE = re.compile(_NEG + r"(?:为)?(?:是)?(?:近)?(?:20日)?(?:最大|最高)")
_RE_HIGH_MAX_SCOPE = re.compile(r"(?:为)?(?:是)?(?:近)?20日最高|最高")
_RE_HIGH_NOT_SCOPE = re.compile(_NEG + r"(?:为)?(?:是)?(?:近)?(?:20日)?最高")
_RE_CANDLE = re.compile(r"K线为(阳|阴)")
_RE_UNIVERSE = re.compile(r"【?\s*(20|10)\s*cm\s*】?", re.IGNORECASE)

_RE_OUT_KEY = re.compile(
    r"^(D-?\d+|T\+\d+\s*/\s*T\+\d+|D-?\d+\s*/\s*D-?\d+"
    r"|Dx(?:\s*-\s*\d+)?"
    r"|D-\(\s*x(?:\s*[+\-]\s*\d+)?\s*\)"
    r"|D-x(?:\s*[+\-]\s*\d+)?[\s/～~]*D[+\-]\d+"
    r"|D\+\d+\s*[/~]\s*D\+\d+"
    r"|x)\s*[：:]\s*(.*)$"
)
_RE_OUT_DAY = re.compile(r"^D-?(\d+)$")
_RE_OUT_RANGE = re.compile(r"^D-?(\d+)\s*[/~～]\s*D-?(\d+)$")
_RE_OUT_T = re.compile(r"^T\+(\d+)\s*/\s*T\+(\d+)$")
# 组合规则（变量日）输出键：
#   Dx-2  -> D-(x+2)（kk 确认：减号表示比 D-x 更远 k 天）
#   Dx    -> D-x
#   D-x D+1 / D-x/D+1 -> 区间 [D-x, D+1]
#   D+1/D+8 -> 前向 T 走势（T+0..T+7 对应 D+1..D+8）
_RE_OUT_VAR = re.compile(r"^Dx(?:\s*-\s*(\d+))?$")
# 变量区间：D-x D+1 / D-x~D-1（末端可为前向 D+b 或历史 D-b）
_RE_OUT_VAR_RANGE = re.compile(r"^D-x(?:\s*([+\-])\s*(\d+))?[\s/～~]*D([+\-])(\d+)$")
# 括号变量日键：D-(x+2) / D-(x-1) / D-(x)
_RE_OUT_VAR_PAREN = re.compile(r"^D-\(\s*x(?:\s*([+\-])\s*(\d+))?\s*\)$")
_RE_OUT_FWD_T = re.compile(r"^D\+(\d+)\s*[/~]\s*D\+(\d+)$")
_RE_OUT_X = re.compile(r"^x$")

NOT_SUPPORTED_HINT = (
    "当前版本支持「以 D-0 为基准日、向前回看若干交易日」的日条件规则"
    "（如：D-0 涨停；D-1 非涨停…），暂不支持带前向窗口/间隔窗口的表达。"
)


def _norm(s):
    return re.sub(r"\s+", "", s)


def _day_offset(tok, m):
    t = _norm(tok).lower()
    if t.startswith(("d-x", "d-(")):             # 变量日（读法1 kk 已确认）
        # D-x     -> 深度 x
        # D-x+k / D-(x+k) -> D-(x+k)，比 D-x 更远 k 天
        # 注意：D-(x+2) 这类括号记号必须走此分支；
        # 否则下方 d- 兜底会抓括号里的第一个数字，把变量日错解成固定日 D-k！
        k = 0
        if m and m.group(6):
            k = int(m.group(7)) * (1 if m.group(6) == "+" else -1)
        return ("var", k)
    if t.startswith("基准日") or t in ("d-0", "d0", "当日"):
        return 0
    if t.startswith("前") or t.startswith("d-"):
        digits = m and (m.group(2) or m.group(3) or m.group(4))
        if digits is None:
            # 兜底仅允许「token 本身含数字」的情形；变量日 token（d-(x+2)）
            # 已在上方分支消费，不会落到这里。
            fm = re.search(r"\d+", t)
            if fm is None:
                return None
            digits = fm.group()
        return -int(digits)
    if t.startswith("d+"):
        return int(m.group(5))
    return None


_RE_ATOM_KW = re.compile(r"成交额|最高价|股价|K线为")


def _atom_scope(c, kws):
    """截取指定原子关键词之后、下一原子关键词之前的文本（作用域内做否定/肯定判定）。"""
    hits = [(m.start(), m.end(), m.group()) for m in _RE_ATOM_KW.finditer(c)]
    for idx, (s, e, g) in enumerate(hits):
        if g in kws:
            nxt = hits[idx + 1][0] if idx + 1 < len(hits) else len(c)
            return c[e:nxt]
    return None


def _parse_conditions(clause):
    """解析单日条件子句 -> dict 或 None（词汇表外 -> fail-closed）。

    每个原子只在自身关键词的作用域内做否定/肯定判定，避免跨原子污染
    （如「成交额为近20日最大且最高价非近20日最高」「成交额最大, 股价不是最高」）。
    """
    c = _norm(clause)
    cond = {}
    if _RE_LIMIT_UP_NEG.search(c):
        cond["limit_up"] = False
    elif _RE_LIMIT_UP.search(c):
        cond["limit_up"] = True
    amt_scope = _atom_scope(c, ("成交额",))
    if amt_scope is not None:
        if _RE_AMT_NOT_SCOPE.search(amt_scope):
            cond["amount_max20"] = False
        elif _RE_AMT_MAX_SCOPE.search(amt_scope):
            cond["amount_max20"] = True
        else:
            return None
    high_scope = _atom_scope(c, ("股价", "最高价"))
    if high_scope is not None:
        if _RE_HIGH_NOT_SCOPE.search(high_scope):
            cond["high_max20"] = False
        elif _RE_HIGH_MAX_SCOPE.search(high_scope):
            cond["high_max20"] = True
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


# 说明性/记号约定行（如「符号约定：D-n代表D-0往前回溯n个交易日…」）不是业务条件。
# 跳过条件从严（fail-closed 不放松）：必须以约定类前缀开头，且整行不含任何业务关键词；
# 带业务关键词的「注：…」行仍按条件解析，绝不静默吞掉。
_RE_NOTATION_LINE = re.compile(r"^\s*(?:符号约定|记号约定|记号说明|约定|说明|备注|注)\s*[：:]")
_RE_BUSINESS_KW = re.compile(r"涨停|跌停|成交额|最高|最低|振幅|涨幅|K线|走势|区间|开盘|收盘|首板|间隔")
# D 记法下写了变量间隔（如「D-y与D-x间隔交易日天数N1∈[1,5]」）：
# 变量间隔只在 T_ 链记法实现，给出可执行的改写指引而不是泛泛的"不支持"。
_CHAIN_REWRITE_HINT = (
    "变量间隔窗口仅支持 T_ 链记法：把三个交易日改写为锚点 T_0（最早）、T_1、T_2（信号日），"
    "间隔写成「T_0-T_1间隔N1∈[1,5]，T_1-T_2间隔N2∈[1,5]」，"
    "区间无涨停写成「T_0与T_1间无涨停」，仅三日涨停写成「仅T_0、T_1、T_2三日涨停」，"
    "锚点前视无涨停写成「T_0前5日无涨停」。"
)


def _drop_notation_lines(text):
    lines = [ln for ln in text.splitlines()
             if not (_RE_NOTATION_LINE.search(ln) and not _RE_BUSINESS_KW.search(ln))]
    return "\n".join(lines)


def _cond_problem_reason(clause, default):
    """条件子句失败时的 reason；变量间隔写法给出 T_ 链改写指引。"""
    c = _norm(clause)
    if "间隔" in c and re.search(r"N\d", c) and not _RE_CHAIN_TRIGGER.search(c):
        return _CHAIN_REWRITE_HINT
    return default


def _parse_outputs(out_text):
    """解析输出段 -> (outputs, err_fragment)。

    err_fragment 非空 = 存在无法映射的输出（fail-closed，由调用方转为 problems）。
    """
    out_text = _strip_annotations(out_text)
    # 波浪号写法归一：全角 ～ → 半角 ~；「~」与「/」均为合法区间分隔符
    # （2026-09-21 kk 口径：分隔符保留原样进入列名，不再统一改写为 /）
    out_text = out_text.replace("～", "~")
    outputs = []
    err = None
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
                mx = _RE_OUT_X.match(key)
                mft = _RE_OUT_FWD_T.match(key)
                mp = _RE_OUT_VAR_PAREN.match(key)
                mvr = _RE_OUT_VAR_RANGE.match(key)
                mv = _RE_OUT_VAR.match(key)
                mr = _RE_OUT_RANGE.match(key)
                mt = _RE_OUT_T.match(key)
                md = _RE_OUT_DAY.match(key)
                if mx:
                    cur = ("xval", None)
                elif mft:
                    a, b = int(mft.group(1)), int(mft.group(2))
                    if a != 1 or b <= a:
                        err = clause
                        break
                    cur = ("fwdt", (a, b))
                elif mp:
                    # D-(x+k)：括号内符号即字面方向（+k 更远，-k 更近）
                    k = int(mp.group(2)) * (1 if mp.group(1) == "+" else -1) \
                        if mp.group(1) else 0
                    cur = ("var", k)
                elif mvr:
                    # D-x+k / D-x-k（读法1：+k 比 D-x 更远）；末端 D+b 或 D-b
                    k = int(mvr.group(2)) * (1 if (mvr.group(1) or "+") == "+" else -1) \
                        if mvr.group(1) else 0
                    end = int(mvr.group(4)) * (1 if mvr.group(3) == "+" else -1)
                    sep = "~" if ("~" in key or "～" in key) else "/"
                    cur = ("varrange", (k, end, sep))
                elif mv:
                    # kk 确认：Dx-2 = D-(x+2)，减号 = 比 D-x 更远 k 天
                    cur = ("var", int(mv.group(1)) if mv.group(1) else 0)
                elif mr:
                    a, b = -int(mr.group(1)), -int(mr.group(2))
                    # 分隔符语义归一：「/」与「~」均表示区间（用户口径），
                    # 列名保留用户书写习惯
                    sep = "~" if ("~" in key or "～" in key) else "/"
                    cur = ("range", (a, b, sep))
                elif mt:
                    cur = ("t", (0, int(mt.group(2))))
                elif md:
                    cur = ("day", -int(md.group(1)))
                else:
                    cur = None
                    continue
            kind, params = cur
            if kind == "xval":
                if "数值" in itn:
                    outputs.append({"atom": "x_value"})
                else:
                    err = clause
                    break
            elif kind == "fwdt":
                if "走势" in itn:
                    # D+1~D+8 价格走势：T+0..T+7 对应 D+1..D+8，输出列用 D+ 记号
                    outputs.append({"atom": "t_walk", "t0": 0, "t1": params[1] - 1,
                                    "day_base": params[0]})
                else:
                    err = clause
                    break
            elif kind == "varrange":
                k, b, sep = params
                if "区间涨幅" in itn:
                    outputs.append({"atom": "range_change", "days": [{"var": k}, b], "sep": sep})
                elif "区间最大振幅" in itn:
                    outputs.append({"atom": "range_max_amplitude", "days": [{"var": k}, b], "sep": sep})
                elif "区间振幅" in itn:
                    outputs.append({"atom": "range_amplitude", "days": [{"var": k}, b], "sep": sep})
                elif "成交额百分比" in itn:
                    outputs.append({"atom": "amount_pct", "days": [{"var": k}, b], "sep": sep})
                else:
                    err = clause
                    break
            elif kind == "var":
                k = params
                if "日期" in itn:
                    outputs.append({"atom": "date", "day_var": k})
                elif "振幅" in itn:
                    outputs.append({"atom": "amplitude", "day_var": k})
                elif "涨幅" in itn:
                    outputs.append({"atom": "change", "day_var": k})
                elif "最低价" in itn:
                    outputs.append({"atom": "rel_low", "day_var": k})
                elif "最高价" in itn:
                    outputs.append({"atom": "rel_high", "day_var": k})
                else:
                    err = clause
                    break
            elif kind == "range":
                a, b, sep = params
                if "区间涨幅" in itn:
                    outputs.append({"atom": "range_change", "days": [a, b], "sep": sep})
                elif "区间最大振幅" in itn:
                    outputs.append({"atom": "range_max_amplitude", "days": [a, b], "sep": sep})
                elif "区间振幅" in itn:
                    outputs.append({"atom": "range_amplitude", "days": [a, b], "sep": sep})
                elif "成交额百分比" in itn:
                    outputs.append({"atom": "amount_pct", "days": [a, b], "sep": sep})
                else:
                    err = clause
                    break
            elif kind == "t":
                if "走势" in itn:
                    outputs.append({"atom": "t_walk", "t0": 0, "t1": params[1]})
                else:
                    err = clause
                    break
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
                    err = clause
                    break
        if err is not None:
            break
    if not outputs and err is None:
        outputs = [{"atom": "date", "day": 0}, {"atom": "t_walk", "t0": 0, "t1": 6}]
    return outputs, err


# ===================== 间隔链规则（T_0→T_1→T_2，间隔 N1/N2 自由组合） =====================
# 111A3 类形态：锚点日 T_0..T_m 依次相邻排布，相邻锚点间隔 N_i 为变量（存在量词），
# 每个满足的 (N1..Nm) 组合各出一行（kk 口径，2026-09-21 确认：间隔N=相差N个交易日）。

_RE_CHAIN_TRIGGER = re.compile(r"T[-_]?0")   # T0 / T_0 / T-0 均为链式锚点起点
_RE_CHAIN_GAP = re.compile(
    r"T_(\d+)\s*[-—～~至]{1,2}\s*T_(\d+)(?:间隔|隔)N(\d+)∈\[\s*(-?\d+)\s*,\s*(-?\d+)\s*\]")
_RE_CHAIN_PREV = re.compile(r"T_(\d+)前(\d+)日无涨停")
_RE_CHAIN_FIRST = re.compile(r"T_(\d+)首板")
_RE_CHAIN_AMT_GE = re.compile(
    r"T_(\d+)的?成交额不小于((?:T_\d+[、,和及]\s*)+?)的?成交额")
_RE_CHAIN_BOTH_MAX = re.compile(r"T_(\d+)的?成交额和股价均是?(?:近)?20日最高")
_RE_CHAIN_GAP_NOLIMIT = re.compile(r"T_(\d+)与T_(\d+)(?:间|之间)?无涨停")
_RE_CHAIN_ONLY = re.compile(r"仅((?:T_\d+[、,]?)+?)(?:三|\d+)日涨停")
_RE_CHAIN_OUT_GAPVAL = re.compile(r"(?:间隔的?交易?日?天数|间隔的?天数|间隔)N(\d+)|^N(\d+)$")


def _parse_chain_rule(text, cond_text, out_text, universe_hint):
    """解析间隔链规则 -> parse_single_rule 兼容的三元组。解析不了 -> fail-closed problems。"""
    problems = []
    # T 标记体系中「-」仅是标识符（kk 口径）：T-0 / T_0 / T0 等价，统一归一为 T_0。
    # 只归一 T-数字 / T_数字，不触碰 T+0（前向日记号）。
    _tnorm = lambda s: re.sub(r"[Tt][-_](\d+)", r"T_\1", s)
    text, cond_text, out_text = _tnorm(text), _tnorm(cond_text), _tnorm(out_text)
    mu = _RE_UNIVERSE.search(text)
    universe = (mu.group(1) + "cm") if mu else (universe_hint or None)

    # 1) 间隔声明（锚点拓扑由此确定）
    gaps = {}
    for m in _RE_CHAIN_GAP.finditer(_strip_annotations(text)):
        a, b, vi, lo, hi = m.groups()
        key = f"T_{a}->T_{b}"
        if key in gaps:
            problems.append({"fragment": m.group(0)[:60], "reason": "间隔声明重复"})
            continue
        gaps[key] = {"from": f"T_{a}", "to": f"T_{b}", "var": f"N{vi}",
                     "min": int(lo), "max": int(hi)}
    if not gaps:
        problems.append({"fragment": "（间隔声明）",
                         "reason": "未识别到间隔声明（形如 T_0-T_1间隔N1∈[1,3]）"})
    anchor_ids = sorted({g.split("->")[0] for g in gaps} | {g.split("->")[1] for g in gaps},
                        key=lambda s: int(s[2:]))
    # 拓扑校验：必须是一条链 T_0→T_1→...，间隔只能连接相邻锚点
    for idx in range(len(anchor_ids)):
        if anchor_ids[idx] != f"T_{idx}":
            problems.append({"fragment": ",".join(anchor_ids),
                             "reason": "锚点必须从 T_0 开始连续编号（T_0、T_1、T_2…）"})
            break
    if not problems:
        for g in gaps.values():
            a, b = int(g["from"][2:]), int(g["to"][2:])
            if b != a + 1:
                problems.append({"fragment": f"{g['from']}->{g['to']}",
                                 "reason": "间隔只能连接相邻锚点（如 T_1-T_2）"})
    if int(gaps.get("T_0->T_1", {}).get("var", "N0")[1:]) != 1:
        problems.append({"fragment": "N1", "reason": "首个间隔变量必须命名为 N1"})
    # 间隔变量必须连续编号 N1..Nk
    for idx, g in enumerate(sorted(gaps.values(), key=lambda g: int(g["from"][2:])), start=1):
        if g["var"] != f"N{idx}":
            problems.append({"fragment": g["var"],
                             "reason": f"间隔变量必须按顺序连续编号（期望 N{idx}）"})


    # 2) 锚点条件
    anchor_conds = {a: {} for a in anchor_ids}
    gap_conds = {}
    ctext = _drop_notation_lines(_strip_annotations(text))
    for m in _RE_CHAIN_ONLY.finditer(ctext):
        for a in re.findall(r"T_\d+", m.group(1)):
            if a in anchor_conds:
                anchor_conds[a]["limit_up"] = True
    for m in _RE_CHAIN_PREV.finditer(ctext):
        a = f"T_{m.group(1)}"
        if a in anchor_conds:
            anchor_conds[a]["prev_no_limit"] = int(m.group(2))
    if _RE_CHAIN_FIRST.search(ctext):
        if "T_0" in anchor_conds:
            anchor_conds["T_0"].setdefault("limit_up", True)
    for m in _RE_CHAIN_AMT_GE.finditer(ctext):
        a = f"T_{m.group(1)}"
        others = [f"T_{x}" for x in re.findall(r"T_(\d+)", m.group(2))]
        if a in anchor_conds and others:
            anchor_conds[a]["amount_ge"] = others
    for m in _RE_CHAIN_BOTH_MAX.finditer(ctext):
        a = f"T_{m.group(1)}"
        if a in anchor_conds:
            anchor_conds[a]["amount_max20"] = True
            anchor_conds[a]["high_max20"] = True
    # 「T_0与T_1间、T_1与T_2间无涨停」共享谓词 → 拆成两个完整子句再匹配
    ctext = re.sub(r"(间|之间)\s*[、,]\s*(?=T_\d+与T_\d+)", r"\1无涨停，", ctext)
    for m in _RE_CHAIN_GAP_NOLIMIT.finditer(ctext):
        key = f"T_{m.group(1)}->T_{m.group(2)}"
        if key in gaps:
            gap_conds[key] = {"limit_up": False}
    # 每个间隔都必须有「无涨停」约束吗？不强制；缺省 = 间隔日无约束
    for a in anchor_ids:
        if not anchor_conds[a]:
            problems.append({"fragment": a, "reason": f"{a} 缺少条件表述（fail-closed）"})

    # 3) 输出段（支持顿号/逗号连接的单行多指标，逐项匹配）
    outputs = []
    if out_text.strip():
        for clause in _split_clauses(out_text.replace("【输出指标】", "\n")):
            for item in re.split(r"[、，,]", clause):
                cn = _norm(item)
                if not cn:
                    continue
                mo = re.match(r"^T_(\d+)~T_(\d+)(区间涨幅|区间振幅|区间最大振幅)$", cn)
                md = re.match(r"^T_(\d+)的?(日期|振幅|涨幅)$", cn)
                mr = re.match(r"^T_(\d+)的?(最低价|最高价)$", cn)
                mv = _RE_CHAIN_OUT_GAPVAL.search(cn)
                if mo:
                    a, b = f"T_{mo.group(1)}", f"T_{mo.group(2)}"
                    if a not in anchor_conds or b not in anchor_conds:
                        problems.append({"fragment": item[:60], "reason": "区间端点必须是已声明的锚点"})
                        continue
                    kind = {"区间涨幅": "change", "区间振幅": "amplitude",
                            "区间最大振幅": "max_amplitude"}[mo.group(3)]
                    outputs.append({"atom": "chain_range", "kind": kind, "anchors": [a, b]})
                elif md:
                    a = f"T_{md.group(1)}"
                    if a not in anchor_conds:
                        problems.append({"fragment": item[:60], "reason": "锚点未在条件段声明"})
                        continue
                    outputs.append({"atom": "chain_" + {"日期": "date", "振幅": "amplitude",
                                                        "涨幅": "change"}[md.group(2)],
                                    "anchor": a})
                elif mr:
                    a = f"T_{mr.group(1)}"
                    if a not in anchor_conds:
                        problems.append({"fragment": item[:60], "reason": "锚点未在条件段声明"})
                        continue
                    outputs.append({"atom": "chain_" +
                                    {"最低价": "rel_low", "最高价": "rel_high"}[mr.group(2)],
                                    "anchor": a})
                elif mv:
                    var = f"N{mv.group(1) or mv.group(2)}"
                    if var not in {g["var"] for g in gaps.values()}:
                        problems.append({"fragment": item[:60], "reason": f"{var} 未在间隔声明中定义"})
                        continue
                    outputs.append({"atom": "chain_gap", "var": var})
                else:
                    problems.append({"fragment": item[:60],
                                     "reason": "存在暂不支持的输出指标表述（fail-closed，不猜测）"})
    if not outputs and not problems:
        problems.append({"fragment": "（输出指标）", "reason": "间隔链规则必须显式给出输出指标"})

    if problems:
        return {"schema_version": 1, "kind": "day_pattern_backward",
                "strategy_plan": {"universe": universe, "days": [], "outputs": []}}, \
               {"universe": universe or "未指明", "events": [], "outputs": []}, problems

    chain = {"anchors": anchor_ids, "gaps": [gaps[k] for k in sorted(gaps)],
             "anchor_conds": anchor_conds, "gap_conds": gap_conds}
    sp = {"universe": universe, "days": [], "outputs": outputs, "chain": chain}
    plan = {"schema_version": 1, "kind": "day_pattern_backward", "strategy_plan": sp}
    events = []
    for a in anchor_ids:
        conds = _cond_text(anchor_conds[a])
        if anchor_conds[a].get("prev_no_limit"):
            conds = [f"前{anchor_conds[a]['prev_no_limit']}日无涨停"] + conds
        if conds:
            events.append({"id": a, "conditions": conds, "is_condition_event": True})
    for g in chain["gaps"]:
        gc = gap_conds.get(f"{g['from']}->{g['to']}")
        events.append({"id": f"{g['from']}~{g['to']}",
                       "conditions": [f"间隔{g['var']}∈[{g['min']},{g['max']}]"
                                      + ("，期间无涨停" if gc else "")],
                       "is_condition_event": True})
    summary = {"universe": universe or "未指明", "events": events,
               "outputs": [o["atom"] for o in outputs]}
    return plan, summary, []


def parse_single_rule(text, universe_hint=None):
    """解析单条规则文本 -> (plan, plan_summary, problems)。problems 非空 = fail-closed。"""
    sections = text.split("【输出指标】")
    cond_text = _drop_notation_lines(_strip_annotations(sections[0]))
    out_text = sections[1] if len(sections) > 1 else ""

    # 间隔链规则（T_0/T_1/T_2 + N1/N2 组合）走专用解析器
    if _RE_CHAIN_TRIGGER.search(cond_text):
        return _parse_chain_rule(text, cond_text, out_text, universe_hint)

    problems = []
    days = {}
    var_days = []      # 符号日：{"offset_var": k, **cond}，深度 = x + k
    quantifier = None  # {"var": "x", "min": a, "max": b}
    for clause in _split_clauses(cond_text):
        mq = _RE_QUANT.match(_norm(clause))
        if mq:
            quantifier = {"var": "x", "min": int(mq.group(1)), "max": int(mq.group(2))}
            continue
        m = _RE_DAY.search(clause)
        if not m:
            if _RE_UNIVERSE.search(clause) or len(_norm(clause)) <= 6:
                continue
            problems.append({"fragment": clause[:60], "reason": "未找到交易日锚点"})
            continue
        off = _day_offset(m.group(1), m)
        if isinstance(off, tuple):
            # 变量日 D-x / D-x+k（深度 = x + k，读法1）
            rest = clause[m.end():]
            if not _norm(rest):
                problems.append({"fragment": clause[:60], "reason": "变量日缺少条件表述"})
                continue
            cond = _parse_conditions(rest)
            if cond is None:
                problems.append({"fragment": clause[:60],
                                 "reason": _cond_problem_reason(clause, "存在暂不支持的条件表述")})
            else:
                var_days.append({"offset_var": off[1], **cond})
            continue
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
            problems.append({"fragment": clause[:60],
                             "reason": _cond_problem_reason(clause, "存在暂不支持的条件表述")})
            continue
        if off in days:
            for k, v in cond.items():
                days[off].setdefault(k, v)
        else:
            days[off] = cond

    if 0 not in days:
        problems.append({"fragment": "（全局）", "reason": "未找到基准日 D-0 的条件"})
    if var_days and quantifier is None:
        problems.append({"fragment": "2≤x≤11", "reason": "规则使用了变量日 D-x，但缺少取值范围声明（如 2≤x≤11）"})

    mu = _RE_UNIVERSE.search(text)
    universe = (mu.group(1) + "cm") if mu else (universe_hint or None)
    outputs, out_err = _parse_outputs(out_text)
    if out_err is not None:
        problems.append({"fragment": out_err[:60],
                         "reason": "存在暂不支持的输出指标表述（fail-closed，不猜测）"})

    sp = {
        "universe": universe,
        "days": [{"offset": o, **days[o]} for o in sorted(days)]
                + sorted(var_days, key=lambda d: d["offset_var"]),
        "outputs": outputs,
    }
    if quantifier is not None:
        sp["quantifier"] = quantifier
        # 确定性复核依赖行内 x 数值；用户未显式输出时自动补列
        if not any(o.get("atom") == "x_value" for o in outputs):
            outputs.append({"atom": "x_value"})
    plan = {
        "schema_version": 1,
        "kind": "day_pattern_backward",
        "strategy_plan": sp,
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

    def _day_key(d):
        return d["offset"] if "offset" in d else -(10**6 + d["offset_var"])

    for d in sorted(sp["days"], key=_day_key):
        conds = _cond_text(d)
        if not conds:
            continue
        if "offset" in d:
            off = d["offset"]
            eid = f"D-{abs(off)}" if off <= 0 else f"D+{off}"
        else:
            k = d["offset_var"]
            eid = "D-x" if k == 0 else f"D-x+{k}"
        events.append({"id": eid, "conditions": conds, "is_condition_event": True})
    outs = [o["atom"] for o in sp["outputs"]]
    return {"universe": sp.get("universe") or "未指明", "events": events, "outputs": outs}


def plan_to_base_rules(plan):
    """plan -> UI rulesToNL 兼容的 base_rules（key 形如 d_0 / d_1 / t_0）。"""
    br = {}
    chain = plan["strategy_plan"].get("chain")
    if chain is not None:
        for a, c in chain["anchor_conds"].items():
            cc = {}
            if "limit_up" in c:
                cc["limit_up"] = c["limit_up"]
            if c.get("amount_max20") is True:
                cc["amount_max20"] = True
            if c.get("high_max20") is True:
                cc["high_max20"] = True
            if c.get("prev_no_limit"):
                cc["prev_no_limit"] = c["prev_no_limit"]
            if c.get("amount_ge"):
                cc["amount_ge"] = c["amount_ge"]
            br[a.replace("T_", "t_")] = cc
        return br
    for d in plan["strategy_plan"]["days"]:
        if "offset" in d:
            key = f"d_{abs(d['offset'])}"
        else:
            key = f"d_x{d['offset_var']}"
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
        br[key] = c
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
