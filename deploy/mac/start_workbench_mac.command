#!/usr/bin/env bash
# 双击即用（macOS 兜底入口）：Finder 双击本文件 -> 终端里跑起后端并自动打开浏览器。
# 注：正式入口建议用 install_mac_launcher.sh 生成的 .app（不弹终端窗口）。
#
# 若双击提示"没有权限"，先在终端执行：
#   chmod +x deploy/mac/start_workbench_mac.command
# 若提示"来自身份不明的开发者"，右键 -> 打开 -> 仍要打开。
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec /bin/bash "$HERE/qwb_launch.sh" open
