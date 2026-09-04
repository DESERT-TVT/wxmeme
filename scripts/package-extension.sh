#!/usr/bin/env bash
# 打包 Chrome / Edge 浏览器插件为 ZIP
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="$ROOT/dist"
ZIP="$DIST/wxmeme-extension.zip"

mkdir -p "$DIST"
rm -f "$ZIP"

(
  cd "$ROOT/extension"
  zip -r "$ZIP" . -x "*.DS_Store" -x "__MACOSX/*"
)

echo "wxmeme: 插件已打包 -> $ZIP"
echo ""
echo "安装方式："
echo "  1. 解压 $ZIP"
echo "  2. Chrome 打开 chrome://extensions"
echo "  3. 开启「开发者模式」→「加载已解压的扩展程序」→ 选解压后的文件夹"
echo ""
echo "或直接加载源码目录: $ROOT/extension"
