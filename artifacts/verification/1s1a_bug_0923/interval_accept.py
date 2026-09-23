# -*- coding: utf-8 -*-
"""区间语义（方案A）落地验收：重识别 -> run_plan -> validate_rows -> 与 kk 参考逐键比对。

只读验收：不写库（store.save_success_result 不调用），结果落 artifacts/verification/1s1a_bug_0923/。
对照参考：0923(131) / 0921A(299) / 111A(722) / 111B(388)。
"""
import sys, io, json, time, pathlib, collections
sys.path.insert(0, 'app')
import pandas as pd
import recognizer, executor, store

ART = pathlib.Path('artifacts/verification/1s1a_bug_0923')
BUFS = []
BUF = io.StringIO()


def p(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    print(s, file=BUF)


CASES = [
    ("strategy_c1790145091328_r1_v1", r"D:\09work\0923_backtest\0923_backtest.xlsx", "0923"),
    ("strategy_10cm_v6", r"D:\09work\0921A_backtest\0921A_backtest.xlsx", "0921A"),
    ("strategy_f120ccad35_v1", r"D:\09work\0921A_backtest\0921A_backtest.xlsx", "0921A"),
    ("strategy_676e25bb91_v1", r"D:\09work\0921A_backtest\0921A_backtest.xlsx", "0921A"),
    ("strategy_99b11761e0_v1", r"D:\09work\0921A_backtest\0921A_backtest.xlsx", "0921A"),
    ("strategy_13b34ebf3a_v1", None, "（无对照）"),
]


def board(code):
    c = str(code).zfill(6)
    if c.startswith(("688", "689")):
        return "688科创"
    if c.startswith(("300", "301")):
        return "300创业"
    if c.startswith("60"):
        return "60沪主板"
    if c.startswith("00"):
        return "00深主板"
    return "其他" + c[:2]


def norm(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip()
    if s in ("nan", "NaN", "None"):
        return ""
    try:
        f = float(s)
        if f == int(f):
            return str(int(f))
    except Exception:
        pass
    return s


state = store.load_state()
latest = executor.data_latest_payload()["latest_date"]
p(f"### 区间语义落地验收   行情最新日={latest}")
p("")

summary_rows = []
for stem, ref_path, ref_tag in CASES:
    m = state["models"].get(stem)
    p("=" * 96)
    if m is None:
        p(f"### {stem}: 库中不存在，跳过")
        continue
    rt = m.get("rule_text") or ""
    before_n = (m.get("current_result") or {}).get("n_hits")
    plan, summ, problems = recognizer.parse_single_rule(rt)
    if problems:
        p(f"### {stem}: 识别失败 {json.dumps(problems, ensure_ascii=False)}")
        continue
    sp = plan["strategy_plan"]
    p(f"### {stem}  对照={ref_tag}  原结果={before_n} 行")
    p(f"    ranges={json.dumps(sp.get('ranges'), ensure_ascii=False)}")
    t0 = time.time()
    rows, columns, meta = executor.run_plan(plan, end_date=latest)
    el = time.time() - t0
    viol = executor.validate_rows(plan, rows, columns)
    p(f"    新区间语义结果: {len(rows)} 行  标本={meta['n_stocks']}  耗时 {el:.1f}s  "
      f"复核违例={len(viol)}")
    if viol:
        p(f"    !! 违例前 5: {json.dumps(viol[:5], ensure_ascii=False)}")
    ca = collections.Counter(board(r["股票代码"]) for r in rows)
    p(f"    板块分布: {dict(sorted(ca.items()))}")
    xa = collections.Counter(r.get("x") for r in rows)
    p(f"    x 分布  : {dict(sorted(xa.items(), key=lambda t: (t[0] is None, t[0])))}")
    pd.DataFrame(rows).to_excel(ART / f"new_{stem}.xlsx", index=False)

    rec = {"stem": stem, "ref": ref_tag, "before": before_n, "after": len(rows),
           "violations": len(viol), "elapsed_s": round(el, 1),
           "boards": dict(ca)}
    if ref_path:
        ref = pd.read_excel(ref_path, dtype=str)
        kcol_a = next(c for c in columns if c.endswith("日期"))
        kcol_b = next(c for c in ref.columns if "日期" in c)
        A = pd.DataFrame(rows)
        A["_k"] = A["股票代码"].map(norm) + "@" + A[kcol_a].map(norm)
        ref["_k"] = ref["股票代码"].map(norm) + "@" + ref[kcol_b].map(norm)
        sa, sb = set(A["_k"]), set(ref["_k"])
        onlyA, onlyB, both = sorted(sa - sb), sorted(sb - sa), sorted(sa & sb)
        p(f"    参考 {ref_tag}: {len(ref)} 行 | 共同={len(both)} 仅新区间={len(onlyA)} "
          f"仅参考={len(onlyB)}")
        p(f"      仅新区间 板块: {dict(sorted(collections.Counter(board(k.split('@')[0]) for k in onlyA).items()))}")
        p(f"      仅参考   板块: {dict(sorted(collections.Counter(board(k.split('@')[0]) for k in onlyB).items()))}")
        common_cols = [c for c in columns if c in ref.columns
                       and c not in (kcol_a, "股票名称", "股票代码")]
        ai = A.set_index("_k")
        bi = ref.set_index("_k")
        dc = collections.Counter()
        samples = []
        for k in both:
            ra, rb = ai.loc[k], bi.loc[k]
            for c in common_cols:
                va, vb = norm(ra[c]), norm(rb[c])
                if va != vb:
                    dc[c] += 1
                    if len(samples) < 25:
                        samples.append(f"        {k} [{c}] 新={va!r} 参考={vb!r}")
        p(f"    共同行字段差异计数: {dict(dc)}  (比对列 {len(common_cols)} 个)")
        for s in samples:
            p(s)
        rec.update({"ref_rows": len(ref), "both": len(both),
                    "only_new": len(onlyA), "only_ref": len(onlyB),
                    "field_diff": dict(dc)})
        # 603156 专项
        for tag, df in (("新", A), ("参考", ref)):
            sub = df[df["股票代码"].map(norm).str.zfill(6) == "603156"]
            p(f"    603156 {tag}: {len(sub)} 行"
              + ("" if len(sub) == 0 else "  -> " + " | ".join(
                  f"{kcol_a}={norm(r[kcol_a])} x={norm(r.get('x'))}" for _, r in sub.iterrows())))
    summary_rows.append(rec)

p("")
p("=" * 96)
p("### 汇总")
p(json.dumps(summary_rows, ensure_ascii=False, indent=2))
ART.joinpath("interval_accept.txt").write_text(BUF.getvalue(), encoding="utf-8")
ART.joinpath("interval_accept.json").write_text(
    json.dumps(summary_rows, ensure_ascii=False, indent=2), encoding="utf-8")
print("\n-> interval_accept.txt / .json / new_*.xlsx 已落盘")
