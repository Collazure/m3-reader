"""Produce minimal portable Windows and Ubuntu source packages.

Only explicitly listed program files and empty resource directories enter an archive.
Existing collected data, OCR output, local documents, opinions and history are excluded.
"""

from __future__ import annotations

import hashlib
import io
import re
import tarfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', (ROOT / "prts_tool" / "__init__.py").read_text(encoding="utf-8")).group(1)
PREFIX = "m3-reader"
EMPTY_DIRS = (
    "resources/collected/prts_text/",
    "resources/collected/terra/",
    "resources/ocr/terra_text/",
    "resources/local/",
    "resources/updates/new/",
    "workspace/",
)
SOURCE_FILES = (
    "pyproject.toml",
    "prts_crawler.py",
    "prts_story_crawler.py",
    "docs/APP_README.md",
    "scripts/entry_cli.py",
    "scripts/entry_gui.py",
    "scripts/build_windows.ps1",
    "scripts/build_ubuntu.sh",
    "scripts/install_ubuntu.sh",
    *(path.relative_to(ROOT).as_posix() for path in sorted((ROOT / "prts_tool").rglob("*.py"))),
)
WINDOWS_FILES = ("bin/windows/m3-reader.exe", "bin/windows/m3-reader-gui.exe")


def readme(platform: str) -> bytes:
    if platform == "windows":
        content = ("# M3 Reader 便携版\n\n"
                   "双击 bin/windows/m3-reader-gui.exe 启动图形界面。\n"
                   "在终端运行 bin/windows/m3-reader.exe gui、tui 或 update。\n"
                   "resources/ 仅有空目录；首次更新才会采集内容。本地文档请放入 resources/local/。\n"
                   "请保持 bin/windows/ 与项目根目录的相对位置。\n")
        content += "双击 install_windows.cmd 可一键安装到当前用户的程序目录，并创建桌面与开始菜单快捷方式。\n"
    else:
        content = ("# M3 Reader Ubuntu 源码安装包\n\n"
                   "解压后运行 bash scripts/install_ubuntu.sh；需要 Python 3.10+、pip 和网络下载依赖。\n"
                   "安装后从应用菜单启动 M3 Reader，终端使用 m3-reader gui/tui/update。\n"
                   "这是源码安装包，不含 Linux 二进制程序或任何资源正文。\n"
                   "若需独立可执行程序，在 Ubuntu 上运行 bash scripts/build_ubuntu.sh。\n")
    return content.encode("utf-8")


def build_windows(target: Path) -> None:
    for name in WINDOWS_FILES:
        if not (ROOT / name).is_file():
            raise FileNotFoundError(f"请先构建 Windows 程序：{ROOT / name}")
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr(f"{PREFIX}/README-install.md", readme("windows"))
        for name in EMPTY_DIRS:
            archive.writestr(f"{PREFIX}/{name}", b"")
        for name in WINDOWS_FILES:
            archive.write(ROOT / name, f"{PREFIX}/{name}")
        for name in ("install_windows.cmd", "scripts/install_windows.ps1"):
            archive.write(ROOT / name, f"{PREFIX}/{name}")


def build_ubuntu(target: Path) -> None:
    with tarfile.open(target, "w:gz") as archive:
        payload = readme("ubuntu")
        info = tarfile.TarInfo(f"{PREFIX}/README-install.md")
        info.size = len(payload)
        info.mode = 0o644
        archive.addfile(info, io.BytesIO(payload))
        for name in EMPTY_DIRS:
            info = tarfile.TarInfo(f"{PREFIX}/{name}")
            info.type = tarfile.DIRTYPE
            info.mode = 0o755
            archive.addfile(info)
        for name in SOURCE_FILES:
            path = ROOT / name
            info = archive.gettarinfo(str(path), arcname=f"{PREFIX}/{name}")
            info.mode = 0o755 if name.endswith(".sh") else 0o644
            with path.open("rb") as source:
                archive.addfile(info, source)


def main() -> int:
    output = ROOT / "installpacks"
    windows = output / "windows" / f"m3-reader-{VERSION}-windows-x64-portable.zip"
    ubuntu = output / "debian" / f"m3-reader-{VERSION}-ubuntu-source.tar.gz"
    windows.parent.mkdir(parents=True, exist_ok=True)
    ubuntu.parent.mkdir(parents=True, exist_ok=True)
    build_windows(windows)
    build_ubuntu(ubuntu)
    checksums = "\n".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(output).as_posix()}"
                          for path in (windows, ubuntu)) + "\n"
    (output / "SHA256SUMS.txt").write_text(checksums, encoding="utf-8")
    print(windows)
    print(ubuntu)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
