# -*- coding: utf-8 -*-
"""第一阶段：重建行情包（纳入 09-23 数据）+ 状态包（含本轮更新后的 6 个模型定义与结果表）。

老包先归档到 dist/archive/*_r1.zip，再原地重建（zipfile 'w' 原地截断）。
"""
import hashlib
import json
import os
import shutil
import time
import zipfile
from pathlib import Path

DIST = Path(r"D:\09work\quant_workbench_v3\dist")
PKG = Path(r"D:\09work\quant_workbench_v3\quant_workbench_package")
ARCHIVE = DIST / "archive"
ARCHIVE.mkdir(parents=True, exist_ok=True)

MARKET = DIST / "qwb_market_pack_20260923.zip"
STATE = DIST / "qwb_state_pack_20260923.zip"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def archive(p: Path, tag: str):
    dst = ARCHIVE / f"{p.stem}_{tag}{p.suffix}"
    if not dst.exists():
        shutil.copy2(p, dst)
        print(f"  归档 -> {dst.name}  ({dst.stat().st_size/1e6:.2f} MB)")
    else:
        print(f"  归档已存在，跳过: {dst.name}")


report = {}
t0 = time.time()

# ── 1) 行情包：appdata/market（11704 个 .day）+ appdata/stock_names.csv ──
print("== 重建行情包 ==")
archive(MARKET, "r1")
mkt_src = PKG / "appdata" / "market"
mkt_files = sorted(p for p in mkt_src.rglob("*") if p.is_file())
names_src = PKG / "appdata" / "stock_names.csv"
assert mkt_files and names_src.exists(), (len(mkt_files), names_src)
raw = sum(p.stat().st_size for p in mkt_files) + names_src.stat().st_size
tmp = DIST / "_market_new.zip"
with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for i, p in enumerate(mkt_files):
        zi = zipfile.ZipInfo(p.relative_to(PKG).as_posix(), date_time=(2026, 9, 23, 18, 0, 0))
        zi.external_attr = 0o644 << 16
        zi.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(zi, p.read_bytes())
        if i % 4000 == 0:
            print(f"   ... {i}/{len(mkt_files)}")
    zi = zipfile.ZipInfo("appdata/stock_names.csv", date_time=(2026, 9, 23, 18, 0, 0))
    zi.external_attr = 0o644 << 16
    zi.compress_type = zipfile.ZIP_DEFLATED
    z.writestr(zi, names_src.read_bytes())
os.replace(tmp, MARKET)
with zipfile.ZipFile(MARKET) as z:
    mn = [n for n in z.namelist() if not n.endswith("/")]
report["market"] = {"name": MARKET.name, "files": len(mn),
                    "raw_mb": round(raw / 1e6, 1),
                    "zip_mb": round(MARKET.stat().st_size / 1e6, 2),
                    "sha256": sha256(MARKET)}
print("  ", json.dumps(report["market"], ensure_ascii=False))

# ── 2) 状态包：appdata/state（模型定义 + 结果表）──
print("== 重建状态包 ==")
archive(STATE, "r1")
state_src = PKG / "appdata" / "state"
st_files = sorted(p for p in state_src.rglob("*") if p.is_file())
assert st_files, "state dir empty"
tmp = DIST / "_state_new.zip"
with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for p in st_files:
        zi = zipfile.ZipInfo(p.relative_to(PKG).as_posix(), date_time=(2026, 9, 23, 18, 0, 0))
        zi.external_attr = 0o644 << 16
        zi.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(zi, p.read_bytes())
os.replace(tmp, STATE)
with zipfile.ZipFile(STATE) as z:
    sn = [n for n in z.namelist() if not n.endswith("/")]
    n_res = sum(1 for n in sn if n.startswith("appdata/state/results/"))
    raw_st = sum(z.getinfo(n).file_size for n in sn)
report["state"] = {"name": STATE.name, "files": len(sn), "results_files": n_res,
                   "raw_mb": round(raw_st / 1e6, 2),
                   "zip_mb": round(STATE.stat().st_size / 1e6, 2),
                   "sha256": sha256(STATE)}
print("  ", json.dumps(report["state"], ensure_ascii=False))

report["elapsed_s"] = round(time.time() - t0, 1)
out = PKG / "artifacts/verification/1s1a_bug_0923/pack_build_phase1.json"
out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print("\n->", out)
