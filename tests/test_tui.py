"""TUI command parsing, completion and feedback tests (no terminal required)."""

from __future__ import annotations

import asyncio
import sys

import pytest

pytest.importorskip("prompt_toolkit")

from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from prts_tool.library import relative_id
from prts_tool.paths import BOOK_DIR, RESOURCES_DIR
from prts_tool.tui import (CommandCompleter, TerminalLibrary, parse_index,
                           parse_update_request)


@pytest.fixture()
def tui():
    with create_pipe_input() as pipe_input:
        yield TerminalLibrary(input=pipe_input, output=DummyOutput())


@pytest.mark.parametrize("command,rest,expected", [
    ("update", "", ["refresh", "-m", "all", "--mode", "changed"]),
    ("update", "avg force", ["refresh", "-m", "avg", "--mode", "force"]),
    ("update", "force avg", ["refresh", "-m", "avg", "--mode", "force"]),
    ("update", "avg --dry-run", ["refresh", "-m", "avg", "--mode", "changed", "--dry-run"]),
    ("update", "--mode force avg", ["refresh", "-m", "avg", "--mode", "force"]),
    ("update", "avg -m missing", ["refresh", "-m", "avg", "--mode", "missing"]),
    ("update", "avg --mode=force", ["refresh", "-m", "avg", "--mode", "force"]),
    ("preview", "operator missing", ["refresh", "-m", "operator", "--mode", "missing", "--dry-run"]),
    ("images", "", ["terra-images", "--mode", "changed"]),
    ("images", "missing", ["terra-images", "--mode", "missing"]),
])
def test_parse_update_request(command, rest, expected):
    args, label = parse_update_request(command, rest)
    assert args == expected
    assert label


@pytest.mark.parametrize("command,rest", [
    ("update", "nope"),
    ("update", "images"),
    ("images", "avg"),
    ("update", "--mode nope"),
    ("update", "avg --mode=wat"),
])
def test_parse_update_request_rejects_bad_arguments(command, rest):
    with pytest.raises(ValueError):
        parse_update_request(command, rest)


def test_parse_index_is_friendly():
    assert parse_index("3", "行号", 5) == 3
    for bad in ("", "x", "0", "9"):
        with pytest.raises(ValueError):
            parse_index(bad, "行号", 5)


def _completions(text: str) -> list[str]:
    document = Document(text, cursor_position=len(text))
    return [item.text for item in CommandCompleter().get_completions(document, CompleteEvent())]


def test_command_completion():
    assert "update" in _completions("upd")
    assert "avg" in _completions("update av")
    assert _completions("update avg f") == ["force"]
    assert _completions("images m") == ["missing"]
    assert "operator" in _completions("preview o")
    assert "back" in _completions("bac")
    assert "next" in _completions("nex")
    assert _completions("update --mode ") == ["changed", "missing", "force"]
    assert _completions("update avg -m f") == ["force"]
    assert _completions("update --mode=f") == ["force"]


def test_startup_focus_is_command(tui):
    assert tui._focus_name() == "命令"


def test_tab_completes_unique_command_immediately(tui):
    async def scenario():
        run = asyncio.create_task(tui.app.run_async())
        await asyncio.sleep(0.1)
        tui.command.text = "hel"
        tui.command.buffer.cursor_position = 3
        tui._complete_command()
        await asyncio.sleep(0.1)
        text = tui.command.text
        tui.app.exit()
        await run
        return text

    assert asyncio.run(scenario()) == "help"


def test_panes_override_readonly_search_keys(tui):
    # prompt_toolkit binds n/N///? to in-buffer search in read-only buffers;
    # the panes must expose their own bindings so commands can start with them.
    for pane in (tui.tree, tui.reader):
        assert pane.control.key_bindings is not None
        for key in ("n", "N", "/", "?"):
            assert pane.control.key_bindings.get_bindings_for_keys((key,))


def test_submit_executes_and_clears_input(tui):
    tui.command.text = "help"
    tui._submit_command()
    assert "终端阅读器" in tui.reader.text
    assert tui.command.text == ""


def test_feedback_and_guidance(tui):
    tui._execute("help")
    assert "终端阅读器" in tui.reader.text
    assert tui._focus_name() == "命令"

    tui._execute("nonesuch")
    assert tui._status_level == "status.error"
    assert "未知命令" in tui._status_text
    assert "notes" in tui._status_text

    tui._execute("jump abc")
    assert "行号必须是数字" in tui._status_text

    tui._execute("go 1")
    assert "先执行 search" in tui._status_text

    tui._execute("run 1")
    assert "先执行 history" in tui._status_text


def test_accept_records_history_and_clears_input(tui):
    tui.command.text = "help"
    tui._submit_command()
    assert "help" in tui.command.buffer.history.get_strings()
    assert tui.command.text == ""


def test_empty_command_hint(tui):
    tui.command.text = ""
    tui._submit_command()
    assert "请输入命令" in tui._status_text


@pytest.mark.parametrize("command,prompt", [
    ("find", "find: "),
    ("search", "search: "),
    ("page", "page: "),
    ("note", "note: "),
    ("note+", "note+: "),
    ("import", "import: "),
])
def test_single_arg_command_enters_prompt_mode(tui, command, prompt):
    tui._execute(command)
    assert tui.input_mode == command
    assert tui._command_prompt == prompt
    assert tui.command.text == ""
    assert "直接回车退出" in tui._status_text


def test_empty_enter_leaves_prompt_mode(tui):
    tui._execute("search")
    tui._submit_command()
    assert tui.input_mode is None
    assert tui._command_prompt == " › "
    assert "已退出 search 输入" in tui._status_text


def test_prompt_value_runs_command_and_restores_prompt(tui, monkeypatch):
    tui._execute("note")
    calls = []
    monkeypatch.setattr(tui, "_execute",
                        lambda raw, allow_prompt=True: calls.append((raw, allow_prompt)))
    tui.command.text = "一条意见"
    tui._submit_command()
    assert calls == [("note 一条意见", False)]
    assert tui.input_mode is None
    assert tui._command_prompt == " › "


def test_alt_focus_bindings_exist(tui):
    for keys in (("escape", "1"), ("escape", "2"), ("escape", "3"),
                 ("escape", "left"), ("escape", "right")):
        assert tui.app.key_bindings.get_bindings_for_keys(keys)
        assert tui.reader.control.key_bindings.get_bindings_for_keys(keys)


def test_result_list_is_two_lines_and_enter_opens(tui):
    path = RESOURCES_DIR / "README.md"
    resource_id = relative_id(path)
    items = [
        {"head": f"1. {resource_id}:1", "body": "  第一条内容",
         "resource_id": resource_id, "line": 1, "page": None},
        {"head": f"2. {resource_id}:2", "body": "  第二条内容",
         "resource_id": resource_id, "line": 2, "page": None},
    ]
    tui._show_result_list("测试结果", items)
    lines = tui.reader.text.splitlines()
    assert lines[2] == items[0]["head"]
    assert lines[3] == items[0]["body"]
    assert lines[4] == items[1]["head"]
    assert tui.result_rows[2] == 0
    assert tui.result_rows[3] == 0
    assert tui.result_rows[4] == 1
    tui._jump_buffer(tui.reader, 5)
    tui._open_selected_result()
    assert not tui.results_mode
    assert tui.selected == path
    assert "已打开" in tui._status_text


def test_find_lists_matches_with_line_numbers(tui):
    path = RESOURCES_DIR / "README.md"
    tui.selected = path
    term = path.read_text(encoding="utf-8").splitlines()[0][:2] or "资源"
    tui._find(term)
    assert tui.results_mode
    assert tui.results
    assert tui.last_find == term
    assert all(item["line"] >= 1 for item in tui.results)


def test_reader_has_line_numbers_and_vim_bindings(tui):
    assert tui.reader.window.left_margins      # NumberedMargin
    keys = tui.reader.control.key_bindings
    for key in ("h", "j", "k", "l", "0", "$", "w", "b", "G", ":", "n", "N"):
        assert keys.get_bindings_for_keys((key,))
    assert keys.get_bindings_for_keys(("g", "g"))


def test_vim_line_jump_and_find_next(tui):
    tui.reader.text = "alpha\nbeta\ngamma\nbeta\n"
    tui.viewing_resource = True
    tui.last_find = "beta"
    tui._jump_buffer(tui.reader, 1)
    tui._vim_goto_line(3)
    assert tui.reader.buffer.document.cursor_position_row == 2
    tui._vim_find_next(False)
    assert tui.reader.buffer.document.cursor_position_row == 3
    tui._vim_find_next(True)
    assert tui.reader.buffer.document.cursor_position_row == 1
    assert "第 2 行" in tui._status_text


def test_back_returns_previous_pages(tui):
    paths = [path for path in tui.files
             if path.suffix.lower() in {".md", ".txt"} and 0 < path.stat().st_size < 5000][:2]
    if len(paths) < 2:
        pytest.skip("需要两个小型文本资源")
    first, second = paths
    tui._open(first)
    first_text = tui.reader.text
    tui._open(second)
    assert tui.selected == second

    tui._execute("back")
    assert tui.selected == first
    assert tui.reader.text == first_text

    tui._execute("back")
    assert tui.selected is None
    assert "终端阅读器" in tui.reader.text


def test_back_without_history(tui):
    tui._execute("back")
    assert "没有可返回" in tui._status_text


def test_back_restores_result_list(tui):
    path = RESOURCES_DIR / "README.md"
    resource_id = relative_id(path)
    items = [{"head": f"1. {resource_id}:1", "body": "  内容",
              "resource_id": resource_id, "line": 1, "page": None}]
    tui._show_result_list("测试", items)
    tui._jump_buffer(tui.reader, 3)
    tui._open_selected_result()
    assert not tui.results_mode

    tui._execute("back")
    assert tui.results_mode
    assert tui.results == items
    assert tui.result_rows[2] == 0


def test_next_opens_next_file_in_same_directory(tui):
    pages = sorted((RESOURCES_DIR / "local" / "大地巡旅" / "text" / "pages").glob("page_*.txt"))
    if len(pages) < 2:
        pytest.skip("需要至少两个本地文本文件")
    first, second = pages[0], pages[1]
    tui._open(first)
    tui._execute("next")
    assert tui.selected == second
    assert tui._status_text.startswith("下一个")

    tui.selected = pages[-1]
    tui._execute("next")
    assert "最后一个文件" in tui._status_text


def test_next_without_open_file(tui):
    tui.selected = None
    tui._execute("next")
    assert "请先打开一个文件" in tui._status_text


def test_page_reads_ocr_from_separated_text_directory(tui):
    pdf = next(BOOK_DIR.glob("*.pdf"))
    tui.selected = pdf
    tui._page("1")
    assert tui.reader.text.startswith("===== 第 1 页 =====")
    assert "PDF 第 1 页 OCR" in tui._status_text


def test_update_streams_output_and_reports(tui, monkeypatch):
    monkeypatch.setattr("prts_tool.tui.crawler_command",
                        lambda args: [sys.executable, "-X", "utf8", "-c",
                                      "print('hello'); print('world')"])
    asyncio.run(tui._run_update("update", "avg changed"))
    assert "hello" in tui.reader.text
    assert "world" in tui.reader.text
    assert "完成" in tui.reader.text and "退出码 0" in tui.reader.text
    assert tui._status_level == "status.ok"
    assert not tui.update_active


def test_update_can_be_cancelled(tui, monkeypatch):
    monkeypatch.setattr("prts_tool.tui.crawler_command",
                        lambda args: [sys.executable, "-X", "utf8", "-c",
                                      "import time; print('started', flush=True); time.sleep(30)"])

    async def scenario():
        task = asyncio.create_task(tui._run_update("update", "avg changed"))
        for _ in range(50):
            if "started" in tui.reader.text:
                break
            await asyncio.sleep(0.1)
        assert tui.update_active
        tui._cancel_update()
        await task

    asyncio.run(scenario())
    assert "已取消" in tui.reader.text
    assert tui._status_level == "status.warn"
    assert not tui.update_active
