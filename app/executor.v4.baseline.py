# -*- coding: utf-8 -*-
"""Strategy Plan 执行器 —— 全部业务公式来自 tdx-stock-backtest Skill，本模块零公式。

组合逻辑：
  1. 读 .day（Skill backtest_common.read_day_file）
  2. 涨停标记（Skill compute_limit_flags）
  3. 20日窗口最大（Skill 0814_backtest.rolling_max20 + 相等比较，口径与 Skill 规则脚本一致）
  4. 输出原子（Skill fmt_date / daily_amplitude / calc_range_increase / calc_range_amplitude /
     generate_t_fields / is_strong_limit_up）
复核（fail-closed）：用 Skill 标量权威口径 is_strong_limit_up 逐行重验涨停条件，
窗口最大用独立 Python max() 重验。任何不一致 -> 结果不可信、不落库。
"""
import logging
import time
from itertools import product as _iproduct
from pathlib import Path

import numpy as np
import pandas as pd

from paths import load_skill_modules, DAY_DIRS

logger = logging.getLogger("qwb.executor")

_START_INT = 19901219

_bc, _sbt, _r0814 = load_skill_modules()

compute_limit_flags = _bc.compute_limit_flags
read_day_file = _bc.read_day_file
fmt_date = _bc.fmt_date
daily_amplitude = _bc.daily_amplitude
calc_range_increase = _sbt.calc_range_increase
calc_range_amplitude = _sbt.calc_range_amplitude
generate_t_fields = _bc.generate_t_fields
is_strong_limit_up = _sbt.is_strong_limit_up
rolling_max20 = _r0814.rolling_max20

# 20cm 板块涨跌幅生效日（Skill backtest_common 常量）
GEM_20CM_DATE = _bc.GEM_20CM_DATE
STAR_20CM_DATE = _r0814.STAR_20CM_DATE


def _collect_stock_files(universe):
    """按板块收集 A 股个股 .day 文件（市场前缀感知，剔除指数/ETF/B股）。"""
    out = []
    for d in DAY_DIRS:
        p = Path(d)
        if not p.exists():
            continue
        for f in sorted(p.glob("*.day")):
            stem = f.stem.lower()
            if not (stem.startswith("sh") or stem.startswith("sz")):
                continue
            code = stem[2:].zfill(6)
            sh = stem.startswith("sh")
            is20 = code.startswith("688") if sh else code.startswith(("300", "301"))
            is10 = code.startswith(("600", "601", "603", "605")) if sh else \
                code.startswith(("000", "001", "002", "003"))
            if universe == "20cm" and is20:
                out.append((code, f))
            elif universe == "10cm" and (is10 or (not sh and code.startswith(("300", "301")))):
                # 2026-09-23 kk 裁定：10cm 池纳入创业板 10% 时代（sz300/301，信号日 < 2020-08-24，
                # 反向门在各执行路径施加）；688 仍不进 10cm。
                out.append((code, f))
            elif universe == "both" and (is20 or is10):
                out.append((code, f))
    return out


def _col_day_name(o):
    """输出列的日锚点名：固定日 D-5 / 变量日 D-x、D-(x+2)、D-(x-1)。

    记号对齐用户基准（0921A_backtest.xlsx）：D-(x+k) 括号记号；
    k=0 即 D-x 本身；k<0 表示比 D-x 更近 |k| 天。
    """
    if "day_var" in o:
        k = o["day_var"]
        if k == 0:
            return "D-x"
        if k > 0:
            return f"D-(x+{k})"
        return f"D-(x-{-k})"
    return f"D-{abs(o['day'])}"


def _col_range_name(days, sep="/"):
    """区间输出列的区间名：两端可为固定偏移或变量日。"""
    def one(d):
        if isinstance(d, dict):
            k = d["var"]
            if k == 0:
                return "D-x"
            if k > 0:
                return f"D-(x+{k})"
            return f"D-(x-{-k})"
        return f"D+{d}" if d > 0 else f"D-{abs(d)}"
    return f"{one(days[0])}{sep}{one(days[1])}"


def _compute_columns(outputs):
    cols = []
    for o in outputs:
        a = o["atom"]
        if a == "date":
            cols.append(f"{_col_day_name(o)}日期")
        elif a == "amplitude":
            cols.append(f"{_col_day_name(o)}振幅")
        elif a == "change":
            cols.append(f"{_col_day_name(o)}涨幅")
        elif a == "rel_low":
            cols.append(f"{_col_day_name(o)}最低价")
        elif a == "rel_high":
            cols.append(f"{_col_day_name(o)}最高价")
        elif a == "x_value":
            cols.append("x")
        elif a in ("range_change", "range_amplitude", "range_max_amplitude"):
            name = {"range_change": "区间涨幅", "range_amplitude": "区间振幅",
                    "range_max_amplitude": "区间最大振幅"}[a]
            cols.append(f"{_col_range_name(o['days'], o.get('sep', '/'))}{name}")
        elif a == "amount_pct":
            cols.append(f"{_col_range_name(o['days'], o.get('sep', '/'))}成交额百分比")
        elif a == "t_walk":
            n = o["t1"] - o["t0"] + 1
            base = o.get("day_base")
            if base is None:
                cols.append("T+0(低/高)")
                cols.extend(f"T+{k}最高价" for k in range(1, n))
            else:
                # D+1~D+8 价格走势：第 k 步（0 起）对应 D+(base+k)
                cols.append(f"D+{base}(低/高)")
                cols.extend(f"D+{base + k}最高价" for k in range(1, n))
    return cols


def _day_index(n, i, off):
    j = i + off
    return j if 0 <= j < n else None


def _mask_for_days(dc, n, limits, is_amtmax, is_highmax, opens, closes):
    """按一组具体日条件（含 _off 具体偏移）计算候选掩码（对齐 D-0 = i）。"""
    cand = np.ones(n, dtype=bool)
    for d in dc:
        off = d["_off"]
        ok = np.ones(n, dtype=bool)
        if "limit_up" in d:
            ok &= limits if d["limit_up"] else ~limits
        if d.get("amount_max20") is not None:
            ok &= is_amtmax if d["amount_max20"] else ~is_amtmax
        if d.get("high_max20") is not None:
            ok &= is_highmax if d["high_max20"] else ~is_highmax
        if d.get("candle"):
            form_ok = (closes > opens) if d["candle"] == "阳" else (closes <= opens)
            # 板优先：涨停日形态为「板」，不参与阳/阴判定（Skill candle_form 口径）
            form_ok = form_ok & ~limits
            ok &= form_ok
        sh2 = np.zeros(n, dtype=bool)
        if off <= 0:
            dst = -off                      # sh2[i] = ok[i - |off|]
            if dst < n:
                sh2[dst:] = ok[: n - dst]
        else:
            if off < n:
                sh2[: n - off] = ok[off:]   # sh2[i] = ok[i + off]
        cand &= sh2
    return cand


def _make_jget(i, xv, n):
    """构造行内日锚解析器：固定日 key=int 偏移；变量日 key=("var", k) 深度 x+k。"""
    cache = {}

    def jget(key):
        if key in cache:
            return cache[key]
        off = -(xv + key[1]) if isinstance(key, tuple) else key
        j = i + off
        cache[key] = j if 0 <= j < n else None
        return cache[key]

    return jget


# ===================== 间隔链（T_0→T_1→…，间隔 N1..Nk 存在量词） =====================

def _chain_columns(outputs):
    cols = []
    for o in outputs:
        a = o["atom"]
        if a == "chain_date":
            cols.append(o.get("label") or f"{o['anchor']}日期")
        elif a == "chain_gap":
            cols.append(o.get("label") or o["var"])
        elif a == "chain_amplitude":
            cols.append(o.get("label") or f"{o['anchor']}振幅")
        elif a == "chain_change":
            cols.append(o.get("label") or f"{o['anchor']}涨幅")
        elif a == "chain_rel_low":
            cols.append(o.get("label") or f"{o['anchor']}最低价")
        elif a == "chain_rel_high":
            cols.append(o.get("label") or f"{o['anchor']}最高价")
        elif a == "chain_range":
            name = {"change": "区间涨幅", "amplitude": "区间振幅",
                    "max_amplitude": "区间最大振幅"}[o["kind"]]
            cols.append(o.get("label") or f"{o['anchors'][0]}~{o['anchors'][1]}{name}")
        elif a == "chain_walk":
            base = o.get("t0", 1)
            cols.append(f"D+{base}(低/高)")
            for kk in range(1, o["t1"] - base + 1):
                cols.append(f"D+{base + kk}最高价")
    return cols


def _chain_anchor_ok(c, j, limits, is_amtmax, is_highmax):
    """单锚点条件快检（向量化口径，与复核的标量口径独立）。"""
    if c.get("limit_up") is not None and bool(limits[j]) != c["limit_up"]:
        return False
    p = c.get("prev_no_limit")
    if p is not None:
        if j - p < 0 or limits[j - p: j].any():
            return False
    if c.get("amount_max20") is not None and (j < 19 or bool(is_amtmax[j]) != c["amount_max20"]):
        return False
    if c.get("high_max20") is not None and (j < 19 or bool(is_highmax[j]) != c["high_max20"]):
        return False
    return True


def _build_chain_row(code, dates, opens, highs, lows, closes, amounts, limits,
                     js, anchors, outputs, gval):
    """gval: 间隔变量 -> 数值（相邻间隔取组合值；跨间隔变量取其覆盖间隔之和）。"""
    row = {"股票代码": code, "股票名称": ""}
    jmap = dict(zip(anchors, js))
    for o in outputs:
        a = o["atom"]
        if a == "chain_date":
            row[o.get("label") or f"{o['anchor']}日期"] = fmt_date(dates[jmap[o["anchor"]]])
        elif a == "chain_gap":
            row[o.get("label") or o["var"]] = gval[o["var"]]
        elif a == "chain_amplitude":
            j = jmap[o["anchor"]]
            row[o.get("label") or f"{o['anchor']}振幅"] = (
                round(float(daily_amplitude(highs[j], lows[j], closes[j - 1])), 2)
                if j >= 1 else "N/A")
        elif a == "chain_change":
            j = jmap[o["anchor"]]
            row[o.get("label") or f"{o['anchor']}涨幅"] = (
                calc_range_increase(float(closes[j]), float(closes[j - 1]))
                if j >= 1 else "N/A")
        elif a == "chain_rel_low":
            j = jmap[o["anchor"]]
            v = ((lows[j] - closes[j - 1]) / closes[j - 1] * 100.0 if j >= 1 else None)
            row[o.get("label") or f"{o['anchor']}最低价"] = f"{round(float(v), 2):+.2f}" if v is not None else "N/A"
        elif a == "chain_rel_high":
            j = jmap[o["anchor"]]
            v = ((highs[j] - closes[j - 1]) / closes[j - 1] * 100.0 if j >= 1 else None)
            row[o.get("label") or f"{o['anchor']}最高价"] = f"{round(float(v), 2):+.2f}" if v is not None else "N/A"
        elif a == "chain_range":
            ja, jb = jmap[o["anchors"][0]], jmap[o["anchors"][1]]
            base = float(closes[ja - 1]) if ja >= 1 else None
            name = {"change": "区间涨幅", "amplitude": "区间振幅",
                    "max_amplitude": "区间最大振幅"}[o["kind"]]
            col = o.get("label") or f"{o['anchors'][0]}~{o['anchors'][1]}{name}"
            if base is None or base <= 0 or jb < ja:
                row[col] = "N/A"
            elif o["kind"] == "change":
                row[col] = f"{calc_range_increase(float(closes[jb]), base)}%"
            elif o["kind"] == "amplitude":
                row[col] = f"{calc_range_amplitude(highs[ja:jb + 1].tolist(), lows[ja:jb + 1].tolist(), base)}%"
            else:
                amps = [(highs[j2] - lows[j2]) / (closes[j2 - 1] if closes[j2 - 1] > 0 else 1) * 100.0
                        for j2 in range(ja, jb + 1)]
                # 区间最大振幅 = 区间内逐日「单日」振幅取最大 -> 单日口径，不带 %（Skill 输出规范）
                row[col] = round(max(amps), 2)
        elif a == "chain_walk":
            # 链式前向走势：与量化路径 t_walk 同口径（T+0 = 信号日后一交易日），
            # 列名沿用用户 D+ 记号（D+1 对应 T+0）。
            je = js[-1]
            base = o.get("t0", 1)
            t_count = o["t1"] - base + 1
            t_raw = generate_t_fields(opens, highs, lows, closes, limits,
                                      base_idx=je, n=len(dates), t_count=t_count)
            row[f"D+{base}(低/高)"] = t_raw.get("T+0(低/高)", "N/A")
            for kk in range(1, t_count):
                row[f"D+{base + kk}最高价"] = t_raw.get(f"T+{kk}最高价", "N/A")
    return row


def _run_chain(plan, start_date, end_date, data_end, progress_cb):
    """间隔链回测：T_0 为最早锚点，T_2（末锚点）为信号日。

    口径（kk 2026-09-22 裁定，对齐 Skill）：间隔 N = 两段涨停之间、**不含两端**的
    K 线根数，即相邻锚点下标差 = N + 1；两日相邻时 N = 0。
    跨间隔（span，如 D-y~D-0 相隔一个中间锚点）N = 各相邻间隔之和 + (中间锚点数)；
    每个满足的 (N1..Nk) 组合各出一行，行内带各 N 数值列。
    """
    sp = plan["strategy_plan"]
    chain = sp["chain"]
    universe = sp["universe"] or "both"
    outputs = sp["outputs"]
    anchors = chain["anchors"]
    gaps = chain["gaps"]
    acon = chain["anchor_conds"]
    gcon = chain["gap_conds"]
    spans = chain.get("span_gaps", [])   # 跨间隔和约束：{"var","min","max","gaps":[间隔下标]}
    start_int = int(start_date.replace("-", "")) if start_date else _START_INT
    end_int = int(end_date.replace("-", "")) if end_date else 20991231
    data_end_int = int(data_end.replace("-", "")) if data_end else 20991231

    prev_need = max([c.get("prev_no_limit", 0) for c in acon.values()] + [0])
    need_window = any(c.get("amount_max20") is not None or c.get("high_max20") is not None
                      for c in acon.values())
    # 相邻锚点下标差 = 间隔值 + 1（间隔 N = 不含两端的中间 K 线根数）
    min_total = sum(g["min"] + 1 for g in gaps)
    gap_ranges = [range(g["min"], g["max"] + 1) for g in gaps]
    gap_vars = [g["var"] for g in gaps]
    gap_pairs = [(anchors.index(g["from"]), anchors.index(g["to"])) for g in gaps]

    stock_files = _collect_stock_files(universe)
    logger.info("链式回测开始: universe=%s 标的=%d anchors=%s gaps=%s",
                universe, len(stock_files), anchors,
                [(g["var"], g["min"], g["max"]) for g in gaps])
    t0 = time.time()
    rows = []
    for k, (code, f) in enumerate(stock_files):
        if progress_cb and k % 500 == 0:
            progress_cb(k, len(stock_files))
        res = read_day_file(f)
        if res is None:
            continue
        dates, opens, highs, lows, closes, amounts, volumes = res
        if data_end_int < 20991231:
            k2 = int(np.searchsorted(dates, data_end_int, side="right"))
            dates, opens, highs, lows, closes, amounts, volumes = (
                a[:k2] for a in (dates, opens, highs, lows, closes, amounts, volumes))
        amounts = amounts.astype(np.float64, copy=False)
        n = len(dates)
        if n < 21:
            continue
        close_c = np.round(closes * 100).astype(np.int64)
        high_c = np.round(highs * 100).astype(np.int64)
        limits = compute_limit_flags(dates, close_c, high_c, code)
        amt_max20 = rolling_max20(amounts)
        high_max20 = rolling_max20(highs)
        with np.errstate(invalid="ignore"):
            is_amtmax = np.zeros(n, dtype=bool)
            is_highmax = np.zeros(n, dtype=bool)
            is_amtmax[19:] = amounts[19:] == amt_max20[19:]
            is_highmax[19:] = highs[19:] == high_max20[19:]

        # T_0 条件与间隔无关，先做一次快检
        c0 = acon.get(anchors[0], {})
        i_lo = max(prev_need, 19 if need_window else 0, 1)
        for i0 in range(i_lo, n - min_total):
            if not _chain_anchor_ok(c0, i0, limits, is_amtmax, is_highmax):
                continue
            for combo in _iproduct(*gap_ranges):
                if spans:
                    # 跨间隔和约束（如 N1 = D-y~D-0 ∈ [3,8]）：
                    # span 值 = 各相邻间隔之和 + (中间锚点数)，先廉价过滤
                    bad = False
                    for s in spans:
                        ss = sum(combo[gi] for gi in s["gaps"]) + (len(s["gaps"]) - 1)
                        if ss < s["min"] or ss > s["max"]:
                            bad = True
                            break
                    if bad:
                        continue
                js = [i0]
                acc = i0
                for gv in combo:
                    acc += gv + 1
                    js.append(acc)
                je = js[-1]
                if je >= n:
                    continue
                d_sig = int(dates[je])
                if d_sig < start_int or d_sig > end_int:
                    continue
                # 板块涨跌幅口径过滤（2026-09-23 kk 裁定，作用于末锚点信号日）
                if universe == "20cm":
                    if code.startswith("688") and d_sig < STAR_20CM_DATE:
                        continue
                    if code.startswith(("300", "301")) and d_sig < GEM_20CM_DATE:
                        continue
                elif universe == "10cm" and code.startswith(("300", "301")) \
                        and d_sig >= GEM_20CM_DATE:
                    continue
                ok = True
                for a_name, j in zip(anchors[1:], js[1:]):
                    if not _chain_anchor_ok(acon.get(a_name, {}), j,
                                            limits, is_amtmax, is_highmax):
                        ok = False
                        break
                if ok:
                    for a_name, c in acon.items():
                        if "amount_ge" not in c:
                            continue
                        j = js[anchors.index(a_name)]
                        for other in c["amount_ge"]:
                            if amounts[j] < amounts[js[anchors.index(other)]]:
                                ok = False
                                break
                        if not ok:
                            break
                if ok:
                    for gi, (pa, pb) in enumerate(gap_pairs):
                        gc = gcon.get(f"{gaps[gi]['from']}->{gaps[gi]['to']}")
                        if gc and gc.get("limit_up") is False and \
                                limits[js[pa] + 1: js[pb]].any():
                            ok = False
                            break
                if not ok:
                    continue
                if closes[i0 - 1] <= 0 or closes[je] <= 0:
                    continue
                gval = {g["var"]: combo[gi] for gi, g in enumerate(gaps)}
                for s in spans:
                    gval[s["var"]] = sum(combo[gi] for gi in s["gaps"])
                rows.append(_build_chain_row(code, dates, opens, highs, lows, closes,
                                             amounts, limits, js, anchors, outputs, gval))
    logger.info("链式回测完成: %d 条, 耗时 %.1fs", len(rows), time.time() - t0)
    if rows:
        df = pd.DataFrame(rows)
        _bc.match_stock_names(df)
        rows = df.to_dict("records")
    columns = ["股票代码", "股票名称"] + _chain_columns(outputs)
    meta = {"universe": universe, "n_stocks": len(stock_files),
            "start_date": fmt_date(start_int), "end_date": fmt_date(end_int)}
    return rows, columns, meta


def run_plan(plan, start_date=None, end_date=None, data_end=None, progress_cb=None):
    """执行 day_pattern_backward 计划，返回 (rows, columns, meta)。

    data_end: 数据截断日（YYYY-MM-DD）。截断后行情数组不包含晚于该日的数据，
    用于 Golden 历史时点复现（生成时点之后的数据不得参与 T 字段计算）。
    """
    sp = plan["strategy_plan"]
    if sp.get("chain") is not None:
        return _run_chain(plan, start_date, end_date, data_end, progress_cb)
    universe = sp["universe"] or "both"
    days = sp["days"]
    outputs = sp["outputs"]
    start_int = int(start_date.replace("-", "")) if start_date else _START_INT
    end_int = int(end_date.replace("-", "")) if end_date else 20991231
    data_end_int = int(data_end.replace("-", "")) if data_end else 20991231

    fixed_offs = [d["offset"] for d in days if "offset" in d]
    min_off = min(fixed_offs) if fixed_offs else 0   # 最深回看（负数，仅固定日）
    max_off = max(fixed_offs) if fixed_offs else 0
    need_window = any(d.get("amount_max20") is not None or d.get("high_max20") is not None
                      for d in days)
    t_count = 0
    for o in outputs:
        if o["atom"] == "t_walk":
            t_count = max(t_count, o["t1"] - o["t0"] + 1)
    quant = sp.get("quantifier")   # 组合规则：{"var": "x", "min": a, "max": b}

    stock_files = _collect_stock_files(universe)
    logger.info("回测开始: universe=%s 标的=%d outputs=%d quantifier=%s",
                universe, len(stock_files), len(outputs),
                f"x∈[{quant['min']},{quant['max']}]" if quant else "-")
    t0 = time.time()
    rows = []
    for k, (code, f) in enumerate(stock_files):
        if progress_cb and k % 500 == 0:
            progress_cb(k, len(stock_files))
        res = read_day_file(f)
        if res is None:
            continue
        dates, opens, highs, lows, closes, amounts, volumes = res
        if data_end_int < 20991231:
            k = int(np.searchsorted(dates, data_end_int, side="right"))
            dates, opens, highs, lows, closes, amounts, volumes = (
                a[:k] for a in (dates, opens, highs, lows, closes, amounts, volumes))
        # Skill 规则脚本（0909A/0824 等）内部将成交额 astype(float64) 后计算，
        # read_day_file 原始返回 float32；这里对齐 Skill 自身的读取口径。
        amounts = amounts.astype(np.float64, copy=False)
        n = len(dates)
        if n < 21:
            continue
        close_c = np.round(closes * 100).astype(np.int64)
        high_c = np.round(highs * 100).astype(np.int64)
        limits = compute_limit_flags(dates, close_c, high_c, code)
        amt_max20 = rolling_max20(amounts)
        high_max20 = rolling_max20(highs)
        with np.errstate(invalid="ignore"):
            is_amtmax = np.zeros(n, dtype=bool)
            is_highmax = np.zeros(n, dtype=bool)
            is_amtmax[19:] = amounts[19:] == amt_max20[19:]
            is_highmax[19:] = highs[19:] == high_max20[19:]

        # 候选掩码（对齐 D-0 = i）
        if quant is not None:
            # —— 组合（变量日）路径：对每个 x 构造具体日条件，存在即命中；
            #    kk 口径：每个满足的 x 各出一行（行内带 x 数值列）——
            per_x = []
            for xv in range(int(quant["min"]), int(quant["max"]) + 1):
                dc = []
                for d in days:
                    base = {k2: v2 for k2, v2 in d.items()
                            if k2 not in ("offset", "offset_var")}
                    if "offset_var" in d:
                        dc.append({**base, "_off": -(xv + d["offset_var"])})
                    else:
                        dc.append({**base, "_off": d["offset"]})
                cand_x = _mask_for_days(dc, n, limits, is_amtmax, is_highmax, opens, closes)
                offs = [d["_off"] for d in dc]
                deepest = min(offs)
                if need_window:
                    i_min = -deepest + 19
                    if i_min > 0:
                        cand_x[:i_min] = False
                lo = 1 - deepest            # 条件日 j = i + off >= 1
                if lo > 0:
                    cand_x[:lo] = False
                hi = n - max(offs)          # 条件日 j <= n-1（防前向越界）
                if hi < n:
                    cand_x[hi:] = False
                per_x.append((xv, dc, cand_x))
            cand = np.zeros(n, dtype=bool)
            for _, _, cand_x in per_x:
                cand |= cand_x
            # 板块涨跌幅口径过滤（2026-09-23 kk 裁定：20cm 维持生效日起；10cm 纳入创业板
            # 10% 时代=300/301 信号日须 < GEM_20CM_DATE；both=各板块全时代并集，不加门槛）
            if universe == "20cm":
                if code.startswith("688"):
                    cand &= dates >= STAR_20CM_DATE
                elif code.startswith(("300", "301")):
                    cand &= dates >= GEM_20CM_DATE
            elif universe == "10cm" and code.startswith(("300", "301")):
                cand &= dates < GEM_20CM_DATE
            cand &= (dates >= start_int) & (dates <= end_int)
            for i in np.nonzero(cand)[0]:
                i = int(i)
                if closes[i - 1] <= 0 or closes[i] <= 0:
                    continue
                # 出行口径（2026-09-21 kk，0921A 基准实证 299/299）：
                # 每个 D-0 命中日只出一行，x 取最小满足值；
                # plan 里 quantifier.mode="all" 可切回「每个满足的 x 各出一行」。
                q_mode = (quant or {}).get("mode", "min")
                for xv, _dc, cand_x in per_x:
                    if not cand_x[i]:
                        continue
                    rows.append(_build_row(code, dates, opens, highs, lows, closes,
                                           amounts, limits, i, _make_jget(i, xv, n),
                                           outputs, t_count, x=xv))
                    if q_mode == "min":
                        break
            continue

        cand = np.ones(n, dtype=bool)
        for d in days:
            # 每日条件掩码 ok[i] 对应「第 i 日」；随后按偏移对齐到 D-0
            ok = np.ones(n, dtype=bool)
            if "limit_up" in d:
                ok &= limits if d["limit_up"] else ~limits
            if d.get("amount_max20") is not None:
                ok &= is_amtmax if d["amount_max20"] else ~is_amtmax
            if d.get("high_max20") is not None:
                ok &= is_highmax if d["high_max20"] else ~is_highmax
            if d.get("candle"):
                form_ok = (closes > opens) if d["candle"] == "阳" else (closes <= opens)
                # 板优先：涨停日形态为「板」，不参与阳/阴判定（Skill candle_form 口径）
                form_ok = form_ok & ~limits
                ok &= form_ok
            # 对齐: sh2[i] = ok[i + off]
            off = d["offset"]
            sh2 = np.zeros(n, dtype=bool)
            if off <= 0:
                dst = -off                      # sh2[i] = ok[i - |off|]
                sh2[dst:] = ok[: n - dst]
            else:
                sh2[: n - off] = ok[off:]       # sh2[i] = ok[i + off]
            cand &= sh2

        # 窗口有效性：使用窗口原子的最深日 j = i + min_off 需 >= 19
        if need_window:
            i_min = -min_off + 19
            if i_min > 0:
                cand[:i_min] = False
        # 前向日（t_walk 不受限；仅当 days 含前向时已 fail-closed）
        if max_off > 0:
            cand[n - max_off:] = False
        # 板块涨跌幅口径过滤（2026-09-23 kk 裁定，与变量日路径同口径）
        if universe == "20cm":
            if code.startswith("688"):
                cand &= dates >= STAR_20CM_DATE
            elif code.startswith(("300", "301")):
                cand &= dates >= GEM_20CM_DATE
        elif universe == "10cm" and code.startswith(("300", "301")):
            cand &= dates < GEM_20CM_DATE
        cand &= (dates >= start_int) & (dates <= end_int)

        idxs = np.nonzero(cand)[0]
        for i in idxs:
            i = int(i)
            jmap = {}
            valid = True
            for d in days:
                j = _day_index(n, i, d["offset"])
                if j is None or j < 1:
                    valid = False
                    break
                jmap[d["offset"]] = j
            if not valid:
                continue
            if closes[i - 1] <= 0 or closes[i] <= 0:
                continue

            def _jget(key, _i=i, _jm=jmap, _n=n):
                # 固定日：条件日取 jmap，其余回退 i+key；越界 -> N/A
                if isinstance(key, tuple):
                    return None
                j = _jm[key] if key in _jm else _i + key
                return j if 0 <= j < _n else None

            row = _build_row(code, dates, opens, highs, lows, closes, amounts, limits,
                             i, _jget, outputs, t_count)
            rows.append(row)
    logger.info("回测完成: %d 条, 耗时 %.1fs", len(rows), time.time() - t0)
    if rows:
        df = pd.DataFrame(rows)
        _bc.match_stock_names(df)  # Skill 本地名称缓存（stock_names.csv）
        rows = df.to_dict("records")
    columns = ["股票代码", "股票名称"] + _compute_columns(outputs)
    meta = {"universe": universe, "n_stocks": len(stock_files),
            "start_date": fmt_date(start_int), "end_date": fmt_date(end_int)}
    return rows, columns, meta


def _okey(o):
    """输出原子的日锚键：固定日 int 偏移；变量日 ("var", k)。"""
    if "day_var" in o:
        return ("var", o["day_var"])
    return o["day"]


def _dkey(d):
    """区间端点键：固定偏移 int；变量日 {"var": k} -> ("var", k)。"""
    return ("var", d["var"]) if isinstance(d, dict) else d


def _build_row(code, dates, opens, highs, lows, closes, amounts, limits,
               i, jget, outputs, t_count, x=None):
    """构建单条命中行。

    jget(key) -> j 或 None：key 为固定日 int 偏移或 ("var", k)（深度 = x + k）。
    任何越界引用输出 N/A（前向数据不足等），不影响其余列。
    """
    row = {"股票代码": code, "股票名称": ""}
    for o in outputs:
        a = o["atom"]
        if a == "x_value":
            row["x"] = x
        elif a == "date":
            j = jget(_okey(o))
            row[f"{_col_day_name(o)}日期"] = fmt_date(dates[j]) if j is not None else "N/A"
        elif a == "amplitude":
            j = jget(_okey(o))
            row[f"{_col_day_name(o)}振幅"] = (
                round(float(daily_amplitude(highs[j], lows[j], closes[j - 1])), 2)
                if j is not None and j >= 1 else "N/A")
        elif a == "change":
            j = jget(_okey(o))
            row[f"{_col_day_name(o)}涨幅"] = (
                calc_range_increase(float(closes[j]), float(closes[j - 1]))
                if j is not None and j >= 1 else "N/A")
        elif a == "rel_low":
            j = jget(_okey(o))
            v = ((lows[j] - closes[j - 1]) / closes[j - 1] * 100.0
                 if j is not None and j >= 1 else None)
            row[f"{_col_day_name(o)}最低价"] = f"{round(float(v), 2):+.2f}" if v is not None else "N/A"
        elif a == "rel_high":
            j = jget(_okey(o))
            v = ((highs[j] - closes[j - 1]) / closes[j - 1] * 100.0
                 if j is not None and j >= 1 else None)
            row[f"{_col_day_name(o)}最高价"] = f"{round(float(v), 2):+.2f}" if v is not None else "N/A"
        elif a in ("range_change", "range_amplitude", "range_max_amplitude"):
            da, db = o["days"]
            ja, jb = jget(_dkey(da)), jget(_dkey(db))
            base = float(closes[ja - 1]) if ja is not None and ja >= 1 else None
            name = {"range_change": "区间涨幅", "range_amplitude": "区间振幅",
                    "range_max_amplitude": "区间最大振幅"}[a]
            col = f"{_col_range_name(o['days'], o.get('sep', '/'))}{name}"
            if base is None or base <= 0 or jb is None or jb < ja:
                row[col] = "N/A"
            elif a == "range_change":
                row[col] = f"{calc_range_increase(float(closes[jb]), base)}%"
            elif a == "range_amplitude":
                row[col] = f"{calc_range_amplitude(highs[ja:jb + 1].tolist(), lows[ja:jb + 1].tolist(), base)}%"
            else:
                amps = [(highs[j] - lows[j]) / (closes[j - 1] if closes[j - 1] > 0 else 1) * 100.0
                        for j in range(ja, jb + 1)]
                # 区间最大振幅 = 区间内逐日「单日」振幅取最大 -> 单日口径，不带 %（Skill 输出规范：
                # 0908_backtest.py L25 / B9 L9 / 0803 L12「单日涨幅/振幅数值不带 %」；
                # 老 Skill 0908 脚本 L312 自身带 % 属格式化瑕疵，golden 继承，裁定按规范修正）
                row[col] = round(max(amps), 2)
        elif a == "amount_pct":
            da, db = o["days"]
            ja, jb = jget(_dkey(da)), jget(_dkey(db))
            col = f"{_col_range_name(o['days'], o.get('sep', '/'))}成交额百分比"
            if ja is None or jb is None or jb < 0:
                row[col] = "N/A"
            else:
                den = amounts[jb]
                row[col] = f"{round(float(amounts[ja] / den * 100.0), 2)}%" if den > 0 else "N/A"
        elif a == "t_walk":
            t_raw = generate_t_fields(opens, highs, lows, closes, limits,
                                      base_idx=i, n=len(dates), t_count=t_count or 7)
            n_fields = t_count or 7
            base = o.get("day_base")
            if base is None:
                row["T+0(低/高)"] = t_raw.get("T+0(低/高)", "N/A")
                for kk in range(1, n_fields):
                    row[f"T+{kk}最高价"] = t_raw.get(f"T+{kk}最高价", "N/A")
            else:
                row[f"D+{base}(低/高)"] = t_raw.get("T+0(低/高)", "N/A")
                for kk in range(1, n_fields):
                    row[f"D+{base + kk}最高价"] = t_raw.get(f"T+{kk}最高价", "N/A")
    return row


# ===================== 确定性复核（fail-closed） =====================

def validate_rows(plan, rows, columns):
    """独立重验：每行每个日条件的原子用 Skill 标量口径重算。

    返回 violations 列表（空 = 通过）。样本全量复核（命中行数量级 ~1e3-1e4，可接受）。
    """
    sp = plan["strategy_plan"]
    universe = sp["universe"] or "both"
    days = sp["days"]
    quant = sp.get("quantifier")
    chain = sp.get("chain")
    violations = []
    if not rows:
        return violations
    by_code = {}
    for r in rows:
        by_code.setdefault(r["股票代码"], []).append(r)
    for code, rws in by_code.items():
        f = None
        for d in DAY_DIRS:
            p = Path(d) / (("sh" if code.startswith(("6",)) else "sz") + code + ".day")
            if p.exists():
                f = p
                break
        if f is None:
            for d in DAY_DIRS:
                p = Path(d) / ("sz" + code + ".day")
                if p.exists():
                    f = p
                    break
        if f is None:
            violations.append({"code": "DATA_MISSING", "detail": f"{code}: 数据文件缺失"})
            continue
        res = read_day_file(f)
        dates, opens, highs, lows, closes, amounts, _v = res
        n = len(dates)
        date_pos = {int(dt): k for k, dt in enumerate(dates)}
        dates_pd = pd.to_datetime(pd.Series(dates).astype(str), format="%Y%m%d")
        # 涨停判定口径（C2 裁定）：严格 ==，与执行器共用 Skill 唯一权威实现
        # compute_limit_flags；复核的独立性体现在「由 日期+N 重建位置后逐行重验」。
        # 标量 is_strong_limit_up 为 >= 口径，在超涨停价脏点上会误报，不用于涨停复核。
        flags = compute_limit_flags(dates, np.round(closes * 100).astype(np.int64),
                                    np.round(highs * 100).astype(np.int64), code)
        if chain is not None:
            # —— 间隔链复核：由 T_2 日期 + N 值重建锚点位置，独立重验全部条件 ——
            anchors = chain["anchors"]
            gaps = chain["gaps"]
            acon = chain["anchor_conds"]
            gcon = chain["gap_conds"]
            spans = chain.get("span_gaps", [])
            for r in rws:
                dcol = f"{anchors[-1]}日期"
                if dcol not in r:
                    dcol = next((c for c in r if c.endswith("日期")), None)
                if dcol is None:
                    violations.append({"code": "ROW_INVALID", "detail": f"{code}: 缺少日期列"})
                    continue
                d0 = int(r[dcol].replace("-", ""))
                je = date_pos.get(d0)
                if je is None:
                    violations.append({"code": "DATE_MISSING",
                                       "detail": f"{code}@{r[dcol]}: 日期不在行情中"})
                    continue
                gvs = []
                ok = True
                # 行内间隔值：直接声明间隔取行值；内部间隔 = 跨间隔和 − 其余已声明间隔
                rowvals = {}
                for g in gaps:
                    if g.get("internal"):
                        continue
                    gv = r.get(g["var"])
                    if not isinstance(gv, (int, np.integer)):
                        violations.append({"code": "ROW_INVALID",
                                           "detail": f"{code}@{r[dcol]}: 缺少 {g['var']} 数值"})
                        ok = False
                        break
                    rowvals[g["var"]] = int(gv)
                if ok:
                    for s in spans:
                        sv = r.get(s["var"])
                        if not isinstance(sv, (int, np.integer)):
                            violations.append({"code": "ROW_INVALID",
                                               "detail": f"{code}@{r[dcol]}: 缺少 {s['var']} 数值"})
                            ok = False
                            break
                        rowvals[s["var"]] = int(sv)
                if ok:
                    for g in gaps:
                        if g.get("internal"):
                            dc = g["decompose"]
                            gv = rowvals[dc["span"]] - sum(rowvals[m] for m in dc["minus"])
                        else:
                            gv = rowvals[g["var"]]
                        if not (g["min"] <= gv <= g["max"]):
                            violations.append({"code": "ROW_INVALID",
                                               "detail": f"{code}@{r[dcol]}: {g['var']}={gv} 超出范围"})
                            ok = False
                            break
                        gvs.append(gv)
                if ok and spans:
                    for s in spans:
                        ss = sum(gvs[gi] for gi in s["gaps"]) + (len(s["gaps"]) - 1)
                        if not (s["min"] <= ss <= s["max"]):
                            violations.append({"code": "SPAN_MISMATCH",
                                               "detail": f"{code}@{r[dcol]}: {s['var']} 和={ss} 超出范围"})
                            ok = False
                            break
                if not ok:
                    continue
                js = [je]
                acc = je
                for gv in reversed(gvs):
                    acc -= gv + 1
                    js.insert(0, acc)
                i0 = js[0]
                if i0 < 1 or any(j < 1 or j >= n for j in js):
                    violations.append({"code": "INDEX_OUT_OF_RANGE",
                                       "detail": f"{code}@{r[dcol]}"})
                    continue
                for a_name, j in zip(anchors, js):
                    c = acon.get(a_name, {})
                    tag = f"{code}@{r[dcol]} {a_name}"
                    if c.get("limit_up") is not None:
                        actual = bool(flags[j])
                        if actual != c["limit_up"]:
                            violations.append({
                                "code": "LIMIT_UP_MISMATCH",
                                "detail": f"{tag}: 期望{'涨停' if c['limit_up'] else '非涨停'}, 复核={'涨停' if actual else '非涨停'}"})
                    p = c.get("prev_no_limit")
                    if p is not None:
                        if j - p < 0 or flags[j - p: j].any():
                            violations.append({
                                "code": "PREV_NO_LIMIT_MISMATCH",
                                "detail": f"{tag}: 前{p}日应无涨停"})
                    if c.get("amount_max20") is not None and j >= 19:
                        wmax = float(np.max(amounts[j - 19: j + 1]))
                        actual = abs(float(amounts[j]) - wmax) < 1e-6 * max(1.0, wmax)
                        if actual != c["amount_max20"]:
                            violations.append({
                                "code": "AMOUNT_MAX20_MISMATCH",
                                "detail": f"{tag}: 期望成交额{'为' if c['amount_max20'] else '非'}20日最高"})
                    if c.get("high_max20") is not None and j >= 19:
                        wmax = float(np.max(highs[j - 19: j + 1]))
                        actual = abs(float(highs[j]) - wmax) < 1e-9
                        if actual != c["high_max20"]:
                            violations.append({
                                "code": "HIGH_MAX20_MISMATCH",
                                "detail": f"{tag}: 期望最高价{'为' if c['high_max20'] else '非'}20日最高"})
                    if "amount_ge" in c:
                        for other in c["amount_ge"]:
                            jo = js[anchors.index(other)]
                            if amounts[j] < amounts[jo] - 1e-6 * max(1.0, amounts[jo]):
                                violations.append({
                                    "code": "AMOUNT_GE_MISMATCH",
                                    "detail": f"{tag}: 成交额应不小于 {other}"})
                for g, gv in zip(gaps, gvs):
                    gc = gcon.get(f"{g['from']}->{g['to']}")
                    if gc and gc.get("limit_up") is False:
                        jf, jt = js[anchors.index(g["from"])], js[anchors.index(g["to"])]
                        if flags[jf + 1: jt].any():
                            violations.append({
                                "code": "GAP_LIMIT_MISMATCH",
                                "detail": f"{code}@{r[dcol]} {g['from']}~{g['to']} 间隔内出现涨停"})
            if len(violations) > 50:
                break
        if chain is not None:
            if len(violations) > 50:
                break
            continue
        for r in rws:
            d0_col = next((c for c in r if c.endswith("日期")), None)
            if d0_col is None:
                violations.append({"code": "ROW_INVALID", "detail": f"{code}: 缺少日期列"})
                continue
            d0 = int(r[d0_col].replace("-", ""))
            i = date_pos.get(d0)
            if i is None:
                violations.append({"code": "DATE_MISSING", "detail": f"{code}@{r[d0_col]}: 日期不在行情中"})
                continue
            if quant is not None:
                xv = r.get("x")
                if not isinstance(xv, (int, np.integer)):
                    violations.append({"code": "ROW_INVALID",
                                       "detail": f"{code}@{r[d0_col]}: 组合规则缺少 x 数值"})
                    continue
                xv = int(xv)
                if not (quant["min"] <= xv <= quant["max"]):
                    violations.append({"code": "ROW_INVALID",
                                       "detail": f"{code}@{r[d0_col]}: x={xv} 超出声明范围"})
                    continue
                eff_days = [{**{k2: v2 for k2, v2 in d.items()
                                if k2 not in ("offset", "offset_var")},
                             "offset": (-(xv + d["offset_var"]) if "offset_var" in d
                                        else d["offset"])}
                            for d in days]
            else:
                eff_days = days
            for dspec in eff_days:
                j = i + dspec["offset"]
                if j < 1 or j >= n:
                    violations.append({"code": "INDEX_OUT_OF_RANGE", "detail": f"{code}@{r[d0_col]}"})
                    continue
                if "limit_up" in dspec:
                    expect = dspec["limit_up"]
                    actual = bool(flags[j])
                    if actual != expect:
                        violations.append({
                            "code": "LIMIT_UP_MISMATCH",
                            "detail": f"{code}@{r[d0_col]} D{dspec['offset']}: 期望{'涨停' if expect else '非涨停'}, 复核={'涨停' if actual else '非涨停'}"})
                if dspec.get("amount_max20") is not None and j >= 19:
                    wmax = float(np.max(amounts[j - 19: j + 1]))
                    actual = abs(float(amounts[j]) - wmax) < 1e-6 * max(1.0, wmax)
                    if actual != dspec["amount_max20"]:
                        violations.append({
                            "code": "AMOUNT_MAX20_MISMATCH",
                            "detail": f"{code}@{r[d0_col]} D{dspec['offset']}: 期望成交额{'为' if dspec['amount_max20'] else '非'}20日最大, 复核={'为' if actual else '非'}"})
                if dspec.get("high_max20") is not None and j >= 19:
                    wmax = float(np.max(highs[j - 19: j + 1]))
                    actual = abs(float(highs[j]) - wmax) < 1e-9
                    if actual != dspec["high_max20"]:
                        violations.append({
                            "code": "HIGH_MAX20_MISMATCH",
                            "detail": f"{code}@{r[d0_col]} D{dspec['offset']}: 期望最高价{'为' if dspec['high_max20'] else '非'}20日最高, 复核={'为' if actual else '非'}"})
            # 涨跌幅口径抽验（2026-09-23 kk 裁定：20cm 生效日起；10cm 创业板反向门）
            if universe == "20cm":
                if code.startswith(("300", "301")) and dates[i] < GEM_20CM_DATE:
                    violations.append({"code": "BOARD_DATE_FILTER", "detail": f"{code}@{r[d0_col]}"})
                if code.startswith("688") and dates[i] < STAR_20CM_DATE:
                    violations.append({"code": "BOARD_DATE_FILTER", "detail": f"{code}@{r[d0_col]}"})
            elif universe == "10cm" and code.startswith(("300", "301")) \
                    and dates[i] >= GEM_20CM_DATE:
                violations.append({"code": "BOARD_DATE_FILTER", "detail": f"{code}@{r[d0_col]}"})
        if len(violations) > 50:
            break
    return violations


def latest_market_date():
    """扫描标准行情最新交易日（含文件数）。"""
    latest = 0
    count = 0
    for d in DAY_DIRS:
        p = Path(d)
        if not p.exists():
            continue
        for f in p.glob("*.day"):
            count += 1
            try:
                with open(f, "rb") as fh:
                    fh.seek(-32, 2)
                    import struct
                    dt = struct.unpack("<I", fh.read(4))[0]
                    latest = max(latest, int(dt))
            except Exception:
                continue
    return (fmt_date(latest) if latest else None), count


def data_latest_payload():
    latest, count = latest_market_date()
    import datetime
    today = datetime.date.today().strftime("%Y-%m-%d")
    stale = bool(latest and latest < today)
    return {"latest_date": latest, "today": today, "stale": stale, "file_count": count}
