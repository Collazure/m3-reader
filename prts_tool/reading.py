"""Local reading positions shared by the GUI and TUI."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from .library import TEXT_SUFFIXES, relative_id, resource_path
from .paths import READING_FILE
from .story_layout import story_relative_path

MAX_POSITIONS = 500


def _load() -> dict:
    try:
        value = json.loads(READING_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "last": "", "positions": {}}
    if not isinstance(value, dict) or not isinstance(value.get("positions"), dict):
        return {"version": 1, "last": "", "positions": {}}
    value["positions"] = {key: item for key, item in value["positions"].items()
                          if isinstance(key, str) and isinstance(item, dict)}
    prefix = "collected/prts_text/avg/"
    value["positions"] = {(prefix + story_relative_path(key[len(prefix):])
                           if key.startswith(prefix) else key): item
                          for key, item in value["positions"].items()}
    if not isinstance(value.get("last"), str):
        value["last"] = ""
    elif value["last"].startswith(prefix):
        value["last"] = prefix + story_relative_path(value["last"][len(prefix):])
    return value


def save_position(path: Path, *, line: int = 1, page: int | None = None, quote: str = "") -> None:
    """Save one resource's current line or PDF page without touching its source."""
    if not path.is_file():
        return
    resource_id = relative_id(path)
    state = _load()
    positions = state["positions"]
    stat = path.stat()
    position = {"line": max(1, int(line)), "page": max(1, int(page)) if page else None,
                "quote": quote.strip()[:160], "stamp": [stat.st_size, stat.st_mtime_ns],
                "visited_at": datetime.now().astimezone().isoformat(timespec="seconds")}
    previous = positions.get(resource_id)
    if (state.get("last") == resource_id and isinstance(previous, dict) and
            all(previous.get(key) == position[key] for key in ("line", "page", "quote", "stamp"))):
        return
    positions[resource_id] = position
    if len(positions) > MAX_POSITIONS:
        oldest = sorted(positions, key=lambda key: positions[key].get("visited_at", ""))
        for key in oldest[:len(positions) - MAX_POSITIONS]:
            del positions[key]
    state["last"] = resource_id
    state["version"] = 1
    READING_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".reading-", suffix=".json", dir=READING_FILE.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False, indent=2)
        os.replace(name, READING_FILE)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def position_for(path: Path) -> tuple[int, int | None]:
    """Return a saved position; relocate its text quote after a source refresh."""
    try:
        item = _load()["positions"].get(relative_id(path), {})
    except ValueError:
        return 1, None
    if not isinstance(item, dict):
        return 1, None
    try:
        line = max(1, int(item.get("line") or 1))
        page = max(1, int(item["page"])) if item.get("page") else None
    except (TypeError, ValueError):
        return 1, None
    if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
        return line, page
    stamp = path.stat()
    quote = item.get("quote") if isinstance(item.get("quote"), str) else ""
    if quote and item.get("stamp") != [stamp.st_size, stamp.st_mtime_ns]:
        nearest = None
        distance = None
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            for index, text in enumerate(stream, 1):
                if quote in text:
                    current = abs(index - line)
                    if distance is None or current < distance:
                        nearest, distance = index, current
        if nearest is not None:
            line = nearest
    return line, page


def last_position() -> tuple[Path, int, int | None] | None:
    state = _load()
    positions = state["positions"]
    order = [state.get("last", "")]
    order.extend(sorted(positions, key=lambda key: positions[key].get("visited_at", ""), reverse=True))
    for resource_id in dict.fromkeys(order):
        if not resource_id:
            continue
        try:
            path = resource_path(resource_id)
        except ValueError:
            continue
        if path.is_file():
            line, page = position_for(path)
            return path, line, page
    return None
