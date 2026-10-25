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
    tui.command.buffer.validate_and_handle()
    assert "help" in tui.command.buffer.history.get_strings()
    assert tui.command.text == ""


def test_empty_command_hint(tui):
    tui.command.text = ""
    tui.command.buffer.validate_and_handle()
    assert "请输入命令" in tui._status_text


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
