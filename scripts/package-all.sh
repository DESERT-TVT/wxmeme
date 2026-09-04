#!/usr/bin/env bash
# 一键打包：浏览器插件 ZIP + 轻量 App + PyInstaller 独立版
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
bash "$ROOT/scripts/package-extension.sh"
bash "$ROOT/scripts/build-macos-app.sh"
bash "$ROOT/scripts/build-standalone-app.sh"
echo ""
echo "wxmeme: 全部打包完成 -> $ROOT/dist/"
echo "  - wxmeme-extension.zip      浏览器插件"
echo "  - wxmeme.app                轻量版（需系统 Python）"
echo "  - wxmeme-standalone.app     独立版（推荐分发）"
