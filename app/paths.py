# -*- coding: utf-8 -*-
"""Quant Workbench 路径与配置加载（跨平台，无盘符硬编码）。

解析优先级（高 -> 低）：
  1. 环境变量：QWB_APPDATA_DIR / QWB_SKILL_DIR / QWB_UI_FILE / QWB_HOST / QWB_PORT
  2. 本机配置：app/config.yaml（若存在；仅作"本机覆盖"，不随分发包传递）
  3. 平台默认：平台应用数据目录 / 包内相对路径

分发给最终用户（如 M4）时不携带 app/config.yaml，
以环境变量或平台默认目录解析，见 deploy/README_DEPLOY.md。

每个路径的解析来源记录在 PATH_SOURCES，供排障与验收证据引用。
"""
import os
import sys
from pathlib import Path

import yaml

APP_DIR = Path(__file__).parent.resolve()
WORKSPACE = APP_DIR.parent

APP_NAME = "QuantWorkbench"

# 标准本地行情 schema 版本（DATA.md 契约；变更须同步证据清单）
MARKET_SCHEMA_VERSION = 1
MARKET_SCHEMA_FIELDS = [
    "symbol", "trade_date", "open", "high", "low", "close",
    "pre_close", "volume", "amount",
]
MARKET_PHYSICAL_FORMAT = "tdx-day-compat-32B"  # date(i32)+OHLC(i32分)+amount(f32元)+volume(i32股)+reserved(i32)


def _platform_appdata() -> Path:
    """平台应用数据目录（不依赖盘符/用户名硬编码）。"""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        return (Path(base) if base else Path.home() / "AppData" / "Local") / APP_NAME
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local" / "share") / APP_NAME


_cfg_path = APP_DIR / "config.yaml"
CFG = {}
CONFIG_SOURCE = "none"
if _cfg_path.exists():
    try:
        CFG = yaml.safe_load(_cfg_path.read_text(encoding="utf-8")) or {}
        CONFIG_SOURCE = f"file:{_cfg_path.name}"
    except Exception:  # noqa: BLE001
        CFG = {}

PATH_SOURCES = {}


def _pick(env_key, cfg_key, default, tag) -> Path:
    v = os.environ.get(env_key)
    if v:
        PATH_SOURCES[tag] = f"env:{env_key}"
        return Path(v).expanduser()
    if CFG.get(cfg_key):
        PATH_SOURCES[tag] = f"config:{cfg_key}"
        return Path(CFG[cfg_key]).expanduser()
    PATH_SOURCES[tag] = "platform-default" if tag == "appdata" else "package-relative"
    return Path(default).expanduser()


APPDATA = _pick("QWB_APPDATA_DIR", "appdata_dir", _platform_appdata(), "appdata").resolve()
SKILL_DIR = _pick("QWB_SKILL_DIR", "skill_dir",
                  WORKSPACE / "skill" / "tdx-stock-backtest-master", "skill").resolve()
UI_FILE = _pick("QWB_UI_FILE", "ui_file",
                WORKSPACE / "ui" / "ui_v2.html", "ui").resolve()
HOST = os.environ.get("QWB_HOST") or CFG.get("host", "127.0.0.1")
PORT = int(os.environ.get("QWB_PORT") or CFG.get("port", 8000))

# ── 标准本地行情（TDX .day 兼容二进制，物理与程序分离，不入 Git）──
MARKET_DIR = APPDATA / "market"
VIPDOC_DIR = MARKET_DIR / "vipdoc"
DAY_DIRS = [str(VIPDOC_DIR / "sh" / "lday"), str(VIPDOC_DIR / "sz" / "lday")]

# ── 产品状态 ──
STATE_DIR = APPDATA / "state"
STATE_FILE = STATE_DIR / "state.json"
RESULTS_DIR = STATE_DIR / "results"

# ── 名称缓存 / 数据缓存 ──
STOCK_NAMES_FILE = APPDATA / "stock_names.csv"
DATA_CACHE = APPDATA / "cache" / "day_xlsx"

for _d in (STATE_DIR, RESULTS_DIR, DATA_CACHE):
    _d.mkdir(parents=True, exist_ok=True)

# Skill 模块会在 import 时写日志到 /tmp/stock_backtest_run.log（Windows 下为当前盘根 \tmp）
_TMP = Path("/tmp")
if not _TMP.exists():
    try:
        _TMP.mkdir(parents=True)
    except OSError:
        pass


def describe():
    """配置摘要（供验收证据与排障）。不含任何密钥。"""
    return {
        "platform": sys.platform,
        "config_source": CONFIG_SOURCE,
        "path_sources": dict(PATH_SOURCES),
        "appdata_dir": str(APPDATA),
        "skill_dir": str(SKILL_DIR),
        "ui_file": str(UI_FILE),
        "host": HOST,
        "port": PORT,
        "market_schema_version": MARKET_SCHEMA_VERSION,
        "market_physical_format": MARKET_PHYSICAL_FORMAT,
        "day_dirs": list(DAY_DIRS),
    }


def ensure_skill_config():
    """通过 Skill 自带的 config.yaml 机制注入路径（Skill 设计支持的用户配置，不改 Skill 代码）。

    tdx_base -> 标准本地行情根（Skill 读取 <tdx_base>/vipdoc/{sh,sz}/lday/*.day）
    """
    cfg_file = SKILL_DIR / "config.yaml"
    want = {
        "tdx_base": str(MARKET_DIR),
        "data_cache": str(DATA_CACHE),
        "stock_names_file": str(STOCK_NAMES_FILE),
    }
    current = {}
    if cfg_file.exists():
        try:
            current = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001
            current = {}
    if current != want:
        import logging
        logging.getLogger("qwb").info("写入 Skill 路径配置: %s", cfg_file)
        cfg_file.write_text(
            "# Quant Workbench 注入的标准行情路径配置（Skill 自带机制，程序自动生成）\n"
            + yaml.safe_dump(want, allow_unicode=True),
            encoding="utf-8",
        )
    return cfg_file


def load_skill_modules():
    """按 Skill 冻结代码原样 import（业务定义唯一权威来源），返回共享底座模块。

    必须先 ensure_skill_config() 再 import（Skill 在 import 时读 config.yaml）。
    """
    ensure_skill_config()
    sk = str(SKILL_DIR)
    if sk not in sys.path:
        sys.path.insert(0, sk)
    import backtest_common as bc
    import StockBacktest_TdxAutoRun0630 as sbt
    import importlib
    r0814 = importlib.import_module("0814_backtest")
    return bc, sbt, r0814
