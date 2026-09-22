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


# ===================== D 记法变量间隔链（D-x/D-y + 间隔N∈[a,b] 自动翻译） =====================
# 2026-09-22 kk 口径：D 记法下出现「多个变量日 + 变量间隔」时，自动翻译为内部间隔链计划，
# 不再要求用户手工改写 T 链。
#   - 变量日排布：按字母倒序（D-y 比 D-x 更早），与 10cm 原文「D-y~D-x区间」方向一致；
#     D-0 恒为末锚点（信号日）。
#   - 间隔声明：相邻端点（如 D-y与D-x）→ 直接间隔；跨多段端点（如 D-y~D-0）→ 跨间隔
#     和约束，未被直接声明的间隔按「跨间隔 − 其余已声明间隔」唯一分解。
#   - 每个满足的 (N1..Nk) 组合各出一行（与 T 链口径一致）。
_RE_DVAR_GAP = re.compile(
    r"D-([a-z])\s*(?:[~～]\s*|与\s*)D-(?:0|([a-z]))\s*间隔\s*(?:交易日)?\s*天数?\s*为?\s*"
    r"N(\d+)\s*∈\s*\[\s*(\d+)\s*,\s*(\d+)\s*\]")
_RE_DSYM_DAY = re.compile(r"^D-([a-z])\s*[:：]\s*(.+)$")
_RE_DSYM_BASE = re.compile(r"^(?:基准日(?:\(D-?0\))?|D-0|D0)\s*[:：]\s*(.+)$")
_RE_DSYM_PREV = re.compile(
    r"^D-([a-z])\s*(?:稍前|更早一侧紧邻的|之前|往前|前)\s*(\d+|[一二三四五六七八九十]+)\s*个?交易日?\s*"
    r"D-\(\1\+(\d+)\)\s*[~～]\s*D-\(\1\+(\d+)\)\s*全部不是涨停$")
_RE_DVAR_GAPNOLIMIT = re.compile(
    r"D-([a-z])\s*[~～]\s*(?:D-0|D-([a-z]))\s*(?:整个)?区间(?:内)?")
_RE_DVAR_ONLY = re.compile(
    r"D-([a-z])\s*[~～]\s*D-0整个区间仅((?:D-(?:[a-z]|0)[、，,]?)+)(\d+|[一二三四五六七八九十]+)日涨停")
_RE_DVAR_FREECOMBO = re.compile(r"^(?:N\d+\s*[、/,与和]\s*)*N\d+\s*自由组合$")
_RE_DOUT_KEY = re.compile(
    r"^((?:D-[a-z]|D-0|D-?\d+|D\+\d+)(?:\s*[~～/]\s*(?:D-[a-z]|D-0|D-?\d+|D\+\d+))?|N\d+)\s*[:：]\s*(.*)$")
_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _dvar_empty_plan(universe, problems):
    return {"schema_version": 1, "kind": "day_pattern_backward",
            "strategy_plan": {"universe": universe, "days": [], "outputs": []}}, \
           {"universe": universe or "未指明", "events": [], "outputs": []}, problems


def _translate_dvar_chain(text, cond_text, out_text, universe_hint):
    """D 记法变量间隔 -> 间隔链计划。任何词汇表外表述 -> fail-closed problems。"""
    problems = []
    mu = _RE_UNIVERSE.search(text)
    universe = (mu.group(1) + "cm") if mu else (universe_hint or None)

    sym_conds = {}    # symbol -> cond dict（"0" 代表 D-0）
    sym_prev = {}     # symbol -> 锚点前视无涨停天数
    intervals = []    # (symA, symB_or_"0", "N1", lo, hi)
    gap_nolimit = set()
    only_syms = None
    cur = None
    for clause in _split_clauses(cond_text):
        stripped = clause.strip()
        c = _norm(clause)
        ms = _RE_DSYM_DAY.match(stripped)
        if ms:
            cond = _parse_conditions(ms.group(2))
            if cond is None:
                problems.append({"fragment": clause[:60], "reason": "存在暂不支持的条件表述"})
                continue
            sym = ms.group(1)
            if sym in sym_conds:
                for k, v in cond.items():
                    sym_conds[sym].setdefault(k, v)
            else:
                sym_conds[sym] = cond
            cur = sym
            continue
        m0 = _RE_DSYM_BASE.match(stripped)
        if m0:
            cond = _parse_conditions(m0.group(1))
            if cond is None:
                problems.append({"fragment": clause[:60], "reason": "存在暂不支持的条件表述"})
                continue
            if "0" in sym_conds:
                for k, v in cond.items():
                    sym_conds["0"].setdefault(k, v)
            else:
                sym_conds["0"] = cond
            cur = "0"
            continue
        if _RE_DVAR_GAP.search(c):
            rest = _RE_DVAR_GAP.sub("", c)
            rest = re.sub(r"(?:N\d+\s*[、/,与和]\s*)*N\d+\s*自由组合", "", rest)
            if re.sub(r"[，,、;；\s]", "", rest):
                problems.append({"fragment": clause[:60],
                                 "reason": "间隔声明子句含无法识别的表述（fail-closed）"})
                continue
            for m in _RE_DVAR_GAP.finditer(c):
                intervals.append((m.group(1), m.group(2) or "0",
                                  f"N{m.group(3)}", int(m.group(4)), int(m.group(5))))
            cur = None
            continue
        if _RE_DVAR_FREECOMBO.match(c):
            cur = None
            continue
        mp = _RE_DSYM_PREV.match(c)
        if mp:
            n = _CN_NUM.get(mp.group(2), None)
            n = int(n) if n is not None else int(mp.group(2))
            k1, k2 = int(mp.group(3)), int(mp.group(4))
            if k1 != 1 or k2 != n:
                problems.append({"fragment": clause[:60],
                                 "reason": "前视窗口表述与天数不一致（期望 D-(y+1)~D-(y+N)）"})
                continue
            sym_prev[mp.group(1)] = n
            cur = None
            continue
        if "全部不是涨停" in c and _RE_DVAR_GAPNOLIMIT.search(c):
            # 一个子句可含多对区间（如「D-y~D-x区间、D-x~D-0区间内全部不是涨停」）
            rest = _RE_DVAR_GAPNOLIMIT.sub("", c).replace("全部不是涨停", "")
            if re.sub(r"[，,、;；\s]", "", rest):
                problems.append({"fragment": clause[:60],
                                 "reason": "区间无涨停子句含无法识别的表述（fail-closed）"})
                continue
            for m in _RE_DVAR_GAPNOLIMIT.finditer(c):
                gap_nolimit.add((m.group(1), m.group(2) or "0"))
            cur = None
            continue
        mo = _RE_DVAR_ONLY.search(c)
        if mo:
            listed = set(re.findall(r"D-([a-z0])", mo.group(2)))
            only_syms = listed
            cur = None
            continue
        if cur is not None:
            # 无锚点续行（如「成交额最大」「股价最高」）并入当前锚点，杜绝静默丢弃
            cond = _parse_conditions(c)
            if cond is not None:
                for k, v in cond.items():
                    sym_conds[cur].setdefault(k, v)
                continue
        if _RE_UNIVERSE.search(clause) or len(c) <= 6:
            continue
        problems.append({"fragment": clause[:60], "reason": "存在暂不支持的条件表述（fail-closed）"})

    if not intervals:
        problems.append({"fragment": "（间隔声明）",
                         "reason": "未识别到变量间隔声明（fail-closed）"})
    if problems:
        return _dvar_empty_plan(universe, problems)

    # —— 拓扑：变量日按字母倒序（y 比 x 早），D-0 恒为末锚点 ——
    symset = [s for s in sym_conds if s != "0"]
    order = sorted(symset, reverse=True) + ["0"]
    pos = {sym: i for i, sym in enumerate(order)}
    n_gap = len(order) - 1
    if n_gap < 1:
        problems.append({"fragment": "（间隔声明）", "reason": "至少需要一个变量日与 D-0 构成间隔"})
    for (a, b, var, _lo, _hi) in intervals:
        for s in (a, b):
            if s not in pos:
                problems.append({"fragment": var, "reason": f"间隔端点 D-{s} 缺少条件声明"})
    for sym in symset:
        if sym not in {a for a, _b, _v, _l, _h in intervals} | \
                      {b for _a, b, _v, _l, _h in intervals}:
            problems.append({"fragment": f"D-{sym}",
                             "reason": "变量日未出现在任何间隔声明中，深度无法确定（fail-closed）"})
    if only_syms is not None:
        for s in only_syms:
            if s not in pos:
                problems.append({"fragment": f"D-{s}", "reason": "「仅…日涨停」引用了未声明的变量日"})
    for sym in sym_prev:
        if sym not in pos:
            problems.append({"fragment": f"D-{sym}", "reason": "前视无涨停引用了未声明的变量日"})
    if problems:
        return _dvar_empty_plan(universe, problems)

    # —— 间隔：直接声明的钉死范围；跨多段声明进 span_gaps；未钉死的唯一分解 ——
    gaps = [None] * n_gap
    spans = []
    seen_vars = set()
    for (a, b, var, lo, hi) in intervals:
        if var in seen_vars:
            problems.append({"fragment": var, "reason": "间隔变量名重复声明"})
            continue
        seen_vars.add(var)
        pa, pb = pos[a], pos[b]
        span_idx = list(range(min(pa, pb), max(pa, pb)))
        if len(span_idx) == 1:
            gi = span_idx[0]
            if gaps[gi] is not None:
                problems.append({"fragment": var,
                                 "reason": f"间隔 {order[gi]}~{order[gi + 1]} 被重复声明"})
                continue
            gaps[gi] = {"from": f"T_{gi}", "to": f"T_{gi + 1}",
                        "var": var, "min": lo, "max": hi}
        else:
            spans.append({"var": var, "min": lo, "max": hi, "gaps": span_idx})
    if problems:
        return _dvar_empty_plan(universe, problems)
    for gi, g in enumerate(gaps):
        if g is not None:
            continue
        cover = [s for s in spans if gi in s["gaps"]]
        if len(cover) != 1:
            problems.append({"fragment": f"T_{gi}->T_{gi + 1}",
                             "reason": "该间隔未被任何间隔声明约束，无法确定取值范围（fail-closed）"})
            continue
        s = cover[0]
        unpinned = [j for j in s["gaps"] if j != gi and gaps[j] is None]
        pinned = [gaps[j] for j in s["gaps"] if j != gi and gaps[j] is not None]
        if unpinned:
            problems.append({"fragment": s["var"],
                             "reason": "跨间隔声明包含多个未直接声明的间隔，无法唯一分解（fail-closed）"})
            continue
        lo_u = max(1, s["min"] - sum(o["max"] for o in pinned))
        hi_u = s["max"] - sum(o["min"] for o in pinned)
        if lo_u > hi_u:
            problems.append({"fragment": s["var"], "reason": "间隔范围矛盾（跨间隔下限小于其余间隔上限之和）"})
            continue
        gaps[gi] = {"from": f"T_{gi}", "to": f"T_{gi + 1}", "var": f"_g{gi}",
                    "min": lo_u, "max": hi_u, "internal": True,
                    "decompose": {"span": s["var"],
                                  "minus": [o["var"] for o in pinned]}}
    if problems:
        return _dvar_empty_plan(universe, problems)

    # —— 锚点条件 ——
    anchor_conds = {}
    for i, sym in enumerate(order):
        c = dict(sym_conds.get(sym, {}))
        if only_syms and sym in only_syms:
            c["limit_up"] = True
        if sym in sym_prev:
            c["prev_no_limit"] = sym_prev[sym]
        if not c:
            problems.append({"fragment": "D-0" if sym == "0" else f"D-{sym}",
                             "reason": "缺少条件表述（fail-closed）"})
        anchor_conds[f"T_{i}"] = c
    gap_conds = {}
    for (a, b) in gap_nolimit:
        for j in range(min(pos[a], pos[b]), max(pos[a], pos[b])):
            gap_conds[f"T_{j}->T_{j + 1}"] = {"limit_up": False}
    if problems:
        return _dvar_empty_plan(universe, problems)

    # —— 输出段（键沿用用户 D 记法，列名保留原书写） ——
    outputs = []
    declared = {g["var"] for g in gaps} | {s["var"] for s in spans}
    _d_out_single = {"日期": "chain_date", "振幅": "chain_amplitude",
                     "涨幅": "chain_change", "最低价": "chain_rel_low",
                     "最高价": "chain_rel_high"}
    _d_out_range = {"区间涨幅": "change", "区间振幅": "amplitude",
                    "区间最大振幅": "max_amplitude"}

    def _dout_item(itn, key):
        """解析单个输出项；key 可为 None（内联风格自行推断）。成功 append 或返回错误片段。"""
        m_gap = re.search(r"间隔(?:交易日)?天数?(N\d+)$", itn) or \
            (re.fullmatch(r"(N\d+)", itn) if key and re.fullmatch(r"N\d+", key) else None)
        if m_gap:
            var = m_gap.group(1)
            if var not in declared:
                return f"{var} 未在间隔声明中定义"
            outputs.append({"atom": "chain_gap", "var": var, "label": var})
            return None
        m_fw = re.fullmatch(r"D\+(\d+)[~～/]?D\+(\d+)(?:的)?(股价走势|价格走势)", itn)
        if m_fw:
            a, b = int(m_fw.group(1)), int(m_fw.group(2))
            if a != 1 or b <= a:
                return "前向走势仅支持 D+1~D+n（n≥2）"
            outputs.append({"atom": "chain_walk", "t0": a, "t1": b})
            return None
        m_rng = re.fullmatch(r"D-([a-z0])\s*[~～/]\s*D-([a-z0])(?:的)?(区间涨幅|区间振幅|区间最大振幅)", itn)
        if m_rng:
            sa, sb = m_rng.group(1), m_rng.group(2)
            if sa not in pos or sb not in pos:
                return "输出区间端点未声明"
            outputs.append({"atom": "chain_range", "kind": _d_out_range[m_rng.group(3)],
                            "anchors": [f"T_{pos[sa]}", f"T_{pos[sb]}"],
                            "label": f"{itn}"})
            return None
        m_sg = re.fullmatch(r"D-([a-z0])(?:的)?(日期|振幅|涨幅|最低价|最高价)", itn)
        if m_sg and (key is None or not re.fullmatch(r"N\d+", key)):
            sym = m_sg.group(1)
            if sym not in pos:
                return "输出引用了未声明的变量日"
            outputs.append({"atom": _d_out_single[m_sg.group(2)],
                            "anchor": f"T_{pos[sym]}", "label": itn})
            return None
        if key is not None:
            m_krng = re.fullmatch(r"D-([a-z0])\s*[~～/]\s*D-([a-z0])", key)
            if m_krng and itn in _d_out_range:
                sa, sb = m_krng.group(1), m_krng.group(2)
                if sa not in pos or sb not in pos:
                    return "输出区间端点未声明"
                outputs.append({"atom": "chain_range", "kind": _d_out_range[itn],
                                "anchors": [f"T_{pos[sa]}", f"T_{pos[sb]}"],
                                "label": f"{key}{itn}"})
                return None
            m_sg2 = re.fullmatch(r"(日期|振幅|涨幅|最低价|最高价)", itn)
            if m_sg2 and re.fullmatch(r"D-([a-z0])", key):
                sym = re.fullmatch(r"D-([a-z0])", key).group(1)
                if sym not in pos:
                    return "输出引用了未声明的变量日"
                outputs.append({"atom": _d_out_single[m_sg2.group(1)],
                                "anchor": f"T_{pos[sym]}", "label": f"{key}{itn}"})
                return None
            if re.fullmatch(r"N\d+", key) and "数值" in itn:
                if key not in declared:
                    return f"{key} 未在间隔声明中定义"
                outputs.append({"atom": "chain_gap", "var": key, "label": key})
                return None
            m_fw2 = re.fullmatch(r"(股价走势|价格走势)", itn)
            if m_fw2 and key:
                m_kfw = re.fullmatch(r"D\+(\d+)\s*[~～/]\s*D\+(\d+)", key)
                if m_kfw:
                    a, b = int(m_kfw.group(1)), int(m_kfw.group(2))
                    if a != 1 or b <= a:
                        return "前向走势仅支持 D+1~D+n（n≥2）"
                    outputs.append({"atom": "chain_walk", "t0": a, "t1": b})
                    return None
        return "存在暂不支持的输出指标表述（fail-closed，不猜测）"

    cur_key = None
    for clause in _split_clauses(out_text.replace("【输出指标】", "\n")):
        mk = _RE_DOUT_KEY.match(clause.strip())
        if mk:
            cur_key = _norm(mk.group(1))
            items = [s for s in re.split(r"[；;，,]", mk.group(2)) if s.strip()]
        elif cur_key is not None:
            items = [clause]
        else:
            # 无键内联风格（如「D-0的日期、D-y与D-x间隔交易日天数N1、…」）
            items = [s for s in re.split(r"[、，,]", clause) if s.strip()]
            for it in items:
                err = _dout_item(_norm(it), None)
                if err:
                    problems.append({"fragment": it[:60], "reason": err})
            continue
        for it in items:
            itn = _norm(it)
            if not itn:
                continue
            err = _dout_item(itn, cur_key)
            if err:
                problems.append({"fragment": it[:60], "reason": err})
    if not outputs and not problems:
        problems.append({"fragment": "（输出指标）", "reason": "必须显式给出输出指标"})
    if problems:
        return _dvar_empty_plan(universe, problems)

    # —— 组装（与 T 链计划同构） ——
    chain = {"anchors": [f"T_{i}" for i in range(len(order))],
             "gaps": gaps, "anchor_conds": anchor_conds, "gap_conds": gap_conds,
             "span_gaps": spans}
    sp = {"universe": universe, "days": [], "outputs": outputs, "chain": chain}
    plan = {"schema_version": 1, "kind": "day_pattern_backward", "strategy_plan": sp}
    events = []
    for i, sym in enumerate(order):
        ac = anchor_conds[f"T_{i}"]
        conds = _cond_text(ac)
        if ac.get("prev_no_limit"):
            conds = [f"前{ac['prev_no_limit']}日无涨停"] + conds
        if conds:
            events.append({"id": "D-0" if sym == "0" else f"D-{sym}",
                           "conditions": conds, "is_condition_event": True})
    for g in gaps:
        if g.get("internal"):
            dc = g["decompose"]
            lbl = f"{dc['span']}-" + "-".join(dc["minus"])
        else:
            lbl = g["var"]
        gc = gap_conds.get(f"{g['from']}->{g['to']}")
        events.append({"id": f"{g['from']}~{g['to']}",
                       "conditions": [f"间隔{lbl}∈[{g['min']},{g['max']}]"
                                      + ("，期间无涨停" if gc else "")],
                       "is_condition_event": True})
    for s in spans:
        events.append({"id": f"跨间隔{s['var']}",
                       "conditions": [f"T_{s['gaps'][0]}~T_{s['gaps'][-1] + 1}"
                                      f"跨间隔{s['var']}∈[{s['min']},{s['max']}]"],
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

    # D 记法变量间隔（D-y~D-0间隔…N1∈[a,b]）自动翻译为间隔链计划
    if _RE_DVAR_GAP.search(cond_text):
        return _translate_dvar_chain(text, cond_text, out_text, universe_hint)

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
