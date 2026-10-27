"""Cross-platform full-screen terminal reader based on prompt_toolkit."""

from __future__ import annotations

import asyncio
import difflib
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .history import diff_rows, import_local, list_runs, load_run
from .jobs import update_arguments
from .library import (IMAGE_SUFFIXES, PDF_SUFFIXES, SEARCH_SCOPES, TEXT_SUFFIXES, append_opinion, display_part, display_resource_id,
                      directory_index, parse_search_request, read_opinions, relative_id, resource_files, resource_path, search_text,
                      source_kind)
from .markdown import render_terminal_markdown_with_map
from .paths import BOOK_TEXT_DIR, DEFAULT_TEXT_DIR, OPINIONS_FILE, PROJECT_DIR, RESOURCES_DIR, TERRA_OCR_DIR, crawler_command
from .story_layout import migrate_story_layout
from .reading import last_position, position_for, save_position

try:
    from prompt_toolkit import Application
    from prompt_toolkit.completion import CompleteEvent, Completer, Completion
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys
    from prompt_toolkit.layout import Dimension, HSplit, Layout, VSplit
    from prompt_toolkit.layout.processors import BeforeInput
    from prompt_toolkit.styles import Style
    from prompt_toolkit.widgets import Frame, Label, TextArea
except ImportError as exc:  # pragma: no cover
    raise SystemExit("TUI 需要 prompt_toolkit。请运行 python -m pip install prompt_toolkit") from exc


MODULES = ("all", "avg", "stage", "activity", "operator", "furniture", "enemies",
           "reclamation", "roguelike", "terra")
MODES = ("changed", "missing", "force")
# Single-argument commands: when called without an argument, ask for it on a
# ``command:`` prompt instead of failing.  Empty Enter leaves the prompt.
PROMPT_COMMANDS = {
    "find": "搜索词",
    "search": "搜索词",
    "jump": "行号",
    "go": "结果序号",
    "run": "运行序号",
    "diff": "差异序号",
    "page": "页码",
    "note": "意见内容",
    "note+": "续写内容",
    "import": "文件路径",
    "replace": "文件路径",
}
COMMANDS = {
    "find": "当前文件查找",
    "search": "全库搜索",
    "font": "查看终端字号设置说明",
    "markdown": "切换 Markdown 源码与终端排版",
    "go": "打开搜索结果",
    "jump": "跳到当前文本行号",
    "update": "更新采集内容",
    "preview": "预览更新，不写入",
    "images": "下载 terra 图片",
    "history": "列出最近更新",
    "run": "查看某次运行的变更",
    "diff": "查看逐行差异",
    "notes": "查看本地意见",
    "note": "写一条意见",
    "note+": "续写意见草稿",
    "save": "保存意见草稿",
    "page": "阅读 PDF 对应页 OCR",
    "open": "用系统查看器打开当前文件",
    "import": "导入本地资料",
    "replace": "替换当前本地资料",
    "help": "帮助",
    "back": "返回上一个页面",
    "next": "打开本目录的下一个文件",
    "resume": "继续上次阅读",
    "quit": "退出",
}

HELP = """M3 Reader 终端阅读器

焦点与快捷键
  启动后直接处于命令栏；在目录区敲任意字符也会回到命令栏。
  阅读区是只读 vim 模式：用 `:` 或 Alt+3 回到命令栏。
  Alt+1 / Alt+2 / Alt+3   目录 / 阅读 / 命令
  Alt+← / Alt+→           循环焦点
  Tab                     命令栏补全（唯一匹配立即生效）
  Enter                   执行命令；搜索结果中打开选中项
  Backspace               编辑当前命令
  Ctrl+U                  清空当前命令（目录区为“更新”，阅读区为半页上）
  Ctrl+C                  清空或退出参数输入；更新中取消更新
  ↑ / ↓                   命令历史；Ctrl+P / Ctrl+N 同样可用
  PageUp / PageDown       滚动阅读区（阅读区空格下翻）
  Esc                     取消补全或参数输入；命令为空时返回目录
  Ctrl+F / Ctrl+G / Ctrl+H / Ctrl+N
                          在目录或阅读区：当前文件查找 / 全库搜索 / 历史 / 写意见
  Ctrl+Q                  退出

阅读区（只读 vim 操作，不需要 Enter）
  h j k l        左右上下移动         0 / $      行首 / 行尾
  w / b          下一个 / 上一个词    gg / G     文件开头 / 结尾
  3G             跳到第 3 行          5j / 2k    移动 5 行 / 2 行
  Ctrl+D / Ctrl+U  半页下 / 上        Ctrl+B     上翻一页
  n / N / ,      下一个 / 上一个匹配  `:`        回到命令栏
  / 查找、? 帮助、空格下翻、Ctrl+O 返回上一个页面。
  阅读区左侧显示绝对行号。

命令栏（Tab 补全，Enter 执行）
  find [词语]                当前文件直接定位；省略词语时提示 “find:”
  search [词语]              全库搜索；可用 search --scope local 词语 限定范围
                             范围：all / collected / local / ocr
  font size/reader/menu N    终端字号由终端程序设置；GUI 可直接设置阅读/任务栏字号
  markdown source/render    Markdown 源码 / 终端排版预览（保留行号）
  jump [行号]                跳到当前文本的指定行
  go [序号]                  打开上一次搜索的结果
  update [模块] [模式] [--dry-run]
                             更新采集内容，如 update avg changed
                             update avg --force；preview avg 只预览
  preview [模块] [模式]      预览将更新的项目，不写入
  images [模式]              单独下载 terra 图片
  history                    列出最近的运行；run 序号 查看变更文件
  diff 序号                  查看当前运行的某项逐行差异
  notes                      查看本地意见
  note 内容                  直接写入本地意见文件
  note 内容 + note+ 续写 + save  分多行写意见；save 保存草稿
  page [页号]                阅读《大地巡旅》PDF 对应页的 OCR
  open                       使用系统查看器打开当前图片或 PDF
  import [路径]              导入本地资料；replace [路径] 替换当前本地资料
  back                       返回上一个打开的页面（阅读区 Ctrl+O）
  next                       打开本目录的下一个文件
  resume                     继续上次阅读（GUI/TUI 共用本地位置）
  help / quit                帮助 / 退出

搜索与查找
  全库搜索结果每条占两行：第一行是文档路径与行号，第二行是匹配内容。
  ↑/↓ 选择条目，Enter 直接打开对应文档并跳到该行；输入字符或按 `:` 回到命令栏。
  find 与 / 在当前文件直接定位；n/N/, 可继续查找。
  单参数命令省略参数时会进入 “命令:” 提示，输入后回车执行；直接回车退出：
  find / search / jump / go / run / diff / page / note / note+ / import / replace。

模块：all, avg, stage, activity, operator, furniture, enemies, reclamation, roguelike, terra
模式：changed, missing, force。终端字体在终端设置中选择 Maple Mono NF CN。"""


def parse_update_request(command: str, rest: str) -> tuple[list[str], str]:
    """Turn an update/preview/images command into CLI arguments and a label.

    Modules and modes may be given in any order; ``--force``/``--missing``/
    ``--dry-run`` are accepted as convenient aliases.
    """
    images = command == "images"
    preview = command == "preview"
    module = "all"
    mode = "changed"
    tokens = rest.split()
    index = 0
    while index < len(tokens):
        raw = tokens[index]
        token = raw.strip().casefold()
        word = token.lstrip("-")
        if word in {"m", "mode"}:
            index += 1
            if index >= len(tokens):
                raise ValueError("--mode 后面要跟 changed、missing 或 force")
            mode = tokens[index].strip().casefold()
            if mode not in MODES:
                raise ValueError(f"未知模式 {tokens[index]!r}。可选：{', '.join(MODES)}")
        elif word.startswith("mode="):
            mode = word.split("=", 1)[1]
            if mode not in MODES:
                raise ValueError(f"未知模式 {mode!r}。可选：{', '.join(MODES)}")
        elif word in {"dry", "dry-run", "dryrun", "preview"}:
            preview = True
        elif word in MODES:
            mode = word
        elif word in MODULES:
            if images:
                raise ValueError("images 命令只接受模式：changed、missing、force")
            module = word
        elif word in {"image", "images"}:
            raise ValueError("下载 terra 图片请使用 images 命令")
        else:
            raise ValueError(
                f"未知参数 {raw!r}。模块：{', '.join(MODULES)}；"
                f"模式：{', '.join(MODES)}；也可加 --dry-run"
            )
        index += 1
    args = update_arguments(module, mode, images=images, preview=preview)
    label = f"{'terra 图片' if images else module} · {mode}"
    if preview:
        label += " · 预览"
    return args, label


def parse_index(rest: str, label: str, maximum: int | None = None) -> int:
    """Parse a 1-based number with a friendly error message."""
    words = rest.split()
    if not words:
        raise ValueError(f"请输入{label}")
    try:
        value = int(words[0])
    except ValueError:
        raise ValueError(f"{label}必须是数字：{words[0]!r}") from None
    if value < 1:
        raise ValueError(f"{label}从 1 开始")
    if maximum is not None and value > maximum:
        raise ValueError(f"{label}超出范围（1–{maximum}）")
    return value


def open_in_system(path: Path) -> None:
    """Open a file with the platform's default viewer (Windows / Linux / macOS)."""
    if os.name == "nt":
        if not hasattr(os, "startfile"):
            raise OSError("当前系统没有 os.startfile")
        os.startfile(str(path))  # type: ignore[attr-defined]
        return

    if sys.platform == "darwin":
        commands = [["open", str(path)]]
    else:
        commands = []
        xdg_open = shutil.which("xdg-open")
        gio = shutil.which("gio")
        if xdg_open:
            commands.append([xdg_open, str(path)])
        if gio:
            commands.append([gio, "open", str(path)])
    for command in commands:
        try:
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError:
            continue
    raise OSError("找不到系统查看器（Linux 需要 xdg-open 或 gio）")


class CommandCompleter(Completer):
    """Complete command names and update modules/modes as the user types."""

    def _options(self, prefix: str, options: list[tuple[str, str]]):
        for value, meta in options:
            if value.startswith(prefix):
                yield Completion(value, start_position=-len(prefix), display_meta=meta)

    @staticmethod
    def _update_options(command: str, args: list[str]) -> list[tuple[str, str]]:
        if command == "images":
            return [(mode, "模式") for mode in MODES] + [
                ("--dry-run", "预览"), ("--force", "强制"), ("--missing", "只补缺失")]
        words = [arg.casefold() for arg in args]
        if words and words[-1] in {"-m", "--mode"}:
            return [(mode, "模式") for mode in MODES]
        if len(words) >= 2 and words[-2] in {"-m", "--mode"}:
            return [(mode, "模式") for mode in MODES]
        words = [word.lstrip("-") for word in words]
        has_module = any(word in MODULES for word in words)
        has_mode = any(word in MODES for word in words)
        options: list[tuple[str, str]] = []
        if not has_module:
            options += [(module, "模块") for module in MODULES]
        if not has_mode:
            options += [(mode, "模式") for mode in MODES]
        options += [("--dry-run", "预览"), ("--force", "强制"), ("--missing", "只补缺失")]
        return options

    def get_completions(self, document, complete_event):
        before = document.text_before_cursor
        stripped = before.lstrip()
        if not stripped:
            yield from self._options("", sorted(COMMANDS.items()))
            return
        if " " not in stripped:
            yield from self._options(stripped, sorted(COMMANDS.items()))
            return
        command, _, rest = stripped.partition(" ")
        command = command.casefold()
        if command == "font":
            parts = rest.split()
            prefix = "" if rest.endswith(" ") else (parts[-1] if parts else "")
            options = ([("size", "字号命令")] if not parts or (len(parts) == 1 and not rest.endswith(" "))
                       else [(str(size), "GUI 字号") for size in (12, 14, 16, 18, 20)])
            yield from self._options(prefix, options)
            return
        if command == "markdown":
            yield from self._options(rest.strip().casefold(),
                                     [("source", "源码"), ("render", "终端排版")])
            return
        if command == "search":
            args = rest.split()
            if rest.startswith("--scope"):
                if len(args) == 1 and not rest.endswith(" "):
                    yield from self._options(args[0], [("--scope", "限定来源")])
                elif len(args) <= 2 and (rest.endswith(" ") or len(args) == 2):
                    prefix = "" if rest.endswith(" ") else args[-1]
                    yield from self._options(prefix, [(scope, "检索来源") for scope in sorted(SEARCH_SCOPES)])
            elif rest.startswith("-") and " " not in rest:
                yield from self._options(rest, [("--scope", "限定来源")])
            return
        if command in {"update", "preview", "images"}:
            args = rest.split()
            prefix = "" if rest.endswith(" ") else (args[-1] if args else "")
            if prefix.casefold().startswith("--mode="):
                value_prefix = prefix.split("=", 1)[1]
                for mode in MODES:
                    if mode.startswith(value_prefix):
                        yield Completion(mode, start_position=-len(value_prefix), display_meta="模式")
                return
            yield from self._options(prefix, self._update_options(command, args))


class TerminalLibrary:
    def __init__(self, *, input=None, output=None):
        migrate_story_layout(DEFAULT_TEXT_DIR / "avg")
        self.tree = TextArea(read_only=True, scrollbar=True, wrap_lines=False)
        self.reader = TextArea(read_only=True, scrollbar=True, wrap_lines=True, line_numbers=True)
        self._status_text = "就绪 · 直接输入命令 · Alt+1/2/3 切换焦点 · help 查看"
        self._status_level = "status.info"
        self.input_mode: str | None = None
        self._command_prompt = " › "
        self._vim_count = ""
        self.last_find = ""
        self.command = TextArea(height=1, prompt="", multiline=False,
                                history=InMemoryHistory(),
                                completer=CommandCompleter(),
                                complete_while_typing=False,
                                input_processors=[BeforeInput(
                                    lambda: self._command_prompt, style="class:command.prompt")])
        self.tree.control.key_bindings = self._pane_keys("tree")
        self.reader.control.key_bindings = self._pane_keys("reader")
        self.status = Label(text=lambda: [(f"class:{self._status_level}", f" {self._status_text} ")],
                            style="class:status")
        self.directory_frame = Frame(self.tree, title="资源目录", width=Dimension(preferred=32, min=24, max=40))
        self.reader_frame = Frame(self.reader, title="阅读区")
        body = VSplit([self.directory_frame, self.reader_frame], padding=1)
        self.app = Application(input=input, output=output,
                               layout=Layout(HSplit([body, self.status,
                                                     Frame(self.command, title="命令 · Tab 补全 · ↑↓ 历史")]),
                                             focused_element=self.command),
                               key_bindings=self._keys(), full_screen=True, mouse_support=True,
                               style=Style.from_dict({
                                   "": "bg:#1f2329 #a8cfa7",
                                   "frame.border": "#688a71",
                                   "frame.label": "bold #cce08c",
                                   "focus": "bg:#385246 #f0f9f9 bold",
                                   "status": "bg:#29313a #cce08c",
                                   "status.info": "bg:#29313a #cce08c",
                                   "status.ok": "bg:#1f3a2a #9ad27f bold",
                                   "status.warn": "bg:#3a3520 #e0c46c bold",
                                   "status.error": "bg:#3a2323 #f08c8c bold",
                                   "command.prompt": "bold #cce08c",
                               }))
        self.directories: dict[tuple[str, ...], set[str]] = {}
        self.file_nodes: dict[tuple[str, ...], Path] = {}
        self.expanded: set[tuple[str, ...]] = {(name,) for name in ("collected", "ocr", "local")}
        self.rows: list[tuple[str, ...]] = []
        self.selected: Path | None = None
        self.search_hits = []
        self.search_running = False
        self.results: list[dict] = []
        self.result_rows: list[int | None] = []
        self.results_mode = False
        self._view_history: list[dict] = []
        self.runs = []
        self.active_run = None
        self.note_draft: list[str] = []
        self.current_pdf_page: int | None = None
        self.viewing_resource = False
        self.view_kind = "static"
        self.markdown_formatted = True
        self._source_text = ""
        self._source_line_map: list[int] = []
        self._markdown_find_fresh = False
        self.update_task = None
        self.update_active = False
        self.update_cancelled = False
        self.update_lines = 0
        self.update_last_line = ""
        self._update_pending: list[str] = []
        self._last_flush = 0.0
        self._book_text: str | None = None
        self._book_pages: dict[int, int] = {}
        self._last_reading_save = 0.0
        self.reader.buffer.on_cursor_position_changed += self._reader_cursor_moved
        self._reload_catalog()
        self.reader.text = HELP

    # -------------------------------------------------------------- 状态与焦点
    def _pane_keys(self, kind: str):
        """Keys owned by the read-only panes.

        prompt_toolkit binds ``n``/``N``/``/``/``?`` to in-buffer search in
        read-only buffers, and those widget bindings take priority over the
        application's ``Keys.Any`` handler. Override them here so typing a
        command works from the tree and the reader, just like a terminal.
        """
        keys = KeyBindings()
        pane = self.reader if kind == "reader" else self.tree
        self._add_focus_keys(keys)

        if kind == "reader":
            self._add_vim_keys(keys)
        else:
            @keys.add("n")
            @keys.add("N")
            def _(event):
                self.app.layout.focus(self.command)
                self.command.buffer.insert_text(event.data)
                self._set_status("焦点：命令 · 输入 help 查看用法", "status.info")

        @keys.add("/")
        def _(event):
            self._execute("find")

        @keys.add("?")
        def _(event):
            self._execute("help")

        @keys.add("space")
        def _(event):
            if kind == "reader":
                self.reader.buffer.cursor_down(20)
            else:
                self._activate_tree_row()

        @keys.add("pageup")
        def _(event):
            pane.buffer.cursor_up(10)

        @keys.add("pagedown")
        def _(event):
            pane.buffer.cursor_down(10)

        return keys

    def _add_focus_keys(self, keys: KeyBindings):
        """Alt shortcuts for focus switching (Tab stays reserved for completion)."""

        @keys.add("escape", "1")
        def _(event):
            self._vim_count = ""
            self.app.layout.focus(self.tree)
            self._set_status("焦点：目录 · Alt+1/2/3 切换", "status.info")

        @keys.add("escape", "2")
        def _(event):
            self._vim_count = ""
            self.app.layout.focus(self.reader)
            self._set_status("焦点：阅读 · hjkl 移动 · gg/G 首尾 · 3G 指定行", "status.info")

        @keys.add("escape", "3")
        def _(event):
            self._vim_count = ""
            self.app.layout.focus(self.command)
            self._set_status("焦点：命令 · Alt+1/2/3 切换", "status.info")

        @keys.add("escape", "left")
        def _(event):
            self._cycle_focus(-1)

        @keys.add("escape", "right")
        def _(event):
            self._cycle_focus(1)

    def _cycle_focus(self, delta: int):
        order = (self.tree, self.reader, self.command)
        current = self.app.layout.current_window
        index = next((i for i, area in enumerate(order) if area.window is current), 0)
        self.app.layout.focus(order[(index + delta) % len(order)])
        self._set_status(f"焦点：{self._focus_name()} · Alt+1/2/3 切换", "status.info")

    # -------------------------------------------------------------- vim 只读操作
    def _vim_count_value(self) -> int | None:
        if not self._vim_count:
            return None
        value = int(self._vim_count)
        self._vim_count = ""
        return value

    def _vim_status(self) -> None:
        if self.results_mode:
            self._update_result_status()
            return
        document = self.reader.buffer.document
        markdown = self.viewing_resource and self.selected and self.selected.suffix.lower() == ".md"
        current = self._source_line_at_cursor() if markdown else document.cursor_position_row + 1
        total = (len(self._source_text.splitlines()) or 1) if markdown else document.line_count
        self._set_status(
            f"第 {current} / {total} 行 · "
            "hjkl 移动 · gg/G 首尾 · 3G 指定行 · n/N 下一个匹配", "status.info")

    def _vim_goto_line(self, line: int) -> None:
        markdown = self.viewing_resource and self.selected and self.selected.suffix.lower() == ".md"
        total = ((len(self._source_text.splitlines()) or 1) if markdown
                 else self.reader.buffer.document.line_count)
        line = max(1, min(int(line), total))
        self._jump_buffer(self.reader, self._display_line_for_source(line) if markdown else line)
        if self.results_mode:
            self._update_result_status()
        else:
            self._set_status(f"第 {line} / {total} 行", "status.info")

    def _vim_find_next(self, backwards: bool) -> None:
        term = self.last_find
        if not term:
            self._set_status("先用 / 或 find 搜索，再用 n/N 跳转", "status.warn")
            return
        if not self.viewing_resource:
            self._set_status("请先打开文档，再用 n/N 跳转", "status.warn")
            return
        if self.selected and self.selected.suffix.lower() == ".md" and self.markdown_formatted:
            needle = term.casefold()
            matches = [number for number, line in enumerate(self._source_text.splitlines(), 1)
                       if needle in line.casefold()]
            if not matches:
                self._set_status(f"没有匹配：{term}", "status.warn")
                return
            current = self._source_line_at_cursor()
            if backwards:
                candidates = ([line for line in matches if line <= current]
                              if self._markdown_find_fresh else
                              [line for line in matches if line < current])
                line = candidates[-1] if candidates else matches[-1]
            else:
                candidates = ([line for line in matches if line >= current]
                              if self._markdown_find_fresh else
                              [line for line in matches if line > current])
                line = candidates[0] if candidates else matches[0]
            self._markdown_find_fresh = False
            self._jump_buffer(self.reader, self._display_line_for_source(line))
            self._set_status(f"匹配 · 原文第 {line} 行 · {term}", "status.ok")
            return
        text = self.reader.text
        haystack = text.casefold()
        needle = term.casefold()
        current = self.reader.buffer.cursor_position
        if backwards:
            position = haystack.rfind(needle, 0, max(0, current - 1))
            if position < 0:
                position = haystack.rfind(needle)
        else:
            position = haystack.find(needle, current + 1)
            if position < 0:
                position = haystack.find(needle)
        if position < 0:
            self._set_status(f"没有匹配：{term}", "status.warn")
            return
        self.reader.buffer.cursor_position = position
        line = text.count("\n", 0, position) + 1
        self._set_status(f"匹配 · 第 {line} 行 · {term}", "status.ok")

    def _add_vim_keys(self, keys: KeyBindings) -> None:
        """Read-only vim motions for the reader pane; no editing operations."""
        buffer = self.reader.buffer

        def motion(action, *, page: bool = False) -> None:
            count = self._vim_count_value() or 1
            action(count * 10 if page else count)
            self._vim_status()

        @keys.add("h")
        def _(event):
            motion(lambda n: buffer.cursor_left(count=n))

        @keys.add("l")
        def _(event):
            motion(lambda n: buffer.cursor_right(count=n))

        @keys.add("j")
        def _(event):
            motion(lambda n: buffer.cursor_down(count=n))

        @keys.add("k")
        def _(event):
            motion(lambda n: buffer.cursor_up(count=n))

        @keys.add("0")
        def _(event):
            if self._vim_count:
                self._vim_count += "0"
                self._set_status(f"计数：{self._vim_count} · 等待动作", "status.info")
            else:
                buffer.cursor_position += buffer.document.get_start_of_line_position()
                self._vim_status()

        @keys.add("$")
        def _(event):
            buffer.cursor_position += buffer.document.get_end_of_line_position()
            self._vim_status()

        for digit in "123456789":
            @keys.add(digit)
            def _(event):
                self._vim_count += event.data
                self._set_status(f"计数：{self._vim_count} · 等待动作", "status.info")

        @keys.add("g", "g")
        def _(event):
            self._vim_goto_line(self._vim_count_value() or 1)

        @keys.add("G")
        def _(event):
            self._vim_goto_line(self._vim_count_value() or buffer.document.line_count)

        @keys.add("w")
        def _(event):
            count = self._vim_count_value() or 1
            offset = buffer.document.find_next_word_beginning(count=count)
            if offset:
                buffer.cursor_position += offset
            self._vim_status()

        @keys.add("b")
        def _(event):
            count = self._vim_count_value() or 1
            offset = buffer.document.find_previous_word_beginning(count=count)
            if offset:
                buffer.cursor_position += offset
            self._vim_status()

        @keys.add("c-d")
        def _(event):
            motion(lambda n: buffer.cursor_down(count=n), page=True)

        @keys.add("c-u")
        def _(event):
            motion(lambda n: buffer.cursor_up(count=n), page=True)

        @keys.add("c-b")
        def _(event):
            motion(lambda n: buffer.cursor_up(count=n), page=True)

        @keys.add(":")
        def _(event):
            self._vim_count = ""
            self.app.layout.focus(self.command)
            self._set_status("命令 · Enter 执行 · Alt+2 返回阅读", "status.info")

        @keys.add("n")
        @keys.add(",")
        def _(event):
            self._vim_find_next(False)

        @keys.add("N")
        def _(event):
            self._vim_find_next(True)

        @keys.add("c-o")
        def _(event):
            self._go_back()

        @keys.add("escape")
        def _(event):
            if self._vim_count:
                self._vim_count = ""
                self._set_status("已清除计数", "status.info")

    def _focus_name(self) -> str:
        try:
            window = self.app.layout.current_window
        except Exception:
            return "目录"
        if window is self.tree.window:
            return "目录"
        if window is self.reader.window:
            return "阅读"
        if window is self.command.window:
            return "命令"
        return "目录"

    def _set_status(self, text: str, level: str = "status.info") -> None:
        self._status_text = " ".join(str(text).split())
        if len(self._status_text) > 140:
            self._status_text = self._status_text[:139] + "…"
        self._status_level = level
        self.app.invalidate()

    def _show(self, title: str, body: str, *, level: str = "status.info", focus: bool = False,
              remember: bool = True) -> None:
        self._save_reading()
        if remember:
            self._push_view()
        self.viewing_resource = False
        self.view_kind = "static"
        self.results_mode = False
        self.results = []
        self.result_rows = []
        self._source_line_map = []
        self.reader.text = body
        self.reader.buffer.cursor_position = 0
        self._set_status(title, level)
        if focus:
            self.app.layout.focus(self.reader)
        self.app.invalidate()

    # -------------------------------------------------------------- 页面历史
    def _snapshot_view(self) -> dict:
        view = {
            "line": (self._source_line_at_cursor()
                     if self.viewing_resource and self.selected and self.selected.suffix.lower() == ".md"
                     else self.reader.buffer.document.cursor_position_row + 1),
            "selected": self.selected,
            "current_pdf_page": self.current_pdf_page,
            "viewing_resource": self.viewing_resource,
            "results": self.results,
            "result_rows": self.result_rows,
            "results_mode": self.results_mode,
            "status_text": self._status_text,
            "view_kind": self.view_kind,
            "source_text": self._source_text,
        }
        if self.view_kind in {"text", "image", "pdf"} and self.selected and self.selected.is_file():
            # Reopen from disk instead of retaining a second copy of large texts.
            view.update(kind="resource", path=self.selected, text=None)
        else:
            view.update(kind="static", path=None, text=self.reader.text)
        return view

    def _push_view(self) -> None:
        self._view_history.append(self._snapshot_view())
        if len(self._view_history) > 50:
            del self._view_history[0]

    def _go_back(self) -> None:
        """Return to the previously opened page (document, result list, help…)."""
        if self.update_active:
            self._set_status("更新进行中，完成后再用 back 返回", "status.warn")
            return
        if not self._view_history:
            self._set_status("没有可返回的页面", "status.warn")
            return
        self._save_reading()
        view = self._view_history.pop()
        if view.get("kind") == "resource" and view.get("path"):
            path = view["path"]
            if not path.is_file():
                self._set_status(f"文件已不存在：{path}", "status.error")
                return
            self._open(path, view["line"], remember=False)
            self.current_pdf_page = view["current_pdf_page"]
            self.view_kind = view.get("view_kind", "text")
            self._save_reading()
            self.app.layout.focus(self.reader)
            self._set_status(f"已返回 · {view['status_text']}", "status.info")
            self.app.invalidate()
            return
        self.view_kind = view.get("view_kind", "static")
        self.viewing_resource = False
        self._source_line_map = []
        self.reader.text = view["text"]
        self.selected = view["selected"]
        self.current_pdf_page = view["current_pdf_page"]
        self.viewing_resource = view["viewing_resource"]
        self._source_text = view.get("source_text", "")
        self.results = view["results"]
        self.result_rows = view["result_rows"]
        self.results_mode = view["results_mode"]
        self._jump_buffer(self.reader, view["line"])
        self._save_reading()
        self.app.layout.focus(self.reader)
        if self.results_mode:
            self._update_result_status()
        else:
            self._set_status(f"已返回 · {view['status_text']}", "status.info")
        self.app.invalidate()

    def _next_file(self) -> None:
        """Open the next file in the same directory (tree order)."""
        if not self.selected:
            raise ValueError("请先打开一个文件")
        path = self.selected
        siblings = sorted((item for item in self.files if item.parent == path.parent),
                          key=lambda item: item.name.casefold())
        if path not in siblings:
            raise ValueError("当前文件不在资源目录中")
        index = siblings.index(path)
        if index + 1 >= len(siblings):
            self._set_status(f"已经是本目录最后一个文件（{path.parent.name}）", "status.warn")
            return
        target = siblings[index + 1]
        self._open(target)
        self._set_status(f"下一个 · {relative_id(target)}", "status.ok")

    # -------------------------------------------------------------- 目录
    def _reload_catalog(self):
        self.files = list(resource_files())
        self.directories.clear()
        self.file_nodes.clear()
        for path in self.files:
            parts = path.relative_to(RESOURCES_DIR).parts
            self.file_nodes[parts] = path
            for n in range(len(parts)):
                self.directories.setdefault(parts[:n], set()).add(parts[n])
        self._draw_tree()

    def _keys(self):
        keys = KeyBindings()
        command_focus = Condition(lambda: self.app.layout.current_window is self.command.window)
        tree_focus = Condition(lambda: self.app.layout.current_window is self.tree.window)
        reader_focus = Condition(lambda: self.app.layout.current_window is self.reader.window)
        self._add_focus_keys(keys)

        @keys.add("c-q")
        def _(event):
            self._save_reading()
            event.app.exit()

        @keys.add("tab", filter=command_focus)
        def _(event):
            self._complete_command()

        @keys.add("tab", filter=~command_focus)
        def _(event):
            self._set_status("Tab 用于命令补全；Alt+1/2/3 切换目录/阅读/命令", "status.info")

        @keys.add("enter", filter=command_focus)
        def _(event):
            self._submit_command()

        @keys.add("enter", filter=tree_focus)
        def _(event):
            self._activate_tree_row()

        @keys.add("enter", filter=reader_focus)
        def _(event):
            if self.results_mode:
                try:
                    self._open_selected_result()
                except (OSError, ValueError, KeyError) as exc:
                    self._set_status(f"打开失败：{exc}", "status.error")

        @keys.add("escape", filter=command_focus)
        def _(event):
            if self.input_mode:
                self._exit_input_mode(f"已退出 {self.input_mode} 输入")
                return
            if self.command.buffer.complete_state:
                self.command.buffer.cancel_completion()
                return
            if self.command.text:
                self.command.text = ""
                self._set_status("命令已清空", "status.info")
                return
            event.app.layout.focus(self.tree)
            self._set_status("已返回目录 · Alt+1/2/3 切换焦点", "status.info")

        @keys.add("c-c")
        def _(event):
            if self.update_active:
                self._cancel_update()
            elif self.input_mode:
                self._exit_input_mode(f"已退出 {self.input_mode} 输入")
            elif command_focus():
                if self.command.text:
                    self.command.text = ""
                    self._set_status("命令已清空 · 按 Ctrl+Q 退出", "status.info")
                else:
                    self._set_status("按 Ctrl+Q 退出；输入 help 查看命令", "status.info")
            else:
                self._set_status("按 Ctrl+Q 退出；更新中可按 Ctrl+C 取消", "status.info")

        @keys.add("c-u", filter=command_focus)
        def _(event):
            self.command.text = ""
            self._set_status("命令已清空", "status.info")

        @keys.add("c-h", filter=command_focus)
        def _(event):
            # Some terminals send Ctrl+H for Backspace instead of 0x7f.
            self.command.buffer.delete_before_cursor()

        @keys.add("c-u", filter=~command_focus)
        def _(event):
            self._prompt("update ", "输入模块和模式，如 update avg changed；Ctrl+C 取消运行中的更新")

        @keys.add("c-p", filter=command_focus)
        def _(event):
            self.command.buffer.history_backward()

        @keys.add("c-n", filter=command_focus)
        def _(event):
            self.command.buffer.history_forward()

        @keys.add("pageup", filter=command_focus)
        def _(event):
            self.app.layout.focus(self.reader)
            self.reader.buffer.cursor_up(10)
            self._set_status("阅读区 · PageUp/PageDown 滚动 · 输入字符返回命令", "status.info")

        @keys.add("pagedown", filter=command_focus)
        def _(event):
            self.app.layout.focus(self.reader)
            self.reader.buffer.cursor_down(10)
            self._set_status("阅读区 · PageUp/PageDown 滚动 · 输入字符返回命令", "status.info")

        @keys.add(Keys.Any, filter=tree_focus)
        def _(event):
            self.app.layout.focus(self.command)
            self.command.buffer.insert_text(event.data)
            self._set_status("焦点：命令 · 输入 help 查看用法", "status.info")

        @keys.add("c-f", filter=~command_focus)
        def _(event):
            self._prompt("find ", "输入词语后回车；Esc 返回")

        @keys.add("c-g", filter=~command_focus)
        def _(event):
            self._prompt("search ", "输入词语后回车；随后用 go 序号 打开结果")

        @keys.add("c-h", filter=~command_focus)
        def _(event):
            self._execute("history")

        @keys.add("c-n", filter=~command_focus)
        def _(event):
            self._prompt("note ", "输入意见后回车；note+ 续写，save 保存")

        return keys

    def _prompt(self, text: str, hint: str = ""):
        self.command.text = text
        self.command.buffer.cursor_position = len(text)
        self.app.layout.focus(self.command)
        if hint:
            self._set_status(hint, "status.info")

    def _activate_tree_row(self):
        row = self.tree.buffer.document.cursor_position_row
        if row >= len(self.rows):
            return
        parts = self.rows[row]
        path = self.file_nodes.get(parts)
        if path:
            try:
                self._open(path)
            except (OSError, UnicodeError) as exc:
                self._set_status(f"打开失败：{exc}", "status.error")
        else:
            if parts in self.expanded:
                self.expanded.remove(parts)
            else:
                self.expanded.add(parts)
            self._draw_tree()
            if index := directory_index(RESOURCES_DIR.joinpath(*parts)):
                self._open(index)
                self.app.layout.focus(self.tree)
                self._set_status(f"目录索引 · {relative_id(index)} · Alt+2 阅读", "status.info")

    def _draw_tree(self):
        lines: list[str] = []
        rows: list[tuple[str, ...]] = []

        def visit(prefix: tuple[str, ...], level: int):
            names = sorted(self.directories.get(prefix, ()), key=lambda name: (prefix + (name,) in self.file_nodes, name.casefold()))
            for name in names:
                parts = prefix + (name,)
                is_file = parts in self.file_nodes
                marker = "·" if is_file else "▾" if parts in self.expanded else "▸"
                lines.append("  " * level + marker + " " + display_part(name))
                rows.append(parts)
                if not is_file and parts in self.expanded:
                    visit(parts, level + 1)

        visit((), 0)
        self.rows = rows
        current = self.tree.buffer.document.cursor_position_row
        self.tree.text = "\n".join(lines)
        self._jump_buffer(self.tree, min(current + 1, len(lines)))

    @staticmethod
    def _jump_buffer(area: TextArea, line: int):
        line = max(1, min(line, area.buffer.document.line_count))
        area.buffer.cursor_position = area.buffer.document.translate_row_col_to_index(line - 1, 0)

    def _markdown_width(self) -> int:
        try:
            columns = self.app.output.get_size().columns
        except (AttributeError, OSError):
            columns = shutil.get_terminal_size((120, 40)).columns
        return max(32, columns - 38)

    def _source_line_at_cursor(self) -> int:
        row = self.reader.buffer.document.cursor_position_row
        if self._source_line_map:
            return self._source_line_map[min(row, len(self._source_line_map) - 1)]
        return row + 1

    def _display_line_for_source(self, line: int) -> int:
        if self._source_line_map:
            return next((index for index, source in enumerate(self._source_line_map, 1)
                         if source >= line), len(self._source_line_map))
        return line

    def _display_markdown(self) -> None:
        if self.markdown_formatted:
            self.reader.text, self._source_line_map = render_terminal_markdown_with_map(
                self._source_text, table_width=self._markdown_width())
        else:
            self.reader.text = self._source_text
            self._source_line_map = []

    # -------------------------------------------------------------- 打开资源
    def _open(self, path: Path, line: int | None = None, *, remember: bool = True):
        self._save_reading()
        if remember:
            self._push_view()
        self.viewing_resource = False
        self.selected = path
        self.current_pdf_page = 1 if path.suffix.lower() in PDF_SUFFIXES else None
        kind = source_kind(path)
        resource_id = relative_id(path)
        saved_line, saved_page = position_for(path) if line is None or path.suffix.lower() in PDF_SUFFIXES else (1, None)
        line = line or saved_line
        if path.suffix.lower() in TEXT_SUFFIXES:
            self.view_kind = "text"
            self._source_text = path.read_text(encoding="utf-8", errors="replace")
            if path.suffix.lower() == ".md":
                self._display_markdown()
            else:
                self.reader.text = self._source_text
                self._source_line_map = []
            total = len(self._source_text.splitlines()) or 1
            line = max(1, min(line, total))
            self._jump_buffer(self.reader, self._display_line_for_source(line))
            self._set_status(f"{kind} · {resource_id} · 第 {line} / {total} 行", "status.info")
        elif path.suffix.lower() in IMAGE_SUFFIXES:
            self._source_line_map = []
            self.view_kind = "image"
            parts = path.relative_to(RESOURCES_DIR).parts
            ocr = TERRA_OCR_DIR / parts[-3] / (parts[-2] + ".md") if len(parts) >= 4 and parts[0] == "collected" else None
            body = f"图片：{resource_id}\n\n输入 open 使用系统查看器查看原图。\n"
            if ocr and ocr.is_file():
                body += f"\n关联 OCR：{relative_id(ocr)}\n\n" + ocr.read_text(encoding="utf-8", errors="replace")
            self._show(f"{kind} · {resource_id}", body, remember=False)
        elif path.suffix.lower() in PDF_SUFFIXES:
            self._source_line_map = []
            self.view_kind = "pdf"
            self._show(f"{kind} · {resource_id}",
                       f"PDF：{resource_id}\n\n输入 page 页号 阅读对应页 OCR；输入 open 使用系统查看器查看原件。",
                       remember=False)
            if saved_page:
                self.current_pdf_page = saved_page
        self.viewing_resource = True
        self._save_reading()
        self.app.layout.focus(self.reader)
        self.app.invalidate()

    # -------------------------------------------------------------- 命令分发
    def _complete_command(self):
        """Tab completion: apply a unique match immediately (no async lag)."""
        if self.input_mode:
            self._set_status(f"{self.input_mode}: 输入参数后回车；直接回车退出", "status.info")
            return
        buffer = self.command.buffer
        if buffer.complete_state:
            buffer.complete_next()
            return
        completions = list(self.command.completer.get_completions(
            buffer.document, CompleteEvent(completion_requested=True)))
        if len(completions) == 1:
            buffer.apply_completion(completions[0])
        elif completions:
            buffer.start_completion(insert_common_part=True)

    def _submit_command(self):
        """Enter submits the typed line itself, not the highlighted completion."""
        buffer = self.command.buffer
        if buffer.complete_state:
            buffer.cancel_completion()
        text = buffer.text.strip()
        mode = self.input_mode
        if mode:
            buffer.reset()
            self._exit_input_mode()
            if not text:
                self._set_status(f"已退出 {mode} 输入", "status.info")
                return
            buffer.history.append_string(f"{mode} {text}")
            self._execute(f"{mode} {text}", allow_prompt=False)
            return
        if not text:
            buffer.reset()
            self._set_status("请输入命令（help 查看用法）", "status.warn")
            return
        buffer.append_to_history()
        buffer.reset()
        self._execute(text)

    def _enter_input_mode(self, command: str):
        """Switch the command line to ``command:`` and wait for its argument."""
        self.input_mode = command
        self._command_prompt = f"{command}: "
        self.command.text = ""
        self.command.buffer.cursor_position = 0
        self.app.layout.focus(self.command)
        label = PROMPT_COMMANDS.get(command, "内容")
        self._set_status(f"{command}: 输入{label}后回车；直接回车退出", "status.info")
        self.app.invalidate()

    def _exit_input_mode(self, message: str | None = None):
        self.input_mode = None
        self._command_prompt = " › "
        self.command.text = ""
        if message:
            self._set_status(message, "status.info")
        self.app.invalidate()

    def _execute(self, raw: str, *, allow_prompt: bool = True):
        command, _, rest = raw.strip().partition(" ")
        command = command.casefold()
        rest = rest.strip()
        if allow_prompt and not rest and command in PROMPT_COMMANDS:
            self._enter_input_mode(command)
            return
        try:
            if command in {"quit", "q"}:
                self._save_reading()
                self.app.exit()
            elif command in {"help", "?"}:
                self._show("帮助 · Tab 补全 · ↑↓ 历史 · Ctrl+C 取消更新", HELP)
            elif command == "back":
                self._go_back()
            elif command == "next":
                self._next_file()
            elif command == "resume":
                target = last_position()
                if not target:
                    raise ValueError("暂无续读记录；先打开一份资料")
                path, line, page = target
                self._open(path, line)
                if page and path.suffix.lower() in PDF_SUFFIXES:
                    self.current_pdf_page = page
                self._set_status(f"继续阅读 · {relative_id(path)}", "status.ok")
            elif command == "find":
                self._find(rest)
            elif command == "jump":
                self._jump(rest)
            elif command == "search":
                if not rest:
                    raise ValueError("请输入搜索词")
                if self.search_running:
                    raise ValueError("已有搜索在运行，请稍候")
                parse_search_request(rest)
                self.app.create_background_task(self._search(rest))
            elif command == "font":
                if not re.fullmatch(r"(?:size|reader|menu)\s+\d+(?:\.\d+)?", rest):
                    raise ValueError("用法：font size 16、font reader 16 或 font menu 14")
                self._set_status("TUI 阅读区与菜单字号均由终端程序控制；请在终端设置中更改", "status.info")
            elif command == "markdown":
                self._markdown(rest)
            elif command == "go":
                self._go(rest)
            elif command in {"update", "preview", "images"}:
                if self.update_active:
                    raise ValueError("已有更新任务在运行（Ctrl+C 取消）")
                self.app.create_background_task(self._run_update(command, rest))
            elif command == "history":
                self._history()
            elif command == "run":
                self._run_details(rest)
            elif command == "diff":
                self._diff(rest)
            elif command == "notes":
                self._notes()
            elif command == "note":
                self._note(rest)
            elif command == "note+":
                self._note_append(rest)
            elif command == "save":
                self._save_note()
            elif command == "page":
                self._page(rest)
            elif command == "open":
                self._external_open()
            elif command in {"import", "replace"}:
                self._import(rest, replace=command == "replace")
            else:
                matches = difflib.get_close_matches(command, list(COMMANDS), n=1)
                hint = f"，你是不是要输入 {matches[0]!r}？" if matches else ""
                raise ValueError(f"未知命令 {command!r}{hint}。输入 help 查看用法")
        except (ValueError, IndexError, KeyError, OSError, RuntimeError) as exc:
            self._set_status(f"操作失败：{exc}", "status.error")
        except Exception as exc:  # keep the TUI alive on unexpected errors
            self._set_status(f"操作失败：{type(exc).__name__}: {exc}", "status.error")
        self.app.invalidate()

    # -------------------------------------------------------------- 阅读命令
    def _find(self, term: str):
        if not term:
            raise ValueError("请输入搜索词")
        path = self.selected
        if not self.viewing_resource or not path or path.suffix.lower() not in TEXT_SUFFIXES or not path.is_file():
            raise ValueError("请先打开一个文本文件再使用 find")
        search_text = (self._source_text if path.suffix.lower() == ".md" and self.markdown_formatted
                       else self.reader.text)
        if term.casefold() not in search_text.casefold():
            self._set_status(f"文件内没有匹配：{term}", "status.warn")
            return
        self.last_find = term
        self._markdown_find_fresh = True
        self._vim_find_next(False)
        self.app.layout.focus(self.reader)

    def _jump(self, rest: str):
        if not self.reader.text.strip():
            raise ValueError("当前没有可跳转的文本")
        total = (len(self._source_text.splitlines()) or 1
                 if self.viewing_resource and self.selected and self.selected.suffix.lower() == ".md"
                 else self.reader.buffer.document.line_count)
        line = parse_index(rest, "行号", total)
        self._jump_buffer(self.reader, self._display_line_for_source(line))
        self.app.layout.focus(self.reader)
        self._set_status(f"已跳到第 {line} / {total} 行", "status.ok")

    async def _search(self, term: str):
        query, scope = parse_search_request(term)
        self.search_running = True
        self.last_find = query
        self._set_status(f"正在搜索 {scope}：{query} …", "status.warn")
        try:
            hits = await asyncio.to_thread(search_text, query, limit=200, scope=scope)
        except Exception as exc:
            self._set_status(f"搜索失败：{exc}", "status.error")
            return
        finally:
            self.search_running = False
        self.search_hits = hits
        items = []
        for index, hit in enumerate(hits, 1):
            head = f"{index:>4}. {'[文件名] ' if hit.kind == 'title' else ''}{display_resource_id(hit.resource_id)}:{hit.line}"
            if hit.page:
                head += f" · PDF 第 {hit.page} 页"
            items.append({
                "head": head,
                "body": f"      {hit.excerpt}",
                "resource_id": hit.resource_id,
                "line": hit.line,
                "page": hit.page,
            })
        if items:
            title = (f"搜索：{query}（{scope}）· {len(items)} 条 · ↑↓ 选择 · Enter 打开")
            self._show_result_list(title, items, level="status.ok")
        else:
            self._show_result_list(f"搜索：{query} · 没有匹配；试试短词或其他范围", [],
                                   level="status.warn")

    def _go(self, rest: str):
        if not self.search_hits:
            raise ValueError("先执行 search 词语，再用 go 序号 打开结果")
        number = parse_index(rest, "结果序号", len(self.search_hits))
        hit = self.search_hits[number - 1]
        self._open(resource_path(hit.resource_id), hit.line)
        if hit.page:
            self.current_pdf_page = hit.page
        self._set_status(f"已打开搜索结果 {number} · {hit.resource_id}:{hit.line}", "status.ok")

    # -------------------------------------------------------------- 结果列表
    def _show_result_list(self, title: str, items: list[dict], *,
                          level: str = "status.ok") -> None:
        """Show two-line results: path/index first, matched content second."""
        lines = [title, ""]
        rows: list[int | None] = [None, None]
        for index, item in enumerate(items):
            lines.append(item["head"])
            rows.append(index)
            lines.append(item["body"])
            rows.append(index)
        self._show(title, "\n".join(lines), level=level, focus=True)
        self.results = items
        self.result_rows = rows
        self.results_mode = True
        if items:
            self._jump_buffer(self.reader, 3)     # header, blank, first head
            self._update_result_status()

    def _update_result_status(self) -> None:
        if not self.results_mode:
            return
        row = self.reader.buffer.document.cursor_position_row
        index = self.result_rows[row] if row < len(self.result_rows) else None
        if index is None:
            self._set_status(f"搜索结果 · {len(self.results)} 条 · ↑↓ 选择 · Enter 打开",
                             "status.info")
            return
        item = self.results[index]
        self._set_status(f"第 {index + 1}/{len(self.results)} 条 · {item['head']} · Enter 打开",
                         "status.info")

    def _reader_cursor_moved(self, _buffer=None) -> None:
        if self.results_mode:
            self._update_result_status()
        elif self.viewing_resource and time.monotonic() - self._last_reading_save >= 2:
            self._save_reading()

    def _save_reading(self) -> None:
        if not self.viewing_resource or not self.selected:
            return
        try:
            if self.selected.suffix.lower() in TEXT_SUFFIXES:
                row = self._source_line_at_cursor() - 1
                source_lines = self._source_text.splitlines()
                save_position(self.selected,
                              line=row + 1,
                              quote=source_lines[row] if row < len(source_lines) else "")
            elif self.selected.suffix.lower() in PDF_SUFFIXES:
                save_position(self.selected, page=self.current_pdf_page or 1)
            else:
                save_position(self.selected)
            self._last_reading_save = time.monotonic()
        except (OSError, ValueError):
            pass

    def _markdown(self, rest: str) -> None:
        mode = rest.casefold() or ("source" if self.markdown_formatted else "render")
        if mode not in {"source", "render"}:
            raise ValueError("用法：markdown source 或 markdown render")
        self.markdown_formatted = mode == "render"
        if self.viewing_resource and self.selected and self.selected.suffix.lower() == ".md":
            line = self._source_line_at_cursor()
            self._display_markdown()
            self._jump_buffer(self.reader, self._display_line_for_source(line))
        self._set_status(f"Markdown：{'终端排版' if self.markdown_formatted else '源码'}", "status.ok")

    def _open_selected_result(self) -> None:
        if not self.results_mode or not self.results:
            return
        row = self.reader.buffer.document.cursor_position_row
        index = self.result_rows[row] if row < len(self.result_rows) else None
        if index is None:
            self._set_status("把光标移到某条搜索结果上再按 Enter", "status.warn")
            return
        item = self.results[index]
        self._push_view()          # remember the result list before leaving it
        self.results_mode = False
        self._open(resource_path(item["resource_id"]), int(item["line"]), remember=False)
        if item.get("page"):
            self.current_pdf_page = int(item["page"])
        self._set_status(f"已打开 · {item['head']}", "status.ok")

    # -------------------------------------------------------------- 更新命令
    async def _run_update(self, command: str, rest: str):
        if self.update_active:
            self._set_status("已有更新任务在运行（Ctrl+C 取消）", "status.warn")
            return
        try:
            args, label = parse_update_request(command, rest)
        except ValueError as exc:
            self._set_status(f"更新参数错误：{exc}", "status.error")
            return

        self.update_active = True
        self.update_cancelled = False
        self.update_lines = 0
        self.update_last_line = ""
        self._update_pending.clear()
        self._last_flush = 0.0
        started = time.monotonic()
        header = (f"更新：{label}\n命令：m3-reader {' '.join(args)}\n"
                  f"（Ctrl+C 取消；Alt+3 切到命令栏）\n" + "-" * 60 + "\n")
        self._push_view()
        self._show(f"更新中 · {label}", header, level="status.warn", focus=True, remember=False)
        try:
            self.update_task = await asyncio.create_subprocess_exec(
                *crawler_command(args), cwd=str(PROJECT_DIR),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        except (OSError, NotImplementedError) as exc:
            self.update_active = False
            self.update_task = None
            self._set_status(f"启动更新失败：{exc}", "status.error")
            return

        ticker_task = asyncio.create_task(self._update_ticker(started, label))
        if self.update_cancelled:  # Ctrl+C arrived while the process was starting
            try:
                self.update_task.terminate()
            except OSError:
                pass
        try:
            stdout = self.update_task.stdout
            while stdout is not None and (line := await stdout.readline()):
                text = line.decode("utf-8", errors="replace")
                self.update_lines += 1
                stripped = text.strip()
                if stripped:
                    self.update_last_line = stripped
                self._append_update(text)
            code = await self.update_task.wait()
            self._flush_update()
            elapsed = time.monotonic() - started
            if self.update_cancelled:
                self._append_reader(f"\n{'-' * 60}\n已取消 · 用时 {elapsed:.1f} 秒\n")
                self._set_status(f"更新已取消 · 用时 {elapsed:.1f} 秒", "status.warn")
            elif code == 0:
                self._append_reader(f"\n{'-' * 60}\n完成 · 用时 {elapsed:.1f} 秒 · 退出码 0\n")
                self._set_status(f"更新完成 · {label} · {elapsed:.1f} 秒 · {self.update_lines} 行输出", "status.ok")
            else:
                self._append_reader(f"\n{'-' * 60}\n失败 · 用时 {elapsed:.1f} 秒 · 退出码 {code}\n")
                self._set_status(f"更新失败 · 退出码 {code} · 详见阅读区", "status.error")
            self._reload_catalog()
        except asyncio.CancelledError:
            self._set_status("更新任务已中止", "status.warn")
            raise
        except Exception as exc:
            self._flush_update()
            if self.update_task is not None:
                try:
                    self.update_task.terminate()
                except OSError:
                    pass
            self._set_status(f"更新出错：{exc}", "status.error")
        finally:
            ticker_task.cancel()
            self.update_task = None
            self.update_active = False
            self.update_cancelled = False
            self.app.invalidate()

    async def _update_ticker(self, started: float, label: str):
        while self.update_active:
            elapsed = time.monotonic() - started
            if self.update_cancelled:
                self._set_status(f"正在取消 · 已运行 {elapsed:.0f}s · {self.update_lines} 行",
                                 "status.warn")
            else:
                last = self.update_last_line
                if len(last) > 40:
                    last = last[:39] + "…"
                suffix = f" · {last}" if last else ""
                self._set_status(f"更新中 · {label} · {elapsed:.0f}s · {self.update_lines} 行{suffix}",
                                 "status.warn")
            await asyncio.sleep(0.5)

    def _cancel_update(self):
        if not self.update_active:
            self._set_status("当前没有更新任务；按 Ctrl+Q 退出", "status.info")
            return
        if self.update_cancelled:
            return
        self.update_cancelled = True
        self._set_status("正在取消更新…", "status.warn")
        task = self.update_task
        if task is not None:
            try:
                task.terminate()
            except ProcessLookupError:
                pass
            except OSError as exc:
                self._set_status(f"取消失败：{exc}", "status.error")

    def _append_update(self, text: str):
        if not text:
            return
        self._update_pending.append(text)
        if time.monotonic() - self._last_flush >= 0.12:
            self._flush_update()

    def _flush_update(self):
        if not self._update_pending:
            return
        self._append_reader("".join(self._update_pending))
        self._update_pending.clear()
        self._last_flush = time.monotonic()
        self.app.invalidate()

    def _append_reader(self, text: str):
        if not text:
            return
        current = self.reader.text
        if current and not current.endswith("\n"):
            current += "\n"
        self.reader.text = current + text
        self.reader.buffer.cursor_position = len(self.reader.text)

    # -------------------------------------------------------------- 历史命令
    def _history(self):
        try:
            self.runs = list_runs()
        except OSError as exc:
            raise ValueError(f"读取更新历史失败：{exc}") from exc
        if not self.runs:
            self._show("最近更新", "暂无更新历史。\n\n运行 update 或导入本地资料后，这里会列出每次运行。",
                       level="status.warn")
            return
        lines = ["最近更新 · 输入 run 序号 查看变更文件", ""]
        lines += [f"{i:>3}. {run.get('started_at', '')}  [{run.get('status', '')}]  "
                  f"{run.get('changed', len(run.get('changes') or []))} 项  {run.get('command', '')}"
                  for i, run in enumerate(self.runs, 1)]
        self._show(f"最近更新 · {len(self.runs)} 次", "\n".join(lines))

    def _run_details(self, rest: str):
        if not self.runs:
            raise ValueError("先执行 history 列出最近更新，再用 run 序号 查看")
        number = parse_index(rest, "运行序号", len(self.runs))
        run = load_run(self.runs[number - 1]["id"])
        if not run:
            raise ValueError("找不到这次运行的详情")
        self.active_run = run
        changes = run.get("changes") or []
        lines = [f"运行：{run.get('command', '')} · {run.get('status', '')}",
                 "输入 diff 序号 查看逐行内容", ""]
        lines += [f"{i:>3}. {change['action']}  {change['resource_id']}"
                  for i, change in enumerate(changes, 1)] or ["（这次运行没有变更文件）"]
        self._show("更新项目", "\n".join(lines))

    def _diff(self, rest: str):
        if not self.active_run:
            raise ValueError("先执行 history，再用 run 序号 选择一次更新")
        changes = self.active_run.get("changes") or []
        if not changes:
            raise ValueError("这次运行没有可查看的变更")
        number = parse_index(rest, "差异序号", len(changes))
        change = changes[number - 1]
        rows = diff_rows(change)
        added = sum(kind == "add" for kind, *_ in rows)
        removed = sum(kind == "remove" for kind, *_ in rows)
        lines = [f"{change['resource_id']}  +{added}  -{removed}",
                 "旧行  新行  | 内容", "-" * 60]
        for kind, old, new, content in rows:
            if kind in {"hunk", "meta"}:
                lines.append(content)
            else:
                marker = "+" if kind == "add" else "-" if kind == "remove" else " "
                lines.append(f"{old or '':>5} {new or '':>5}  {marker} {content}")
        self._show(f"逐行差异 · {change['resource_id']}", "\n".join(lines))

    # -------------------------------------------------------------- 意见命令
    def _notes(self):
        body = read_opinions()
        self._show(f"本地意见 · {OPINIONS_FILE}", body or "暂无意见。用 note 内容 添加。")

    def _note(self, rest: str):
        if not rest:
            self.note_draft = []
            self._set_status("意见草稿已开始：note+ 内容 续写，save 保存", "status.info")
            return
        self.note_draft = [rest]
        self._save_note()

    def _note_append(self, rest: str):
        if not rest:
            raise ValueError("请输入要续写的内容")
        if not self.note_draft:
            self.note_draft = []
        self.note_draft.append(rest)
        self._set_status(f"意见草稿：{len(self.note_draft)} 行 · save 保存", "status.info")

    def _save_note(self):
        if not any(part.strip() for part in self.note_draft):
            raise ValueError("意见草稿为空；先用 note 内容 或 note+ 内容 添加")
        append_opinion("\n".join(self.note_draft))
        self.note_draft = []
        self._set_status(f"意见已保存 · {OPINIONS_FILE}", "status.ok")

    # -------------------------------------------------------------- 其他资源
    def _page(self, rest: str):
        if not self.selected or self.selected.suffix.lower() not in PDF_SUFFIXES:
            raise ValueError("请先打开《大地巡旅》PDF 文件")
        page = parse_index(rest, "页码")
        if self._book_text is None:
            self._set_status("正在读取《大地巡旅》OCR…", "status.warn")
            source = BOOK_TEXT_DIR / "大地巡旅_OCR.txt"
            if not source.is_file():
                raise ValueError(f"找不到 OCR 文本：{source}")
            self._book_text = source.read_text(encoding="utf-8", errors="replace")
            self._book_pages = {int(match.group(1)): match.start()
                                for match in re.finditer(r"^===== 第 (\d+) 页 =====", self._book_text, re.M)}
        if not self._book_pages:
            raise ValueError("OCR 文本里没有分页标记")
        if page not in self._book_pages:
            low, high = min(self._book_pages), max(self._book_pages)
            raise ValueError(f"没有第 {page} 页 OCR（共 {low}–{high} 页）")
        start = self._book_pages[page]
        end = min((position for position in self._book_pages.values() if position > start),
                  default=len(self._book_text))
        self._push_view()
        self._show(f"PDF 第 {page} 页 OCR · 共 {len(self._book_pages)} 页",
                   self._book_text[start:end], remember=False)
        self.view_kind = "page"
        self.current_pdf_page = page
        self.viewing_resource = True
        self._save_reading()

    def _external_open(self):
        if not self.selected:
            raise ValueError("请先打开文件")
        if not self.selected.exists():
            raise ValueError(f"文件不存在：{self.selected}")
        open_in_system(self.selected)
        self._set_status(f"已交给系统查看器 · {self.selected.name}", "status.ok")

    def _import(self, rest: str, *, replace: bool):
        if not rest:
            raise ValueError("请输入文件路径")
        source = Path(rest.strip().strip('"').strip("'")).expanduser()
        if not source.exists():
            raise ValueError(f"找不到文件：{source}")
        if replace and not self.selected:
            raise ValueError("请先打开要替换的本地资料")
        target = relative_id(self.selected) if replace else None
        run = import_local(source, target)
        changes = run.get("changes") or []
        if not changes:
            raise ValueError("导入没有产生变更")
        path = resource_path(changes[0]["resource_id"])
        self._reload_catalog()
        parts = path.relative_to(RESOURCES_DIR).parts
        for n in range(1, len(parts)):
            self.expanded.add(parts[:n])
        self._draw_tree()
        self._open(path)
        self._set_status(f"{'已替换' if replace else '已导入'} · {changes[0]['resource_id']}", "status.ok")

    def run(self):
        try:
            self.app.run()
        finally:
            task = self.update_task
            if task is not None:
                try:
                    task.terminate()
                except OSError:
                    pass


def main() -> int:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise SystemExit("TUI 需要交互式终端；请在 Windows Terminal 或 Ubuntu 终端中运行")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    TerminalLibrary().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
