"""Standalone in-app preview window (embedded WebKit, no external browser)."""

from __future__ import annotations

import argparse
import shutil
import socket
import threading
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

from platform_utils import downloads_dir, reveal_in_folder


def _server_ready(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=1) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _port_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _standalone_args() -> argparse.Namespace:
    import wxmeme

    keys_file = wxmeme.find_wcdb_keys_file("auto")
    return argparse.Namespace(
        emoticon_key=None,
        seed=None,
        wxid=None,
        db_key=None,
        decrypted_db=None,
        msg_key=None,
        cdn=True,
        force_fav_archive=False,
        sync_persist=keys_file is None,
        wcdb_keys=str(keys_file) if keys_file else None,
    )


class WxmemeApi:
    """Native save helpers for embedded WebView (download links do not work reliably)."""

    def save_sticker(self, name: str) -> dict:
        import wxmeme

        safe = Path(name).name
        src = (wxmeme.LIBRARY / safe).resolve()
        if src.parent != wxmeme.LIBRARY.resolve() or not src.is_file():
            return {"ok": False, "error": "文件不存在"}
        dest_dir = downloads_dir() / "wxmeme" / "picked"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / safe
        shutil.copy2(src, dest)
        reveal_in_folder(dest)
        return {"ok": True, "path": str(dest)}

    def save_zip(self) -> dict:
        import wxmeme

        try:
            zip_path = wxmeme.build_stickers_zip()
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        reveal_in_folder(zip_path)
        return {"ok": True, "path": str(zip_path)}


def run_webview_ui(bootstrap_exporter, log_error) -> int:
    import webview

    bootstrap_exporter()
    import wxmeme

    port = wxmeme.PORT
    url = f"http://127.0.0.1:{port}/"
    args = _standalone_args()
    config = wxmeme.build_config(args)
    paths = wxmeme.discover_paths()
    server_lock = threading.Lock()
    server_started = False
    export_error: list[str] = []

    def ensure_server() -> None:
        nonlocal server_started
        with server_lock:
            if server_started or _server_ready(url):
                server_started = True
                return
            if _port_busy(port):
                for _ in range(50):
                    if _server_ready(url):
                        server_started = True
                        return
                    time.sleep(0.1)
            wxmeme.start_server_thread(port, config, paths)
            for _ in range(50):
                if _server_ready(url):
                    server_started = True
                    return
                time.sleep(0.1)
            raise RuntimeError(f"无法启动预览服务 {url}")

    def do_export() -> None:
        try:
            wxmeme.export_library(config, paths)
        except Exception:
            export_error.append(traceback.format_exc())
            wxmeme._set_export_status(done=True, phase="error", message="导出失败")

    try:
        ensure_server()
    except Exception:
        message = traceback.format_exc()
        log_error(message)
        _show_error_window(webview, message)
        return 1

    status = wxmeme.export_status_snapshot()
    if status.get("done", True):
        threading.Thread(target=do_export, daemon=True, name="wxmeme-export").start()

    window = webview.create_window(
        "wxmeme 我的表情",
        url,
        width=1024,
        height=760,
        min_size=(640, 480),
        js_api=WxmemeApi(),
    )
    webview.start()
    if export_error:
        log_error(export_error[0])
    return 0


def _show_error_window(webview, message: str) -> None:
    safe = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html = f"""<!DOCTYPE html><html><body style="font-family:sans-serif;padding:24px;background:#101010;color:#fff">
    <h2>wxmeme 启动失败</h2><pre style="white-space:pre-wrap">{safe}</pre></body></html>"""
    webview.create_window("wxmeme", html=html, width=640, height=420)
    webview.start()
