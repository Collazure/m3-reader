"""Build and synchronize data-free M3 Reader release packages.

The script does not commit, push, install, or modify resources/workspace.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKS = ROOT / "installpacks"
REPOSITORY = "Collazure/m3-reader"
VERSION = re.search(
    r'__version__\s*=\s*"([^"]+)"',
    (ROOT / "prts_tool/__init__.py").read_text(encoding="utf-8"),
).group(1)
PACKAGES = (
    f"windows/m3-reader-{VERSION}-windows-x64-setup.exe",
    f"debian/m3-reader-{VERSION}-ubuntu-source.tar.gz",
    f"debian/m3-reader-{VERSION}-ubuntu-x64-portable.tar.gz",
    f"debian/m3-reader_{VERSION}_amd64.deb",
)


class ReleaseError(RuntimeError):
    pass


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def check_version() -> None:
    source = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    if not re.search(rf'^version\s*=\s*"{re.escape(VERSION)}"$', source, re.M):
        raise ReleaseError("pyproject.toml 与 prts_tool/__init__.py 版本不一致")


def write_checksums(*, complete: bool = False) -> None:
    present = [relative for relative in PACKAGES if (PACKS / relative).is_file()]
    if complete and len(present) != len(PACKAGES):
        raise ReleaseError("缺少当前版本的 Windows 或 Ubuntu 安装包")
    if not present:
        raise ReleaseError("当前版本没有安装包")
    lines = [f"{digest(PACKS / relative)}  {relative}" for relative in present]
    (PACKS / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def verify(*, complete: bool = False) -> None:
    check_version()
    manifest = PACKS / "SHA256SUMS.txt"
    if not manifest.is_file():
        raise ReleaseError("找不到 installpacks/SHA256SUMS.txt")
    seen: set[str] = set()
    for line in manifest.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([^\s]+)", line)
        if not match:
            raise ReleaseError(f"校验清单格式无效：{line}")
        expected, relative = match.groups()
        if relative not in PACKAGES or relative in seen:
            raise ReleaseError(f"校验清单包含旧版、重复或未知文件：{relative}")
        path = PACKS / relative
        if not path.is_file() or digest(path) != expected:
            raise ReleaseError(f"安装包校验失败：{relative}")
        seen.add(relative)
    if complete and seen != set(PACKAGES):
        raise ReleaseError("校验清单未包含当前版本的四个安装包")
    print(f"已验证 {len(seen)} 个 {VERSION} 安装包")


def build(*, package_only: bool = False) -> None:
    check_version()
    if sys.platform == "win32":
        if not package_only:
            shell = shutil.which("pwsh") or shutil.which("powershell")
            if not shell:
                raise ReleaseError("找不到 PowerShell")
            subprocess.run([shell, "-NoProfile", "-File", str(ROOT / "scripts/build_windows.ps1")],
                           cwd=ROOT, check=True)
        subprocess.run([sys.executable, str(ROOT / "scripts/package_installpacks.py"),
                        "--platform", "windows"], cwd=ROOT, check=True)
        # The Ubuntu source package can be prepared on Windows without Linux binaries.
        subprocess.run([sys.executable, str(ROOT / "scripts/package_installpacks.py"),
                        "--platform", "ubuntu-source"], cwd=ROOT, check=True)
    elif sys.platform.startswith("linux"):
        if not package_only:
            subprocess.run(["bash", str(ROOT / "scripts/build_ubuntu.sh")], cwd=ROOT, check=True)
        subprocess.run([sys.executable, str(ROOT / "scripts/package_installpacks.py"),
                        "--platform", "ubuntu"], cwd=ROOT, check=True)
    else:
        raise ReleaseError(f"不支持的平台：{sys.platform}")
    verify()


def github_json(path: str) -> dict:
    request = urllib.request.Request(
        f"https://api.github.com/repos/{REPOSITORY}/{path}",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "m3-reader-release"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        import json
        return json.load(response)


def ci_status(run_id: int) -> bool:
    jobs = github_json(f"actions/runs/{run_id}/jobs?per_page=20")["jobs"]
    states = {job["name"]: (job["status"], job.get("conclusion")) for job in jobs}
    for name in ("windows", "ubuntu"):
        print(f"{name}: {states.get(name, ('missing', None))}")
    if any(states.get(name, ("", ""))[1] in {"failure", "cancelled", "timed_out"}
           for name in ("windows", "ubuntu")):
        raise ReleaseError("CI 有失败的构建")
    return all(states.get(name) == ("completed", "success") for name in ("windows", "ubuntu"))


def sync_ubuntu(run_id: int, artifact_zip: Path) -> None:
    check_version()
    if not (PACKS / PACKAGES[0]).is_file():
        raise ReleaseError("请先构建当前版本的 Windows 安装包")
    if not ci_status(run_id):
        raise ReleaseError("Windows 和 Ubuntu CI 尚未全部通过")
    artifacts = github_json(f"actions/runs/{run_id}/artifacts?per_page=20")["artifacts"]
    artifact = next((item for item in artifacts if item["name"] == "m3-reader-ubuntu"), None)
    if artifact is None:
        raise ReleaseError("CI 未生成 m3-reader-ubuntu 产物")
    expected_zip = artifact.get("digest", "")
    if expected_zip != f"sha256:{digest(artifact_zip)}":
        raise ReleaseError("下载的 Ubuntu ZIP 与 GitHub 摘要不一致")
    linux = PACKAGES[1:]
    expected_members = {*(linux), "SHA256SUMS.txt"}
    build_dir = ROOT / "build"
    build_dir.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="release-sync-", dir=build_dir) as temporary:
        stage = Path(temporary).resolve()
        if stage.parent != build_dir.resolve():
            raise ReleaseError("暂存目录超出项目 build/")
        with zipfile.ZipFile(artifact_zip) as archive:
            if set(archive.namelist()) != expected_members:
                raise ReleaseError("Ubuntu ZIP 含有缺失或意外文件")
            lines = archive.read("SHA256SUMS.txt").decode("utf-8").splitlines()
            hashes = {}
            for line in lines:
                match = re.fullmatch(r"([0-9a-f]{64})  ([^\s]+)", line)
                if not match or match.group(2) not in linux:
                    raise ReleaseError("Ubuntu ZIP 校验清单无效")
                hashes[match.group(2)] = match.group(1)
            if set(hashes) != set(linux):
                raise ReleaseError("Ubuntu ZIP 校验清单不完整")
            for relative in linux:
                target = stage / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(relative) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                if digest(target) != hashes[relative]:
                    raise ReleaseError(f"Ubuntu 安装包校验失败：{relative}")
        portable = stage / linux[1]
        with tarfile.open(portable, "r:gz") as archive:
            for name in ("m3-reader", "m3-reader-gui"):
                member = archive.getmember(f"m3-reader/bin/ubuntu/{name}")
                if not member.isfile():
                    raise ReleaseError(f"Ubuntu 便携包缺少可执行文件：{name}")
                target = stage / "bin/ubuntu" / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
        for relative in linux:
            destination = PACKS / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(stage / relative, destination)
        for name in ("m3-reader", "m3-reader-gui"):
            destination = ROOT / "bin/ubuntu" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(stage / "bin/ubuntu" / name, destination)
            destination.chmod(destination.stat().st_mode | 0o111)
    write_checksums(complete=True)
    verify(complete=True)
    debian = (PACKS / "debian").resolve()
    for old in debian.iterdir():
        if (old.is_file() and old.name.startswith("m3-reader")
                and old.name not in {Path(relative).name for relative in linux}
                and old.name.endswith(("-ubuntu-source.tar.gz",
                                       "-ubuntu-x64-portable.tar.gz", "_amd64.deb"))):
            if old.resolve().parent != debian:
                raise ReleaseError(f"旧归档路径超出 installpacks/debian：{old}")
            old.unlink()
    print(f"Ubuntu CI {run_id} 已同步至 installpacks/debian 与 bin/ubuntu")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build_command = commands.add_parser("build", help="构建本机二进制与安装包")
    build_command.add_argument("--package-only", action="store_true", help="复用已构建的二进制")
    verify_command = commands.add_parser("verify", help="核对本机安装包 SHA-256")
    verify_command.add_argument("--complete", action="store_true", help="要求两端四个包齐全")
    status_command = commands.add_parser("ci-status", help="查询指定 GitHub Actions run")
    status_command.add_argument("--run-id", type=int, required=True)
    sync_command = commands.add_parser("sync-ubuntu", help="校验并同步 Ubuntu CI ZIP")
    sync_command.add_argument("--run-id", type=int, required=True)
    sync_command.add_argument("--artifact-zip", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "build":
            build(package_only=args.package_only)
        elif args.command == "verify":
            verify(complete=args.complete)
        elif args.command == "ci-status":
            return 0 if ci_status(args.run_id) else 2
        else:
            sync_ubuntu(args.run_id, args.artifact_zip)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError,
            urllib.error.URLError, ReleaseError) as exc:
        parser.exit(1, f"发布操作失败：{exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
