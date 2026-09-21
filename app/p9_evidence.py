# -*- coding: utf-8 -*-
"""P9 跨平台一致性证据采集器（Windows <-> Apple Silicon M4）。

在**任一端**运行，产出可机器比对的证据包；两端证据由 p9_compare.py 判定。

采集内容（对齐 ACCEPTANCE.md「P9 Windows → M4 一致性」）：
  - 运行环境：OS/架构/Python/关键依赖版本、路径解析来源（paths.describe()）
  - 输入资产：Skill 目录、Golden（规则+结果表）、固定测试行情包（标准本地行情）、
              名称缓存 stock_names.csv  —— 逐文件 SHA-256 + 清单根哈希
  - 运行方式：命令、工作目录、入口
  - 业务输出：P0 全部规则的 canonical 结果（列集合 + 量化到 1e-4 的行集合 + 行集合哈希）
  - 结果 Excel：二进制 SHA-256（若本机后端可达）

canonical 规则（两端必须一致，否则判为不可比）：
  - 列集合：本实现输出列顺序
  - 值量化：数值统一为 Python float 后 round(4)，格式化 %.4f；去掉前导 '+'；-0.0 -> 0.0
  - 空值语义：None / NaN / "" / "N/A"/ "--" 统一为 "N/A"
  - 行序不敏感：行按规范化字符串排序后拼接

用法：
  python app/p9_evidence.py collect --label win
  python app/p9_evidence.py collect --label mac --skip-p0        # 只采环境+输入
  python app/p9_evidence.py collect --label win --skip-market    # 跳过行情包哈希（快速自检）
"""
import hashlib
import json
import math
import os
import platform
import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import paths  # noqa: E402

SCHEMA = "p9-evidence/1"
CANON_VERSION = 2
QUANT = 4  # canonical 数值精度（10^-4）
# 标识符/日期列：原样保留，不做数值量化（否则 '000001' -> '1.0000' 丢失前导零）
TEXT_COLUMNS = ("股票代码", "股票名称", "交易所", "板块")
TEXT_COLUMN_SUBSTR = ("日期",)
CANON_RULE = {
    "canon_version": CANON_VERSION,
    "value_quantum": 10 ** -QUANT,
    "format": f"%.{QUANT}f",
    "empty_tokens": ["", "N/A", "nan", "NaN", "None", "--"],
    "strip_leading_plus": True,
    "normalize_negative_zero": True,
    "leading_zero_guard": True,
    "text_columns": list(TEXT_COLUMNS),
    "text_column_substrings": list(TEXT_COLUMN_SUBSTR),
    "row_order": "sorted",
    "tree_hash_algo": "sha256 over sorted('relpath|sha256\\n')",
    "manifest_format": "relpath\\tsize\\tsha256",
}


# ─────────────────────── 基础工具 ───────────────────────

def sha256_file(p, buf_size=1 << 20):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(buf_size), b""):
            h.update(b)
    return h.hexdigest()


def rel_posix(p, base):
    return p.relative_to(base).as_posix()


def scan_tree(base, skip_names=(), exts=None):
    """返回 (entries, tree_hash)。entries: [{path,size,sha256}]，path 为相对 posix 路径。"""
    base = Path(base)
    entries = []
    if base.exists():
        for p in sorted(base.rglob("*")):
            if not p.is_file():
                continue
            rel = rel_posix(p, base)
            if any(s in p.parts for s in skip_names):
                continue
            if exts and p.suffix.lower() not in exts:
                continue
            entries.append({"path": rel, "size": p.stat().st_size, "sha256": sha256_file(p)})
    h = hashlib.sha256()
    for e in sorted(entries, key=lambda x: x["path"]):
        h.update(f"{e['path']}|{e['sha256']}\n".encode("utf-8"))
    return entries, h.hexdigest()


def write_manifest(path, entries):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        for e in sorted(entries, key=lambda x: x["path"]):
            f.write(f"{e['path']}\t{e['size']}\t{e['sha256']}\n")
    return path


def pkg_versions(names):
    import importlib.metadata as md
    out = {}
    for n in names:
        try:
            out[n] = md.version(n)
        except Exception:  # noqa: BLE001
            out[n] = None
    return out


def market_index_last_trade_date(vipdoc):
    """上证指数最后交易日（判断行情包完整性）。"""
    p = Path(vipdoc) / "sh" / "lday" / "sh000001.day"
    if not p.exists():
        return None
    b = p.read_bytes()
    n = len(b) // 32
    if n == 0:
        return None
    d = struct.unpack("<I", b[(n - 1) * 32:(n - 1) * 32 + 4])[0]
    return f"{d // 10000:04d}-{d // 100 % 100:02d}-{d % 100:02d}"


# ─────────────────────── canonical 化 ───────────────────────

_EMPTY = set(CANON_RULE["empty_tokens"])


def is_text_column(col):
    return col in TEXT_COLUMNS or any(s in col for s in TEXT_COLUMN_SUBSTR)


def canon_scalar(v, text=False):
    if v is None:
        return "N/A"
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return "N/A"
    s = str(v).strip()
    if s in _EMPTY:
        return "N/A"
    if text:
        return s
    # 前导零保护：'000001' 这类是标识符而非数量，原样保留
    if len(s) > 1 and s[0] == "0" and s[1:].isdigit():
        return s
    pct = ""
    body = s
    if body.endswith("%"):
        pct, body = "%", body[:-1]
    if body.startswith("+"):
        body = body[1:]
    try:
        f = float(body)
    except ValueError:
        return s
    q = round(f, QUANT)
    if q == 0:
        q = 0.0
    return f"{q:.{QUANT}f}{pct}"


def canon_rows(rows, columns):
    """rows: list[dict] -> (canon_lines_sorted, sha256, n_rows)"""
    flags = [is_text_column(c) for c in columns]
    lines = []
    for r in rows:
        lines.append("|".join(canon_scalar(r.get(c), t) for c, t in zip(columns, flags)))
    lines.sort()
    blob = "\n".join(lines)
    return lines, hashlib.sha256(blob.encode("utf-8")).hexdigest(), len(lines)


# ─────────────────────── 采集阶段 ───────────────────────

def stage_environment(label):
    import numpy
    import pandas
    return {
        "schema": SCHEMA,
        "label": label,
        "collected_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "host": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "node": platform.node(),
            "stdlib_platform": sys.platform,
        },
        "python": {
            "version": sys.version.split()[0],
            "executable": sys.executable,
            "implementation": platform.python_implementation(),
            "byteorder": sys.byteorder,
        },
        "packages": pkg_versions([
            "numpy", "pandas", "openpyxl", "fastapi", "uvicorn", "starlette",
            "pydantic", "PyYAML", "xlsxwriter", "python-dateutil", "pytz",
        ]),
        "runtime_versions": {"numpy": numpy.__version__, "pandas": pandas.__version__},
        "paths": paths.describe(),
        "canon_rule": CANON_RULE,
    }


def stage_inputs(OUT, label, skip_market=False):
    res = {"schema": SCHEMA, "label": label,
           "collected_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "assets": {}}

    scopes = [
        ("skill", paths.SKILL_DIR,
         {"label": "tdx-stock-backtest Skill（冻结业务定义）",
          "role": "business-authority", "skip": ("__pycache__", ".git")}),
        ("golden", ROOT / "golden",
         {"label": "Golden：固定自然语言规则 + 期望结果表",
          "role": "expected-output",
          "skip": ("vipdoc",), "exts": {".txt", ".csv", ".xlsx"}}),
    ]
    if not skip_market:
        scopes.append(("market_pack", paths.VIPDOC_DIR,
                       {"label": "固定测试行情包（标准本地行情，TDX .day 兼容）",
                        "role": "input-market", "skip": (), "exts": {".day"}}))

    for name, base, meta in scopes:
        t0 = time.time()
        entries, th = scan_tree(base, skip_names=meta.get("skip", ()),
                                exts=meta.get("exts"))
        mpath = write_manifest(OUT / f"INPUT_{label}_{name}.manifest.txt", entries)
        asset = {
            "label": meta["label"], "role": meta["role"], "root": str(base),
            "exists": Path(base).exists(),
            "n_files": len(entries),
            "total_bytes": sum(e["size"] for e in entries),
            "tree_hash": th,
            "manifest_file": mpath.name,
            "n_files_scanned": len(entries),
            "elapsed_sec": round(time.time() - t0, 1),
        }
        if name == "market_pack":
            by = {}
            for e in entries:
                parts = e["path"].split("/")
                key = parts[0] if len(parts) > 1 else "_"
                by[key] = by.get(key, 0) + 1
            asset["by_market"] = by
            asset["index_last_trade_date"] = market_index_last_trade_date(base)
            asset["schema_version"] = paths.MARKET_SCHEMA_VERSION
            asset["schema_fields"] = paths.MARKET_SCHEMA_FIELDS
            asset["physical_format"] = paths.MARKET_PHYSICAL_FORMAT
        res["assets"][name] = asset

    # 名称缓存单独列出（影响输出「股票名称」列）
    nf = paths.STOCK_NAMES_FILE
    res["assets"]["stock_names"] = {
        "label": "股票名称缓存（输出列「股票名称」来源）", "role": "input-names",
        "root": str(nf), "exists": nf.exists(),
        "sha256": sha256_file(nf) if nf.exists() else None,
        "size": nf.stat().st_size if nf.exists() else 0,
    }
    return res


def stage_p0(OUT, label):
    """跑 P0 全部规则，输出权威判定 + canonical 业务结果（同一 harness 路径）。"""
    import executor
    import golden_test as gt

    captured = {}
    _orig = executor.run_plan

    def spy(*a, **kw):
        rows, cols, meta = _orig(*a, **kw)
        captured["r"] = (rows, cols, meta)
        return rows, cols, meta

    executor.run_plan = spy
    rules = gt.load_rule_texts()
    verdicts, canonical, t0 = {}, [], time.time()
    try:
        for name in sorted(rules):
            captured.clear()
            try:
                r = gt.run_rule(name, rules[name], [])
                gt.classify(r)
            except Exception as e:  # noqa: BLE001
                import traceback
                r = {"rule": name, "verdict": "ERROR",
                     "detail": {"error": str(e), "traceback": traceback.format_exc()}}
            entry = {"rule": name, "verdict": r["verdict"],
                     "recognize": r.get("recognize")}
            if "r" in captured:
                rows, cols, meta = captured["r"]
                lines, rh, n = canon_rows(rows, cols)
                entry.update({"columns": cols, "n_rows": n, "rows_sha256": rh,
                              "meta": meta, "canonical_rows": lines})
            else:
                entry.update({"columns": None, "n_rows": 0, "rows_sha256": None,
                              "canonical_rows": [],
                              "failure": (r.get("detail") or {}).get("failure")})
            canonical.append(entry)
            verdicts[name] = {
                "verdict": r["verdict"],
                "hits": (r.get("detail") or {}).get("hits"),
                "conflicts": (r.get("detail") or {}).get("conflicts"),
                "notes": (r.get("detail") or {}).get("notes"),
                "our_columns": (r.get("detail") or {}).get("our_columns"),
                "cutoff_d0": (r.get("detail") or {}).get("cutoff_d0"),
                "data_end": (r.get("detail") or {}).get("data_end"),
            }
            print(f"  [{name}] {r['verdict']} rows={entry['n_rows']}", flush=True)
    finally:
        executor.run_plan = _orig

    doc = {"schema": SCHEMA, "label": label,
           "collected_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "elapsed_sec": round(time.time() - t0, 1),
           "canon_rule": CANON_RULE,
           "summary": _summarize(canonical),
           "rules": canonical}
    (OUT / f"P0_{label}_CANONICAL.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / f"P0_{label}_VERDICTS.json").write_text(
        json.dumps({"schema": SCHEMA, "label": label, "verdicts": verdicts},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    return doc


def _summarize(canonical):
    s = {"total": len(canonical), "by_verdict": {}, "total_rows": 0}
    for e in canonical:
        s["by_verdict"].setdefault(e["verdict"], []).append(e["rule"])
        s["total_rows"] += e["n_rows"]
    return s


def stage_excel(OUT, label, timeout=20):
    """结果 Excel 二进制 SHA-256（经后端 API 真实回测产出）。服务不可达则记 skipped。"""
    import urllib.error
    import urllib.request

    base = f"http://{paths.HOST}:{paths.PORT}"
    plan = {"schema_version": 1, "kind": "day_pattern_backward", "strategy_plan": {
        "universe": "20cm", "days": [
            {"offset": -2, "limit_up": True},
            {"offset": -1, "limit_up": False, "amount_max20": False},
            {"offset": 0, "limit_up": True, "amount_max20": True, "high_max20": False}],
        "outputs": [{"atom": "date", "day": 0}, {"atom": "t_walk", "t0": 0, "t1": 6}]}}
    stem = "p9_excel_probe"
    out = {"schema": SCHEMA, "label": label,
           "collected_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "endpoint": base, "stem": stem}

    def _req(path, payload=None, method="GET"):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload else None
        req = urllib.request.Request(base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()

    try:
        st, blob = _req("/api/plan/backtest",
                        {"plan": plan, "rule_text": "P9 Excel 探针：D-2涨停，D-1非涨停且非20日成交额最大，"
                                                    "D-0涨停且20日成交额最大且最高价非20日最高",
                         "stem": stem}, "POST")
        r = json.loads(blob.decode("utf-8"))
        out.update({"backtest_status": r.get("status"), "n_hits": r.get("n_hits"),
                    "data_date": r.get("data_date")})
        st, blob = _req(f"/api/backtest/{stem}/candidates/export")
        xlsx = OUT / f"EXCEL_{label}_{stem}.xlsx"
        xlsx.write_bytes(blob)
        out.update({"excel_bytes": len(blob),
                    "excel_sha256": hashlib.sha256(blob).hexdigest(),
                    "excel_saved": xlsx.name})
        # 同源结构化结果
        st, blob = _req(f"/api/backtest/{stem}/candidates")
        c = json.loads(blob.decode("utf-8"))
        rows = c.get("rows") or c.get("candidates") or []
        cols = c.get("columns") or []
        out["structured_n_rows"] = len(rows)
        out["structured_columns"] = cols
        _, rh, n = canon_rows(rows, cols)
        out["structured_rows_sha256"] = rh
        out["structured_canonical_rows"] = None  # 省体积：与 Excel 同源，行哈希足够
    except Exception as e:  # noqa: BLE001
        out["skipped"] = True
        out["reason"] = f"{type(e).__name__}: {e}"
    (OUT / f"EXCEL_{label}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


# ─────────────────────── main ───────────────────────

def collect(label, skip_p0=False, skip_market=False, skip_excel=False):
    OUT = ROOT / "artifacts" / "verification" / "p9" / label
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"[p9] out={OUT}", flush=True)

    env = stage_environment(label)
    (OUT / f"ENV_{label}.json").write_text(
        json.dumps(env, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[p9] env OK: {env['host']['system']}/{env['host']['machine']} "
          f"py={env['python']['version']} numpy={env['runtime_versions']['numpy']} "
          f"pandas={env['runtime_versions']['pandas']}", flush=True)

    inp = stage_inputs(OUT, label, skip_market=skip_market)
    (OUT / f"INPUTS_{label}.json").write_text(
        json.dumps(inp, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, a in inp["assets"].items():
        if k == "stock_names":
            print(f"[p9] input {k}: sha={str(a['sha256'])[:16]} size={a['size']}", flush=True)
        else:
            print(f"[p9] input {k}: n={a['n_files']} bytes={a['total_bytes']} "
                  f"tree={a['tree_hash'][:16]}", flush=True)

    if not skip_p0:
        print("[p9] P0 start (26 rules)...", flush=True)
        p0 = stage_p0(OUT, label)
        print(f"[p9] P0 done {p0['elapsed_sec']}s rows={p0['summary']['total_rows']}", flush=True)

    if not skip_excel:
        ex = stage_excel(OUT, label)
        print(f"[p9] excel: {'skipped ' + ex.get('reason', '') if ex.get('skipped') else ex['excel_sha256'][:16]}",
              flush=True)

    print(f"[p9] DONE -> {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    stage = args[0] if args else "collect"
    label = "win"
    if "--label" in args:
        label = args[args.index("--label") + 1]
    if stage != "collect":
        print(f"unknown stage: {stage}")
        sys.exit(2)
    sys.exit(collect(label,
                     skip_p0="--skip-p0" in args,
                     skip_market="--skip-market" in args,
                     skip_excel="--skip-excel" in args))
