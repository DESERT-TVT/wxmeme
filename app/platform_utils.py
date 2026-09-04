"""Cross-platform helpers for GUI / standalone builds."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def downloads_dir() -> Path:
    if sys.platform == "win32":
        userprofile = os.environ.get("USERPROFILE")
        if userprofile:
            return Path(userprofile) / "Downloads"
    return Path.home() / "Downloads"


def show_error(title: str, message: str) -> None:
    short = message[-400:] if len(message) > 400 else message
    try:
        if sys.platform == "darwin":
            safe = short.replace('"', "'").replace("\\", "/")
            subprocess.run(
                ["osascript", "-e", f'display alert "{title}" message "{safe}" as critical'],
                check=False,
            )
            return
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.MessageBoxW(  # type: ignore[attr-defined]
                0,
                short,
                title,
                0x00000010,
            )
            return
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, short)
        root.destroy()
    except Exception:
        pass


def reveal_in_folder(path: Path) -> None:
    path = Path(path).resolve()
    try:
        if sys.platform == "win32":
            subprocess.run(["explorer", "/select,", str(path)], check=False)
        elif sys.platform == "darwin":
            subprocess.run(["open", "-R", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path.parent)], check=False)
    except Exception:
        pass


def open_folder(path: Path) -> None:
    path = Path(path).resolve()
    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except Exception:
        pass
