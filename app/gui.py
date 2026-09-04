#!/usr/bin/env python3
"""wxmeme macOS 图形界面：导出微信「我的表情」并预览。"""

from __future__ import annotations

import os
import queue
import subprocess
import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, scrolledtext, ttk

from paths import (
    EXPORT_SCRIPT,
    EXPORTER,
    LIBRARY,
    PREVIEW_URL,
    PROJECT_ROOT,
    WCDB_KEYS,
    is_frozen,
    python_executable,
    subprocess_env,
    wxmeme_command,
)


class WxmemeApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("wxmeme 表情导出")
        self.geometry("640x480")
        self.minsize(520, 420)

        self._proc: subprocess.Popen[str] | None = None
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._server_running = False

        self._build_ui()
        self.after(100, self._drain_output)
        self.lift()
        self.attributes("-topmost", True)
        self.after(200, lambda: self.attributes("-topmost", False))
        self.focus_force()

    def _build_ui(self) -> None:
        header = ttk.Frame(self, padding=12)
        header.pack(fill=tk.X)
        ttk.Label(header, text="wxmeme 表情导出", font=("PingFang SC", 18, "bold")).pack(anchor=tk.W)
        subtitle = "独立版 · 无需安装 Python" if is_frozen() else "从 Mac 微信导出「我的表情」"
        ttk.Label(
            header,
            text=f"{subtitle}，保存到 ~/Downloads/wxmeme/library",
            wraplength=580,
        ).pack(anchor=tk.W, pady=(4, 0))

        actions = ttk.Frame(self, padding=(12, 0))
        actions.pack(fill=tk.X)
        ttk.Button(actions, text="完整导出（同步微信）", command=self._run_full_export).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(actions, text="快速导出（CDN）", command=self._run_quick_export).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(actions, text="打开预览", command=self._open_preview).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(actions, text="打开文件夹", command=self._open_library).pack(side=tk.LEFT)

        self.log = scrolledtext.ScrolledText(self, wrap=tk.WORD, height=18, font=("Menlo", 11))
        self.log.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
        self.log.configure(state=tk.DISABLED)

        footer = ttk.Frame(self, padding=(12, 0, 12, 12))
        footer.pack(fill=tk.X)
        ttk.Label(
            footer,
            text="浏览器插件：dist/wxmeme-extension.zip",
            foreground="#666",
        ).pack(anchor=tk.W)

    def _append(self, text: str) -> None:
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, text)
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def _ensure_deps(self) -> None:
        if is_frozen():
            return
        venv_python = PROJECT_ROOT / ".venv" / "bin" / "python3"
        if venv_python.is_file():
            return
        self._append("wxmeme: 首次运行，安装依赖…\n")
        subprocess.run([python_executable(), "-m", "venv", str(PROJECT_ROOT / ".venv")], check=True, cwd=PROJECT_ROOT)
        subprocess.run(
            [
                str(venv_python),
                "-m",
                "pip",
                "install",
                "-q",
                "-r",
                str(PROJECT_ROOT / "exporter" / "requirements.txt"),
            ],
            check=True,
            cwd=PROJECT_ROOT,
        )

    def _drain_output(self) -> None:
        try:
            while True:
                line = self._queue.get_nowait()
                if line is None:
                    self._proc = None
                    break
                self._append(line)
        except queue.Empty:
            pass
        self.after(100, self._drain_output)

    def _run_command(self, cmd: list[str], cwd: os.PathLike[str] | None = None) -> None:
        if self._proc and self._proc.poll() is None:
            messagebox.showwarning("wxmeme", "已有任务在运行，请稍候。")
            return

        self._append(f"\n$ {' '.join(cmd)}\n")

        def worker() -> None:
            try:
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(cwd or PROJECT_ROOT),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=subprocess_env(),
                )
                self._proc = proc
                assert proc.stdout is not None
                for line in proc.stdout:
                    self._queue.put(line)
                proc.wait()
                self._queue.put(f"\nwxmeme: 退出码 {proc.returncode}\n")
            except Exception as exc:
                self._queue.put(f"\n错误: {exc}\n")
            finally:
                self._queue.put(None)

        threading.Thread(target=worker, daemon=True).start()

    def _run_full_export(self) -> None:
        if not EXPORT_SCRIPT.is_file():
            messagebox.showerror("wxmeme", f"找不到脚本:\n{EXPORT_SCRIPT}")
            return
        try:
            self._ensure_deps()
        except subprocess.CalledProcessError as exc:
            messagebox.showerror("wxmeme", f"依赖安装失败: {exc}")
            return
        self._run_command(["/bin/bash", str(EXPORT_SCRIPT)])

    def _run_quick_export(self) -> None:
        if not is_frozen() and not EXPORTER.is_file():
            messagebox.showerror("wxmeme", f"找不到导出器:\n{EXPORTER}")
            return
        try:
            self._ensure_deps()
        except subprocess.CalledProcessError as exc:
            messagebox.showerror("wxmeme", f"依赖安装失败: {exc}")
            return
        args = ["--cdn", "--sync-persist", "--scan-only"]
        if WCDB_KEYS.is_file():
            args = ["--wcdb-keys", str(WCDB_KEYS), "--cdn", "--scan-only"]
        self._run_command(wxmeme_command(*args))

    def _open_preview(self) -> None:
        if not is_frozen() and not EXPORTER.is_file():
            messagebox.showerror("wxmeme", f"找不到导出器:\n{EXPORTER}")
            return
        if self._server_running:
            webbrowser.open(PREVIEW_URL)
            return

        def worker() -> None:
            try:
                self._ensure_deps()
                self._server_running = True
                self._append("\nwxmeme: 启动预览服务 …\n")
                proc = subprocess.Popen(
                    wxmeme_command("--cdn", "--no-browser"),
                    cwd=str(PROJECT_ROOT),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=subprocess_env(),
                )
                self._proc = proc
                assert proc.stdout is not None
                for line in proc.stdout:
                    self._queue.put(line)
                    if "127.0.0.1" in line:
                        webbrowser.open(PREVIEW_URL)
            except Exception as exc:
                self._queue.put(f"\n错误: {exc}\n")
                self._server_running = False

        threading.Thread(target=worker, daemon=True).start()

    def _open_library(self) -> None:
        LIBRARY.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(LIBRARY)], check=False)


def main() -> None:
    os.chdir(PROJECT_ROOT)
    app = WxmemeApp()
    app.mainloop()


if __name__ == "__main__":
    main()
