# -*- coding: utf-8 -*-
"""与 kk 参考的严格等价核验：区分「数值真差异」/「仅符号或格式差异」/「一边为空（数据边界）」。"""
import sys, io
sys.path.insert(0, 'app')
import pandas as pd

BUF = io.StringIO()


def p(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    print(s, file=BUF)


def num(v):
    s = str(v).strip().replace('%', '').replace('+', '')
    if s in ('', 'nan', 'N/A', 'None'):
        return None
    try:
        return float(s)
    except Exception:
        return None


def cmp(new_path, ref_path, tag):
    A = pd.read_excel(new_path, dtype=str)
    B = pd.read_excel(ref_path, dtype=str)
    ka = next(c for c in A.columns if c.endswith('日期'))
    kb = next(c for c in B.columns if '日期' in c)
    A['_k'] = A['股票代码'].astype(str).str.zfill(6) + '@' + A[ka].astype(str).str.strip()
    B['_k'] = B['股票代码'].astype(str).str.zfill(6) + '@' + B[kb].astype(str).str.strip()
    both = sorted(set(A['_k']) & set(B['_k']))
    ai, bi = A.set_index('_k'), B.set_index('_k')
    cols = [c for c in A.columns
            if c in B.columns and c not in (ka, '股票代码', '股票名称', '_k')]
    p(f"  [{tag}] 新 {len(A)} 行 / 参考 {len(B)} 行 / 共同 {len(both)} 行 / 比对列 {len(cols)}")
    real, sign, empty = {}, {}, {}
    for c in cols:
        for k in both:
            va, vb = str(ai.loc[k, c]).strip(), str(bi.loc[k, c]).strip()
            if va == vb:
                continue
            na, nb = num(va), num(vb)
            if na is not None and nb is not None:
                if abs(na - nb) < 1e-9:
                    sign[c] = sign.get(c, 0) + 1
                else:
                    real[c] = real.get(c, 0) + 1
                    if real[c] <= 3:
                        p(f"      !! 数值差异 {k} [{c}] 新={va!r} 参考={vb!r}")
            elif (va == '') or (vb == ''):
                empty[c] = empty.get(c, 0) + 1
            else:
                real[c] = real.get(c, 0) + 1
                if real[c] <= 3:
                    p(f"      !! 文本差异 {k} [{c}] 新={va!r} 参考={vb!r}")
    for c, v in sign.items():
        p(f"      仅「+」号/百分号格式差异（数值相同）: {c} x{v}")
    for c, v in empty.items():
        p(f"      一边为空（09-23 之后数据边界）: {c} x{v}")
    p(f"      数值真差异: {real if real else '无'}")
    p("")


cmp('artifacts/verification/1s1a_bug_0923/new_strategy_c1790145091328_r1_v1.xlsx',
    r'D:/09work/0923_backtest/0923_backtest.xlsx', '1S1A vs 0923')
cmp('artifacts/verification/1s1a_bug_0923/new_strategy_10cm_v6.xlsx',
    r'D:/09work/0921A_backtest/0921A_backtest.xlsx', '10cm_v6 vs 0921A')
cmp('artifacts/verification/1s1a_bug_0923/new_strategy_f120ccad35_v1.xlsx',
    r'D:/09work/0921A_backtest/0921A_backtest.xlsx', 'f120ccad35 vs 0921A')
open('artifacts/verification/1s1a_bug_0923/numeric_equivalence.txt', 'w',
     encoding='utf-8').write(BUF.getvalue())
print("-> numeric_equivalence.txt 已落盘")
