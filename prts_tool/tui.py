"""Cross-platform full-screen terminal reader based on prompt_toolkit."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

from .history import diff_rows, import_local, list_runs, load_run
from .jobs import update_arguments
from .library import (IMAGE_SUFFIXES, PDF_SUFFIXES, TEXT_SUFFIXES, append_opinion,
                      read_opinions, relative_id, resource_files, resource_path, search_text,
                      source_kind)
from .paths import BOOK_DIR, OPINIONS_FILE, PROJECT_DIR, RESOURCES_DIR, TERRA_OCR_DIR, crawler_command

try:
    from prompt_toolkit import Application
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Dimension, HSplit, Layout, VSplit
    from prompt_toolkit.styles import Style
    from prompt_toolkit.widgets import Frame, Label, TextArea
except ImportError as exc:  # pragma: no cover
    raise SystemExit("TUI 需要 prompt_toolkit。请运行 python -m pip install prompt_toolkit") from exc


HELP = """M3 Reader 终端阅读器

目录：Tab 切换焦点；左侧上下移动，Enter 展开或打开文件。
快捷键：Ctrl+F 文件查找、Ctrl+G 全局搜索、Ctrl+U 更新、Ctrl+H 历史、Ctrl+N 意见、Ctrl+Q 退出。

在底部命令栏输入并回车：
  find 词语                 当前文件查找
  search 词语               全库搜索；随后 go 序号 打开结果
  jump 行号                 跳到当前文本的指定行
  update [模块] [模式]       更新采集内容，如 update avg changed
  preview [模块]            预览将更新的项目，不写入
  images [模式]             单独下载 terra 图片
  history                   列出最近的运行；run 序号 查看变化文件
  diff 序号                 查看当前运行的某项逐行差异
  notes                     查看本地意见
  note 内容                 直接写入本地意见文件；可用 note+ 续写，save 保存草稿
  notes                     阅读本地意见文件
  page 页号                 阅读《大地巡旅》PDF 对应页的 OCR
  open                      使用系统查看器打开当前图片或 PDF
  import 文件路径             导入本地资料；replace 文件路径 替换当前本地资料
  help / quit               帮助 / 退出

模块：all, avg, stage, activity, operator, furniture, enemies, reclamation, roguelike, terra。
模式：changed, missing, force。终端字体在终端设置中选择 Maple Mono NF CN。"""


class TerminalLibrary:
    def __init__(self, *, input=None, output=None):
        self.tree = TextArea(read_only=True, scrollbar=True, wrap_lines=False)
        self.reader = TextArea(read_only=True, scrollbar=True, wrap_lines=True)
        self.command = TextArea(height=1, prompt=" › ", multiline=False)
        self.command.buffer.accept_handler = self._accept
        self.status = Label(text="就绪 · Ctrl+Q 退出 · 输入 help 查看命令")
        self.heading = Label(text="  M3 READER  /  资料终端     COLLECTED · OCR · LOCAL")
        body = VSplit([Frame(self.tree, title="资源目录", width=Dimension(preferred=32, min=24, max=40)),
                       Frame(self.reader, title="阅读 / 搜索 / 差异")], padding=1)
        self.app = Application(input=input, output=output,
                               layout=Layout(HSplit([self.heading, body, self.status,
                                                       Frame(self.command, title="命令")]), focused_element=self.tree),
                               key_bindings=self._keys(), full_screen=True, mouse_support=True,
                               style=Style.from_dict({
                                   "": "bg:#1f2329 #a8cfa7",
                                   "frame.border": "#688a71",
                                   "frame.label": "bold #cce08c",
                                   "status": "bg:#29313a #cce08c",
                               }))
        self.directories: dict[tuple[str, ...], set[str]] = {}
        self.file_nodes: dict[tuple[str, ...], Path] = {}
        self.expanded: set[tuple[str, ...]] = {(name,) for name in ("collected", "ocr", "local")}
        self.rows: list[tuple[str, ...]] = []
        self.selected: Path | None = None
        self.search_hits = []
        self.runs = []
        self.active_run = None
        self.note_draft: list[str] = []
        self.current_pdf_page: int | None = None
        self.viewing_resource = False
        self.update_task = None
        self._reload_catalog()
        self.reader.text = HELP

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

        @keys.add("tab")
        def _(event):
            focus = event.app.layout.current_window
            target = self.reader if focus == self.tree.window else self.command if focus == self.reader.window else self.tree
            event.app.layout.focus(target)

        @keys.add("enter", filter=Condition(lambda: self.app.layout.current_window == self.tree.window))
        def _(event):
            row = self.tree.buffer.document.cursor_position_row
            if row < len(self.rows):
                parts = self.rows[row]
                path = self.file_nodes.get(parts)
                if path:
                    self._open(path)
                else:
                    if parts in self.expanded:
                        self.expanded.remove(parts)
                    else:
                        self.expanded.add(parts)
                    self._draw_tree()

        @keys.add("c-f")
        def _(event):
            self._prompt("find ")

        @keys.add("c-g")
        def _(event):
            self._prompt("search ")

        @keys.add("c-u")
        def _(event):
            self._prompt("update ")

        @keys.add("c-h")
        def _(event):
            self._execute("history")

        @keys.add("c-n")
        def _(event):
            self._prompt("note ")

        return keys

    def _prompt(self, text: str):
        self.command.text = text
        self.command.buffer.cursor_position = len(text)
        self.app.layout.focus(self.command)

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

    def _show(self, title: str, body: str):
        self.viewing_resource = False
        self.reader.text = body
        self.reader.buffer.cursor_position = 0
        self.status.text = title
        self.app.invalidate()

    @staticmethod
    def _jump_buffer(area: TextArea, line: int):
        line = max(1, min(line, area.buffer.document.line_count))
        area.buffer.cursor_position = area.buffer.document.translate_row_col_to_index(line - 1, 0)

    def _open(self, path: Path, line: int = 1):
        self.selected = path
        self.current_pdf_page = 1 if path.suffix.lower() in PDF_SUFFIXES else None
        kind = source_kind(path)
        resource_id = relative_id(path)
        if path.suffix.lower() in TEXT_SUFFIXES:
            self.reader.text = path.read_text(encoding="utf-8", errors="replace")
            self._jump_buffer(self.reader, line)
            self.status.text = f"{kind} · {resource_id} · 第 {line} 行"
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
        self.app.invalidate()

    def _accept(self, buffer):
        command = buffer.text.strip()
        self.command.text = ""
        if command:
            self._execute(command)
        return True

    def _execute(self, raw: str):
        command, _, rest = raw.partition(" ")
        command = command.casefold()
        rest = rest.strip()
        try:
            if command in {"quit", "q"}:
                self.app.exit()
            elif command in {"help", "?"}:
                self._show("帮助", HELP)
            elif command == "find":
                self._find(rest)
            elif command == "jump":
                self._jump_buffer(self.reader, int(rest))
                self.status.text = f"已跳到第 {rest} 行"
            elif command == "search":
                self.app.create_background_task(self._search(rest))
            elif command == "go":
                hit = self.search_hits[int(rest) - 1]
                self._open(resource_path(hit.resource_id), hit.line)
            elif command in {"update", "preview", "images"}:
                self.app.create_background_task(self._run_update(command, rest))
            elif command == "history":
                self._history()
            elif command == "run":
                self._run_details(int(rest))
            elif command == "diff":
                self._diff(int(rest))
            elif command == "notes":
                self._notes()
            elif command == "note":
                self.note_draft = [rest] if rest else []
                if rest:
                    self._save_note()
                else:
                    self.status.text = "意见草稿已开始：用 note+ 内容 续写，再用 save 保存"
            elif command == "note+":
                self.note_draft.append(rest)
                self.status.text = f"意见草稿：{len(self.note_draft)} 行"
            elif command == "save":
                self._save_note()
            elif command == "page":
                self._page(int(rest))
            elif command == "open":
                self._external_open()
            elif command in {"import", "replace"}:
                if not rest:
                    raise ValueError("请输入文件路径")
                if command == "replace" and not self.selected:
                    raise ValueError("请先打开要替换的本地资料")
                target = relative_id(self.selected) if command == "replace" else None
                run = import_local(Path(rest.strip('"')), target)
                path = resource_path(run["changes"][0]["resource_id"])
                parts = path.relative_to(RESOURCES_DIR).parts
                self.file_nodes[parts] = path
                for n in range(len(parts)):
                    self.directories.setdefault(parts[:n], set()).add(parts[n])
                self.expanded.add((parts[0],))
                self._draw_tree()
                self._open(path)
                self.status.text = "本地资料已导入并记入历史"
            else:
                raise ValueError("未知命令，输入 help 查看用法")
        except (ValueError, IndexError, KeyError, OSError) as exc:
            self.status.text = f"操作失败：{exc}"
        self.app.invalidate()

    def _find(self, term: str):
        if not term:
            raise ValueError("请输入搜索词")
        body = self.reader.text
        start = self.reader.buffer.cursor_position + 1
        position = body.casefold().find(term.casefold(), start)
        if position < 0:
            position = body.casefold().find(term.casefold())
        if position < 0:
            self.status.text = "当前文本没有匹配"
        else:
            self.reader.buffer.cursor_position = position
            self.app.layout.focus(self.reader)
            self.status.text = f"文件内匹配 · 第 {body.count(chr(10), 0, position) + 1} 行"

    async def _search(self, term: str):
        if not term:
            self.status.text = "请输入搜索词"
            return
        self.status.text = "正在搜索全部资源…"
        hits = await asyncio.to_thread(search_text, term, limit=200)
        self.search_hits = hits
        lines = [f"全局搜索：{term} · {len(hits)} 条（上限 200）", "输入 go 序号 打开命中行。", ""]
        lines.extend(f"{i:>3}. {hit.resource_id}:{hit.line}" +
                     (f" [PDF 第 {hit.page} 页]" if hit.page else "") +
                     f"  {hit.excerpt}" for i, hit in enumerate(hits, 1))
        self._show("全局搜索完成", "\n".join(lines))

    async def _run_update(self, command: str, rest: str):
        if self.update_task:
            self.status.text = "已有更新任务在运行"
            return
        try:
            words = rest.split()
            module = words[0] if words and command != "images" else "all"
            mode = words[1] if len(words) > 1 and command != "images" else words[0] if words and command == "images" else "changed"
            if module not in {"all", "avg", "stage", "activity", "operator", "furniture", "enemies", "reclamation", "roguelike", "terra"}:
                raise ValueError("未知模块")
            if mode not in {"changed", "missing", "force"}:
                raise ValueError("未知更新模式")
            args = update_arguments(module, mode, images=command == "images", preview=command == "preview")
            self._show("运行中 · " + " ".join(args), "")
            self.update_task = await asyncio.create_subprocess_exec(*crawler_command(args),
                                                                     cwd=str(PROJECT_DIR), stdout=asyncio.subprocess.PIPE,
                                                                     stderr=asyncio.subprocess.STDOUT)
            while line := await self.update_task.stdout.readline():
                self.reader.text += line.decode("utf-8", errors="replace")
                self.reader.buffer.cursor_position = len(self.reader.text)
                self.app.invalidate()
            code = await self.update_task.wait()
            self.status.text = f"任务结束 · 退出码 {code}"
            self._reload_catalog()
        except (ValueError, OSError) as exc:
            self.status.text = f"更新失败：{exc}"
        finally:
            self.update_task = None
            self.app.invalidate()

    def _history(self):
        self.runs = list_runs()
        lines = ["最近更新 · 输入 run 序号 查看变更文件", ""]
        lines += [f"{i:>3}. {run['started_at']}  [{run['status']}]  {run['changed']} 项  {run['command']}"
                  for i, run in enumerate(self.runs, 1)]
        self._show("最近更新", "\n".join(lines))

    def _run_details(self, number: int):
        self.active_run = load_run(self.runs[number - 1]["id"])
        lines = [f"运行：{self.active_run['command']} · {self.active_run['status']}",
                 "输入 diff 序号 查看逐行内容", ""]
        lines += [f"{i:>3}. {change['action']}  {change['resource_id']}"
                  for i, change in enumerate(self.active_run["changes"], 1)]
        self._show("更新项目", "\n".join(lines))

    def _diff(self, number: int):
        if not self.active_run:
            raise ValueError("先用 history 和 run 序号 选择一次更新")
        change = self.active_run["changes"][number - 1]
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

    def _notes(self):
        self._show(f"本地意见 · {OPINIONS_FILE}", read_opinions())

    def _save_note(self):
        if not any(part.strip() for part in self.note_draft):
            raise ValueError("请输入意见内容")
        append_opinion("\n".join(self.note_draft))
        self.note_draft = []
        self.status.text = f"意见已保存到 {OPINIONS_FILE}"

    def _page(self, page: int):
        if not self.selected or self.selected.suffix.lower() != ".pdf":
            raise ValueError("请先打开《大地巡旅》PDF")
        source = BOOK_DIR / "大地巡旅_OCR.txt"
        body = source.read_text(encoding="utf-8", errors="replace")
        start = body.find(f"===== 第 {page} 页 =====")
        if start < 0:
            raise ValueError("没有该页 OCR")
        end = body.find("===== 第 ", start + 1)
        self._show(f"PDF 第 {page} 页 OCR", body[start:end if end >= 0 else None])
        self.current_pdf_page = page
        self.viewing_resource = True

    def _external_open(self):
        if not self.selected:
            raise ValueError("请先打开文件")
        if os.name == "nt":
            os.startfile(self.selected)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(self.selected)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.status.text = "已交给系统查看器"

    def run(self):
        self.app.run()


def main() -> int:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise SystemExit("TUI 需要交互式终端；请在 Windows Terminal 或 Ubuntu 终端中运行")
    TerminalLibrary().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
