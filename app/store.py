# -*- coding: utf-8 -*-
"""产品状态持久化（appdata/state/）。

每张模型卡片（stem）维护：
  rule_text / plan / base_rules
  current_result  / previous_result
成功回测：previous <- current，current <- 新结果；
失败回测：两者都不变（fail-closed，不覆盖已有成功结果）。
"""
import json
import shutil
import threading
from datetime import datetime
from pathlib import Path

from paths import STATE_FILE, RESULTS_DIR

_lock = threading.Lock()


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _empty_state():
    return {"schema_version": 1, "models": {}}


def load_state():
    with _lock:
        if not STATE_FILE.exists():
            return _empty_state()
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            backup = STATE_FILE.with_suffix(".corrupt.json")
            shutil.copy2(STATE_FILE, backup)
            return _empty_state()


def save_state(state):
    with _lock:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(STATE_FILE)


def _model(state, stem):
    return state["models"].setdefault(stem, {})


def get_rule(stem):
    m = load_state()["models"].get(stem)
    if not m or "rule_text" not in m:
        return None
    return {"strategy": {"rule_text": m.get("rule_text", ""),
                         "base_rules": m.get("base_rules"),
                         "plan": m.get("plan")}}


def save_rule(stem, rule_text, plan, base_rules):
    state = load_state()
    m = _model(state, stem)
    m["rule_text"] = rule_text
    m["plan"] = plan
    m["base_rules"] = base_rules
    m["updated_at"] = _now()
    save_state(state)


def result_dir(stem):
    d = RESULTS_DIR / stem
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_success_result(stem, columns, rows, n_hits, data_date, meta):
    """成功结果落库 + current/previous 轮换。返回 (current, previous) 摘要。"""
    state = load_state()
    m = _model(state, stem)
    rd = result_dir(stem)

    # previous <- current
    if "current_result" in m and m["current_result"]:
        cur = m["current_result"]
        src = rd / "current.json"
        if src.exists():
            shutil.copy2(src, rd / "previous.json")
        if (rd / "current.xlsx").exists():
            shutil.copy2(rd / "current.xlsx", rd / "previous.xlsx")
        m["previous_result"] = cur

    result = {
        "n_hits": n_hits,
        "data_date": data_date,
        "columns": columns,
        "updated_at": _now(),
        "meta": meta,
    }
    (rd / "current.json").write_text(
        json.dumps({"columns": columns, "rows": rows}, ensure_ascii=False),
        encoding="utf-8")
    m["current_result"] = result
    save_state(state)
    return result, m.get("previous_result")


def compute_new_hits(state, stem):
    """new_hits = current - previous（仅成功结果参与 diff）。"""
    m = state["models"].get(stem) or {}
    cur = m.get("current_result")
    prev = m.get("previous_result")
    if not cur:
        return []
    cur_rows = _load_rows(stem, "current")
    if cur_rows is None:
        return []
    prev_codes = set()
    if prev:
        prev_rows = _load_rows(stem, "previous")
        if prev_rows:
            prev_codes = {r.get("股票代码") for r in prev_rows}
    names = {}
    for r in cur_rows:
        names.setdefault(r.get("股票代码"), r.get("股票名称"))
    new = []
    for r in cur_rows:
        c = r.get("股票代码")
        if c and c not in prev_codes and c not in {x.get("code") for x in new}:
            new.append({"code": c, "name": names.get(c) or ""})
    return new


def day_new_hits(state, stem, day):
    """当日新增命中 = current 结果中「D-0 日期 == day」的命中股票（去重，保序）。

    语义与 compute_new_hits（本次-上次 diff）不同：这里只统计在指定交易日
    当天新触发规则的信号，与是否手动重跑无关（首页绿色高亮唯一数据源）。
    """
    rows = _load_rows(stem, "current")
    if rows is None or not rows or not day:
        return []
    d0 = next((c for c in rows[0] if c == "D-0日期" or c.endswith("日期")), None)
    if not d0:
        return []
    seen = set()
    out = []
    for r in rows:
        if r.get(d0) == day:
            c = r.get("股票代码")
            if c and c not in seen:
                seen.add(c)
                out.append({"code": c, "name": r.get("股票名称") or ""})
    return out


def _load_rows(stem, which):
    f = result_dir(stem) / f"{which}.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))["rows"]
    except Exception:
        return None


def load_result(stem, which="current"):
    f = result_dir(stem) / f"{which}.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None


def daily_state_payload():
    """/api/daily/state：data_date + 每模型 new_hits（diff）+ day_new_hits（当日新增）。"""
    state = load_state()
    data_date = None
    models_out = {}
    for stem, m in state["models"].items():
        cur = m.get("current_result") or {}
        dd = cur.get("data_date")
        if dd and (data_date is None or dd > data_date):
            data_date = dd
        new_hits = compute_new_hits(state, stem) if cur else []
        models_out[stem] = {
            "data_date": dd,
            "n_hits": cur.get("n_hits", 0),
            "new_hits": new_hits,
        }
    # 第二遍：全局最新交易日确定后，补「当日新增命中」（首页高亮唯一判据）
    for stem, m in state["models"].items():
        if models_out[stem]["data_date"]:
            models_out[stem]["day_new_hits"] = day_new_hits(state, stem, data_date)
        else:
            models_out[stem]["day_new_hits"] = []
    return {"data_date": data_date, "models": models_out}
