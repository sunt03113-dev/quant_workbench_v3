# -*- coding: utf-8 -*-
"""STEP1 实测脚本2：westock CLI 真实调用探针。保存原始 stdout/stderr。"""
import json
import subprocess
from pathlib import Path

WS = Path(r"D:\09work\quant_workbench_v3\quant_workbench_package")
OUT = WS / "artifacts" / "verification" / "step1"
OUT.mkdir(parents=True, exist_ok=True)
EXE = r"C:\Users\21412\.local\bin\westock.exe"

probes = {
    "version": [EXE, "--version"],
    "quote_600519": [EXE, "quote", "sh600519"],
    "kline_600519": [EXE, "kline", "sh600519", "--period", "day", "--limit", "5"],
    "kline_300010": [EXE, "kline", "sz300010", "--period", "day", "--limit", "5"],
    "kline_688006": [EXE, "kline", "sh688006", "--period", "day", "--limit", "5"],
    "quote_688006": [EXE, "quote", "sh688006"],
}

summary = {}
for name, cmd in probes.items():
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=60)
        (OUT / f"westock_{name}.txt").write_text(
            f"# cmd: {cmd[1:]}\n# returncode: {p.returncode}\n\n--- STDOUT ---\n{p.stdout}\n\n--- STDERR ---\n{p.stderr}\n",
            encoding="utf-8")
        summary[name] = {"rc": p.returncode, "stdout_len": len(p.stdout),
                         "stderr_head": p.stderr[:120]}
    except Exception as e:
        summary[name] = {"error": repr(e)}

print(json.dumps(summary, ensure_ascii=False, indent=2))
