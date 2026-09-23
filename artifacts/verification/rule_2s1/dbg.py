# -*- coding: utf-8 -*-
import json
import pathlib
import sys

WS = pathlib.Path(r"D:\09work\quant_workbench_v3\quant_workbench_package")
sys.path.insert(0, str(WS / "app"))
import recognizer  # noqa: E402

out = {}
clause = "不涨停，收/定为阴"
out["norm"] = recognizer._norm(clause)
out["parse_conditions"] = recognizer._parse_conditions(clause)
out["regex_hit"] = bool(recognizer._RE_CANDLE.search(recognizer._norm(clause)))
m = recognizer._RE_CANDLE.search(recognizer._norm(clause))
if m:
    out["groups"] = m.groups()
pathlib.Path(WS / "artifacts/verification/rule_2s1/dbg.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
