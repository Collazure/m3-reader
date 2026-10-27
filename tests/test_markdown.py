"""Markdown preview keeps terminal navigation aligned with source lines."""

from prts_tool.markdown import display_width, render_terminal_markdown, render_terminal_markdown_with_map


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


def test_terminal_markdown_aligns_cjk_table_without_losing_cells():
    source = ("| 名称 | 说明 |\n| :--- | ---: |\n"
              "| A | **重点** |\n| 中文 | 包含 \\| 竖线 |\n"
              "\n~~~md\n| 原样 | 保留 |\n| --- | --- |\n~~~\n")
    lines = render_terminal_markdown(source).splitlines()
    assert len(lines) == len(source.splitlines())
    assert "重点" in lines[2] and "**" not in lines[2]
    assert "包含 | 竖线" in lines[3]
    bars = [[display_width(line[:index]) for index, char in enumerate(line) if char == "│"]
            for line in (lines[0], lines[2], lines[3])]
    assert bars[0] == bars[1] == bars[2]
    assert display_width(lines[1][:lines[1].index("┼")]) == bars[0][1]
    assert lines[6] == "| 原样 | 保留 |"


def test_terminal_table_wraps_to_reader_width_and_maps_source_lines():
    source = ("| 路径 | 说明 | 维护方式 |\n| --- | --- | --- |\n"
              "| resources/collected/prts_text/ | 很长的中文说明，包含重要内容 | python -m prts_tool update |\n")
    rendered, line_map = render_terminal_markdown_with_map(source, table_width=44)
    lines = rendered.splitlines()
    assert len(lines) == len(line_map) and len(lines) > 3
    assert all(display_width(line) <= 44 for line in lines)
    assert line_map[:2] == [1, 2] and line_map[2:] == [3] * (len(lines) - 2)
    assert "resources/collected/prts_text/" in "".join(
        line.split("│")[1].strip() for line in lines[2:])
    assert "很长的中文说明，包含重要内容" in "".join(
        line.split("│")[2].strip() for line in lines[2:])


def test_terminal_table_respects_column_alignment():
    rows = render_terminal_markdown(
        "| One | Two |\n| :---: | ---: |\n| x | y |\n").splitlines()
    assert rows[2].split("│")[1] == "   x   "
    assert rows[2].split("│")[2] == "    y "


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
        assert tui.reader.text == render_terminal_markdown_with_map(
            source, table_width=tui._markdown_width())[0]
        assert len(tui._source_line_map) > len(source.splitlines())
        tui._jump("9")
        assert tui._source_line_at_cursor() == 9
        tui._save_reading()
        assert reading._load()["positions"]["README.md"]["quote"] == source.splitlines()[8]
