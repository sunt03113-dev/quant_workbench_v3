# -*- coding: utf-8 -*-
"""1S1A（strategy_c1790145091328_r1_v1）结果独立验证。
三道检查：
  A. 引擎复核 validate_rows（计划一致性，逐行逐条件）
  B. 不依赖引擎的独立复算：vipdoc .day 原始行情 → 涨停(strict==)/20日滚动最大 → 逐条件核对 3 行样本
  C. 桌面 xlsx（用户下载的 1S1A_回测结果.xlsx）与引擎 current.xlsx 逐位比对
"""
import json
import struct
import sys
from pathlib import Path

ROOT = Path(r"D:\09work\quant_workbench_v3\quant_workbench_package")
sys.path.insert(0, str(ROOT / "app"))

import pandas as pd  # noqa: E402
import executor  # noqa: E402
from paths import RESULTS_DIR, STATE_FILE  # noqa: E402
import store  # noqa: E402

STEM = "strategy_c1790145091328_r1_v1"
OUT = []
def log(s):
    OUT.append(str(s)); print(s)

# ── 载入模型与结果 ──────────────────────────────────────────
st = json.loads(STATE_FILE.read_text(encoding="utf-8"))
m = st["models"][STEM]
plan = m["plan"]
cur = RESULTS_DIR / STEM / "current.xlsx"
df = pd.read_excel(cur, dtype=str)
log(f"[load] current.xlsx rows={len(df)} data_date={(m.get('current_result') or {}).get('data_date')}")
log(f"[load] columns={list(df.columns)}")

# ── A. 引擎复核 ────────────────────────────────────────────
rows_a = df.to_dict("records")
for r in rows_a:  # x 列还原为 int（Excel 读出为字符串会导致校验器误判类型）
    r["x"] = int(float(r["x"]))
viol = executor.validate_rows(plan, rows_a, list(df.columns))
log(f"[A] engine validate_rows violations = {len(viol)}")
for v in viol[:5]:
    log(f"    {v}")

# ── B. 独立复算（vipdoc 原始 .day）─────────────────────────
def read_day(code6):
    for mkt in ("sh", "sz"):
        p = ROOT / "appdata" / "market" / "vipdoc" / mkt / "lday" / f"{mkt}{code6}.day"
        if p.exists():
            recs = []
            with open(p, "rb") as fh:
                while True:
                    b = fh.read(32)
                    if len(b) < 32:
                        break
                    d = struct.unpack("<I", b[:4])[0]
                    o, h, l, c = (v / 100.0 for v in struct.unpack("<IIII", b[4:20]))
                    amt = struct.unpack("<f", b[20:24])[0]
                    recs.append((d, o, c, h, l, amt))
            return mkt, recs
    return None, None

def limit_price(prev_close, code6):
    # 10cm 池：主板 10%；创业板 300/301 仅 2020-08-24 前 10%（本行日期均在 2026，10%）
    return round(prev_close * 1.10, 2)

def check_row(code6, d0_date, x):
    mkt, recs = read_day(code6)
    assert recs, f"{code6} .day not found"
    dates = [r[0] for r in recs]
    opens = [r[1] for r in recs]
    closes = [r[2] for r in recs]
    highs = [r[3] for r in recs]
    amts = [r[5] for r in recs]
    d0_int = int(d0_date.replace("-", ""))
    j0 = dates.index(d0_int)
    # 20 日滚动最大（窗口含当日，与前 19 日），j<19 不判定（引擎同口径）
    def roll_max(arr, j):
        return max(arr[j - 19:j + 1]) if j >= 19 else None
    fails = []
    def cond(tag, j, want_limit, want_amtmax, want_highmax):
        ok = True
        if want_limit is not None:
            actual = closes[j] == limit_price(closes[j - 1], code6)
            if actual != want_limit:
                ok = False; fails.append(f"{tag} 涨停期望{want_limit}实得{actual}(close={closes[j]},prev={closes[j-1]})")
        if want_amtmax is not None and j >= 19:
            actual = amts[j] == roll_max(amts, j)
            if actual != want_amtmax:
                ok = False; fails.append(f"{tag} 额20日最大期望{want_amtmax}实得{actual}")
        if want_highmax is not None and j >= 19:
            actual = highs[j] == roll_max(highs, j)
            if actual != want_highmax:
                ok = False; fails.append(f"{tag} 高20日最大期望{want_highmax}实得{actual}")
        return ok
    # D-0 / D-1
    cond("D-0", j0, True, True, True)
    cond("D-1", j0 - 1, False, False, False)
    # D-x, D-(x+1), D-(x+2), D-(x+3), D-(x+4)
    cond("D-x", j0 - x, False, False, False)
    cond("D-(x+1)", j0 - x - 1, False, True, True)
    cond("D-(x+2)", j0 - x - 2, True, True, True)
    cond("D-(x+3)", j0 - x - 3, False, False, None)
    cond("D-(x+4)", j0 - x - 4, False, False, None)
    return fails

# 抽 3 行：首行、中间行、末行（覆盖不同 x 值）
xs = df["x"].tolist() if "x" in df.columns else None
xcol = [c for c in df.columns if c.strip() == "x"][0]
codecol = [c for c in df.columns if "代码" in c][0]
datecol = [c for c in df.columns if c.strip() == "D-0日期" or ("日期" in c and "D-0" in c)][0]
idxs = [0, len(df) // 2, len(df) - 1]
for i in idxs:
    row = df.iloc[i]
    code6 = str(row[codecol]).split(".")[0].zfill(6)
    x = int(float(row[xcol]))
    d0 = str(row[datecol])
    fails = check_row(code6, d0, x)
    log(f"[B] row{i} {code6} D-0={d0} x={x} -> {'OK' if not fails else 'FAIL ' + '; '.join(fails)}")

# ── C. 桌面 xlsx 比对 ──────────────────────────────────────
desk = Path(r"C:\Users\21412\Desktop\temp仅0827\1S1A_回测结果.xlsx")
if desk.exists():
    dx = pd.read_excel(desk, dtype=str)
    same_shape = dx.shape == df.shape
    same_cols = list(dx.columns) == list(df.columns)
    if same_shape and same_cols:
        diff = 0
        for c in df.columns:
            a = dx[c].fillna("N/A").astype(str)
            b = df[c].fillna("N/A").astype(str)
            diff += int((a != b).sum())
        log(f"[C] desktop xlsx rows={dx.shape} shape_match={same_shape} cols_match={same_cols} cell_diffs={diff}")
    else:
        log(f"[C] desktop xlsx shape={dx.shape} vs engine {df.shape}; cols_match={same_cols}")
        log(f"    desk cols={list(dx.columns)[:8]}...")
else:
    log("[C] desktop xlsx not found")

Path(r"D:\09work\quant_workbench_v3\quant_workbench_package\artifacts\verification\1s1a_check\verify_out.txt").write_text("\n".join(OUT) + "\n", encoding="utf-8")
