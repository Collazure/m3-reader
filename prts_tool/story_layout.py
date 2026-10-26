"""Stable, Chinese story layout and migration of older downloaded files."""

from __future__ import annotations

import re
from pathlib import Path


def story_relative_path(value: str) -> str:
    """Normalize older AVG paths without touching filenames or other modules."""
    parts = list(Path(value.replace("\\", "/")).parts)
    if not parts:
        return value
    if parts[0] == "四月辑录":
        parts = ["特殊", *parts]
    elif parts[0].startswith("特殊 "):
        parts = ["特殊", parts[0][len("特殊 "):], *parts[1:]]
    if len(parts) >= 2 and parts[0] == "主线":
        parts[1] = re.sub(r"^第(\d)章", r"第0\1章", parts[1])
    return "/".join(parts)


def migrate_story_layout(root: Path) -> int:
    """Move existing story files and update the collector manifest; safe to rerun."""
    import json
    from .collectors.avg import AvgCollector
    from .output import Manifest

    root = root.resolve()
    if not root.is_dir():
        return 0
    legacy = ((root / "四月辑录").exists() or
              any(root.glob("特殊 *")) or
              any(re.match(r"^第\d章", path.name) for path in (root / "主线").glob("*")))
    if not legacy:
        return 0
    changes = []
    for source in root.rglob("*"):
        if not source.is_file() or source.name in {"_manifest.json", "_索引.md"}:
            continue
        relative = source.relative_to(root).as_posix()
        target_relative = story_relative_path(relative)
        if target_relative != relative:
            changes.append((source, root / target_relative))
    for source, target in changes:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.read_bytes() != source.read_bytes():
                raise FileExistsError(f"迁移目标已有不同内容：{target}")
            source.unlink()
        else:
            source.replace(target)
    manifest_path = root / "_manifest.json"
    if manifest_path.is_file():
        manifest = Manifest(manifest_path)
        for record in manifest.items.values():
            for field in ("folder", "file"):
                old = record.get(field)
                if isinstance(old, str) and old:
                    record[field] = story_relative_path(old)
        manifest.save(force=True)
        AvgCollector._write_toc(manifest, root)
    for directory in sorted((p for p in root.rglob("*") if p.is_dir()),
                            key=lambda p: len(p.parts), reverse=True):
        if not any(directory.iterdir()):
            directory.rmdir()
    return len(changes)
