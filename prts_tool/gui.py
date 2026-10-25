"""Qt desktop reader for the PRTS resource library."""

from __future__ import annotations

import re
import sys
import codecs
from pathlib import Path

from .history import diff_rows, import_local, list_runs, load_run
from .jobs import update_arguments, update_command_sequence
from .library import (IMAGE_SUFFIXES, PDF_SUFFIXES, TEXT_SUFFIXES, read_opinions,
                      relative_id, resource_files, resource_path, search_text,
                      source_kind, write_opinions)
from .paths import BOOK_DIR, OPINIONS_FILE, PROJECT_DIR, RESOURCES_DIR, crawler_command

try:
    from PySide6.QtCore import QPointF, QProcess, Qt, QThread, Signal
    from PySide6.QtGui import QAction, QColor, QFont, QPainter, QPixmap, QSyntaxHighlighter, QTextCharFormat, QTextCursor, QTextFormat
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtPdfWidgets import QPdfView
    from PySide6.QtWidgets import (QApplication, QComboBox, QDockWidget, QHBoxLayout,
                                   QFileDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
                                   QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSplitter,
                                   QTabWidget, QTextEdit, QToolBar, QTreeWidget, QTreeWidgetItem,
                                   QVBoxLayout, QWidget)
except ImportError as exc:  # pragma: no cover - tested with the optional Qt runtime
    raise SystemExit("GUI 需要 PySide6。请运行 python -m pip install PySide6 PySide6-Addons") from exc


STYLE = """
QWidget { background: #1f2329; color: #a8cfa7; font-family: 'Maple Mono NF CN','Noto Sans Mono CJK SC',monospace; font-size: 13px; }
QMainWindow, QDockWidget { background: #191f24; }
QToolBar, QMenuBar, QStatusBar { background: #202a30; border-bottom: 1px solid #4f5f5f; spacing: 7px; padding: 5px; }
QTreeWidget, QListWidget, QPlainTextEdit, QLineEdit, QComboBox { background: #1f2329; color: #a8cfa7; border: 1px solid #41534b; selection-background-color: #40536a; selection-color: #f0f9f9; }
QTreeWidget::item, QListWidget::item { padding: 3px; }
QPushButton { background: #29383a; color: #cce08c; border: 1px solid #688a71; padding: 5px 10px; }
QPushButton:hover { background: #3a5547; }
QPushButton:disabled { color: #829684; border-color: #41534b; }
QTabBar::tab { background: #273137; color: #a8cfa7; border: 1px solid #41534b; padding: 7px 14px; }
QTabBar::tab:selected { background: #385246; color: #f0f9f9; }
QHeaderView::section { background: #29383a; color: #cce08c; padding: 5px; }
QDockWidget::title { background: #29383a; color: #cce08c; padding: 6px; }
QScrollBar { background: #1f2329; width: 12px; }
QScrollBar::handle { background: #4f695b; }
"""


class SearchThread(QThread):
    ready = Signal(list)

    def __init__(self, query: str):
        super().__init__()
        self.query = query

    def run(self):
        self.ready.emit(search_text(self.query, limit=10000))


class ReaderHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self.heading = QTextCharFormat()
        self.heading.setForeground(QColor("#cce08c"))
        self.heading.setFontWeight(QFont.Weight.Bold)
        self.speaker = QTextCharFormat()
        self.speaker.setForeground(QColor("#8cd0d3"))
        self.metadata = QTextCharFormat()
        self.metadata.setForeground(QColor("#829684"))

    def highlightBlock(self, text):
        if text.startswith("#") or text.startswith("====="):
            self.setFormat(0, len(text), self.heading)
        elif text.startswith(("生成时间：", "抓取时间：", "来源：", "出处：")):
            self.setFormat(0, len(text), self.metadata)
        else:
            match = re.match(r"^[^\s：:]{1,24}[：:]", text)
            if match:
                self.setFormat(0, match.end(), self.speaker)


class LineArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(self.editor.line_width(), 0)

    def paintEvent(self, event):
        self.editor.paint_lines(event)


class TextReader(QPlainTextEdit):
    def __init__(self, path: Path):
        super().__init__()
        self.path = path
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setFont(QFont("Maple Mono NF CN", 14))
        self.setPlainText(path.read_text(encoding="utf-8", errors="replace"))
        self.highlighter = ReaderHighlighter(self.document())
        self.line_area = LineArea(self)
        self.blockCountChanged.connect(self._margin)
        self.updateRequest.connect(self._scroll_margin)
        self.cursorPositionChanged.connect(self._highlight_line)
        self._margin()
        self._highlight_line()

    def line_width(self):
        digits = len(str(max(1, self.blockCount())))
        return 14 + self.fontMetrics().horizontalAdvance("9") * digits

    def _margin(self, *_):
        self.setViewportMargins(self.line_width(), 0, 0, 0)

    def _scroll_margin(self, rect, dy):
        if dy:
            self.line_area.scroll(0, dy)
        else:
            self.line_area.update(0, rect.y(), self.line_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._margin()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.line_area.setGeometry(0, self.contentsRect().top(), self.line_width(), self.contentsRect().height())

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            steps = event.angleDelta().y() / 120
            if steps:
                font = self.font()
                font.setPointSizeF(max(8, min(32, font.pointSizeF() + steps)))
                self.setFont(font)
                self._margin()
                self.line_area.update()
            event.accept()
        else:
            super().wheelEvent(event)

    def paint_lines(self, event):
        painter = QPainter(self.line_area)
        painter.fillRect(event.rect(), QColor("#1f2329"))
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        while block.isValid() and top <= event.rect().bottom():
            height = round(self.blockBoundingRect(block).height())
            if block.isVisible() and top + height >= event.rect().top():
                painter.setPen(QColor("#cce08c" if block == self.textCursor().block() else "#829684"))
                painter.drawText(0, top, self.line_width() - 5, self.fontMetrics().height(),
                                 Qt.AlignmentFlag.AlignRight, str(number + 1))
            block = block.next()
            number += 1
            top += height

    def _highlight_line(self):
        selection = QTextEdit.ExtraSelection()
        selection.format.setBackground(QColor("#29313a"))
        selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        self.setExtraSelections([selection])
        self.line_area.update()

    def jump(self, line: int):
        block = self.document().findBlockByNumber(max(0, line - 1))
        if block.isValid():
            cursor = QTextCursor(block)
            self.setTextCursor(cursor)
            self.centerCursor()
            self.setFocus()


class ImageReader(QScrollArea):
    def __init__(self, path: Path):
        super().__init__()
        self.path = path
        self.original = QPixmap(str(path))
        self.scale = 1.0
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWidget(self.label)
        self.setWidgetResizable(False)
        self._draw()

    def _draw(self):
        if self.original.isNull():
            self.label.setText("图片无法读取")
            return
        scaled = self.original.scaled(self.original.size() * self.scale,
                                      Qt.AspectRatioMode.KeepAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation)
        self.label.setPixmap(scaled)
        self.label.resize(scaled.size())

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.scale = max(.1, min(5, self.scale * (1.2 if event.angleDelta().y() > 0 else .8)))
            self._draw()
            event.accept()
        else:
            super().wheelEvent(event)


class PdfReader(QWidget):
    def __init__(self, path: Path):
        super().__init__()
        self.path = path
        self.document = QPdfDocument(self)
        self.view = QPdfView(self)
        self.view.setDocument(self.document)
        self.view.setPageMode(QPdfView.PageMode.MultiPage)
        self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        self.page_box = QLineEdit("1")
        self.page_box.setMaximumWidth(55)
        self.page_box.returnPressed.connect(self.jump_from_box)
        row = QHBoxLayout()
        row.addWidget(QLabel("PDF 页码"))
        row.addWidget(self.page_box)
        row.addStretch()
        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addWidget(self.view)
        self.document.load(str(path))

    def jump_from_box(self):
        try:
            self.jump(int(self.page_box.text()))
        except ValueError:
            pass

    def jump(self, page: int):
        page = max(1, min(self.document.pageCount(), page))
        self.view.pageNavigator().jump(page - 1, QPointF(), 0)
        self.page_box.setText(str(page))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("M3 Reader // 资料终端")
        self.resize(1500, 920)
        self.current_path: Path | None = None
        self.search_worker: SearchThread | None = None
        self.process: QProcess | None = None
        self.update_queue: list[list[str]] = []
        self.readers: dict[str, QWidget] = {}
        self.wrap_enabled = True
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["资源目录"])
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.itemClicked.connect(self.click_tree_item)
        self.tree.itemDoubleClicked.connect(self.open_tree_item)
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._tab_changed)
        split = QSplitter()
        split.addWidget(self.tree)
        split.addWidget(self.tabs)
        split.setSizes([360, 1100])
        self.setCentralWidget(split)
        self.make_toolbar()
        self.make_search_dock()
        self.make_history_dock()
        self.make_notes_dock()
        self.make_jobs_dock()
        self.reload_tree()
        self.reload_history()
        self.reload_opinions()
        self.statusBar().showMessage("资料就绪 · 双击左侧文件打开 · Ctrl+F 文件搜索 · Ctrl+Shift+F 全局搜索")

    def make_toolbar(self):
        bar = QToolBar("操作")
        self.addToolBar(bar)
        bar.addWidget(QLabel("  M3 Reader / 资料终端   "))
        self.find_input = QLineEdit()
        self.find_input.setPlaceholderText("文件内查找 Ctrl+F")
        self.find_input.setMaximumWidth(260)
        self.find_input.returnPressed.connect(self.find_next)
        bar.addWidget(self.find_input)
        bar.addAction("下一个 F3", self.find_next)
        self.global_input = QLineEdit()
        self.global_input.setPlaceholderText("全局搜索 Ctrl+Shift+F")
        self.global_input.setMaximumWidth(270)
        self.global_input.returnPressed.connect(self.global_search)
        bar.addWidget(self.global_input)
        bar.addAction("搜索", self.global_search)
        self.module = QComboBox()
        self.module.addItems(["all", "avg", "stage", "activity", "operator", "furniture", "enemies", "reclamation", "roguelike", "terra"])
        bar.addWidget(self.module)
        self.mode = QComboBox()
        self.mode.addItems(["changed", "missing", "force"])
        bar.addWidget(self.mode)
        self.run_button = QPushButton("更新")
        self.run_button.clicked.connect(self.choose_update)
        bar.addWidget(self.run_button)
        self.preview_button = QPushButton("预览")
        self.preview_button.clicked.connect(lambda: self.run_update(preview=True))
        bar.addWidget(self.preview_button)
        self.images_button = QPushButton("下载 terra 图片")
        self.images_button.clicked.connect(lambda: self.run_update(images=True))
        bar.addWidget(self.images_button)
        bar.addAction("导入本地资料", self.import_file)
        bar.addAction("替换当前本地资料", self.replace_file)
        bar.addAction("更新意见", lambda: (self.notes_dock.show(), self.opinions_edit.setFocus()))
        wrap = QAction("自动换行", self)
        wrap.setCheckable(True)
        wrap.setChecked(True)
        wrap.triggered.connect(self.set_wrap)
        bar.addAction(wrap)
        action = QAction("文件查找", self)
        action.setShortcut("Ctrl+F")
        action.triggered.connect(self.find_input.setFocus)
        self.addAction(action)
        action = QAction("全局搜索", self)
        action.setShortcut("Ctrl+Shift+F")
        action.triggered.connect(self.global_input.setFocus)
        self.addAction(action)
        action = QAction("查找下一个", self)
        action.setShortcut("F3")
        action.triggered.connect(self.find_next)
        self.addAction(action)

    def _dock(self, title, widget, where):
        dock = QDockWidget(title, self)
        dock.setWidget(widget)
        self.addDockWidget(where, dock)
        return dock

    def make_search_dock(self):
        self.search_results = QListWidget()
        self.search_results.itemDoubleClicked.connect(self.open_search_hit)
        self.search_dock = self._dock("搜索结果 · 双击跳转", self.search_results, Qt.DockWidgetArea.BottomDockWidgetArea)
        self.search_dock.hide()

    def make_history_dock(self):
        self.history_tree = QTreeWidget()
        self.history_tree.setHeaderLabels(["最近更新 · 双击差异", "变化"])
        self.history_tree.itemDoubleClicked.connect(self.open_history_item)
        self._dock("逐行更新历史", self.history_tree, Qt.DockWidgetArea.RightDockWidgetArea)

    def make_notes_dock(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.addWidget(QLabel(f"本地文件：{OPINIONS_FILE}"))
        self.opinions_edit = QPlainTextEdit()
        self.opinions_edit.setPlaceholderText("在这里直接填写更新意见，无需打开资源文件")
        self.opinions_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        layout.addWidget(self.opinions_edit)
        row = QHBoxLayout()
        for title, action in [("保存 Ctrl+S", self.save_opinions), ("从文件重载", self.reload_opinions)]:
            button = QPushButton(title)
            button.clicked.connect(action)
            row.addWidget(button)
        layout.addLayout(row)
        self.notes_dock = self._dock("本地更新意见", panel, Qt.DockWidgetArea.RightDockWidgetArea)
        save = QAction("保存更新意见", self)
        save.setShortcut("Ctrl+S")
        save.triggered.connect(self.save_opinions)
        self.addAction(save)

    def set_wrap(self, enabled):
        self.wrap_enabled = enabled
        for reader in self.readers.values():
            if isinstance(reader, TextReader):
                reader.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth if enabled else QPlainTextEdit.LineWrapMode.NoWrap)

    def make_jobs_dock(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        self.job_log = QPlainTextEdit()
        self.job_log.setReadOnly(True)
        layout.addWidget(self.job_log)
        stop = QPushButton("停止任务")
        stop.clicked.connect(self.stop_update)
        layout.addWidget(stop)
        self.jobs_dock = self._dock("任务进度", panel, Qt.DockWidgetArea.BottomDockWidgetArea)
        self.jobs_dock.hide()

    def reload_tree(self):
        self.tree.clear()
        entries: dict[str, QTreeWidgetItem] = {}
        for path in sorted(resource_files(), key=lambda p: p.relative_to(RESOURCES_DIR).as_posix().casefold()):
            parts = path.relative_to(RESOURCES_DIR).parts
            parent = None
            for index, part in enumerate(parts):
                key = "/".join(parts[:index + 1])
                if key not in entries:
                    item = QTreeWidgetItem([part])
                    if parent is None:
                        self.tree.addTopLevelItem(item)
                    else:
                        parent.addChild(item)
                    entries[key] = item
                parent = entries[key]
            parent.setData(0, Qt.ItemDataRole.UserRole, str(path))
        self.tree.sortItems(0, Qt.SortOrder.AscendingOrder)

    def open_tree_item(self, item, _column):
        value = item.data(0, Qt.ItemDataRole.UserRole)
        if value:
            self.open_resource(Path(value))
        else:
            item.setExpanded(not item.isExpanded())

    def click_tree_item(self, item, _column):
        value = item.data(0, Qt.ItemDataRole.UserRole)
        if value:
            self.open_resource(Path(value))

    def open_resource(self, path: Path, line: int = 0, page: int | None = None):
        if not path.is_file():
            QMessageBox.warning(self, "找不到资料", str(path))
            return
        key = str(path.resolve())
        if key in self.readers:
            reader = self.readers[key]
            self.tabs.setCurrentWidget(reader)
        else:
            suffix = path.suffix.lower()
            if suffix in TEXT_SUFFIXES:
                reader = TextReader(path)
                reader.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth if self.wrap_enabled else QPlainTextEdit.LineWrapMode.NoWrap)
            elif suffix in IMAGE_SUFFIXES:
                reader = ImageReader(path)
            elif suffix in PDF_SUFFIXES:
                reader = PdfReader(path)
            else:
                return
            self.readers[key] = reader
            self.tabs.addTab(reader, path.name)
            self.tabs.setTabToolTip(self.tabs.indexOf(reader), relative_id(path))
            self.tabs.setCurrentWidget(reader)
        self.current_path = path
        if isinstance(reader, TextReader) and line:
            reader.jump(line)
        if isinstance(reader, PdfReader) and page:
            reader.jump(page)
        self.statusBar().showMessage(f"{source_kind(path)} · {relative_id(path)}")

    def close_tab(self, index):
        reader = self.tabs.widget(index)
        if reader:
            if hasattr(reader, "path"):
                self.readers.pop(str(reader.path.resolve()), None)
            self.tabs.removeTab(index)
            reader.deleteLater()

    def _tab_changed(self, index):
        reader = self.tabs.widget(index)
        self.current_path = reader.path if hasattr(reader, "path") else None

    def find_next(self):
        reader = self.tabs.currentWidget()
        term = self.find_input.text()
        if isinstance(reader, TextReader) and term:
            if not reader.find(term):
                reader.moveCursor(QTextCursor.MoveOperation.Start)
                reader.find(term)

    def global_search(self):
        term = self.global_input.text().strip()
        if not term or (self.search_worker and self.search_worker.isRunning()):
            return
        self.search_results.clear()
        self.search_results.addItem("正在搜索…")
        self.search_dock.show()
        self.search_worker = SearchThread(term)
        self.search_worker.ready.connect(self.show_hits)
        self.search_worker.start()

    def show_hits(self, hits):
        self.search_results.clear()
        for hit in hits:
            label = f"{hit.resource_id}:{hit.line}" + (f" · PDF 第 {hit.page} 页" if hit.page else "")
            item = QListWidgetItem(f"{label}\n    {hit.excerpt}")
            item.setData(Qt.ItemDataRole.UserRole, hit)
            self.search_results.addItem(item)
        self.statusBar().showMessage(f"搜索完成：{len(hits)} 条结果" + ("（达到显示上限，可缩小关键词范围）" if len(hits) >= 10000 else ""))

    def open_search_hit(self, item):
        hit = item.data(Qt.ItemDataRole.UserRole)
        if not hit:
            return
        self.open_resource(resource_path(hit.resource_id), line=hit.line)
        if hit.page and hit.resource_id.endswith("大地巡旅_OCR.txt"):
            self.open_resource(next(BOOK_DIR.glob("*.pdf")), page=hit.page)

    def reload_history(self):
        self.history_tree.clear()
        for run in list_runs():
            root = QTreeWidgetItem([f"{run['started_at']}  {run['command']}  [{run['status']}]", str(run["changed"])])
            root.setData(0, Qt.ItemDataRole.UserRole, (run["id"], None))
            self.history_tree.addTopLevelItem(root)

    def open_history_item(self, item, _column):
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if not payload:
            return
        run_id, index = payload
        run = load_run(run_id)
        if index is None:
            if item.childCount() == 0:
                for i, change in enumerate(run["changes"]):
                    child = QTreeWidgetItem([f"{change['action']} · {change['resource_id']}", change["kind"]])
                    child.setToolTip(0, change["resource_id"])
                    child.setData(0, Qt.ItemDataRole.UserRole, (run_id, i))
                    item.addChild(child)
            item.setExpanded(True)
            return
        self.show_diff(run["changes"][index], run_id)

    def show_diff(self, change, run_id):
        listing = QTreeWidget()
        listing.setHeaderLabels(["旧行", "新行", "", "内容"])
        listing.setColumnWidth(0, 56)
        listing.setColumnWidth(1, 56)
        listing.setColumnWidth(2, 30)
        listing.setColumnWidth(3, 950)
        listing.setUniformRowHeights(True)
        rows = diff_rows(change)
        additions = sum(kind == "add" for kind, *_ in rows)
        removals = sum(kind == "remove" for kind, *_ in rows)
        summary = QTreeWidgetItem(["", "", "", f"{change['resource_id']}    +{additions}  -{removals}"])
        summary.setBackground(3, QColor("#29383a"))
        listing.addTopLevelItem(summary)
        for kind, old_line, new_line, content in rows:
            marker = "+" if kind == "add" else "-" if kind == "remove" else " "
            entry = QTreeWidgetItem([str(old_line or ""), str(new_line or ""), marker, content])
            entry.setData(0, Qt.ItemDataRole.UserRole, (change["resource_id"], new_line))
            color = {"add": "#254d37", "remove": "#58333a", "hunk": "#344d5c", "meta": "#29383a"}.get(kind)
            if color:
                for column in range(4):
                    entry.setBackground(column, QColor(color))
            listing.addTopLevelItem(entry)
        listing.itemDoubleClicked.connect(self.open_diff_line)
        title = f"差异 · {Path(change['resource_id']).name} · {run_id}"
        self.tabs.addTab(listing, title)
        self.tabs.setCurrentWidget(listing)

    def open_diff_line(self, item, _column):
        target = item.data(0, Qt.ItemDataRole.UserRole)
        if not target:
            return
        resource_id, line = target
        if line:
            path = resource_path(resource_id)
            if path.is_file():
                self.open_resource(path, line=line)

    def reload_opinions(self):
        if self.opinions_edit.document().isModified():
            answer = QMessageBox.question(self, "重载更新意见", "当前编辑尚未保存，确定从文件重载？")
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.opinions_edit.setPlainText(read_opinions())
        self.opinions_edit.document().setModified(False)

    def save_opinions(self):
        try:
            write_opinions(self.opinions_edit.toPlainText())
            self.opinions_edit.document().setModified(False)
            self.statusBar().showMessage(f"更新意见已保存：{OPINIONS_FILE}")
        except OSError as exc:
            QMessageBox.warning(self, "保存失败", str(exc))

    def closeEvent(self, event):
        if self.opinions_edit.document().isModified():
            answer = QMessageBox.question(self, "保存更新意见", "更新意见有未保存的更改，退出前保存？",
                                          QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
                                          QMessageBox.StandardButton.Cancel)
            if answer == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            if answer == QMessageBox.StandardButton.Save:
                self.save_opinions()
                if self.opinions_edit.document().isModified():
                    event.ignore()
                    return
        super().closeEvent(event)

    def import_file(self):
        name, _ = QFileDialog.getOpenFileName(self, "导入本地资料", "", "资料 (*.txt *.md *.pdf *.jpg *.jpeg *.png *.webp *.gif *.bmp)")
        if not name:
            return
        try:
            run = import_local(Path(name))
            self.reload_tree()
            self.reload_history()
            self.open_resource(resource_path(run["changes"][0]["resource_id"]))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "导入失败", str(exc))

    def replace_file(self):
        if not self.current_path:
            QMessageBox.information(self, "替换资料", "请先打开一份本地资料")
            return
        target = relative_id(self.current_path)
        if target.split("/", 1)[0] != "local":
            QMessageBox.information(self, "替换资料", "当前文件由采集或 OCR 维护，请使用相应更新操作")
            return
        name, _ = QFileDialog.getOpenFileName(self, "选择替换文件", "", "资料 (*.txt *.md *.pdf *.jpg *.jpeg *.png *.webp *.gif *.bmp)")
        if not name:
            return
        try:
            import_local(Path(name), target)
            key = str(self.current_path.resolve())
            reader = self.readers.pop(key, None)
            if reader:
                index = self.tabs.indexOf(reader)
                self.tabs.removeTab(index)
                reader.deleteLater()
            self.reload_history()
            self.open_resource(resource_path(target))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "替换失败", str(exc))

    def choose_update(self):
        dialog = QMessageBox(self)
        dialog.setWindowTitle("选择更新内容")
        dialog.setText("请选择本次更新范围")
        dialog.setInformativeText("纯文本按当前模块更新；完整资料更新所有可采集文本，再下载 terra 图片。本地 PDF 与 OCR 由本地维护。")
        text_button = dialog.addButton("纯文本", QMessageBox.ButtonRole.AcceptRole)
        full_button = dialog.addButton("完整资料（含图片）", QMessageBox.ButtonRole.AcceptRole)
        dialog.addButton(QMessageBox.StandardButton.Cancel)
        dialog.exec()
        if dialog.clickedButton() is text_button:
            self.run_update()
        elif dialog.clickedButton() is full_button:
            self.run_update(full=True)

    def run_update(self, *, preview=False, images=False, full=False):
        if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            return
        self.update_queue = ([update_arguments(self.module.currentText(), self.mode.currentText(), images=True, preview=preview)]
                             if images else update_command_sequence(self.module.currentText(), self.mode.currentText(), full=full, preview=preview))
        self.jobs_dock.show()
        self.job_log.clear()
        for widget in (self.run_button, self.preview_button, self.images_button):
            widget.setEnabled(False)
        self._start_next_update()

    def _start_next_update(self):
        args = self.update_queue.pop(0)
        self.job_log.appendPlainText("运行：" + " ".join(args))
        try:
            command = crawler_command(args)
        except OSError as exc:
            self.job_log.appendPlainText(f"启动失败：{exc}")
            self.update_queue.clear()
            for widget in (self.run_button, self.preview_button, self.images_button):
                widget.setEnabled(True)
            return
        self.process = QProcess(self)
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.process.setWorkingDirectory(str(PROJECT_DIR))
        self.process.setProgram(command[0])
        self.process.setArguments(command[1:])
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.read_process)
        self.process.finished.connect(self.update_finished)
        self.process.errorOccurred.connect(self.update_process_error)
        self.process.start()

    def update_process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.job_log.appendPlainText(f"无法启动程序：{self.process.errorString()}")
            self.update_queue.clear()
            for widget in (self.run_button, self.preview_button, self.images_button):
                widget.setEnabled(True)

    def read_process(self):
        data = self.decoder.decode(bytes(self.process.readAllStandardOutput()))
        self.job_log.moveCursor(QTextCursor.MoveOperation.End)
        self.job_log.insertPlainText(data)

    def stop_update(self):
        self.update_queue.clear()
        if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.terminate()

    def update_finished(self, code, _status):
        self.read_process()
        self.job_log.insertPlainText(self.decoder.decode(b"", final=True))
        self.job_log.appendPlainText(f"\n本阶段结束，退出码 {code}")
        if code == 0 and self.update_queue:
            self._start_next_update()
            return
        self.update_queue.clear()
        for widget in (self.run_button, self.preview_button, self.images_button):
            widget.setEnabled(True)
        self.reload_tree()
        self.reload_history()


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    app.setFont(QFont("Maple Mono NF CN", 11))
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
