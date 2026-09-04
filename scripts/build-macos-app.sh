#!/usr/bin/env bash
# 打包 macOS 应用 wxmeme.app
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="$ROOT/dist"
APP="$DIST/wxmeme.app"
PAYLOAD="$APP/Contents/Resources/project"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$PAYLOAD"

cp "$ROOT/app/Info.plist" "$APP/Contents/Info.plist"
cp "$ROOT/extension/icons/icon128.png" "$APP/Contents/Resources/AppIcon.png"

cat > "$APP/Contents/MacOS/wxmeme" <<'LAUNCHER'
#!/bin/bash
DIR="$(cd "$(dirname "$0")/../Resources/project" && pwd)"
cd "$DIR"
exec /usr/bin/python3 "$DIR/app/gui.py"
LAUNCHER
chmod +x "$APP/Contents/MacOS/wxmeme"

rsync -a \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude 'dist' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude 'library' \
  "$ROOT/exporter" \
  "$ROOT/scripts" \
  "$PAYLOAD/"

mkdir -p "$PAYLOAD/app"
cp "$ROOT/app/gui.py" "$PAYLOAD/app/gui.py"

xattr -cr "$APP" 2>/dev/null || true
codesign --force --sign - "$APP" 2>/dev/null || true

echo "wxmeme: App 已打包 -> $APP"
echo "双击运行，或: open \"$APP\""
