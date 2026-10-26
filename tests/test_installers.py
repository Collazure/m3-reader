"""Installer upgrade checks using isolated fake program files and user data."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(os.name == "nt", reason="requires Bash launcher")
def test_source_launcher_keeps_code_and_data_roots_separate(tmp_path):
    env = dict(os.environ, M3_READER_HOME=str(tmp_path / "user data"))
    result = subprocess.run(["bash", str(ROOT / "scripts/m3-reader"), "--version"],
                            cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "m3-reader, version" in result.stdout


def _fake_portable(root: Path, version: str) -> None:
    binary_dir = root / "bin/ubuntu"
    binary_dir.mkdir(parents=True, exist_ok=True)
    for name in ("m3-reader", "m3-reader-gui"):
        target = binary_dir / name
        target.write_text(f"#!/bin/sh\necho {version}\n", encoding="utf-8")
        target.chmod(0o755)
    icon = root / "assets/icon.png"
    icon.parent.mkdir(exist_ok=True)
    icon.write_bytes(b"test-icon")


@pytest.mark.skipif(os.name == "nt", reason="requires Bash launcher")
def test_linux_portable_upgrade_preserves_resources_and_chosen_location(tmp_path):
    source = tmp_path / "source"
    (source / "scripts").mkdir(parents=True)
    shutil.copy2(ROOT / "scripts/install_ubuntu_portable.sh", source / "scripts/install_ubuntu_portable.sh")
    shutil.copy2(ROOT / "scripts/ensure_user_path.sh", source / "scripts/ensure_user_path.sh")
    _fake_portable(source, "first")
    home = tmp_path / "home"
    home.mkdir()
    env = dict(os.environ, HOME=str(home))
    script = source / "scripts/install_ubuntu_portable.sh"
    subprocess.run(["bash", str(script)], env=env, check=True, capture_output=True)
    assert (home / ".profile").read_text(encoding="utf-8").count("# M3 Reader command path") == 1
    installed = home / ".local/opt/m3-reader"
    resource = installed / "resources/local/notes.txt"
    resource.write_text("保留资料", encoding="utf-8")
    _fake_portable(source, "second")
    subprocess.run(["bash", str(script)], env=env, check=True, capture_output=True)
    assert (home / ".profile").read_text(encoding="utf-8").count("# M3 Reader command path") == 1
    assert resource.read_text(encoding="utf-8") == "保留资料"
    assert subprocess.check_output([str(installed / "bin/ubuntu/m3-reader")], text=True).strip() == "second"

    chosen = tmp_path / "chosen installation"
    chosen_resource = chosen / "resources/local/notes.txt"
    chosen_resource.parent.mkdir(parents=True)
    chosen_resource.write_text("已有资料", encoding="utf-8")
    subprocess.run(["bash", str(script)], env={**env, "M3_READER_INSTALL_DIR": str(chosen)},
                   check=True, capture_output=True)
    assert chosen_resource.read_text(encoding="utf-8") == "已有资料"
    assert (home / ".local/bin/m3-reader").resolve() == chosen / "bin/ubuntu/m3-reader"
    assert not (chosen / "bin/windows").exists()


@pytest.mark.skipif(shutil.which("dpkg-deb") is None, reason="requires Debian packaging tools")
def test_deb_upgrade_contains_only_linux_program_and_preserves_user_data(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("m3_package", ROOT / "scripts/package_installpacks.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    project = tmp_path / "project"
    (project / "scripts").mkdir(parents=True)
    shutil.copy2(ROOT / "scripts/deb_launcher.sh", project / "scripts/deb_launcher.sh")
    monkeypatch.setattr(module, "ROOT", project)
    extracted = tmp_path / "extracted"
    resource = extracted / "home/user/.local/share/m3-reader/resources/local/notes.txt"
    resource.parent.mkdir(parents=True)
    resource.write_text("保留资料", encoding="utf-8")
    for version in ("1.0.0", "1.0.1"):
        _fake_portable(project, f"m3-reader, version {version}")
        monkeypatch.setattr(module, "VERSION", version)
        target = tmp_path / f"m3-reader_{version}_amd64.deb"
        module.build_deb(target)
        listing = subprocess.check_output(["dpkg-deb", "-c", str(target)], text=True)
        assert "./opt/m3-reader/bin/ubuntu/m3-reader" in listing
        assert "./usr/bin/m3-reader-gui" in listing
        assert "bin/windows" not in listing
        assert "resources/" not in listing
        subprocess.run(["dpkg-deb", "-x", str(target), str(extracted)], check=True)
        assert resource.read_text(encoding="utf-8") == "保留资料"
    assert subprocess.check_output([str(extracted / "opt/m3-reader/bin/ubuntu/m3-reader")],
                                   text=True).strip() == "m3-reader, version 1.0.1"


def test_linux_source_archive_has_no_windows_program_or_resource_payload(tmp_path):
    spec = importlib.util.spec_from_file_location("m3_package_source", ROOT / "scripts/package_installpacks.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target = tmp_path / "source.tar.gz"
    module.build_ubuntu(target)
    with tarfile.open(target, "r:gz") as archive:
        members = archive.getmembers()
    assert all("/bin/windows/" not in item.name and not item.name.endswith((".exe", ".ps1"))
               for item in members)
    assert all(item.isdir() for item in members if "/resources/" in item.name)
