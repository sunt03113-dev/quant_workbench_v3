#!/usr/bin/env bash
# Quant Workbench —— macOS 启动器（.app / LaunchAgent / 手工调用 共用）
#
# 用法：
#   bash deploy/mac/qwb_launch.sh open     # 确保后端在跑并打开浏览器（.app 双击走这里）
#   bash deploy/mac/qwb_launch.sh serve    # 前台托管（LaunchAgent 登录自启用）
#   bash deploy/mac/qwb_launch.sh status   # 查看状态
#   bash deploy/mac/qwb_launch.sh stop     # 停止后端
#   bash deploy/mac/qwb_launch.sh setup    # 首次初始化（建 venv + 装依赖）
#
# 路径解析沿用 app/paths.py：环境变量 > app/config.yaml > 平台默认；
# 本脚本只负责把 PKG_ROOT 下的目录用环境变量指好，不写任何配置文件。
set -uo pipefail

MAC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_ROOT="${QWB_PKG_ROOT:-$(cd "$MAC_DIR/../.." && pwd)}"
export QWB_PKG_ROOT="$PKG_ROOT"

# .app / launchd 启动时 PATH 极简，必须自行补全（Homebrew + 系统目录）
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

# 可选本机覆盖（不进 Git）：PKG_ROOT/.qwb_env
if [ -f "$PKG_ROOT/.qwb_env" ]; then
  # shellcheck disable=SC1090
  . "$PKG_ROOT/.qwb_env"
fi

export QWB_APPDATA_DIR="${QWB_APPDATA_DIR:-$PKG_ROOT/appdata}"
export QWB_SKILL_DIR="${QWB_SKILL_DIR:-$PKG_ROOT/skill/tdx-stock-backtest-master}"
export QWB_UI_FILE="${QWB_UI_FILE:-$PKG_ROOT/ui/ui_v2.html}"
export QWB_HOST="${QWB_HOST:-127.0.0.1}"
export QWB_PORT="${QWB_PORT:-8000}"

VENV="$PKG_ROOT/.venv"
PY="$VENV/bin/python"
URL="http://${QWB_HOST}:${QWB_PORT}"
LOG_DIR="$QWB_APPDATA_DIR/logs"
LOG="$LOG_DIR/server.log"
PIDFILE="$LOG_DIR/server.pid"

# 系统工具（macOS 下都在固定路径；用 command -v 兜底，便于异机/CI 验证）
CURL="$(command -v curl 2>/dev/null || echo /usr/bin/curl)"
OPEN="$(command -v open 2>/dev/null || echo /usr/bin/open)"
SLEEP="$(command -v sleep 2>/dev/null || echo /bin/sleep)"
MKDIR="$(command -v mkdir 2>/dev/null || echo /bin/mkdir)"
RM="$(command -v rm 2>/dev/null || echo /bin/rm)"
OSASCRIPT="/usr/bin/osascript"

say() { printf '[qwb] %s\n' "$*"; }

# 图形提示（失败时让用户看得见，不至于"双击了没反应"）
note() {
  [ -x "$OSASCRIPT" ] || return 0
  local msg="${1//\"/}"
  "$OSASCRIPT" -e "display dialog \"$msg\" buttons {\"好\"} default button 1 with title \"量化工作台\"" >/dev/null 2>&1 || true
}

# 就绪判据：GET /api/daily/state 有响应
is_up() { "$CURL" -fsS -m 3 "$URL/api/daily/state" >/dev/null 2>&1; }

ensure_venv() {
  if [ -x "$PY" ]; then return 0; fi
  say "未发现 venv，执行首次初始化"
  note "首次使用，正在初始化运行环境（建 venv 并安装依赖，约 2-5 分钟），完成后会自动打开工作台。"
  "$MKDIR" -p "$LOG_DIR"
  if ! /bin/bash "$PKG_ROOT/deploy/bootstrap.sh" setup >"$LOG_DIR/setup.log" 2>&1; then
    say "[ERROR] 初始化失败，详见 $LOG_DIR/setup.log"
    note "初始化失败，请把 appdata/logs/setup.log 发给管理员。"
    return 1
  fi
  say "初始化完成"
}

start_bg() {
  "$MKDIR" -p "$LOG_DIR"
  ( cd "$PKG_ROOT/app" && /usr/bin/nohup "$PY" -X utf8 server.py >>"$LOG" 2>&1 & echo $! >"$PIDFILE" )
  say "后端启动中（日志：$LOG）"
}

wait_up() { # $1 = 超时秒数
  local t="${1:-60}" i=0
  while [ "$i" -lt "$t" ]; do
    if is_up; then return 0; fi
    "$SLEEP" 1
    i=$((i + 1))
  done
  return 1
}

cmd_open() {
  ensure_venv || return 1
  if is_up; then
    say "后端已在运行"
  else
    start_bg
    if ! wait_up 120; then
      say "[ERROR] 后端 120s 内未就绪"
      note "后端启动失败，请查看 appdata/logs/server.log。"
      return 1
    fi
  fi
  "$OPEN" "$URL"
  say "已打开 $URL"
}

# 前台托管：由 launchd 拉起；若已有实例则等它退出后再接管（避免 KeepAlive 空转）
cmd_serve() {
  ensure_venv || exit 1
  "$MKDIR" -p "$LOG_DIR"
  if is_up; then
    say "已有实例在运行，等待其退出后接管…"
    while is_up; do "$SLEEP" 5; done
  fi
  ( if wait_up 120; then "$OPEN" "$URL"; fi ) &
  cd "$PKG_ROOT/app"
  say "前台托管启动 $URL"
  exec "$PY" -X utf8 server.py
}

cmd_status() {
  say "PKG_ROOT = $PKG_ROOT"
  say "URL      = $URL"
  say "APPDATA  = $QWB_APPDATA_DIR"
  if is_up; then say "状态     = 运行中"; else say "状态     = 未运行"; fi
  if [ -f "$PIDFILE" ]; then say "PID 文件 = $(cat "$PIDFILE" 2>/dev/null)"; fi
  if command -v lsof >/dev/null 2>&1; then
    local listen
    listen="$(lsof -nP -iTCP:"$QWB_PORT" -sTCP:LISTEN 2>/dev/null | tail -n +2 | awk '{print $2}' | tr '\n' ' ')"
    say "监听进程 = ${listen:-无}"
  fi
}

cmd_stop() {
  local pids=""
  if command -v lsof >/dev/null 2>&1; then
    pids="$(lsof -tiTCP:"$QWB_PORT" -sTCP:LISTEN 2>/dev/null || true)"
  fi
  if [ -z "$pids" ] && [ -f "$PIDFILE" ]; then pids="$(cat "$PIDFILE" 2>/dev/null || true)"; fi
  if [ -z "$pids" ]; then say "未发现运行中的后端"; return 0; fi
  # shellcheck disable=SC2086
  kill $pids 2>/dev/null || true
  "$SLEEP" 1
  say "已停止：$pids"
  "$RM" -f "$PIDFILE"
}

case "${1:-open}" in
  open | start) cmd_open ;;
  serve)        cmd_serve ;;
  status)       cmd_status ;;
  stop)         cmd_stop ;;
  setup)        ensure_venv ;;
  *)            say "未知子命令: $1（可用 open | serve | status | stop | setup）"; exit 2 ;;
esac
