# -*- coding: utf-8 -*-
"""第三阶段（收尾）：清掉本机 state 里的探针污染 + 重打状态包 + 重打代码包（纳入新增证据）+ 更新 SHA256SUMS。

为什么需要这一步：
  1) `live_api_check.py` 为了做端点式对照，向真实 API 发过 3 个探针 stem 的回测
     （`strategy_zz_probe_endpoint_v1` / `_degraded_v1` / `_no_ranges_v1`），
     `save_*` 会把它们写进 `state.json` 与 `results/`。这是**我引入的污染**，必须清除，
     否则 kk 在 UI 上会看到 3 张莫名其妙的卡片，且状态包会把污染带到 M4。
  2) 活体回测还对真实 stem 写了一次 → `current/previous` 轮换，状态已与 phase2 打的状态包不一致；
  3) 本轮又新增了若干证据文件，代码包 overlay 需重新纳入。

`p9_excel_probe` / `strategy_e2etest_v1` 是**上一版已交付状态包里就有的历史条目**（非本轮引入），
不在清理范围（动它们等于擅自改 kk 的工作台内容）。
"""
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

DIST = Path(r"D:\09work\quant_workbench_v3\dist")
PKG = Path(r"D:\09work\quant_workbench_v3\quant_workbench_package")
ARCHIVE = DIST / "archive"
ARCHIVE.mkdir(parents=True, exist_ok=True)
OUT = DIST / "qwb_m4_deploy_20260923.zip"
MARKET = DIST / "qwb_market_pack_20260923.zip"
STATE = DIST / "qwb_state_pack_20260923.zip"
ART = PKG / "artifacts/verification/1s1a_bug_0923"

PROBE_PREFIX = "strategy_zz_probe_"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


report = {}
log = []

# ── 1) 清探针污染 ────────────────────────────────────────────────
print("== 1) 清探针污染 ==")
sj = PKG / "appdata/state/state.json"
st = json.loads(sj.read_text(encoding="utf-8"))
before_models = sorted(st.get("models", {}).keys())
removed = [m for m in before_models if m.startswith(PROBE_PREFIX)]
for m in removed:
    del st["models"][m]
    rd = PKG / "appdata/state/results" / m
    if rd.exists():
        shutil.rmtree(rd)
        log.append(f"  删除结果目录 results/{m}")
print(f"  移除探针模型 {len(removed)}: {removed}")
# 缩进与 store 落盘风格保持一致（2 空格）
sj.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
after_models = sorted(json.loads(sj.read_text(encoding="utf-8"))["models"].keys())
print(f"  state.json 模型数 {len(before_models)} -> {len(after_models)}")
assert not [m for m in after_models if m.startswith(PROBE_PREFIX)], "探针未清净"
report["state_cleanup"] = {"removed": removed,
                           "models_before": len(before_models),
                           "models_after": len(after_models)}

# 遗留 results 目录（不属于任何模型）也一并核对
resdirs = sorted(p.name for p in (PKG / "appdata/state/results").iterdir() if p.is_dir())
orphan = [d for d in resdirs if d not in after_models]
print(f"  结果目录 {len(resdirs)} 个；不属于任何模型的孤立目录: {orphan}")
report["orphan_result_dirs"] = orphan

# ── 2) 重打状态包 ────────────────────────────────────────────────
print("\n== 2) 重打状态包 ==")
prev_state_sha = sha256(STATE)
state_src = PKG / "appdata" / "state"
st_files = sorted(p for p in state_src.rglob("*") if p.is_file())
tmp = DIST / "_state_new.zip"
with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for p in st_files:
        zi = zipfile.ZipInfo(p.relative_to(PKG).as_posix(), date_time=(2026, 9, 23, 19, 0, 0))
        zi.external_attr = 0o644 << 16
        zi.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(zi, p.read_bytes())
import os
os.replace(tmp, STATE)
with zipfile.ZipFile(STATE) as z:
    sn = [n for n in z.namelist() if not n.endswith("/")]
    packed_models = sorted(json.loads(z.read("appdata/state/state.json").decode("utf-8"))["models"].keys())
n_res = sum(1 for n in sn if n.startswith("appdata/state/results/"))
report["state"] = {"name": STATE.name, "files": len(sn), "results_files": n_res,
                   "models": len(packed_models),
                   "zip_mb": round(STATE.stat().st_size / 1e6, 2),
                   "sha256": sha256(STATE), "sha256_before": prev_state_sha,
                   "probe_free": not any(m.startswith(PROBE_PREFIX) for m in packed_models)}
print(f"  {json.dumps(report['state'], ensure_ascii=False)}")

# ── 3) 重打代码包（overlay 含新增证据）──────────────────────────
print("\n== 3) 重打代码包 ==")
overlay = [
    "app/executor.py",
    "app/recognizer.py",
    "app/ask.py",
    "app/recognizer.v5.baseline.py",
    "app/executor.v4.baseline.py",
    "deploy/M4_DEPLOY_INSTRUCTION.md",
]
for p in sorted(ART.iterdir()):
    # 排除两类：
    #   1) 本机安全网备份 zip（非交付物，且 3.9MB state 备份会白占体积）
    #   2) 打包报告 pack_build_phase*.json —— **自引用**：报告里写着包的 sha256，
    #      而写入报告会让包哈希再变。把它排除后重打即幂等（同一 HEAD 连打两次哈希相同）。
    if p.is_file() and p.suffix != ".zip" and not p.name.startswith("pack_build_phase"):
        overlay.append(p.relative_to(PKG).as_posix())
for a in overlay:
    f = PKG / a
    assert f.exists(), f"missing source: {f}"

prev_code_sha = sha256(OUT)
with zipfile.ZipFile(OUT) as z:
    base = set(n for n in z.namelist() if not n.endswith("/"))
# 旧包里已混入的打包报告（自引用）一次性剔除，避免包内留一份哈希过期的报告
base = {n for n in base if not Path(n).name.startswith("pack_build_phase")}
ovset = set(overlay)
TMP = DIST / "_deploy_new.zip"
with zipfile.ZipFile(OUT) as zin, zipfile.ZipFile(TMP, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zout:
    for item in zin.infolist():
        if item.filename.endswith("/"):
            continue
        if Path(item.filename).name.startswith("pack_build_phase"):
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

with zipfile.ZipFile(OUT) as z:
    names = [n for n in z.namelist() if not n.endswith("/")]
    bad = [a for a in overlay
           if hashlib.sha256(z.read(a)).hexdigest()
           != hashlib.sha256((PKG / a).read_bytes()).hexdigest()]
    assert not bad, f"overlay mismatch inside zip: {bad}"
report["code_pack"] = {"name": OUT.name, "files": len(names),
                       "zip_mb": round(OUT.stat().st_size / 1e6, 2),
                       "sha256": sha256(OUT), "sha256_before": prev_code_sha,
                       "overlay": overlay, "overlay_verified": True}
print(f"  files={len(names)} size={OUT.stat().st_size/1e6:.2f}MB overlay={len(overlay)} verified")

# ── 4) 更新 SHA256SUMS ──────────────────────────────────────────
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
report["sha256sums"] = lines[3:]
report["market"] = {"name": MARKET.name,
                    "zip_mb": round(MARKET.stat().st_size / 1e6, 2),
                    "sha256": sha256(MARKET)}

print("\n" + "\n".join(lines))
(ART / "pack_build_phase3.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
print("\n-> pack_build_phase3.json 已落盘")
