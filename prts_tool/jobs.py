"""Update command construction and one writer at a time across interfaces."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .history import HistoryCapture
from .latest import LatestCapture
from .paths import WORKSPACE_DIR


def update_arguments(module: str = "all", mode: str = "changed", *, images: bool = False,
                     preview: bool = False, keyword: str = "") -> list[str]:
    args = ["terra-images"] if images else ["refresh", "-m", module]
    args += ["--mode", mode]
    if preview:
        args.append("--dry-run")
    if keyword.strip():
        args += ["--keyword", keyword.strip()]
    return args


def update_command_sequence(module: str, mode: str, *, full: bool = False,
                            preview: bool = False) -> list[list[str]]:
    """Full update collects every crawlable module, then terra images."""
    if full:
        return [update_arguments("all", mode, preview=preview),
                update_arguments("all", mode, images=True, preview=preview)]
    return [update_arguments(module, mode, preview=preview)]


class UpdateCapture:
    def __init__(self, out_dir: Path, collectors: list[type], *, dry_run: bool = False):
        self.out_dir, self.collectors, self.dry_run = out_dir, collectors, dry_run
        self.lock = None
        self.history = None
        self.latest = None
        self.latest_count = 0

    def __enter__(self):
        WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
        self.lock = (WORKSPACE_DIR / "update.lock").open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self.lock.seek(0)
                if not self.lock.read(1):
                    self.lock.write(b"0")
                    self.lock.flush()
                self.lock.seek(0)
                msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.lock.close()
            self.lock = None
            raise RuntimeError("已有更新任务正在运行，请等待它完成") from exc
        try:
            if not self.dry_run:
                self.history = HistoryCapture.start(" ".join(sys.argv[1:]), self.out_dir)
                self.latest = LatestCapture(self.out_dir, self.collectors)
        except BaseException:
            try:
                if self.history:
                    self.history.close()
            finally:
                self._unlock()
            raise
        return self

    def _unlock(self):
        if self.lock:
            if os.name == "nt":
                import msvcrt
                self.lock.seek(0)
                msvcrt.locking(self.lock.fileno(), msvcrt.LK_UNLCK, 1)
            self.lock.close()
            self.lock = None

    def __exit__(self, exc_type, exc, traceback):
        save_error = None
        try:
            try:
                if self.latest:
                    self.latest_count = self.latest.save()
            except OSError as error:
                save_error = error
            finally:
                if self.history:
                    status = "success" if exc is None and save_error is None else "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
                    self.history.finish(status=status, error=str(exc or save_error) if exc or save_error else "")
        finally:
            self._unlock()
        if save_error and exc is None:
            raise save_error
        return False
