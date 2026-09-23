# -*- coding: utf-8 -*-
"""决定性对照：HEAD 版本 vs 当前版本，在同一份 vipdoc 数据上各跑一次 golden。

流程：备份当前 3 个源文件 -> 用 git show HEAD 覆盖 -> 跑 golden（存 before） ->
还原当前版本（校验 sha256）-> 跑 golden（存 after）-> 深度比对。

任何异常都会在 finally 里还原并校验，绝不留下 HEAD 版本。
"""
import hashlib
import io
import json
import os
import contextlib
import runpy
import subprocess
import sys
import traceback

ROOT = r'D:/09work/quant_workbench_v3/quant_workbench_package'
ART = os.path.join(ROOT, 'artifacts/verification/1s1a_bug_0923')
FILES = ['app/executor.py', 'app/recognizer.py', 'app/ask.py']
GJSON = os.path.join(ROOT, 'artifacts/verification/step3/golden_test_results.json')
os.chdir(ROOT)


def sha(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()


def run_golden(tag):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            runpy.run_path('app/golden_test.py', run_name='__main__')
        except SystemExit as e:
            print('SystemExit', e)
    dst = os.path.join(ART, f'golden_{tag}.json')
    with open(GJSON, encoding='utf-8') as f:
        txt = f.read()
    with open(dst, 'w', encoding='utf-8') as f:
        f.write(txt)
    return json.loads(txt)


# 1) 备份当前（改动后）版本
after_bytes = {p: open(os.path.join(ROOT, p), 'rb').read() for p in FILES}
after_sha = {p: sha(os.path.join(ROOT, p)) for p in FILES}
print('改动后 sha256:', json.dumps(after_sha, indent=1))

before_json = None
after_json = None
try:
    # 2) 覆盖为 HEAD 版本
    for p in FILES:
        blob = subprocess.run(['git', 'show', f'HEAD:{p}'], cwd=ROOT,
                              capture_output=True).stdout
        assert blob, p
        open(os.path.join(ROOT, p), 'wb').write(blob)
    print('已切到 HEAD 版本，开始跑 golden(before) ...')
    before_json = run_golden('before')

    # 3) 还原当前版本
    for p in FILES:
        open(os.path.join(ROOT, p), 'wb').write(after_bytes[p])
    bad = [p for p in FILES if sha(os.path.join(ROOT, p)) != after_sha[p]]
    if bad:
        raise RuntimeError(f'还原失败（哈希不符）: {bad}')
    print('已还原当前版本（哈希校验通过），开始跑 golden(after) ...')
    after_json = run_golden('after')
finally:
    for p in FILES:
        open(os.path.join(ROOT, p), 'wb').write(after_bytes[p])
    bad = [p for p in FILES if sha(os.path.join(ROOT, p)) != after_sha[p]]
    print('FINAL 还原校验:', 'OK' if not bad else f'!! 失败 {bad}')

if before_json is None or after_json is None:
    print('!! 对照未完成')
    sys.exit(1)


def walk(a, b, path='', out=None):
    if out is None:
        out = []
    if type(a) != type(b):
        out.append(('TYPE', path, a, b))
        return out
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append(('ONLY_AFTER', path + '/' + k, None, b[k]))
            elif k not in b:
                out.append(('ONLY_BEFORE', path + '/' + k, a[k], None))
            else:
                walk(a[k], b[k], path + '/' + k, out)
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append(('LEN', path, len(a), len(b)))
        for i in range(min(len(a), len(b))):
            walk(a[i], b[i], path + f'[{i}]', out)
    elif a != b:
        out.append(('DIFF', path, a, b))
    return out


om = {r['rule']: r for r in before_json['results']}
nm = {r['rule']: r for r in after_json['results']}
lines = []
lines.append('summary 一致: %s' % (before_json.get('summary') == after_json.get('summary')))
VOLATILE = ('/run_seconds', '/elapsed', '/runtime')
for k in sorted(om):
    d = [t for t in walk(om[k], nm.get(k, {})) if not any(t[1].endswith(v) for v in VOLATILE)]
    if d:
        lines.append('---- %s  (%d 处非时间差异)' % (k, len(d)))
        for kind, path, a, b in d[:20]:
            lines.append('   [%s] %s  BEFORE=%s  AFTER=%s' % (kind, path, repr(a)[:60], repr(b)[:60]))
    else:
        lines.append('---- %s  与 HEAD 完全一致（仅 run_seconds 计时差）' % k)
report = '\n'.join(lines)
open(os.path.join(ART, 'golden_head_vs_new.txt'), 'w', encoding='utf-8').write(report + '\n')
print(report)
