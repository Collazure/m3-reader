"""保存最近一次实际写入的采集内容。"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from .paths import LATEST_DIR, data_root


CONTENT_SUFFIXES = {".txt", ".md", ".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _files(roots: dict[str, Path]) -> dict[tuple[str, Path], tuple[int, int]]:
    """记录内容文件的修改时间和大小，忽略清单与索引。"""
    found = {}
    for label, root in roots.items():
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.name.startswith("_"):
                continue
            if path.suffix.lower() not in CONTENT_SUFFIXES:
                continue
            stat = path.stat()
            if stat.st_size:
                found[(label, path.relative_to(root))] = (stat.st_mtime_ns, stat.st_size)
    return found


class LatestCapture:
    """保存本次采集中写入的所有有效内容文件。"""

    def __init__(self, out_dir: Path, collectors: list[type]):
        roots = {out_dir.name: out_dir}
        for cls in collectors:
            if cls.data_root:
                roots[cls.data_root] = data_root(out_dir, cls.data_root)
        self.roots = roots
        self.before = _files(roots)

    def save(self) -> int:
        after = _files(self.roots)
        changed = [key for key, sig in after.items() if self.before.get(key) != sig]
        if not changed:
            return 0

        # 先完整复制，再替换 new；复制失败时保留上一次的副本。
        LATEST_DIR.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".new-", dir=LATEST_DIR.parent))
        backup = staging.with_name(staging.name + "-previous")
        try:
            for label, relative in sorted(changed):
                src = self.roots[label] / relative
                # 只保留文件的直接上一级目录，不复制源目录的完整层级。
                parent_name = relative.parent.name if relative.parent != Path(".") else label
                dst = staging / parent_name / relative.name
                dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists():
                    number = 2
                    while True:
                        alternate = dst.with_name(f"{dst.stem} ({number}){dst.suffix}")
                        if not alternate.exists():
                            dst = alternate
                            break
                        number += 1
                shutil.copy2(src, dst)
            if LATEST_DIR.exists():
                LATEST_DIR.rename(backup)
            try:
                staging.rename(LATEST_DIR)
            except OSError:
                if backup.exists():
                    backup.rename(LATEST_DIR)
                raise
        finally:
            if staging.exists():
                shutil.rmtree(staging)
            if backup.exists() and LATEST_DIR.exists():
                shutil.rmtree(backup)
        return len(changed)
