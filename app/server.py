# -*- coding: utf-8 -*-
"""Quant Workbench 后端 —— 按冻结 UI 契约实现（127.0.0.1:8000）。

端点：
  GET  /                                          冻结 UI
  GET  /api/data/latest                           行情新鲜度
  POST /api/plan/recognize                        NL -> Strategy Plan
  POST /api/plan/resolve_ambiguity                澄清后修订
  POST /api/plan/backtest                         执行回测（Skill 业务原子 + 确定性复核）
  GET  /api/rules/{stem}                          持久化规则
  GET  /api/backtest/{stem}/candidates            当前结果（全量）
  GET  /api/backtest/{stem}/candidates/export     Excel 下载
  GET  /api/daily/state                           每日状态（new_hits 高亮）
  POST /api/daily/run + GET /api/daily/jobs/{id}  手动更新任务
"""
import logging
import threading
import time
import uuid
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

import executor
import provider
import recognizer
import store
from paths import UI_FILE, HOST, PORT

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("qwb.server")

app = FastAPI(title="Quant Workbench", docs_url=None, redoc_url=None)

# Skill 导入在 executor 模块加载时完成（含 config.yaml 注入）

# ───────────────────────── 模型 ─────────────────────────


class RecognizeReq(BaseModel):
    natural_text: str
    universe: str | None = None


class ResolveReq(BaseModel):
    plan: dict
    rule_text: str
    choices: list = []
    universe_hint: str = ""


class BacktestReq(BaseModel):
    plan: dict
    rule_text: str = ""
    stem: str | None = None
    with_names: bool = True


# ───────────────────────── 冻结 UI ─────────────────────────


@app.get("/")
def index():
    return FileResponse(UI_FILE, media_type="text/html")


# ───────────────────────── 数据新鲜度 ─────────────────────────


@app.get("/api/data/latest")
def data_latest():
    return executor.data_latest_payload()


# ───────────────────────── 规则识别 ─────────────────────────


@app.post("/api/plan/recognize")
def plan_recognize(req: RecognizeReq):
    text = (req.natural_text or "").strip()
    if not text:
        raise HTTPException(400, detail="规则文本为空")
    # 多规则文档：逐条独立识别，不合并回测
    multi = recognizer.split_multi_rules(text)
    if multi:
        rules = []
        for name, blk in multi:
            r = recognizer.recognize(blk)
            r["rule_name"] = name
            r["rule_text"] = blk
            rules.append(r)
        return {"status": "MULTI", "n_rules": len(rules), "rules": rules}
    return recognizer.recognize(text, universe=req.universe)


@app.post("/api/plan/resolve_ambiguity")
def plan_resolve(req: ResolveReq):
    return recognizer.resolve_ambiguity(req.plan, req.rule_text,
                                        req.choices, req.universe_hint or None)


# ───────────────────────── 回测 ─────────────────────────


def _derive_stem(plan, stem):
    if stem:
        return stem
    return "strategy_" + uuid.uuid4().hex[:10] + "_v1"


@app.post("/api/plan/backtest")
def plan_backtest(req: BacktestReq):
    plan = req.plan
    if not plan or plan.get("kind") != "day_pattern_backward":
        raise HTTPException(400, detail="无效的执行计划")
    if not plan.get("strategy_plan", {}).get("outputs"):
        raise HTTPException(400, detail="执行计划缺少输出指标（outputs 为空），已拒绝执行")
    stem = _derive_stem(plan, req.stem)
    market = executor.data_latest_payload()
    end_date = market["latest_date"]
    if not end_date:
        return JSONResponse({"status": "FAILED", "validation": {
            "valid": False,
            "violations": [{"code": "MISSING_DATA",
                            "detail": "标准本地行情为空，请先更新行情数据"}]}})

    t0 = time.time()
    try:
        rows, columns, meta = executor.run_plan(plan, end_date=end_date)
    except Exception as exc:
        logger.exception("回测执行失败")
        return JSONResponse({"status": "FAILED", "validation": {
            "valid": False,
            "violations": [{"code": "TECHNICAL_FAILURE", "detail": str(exc)}]}})

    # 确定性复核（fail-closed：不通过则不落库、不改 current/previous）
    violations = executor.validate_rows(plan, rows, columns)
    if violations:
        logger.warning("复核未通过: %d 项", len(violations))
        return JSONResponse({"status": "FAILED", "stem": stem, "n_hits": len(rows),
                             "validation": {"valid": False, "violations": violations[:20]}})

    # 成功：保存规则 + current/previous 轮换
    base_rules = recognizer.plan_to_base_rules(plan)
    store.save_rule(stem, req.rule_text, plan, base_rules)
    result, _prev = store.save_success_result(
        stem, columns, rows, len(rows), end_date, meta)

    # Excel（Skill output_excel 依赖 openpyxl；此处直接 pandas 落盘，列序一致）
    rd = store.result_dir(stem)
    df = pd.DataFrame(rows)
    for c in columns:
        if c not in df.columns:
            df[c] = "N/A"
    df = df.reindex(columns=columns)
    xlsx = rd / "current.xlsx"
    df.to_excel(xlsx, index=False)
    logger.info("回测 OK: stem=%s hits=%d 耗时=%.1fs", stem, len(rows), time.time() - t0)

    return {
        "status": "OK",
        "stem": stem,
        "n_hits": len(rows),
        "columns": columns,
        "rows": rows[:500],
        "data_date": end_date,
        "validation": {"valid": True, "violations": []},
        "elapsed_sec": round(time.time() - t0, 1),
    }


# ───────────────────────── 规则持久化 ─────────────────────────


@app.get("/api/rules/{stem}")
def get_rule(stem: str):
    d = store.get_rule(stem)
    if d is None:
        raise HTTPException(404, detail=f"规则不存在: {stem}")
    return d


@app.get("/api/backtest/{stem}/candidates")
def candidates(stem: str, limit: int = 10000):
    res = store.load_result(stem, "current")
    if res is None:
        raise HTTPException(404, detail="该模型尚无成功回测结果")
    return {"columns": res["columns"], "rows": res["rows"][:limit]}


@app.get("/api/backtest/{stem}/candidates/export")
def export_candidates(stem: str, model_name: str = ""):
    xlsx = store.result_dir(stem) / "current.xlsx"
    if not xlsx.exists():
        raise HTTPException(404, detail="该模型尚无成功回测结果")
    safe = (model_name or stem).replace("/", "_").replace("\\", "_")
    return FileResponse(xlsx, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        filename=f"{safe}_回测结果.xlsx")


# ───────────────────────── 每日状态 / 手动更新 ─────────────────────────

_jobs = {}
_jobs_lock = threading.Lock()


@app.get("/api/daily/state")
def daily_state():
    return store.daily_state_payload()


@app.post("/api/daily/run")
def daily_run():
    job_id = uuid.uuid4().hex[:12]
    with _jobs_lock:
        _jobs[job_id] = {"status": "running", "started_at": time.time(), "error": None,
                         "message": "正在检查标准本地行情…"}
    threading.Thread(target=_run_daily_job, args=(job_id,), daemon=True).start()
    return {"job_id": job_id}


def _daily_pipeline(progress_cb):
    """每日管线：增量行情 → 重跑全部模型（失败保护逐模型生效）→ 状态。

    供 手动更新(/api/daily/run) 与 定时调度(工作日 15:45) 共用；pipeline_lock 防重入。
    """
    with _pipeline_lock:
        msgs = []

        def prog(m):
            msgs.append(m)
            progress_cb(m)

        # 1) 增量行情（Provider → 标准化/校验 → 追加；失败回滚不破坏历史）
        prog("正在检查并更新行情数据…")
        summary = provider.update(executor.DAY_DIRS, progress_cb=prog)
        logger.info("Provider update: %s", {k: v for k, v in summary.items()
                                            if k != "errors"})
        if summary["status"] == "NO_DATA":
            raise RuntimeError("标准本地行情为空")
        if summary["status"] == "OK":
            prog(f"已增量写入 {'/'.join(str(d) for d in summary['appended_days'])}"
                 f" 共 {summary['updated_files']} 个标的（跳过 {summary['skipped']}）")
        else:
            prog(f"行情已是最新（{summary.get('local_last')}），无需增量")

        # 2) 行情有更新 → 重跑全部模型（成功才轮换，失败模型保持旧结果）
        market = executor.data_latest_payload()
        latest = market["latest_date"]
        state = store.load_state()
        stems = [s for s, m in state["models"].items() if m.get("plan")]
        reran, kept = 0, 0
        for stem in stems:
            m = state["models"][stem]
            if m.get("current_result", {}).get("data_date") == latest:
                kept += 1          # 已是该交易日结果，跳过
                continue
            try:
                rows, columns, meta = executor.run_plan(m["plan"], end_date=latest)
                violations = executor.validate_rows(m["plan"], rows, columns)
                if violations:
                    raise RuntimeError(f"复核未通过 {len(violations)} 项")
                store.save_success_result(stem, columns, rows, len(rows),
                                          latest, meta)
                rd = store.result_dir(stem)
                df = pd.DataFrame(rows)
                for c in columns:
                    if c not in df.columns:
                        df[c] = "N/A"
                df.reindex(columns=columns).to_excel(rd / "current.xlsx", index=False)
                reran += 1
                prog(f"模型 {stem}: 重跑完成 {len(rows)} 条")
            except Exception:
                kept += 1
                logger.exception("模型 %s 每日重跑失败（保持旧结果）", stem)

        # 3) 状态（new_hits diff 基于新 current vs 旧 previous）
        payload = store.daily_state_payload()
        n_new = sum(1 for m in payload["models"].values() if m["new_hits"])
        return {"latest_date": latest, "provider": summary["status"],
                "reran": reran, "kept": kept, "models_with_new_hits": n_new}


def _run_daily_job(job_id):
    def setj(**kw):
        with _jobs_lock:
            _jobs[job_id].update(kw)

    try:
        out = _daily_pipeline(lambda m: setj(message=m))
        setj(status="done", message=(
            f"行情截至 {out['latest_date']}；重跑 {out['reran']} 个模型，"
            f"{out['models_with_new_hits']} 个模型存在新增命中"),
            data_date=out["latest_date"], provider=out["provider"])
    except Exception as exc:
        logger.exception("daily job failed")
        setj(status="failed", error=str(exc))


# ───────────────────────── 轻量调度（工作日 15:45 + 启动补偿） ─────────────────────────
# 15:45：主源东财日线收盘（15:00）后即定型，不依赖 tushare 的 15~16 点入库窗口；
# 快照快速路径（provider.SNAPSHOT_EARLIEST=15:05）与单模型重跑均在几分钟内完成。

_pipeline_lock = threading.Lock()
SCHEDULE_HOUR, SCHEDULE_MIN = 15, 45


def _next_run_ts():
    """下一个工作日 15:45 的时间戳。"""
    from datetime import datetime, timedelta
    now = datetime.now()
    cand = now.replace(hour=SCHEDULE_HOUR, minute=SCHEDULE_MIN,
                       second=0, microsecond=0)
    if cand <= now or now.weekday() >= 5:
        cand += timedelta(days=1)
    while cand.weekday() >= 5:
        cand += timedelta(days=1)
    return cand.timestamp()


def _scheduler_loop():
    # 启动补偿：若已过当日 15:45 且有模型结果落后于最新行情 → 补跑一次
    from datetime import datetime
    time.sleep(20)
    try:
        market = executor.data_latest_payload()
        state = store.load_state()
        now = datetime.now()
        passed = now.hour > SCHEDULE_HOUR or (
            now.hour == SCHEDULE_HOUR and now.minute >= SCHEDULE_MIN)
        stale = any(m.get("current_result", {}).get("data_date") != market["latest_date"]
                    for m in state["models"].values() if m.get("plan"))
        if passed and now.weekday() < 5 and stale and market["latest_date"]:
            logger.info("启动补偿：模型结果落后于行情，执行每日管线")
            _daily_pipeline(lambda m: logger.info("管线: %s", m))
    except Exception:
        logger.exception("启动补偿失败")
    while True:
        wait = max(1.0, _next_run_ts() - time.time())
        logger.info("调度器：%.0f 小时后执行每日管线", wait / 3600)
        time.sleep(wait)
        try:
            _daily_pipeline(lambda m: logger.info("管线: %s", m))
        except Exception:
            logger.exception("定时管线失败")


@app.on_event("startup")
def _start_scheduler():
    threading.Thread(target=_scheduler_loop, daemon=True).start()


@app.get("/api/daily/jobs/{job_id}")
def daily_job(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, detail="任务不存在")
    return job


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
