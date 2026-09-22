"""Repack the M4 deploy zip: keep the original file set, add/replace deploy/mac/* and touched files.

Avoids re-deriving the original exclusion rules -- the existing zip is the source of truth
for which files belong to the code package. Run from the repo root.
"""
import hashlib
import shutil
import sys
import zipfile
from pathlib import Path

DIST = Path(r"D:\09work\quant_workbench_v3\dist")
PKG = Path(r"D:\09work\quant_workbench_v3\quant_workbench_package")
SRC = DIST / "qwb_m4_deploy_20260921.zip"
ARCHIVE = DIST / "archive"
PREV = ARCHIVE / "qwb_m4_deploy_20260921_prev.zip"
MARKET = DIST / "qwb_market_pack_20260921.zip"

with zipfile.ZipFile(SRC) as z:
    names = z.namelist()
tops = {}
for n in names:
    top = n.split("/")[0]
    tops[top] = tops.get(top, 0) + 1
print("原包顶层条目统计:")
for k, v in sorted(tops.items(), key=lambda kv: -kv[1]):
    print(f"  {k:<28} {v}")
print(f"  total files = {sum(1 for n in names if not n.endswith('/'))}")

# files to override / add (inside-zip relative posix paths)
add = [
    "deploy/M4_DEPLOY_INSTRUCTION.md",
    "deploy/README_DEPLOY.md",
    "deploy/start_workbench.bat",
    "artifacts/verification/mac_launcher/SELFTEST.md",
    "artifacts/verification/n_interval_semantics/REPORT.md",
    # 2026-09-22 间隔口径切换（N = 两段涨停之间不含两端的 K 线根数，对齐 Skill）
    "app/recognizer.py",
    "app/executor.py",
    "app/recognizer.v4.baseline.py",
    "app/executor.v3.baseline.py",
    "skill/tdx-stock-backtest-master/tdx-stock-backtest.md",
    "skill/tdx-stock-backtest-master/README.md",
]
for p in sorted((PKG / "deploy" / "mac").rglob("*")):
    if p.is_file():
        add.append(p.relative_to(PKG).as_posix())

print("\n覆盖/新增:")
for a in add:
    src_file = PKG / Path(a)
    assert src_file.exists(), f"missing source: {src_file}"
    print(f"  {a}")

if not PREV.parent.exists():
    ARCHIVE.mkdir(parents=True, exist_ok=True)
if not PREV.exists():
    shutil.copy2(SRC, PREV)
    print(f"\n原包已备份 -> {PREV}")

TMP = DIST / "_qwb_m4_deploy_20260921.new.zip"
addset = set(add)
with zipfile.ZipFile(SRC) as zin, zipfile.ZipFile(TMP, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zout:
    for item in zin.infolist():
        if item.filename in addset:
            continue  # will be re-added from disk
        data = zin.read(item.filename)
        zi = zipfile.ZipInfo(item.filename, date_time=item.date_time)
        zi.external_attr = item.external_attr
        zi.compress_type = zipfile.ZIP_DEFLATED
        zout.writestr(zi, data)
    for a in add:
        zi = zipfile.ZipInfo(a, date_time=(2026, 9, 21, 18, 0, 0))
        zi.external_attr = (0o755 if a.endswith((".sh", ".command")) else 0o644) << 16
        zi.compress_type = zipfile.ZIP_DEFLATED
        zout.writestr(zi, (PKG / Path(a)).read_bytes())

shutil.move(str(TMP), str(SRC))


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


with zipfile.ZipFile(SRC) as z:
    n_new = sum(1 for n in z.namelist() if not n.endswith("/"))
    has_mac = sorted(n for n in z.namelist() if n.startswith("deploy/mac/"))

lines = [
    "# Quant Workbench 2026-09-21 发布包校验",
    "# 代码包已追加 deploy/mac/（macOS 双击启动器）",
    "",
    f"{sha256(SRC)}  {SRC.name}",
    f"{sha256(MARKET)}  {MARKET.name}",
]
sums = DIST / "SHA256SUMS_20260921.txt"
sums.write_text("\n".join(lines) + "\n", encoding="utf-8")

print(f"\n新包: {SRC.name}  文件数 {n_new}  ({SRC.stat().st_size/1e6:.2f} MB)")
print("deploy/mac 内容:")
for m in has_mac:
    print("  ", m)
print(f"\n校验文件 -> {sums}")
print("\n".join(lines[2:]))
