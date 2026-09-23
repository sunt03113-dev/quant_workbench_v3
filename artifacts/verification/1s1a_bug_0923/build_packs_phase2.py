# -*- coding: utf-8 -*-
"""第二阶段：重打代码包（区间语义方案A）+ 三包 SHA256SUMS。

基准包 = 当前 dist/qwb_m4_deploy_20260923.zip（已含 09-21/09-22/09-23 各轮 overlay），
本轮再 overlay：3 个源文件 + 2 个新 baseline + 部署指令 + 本轮证据目录。
"""
import hashlib
import json
import os
import shutil
import zipfile
from pathlib import Path

DIST = Path(r"D:\09work\quant_workbench_v3\dist")
PKG = Path(r"D:\09work\quant_workbench_v3\quant_workbench_package")
ARCHIVE = DIST / "archive"
OUT = DIST / "qwb_m4_deploy_20260923.zip"
MARKET = DIST / "qwb_market_pack_20260923.zip"
STATE = DIST / "qwb_state_pack_20260923.zip"
ART = PKG / "artifacts/verification/1s1a_bug_0923"

overlay = [
    "app/executor.py",
    "app/recognizer.py",
    "app/ask.py",
    "app/recognizer.v5.baseline.py",
    "app/executor.v4.baseline.py",
    "deploy/M4_DEPLOY_INSTRUCTION.md",
]
# 本轮证据目录（排除本机 state 备份 zip，避免把 3.9MB 备份塞进代码包）
for p in sorted(ART.iterdir()):
    if p.is_file() and p.name != "state_backup_before_rerun.zip":
        overlay.append(p.relative_to(PKG).as_posix())

for a in overlay:
    f = PKG / a
    assert f.exists(), f"missing source: {f}"

ARCHIVE.mkdir(parents=True, exist_ok=True)
prev = ARCHIVE / "qwb_m4_deploy_20260923_r1.zip"
if not prev.exists():
    shutil.copy2(OUT, prev)
    print(f"归档 -> {prev.name} ({prev.stat().st_size/1e6:.2f} MB)")

with zipfile.ZipFile(OUT) as z:
    base = set(n for n in z.namelist() if not n.endswith("/"))
print(f"基准包文件数 = {len(base)}")

ovset = set(overlay)
TMP = DIST / "_deploy_new.zip"
with zipfile.ZipFile(OUT) as zin, zipfile.ZipFile(TMP, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zout:
    for item in zin.infolist():
        if item.filename.endswith("/"):
            continue
        data = (PKG / item.filename).read_bytes() if item.filename in ovset else zin.read(item.filename)
        zi = zipfile.ZipInfo(item.filename, date_time=item.date_time)
        zi.external_attr = item.external_attr
        zi.compress_type = zipfile.ZIP_DEFLATED
        zout.writestr(zi, data)
    for a in overlay:
        if a in base:
            continue
        zi = zipfile.ZipInfo(a, date_time=(2026, 9, 23, 19, 0, 0))
        zi.external_attr = (0o755 if a.endswith((".sh", ".command")) else 0o644) << 16
        zi.compress_type = zipfile.ZIP_DEFLATED
        zout.writestr(zi, (PKG / a).read_bytes())
os.replace(TMP, OUT)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


with zipfile.ZipFile(OUT) as z:
    names = [n for n in z.namelist() if not n.endswith("/")]
    bad = [a for a in overlay
           if hashlib.sha256(z.read(a)).hexdigest()
           != hashlib.sha256((PKG / a).read_bytes()).hexdigest()]
    assert not bad, f"overlay mismatch inside zip: {bad}"

lines = [
    "# Quant Workbench 2026-09-23 发布包校验（三包配套 · 区间语义方案A 修订）",
    "# 区间语义(D-1/D-x 同组条件 -> D-x~D-1 整段) + 10cm 口径 + 行情至 09-23 + 工作台状态",
    "",
    f"{sha256(OUT)}  {OUT.name}",
    f"{sha256(MARKET)}  {MARKET.name}",
    f"{sha256(STATE)}  {STATE.name}",
]
(DIST / "SHA256SUMS_20260923.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
(DIST / "SHA256SUMS_market_20260923.txt").write_text(
    f"market pack: {len([n for n in zipfile.ZipFile(MARKET).namelist() if n.endswith('.day')])} .day, "
    f"zip {MARKET.stat().st_size/1e6:.2f} MB, 数据截止 2026-09-23\n"
    f"sha256= {sha256(MARKET)}\n", encoding="utf-8")

rep = {"code_pack": {"name": OUT.name, "files": len(names),
                     "zip_mb": round(OUT.stat().st_size / 1e6, 2), "sha256": sha256(OUT)},
       "overlay": overlay, "overlay_verified": True,
       "sha256sums": lines[3:]}
(ART / "pack_build_phase2.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2),
                                            encoding="utf-8")
print(f"\nout={OUT.name} files={len(names)} size={OUT.stat().st_size/1e6:.2f}MB overlay={len(overlay)} verified=all")
print("\n".join(lines))
