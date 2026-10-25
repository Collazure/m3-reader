"""Shared local library, text search, and user notes for both interfaces."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .paths import NOTES_FILE, OPINIONS_FILE, RESOURCES_DIR

TEXT_SUFFIXES = {".txt", ".md", ".csv", ".tsv"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
PDF_SUFFIXES = {".pdf"}
SKIP_PARTS = {"updates", "__pycache__"}


def resource_files() -> Iterator[Path]:
    """Return all readable resources, keeping indexes out of the reading tree."""
    for path in RESOURCES_DIR.rglob("*"):
        if path.is_file() and not any(part in SKIP_PARTS for part in path.relative_to(RESOURCES_DIR).parts):
            if path.name.startswith("_manifest") or path.name.startswith("_pages"):
                continue
            if path.suffix.lower() in TEXT_SUFFIXES | IMAGE_SUFFIXES | PDF_SUFFIXES:
                yield path


def relative_id(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(RESOURCES_DIR.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError("资源必须位于 resources/ 下") from exc


def resource_path(resource_id: str) -> Path:
    path = (RESOURCES_DIR / resource_id).resolve()
    relative_id(path)
    return path


def source_kind(path: Path) -> str:
    parts = path.resolve().relative_to(RESOURCES_DIR.resolve()).parts
    if parts[0] == "collected":
        return "采集资源"
    if parts[0] == "ocr" or "OCR" in path.name or "大地巡旅_OCR_pages" in parts:
        return "OCR 派生资料"
    return "本地资料"


@dataclass(frozen=True)
class SearchHit:
    resource_id: str
    line: int
    excerpt: str
    page: int | None = None


def search_text(query: str, *, limit: int = 500, files: Iterator[Path] | None = None) -> list[SearchHit]:
    term = query.strip().casefold()
    if not term:
        return []
    hits: list[SearchHit] = []
    for path in files if files is not None else resource_files():
        if path.suffix.lower() not in TEXT_SUFFIXES or path.name.startswith("_"):
            continue
        page: int | None = None
        try:
            with path.open("r", encoding="utf-8", errors="replace") as stream:
                for line_no, line in enumerate(stream, 1):
                    if path.name == "大地巡旅_OCR.txt" and line.startswith("===== 第 "):
                        try:
                            page = int(line.split()[2])
                        except (IndexError, ValueError):
                            pass
                    if term in line.casefold():
                        offset = line.casefold().find(term)
                        start = max(0, offset - 70)
                        excerpt = ("…" if start else "") + line[start:start + 220].strip()
                        if len(line) > start + 220:
                            excerpt += "…"
                        hits.append(SearchHit(relative_id(path), line_no, excerpt, page))
                        if len(hits) >= limit:
                            return hits
        except OSError:
            continue
    return hits


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".writing-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_opinions() -> str:
    """Return the user-owned Markdown file, creating it on first use."""
    OPINIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not OPINIONS_FILE.exists():
        OPINIONS_FILE.write_text("# 更新意见\n\n在此填写意见。可自由添加标题、资源路径或待办项。\n", encoding="utf-8")
    return OPINIONS_FILE.read_text(encoding="utf-8")


def write_opinions(content: str) -> None:
    OPINIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".opinions-", suffix=".md", dir=OPINIONS_FILE.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        os.replace(name, OPINIONS_FILE)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def append_opinion(content: str) -> None:
    if not content.strip():
        raise ValueError("意见内容不能为空")
    current = read_opinions()
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    write_opinions(current.rstrip() + f"\n\n## {stamp}\n\n{content.strip()}\n")


def load_notes() -> list[dict]:
    if not NOTES_FILE.exists():
        return []
    try:
        return json.loads(NOTES_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def save_note(resource_id: str, body: str, *, line: int = 0, page: int | None = None,
              quote: str = "", note_id: str | None = None) -> dict:
    path = resource_path(resource_id)
    if not body.strip():
        raise ValueError("意见内容不能为空")
    notes = load_notes()
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    note = next((item for item in notes if item["id"] == note_id), None)
    if note is None:
        note = {"id": uuid.uuid4().hex, "created_at": now, "status": "待处理"}
        notes.append(note)
    stamp = [path.stat().st_size, path.stat().st_mtime_ns] if path.is_file() else None
    note.update(resource_id=resource_id, line=line, page=page, quote=quote,
                resource_stamp=stamp,
                body=body.strip(), updated_at=now)
    _write_json(NOTES_FILE, notes)
    return note


def note_location(note: dict) -> tuple[int, bool]:
    """Find a saved quote after refresh; return (line or page, stale)."""
    path = resource_path(note["resource_id"])
    requested = int(note.get("line") or note.get("page") or 1)
    if not path.is_file():
        return requested, True
    quote = (note.get("quote") or "").replace("\u2029", "\n").strip()
    if quote and path.suffix.lower() in TEXT_SUFFIXES:
        content = path.read_text(encoding="utf-8", errors="replace")
        if "\n" in quote:
            offset = content.find(quote)
            return (content.count("\n", 0, offset) + 1, False) if offset >= 0 else (requested, True)
        lines = content.splitlines()
        if 1 <= requested <= len(lines) and quote in lines[requested - 1]:
            return requested, False
        for line, body in enumerate(lines, 1):
            if quote in body:
                return line, False
        return requested, True
    stamp = [path.stat().st_size, path.stat().st_mtime_ns]
    return requested, note.get("resource_stamp") != stamp


def set_note_status(note_id: str, status: str) -> None:
    if status not in {"待处理", "已处理"}:
        raise ValueError(status)
    notes = load_notes()
    for note in notes:
        if note["id"] == note_id:
            note["status"] = status
            _write_json(NOTES_FILE, notes)
            return
    raise KeyError(note_id)
