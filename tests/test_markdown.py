"""Markdown preview keeps terminal navigation aligned with source lines."""

from prts_tool.markdown import render_terminal_markdown


def test_terminal_markdown_preserves_lines_and_code():
    source = ("# 标题\n\n> 引用 **重点**\n- 条目 [链接](page.md)\n"
              "![图](pic.png)\n```python\n**代码原样**\n```\n")
    rendered = render_terminal_markdown(source)
    assert len(rendered.splitlines()) == len(source.splitlines())
    assert rendered.startswith("▸ 标题\n")
    assert "│ 引用 重点" in rendered
    assert "• 条目 链接 <page.md>" in rendered
    assert "[图片: 图] pic.png" in rendered
    assert "**代码原样**" in rendered


def test_tui_markdown_switch_keeps_source_quote(tmp_path, monkeypatch):
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput
    from prts_tool import reading
    from prts_tool.paths import RESOURCES_DIR
    from prts_tool.tui import TerminalLibrary

    monkeypatch.setattr(reading, "READING_FILE", tmp_path / "reading.json")
    path = RESOURCES_DIR / "README.md"
    source = path.read_text(encoding="utf-8")
    with create_pipe_input() as pipe:
        tui = TerminalLibrary(input=pipe, output=DummyOutput())
        tui._open(path)
        assert tui.reader.text != source
        assert tui.reader.text.startswith("▸ ")
        tui._execute("markdown source")
        assert tui.reader.text == source
        tui._execute("markdown render")
        assert tui.reader.text == render_terminal_markdown(source)
        tui._save_reading()
        assert reading._load()["positions"]["README.md"]["quote"] == source.splitlines()[0]
