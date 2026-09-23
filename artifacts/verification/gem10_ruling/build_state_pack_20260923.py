"""Build the third deploy artifact: appdata/state (model definitions + result tables).

Why: 代码包只带 golden 期望结果表，行情包只带 market + stock_names。
产品的「模型定义 + 已有结果表」在 appdata/state —— 不带它，M4 打开是空工作台。
state.json 经扫描零绝对路径（可移植）。Run from anywhere.
"""
import hashlib
import zipfile
from pathlib import Path

PKG = Path(r"D:\09work\quant_workbench_v3\quant_workbench_package")
DIST = Path(r"D:\09work\quant_workbench_v3\dist")
SRC = PKG / "appdata" / "state"
OUT = DIST / "qwb_state_pack_20260923.zip"

assert SRC.is_dir(), SRC
files = sorted(p for p in SRC.rglob("*") if p.is_file())
assert files, "state dir empty"

with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for p in files:
        rel = p.relative_to(PKG).as_posix()          # appdata/state/...
        zi = zipfile.ZipInfo(rel, date_time=(2026, 9, 23, 18, 0, 0))
        zi.external_attr = 0o644 << 16
        zi.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(zi, p.read_bytes())


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


with zipfile.ZipFile(OUT) as z:
    names = [n for n in z.namelist() if not n.endswith("/")]
    n_results = sum(1 for n in names if n.startswith("appdata/state/results/"))
    raw = sum(z.getinfo(n).file_size for n in names)

lines = [f"out={OUT.name}",
         f"files={len(names)} (results/*={n_results})",
         f"raw={raw/1e6:.2f}MB zip={OUT.stat().st_size/1e6:.2f}MB",
         f"sha256={sha256(OUT)}"]
(PKG / "artifacts/verification/gem10_ruling/state_pack_build.txt").write_text(
    "\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
