# -*- coding: utf-8 -*-
"""P9 跨平台一致性判定器（Windows <-> Apple Silicon M4）。

读取两端由 p9_evidence.py 采集的证据包，按 ACCEPTANCE.md 判据输出结论：

  跨平台 PASS 条件
    (1) 输入资产哈希一致：Skill / Golden / 固定测试行情包 / 名称缓存
        —— 行清单根哈希必须完全相同，否则两端跑的就不是同一套东西，判定 ABORT。
    (2) 业务输出 canonical diff = 0：逐规则比较列集合与量化后的行集合。
    (3) Excel 二进制哈希**不参与** PASS/FAIL（元数据易变），单独记录差异；
        另比对其同源结构化结果的 canonical 行哈希。

用法：
  python app/p9_compare.py --left win --right mac
  python app/p9_compare.py --left win --right win      # 同端自比对（工具自校验）
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
P9 = ROOT / "artifacts" / "verification" / "p9"

REQUIRED_ASSETS = ["skill", "golden", "market_pack", "stock_names"]


def load(label):
    """按目录内容自描述加载（文件名中的 label 不参与匹配，便于回传后重命名目录）。"""
    d = P9 / label
    if not d.exists():
        return None

    def _j(patterns):
        for pat in patterns:
            fs = sorted(d.glob(pat))
            if fs:
                return json.loads(fs[0].read_text(encoding="utf-8"))
        return None

    return {
        "dir": d,
        "env": _j(["ENV_*.json"]),
        "inputs": _j(["INPUTS_*.json"]),
        "p0": _j(["P0_*_CANONICAL.json"]),
        "verdicts": _j(["P0_*_VERDICTS.json"]),
        "excel": _j(["EXCEL_*.json"]),
        "manifest_files": sorted(p.name for p in d.glob("*.manifest.txt")),
    }


def _asset_fingerprint(inputs, key):
    a = (inputs or {}).get("assets", {}).get(key)
    if not a:
        return None
    if key == "stock_names":
        return {"sha256": a.get("sha256"), "size": a.get("size"), "exists": a.get("exists")}
    return {"tree_hash": a.get("tree_hash"), "n_files": a.get("n_files"),
            "total_bytes": a.get("total_bytes"), "exists": a.get("exists")}


def compare_inputs(L, R):
    res = {"assets": {}, "all_identical": True, "gate": "PASS"}
    for key in REQUIRED_ASSETS:
        fl = _asset_fingerprint(L["inputs"], key)
        fr = _asset_fingerprint(R["inputs"], key)
        if fl is None or fr is None:
            same = False
            reason = "缺少该资产的采集结果"
        else:
            same = fl == fr
            reason = "" if same else "指纹不一致"
        res["assets"][key] = {"left": fl, "right": fr, "identical": same, "reason": reason}
        if not same:
            res["all_identical"] = False
    if not res["all_identical"]:
        res["gate"] = "ABORT"
        res["note"] = ("输入资产不一致：两端不是同一套 Skill/Golden/行情包，"
                       "业务 diff 无意义。必须先统一输入再判定。")
    return res


def _rule_map(p0):
    return {r["rule"]: r for r in (p0 or {}).get("rules", [])}


def check_integrity(p0, label):
    """证据自洽性门禁：rows_sha256 必须等于 canonical_rows 的规范化哈希，n_rows 必须等于行数。

    证据内部自相矛盾时（例如被手工编辑过），任何跨端结论都不可信。
    """
    problems = []
    for r in (p0 or {}).get("rules", []):
        lines = r.get("canonical_rows")
        if lines is None:
            continue
        if r.get("n_rows") != len(lines):
            problems.append({"rule": r["rule"], "issue": "n_rows_mismatch",
                             "declared": r.get("n_rows"), "actual": len(lines)})
        h = r.get("rows_sha256")
        if h is None and not lines:
            continue
        calc = hashlib.sha256("\n".join(sorted(lines)).encode("utf-8")).hexdigest()
        if h != calc:
            problems.append({"rule": r["rule"], "issue": "rows_sha256_mismatch",
                             "declared": h, "recomputed": calc})
    return {"label": label, "ok": not problems, "n_problems": len(problems),
            "problems": problems[:10]}


def compare_outputs(L, R):
    ml, mr = _rule_map(L["p0"]), _rule_map(R["p0"])
    only_l = sorted(set(ml) - set(mr))
    only_r = sorted(set(mr) - set(ml))
    rules = []
    n_diff = 0
    for name in sorted(set(ml) & set(mr)):
        a, b = ml[name], mr[name]
        cols_eq = a.get("columns") == b.get("columns")
        ra, rb = a.get("rows_sha256"), b.get("rows_sha256")
        if ra is None and rb is None:
            # 能力缺口 / 未产出结果：两端都无行集合，视为一致（由 verdict 与 n_rows 佐证）
            rows_eq = a.get("n_rows") == b.get("n_rows")
            rows_state = "no_rows_both"
        elif ra is None or rb is None:
            rows_eq = False
            rows_state = "one_side_missing"
        else:
            rows_eq = ra == rb
            rows_state = "computed"
        n_eq = a.get("n_rows") == b.get("n_rows")
        v_eq = a.get("verdict") == b.get("verdict")
        diff_rows = []
        if not rows_eq and a.get("canonical_rows") is not None \
                and b.get("canonical_rows") is not None:
            sa, sb = set(a["canonical_rows"]), set(b["canonical_rows"])
            diff_rows = [{"only_left": sorted(sa - sb)[:10],
                          "only_right": sorted(sb - sa)[:10],
                          "n_only_left": len(sa - sb), "n_only_right": len(sb - sa)}]
        entry = {"rule": name, "columns_equal": cols_eq, "rows_equal": rows_eq,
                 "rows_state": rows_state, "n_rows_equal": n_eq, "verdict_equal": v_eq,
                 "left": {"verdict": a.get("verdict"), "n_rows": a.get("n_rows"),
                          "rows_sha256": a.get("rows_sha256"),
                          "columns": a.get("columns")},
                 "right": {"verdict": b.get("verdict"), "n_rows": b.get("n_rows"),
                           "rows_sha256": b.get("rows_sha256"),
                           "columns": b.get("columns")}}
        ok = cols_eq and rows_eq and n_eq
        entry["equal"] = ok
        if not ok:
            n_diff += 1
            entry["diff"] = diff_rows
            if not cols_eq:
                entry["column_diff"] = {"left": a.get("columns"), "right": b.get("columns")}
        rules.append(entry)
    return {"rules": rules, "n_rules_compared": len(rules), "n_rules_differing": n_diff,
            "rules_only_left": only_l, "rules_only_right": only_r,
            "canonical_diff": n_diff, "gate": "PASS" if n_diff == 0 and not only_l and not only_r
            else "FAIL"}


def compare_excel(L, R):
    el, er = L.get("excel"), R.get("excel")
    if not el or not er:
        return {"gate": "SKIPPED", "note": "至少一端未采集 Excel 证据"}
    if el.get("skipped") or er.get("skipped"):
        return {"gate": "SKIPPED", "note": "至少一端后端不可达，未能产出 Excel",
                "left_reason": el.get("reason"), "right_reason": er.get("reason")}
    return {
        "gate": "INFO",
        "note": "Excel 二进制哈希不参与 PASS/FAIL（容器元数据/时间戳易变），仅记录",
        "binary_sha256": {"left": el.get("excel_sha256"), "right": er.get("excel_sha256"),
                          "identical": el.get("excel_sha256") == er.get("excel_sha256")},
        "bytes": {"left": el.get("excel_bytes"), "right": er.get("excel_bytes"),
                  "identical": el.get("excel_bytes") == er.get("excel_bytes")},
        "structured_rows_sha256": {
            "left": el.get("structured_rows_sha256"),
            "right": er.get("structured_rows_sha256"),
            "identical": el.get("structured_rows_sha256") == er.get("structured_rows_sha256"),
        },
        "structured_n_rows": {"left": el.get("structured_n_rows"),
                              "right": er.get("structured_n_rows")},
        "n_hits": {"left": el.get("n_hits"), "right": er.get("n_hits")},
        "data_date": {"left": el.get("data_date"), "right": er.get("data_date")},
    }


def compare_runtime(L, R):
    el, er = (L["env"] or {}), (R["env"] or {})
    pl, pr = el.get("packages", {}), er.get("packages", {})
    keys = sorted(set(pl) | set(pr))
    pkgs = {k: {"left": pl.get(k), "right": pr.get(k), "identical": pl.get(k) == pr.get(k)}
            for k in keys}
    return {
        "platform": {
            "left": {k: (el.get("host") or {}).get(k) for k in ("system", "machine", "release")},
            "right": {k: (er.get("host") or {}).get(k) for k in ("system", "machine", "release")},
        },
        "python": {"left": (el.get("python") or {}).get("version"),
                   "right": (er.get("python") or {}).get("version"),
                   "identical": (el.get("python") or {}).get("version")
                   == (er.get("python") or {}).get("version")},
        "packages": pkgs,
        "packages_all_identical": all(v["identical"] for v in pkgs.values()),
        "canon_rule_identical": el.get("canon_rule") == er.get("canon_rule"),
        "schema_identical": el.get("schema") == er.get("schema"),
        "note": ("依赖版本不同不直接判 FAIL，但若业务 diff 非 0 必须先排除版本因素"
                 "（数值库舍入/排序实现差异）。"),
    }


def main():
    args = sys.argv[1:]
    left = args[args.index("--left") + 1] if "--left" in args else "win"
    right = args[args.index("--right") + 1] if "--right" in args else "mac"

    L, R = load(left), load(right)
    missing = [k for k, v in ((left, L), (right, R)) if v is None or v["p0"] is None or v["inputs"] is None]
    if missing:
        print(f"[p9] 证据不完整，缺少端: {missing}")
        for lab in missing:
            d = P9 / lab
            print(f"      期望目录: {d}")
        print(f"      请先在该端运行: python app/p9_evidence.py collect --label {missing[0]}")
        return 2

    doc = {
        "schema": "p9-compare/1",
        "compared_at": __import__("time").strftime("%Y-%m-%dT%H:%M:%S"),
        "left_label": left, "right_label": right,
        "integrity": {"left": check_integrity(L["p0"], left),
                      "right": check_integrity(R["p0"], right)},
        "runtime": compare_runtime(L, R),
        "inputs": compare_inputs(L, R),
        "outputs": compare_outputs(L, R),
        "excel": compare_excel(L, R),
    }

    # 顶层判定
    integ_bad = [k for k, v in doc["integrity"].items() if not v["ok"]]
    if integ_bad:
        doc["verdict"] = "EVIDENCE_INCONSISTENT"
        doc["verdict_reason"] = (f"证据自相矛盾（{integ_bad}）：行哈希与行集合不匹配，"
                                 "需重新采集后再判定")
    elif doc["inputs"]["gate"] == "ABORT":
        doc["verdict"] = "ABORT"
        doc["verdict_reason"] = "输入资产不一致，两端不可比（先统一 Skill/Golden/行情包）"
    elif doc["outputs"]["gate"] != "PASS":
        doc["verdict"] = "FAIL"
        doc["verdict_reason"] = f"业务 canonical diff = {doc['outputs']['canonical_diff']}（应为 0）"
    elif not doc["runtime"]["canon_rule_identical"]:
        doc["verdict"] = "FAIL"
        doc["verdict_reason"] = "两端 canonical 规则不一致，结果不可比"
    else:
        doc["verdict"] = "PASS"
        doc["verdict_reason"] = "输入资产哈希一致 且 业务输出 canonical diff = 0"

    OUT = P9 / f"P9_COMPARE_{left}_{right}.json"
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")

    r = doc["outputs"]
    print(f"[p9] left={left} right={right}")
    print(f"[p9] integrity: left={doc['integrity']['left']['ok']} "
          f"right={doc['integrity']['right']['ok']}")
    print(f"[p9] inputs gate={doc['inputs']['gate']} all_identical={doc['inputs']['all_identical']}")
    print(f"[p9] outputs diff={r['canonical_diff']}/{r['n_rules_compared']} rules differing")
    print(f"[p9] excel={doc['excel']['gate']} "
          f"binary_identical={doc['excel'].get('binary_sha256', {}).get('identical')}")
    print(f"[p9] VERDICT = {doc['verdict']}  ({doc['verdict_reason']})")
    print(f"[p9] -> {OUT}")
    return 0 if doc["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
