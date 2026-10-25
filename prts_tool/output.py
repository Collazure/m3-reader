#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""输出层：文件名清洗、排序、增量清单。"""

from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from pathlib import Path


def sanitize(name: str) -> str:
    """清掉 Windows / Linux 都不允许的文件名字符。"""
    name = unicodedata.normalize("NFC", str(name))
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:120] or "未命名"


def sanitize_path(rel: str) -> str:
    """逐段清洗相对路径，保留 `/` 分隔（如 `主线/第2章 异卵同生`）。"""
    parts = str(rel).replace("\\", "/").split("/")
    return "/".join(sanitize(p) for p in parts if p)


def natural_key(label: str):
    """自然排序：把数字串按数值比较（数字段优先于文字段）。"""
    return [(0, int(p)) if p.isdigit() else (1, p) for p in re.split(r"(\d+)", str(label))]


def write_text(path: Path, text: str, *, ignore_timestamps: bool = False) -> bool:
    """只在内容变化时写入，保留相同文件原有的修改时间。"""
    data = text.encode("utf-8")
    if path.is_file():
        old = path.read_bytes()
        if old == data:
            return False
        if ignore_timestamps:
            timestamp = r"(生成时间：|抓取时间：)\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"
            stable = lambda body: re.sub(timestamp, r"\1", body.decode("utf-8"))
            if stable(old) == stable(data):
                return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True


def signature(*parts: object) -> str:
    """把若干标识（页面 revid 等）压成一个短签名，用于增量比对。"""
    h = hashlib.md5()
    for p in parts:
        h.update(str(p).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


class Manifest:
    """按 key 记录签名的小清单（每个采集模块一份）。"""

    def __init__(self, path: Path):
        self.path = path
        self.items: dict[str, dict] = {}
        if path.exists():
            try:
                self.items = json.loads(path.read_text(encoding="utf-8")).get("items", {})
            except (json.JSONDecodeError, OSError):
                self.items = {}
        self.dirty = False

    def get(self, key: str) -> dict:
        return self.items.get(key, {})

    def sig_of(self, key: str) -> str:
        """取签名；兼容旧版清单（旧版只记了 revid）。"""
        item = self.items.get(key, {})
        sig = item.get("sig")
        if sig:
            return str(sig)
        return str(item.get("revid", "")) if item.get("revid") else ""

    def record(self, key: str, sig: str, **extra) -> None:
        value = {"sig": sig, "updated": time.strftime("%Y-%m-%d %H:%M:%S"), **extra}
        old = self.items.get(key, {})
        if {k: v for k, v in old.items() if k != "updated"} == \
                {k: v for k, v in value.items() if k != "updated"}:
            return
        self.items[key] = value
        self.dirty = True

    def drop(self, key: str) -> None:
        if key in self.items:
            del self.items[key]
            self.dirty = True

    def save(self, force: bool = False) -> None:
        if not (self.dirty or force):
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total": len(self.items),
            "items": self.items,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        self.dirty = False
