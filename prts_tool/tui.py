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
from .library import (IMAGE_SUFFIXES, PDF_SUFFIXES, TEXT_SUFFIXES, append_opinion,
                      read_opinions, relative_id, resource_files, resource_path, search_text,
                      source_kind)
from .paths import BOOK_DIR, OPINIONS_FILE, PROJECT_DIR, RESOURCES_DIR, TERRA_OCR_DIR, crawler_command

try:
    from prompt_toolkit import Application
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Dimension, HSplit, Layout, VSplit
    from prompt_toolkit.styles import Style
    from prompt_toolkit.widgets import Frame, Label, TextArea
except ImportError as exc:  # pragma: no cover
    raise SystemExit("TUI 需要 prompt_toolkit。请运行 python -m pip install prompt_toolkit") from exc


MODULES = ("all", "avg", "stage", "activity", "operator", "furniture", "enemies",
           "reclamation", "roguelike", "terra")
MODES = ("changed", "missing", "force")
COMMANDS = {
    "find": "当前文件查找",
    "search": "全库搜索",
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
    "quit": "退出",
}

HELP = """M3 Reader 终端阅读器

焦点与快捷键
  Tab          在「目录 → 阅读 → 命令」之间切换
  Esc          在命令栏按 Esc 返回目录
  Ctrl+F       当前文件查找      Ctrl+G  全库搜索
  Ctrl+U       更新              Ctrl+H  最近更新
  Ctrl+N       写意见            Ctrl+C  取消正在运行的更新
  Ctrl+Q       退出

命令栏（Tab 补全，↑↓ 翻历史，Enter 执行）
  find 词语                  当前文件查找
  search 词语                全库搜索；随后 go 序号 打开结果
  jump 行号                  跳到当前文本的指定行
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
  page 页号                  阅读《大地巡旅》PDF 对应页的 OCR
  open                       使用系统查看器打开当前图片或 PDF
  import 文件路径            导入本地资料；replace 文件路径 替换当前本地资料
  help / quit                帮助 / 退出

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
        self.tree = TextArea(read_only=True, scrollbar=True, wrap_lines=False)
        self.reader = TextArea(read_only=True, scrollbar=True, wrap_lines=True)
        self._status_text = "就绪 · Ctrl+Q 退出 · help 查看命令"
        self._status_level = "status.info"
        self.command = TextArea(height=1, prompt=" › ", multiline=False,
                                history=InMemoryHistory(),
                                completer=CommandCompleter(),
                                complete_while_typing=True)
        self.command.buffer.accept_handler = self._accept
        self.status = Label(text=lambda: [(f"class:{self._status_level}", f" {self._status_text} ")],
                            style="class:status")
        self.heading = Label(text=self._heading_fragments, style="class:heading")
        body = VSplit([Frame(self.tree, title="资源目录", width=Dimension(preferred=32, min=24, max=40)),
                       Frame(self.reader, title="阅读 / 搜索 / 差异")], padding=1)
        self.app = Application(input=input, output=output,
                               layout=Layout(HSplit([self.heading, body, self.status,
                                                       Frame(self.command, title="命令 · Tab 补全 · ↑↓ 历史")])),
                               key_bindings=self._keys(), full_screen=True, mouse_support=True,
                               style=Style.from_dict({
                                   "": "bg:#1f2329 #a8cfa7",
                                   "frame.border": "#688a71",
                                   "frame.label": "bold #cce08c",
                                   "heading": "bg:#202a30 #cce08c bold",
                                   "focus": "bg:#385246 #f0f9f9 bold",
                                   "status": "bg:#29313a #cce08c",
                                   "status.info": "bg:#29313a #cce08c",
                                   "status.ok": "bg:#1f3a2a #9ad27f bold",
                                   "status.warn": "bg:#3a3520 #e0c46c bold",
                                   "status.error": "bg:#3a2323 #f08c8c bold",
                               }))
        self.directories: dict[tuple[str, ...], set[str]] = {}
        self.file_nodes: dict[tuple[str, ...], Path] = {}
        self.expanded: set[tuple[str, ...]] = {(name,) for name in ("collected", "ocr", "local")}
        self.rows: list[tuple[str, ...]] = []
        self.selected: Path | None = None
        self.search_hits = []
        self.search_running = False
        self.runs = []
        self.active_run = None
        self.note_draft: list[str] = []
        self.current_pdf_page: int | None = None
        self.viewing_resource = False
        self.update_task = None
        self.update_active = False
        self.update_cancelled = False
        self.update_lines = 0
        self.update_last_line = ""
        self._update_pending: list[str] = []
        self._last_flush = 0.0
        self._book_text: str | None = None
        self._book_pages: dict[int, int] = {}
        self._reload_catalog()
        self.reader.text = HELP

    # -------------------------------------------------------------- 状态与焦点
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

    def _heading_fragments(self):
        return [("", "  M3 READER  /  资料终端     COLLECTED · OCR · LOCAL"),
                ("class:focus", f"  [{self._focus_name()}]")]

    def _set_status(self, text: str, level: str = "status.info") -> None:
        self._status_text = " ".join(str(text).split())
        if len(self._status_text) > 140:
            self._status_text = self._status_text[:139] + "…"
        self._status_level = level
        self.app.invalidate()

    def _show(self, title: str, body: str, *, level: str = "status.info", focus: bool = True) -> None:
        self.viewing_resource = False
        self.reader.text = body
        self.reader.buffer.cursor_position = 0
        self._set_status(title, level)
        if focus:
            self.app.layout.focus(self.reader)
        self.app.invalidate()

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

        @keys.add("c-q")
        def _(event):
            event.app.exit()

        @keys.add("tab", filter=Condition(lambda: self.app.layout.current_window is not self.command.window))
        def _(event):
            focus = event.app.layout.current_window
            target = self.reader if focus == self.tree.window else self.command if focus == self.reader.window else self.tree
            event.app.layout.focus(target)
            self._set_status(f"焦点：{self._focus_name()} · Tab 切换", "status.info")

        @keys.add("escape", filter=Condition(lambda: self.app.layout.current_window is self.command.window))
        def _(event):
            self.command.text = ""
            event.app.layout.focus(self.tree)
            self._set_status("已返回目录 · Tab 切换焦点", "status.info")

        @keys.add("c-c")
        def _(event):
            if self.update_active:
                self._cancel_update()
            else:
                self._set_status("按 Ctrl+Q 退出；更新中可按 Ctrl+C 取消", "status.info")

        @keys.add("enter", filter=Condition(lambda: self.app.layout.current_window is self.tree.window))
        def _(event):
            row = self.tree.buffer.document.cursor_position_row
            if row < len(self.rows):
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

        @keys.add("c-f")
        def _(event):
            self._prompt("find ", "输入词语后回车；Esc 返回")

        @keys.add("c-g")
        def _(event):
            self._prompt("search ", "输入词语后回车；随后用 go 序号 打开结果")

        @keys.add("c-u")
        def _(event):
            self._prompt("update ", "输入模块和模式，如 update avg changed；Ctrl+C 取消运行中的更新")

        @keys.add("c-h")
        def _(event):
            self._execute("history")

        @keys.add("c-n")
        def _(event):
            self._prompt("note ", "输入意见后回车；note+ 续写，save 保存")

        return keys

    def _prompt(self, text: str, hint: str = ""):
        self.command.text = text
        self.command.buffer.cursor_position = len(text)
        self.app.layout.focus(self.command)
        if hint:
            self._set_status(hint, "status.info")

    def _draw_tree(self):
        lines: list[str] = []
        rows: list[tuple[str, ...]] = []

        def visit(prefix: tuple[str, ...], level: int):
            names = sorted(self.directories.get(prefix, ()), key=lambda name: (prefix + (name,) in self.file_nodes, name.casefold()))
            for name in names:
                parts = prefix + (name,)
                is_file = parts in self.file_nodes
                marker = "·" if is_file else "▾" if parts in self.expanded else "▸"
                lines.append("  " * level + marker + " " + name)
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

    # -------------------------------------------------------------- 打开资源
    def _open(self, path: Path, line: int = 1):
        self.selected = path
        self.current_pdf_page = 1 if path.suffix.lower() in PDF_SUFFIXES else None
        kind = source_kind(path)
        resource_id = relative_id(path)
        if path.suffix.lower() in TEXT_SUFFIXES:
            self.reader.text = path.read_text(encoding="utf-8", errors="replace")
            total = self.reader.buffer.document.line_count
            line = max(1, min(line, total))
            self._jump_buffer(self.reader, line)
            self._set_status(f"{kind} · {resource_id} · 第 {line} / {total} 行", "status.info")
        elif path.suffix.lower() in IMAGE_SUFFIXES:
            parts = path.relative_to(RESOURCES_DIR).parts
            ocr = TERRA_OCR_DIR / parts[-3] / (parts[-2] + ".md") if len(parts) >= 4 and parts[0] == "collected" else None
            body = f"图片：{resource_id}\n\n输入 open 使用系统查看器查看原图。\n"
            if ocr and ocr.is_file():
                body += f"\n关联 OCR：{relative_id(ocr)}\n\n" + ocr.read_text(encoding="utf-8", errors="replace")
            self._show(f"{kind} · {resource_id}", body)
        elif path.suffix.lower() in PDF_SUFFIXES:
            self._show(f"{kind} · {resource_id}",
                       f"PDF：{resource_id}\n\n输入 page 页号 阅读对应页 OCR；输入 open 使用系统查看器查看原件。")
        self.viewing_resource = True
        self.app.layout.focus(self.reader)
        self.app.invalidate()

    # -------------------------------------------------------------- 命令分发
    def _accept(self, buffer):
        command = buffer.text.strip()
        if command:
            self._execute(command)
        else:
            self._set_status("请输入命令（help 查看用法）", "status.warn")
        return False

    def _execute(self, raw: str):
        command, _, rest = raw.strip().partition(" ")
        command = command.casefold()
        rest = rest.strip()
        try:
            if command in {"quit", "q"}:
                self.app.exit()
            elif command in {"help", "?"}:
                self._show("帮助 · Tab 补全 · ↑↓ 历史 · Ctrl+C 取消更新", HELP)
            elif command == "find":
                self._find(rest)
            elif command == "jump":
                self._jump(rest)
            elif command == "search":
                if not rest:
                    raise ValueError("请输入搜索词")
                if self.search_running:
                    raise ValueError("已有搜索在运行，请稍候")
                self.app.create_background_task(self._search(rest))
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
        body = self.reader.text
        start = self.reader.buffer.cursor_position + 1
        position = body.casefold().find(term.casefold(), start)
        if position < 0:
            position = body.casefold().find(term.casefold())
        if position < 0:
            self._set_status(f"当前文本没有匹配：{term}", "status.warn")
        else:
            self.reader.buffer.cursor_position = position
            self.app.layout.focus(self.reader)
            line = body.count("\n", 0, position) + 1
            self._set_status(f"文件内匹配 · 第 {line} 行 · {term}", "status.ok")

    def _jump(self, rest: str):
        if not self.reader.text.strip():
            raise ValueError("当前没有可跳转的文本")
        total = self.reader.buffer.document.line_count
        line = parse_index(rest, "行号", total)
        self._jump_buffer(self.reader, line)
        self.app.layout.focus(self.reader)
        self._set_status(f"已跳到第 {line} / {total} 行", "status.ok")

    async def _search(self, term: str):
        self.search_running = True
        self._set_status(f"正在搜索全部资源：{term} …", "status.warn")
        try:
            hits = await asyncio.to_thread(search_text, term, limit=200)
        except Exception as exc:
            self._set_status(f"搜索失败：{exc}", "status.error")
            return
        finally:
            self.search_running = False
        self.search_hits = hits
        lines = [f"全局搜索：{term} · {len(hits)} 条（上限 200）",
                 "输入 go 序号 打开命中行。", ""]
        if hits:
            lines.extend(f"{i:>3}. {hit.resource_id}:{hit.line}" +
                         (f" [PDF 第 {hit.page} 页]" if hit.page else "") +
                         f"  {hit.excerpt}" for i, hit in enumerate(hits, 1))
        else:
            lines.append("没有匹配，换一个词试试。")
        self._show(f"搜索完成 · {term} · {len(hits)} 条",
                   "\n".join(lines), level="status.ok" if hits else "status.warn")

    def _go(self, rest: str):
        if not self.search_hits:
            raise ValueError("先执行 search 词语，再用 go 序号 打开结果")
        number = parse_index(rest, "结果序号", len(self.search_hits))
        hit = self.search_hits[number - 1]
        self._open(resource_path(hit.resource_id), hit.line)
        if hit.page:
            self.current_pdf_page = hit.page
        self._set_status(f"已打开搜索结果 {number} · {hit.resource_id}:{hit.line}", "status.ok")

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
                  f"（Ctrl+C 取消；Tab 切到命令栏）\n" + "-" * 60 + "\n")
        self._show(f"更新中 · {label}", header, level="status.warn", focus=True)
        try:
            self.update_task = await asyncio.create_subprocess_exec(
                *crawler_command(args), cwd=str(PROJECT_DIR),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        except (OSError, NotImplementedError) as exc:
            self.update_active = False
            self.update_task = None
            self._set_status(f"启动更新失败：{exc}", "status.error")
            return

        self.app.create_background_task(self._update_ticker(started, label))
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
            source = BOOK_DIR / "大地巡旅_OCR.txt"
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
        self._show(f"PDF 第 {page} 页 OCR · 共 {len(self._book_pages)} 页",
                   self._book_text[start:end])
        self.current_pdf_page = page
        self.viewing_resource = True

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
