#!/usr/bin/env bash
# PyInstaller 独立版 macOS App（内置 Python，无需本机安装）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="$ROOT/dist"
BUILD_VENV="$ROOT/.build-venv"

echo "wxmeme: 准备 PyInstaller 构建环境 …"
python3 -m venv "$BUILD_VENV"
# shellcheck disable=SC1091
source "$BUILD_VENV/bin/activate"
pip install -q -U pip
pip install -q -r "$ROOT/requirements-build.txt"

rm -rf "$ROOT/build" "$DIST/wxmeme-standalone.app" "$DIST/wxmeme"

echo "wxmeme: 正在打包（约 1-2 分钟）…"
pyinstaller "$ROOT/app/wxmeme.spec" --noconfirm --distpath "$DIST" --workpath "$ROOT/build"

if [[ -d "$DIST/wxmeme-standalone.app" ]]; then
  xattr -cr "$DIST/wxmeme-standalone.app" 2>/dev/null || true
  codesign --force --sign - "$DIST/wxmeme-standalone.app" 2>/dev/null || true
fi

echo ""
echo "wxmeme: 独立版 App -> $DIST/wxmeme-standalone.app"
echo "双击运行，无需安装 Python。"
echo ""
echo "验证 CLI:"
echo "  \"$DIST/wxmeme-standalone.app/Contents/MacOS/wxmeme\" --cli --help"
