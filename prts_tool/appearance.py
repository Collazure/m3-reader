"""Small, per-user GUI appearance preference file."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .resource_settings import settings_file


THEME_NAMES = {
    "classic": "经典",
    "soft": "柔亮",
    "ocean": "深海蓝",
    "warm": "暖棕",
}


def appearance_file() -> Path:
    return settings_file().with_name("appearance.json")


def load_theme() -> str:
    try:
        data = json.loads(appearance_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "classic"
    name = data.get("theme") if isinstance(data, dict) else None
    return name if name in THEME_NAMES else "classic"


def save_theme(name: str) -> None:
    if name not in THEME_NAMES:
        raise ValueError(f"未知主题：{name}")
    target = appearance_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".appearance-", suffix=".json", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"version": 1, "theme": name}, stream, ensure_ascii=False)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
