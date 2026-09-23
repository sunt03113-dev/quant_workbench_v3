"""Build qwb_m4_deploy_20260923.zip from the 20260921 pack + gem10_ruling changes.

Base: dist/qwb_m4_deploy_20260921.zip (source of truth for the file set; already
contains 09-21/09-22 overrides). Overlay the 09-23 10cm ruling changes from disk,
write dist/qwb_m4_deploy_20260923.zip + SHA256SUMS_20260923.txt.
Run from anywhere; paths are absolute.
"""
import hashlib
import zipfile
from pathlib import Path

DIST = Path(r"D:\09work\quant_workbench_v3\dist")
PKG = Path(r"D:\09work\quant_workbench_v3\quant_workbench_package")
SRC = DIST / "qwb_m4_deploy_20260921.zip"
OUT = DIST / "qwb_m4_deploy_20260923.zip"
MARKET = DIST / "qwb_market_pack_20260923.zip"
STATE = DIST / "qwb_state_pack_20260923.zip"

# files replaced/added from current disk (inside-zip relative posix paths)
overlay = [
    "app/ask.py",
    "app/executor.py",
    "skill/tdx-stock-backtest-master/0824_backtest.py",
    "skill/tdx-stock-backtest-master/0827A_backtest.py",
    "skill/tdx-stock-backtest-master/0909A_backtest.py",
    "golden/0824_backtest/0824_backtest.csv",
    "golden/0824_backtest/0824_backtest.xlsx",
    "golden/0827A_backtest/0827A_backtest.csv",
    "golden/0827A_backtest/0827A_backtest.xlsx",
    "golden/0909A_backtest/0909A_backtest.csv",
    "golden/0909A_backtest/0909A_backtest.xlsx",
    "deploy/M4_DEPLOY_INSTRUCTION.md",
    "artifacts/verification/gem10_ruling/CHANGES.md",
]
for a in overlay:
    f = PKG / a
    assert f.exists(), f"missing source: {f}"

with zipfile.ZipFile(SRC) as z:
    names = [n for n in z.namelist() if not n.endswith("/")]

ovset = set(overlay)
with zipfile.ZipFile(SRC) as zin, zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zout:
    for item in zin.infolist():
        if item.filename.endswith("/"):
            continue
        data = overlay_bytes = None
        if item.filename in ovset:
            data = (PKG / item.filename).read_bytes()
        else:
            data = zin.read(item.filename)
        zi = zipfile.ZipInfo(item.filename, date_time=item.date_time)
        zi.external_attr = item.external_attr
        zi.compress_type = zipfile.ZIP_DEFLATED
        zout.writestr(zi, data)
    # pure additions (not present in base pack)
    base = set(names)
    for a in overlay:
        if a in base:
            continue
        zi = zipfile.ZipInfo(a, date_time=(2026, 9, 23, 18, 0, 0))
        zi.external_attr = 0o644 << 16
        zi.compress_type = zipfile.ZIP_DEFLATED
        zout.writestr(zi, (PKG / a).read_bytes())


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


with zipfile.ZipFile(OUT) as z:
    new_names = [n for n in z.namelist() if not n.endswith("/")]
    # verify overlay landed
    bad = [a for a in overlay
           if hashlib.sha256(z.read(a)).hexdigest() != hashlib.sha256((PKG / a).read_bytes()).hexdigest()]
    assert not bad, f"overlay mismatch inside zip: {bad}"

lines = [
    "# Quant Workbench 2026-09-23 发布包校验（三包配套）",
    "# 10cm 口径裁定（创业板 10% 时代入池 + 反向门）+ 行情至 09-22 + 工作台状态",
    "",
    f"{sha256(OUT)}  {OUT.name}",
    f"{sha256(MARKET)}  {MARKET.name}",
    f"{sha256(STATE)}  {STATE.name}",
]
(DIST / "SHA256SUMS_20260923.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

report = [f"out={OUT.name} files={len(new_names)} size={OUT.stat().st_size/1e6:.2f}MB",
          f"overlay={len(overlay)} verified=all"]
report += [f"  {n}  {zout.fp and ''}" for n in []]
report += [""] + lines
Path(PKG / "artifacts/verification/gem10_ruling/code_pack_build.txt").write_text(
    "\n".join(report) + "\n", encoding="utf-8")
print("\n".join(report))
