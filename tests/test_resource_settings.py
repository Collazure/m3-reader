"""Resource directory selection and lossless library operations."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from prts_tool.resource_settings import (configured_root, import_resources, initialize_resources,
                                         inspect_resources, move_resources, resource_root, save_resources)


def test_selection_and_existing_library(tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    monkeypatch.setenv("M3_READER_SETTINGS", str(settings))
    root = tmp_path / "existing"
    file = root / "collected/prts_text/story.txt"
    file.parent.mkdir(parents=True)
    file.write_text("existing", encoding="utf-8")
    assert initialize_resources(root) == 1
    assert file.read_text(encoding="utf-8") == "existing"
    assert save_resources(root) == 1
    assert configured_root() == root
    assert resource_root(tmp_path / "project") == root
    assert json.loads(settings.read_text(encoding="utf-8"))["resources_dir"] == str(root)
    override = tmp_path / "override"
    monkeypatch.setenv("M3_READER_RESOURCES", str(override))
    assert resource_root(tmp_path / "project") == override


def test_reject_unrelated_folder_and_links(tmp_path):
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    (unrelated / "other.txt").write_text("data", encoding="utf-8")
    with pytest.raises(ValueError, match="未知项目"):
        inspect_resources(unrelated)
    target = tmp_path / "target"
    initialize_resources(target)
    (target / "local/link").symlink_to(unrelated, target_is_directory=True)
    with pytest.raises(ValueError, match="软链接"):
        inspect_resources(target)
    link = tmp_path / "root-link"
    link.symlink_to(unrelated, target_is_directory=True)
    with pytest.raises(ValueError, match="软链接"):
        save_resources(link)


def test_import_preserves_existing_and_rejects_conflict(tmp_path):
    source, destination = tmp_path / "source", tmp_path / "destination"
    initialize_resources(source)
    initialize_resources(destination)
    (source / "local/one.txt").write_text("one", encoding="utf-8")
    (destination / "local/one.txt").write_text("one", encoding="utf-8")
    (source / "local/two.txt").write_text("two", encoding="utf-8")
    (source / "README.md").write_text("older instructions", encoding="utf-8")
    (destination / "README.md").write_text("newer instructions", encoding="utf-8")
    assert import_resources(source, destination) == (1, 1)
    assert (destination / "local/two.txt").read_text(encoding="utf-8") == "two"
    (source / "local/one.txt").write_text("different", encoding="utf-8")
    (source / "local/three.txt").write_text("three", encoding="utf-8")
    with pytest.raises(ValueError, match="冲突"):
        import_resources(source, destination)
    assert not (destination / "local/three.txt").exists()


def test_move_switches_only_after_copy_and_verification(tmp_path, monkeypatch):
    monkeypatch.setenv("M3_READER_SETTINGS", str(tmp_path / "settings.json"))
    source, destination = tmp_path / "source", tmp_path / "destination"
    initialize_resources(source)
    (source / "local/notes.txt").write_text("保留资料", encoding="utf-8")
    save_resources(source)
    assert move_resources(source, destination) == 1
    assert not source.exists()
    assert (destination / "local/notes.txt").read_text(encoding="utf-8") == "保留资料"
    assert configured_root() == destination


def test_fresh_crawler_process_uses_selected_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("M3_READER_SETTINGS", str(tmp_path / "settings.json"))
    selected = tmp_path / "chosen resources"
    save_resources(selected)
    environment = dict(os.environ)
    environment.pop("M3_READER_RESOURCES", None)
    result = subprocess.check_output(
        [sys.executable, "-c", "from prts_tool.paths import DEFAULT_TEXT_DIR; print(DEFAULT_TEXT_DIR)"],
        env=environment, text=True)
    assert result.strip() == str(selected / "collected/prts_text")
