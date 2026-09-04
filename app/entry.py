#!/usr/bin/env python3
"""Unified entry: GUI, wxmeme CLI, or wcdb_extract CLI (for PyInstaller)."""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path


def _log_path() -> Path:
    from platform_utils import downloads_dir

    path = downloads_dir() / "wxmeme" / "app.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _write_log(message: str) -> None:
    try:
        _log_path().write_text(message, encoding="utf-8")
    except OSError:
        pass


def _show_fatal_error(message: str) -> None:
    _write_log(message)
    from platform_utils import show_error

    show_error("wxmeme 启动失败", message)


def _normalize_argv() -> None:
    if sys.platform == "darwin":
        sys.argv = [sys.argv[0], *[arg for arg in sys.argv[1:] if not arg.startswith("-psn_")]]


def _configure_tk_env() -> None:
    if sys.platform != "darwin":
        return
    candidates = [
        (
            "/System/Library/Frameworks/Tcl.framework/Versions/8.5/Resources/Scripts",
            "/System/Library/Frameworks/Tk.framework/Versions/8.5/Resources/Scripts",
        ),
        (
            "/System/Library/Frameworks/Tcl.framework/Versions/Current/Resources/Scripts",
            "/System/Library/Frameworks/Tk.framework/Versions/Current/Resources/Scripts",
        ),
    ]
    for tcl, tk in candidates:
        if Path(tcl).is_dir() and Path(tk).is_dir():
            os.environ["TCL_LIBRARY"] = tcl
            os.environ["TK_LIBRARY"] = tk
            os.environ.setdefault("LANG", "zh_CN.UTF-8")
            os.environ.setdefault("LC_ALL", "zh_CN.UTF-8")
            return


def _bootstrap_exporter() -> Path:
    if getattr(sys, "frozen", False):
        root = Path(sys._MEIPASS)
    else:
        root = Path(__file__).resolve().parent.parent
    exporter = root / "exporter"
    if str(exporter) not in sys.path:
        sys.path.insert(0, str(exporter))
    os.chdir(root)
    return root


def run_cli() -> int:
    _bootstrap_exporter()
    import wxmeme

    return wxmeme.main()


def run_wcdb() -> int:
    _bootstrap_exporter()
    import wcdb_extract

    return wcdb_extract.main()


def run_gui() -> None:
    if getattr(sys, "frozen", False):
        from webview_ui import run_webview_ui

        raise SystemExit(run_webview_ui(_bootstrap_exporter, _write_log))
    _configure_tk_env()
    from gui import main as gui_main

    gui_main()


def main() -> int:
    _normalize_argv()
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "--cli":
            sys.argv = [sys.argv[0], *sys.argv[2:]]
            return run_cli()
        if len(sys.argv) > 1 and sys.argv[1] == "--wcdb":
            sys.argv = [sys.argv[0], *sys.argv[2:]]
            return run_wcdb()
        run_gui()
        return 0
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else (0 if code is None else 1)
    except Exception:
        _show_fatal_error(traceback.format_exc())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
