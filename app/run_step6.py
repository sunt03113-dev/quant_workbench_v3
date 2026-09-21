# -*- coding: utf-8 -*-
"""运行 step6_test.py 并落 UTF-8 日志（shell 输出捕获故障兜底）。"""
import contextlib
import io
import runpy
from pathlib import Path

HERE = Path(__file__).parent
buf = io.StringIO()
code = 0
try:
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        runpy.run_path(str(HERE / "step6_test.py"), run_name="__main__")
except SystemExit as e:
    code = e.code or 0
except BaseException as e:
    buf.write(f"\nFATAL: {e!r}")
    code = 99
log = HERE.parent / "artifacts" / "verification" / "step6" / "test_run_utf8.log"
log.parent.mkdir(parents=True, exist_ok=True)
log.write_text(buf.getvalue(), encoding="utf-8")
print("WROTE", log, "EXIT", code)
