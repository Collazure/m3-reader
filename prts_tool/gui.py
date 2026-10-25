"""Qt desktop reader for the PRTS resource library."""

from __future__ import annotations

import re
import sys
import codecs
from pathlib import Path

from . import __version__
from .history import diff_rows, import_local, list_runs, load_run
from .jobs import update_arguments, update_command_sequence
from .library import (IMAGE_SUFFIXES, PDF_SUFFIXES, TEXT_SUFFIXES, directory_index, read_opinions,
                      relative_id, resource_files, resource_path, search_text,
                      source_kind, write_opinions)
from .paths import APP_ICON_FILE, BOOK_DIR, OPINIONS_FILE, PROJECT_DIR, RESOURCES_DIR, crawler_command
from .reading import last_position, position_for, save_position

try:
    from PySide6.QtCore import QEvent, QPointF, QProcess, Qt, QThread, QTimer, QUrl, Signal
    from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QIcon, QPainter, QPixmap, QSyntaxHighlighter, QTextCharFormat, QTextCursor, QTextDocument, QTextFormat
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtPdfWidgets import QPdfView
    from PySide6.QtWidgets import (QApplication, QComboBox, QDockWidget, QHBoxLayout,
                                   QFileDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
                                   QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSplitter,
                                   QTabWidget, QTextEdit, QToolBar, QTreeWidget, QTreeWidgetItem, QWidgetAction,
                                   QVBoxLayout, QWidget)
except ImportError as exc:  # pragma: no cover - tested with the optional Qt runtime
    raise SystemExit("GUI 需要 PySide6。请运行 python -m pip install PySide6 PySide6-Addons") from exc


STYLE = """
QWidget { background: #1f2329; color: #a8cfa7; font-family: 'Maple Mono NF CN','Noto Sans Mono CJK SC',monospace; font-size: 13px; }
QMainWindow, QDockWidget { background: #191f24; }
QToolBar, QMenuBar, QStatusBar { background: #202a30; border-bottom: 1px solid #4f5f5f; spacing: 7px; padding: 5px; }
QMenu { background: #202a30; border: 1px solid #688a71; padding: 5px; }
QMenu::item { padding: 5px 22px; }
QMenu::item:selected { background: #385246; color: #f0f9f9; }
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


class CommandLine(QLineEdit):
    """Optional GUI command input with terminal-like history and Tab completion."""

    COMMANDS = ("find", "search", "jump", "update", "preview", "images", "history",
                "diff", "notes", "note", "save", "page", "open", "import", "replace",
                "resume", "next", "prev", "back", "help", "quit")

    def __init__(self):
        super().__init__()
        self.history: list[str] = []
        self.history_index = 0

    def remember(self, command: str):
        if command and (not self.history or self.history[-1] != command):
            self.history.append(command)
            self.history = self.history[-100:]
        self.history_index = len(self.history)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down) and self.history:
            offset = -1 if event.key() == Qt.Key.Key_Up else 1
            self.history_index = max(0, min(len(self.history), self.history_index + offset))
            self.setText(self.history[self.history_index] if self.history_index < len(self.history) else "")
            return
        if event.key() == Qt.Key.Key_Tab and self.text().strip() and " " not in self.text().strip():
            matches = [command for command in self.COMMANDS if command.startswith(self.text().strip().casefold())]
            if len(matches) == 1:
                self.setText(matches[0] + " ")
            return
        super().keyPressEvent(event)


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
    vim_prompt = Signal(str)
    vim_find = Signal(bool)

    def __init__(self, path: Path):
        super().__init__()
        self.path = path
        self.vim_enabled = True
        self._vim_count = ""
        self._vim_g = False
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
        self.line_area.setGeometry(0, self.contentsRect().top(),
                                   self.line_width(), self.contentsRect().height())
        self.line_area.show()

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

    def keyPressEvent(self, event):
        if not self.vim_enabled:
            super().keyPressEvent(event)
            return
        key = event.key()
        modifiers = event.modifiers()
        if modifiers == Qt.KeyboardModifier.ControlModifier and key in (Qt.Key.Key_D, Qt.Key.Key_U, Qt.Key.Key_B):
            cursor = self.textCursor()
            step = 40 if key == Qt.Key.Key_B else 20
            operation = (QTextCursor.MoveOperation.Down if key == Qt.Key.Key_D
                         else QTextCursor.MoveOperation.Up)
            cursor.movePosition(operation, QTextCursor.MoveMode.MoveAnchor, step)
            self.setTextCursor(cursor)
            self.centerCursor()
            event.accept()
            return
        if key == Qt.Key.Key_Escape:
            self._vim_count = ""
            self._vim_g = False
            event.accept()
            return
        if modifiers not in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ShiftModifier):
            super().keyPressEvent(event)
            return
        char = event.text()
        if not char:
            super().keyPressEvent(event)
            return
        if char.isdigit():
            if char == "0" and not self._vim_count:
                self._vim_move(QTextCursor.MoveOperation.StartOfLine, 1)
            else:
                self._vim_count = (self._vim_count + char)[-5:]
            event.accept()
            return
        count = min(int(self._vim_count or "1"), 100000)
        if self._vim_g:
            self._vim_g = False
            if char == "g":
                self.jump(int(self._vim_count or "1"))
                self._vim_count = ""
                event.accept()
                return
        movement = {
            "h": QTextCursor.MoveOperation.Left, "j": QTextCursor.MoveOperation.Down,
            "k": QTextCursor.MoveOperation.Up, "l": QTextCursor.MoveOperation.Right,
            "w": QTextCursor.MoveOperation.NextWord, "b": QTextCursor.MoveOperation.PreviousWord,
            "$": QTextCursor.MoveOperation.EndOfLine,
        }.get(char)
        if movement is not None:
            self._vim_move(movement, 1 if char == "$" else count)
        elif char == "g":
            self._vim_g = True
            event.accept()
            return
        elif char == "G":
            self.jump(int(self._vim_count) if self._vim_count else self.blockCount())
        elif char in {"/", ":"}:
            self.vim_prompt.emit(char)
        elif char in {"n", "N"}:
            self.vim_find.emit(char == "N")
        self._vim_count = ""
        event.accept()

    def _vim_move(self, operation, count):
        cursor = self.textCursor()
        cursor.movePosition(operation, QTextCursor.MoveMode.MoveAnchor, count)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()


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
        self.setWindowIcon(QIcon(str(APP_ICON_FILE)))
        self.resize(1500, 920)
        self.current_path: Path | None = None
        self.search_worker: SearchThread | None = None
        self.process: QProcess | None = None
        self.update_queue: list[list[str]] = []
        self.readers: dict[str, QWidget] = {}
        self._active_reader: QWidget | None = None
        self._navigation_history: list[tuple[Path, int, int | None]] = []
        self._going_back = False
        self._position_timer = QTimer(self)
        self._position_timer.setSingleShot(True)
        self._position_timer.setInterval(750)
        self._position_timer.timeout.connect(self._save_current_position)
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
        self.make_command_dock()
        self.reload_tree()
        self.reload_history()
        self.reload_opinions()
        self.statusBar().showMessage("资料就绪 · 双击左侧文件打开 · Ctrl+F 文件搜索 · Ctrl+Shift+F 全局搜索")

    def make_toolbar(self):
        self.import_menu = self.menuBar().addMenu("导入")
        self.reading_menu = self.menuBar().addMenu("阅读")
        self.tools_menu = self.menuBar().addMenu("工具")
        self.view_menu = self.menuBar().addMenu("视图")
        self.reading_menu.addAction("继续阅读", self.resume_reading)
        self.reading_menu.addAction("返回上一个文件", self.go_back)
        self.reading_menu.addAction("上一文件", lambda: self.adjacent_file(-1))
        self.reading_menu.addAction("下一文件", lambda: self.adjacent_file(1))
        controls = QWidget()
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(8, 4, 8, 4)
        controls_layout.addWidget(QLabel("模块"))
        self.module = QComboBox()
        self.module.addItems(["all", "avg", "stage", "activity", "operator", "furniture", "enemies", "reclamation", "roguelike", "terra"])
        controls_layout.addWidget(self.module)
        controls_layout.addWidget(QLabel("模式"))
        self.mode = QComboBox()
        self.mode.addItems(["changed", "missing", "force"])
        controls_layout.addWidget(self.mode)
        controls_action = QWidgetAction(self.import_menu)
        controls_action.setDefaultWidget(controls)
        self.import_menu.addAction(controls_action)
        self.import_menu.addSeparator()
        self.run_button = self.import_menu.addAction("更新…", self.choose_update)
        self.preview_button = self.import_menu.addAction("预览文本更新", lambda: self.run_update(preview=True))
        self.images_button = self.import_menu.addAction("下载 terra 图片", lambda: self.run_update(images=True))
        self.import_menu.addSeparator()
        self.import_menu.addAction("导入本地资料…", self.import_file)
        self.import_menu.addAction("替换当前本地资料…", self.replace_file)
        self.notes_toolbar_action = self.tools_menu.addAction(
            "更新意见", lambda: (self.notes_dock.show(), self.opinions_edit.setFocus()))
        wrap = QAction("自动换行", self)
        wrap.setCheckable(True)
        wrap.setChecked(True)
        wrap.triggered.connect(self.set_wrap)
        self.view_menu.addAction(wrap)
        self.vim_action = QAction("只读 Vim 操作", self)
        self.vim_action.setCheckable(True)
        self.vim_action.setChecked(True)
        self.vim_action.toggled.connect(self.set_vim)
        self.view_menu.addAction(self.vim_action)
        self.command_action = QAction("命令栏", self)
        self.command_action.setCheckable(True)
        self.command_action.setShortcut("Ctrl+L")
        self.command_action.toggled.connect(self.set_command_visible)
        self.view_menu.addAction(self.command_action)
        self.help_menu = self.menuBar().addMenu("帮助")
        self.help_menu.addAction("快捷键与命令", self.show_command_help)
        self.help_menu.addAction("关于 M3 Reader", lambda: QMessageBox.information(
            self, "关于 M3 Reader", f"M3 Reader {__version__}\nPRTS 资料阅读与采集工具"))
        right = QWidget(self)
        right_layout = QHBoxLayout(right)
        right_layout.setContentsMargins(4, 0, 4, 0)
        right_layout.setSpacing(5)
        self.find_input = QLineEdit()
        self.find_input.setPlaceholderText("文件内搜索 Ctrl+F")
        self.find_input.setFixedWidth(190)
        self.find_input.returnPressed.connect(self.find_next)
        right_layout.addWidget(self.find_input)
        next_button = QPushButton("下一个")
        next_button.clicked.connect(self.find_next)
        right_layout.addWidget(next_button)
        self.global_input = QLineEdit()
        self.global_input.setPlaceholderText("全局搜索 Ctrl+Shift+F")
        self.global_input.setFixedWidth(200)
        self.global_input.returnPressed.connect(self.global_search)
        right_layout.addWidget(self.global_input)
        global_button = QPushButton("搜索")
        global_button.clicked.connect(self.global_search)
        right_layout.addWidget(global_button)
        right_layout.addWidget(QLabel(f"M3 Reader · v{__version__}"))
        self.menuBar().setCornerWidget(right, Qt.Corner.TopRightCorner)
        self.vim_input = QLineEdit(self)
        self.vim_input.setMaximumWidth(350)
        self.vim_input.returnPressed.connect(self.run_vim_input)
        self.vim_input.installEventFilter(self)
        self.statusBar().addPermanentWidget(self.vim_input)
        self.vim_input.hide()
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
        self.history_dock = self._dock("变动栏 · 逐行更新历史", self.history_tree,
                                       Qt.DockWidgetArea.RightDockWidgetArea)
        self.history_dock.hide()
        self.history_action = QAction("变动栏", self)
        self.history_action.setCheckable(True)
        self.history_action.setChecked(False)
        self.history_action.setToolTip("打开或关闭逐行更新历史")
        self.history_action.triggered.connect(self.set_history_visible)
        self.tools_menu.addAction(self.history_action)
        self.history_dock.visibilityChanged.connect(self.history_action.setChecked)

    def set_history_visible(self, visible: bool):
        self.history_dock.setVisible(visible)
        if visible:
            self.history_dock.raise_()
            self.history_tree.setFocus()

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
        self.notes_dock.hide()
        save = QAction("保存更新意见", self)
        save.setShortcut("Ctrl+S")
        save.triggered.connect(self.save_opinions)
        self.addAction(save)

    def set_wrap(self, enabled):
        self.wrap_enabled = enabled
        for reader in self.readers.values():
            if isinstance(reader, TextReader):
                reader.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth if enabled else QPlainTextEdit.LineWrapMode.NoWrap)

    def set_vim(self, enabled):
        for reader in self.readers.values():
            if isinstance(reader, TextReader):
                reader.vim_enabled = enabled

    def show_vim_prompt(self, prefix: str):
        self.vim_input.setText(prefix)
        self.vim_input.show()
        self.vim_input.setFocus()

    def run_vim_input(self):
        command = self.vim_input.text().strip()
        self.vim_input.hide()
        reader = self.tabs.currentWidget()
        if not isinstance(reader, TextReader):
            return
        if command.startswith("/"):
            term = command[1:]
            if term:
                self.find_input.setText(term)
                self.find_next()
        elif command.startswith(":"):
            value = command[1:].strip()
            if value.isdecimal() and int(value) > 0:
                reader.jump(int(value))
            else:
                self.statusBar().showMessage("Vim 命令支持 :行号 与 /关键词")
        reader.setFocus()

    def eventFilter(self, obj, event):
        if obj is getattr(self, "vim_input", None) and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self.vim_input.hide()
                reader = self.tabs.currentWidget()
                if isinstance(reader, TextReader):
                    reader.setFocus()
                return True
        return super().eventFilter(obj, event)

    def vim_find(self, backwards: bool):
        reader = self.tabs.currentWidget()
        term = self.find_input.text()
        if not isinstance(reader, TextReader) or not term:
            self.show_vim_prompt("/")
            return
        flags = QTextDocument.FindFlag.FindBackward if backwards else QTextDocument.FindFlag(0)
        if not reader.find(term, flags):
            reader.moveCursor(QTextCursor.MoveOperation.End if backwards else QTextCursor.MoveOperation.Start)
            reader.find(term, flags)

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

    def make_command_dock(self):
        panel = QWidget()
        row = QHBoxLayout(panel)
        row.setContentsMargins(8, 4, 8, 4)
        row.addWidget(QLabel("命令 ›"))
        self.command_input = CommandLine()
        self.command_input.setPlaceholderText("find / search / jump / update / history / diff / notes / resume / next / back …  (Tab 补全，↑↓ 历史)")
        self.command_input.returnPressed.connect(self.execute_gui_command)
        row.addWidget(self.command_input)
        self.command_dock = self._dock("命令 · Ctrl+L 隐藏", panel, Qt.DockWidgetArea.BottomDockWidgetArea)
        self.command_dock.hide()
        self.command_dock.visibilityChanged.connect(self.command_action.setChecked)

    def set_command_visible(self, visible: bool):
        self.command_dock.setVisible(visible)
        if visible:
            self.command_dock.raise_()
            self.command_input.setFocus()

    def show_command_help(self):
        QMessageBox.information(self, "阅读快捷键与命令",
            "只读 Vim：h/j/k/l、0/$、w/b、gg/G、数字前缀、Ctrl+D/U/B、/搜索、n/N、:行号。\n\n"
            "可选命令栏（Ctrl+L）：find、search、jump、update、preview、images、history、"
            "diff 运行序号 变化序号、notes、note、save、page、open、import、replace、"
            "resume、next、prev、back、help、quit。")

    def reload_tree(self):
        self.tree.clear()
        entries: dict[str, QTreeWidgetItem] = {}
        self.catalog_files = sorted(resource_files(), key=lambda p: p.relative_to(RESOURCES_DIR).as_posix().casefold())
        for path in self.catalog_files:
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
            self.open_directory_index(item)

    def click_tree_item(self, item, _column):
        value = item.data(0, Qt.ItemDataRole.UserRole)
        if value:
            self.open_resource(Path(value))
        else:
            self.open_directory_index(item)

    def open_directory_index(self, item):
        parts = []
        current = item
        while current is not None:
            parts.append(current.text(0))
            current = current.parent()
        folder = RESOURCES_DIR.joinpath(*reversed(parts))
        if index := directory_index(folder):
            self.open_resource(index)

    def resume_reading(self):
        target = last_position()
        if not target:
            self.statusBar().showMessage("暂无续读记录；打开一份资料后即可保存阅读位置")
            return
        path, line, page = target
        self.open_resource(path, line=line, page=page)

    def adjacent_file(self, direction: int):
        path = self.current_path
        if not path:
            self.statusBar().showMessage("请先打开一份资料")
            return
        siblings = sorted((item for item in self.catalog_files if item.parent == path.parent and item.is_file()),
                          key=lambda item: item.name.casefold())
        try:
            index = siblings.index(path)
        except ValueError:
            self.statusBar().showMessage("当前文件已不在目录中")
            return
        next_index = index + direction
        if 0 <= next_index < len(siblings):
            self.open_resource(siblings[next_index])
        else:
            self.statusBar().showMessage("已到达当前目录的开头或末尾")

    def go_back(self):
        while self._navigation_history:
            path, line, page = self._navigation_history.pop()
            if path.is_file():
                self._going_back = True
                try:
                    self.open_resource(path, line=line, page=page)
                finally:
                    self._going_back = False
                return
        self.statusBar().showMessage("没有可返回的文件")

    @staticmethod
    def _reader_location(reader):
        if isinstance(reader, TextReader):
            return reader.textCursor().blockNumber() + 1, None
        if isinstance(reader, PdfReader):
            return 1, reader.view.pageNavigator().currentPage() + 1
        return 1, None

    def execute_gui_command(self):
        raw = self.command_input.text().strip()
        self.command_input.clear()
        if not raw:
            return
        self.command_input.remember(raw)
        if raw.startswith("/"):
            raw = "find " + raw[1:]
        elif raw.startswith(":") and raw[1:].isdecimal():
            raw = "jump " + raw[1:]
        elif raw.startswith(":"):
            raw = raw[1:]
        command, _, rest = raw.partition(" ")
        command, rest = command.casefold(), rest.strip()
        try:
            if command == "find":
                if rest:
                    self.find_input.setText(rest)
                    self.find_next()
                else:
                    self.find_input.setFocus()
            elif command == "search":
                if rest:
                    self.global_input.setText(rest)
                    self.global_search()
                else:
                    self.global_input.setFocus()
            elif command == "jump":
                reader = self.tabs.currentWidget()
                if not isinstance(reader, TextReader) or not rest.isdecimal() or int(rest) < 1:
                    raise ValueError("先打开文本，再输入 jump 行号")
                reader.jump(int(rest))
            elif command in {"update", "preview", "images"}:
                self._command_update(command, rest)
            elif command == "history":
                self.set_history_visible(True)
            elif command == "diff":
                parts = rest.split()
                if len(parts) != 2 or not all(part.isdecimal() and int(part) > 0 for part in parts):
                    raise ValueError("用法：diff 运行序号 变化序号")
                runs = list_runs()
                run = load_run(runs[int(parts[0]) - 1]["id"])
                self.show_diff(run["changes"][int(parts[1]) - 1], run["id"])
            elif command == "notes":
                self.notes_dock.show()
                self.opinions_edit.setFocus()
            elif command == "note":
                if not rest:
                    raise ValueError("请输入意见内容")
                self.opinions_edit.appendPlainText("\n" + rest)
                self.save_opinions()
                self.notes_dock.show()
            elif command == "save":
                self.save_opinions()
            elif command == "page":
                reader = self.tabs.currentWidget()
                if not isinstance(reader, PdfReader) or not rest.isdecimal() or int(rest) < 1:
                    raise ValueError("先打开 PDF，再输入 page 页号")
                reader.jump(int(rest))
            elif command == "open":
                if rest:
                    self.open_resource(resource_path(rest.strip('"')))
                elif self.current_path:
                    QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.current_path)))
                else:
                    raise ValueError("先打开一份资料，或输入 open 资源相对路径")
            elif command in {"import", "replace"}:
                if not rest:
                    self.replace_file() if command == "replace" else self.import_file()
                else:
                    target = relative_id(self.current_path) if command == "replace" and self.current_path else None
                    if command == "replace" and not target:
                        raise ValueError("请先打开要替换的本地资料")
                    run = import_local(Path(rest.strip('"')), target)
                    self.reload_tree()
                    self.reload_history()
                    self.open_resource(resource_path(run["changes"][0]["resource_id"]))
            elif command == "resume":
                self.resume_reading()
            elif command == "next":
                self.adjacent_file(1)
            elif command == "prev":
                self.adjacent_file(-1)
            elif command == "back":
                self.go_back()
            elif command in {"help", "?"}:
                self.show_command_help()
            elif command in {"quit", "q"}:
                self.close()
            else:
                raise ValueError(f"未知命令：{command}；输入 help 查看可用命令")
        except (ValueError, IndexError, KeyError, OSError) as exc:
            self.statusBar().showMessage(f"命令失败：{exc}", 8000)

    def _command_update(self, command: str, rest: str):
        module, mode = self.module.currentText(), self.mode.currentText()
        full = False
        preview = command == "preview"
        words = rest.split()
        index = 0
        while index < len(words):
            word = words[index].casefold()
            if word in {"-m", "--mode"}:
                index += 1
                if index >= len(words):
                    raise ValueError("--mode 后面需要 changed、missing 或 force")
                mode = words[index].casefold()
            elif word in {"--images", "full"}:
                full = True
            elif word in {"--dry-run", "dry", "preview"}:
                preview = True
            elif word in {"--force", "--missing"}:
                mode = "force" if word == "--force" else "missing"
            elif word in {"all", "avg", "stage", "activity", "operator", "furniture", "enemies", "reclamation", "roguelike", "terra"}:
                module = word
            elif word in {"changed", "missing", "force"}:
                mode = word
            else:
                raise ValueError(f"未知更新参数：{words[index]}")
            index += 1
        if mode not in {"changed", "missing", "force"}:
            raise ValueError(f"未知更新模式：{mode}")
        self.module.setCurrentText(module)
        self.mode.setCurrentText(mode)
        self.run_update(preview=preview, images=command == "images", full=full and command != "images")

    def open_resource(self, path: Path, line: int = 0, page: int | None = None):
        if not path.is_file():
            QMessageBox.warning(self, "找不到资料", str(path))
            return
        previous = self.tabs.currentWidget()
        if (not self._going_back and hasattr(previous, "path") and
                previous.path.resolve() != path.resolve()):
            previous_line, previous_page = self._reader_location(previous)
            self._navigation_history.append((previous.path, previous_line, previous_page))
            self._navigation_history = self._navigation_history[-50:]
        key = str(path.resolve())
        existing = key in self.readers
        if existing:
            reader = self.readers[key]
            self.tabs.setCurrentWidget(reader)
        else:
            suffix = path.suffix.lower()
            if suffix in TEXT_SUFFIXES:
                reader = TextReader(path)
                reader.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth if self.wrap_enabled else QPlainTextEdit.LineWrapMode.NoWrap)
                reader.vim_enabled = self.vim_action.isChecked()
                reader.vim_prompt.connect(self.show_vim_prompt)
                reader.vim_find.connect(self.vim_find)
                reader.cursorPositionChanged.connect(self._queue_position_save)
            elif suffix in IMAGE_SUFFIXES:
                reader = ImageReader(path)
            elif suffix in PDF_SUFFIXES:
                reader = PdfReader(path)
                reader.view.pageNavigator().currentPageChanged.connect(self._queue_position_save)
            else:
                return
            self.readers[key] = reader
            self.tabs.addTab(reader, path.name)
            self.tabs.setTabToolTip(self.tabs.indexOf(reader), relative_id(path))
            self.tabs.setCurrentWidget(reader)
        self.current_path = path
        saved_line, saved_page = position_for(path) if not existing and not line and page is None else (1, None)
        if isinstance(reader, TextReader) and (line or not existing):
            reader.jump(min(line or saved_line, reader.blockCount()))
        if isinstance(reader, PdfReader) and (page or (not existing and saved_page)):
            reader.jump(page or saved_page)
        self._save_reader_position(reader)
        self.statusBar().showMessage(f"{source_kind(path)} · {relative_id(path)}")

    def close_tab(self, index):
        reader = self.tabs.widget(index)
        if reader:
            self._save_reader_position(reader)
            if hasattr(reader, "path"):
                self.readers.pop(str(reader.path.resolve()), None)
            self.tabs.removeTab(index)
            reader.deleteLater()

    def _tab_changed(self, index):
        reader = self.tabs.widget(index)
        if self._active_reader is not reader:
            self._position_timer.stop()
            self._save_reader_position(self._active_reader)
        self._active_reader = reader
        self.current_path = reader.path if hasattr(reader, "path") else None

    def _queue_position_save(self, *_):
        self._position_timer.start()

    def _save_current_position(self):
        self._save_reader_position(self.tabs.currentWidget())

    def _save_reader_position(self, reader):
        if not hasattr(reader, "path"):
            return
        try:
            if isinstance(reader, TextReader):
                cursor = reader.textCursor()
                save_position(reader.path, line=cursor.blockNumber() + 1,
                              quote=cursor.block().text())
            elif isinstance(reader, PdfReader):
                save_position(reader.path, page=reader.view.pageNavigator().currentPage() + 1)
            elif isinstance(reader, ImageReader):
                save_position(reader.path)
        except (OSError, ValueError):
            pass

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
        self._position_timer.stop()
        self._save_current_position()
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
    app.setWindowIcon(QIcon(str(APP_ICON_FILE)))
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
