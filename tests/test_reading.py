"""Shared reading positions and directory index selection."""

from pathlib import Path

from prts_tool import library, reading


def test_directory_prefers_module_index(tmp_path, monkeypatch):
    root = tmp_path / "resources"
    module = root / "collected" / "prts_text" / "avg"
    chapter = module / "主线" / "第一章"
    chapter.mkdir(parents=True)
    (root / "README.md").write_text("资料", encoding="utf-8")
    (module / "_索引.md").write_text("模块索引", encoding="utf-8")
    (chapter / "_索引.md").write_text("章节索引", encoding="utf-8")
    monkeypatch.setattr(library, "RESOURCES_DIR", root)
    assert library.directory_index(chapter) == module / "_索引.md"
    assert library.directory_index(root / "collected") == root / "README.md"


def test_reading_position_follows_text_after_refresh(tmp_path, monkeypatch):
    path = tmp_path / "story.txt"
    path.write_text("开头\n目标句\n结尾\n", encoding="utf-8")
    monkeypatch.setattr(reading, "READING_FILE", tmp_path / "reading.json")
    monkeypatch.setattr(reading, "relative_id", lambda source: source.name)
    monkeypatch.setattr(reading, "resource_path", lambda _resource_id: path)
    reading.save_position(path, line=2, quote="目标句")
    path.write_text("新增\n开头\n目标句\n结尾\n", encoding="utf-8")
    assert reading.position_for(path) == (3, None)
    assert reading.last_position() == (path, 3, None)


def test_corrupt_reading_state_falls_back_safely(tmp_path, monkeypatch):
    path = tmp_path / "story.txt"
    path.write_text("正文", encoding="utf-8")
    state = tmp_path / "reading.json"
    state.write_text('{"last": 42, "positions": {"story.txt": {"line": "bad"}}}', encoding="utf-8")
    monkeypatch.setattr(reading, "READING_FILE", state)
    monkeypatch.setattr(reading, "relative_id", lambda source: source.name)
    assert reading.position_for(path) == (1, None)


def test_tui_resume_uses_shared_position(tmp_path, monkeypatch):
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput
    from prts_tool.paths import RESOURCES_DIR
    from prts_tool.tui import TerminalLibrary

    monkeypatch.setattr(reading, "READING_FILE", tmp_path / "reading.json")
    path = RESOURCES_DIR / "README.md"
    with create_pipe_input() as pipe:
        tui = TerminalLibrary(input=pipe, output=DummyOutput())
        tui._open(path)
        tui._jump_buffer(tui.reader, 2)
        tui._save_reading()
        tui._show("帮助", "临时页面")
        tui._execute("resume")
        assert tui.selected == path
        assert tui.reader.buffer.document.cursor_position_row == 1
