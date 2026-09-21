#!/usr/bin/env bash
# Quant Workbench 一键部署 / 启动（macOS · Apple Silicon / Linux）
#
# 用法：
#   ./deploy/bootstrap.sh check          # 只做依赖与环境自检
#   ./deploy/bootstrap.sh setup          # 建 venv 并安装依赖
#   ./deploy/bootstrap.sh serve          # 启动后端（前台）
#   ./deploy/bootstrap.sh p9 collect mac # 采集本端 P9 证据
#
# 环境变量（可选，覆盖 app/config.yaml；见 deploy/config.example.yaml）：
#   QWB_APPDATA_DIR  QWB_SKILL_DIR  QWB_UI_FILE  QWB_HOST  QWB_PORT
set -euo pipefail

PKG_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${QWB_VENV:-$PKG_ROOT/.venv}"
PY="${PYTHON:-python3}"

info() { printf '[qwb] %s\n' "$*"; }
die()  { printf '[qwb][ERROR] %s\n' "$*" >&2; exit 1; }

cmd_setup() {
  info "package root: $PKG_ROOT"
  "$PY" -V || die "找不到 python3"
  if [ ! -d "$VENV" ]; then
    info "创建 venv: $VENV"
    "$PY" -m venv "$VENV"
  fi
  # shellcheck disable=SC1091
  "$VENV/bin/python" -m pip install --upgrade pip >/dev/null
  info "安装依赖（deploy/requirements.txt）"
  "$VENV/bin/python" -m pip install -r "$PKG_ROOT/deploy/requirements.txt"
  info "依赖安装完成"
  cmd_check
}

cmd_check() {
  local py="$VENV/bin/python"
  [ -x "$py" ] || py="$PY"
  info "使用解释器: $py"
  "$py" - <<'PYEOF'
import importlib, sys
sys.path.insert(0, "app")
need = ["numpy", "pandas", "openpyxl", "fastapi", "uvicorn", "yaml", "tqdm", "akshare"]
bad = []
for m in need:
    try:
        importlib.import_module(m)
    except Exception as e:
        bad.append(f"{m}: {type(e).__name__}: {e}")
print("[qwb] python", sys.version.split()[0])
if bad:
    print("[qwb][ERROR] 缺少依赖：")
    for b in bad:
        print("   ", b)
    sys.exit(1)
print("[qwb] 依赖自检通过")
import paths, json
print("[qwb] 路径解析:", json.dumps(paths.describe(), ensure_ascii=False))
from pathlib import Path
asrc = paths.PATH_SOURCES.get("appdata")
if asrc and asrc.startswith("config:") and not Path(paths.APPDATA).exists():
    print("[qwb][ERROR] 检测到随包携带的 app/config.yaml（开发机绝对路径），"
          "当前机器上该路径不存在。")
    print("             请移走 app/config.yaml，改用环境变量 QWB_APPDATA_DIR / QWB_SKILL_DIR / QWB_UI_FILE。")
    sys.exit(1)
missing = [d for d in paths.DAY_DIRS if not Path(d).exists()]
if missing:
    print("[qwb][WARN] 标准行情目录不存在（需先导入行情包）：")
    for m in missing:
        print("   ", m)
PYEOF
}

cmd_serve() {
  local py="$VENV/bin/python"
  [ -x "$py" ] || die "venv 不存在，先运行: ./deploy/bootstrap.sh setup"
  cd "$PKG_ROOT/app"
  info "启动后端 http://${QWB_HOST:-127.0.0.1}:${QWB_PORT:-8000}"
  exec "$py" -X utf8 server.py
}

cmd_p9() {
  local py="$VENV/bin/python"
  [ -x "$py" ] || py="$PY"
  cd "$PKG_ROOT"
  exec "$py" -X utf8 app/p9_evidence.py "${@:-collect --label mac}"
}

case "${1:-check}" in
  setup)   cmd_setup ;;
  check)   cmd_check ;;
  serve)   cmd_serve ;;
  p9)      shift; cmd_p9 "$@" ;;
  *) die "未知子命令: $1（可用: setup | check | serve | p9）" ;;
esac
