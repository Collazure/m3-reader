"""Persistent per-run changes, with old and new text for line-level review."""

from __future__ import annotations

import difflib
import gzip
import json
import os
import re
import shutil
import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .library import IMAGE_SUFFIXES, PDF_SUFFIXES, TEXT_SUFFIXES, relative_id, resource_path
from .paths import DEFAULT_TEXT_DIR, DEFAULT_TERRA_DIR, HISTORY_DIR, RESOURCES_DIR, WORKSPACE_DIR

_TIME = re.compile(r"(生成时间：|抓取时间：)\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")


def _save_run(run: dict) -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    path = HISTORY_DIR / f"{run['id']}.json.gz"
    temporary = path.with_suffix(".tmp")
    try:
        with gzip.open(temporary, "wt", encoding="utf-8") as stream:
            json.dump(run, stream, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _stable(text: str) -> str:
    return _TIME.sub(r"\1", text)


def _snapshot(roots: tuple[Path, ...]) -> dict[str, tuple[str, str | None]]:
    found: dict[str, tuple[str, str | None]] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.name.startswith("_"):
                continue
            if path.suffix.lower() not in TEXT_SUFFIXES | IMAGE_SUFFIXES:
                continue
            key = relative_id(path)
            if path.suffix.lower() in TEXT_SUFFIXES:
                body = path.read_text(encoding="utf-8", errors="replace")
                found[key] = ("text", body)
            else:
                found[key] = ("image", _digest(path))
    return found


@dataclass
class HistoryCapture:
    command: str
    roots: tuple[Path, ...]
    before: dict[str, tuple[str, str | None]]
    started_at: str

    @classmethod
    def start(cls, command: str, out_dir: Path) -> "HistoryCapture | None":
        if out_dir.resolve() != DEFAULT_TEXT_DIR.resolve():
            return None
        roots = (DEFAULT_TEXT_DIR, DEFAULT_TERRA_DIR)
        return cls(command, roots, _snapshot(roots),
                   datetime.now().astimezone().isoformat(timespec="seconds"))

    def finish(self, *, status: str = "success", error: str = "") -> dict:
        after = _snapshot(self.roots)
        changes = []
        for key in sorted(self.before.keys() | after.keys()):
            old = self.before.get(key)
            new = after.get(key)
            if old == new:
                continue
            kind = (new or old)[0]
            if kind == "text" and old and new and _stable(old[1] or "") == _stable(new[1] or ""):
                continue
            changes.append({
                "resource_id": key,
                "kind": kind,
                "action": "added" if old is None else "deleted" if new is None else "modified",
                "old": old[1] if old else None,
                "new": new[1] if new else None,
            })
        run = {
            "id": datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8],
            "started_at": self.started_at,
            "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "command": self.command,
            "status": status,
            "error": error,
            "changes": changes,
        }
        _save_run(run)
        return run


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def import_local(source: Path, target_id: str | None = None) -> dict:
    """Import or replace a local source, preserving the replaced file as a version."""
    source = source.expanduser().resolve()
    if not source.is_file() or source.suffix.lower() not in TEXT_SUFFIXES | IMAGE_SUFFIXES | PDF_SUFFIXES:
        raise ValueError("请选择 txt、md、图片或 PDF 文件")
    if target_id:
        dest = resource_path(target_id)
        if dest.relative_to(RESOURCES_DIR).parts[0] != "local":
            raise ValueError("采集资料和 OCR 不能手动覆盖")
        if dest.suffix.lower() != source.suffix.lower():
            raise ValueError("替换文件的类型必须与原文件相同")
    else:
        dest = RESOURCES_DIR / "local" / source.name
    if dest.resolve() == source:
        raise ValueError("来源与目标是同一个文件")
    dest.parent.mkdir(parents=True, exist_ok=True)
    old_text = dest.read_text(encoding="utf-8", errors="replace") if dest.is_file() and dest.suffix.lower() in TEXT_SUFFIXES else None
    old_hash = _digest(dest) if dest.is_file() else None
    new_hash = _digest(source)
    if old_hash == new_hash:
        raise ValueError("内容与现有资源相同")
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
    backup = None
    if dest.is_file():
        backup = WORKSPACE_DIR / "versions" / run_id / relative_id(dest)
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dest, backup)
    temporary = dest.with_name(f".{dest.name}.{run_id}.tmp")
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, dest)
    finally:
        temporary.unlink(missing_ok=True)
    new_text = dest.read_text(encoding="utf-8", errors="replace") if dest.suffix.lower() in TEXT_SUFFIXES else None
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    run = {
        "id": run_id, "started_at": now, "finished_at": now,
        "command": f"本地导入 {source.name}", "status": "success", "error": "",
        "changes": [{"resource_id": relative_id(dest),
                     "kind": "text" if dest.suffix.lower() in TEXT_SUFFIXES else "media",
                     "action": "modified" if old_hash else "added",
                     "old": old_text if old_text is not None else old_hash,
                     "new": new_text if new_text is not None else new_hash,
                     "backup": str(backup.relative_to(WORKSPACE_DIR)) if backup else None}],
    }
    _save_run(run)
    return run


def list_runs(limit: int = 12) -> list[dict]:
    if not HISTORY_DIR.is_dir():
        return []
    result = []
    for path in sorted(HISTORY_DIR.glob("*.json.gz"), reverse=True)[:limit]:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            run = json.load(stream)
        result.append({key: run[key] for key in ("id", "started_at", "command", "status")}
                      | {"changed": len(run["changes"])})
    return result


def load_run(run_id: str) -> dict:
    if not re.fullmatch(r"[0-9]{8}-[0-9]{6}-[0-9a-f]{8}", run_id):
        raise ValueError("无效的运行编号")
    with gzip.open(HISTORY_DIR / f"{run_id}.json.gz", "rt", encoding="utf-8") as stream:
        return json.load(stream)


def diff_text(change: dict, context: int = 3) -> str:
    if change["kind"] != "text":
        return f"{change['action']}：{change['resource_id']}（图片或 PDF）"
    old = (change["old"] or "").splitlines(keepends=True)
    new = (change["new"] or "").splitlines(keepends=True)
    return "".join(difflib.unified_diff(old, new, fromfile="更新前", tofile="更新后", n=context))


def diff_rows(change: dict, context: int = 3) -> list[tuple[str, int | None, int | None, str]]:
    """Git-style diff rows with old/new line numbers for navigation."""
    if change["kind"] != "text":
        return [("meta", None, None, f"{change['action']}：{change['resource_id']}（图片或 PDF）")]
    rows = []
    old_line = new_line = 0
    for line in diff_text(change, context).splitlines():
        if line.startswith(("---", "+++")):
            rows.append(("meta", None, None, line))
        elif line.startswith("@@"):
            match = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)", line)
            if match:
                old_line, new_line = map(int, match.groups())
            rows.append(("hunk", None, None, line))
        elif line.startswith("+"):
            rows.append(("add", None, new_line, line[1:]))
            new_line += 1
        elif line.startswith("-"):
            rows.append(("remove", old_line, None, line[1:]))
            old_line += 1
        else:
            rows.append(("context", old_line, new_line, line[1:]))
            old_line += 1
            new_line += 1
    return rows
