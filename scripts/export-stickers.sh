#!/usr/bin/env bash
# 一键：wcdb-key-tool 提取 emoticon.db 密钥 + wxmeme 按微信最新顺序导出
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WCDB_DIR="${WCDB_DIR:-$HOME/Desktop/wcdb-key-tool}"
WECHAT_RESIGNED="${WECHAT_RESIGNED:-$HOME/Applications/WeChat-resigned.app}"
KEYS_FILE="$WCDB_DIR/all_keys.json"

wechat_signature_ok() {
  codesign -vv "$WECHAT_RESIGNED" >/dev/null 2>&1
}

ensure_resigned_wechat() {
  if [[ -d "$WECHAT_RESIGNED" ]] && wechat_signature_ok; then
    echo "wxmeme: 重签名版微信已就绪 $WECHAT_RESIGNED"
    return
  fi

  if [[ -d "$WECHAT_RESIGNED" ]]; then
    echo "wxmeme: 旧副本签名无效，重新复制 …"
    rm -rf "$WECHAT_RESIGNED"
  fi

  echo "wxmeme: 复制微信到 $WECHAT_RESIGNED …"
  mkdir -p "$(dirname "$WECHAT_RESIGNED")"
  ditto /Applications/WeChat.app "$WECHAT_RESIGNED"

  echo "wxmeme: 重签名微信（去除 Hardened Runtime）…"
  xattr -cr "$WECHAT_RESIGNED" 2>/dev/null || true

  if ! codesign --force --sign - "$WECHAT_RESIGNED" 2>&1; then
    if wechat_signature_ok; then
      echo "wxmeme: codesign 有警告，但签名验证通过，继续"
    else
      echo "错误: 无法重签名微信。请确认："
      echo "  1. 系统设置 → 隐私与安全性 → 已允许终端/ Cursor"
      echo "  2. 或手动运行: ditto /Applications/WeChat.app $WECHAT_RESIGNED && codesign --force --sign - $WECHAT_RESIGNED"
      exit 1
    fi
  fi

  echo "wxmeme: 签名验证通过"
}

find_db_dir() {
  find "$HOME/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files" \
    -maxdepth 2 -type d -name db_storage 2>/dev/null | head -1
}

ensure_wcdb_tool() {
  if [[ -f "$WCDB_DIR/wcdb_key_tool_macos.py" ]]; then
    return
  fi
  echo "wxmeme: 克隆 wcdb-key-tool …"
  git clone --depth 1 https://github.com/TANGandXUE/wcdb-key-tool.git "$WCDB_DIR"
}

launch_resigned_wechat() {
  echo "wxmeme: 启动重签名版微信 …"
  osascript -e 'tell application "WeChat" to quit' 2>/dev/null || true
  sleep 2
  killall WeChat 2>/dev/null || true
  sleep 1
  open "$WECHAT_RESIGNED"
  for _ in $(seq 1 30); do
    pgrep -x WeChat >/dev/null && break
    sleep 1
  done
  pgrep -x WeChat >/dev/null || { echo "错误: 微信未能启动"; exit 1; }
  echo "wxmeme: 微信已启动 (PID $(pgrep -x WeChat | head -1))，等待 5 秒 …"
  sleep 5
}

extract_keys() {
  local db_dir="$1"
  if [[ -f "$KEYS_FILE" ]]; then
    if python3 - <<PY
import json, sys
from pathlib import Path
sys.path.insert(0, "$WCDB_DIR")
# quick check: emoticon key exists
data = json.loads(Path("$KEYS_FILE").read_text())
key = data.get("emoticon/emoticon.db", {}).get("enc_key")
sys.exit(0 if key else 1)
PY
    then
      echo "wxmeme: 已有有效密钥 $KEYS_FILE"
      return
    fi
  fi

  echo ""
  echo "============================================================"
  echo " 首次提取需要在微信里重新登录一次（约 3 分钟内完成）"
  echo "  1. 微信 → 设置"
  echo "  2. 退出登录"
  echo "  3. 重新扫码登录"
  echo "============================================================"
  echo ""
  osascript -e 'display notification "请退出登录并重新登录微信" with title "wxmeme 提取密钥" sound name "Glass"' || true

  if [[ "${WXMEME_FROZEN:-}" == "1" && -n "${WXMEME_PYTHON:-}" ]]; then
    if ! "$WXMEME_PYTHON" --wcdb \
      --db-dir "$db_dir" \
      --output "$KEYS_FILE" \
      --timeout 180; then
      echo ""
      echo "密钥提取未完成。请在脚本提示的 3 分钟内完成「退出登录 → 重新登录」，然后重新运行："
      echo "  bash scripts/export-stickers.sh"
      exit 1
    fi
    return
  fi

  if ! python3 "$ROOT/exporter/wcdb_extract.py" \
    --db-dir "$db_dir" \
    --output "$KEYS_FILE" \
    --timeout 180; then
    echo ""
    echo "密钥提取未完成。请在脚本提示的 3 分钟内完成「退出登录 → 重新登录」，然后重新运行："
    echo "  bash scripts/export-stickers.sh"
    exit 1
  fi
}

run_export() {
  cd "$ROOT"
  if [[ "${WXMEME_FROZEN:-}" == "1" && -n "${WXMEME_PYTHON:-}" ]]; then
    "$WXMEME_PYTHON" --cli --wcdb-keys "$KEYS_FILE" --cdn --scan-only "$@"
    return
  fi
  if [[ ! -d .venv ]]; then
    python3 -m venv .venv
  fi
  # shellcheck disable=SC1091
  source .venv/bin/activate
  pip3 install -q -r exporter/requirements.txt
  python3 exporter/wxmeme.py --wcdb-keys "$KEYS_FILE" --cdn --scan-only "$@"
}

main() {
  DB_DIR="${DB_DIR:-$(find_db_dir)}"
  if [[ -z "$DB_DIR" ]]; then
    echo "错误: 未找到微信 db_storage 目录"
    exit 1
  fi
  echo "wxmeme: 数据库目录 $DB_DIR"

  ensure_wcdb_tool
  ensure_resigned_wechat
  launch_resigned_wechat
  extract_keys "$DB_DIR" || exit 1
  run_export "$@"
  echo ""
  echo "wxmeme: 完成 -> $HOME/Downloads/wxmeme/library"
}

main "$@"
