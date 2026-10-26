"""Produce platform-specific installers without user resources.

Only explicitly listed program files and empty resource directories enter an archive.
Existing collected data, OCR output, local documents, opinions and history are excluded.
"""

from __future__ import annotations

import hashlib
import io
import argparse
import os
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
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
    "assets/icon.png",
    "pyproject.toml",
    "prts_crawler.py",
    "prts_story_crawler.py",
    "docs/APP_README.md",
    "scripts/entry_cli.py",
    "scripts/entry_gui.py",
    "scripts/build_ubuntu.sh",
    "scripts/install_ubuntu.sh",
    "scripts/install_ubuntu_portable.sh",
    "scripts/install_cli.sh",
    "scripts/ensure_user_path.sh",
    "scripts/m3-reader",
    "scripts/m3-reader-gui",
    *(path.relative_to(ROOT).as_posix() for path in sorted((ROOT / "prts_tool").rglob("*.py"))),
)
WINDOWS_FILES = ("bin/windows/m3-reader.exe", "bin/windows/m3-reader-gui.exe")
UBUNTU_FILES = ("bin/ubuntu/m3-reader", "bin/ubuntu/m3-reader-gui", "bin/ubuntu/m3-reader-gui.desktop")


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
    _check_binary_version(ROOT / WINDOWS_FILES[0])
    compiler = os.environ.get("M3_READER_ISCC") or shutil.which("ISCC.exe") or shutil.which("ISCC")
    if not compiler:
        for base in (Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Programs",
                     Path.home() / "AppData/Local/Programs",
                     Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))):
            for folder in ("Inno Setup 7", "Inno Setup 6"):
                candidate = base / folder / "ISCC.exe"
                if candidate.is_file():
                    compiler = str(candidate)
                    break
            if compiler:
                break
    if not compiler:
        raise RuntimeError("构建 Windows 安装包需要 Inno Setup 的 ISCC.exe")
    env = dict(os.environ, M3_READER_VERSION=VERSION)
    subprocess.run([str(compiler), str(ROOT / "scripts" / "windows_installer.iss")],
                   cwd=ROOT, env=env, check=True)
    if not target.is_file():
        raise FileNotFoundError(f"Inno Setup 未生成安装包：{target}")


def _check_binary_version(path: Path) -> None:
    result = subprocess.run([str(path), "--version"], text=True, capture_output=True, check=True)
    if result.stdout.strip() != f"m3-reader, version {VERSION}":
        raise RuntimeError(f"可执行程序版本与源码 {VERSION} 不一致：{path}：{result.stdout.strip()}")


def build_deb(target: Path) -> None:
    for name in UBUNTU_FILES[:2]:
        if not (ROOT / name).is_file():
            raise FileNotFoundError(f"请先构建 Linux 程序：{ROOT / name}")
    _check_binary_version(ROOT / UBUNTU_FILES[0])
    if not shutil.which("dpkg-deb"):
        raise RuntimeError("构建 .deb 需要 dpkg-deb")
    (ROOT / "build").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="m3-deb-", dir=ROOT / "build") as temp:
        stage = Path(temp)
        control = stage / "DEBIAN"
        control.mkdir()
        glibc_version = platform.libc_ver()[1]
        libc_dependency = f"libc6 (>= {glibc_version})" if re.fullmatch(r"\d+\.\d+", glibc_version) else "libc6"
        (control / "control").write_text(
            f"Package: m3-reader\nVersion: {VERSION}\nSection: utils\nPriority: optional\n"
            "Architecture: amd64\nMaintainer: Collazure\n"
            f"Depends: {libc_dependency}, libegl1, libgl1, libxkbcommon0, libxcb-cursor0\n"
            "Description: M3 Reader local PRTS resource reader\n"
            " Python-based offline reader and updater for PRTS resources.\n", encoding="utf-8")
        program_dir = stage / "opt/m3-reader/bin/ubuntu"
        program_dir.mkdir(parents=True)
        for name in UBUNTU_FILES[:2]:
            dest = program_dir / Path(name).name
            shutil.copy2(ROOT / name, dest)
            dest.chmod(0o755)
        bin_dir = stage / "usr/bin"
        bin_dir.mkdir(parents=True)
        for name in ("m3-reader", "m3-reader-gui"):
            dest = bin_dir / name
            shutil.copy2(ROOT / "scripts/deb_launcher.sh", dest)
            dest.chmod(0o755)
        desktop = stage / "usr/share/applications/m3-reader.desktop"
        desktop.parent.mkdir(parents=True)
        desktop.write_text("[Desktop Entry]\nType=Application\nName=M3 Reader\n"
                           "Comment=阅读和更新 PRTS 资料\nExec=/usr/bin/m3-reader-gui\n"
                           "Icon=m3-reader\nTerminal=false\nCategories=Office;Utility;\n", encoding="utf-8")
        desktop.chmod(0o644)
        icon = stage / "usr/share/pixmaps/m3-reader.png"
        icon.parent.mkdir(parents=True)
        shutil.copy2(ROOT / "assets/icon.png", icon)
        icon.chmod(0o644)
        for directory in (stage, *(path for path in stage.rglob("*") if path.is_dir())):
            directory.chmod(0o755)
        subprocess.run(["dpkg-deb", "--root-owner-group", "--build", str(stage), str(target)], check=True)


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


def build_ubuntu_portable(target: Path) -> None:
    for name in UBUNTU_FILES[:2]:
        if not (ROOT / name).is_file():
            raise FileNotFoundError(f"请先在 Ubuntu 构建程序：{ROOT / name}")
    _check_binary_version(ROOT / UBUNTU_FILES[0])
    with tarfile.open(target, "w:gz") as archive:
        payload = ("# M3 Reader Ubuntu 便携版\n\n解压后运行 bash scripts/install_ubuntu_portable.sh "
                   "即可创建应用菜单入口；也可直接运行 bin/ubuntu/m3-reader-gui。\n"
                   "资料首次使用时下载，本包不含采集正文和个人文件。\n").encode("utf-8")
        info = tarfile.TarInfo(f"{PREFIX}/README-install.md")
        info.size = len(payload)
        info.mode = 0o644
        archive.addfile(info, io.BytesIO(payload))
        for name in EMPTY_DIRS:
            info = tarfile.TarInfo(f"{PREFIX}/{name}")
            info.type = tarfile.DIRTYPE
            info.mode = 0o755
            archive.addfile(info)
        for name in UBUNTU_FILES[:2] + ("assets/icon.png", "scripts/install_ubuntu_portable.sh",
                                       "scripts/ensure_user_path.sh"):
            path = ROOT / name
            info = archive.gettarinfo(str(path), arcname=f"{PREFIX}/{name}")
            info.mode = 0o755 if name in UBUNTU_FILES or name.endswith(".sh") else 0o644
            with path.open("rb") as source:
                archive.addfile(info, source)


def _package_family(path: Path) -> str | None:
    name = path.name
    if path.parent.name == "windows" and name.startswith("m3-reader-") and path.suffix in {".zip", ".exe"}:
        return "windows"
    for family, suffix in (("ubuntu-source", "-ubuntu-source.tar.gz"),
                           ("ubuntu-portable", "-ubuntu-x64-portable.tar.gz")):
        if name.startswith("m3-reader-") and name.endswith(suffix):
            return family
    if name.startswith("m3-reader_") and name.endswith("_amd64.deb"):
        return "ubuntu-deb"
    return None


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build data-free M3 Reader install packages")
    parser.add_argument("--platform", choices=("windows", "ubuntu-source", "ubuntu-portable", "ubuntu-deb", "ubuntu", "all"),
                        default="windows" if os.name == "nt" else "ubuntu")
    platform = parser.parse_args().platform
    output = ROOT / "installpacks"
    windows = output / "windows" / f"m3-reader-{VERSION}-windows-x64-setup.exe"
    ubuntu = output / "debian" / f"m3-reader-{VERSION}-ubuntu-source.tar.gz"
    portable = output / "debian" / f"m3-reader-{VERSION}-ubuntu-x64-portable.tar.gz"
    deb = output / "debian" / f"m3-reader_{VERSION}_amd64.deb"
    targets = []
    if platform in ("windows", "all"):
        windows.parent.mkdir(parents=True, exist_ok=True)
        build_windows(windows)
        targets.append(windows)
    if platform in ("ubuntu-source", "ubuntu", "all"):
        ubuntu.parent.mkdir(parents=True, exist_ok=True)
        build_ubuntu(ubuntu)
        targets.append(ubuntu)
    if platform in ("ubuntu-portable", "ubuntu") or (platform == "all" and all((ROOT / name).is_file() for name in UBUNTU_FILES)):
        portable.parent.mkdir(parents=True, exist_ok=True)
        build_ubuntu_portable(portable)
        targets.append(portable)
    if platform in ("ubuntu-deb", "ubuntu") or (platform == "all" and all((ROOT / name).is_file() for name in UBUNTU_FILES[:2])):
        deb.parent.mkdir(parents=True, exist_ok=True)
        build_deb(deb)
        targets.append(deb)
    for target in targets:
        folder = target.parent
        for older in folder.iterdir():
            if (older.is_file() and older != target and older not in targets
                    and _package_family(older) == _package_family(target)):
                older.unlink()
    current_packages = [path for path in (windows, ubuntu, portable, deb) if path.is_file()]
    checksums = "\n".join(f"{_checksum(path)}  {path.relative_to(output).as_posix()}"
                          for path in current_packages) + "\n"
    (output / "SHA256SUMS.txt").write_bytes(checksums.encode("utf-8"))
    for path in targets:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
