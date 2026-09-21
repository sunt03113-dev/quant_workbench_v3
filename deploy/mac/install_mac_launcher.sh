#!/usr/bin/env bash
# Quant Workbench —— 在 macOS 上安装「双击即用」入口
#
# 做什么：
#   1) 生成 ~/Applications/QuantWorkbench.app（双击即用，无终端窗口，自动开后端 + 开浏览器）
#   2) 在桌面放一个快捷方式「量化工作台.app」
#   3) 可选：装 LaunchAgent 登录自启（开机后台起服务，用户连双击都不需要）
#   4) 可选：把图标加进 Dock
#
# 用法（在包根目录执行）：
#   bash deploy/mac/install_mac_launcher.sh              # 只建 .app + 桌面快捷方式
#   bash deploy/mac/install_mac_launcher.sh --login      # 额外安装登录自启
#   bash deploy/mac/install_mac_launcher.sh --dock       # 额外加入 Dock
#   bash deploy/mac/install_mac_launcher.sh --uninstall  # 全部卸载
set -uo pipefail

MAC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_ROOT="$(cd "$MAC_DIR/../.." && pwd)"

APP_DIR="$HOME/Applications/QuantWorkbench.app"
DESK_LINK="$HOME/Desktop/量化工作台.app"
AGENT_LABEL="com.qwb.workbench.server"
AGENT="$HOME/Library/LaunchAgents/$AGENT_LABEL.plist"
LOG_DIR="$PKG_ROOT/appdata/logs"

DO_LOGIN=0
DO_DOCK=0
DO_UNINSTALL=0
for a in "$@"; do
  case "$a" in
    --login)     DO_LOGIN=1 ;;
    --dock)      DO_DOCK=1 ;;
    --uninstall) DO_UNINSTALL=1 ;;
    *)           echo "[qwb] 未知参数: $a"; exit 2 ;;
  esac
done

say() { printf '[qwb] %s\n' "$*"; }

prep_perms() {
  /bin/chmod +x "$PKG_ROOT/deploy/bootstrap.sh" "$MAC_DIR"/*.sh "$MAC_DIR"/*.command 2>/dev/null || true
  # 去掉下载/拷贝带来的隔离属性，避免 Gatekeeper 拦 .app
  /usr/bin/xattr -dr com.apple.quarantine "$PKG_ROOT" 2>/dev/null || true
}

make_app() {
  /bin/mkdir -p "$HOME/Applications" "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Resources"
  cat >"$APP_DIR/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>QuantWorkbench</string>
  <key>CFBundleDisplayName</key><string>量化工作台</string>
  <key>CFBundleIdentifier</key><string>com.qwb.workbench.launcher</string>
  <key>CFBundleExecutable</key><string>QuantWorkbench</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>LSUIElement</key><true/>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

  # 启动器：不弹终端，直接调 qwb_launch.sh open
  cat >"$APP_DIR/Contents/MacOS/QuantWorkbench" <<EOF
#!/bin/bash
export QWB_PKG_ROOT="$PKG_ROOT"
exec /bin/bash "$PKG_ROOT/deploy/mac/qwb_launch.sh" open
EOF
  /bin/chmod +x "$APP_DIR/Contents/MacOS/QuantWorkbench"
  if command -v codesign >/dev/null 2>&1; then
    /usr/bin/codesign --force --sign - "$APP_DIR" >/dev/null 2>&1 || true
  fi
  say "已生成 $APP_DIR"
}

make_desktop_link() {
  if [ -d "$HOME/Desktop" ]; then
    /bin/ln -sfn "$APP_DIR" "$DESK_LINK" && say "桌面快捷方式：$DESK_LINK"
  else
    say "[WARN] 未找到 ~/Desktop，跳过桌面快捷方式"
  fi
}

install_agent() {
  /bin/mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"
  cat >"$AGENT" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$AGENT_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$PKG_ROOT/deploy/mac/qwb_launch.sh</string>
    <string>serve</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>QWB_PKG_ROOT</key><string>$PKG_ROOT</string>
  </dict>
  <key>WorkingDirectory</key><string>$PKG_ROOT</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$LOG_DIR/server.launchd.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/server.launchd.err.log</string>
</dict>
</plist>
EOF

  launchctl bootout "gui/$(id -u)/$AGENT_LABEL" >/dev/null 2>&1 || true
  if launchctl bootstrap "gui/$(id -u)" "$AGENT" >/dev/null 2>&1; then
    say "登录自启已安装（launchctl bootstrap）"
  elif launchctl load -w "$AGENT" >/dev/null 2>&1; then
    say "登录自启已安装（launchctl load）"
  else
    say "[WARN] LaunchAgent 加载失败，请手工执行：launchctl bootstrap gui/\$(id -u) $AGENT"
  fi
  launchctl kickstart -k "gui/$(id -u)/$AGENT_LABEL" >/dev/null 2>&1 || true
  say "服务随即启动，日志：$LOG_DIR/server.launchd.log / server.log"
}

add_to_dock() {
  /usr/bin/defaults write com.apple.dock persistent-apps -array-add \
    "<dict><key>tile-data</key><dict><key>file-data</key><dict><key>_CFURLString</key><string>$APP_DIR</string><key>_CFURLStringType</key><integer>0</integer></dict></dict></dict>" \
    2>/dev/null && say "已加入 Dock（立即生效）"
  /usr/bin/killall Dock >/dev/null 2>&1 || true
}

uninstall_all() {
  launchctl bootout "gui/$(id -u)/$AGENT_LABEL" >/dev/null 2>&1 || true
  launchctl unload -w "$AGENT" >/dev/null 2>&1 || true
  /bin/rm -f "$AGENT"
  /bin/rm -rf "$APP_DIR"
  /bin/rm -f "$DESK_LINK"
  say "已卸载 .app / 桌面快捷方式 / 登录自启"
  if command -v lsof >/dev/null 2>&1; then
    local pids
    pids="$(lsof -tiTCP:8000 -sTCP:LISTEN 2>/dev/null || true)"
    if [ -n "$pids" ]; then
      # shellcheck disable=SC2086
      kill $pids 2>/dev/null || true
      say "已停止后端：$pids"
    fi
  fi
}

if [ "$DO_UNINSTALL" = "1" ]; then
  uninstall_all
  exit 0
fi

prep_perms
make_app
make_desktop_link
[ "$DO_LOGIN" = "1" ] && install_agent
[ "$DO_DOCK" = "1" ] && add_to_dock

echo
say "安装完成。"
say "  · 双击 ${HOME}/Desktop/量化工作台.app  ->  后台起服务 + 自动开浏览器"
say "  · 不想用双击、要开机自动可用：bash deploy/mac/install_mac_launcher.sh --login"
say "  · 手头没图形界面时：bash deploy/mac/qwb_launch.sh open | status | stop"
