"""Persistent resource location and lossless library directory operations."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

RESOURCE_PARTS = ("collected/prts_text", "collected/terra", "ocr/terra_text", "local", "updates/new")
ALLOWED_TOP = {"collected", "ocr", "local", "updates", "README.md"}


def settings_file() -> Path:
    override = os.environ.get("M3_READER_SETTINGS")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "M3 Reader"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "m3-reader"
    return base / "settings.json"


def configured_root() -> Path | None:
    if os.name == "nt" and not os.environ.get("M3_READER_SETTINGS"):
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\M3 Reader") as key:
                location, _ = winreg.QueryValueEx(key, "ResourcesLocation")
            if isinstance(location, str) and location:
                return Path(location).expanduser().resolve()
        except (OSError, ImportError):
            pass
    try:
        value = json.loads(settings_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    location = value.get("resources_dir") if isinstance(value, dict) else None
    return Path(location).expanduser().resolve() if isinstance(location, str) and location else None


def resource_root(project_dir: Path) -> Path:
    override = os.environ.get("M3_READER_RESOURCES")
    if override:
        return Path(override).expanduser().resolve()
    return configured_root() or project_dir / "resources"


def inspect_resources(directory: Path) -> int:
    """Return existing file count; reject an unrelated folder or linked content."""
    directory = directory.expanduser()
    if directory.is_symlink():
        raise ValueError(f"resources 目录不能是软链接：{directory}")
    directory = directory.resolve()
    if not directory.exists():
        return 0
    if not directory.is_dir():
        raise ValueError(f"不是目录：{directory}")
    entries = list(directory.iterdir())
    unknown = [entry.name for entry in entries if entry.name not in ALLOWED_TOP]
    if unknown:
        raise ValueError(f"不是有效的 resources 目录；存在未知项目：{', '.join(unknown[:5])}")
    files = 0
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"resources 内不能包含软链接：{path}")
        if path.is_file():
            files += 1
    return files


def initialize_resources(directory: Path) -> int:
    count = inspect_resources(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for part in RESOURCE_PARTS:
        (directory / part).mkdir(parents=True, exist_ok=True)
    return count


def save_resources(directory: Path) -> int:
    if directory.expanduser().is_symlink():
        raise ValueError(f"resources 目录不能是软链接：{directory}")
    directory = directory.expanduser().resolve()
    count = initialize_resources(directory)
    path = settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".settings-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"version": 1, "resources_dir": str(directory)}, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    if os.name == "nt" and not os.environ.get("M3_READER_SETTINGS"):
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\M3 Reader") as key:
            winreg.SetValueEx(key, "ResourcesLocation", 0, winreg.REG_SZ, str(directory))
    return count


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def import_resources(source: Path, destination: Path) -> tuple[int, int]:
    """Copy missing files into the active library; abort before copying on conflicts."""
    if source.expanduser().is_symlink() or destination.expanduser().is_symlink():
        raise ValueError("resources 目录不能是软链接")
    source, destination = source.expanduser().resolve(), destination.expanduser().resolve()
    if source == destination:
        raise ValueError("来源与当前 resources 目录相同")
    if source in destination.parents or destination in source.parents:
        raise ValueError("来源与当前 resources 目录不能互相包含")
    inspect_resources(source)
    if not source.is_dir():
        raise ValueError(f"来源目录不存在：{source}")
    initialize_resources(destination)
    incoming = [path for path in source.rglob("*") if path.is_file() and path != source / "README.md"]
    missing = []
    same = 0
    for path in incoming:
        target = destination / path.relative_to(source)
        if target.exists():
            if not target.is_file() or path.stat().st_size != target.stat().st_size or _digest(path) != _digest(target):
                raise ValueError(f"导入冲突，未复制任何文件：{target}")
            same += 1
        else:
            missing.append((path, target))
    for path, target in missing:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.import-tmp")
        try:
            shutil.copy2(path, temporary)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    return len(missing), same


def move_resources(source: Path, destination: Path) -> int:
    """Verify a full copy before switching configuration and deleting the old tree."""
    if source.expanduser().is_symlink() or destination.expanduser().is_symlink():
        raise ValueError("resources 目录不能是软链接")
    source, destination = source.expanduser().resolve(), destination.expanduser().resolve()
    count = inspect_resources(source)
    if not source.is_dir() or source == destination:
        raise ValueError("请选择与当前目录不同的目标目录")
    if source in destination.parents or destination in source.parents:
        raise ValueError("目标目录不能位于当前目录内部或外部")
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise ValueError("移动目标必须为空；合并现有资料请使用“导入 resources”")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".m3-resources-", dir=destination.parent))
    try:
        shutil.copytree(source, staging, dirs_exist_ok=True)
        for old in source.rglob("*"):
            if old.is_file():
                new = staging / old.relative_to(source)
                if not new.is_file() or _digest(old) != _digest(new):
                    raise OSError(f"复制后校验失败：{old}")
        if destination.exists():
            destination.rmdir()
        staging.rename(destination)
        save_resources(destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    shutil.rmtree(source)
    return count
