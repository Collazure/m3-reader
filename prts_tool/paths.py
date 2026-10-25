"""Project resource locations, independent of the caller's working directory."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_DIR = (Path(os.environ["M3_READER_HOME"]).expanduser().resolve()
               if os.environ.get("M3_READER_HOME") else
               Path(sys.executable).resolve().parent.parent.parent if getattr(sys, "frozen", False)
               else Path(__file__).resolve().parent.parent)
RESOURCES_DIR = PROJECT_DIR / "resources"
DEFAULT_TEXT_DIR = RESOURCES_DIR / "collected" / "prts_text"
DEFAULT_TERRA_DIR = RESOURCES_DIR / "collected" / "terra"
TERRA_OCR_DIR = RESOURCES_DIR / "ocr" / "terra_text"
BOOK_DIR = RESOURCES_DIR / "local" / "大地巡旅"
BOOK_IMAGE_DIR = BOOK_DIR / "images"
BOOK_TEXT_DIR = BOOK_DIR / "text"
BOOK_OCR_FILE = BOOK_TEXT_DIR / "大地巡旅_OCR.txt"
LATEST_DIR = RESOURCES_DIR / "updates" / "new"
WORKSPACE_DIR = PROJECT_DIR / "workspace"
HISTORY_DIR = WORKSPACE_DIR / "history"
NOTES_FILE = WORKSPACE_DIR / "notes.json"
OPINIONS_FILE = WORKSPACE_DIR / "更新意见.md"
READING_FILE = WORKSPACE_DIR / "reading.json"
APP_ICON_FILE = Path(getattr(sys, "_MEIPASS", PROJECT_DIR)) / "assets" / "icon.png"


def crawler_command(args: list[str]) -> list[str]:
    """Launch the CLI from source or from adjacent packaged executables."""
    if getattr(sys, "frozen", False):
        sibling = Path(sys.executable).with_name("m3-reader.exe" if os.name == "nt" else "m3-reader")
        if not sibling.is_file():
            raise FileNotFoundError(f"找不到采集程序：{sibling}")
        return [str(sibling), *args]
    return [sys.executable, str(PROJECT_DIR / "prts_crawler.py"), *args]


def data_root(out_dir: Path, name: str) -> Path:
    """Keep custom --out's historical sibling rule; use the project layout by default."""
    resolved = out_dir.expanduser().resolve()
    if name == "terra" and resolved == DEFAULT_TEXT_DIR.resolve():
        return DEFAULT_TERRA_DIR
    return resolved.parent / name
