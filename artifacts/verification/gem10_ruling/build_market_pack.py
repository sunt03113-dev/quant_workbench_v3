# -*- coding: utf-8 -*-
"""重建 M4 行情包：appdata/market + stock_names.csv -> dist/qwb_market_pack_<date>.zip（ZIP_STORED）。"""
import hashlib
import sys
import time
import zipfile
from pathlib import Path

DATE = sys.argv[1] if len(sys.argv) > 1 else "20260923"
WS = Path(r"D:\09work\quant_workbench_v3\quant_workbench_package")
OUT = Path(rf"D:\09work\quant_workbench_v3\dist\qwb_market_pack_{DATE}.zip")
SUMS = Path(rf"D:\09work\quant_workbench_v3\dist\SHA256SUMS_market_{DATE}.txt")

market = WS / "appdata" / "market"
names = WS / "appdata" / "stock_names.csv"
assert market.exists() and names.exists()

t0 = time.time()
files = sorted(market.rglob("*.day"))
assert names.is_file()
n = 0
with zipfile.ZipFile(OUT, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as z:
    for f in files:
        arc = f.relative_to(WS).as_posix()          # appdata/market/...
        z.write(f, arc)
        n += 1
    z.write(names, names.relative_to(WS).as_posix())  # appdata/stock_names.csv（与旧包一致）
    n += 1

raw = sum(f.stat().st_size for f in files) + names.stat().st_size
h = hashlib.sha256(OUT.read_bytes()).hexdigest()
elapsed = time.time() - t0
lines = [f"market pack: {n} files, 原始 {raw / 1e6:.1f} MB, zip {OUT.stat().st_size / 1e6:.1f} MB, {elapsed:.0f}s",
         f"sha256= {h}"]
SUMS.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
