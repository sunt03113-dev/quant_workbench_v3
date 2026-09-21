# -*- coding: utf-8 -*-
"""P9 比对器自校验（正向 + 负向 + 输入门禁）。

比对器只在一处正例上返回 PASS 是没有说服力的：必须证明它**能**报出差异，
也要证明输入不一致时它会 ABORT 而不是给出假 PASS。

三个用例：
  T1 正向：证据 vs 自身副本            -> 期望 PASS（canonical diff = 0）
  T2 负向：篡改副本中一行业务结果      -> 期望 FAIL 且定位到该规则
  T3 门禁：篡改副本的行情包 tree_hash  -> 期望 ABORT（输入不一致，业务 diff 无意义）

用法：
  python app/p9_selfcheck.py [--label win]
产出：
  artifacts/verification/p9/P9_SELFCHECK.json
"""
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
P9 = ROOT / "artifacts" / "verification" / "p9"
PY = sys.executable


def run_compare(left, right):
    """返回 (verdict, doc, returncode)"""
    r = subprocess.run([PY, "-X", "utf8", str(ROOT / "app" / "p9_compare.py"),
                        "--left", left, "--right", right],
                       capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT))
    doc_p = P9 / f"P9_COMPARE_{left}_{right}.json"
    doc = json.loads(doc_p.read_text(encoding="utf-8")) if doc_p.exists() else None
    return (doc or {}).get("verdict"), doc, r.returncode


def _first_rule_with_rows(doc):
    for r in doc["rules"]:
        if r.get("canonical_rows"):
            return r
    return None


def main():
    label = "win"
    args = sys.argv[1:]
    if "--label" in args:
        label = args[args.index("--label") + 1]

    src = P9 / label
    if not (src / "P0_win_CANONICAL.json").exists() and not list(src.glob("P0_*_CANONICAL.json")):
        print(f"[selfcheck] 缺少 {label} 证据，先运行 p9_evidence.py collect --label {label}")
        return 2

    work = P9 / f"{label}_selfcheck"
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(src, work)

    report = {"schema": "p9-selfcheck/1", "label": label, "cases": []}

    # ── T1 正向 ──
    v, doc, rc = run_compare(label, f"{label}_selfcheck")
    t1_ok = v == "PASS"
    report["cases"].append({
        "id": "T1", "name": "正向：同源证据自比对",
        "expect": "PASS", "actual": v, "ok": t1_ok,
        "canonical_diff": (doc or {}).get("outputs", {}).get("canonical_diff"),
        "n_rules_compared": (doc or {}).get("outputs", {}).get("n_rules_compared"),
    })
    print(f"[selfcheck] T1 expect=PASS actual={v} ok={t1_ok}")

    # ── T2 负向：篡改一行 ──
    cp = sorted(work.glob("P0_*_CANONICAL.json"))[0]
    d = json.loads(cp.read_text(encoding="utf-8"))
    rule = _first_rule_with_rows(d)
    tampered = None
    if rule:
        lines = rule["canonical_rows"]
        if len(lines) > 1:
            lines.pop()                      # 删一行 -> 行集合必不同
            tampered = {"rule": rule["rule"], "action": "drop_last_row",
                        "n_rows": rule["n_rows"], "rows_after": len(lines)}
        else:
            lines[0] = lines[0] + "|TAMPERED"
            tampered = {"rule": rule["rule"], "action": "mutate_row"}
        # 关键：重算行哈希，模拟"另一端真实产出的不同结果"（保持证据自洽）
        lines.sort()
        rule["n_rows"] = len(lines)
        rule["rows_sha256"] = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
        cp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    v2, doc2, rc2 = run_compare(label, f"{label}_selfcheck")
    t2_ok = v2 == "FAIL"
    hit = None
    if doc2:
        for r in doc2["outputs"]["rules"]:
            if r.get("equal") is False:
                hit = {"rule": r["rule"], "n_only_left": (r.get("diff") or [{}])[0].get("n_only_left"),
                       "n_only_right": (r.get("diff") or [{}])[0].get("n_only_right")}
                break
    report["cases"].append({
        "id": "T2", "name": "负向：篡改一行业务结果",
        "expect": "FAIL", "actual": v2, "ok": t2_ok,
        "tamper": tampered, "located": hit,
        "canonical_diff": (doc2 or {}).get("outputs", {}).get("canonical_diff"),
    })
    print(f"[selfcheck] T2 expect=FAIL actual={v2} ok={t2_ok} located={hit}")

    # ── T3 门禁：篡改输入资产哈希 ──
    ip = sorted(work.glob("INPUTS_*.json"))[0]
    di = json.loads(ip.read_text(encoding="utf-8"))
    orig = di["assets"]["market_pack"]["tree_hash"]
    di["assets"]["market_pack"]["tree_hash"] = "0" * 64
    ip.write_text(json.dumps(di, ensure_ascii=False, indent=1), encoding="utf-8")
    v3, doc3, rc3 = run_compare(label, f"{label}_selfcheck")
    t3_ok = v3 == "ABORT"
    report["cases"].append({
        "id": "T3", "name": "门禁：输入资产哈希不一致",
        "expect": "ABORT", "actual": v3, "ok": t3_ok,
        "tampered_asset": "market_pack",
        "orig_tree_hash": orig,
        "gate": (doc3 or {}).get("inputs", {}).get("gate"),
    })
    print(f"[selfcheck] T3 expect=ABORT actual={v3} ok={t3_ok}")

    all_ok = all(c["ok"] for c in report["cases"])
    report["all_ok"] = all_ok
    report["conclusion"] = (
        "比对器可用：能对同源证据判 PASS、能报出业务差异并定位、能在输入不一致时 ABORT"
        if all_ok else "比对器自校验未通过，结论不可信，须修复后重跑")
    (P9 / "P9_SELFCHECK.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    shutil.rmtree(work, ignore_errors=True)
    for n in ("P9_COMPARE_win_win_selfcheck.json",):
        p = P9 / n
        if p.exists():
            p.unlink()
    print(f"[selfcheck] ALL_OK={all_ok}")
    print(f"[selfcheck] -> {P9 / 'P9_SELFCHECK.json'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
