"""Shared paths for dev and PyInstaller builds."""

from __future__ import annotations

import sys
from pathlib import Path

from platform_utils import downloads_dir


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def project_root() -> Path:
    if is_frozen():
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


PROJECT_ROOT = project_root()
EXPORTER_DIR = PROJECT_ROOT / "exporter"
EXPORTER = EXPORTER_DIR / "wxmeme.py"
EXPORT_SCRIPT = PROJECT_ROOT / "scripts" / "export-stickers.sh"
WCDB_EXTRACT = EXPORTER_DIR / "wcdb_extract.py"
LIBRARY = downloads_dir() / "wxmeme" / "library"
PREVIEW_URL = "http://127.0.0.1:8765"
VENV_PYTHON = (
    PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    if sys.platform == "win32"
    else PROJECT_ROOT / ".venv" / "bin" / "python3"
)
WCDB_KEYS = Path.home() / "Desktop" / "wcdb-key-tool" / "all_keys.json"


def python_executable() -> str:
    if is_frozen():
        return sys.executable
    if VENV_PYTHON.is_file():
        return str(VENV_PYTHON)
    return sys.executable


def wxmeme_command(*args: str) -> list[str]:
    if is_frozen():
        return [sys.executable, "--cli", *args]
    return [python_executable(), str(EXPORTER), *args]


def wcdb_command(*args: str) -> list[str]:
    if is_frozen():
        return [sys.executable, "--wcdb", *args]
    return [python_executable(), str(WCDB_EXTRACT), *args]


def subprocess_env() -> dict[str, str]:
    import os

    env = os.environ.copy()
    if is_frozen():
        env["WXMEME_PYTHON"] = sys.executable
        env["WXMEME_FROZEN"] = "1"
        env["WXMEME_BUNDLE"] = str(PROJECT_ROOT)
    return env
