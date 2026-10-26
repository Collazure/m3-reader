"""Qt desktop reader for the PRTS resource library."""

from __future__ import annotations

import re
import sys
import codecs
import html
from pathlib import Path

from . import __version__
from .history import diff_rows, import_local, list_runs, load_run
from .jobs import update_arguments, update_command_sequence
from .library import (IMAGE_SUFFIXES, PDF_SUFFIXES, TEXT_SUFFIXES, directory_index, parse_search_request, read_opinions,
                      SEARCH_TAGS, display_part, display_resource_id, relative_id, resource_files, resource_path, search_text,
                      source_kind, write_opinions)
from .paths import APP_ICON_FILE, BOOK_DIR, BOOK_IMAGE_DIR, DEFAULT_TEXT_DIR, OPINIONS_FILE, PROJECT_DIR, RESOURCES_DIR, crawler_command
from .story_layout import migrate_story_layout
from .reading import last_position, position_for, save_position

try:
    from PySide6.QtCore import QEvent, QPointF, QProcess, QSignalBlocker, Qt, QThread, QTimer, QUrl, Signal
    from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QIcon, QPainter, QPixmap, QSyntaxHighlighter, QTextCharFormat, QTextCursor, QTextDocument, QTextFormat
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtPdfWidgets import QPdfView
    from PySide6.QtWidgets import (QApplication, QBoxLayout, QCheckBox, QComboBox, QDockWidget, QHBoxLayout,
                                   QFileDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu,
                                   QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSplitter,
                                   QSizePolicy, QTabWidget, QTextBrowser, QTextEdit, QToolBar, QToolButton, QTreeWidget, QTreeWidgetItem, QWidgetAction,
                                   QVBoxLayout, QWidget)
except ImportError as exc:  # pragma: no cover - tested with the optional Qt runtime
    raise SystemExit("GUI 需要 PySide6。请运行 python -m pip install PySide6 PySide6-Addons") from exc


STYLE = """
QWidget { background: #1f2329; color: #a8cfa7; font-family: 'Maple Mono NF CN','Noto Sans Mono CJK SC',monospace; }
QMainWindow, QDockWidget { background: #191f24; }
QToolBar, QMenuBar, QStatusBar { background: #202a30; border-bottom: 1px solid #4f5f5f; spacing: 7px; padding: 5px; }
QMenuBar::item { padding: 4px 7px; margin: 0; }
QMenuBar::item:selected { background: #385246; color: #f0f9f9; }
QMenu { background: #202a30; border: 1px solid #688a71; padding: 5px; }
QMenu::item { padding: 5px 22px; }
QMenu::item:selected { background: #385246; color: #f0f9f9; }
QTreeWidget, QListWidget, QPlainTextEdit, QTextBrowser, QLineEdit, QComboBox { background: #1f2329; color: #a8cfa7; border: 1px solid #41534b; selection-background-color: #40536a; selection-color: #f0f9f9; }
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
QCheckBox { background: #202a30; color: #a8cfa7; padding: 4px 8px; spacing: 7px; }
QCheckBox::indicator { width: 14px; height: 14px; }
QCheckBox::indicator:checked { background: #8cd0d3; border: 1px solid #a9e8b5; }
QCheckBox::indicator:unchecked { background: #1f2329; border: 1px solid #688a71; }
"""

# Search file-format filters. Text formats are on by default; binary formats
# (PDF / images) are filename-only and stay off to avoid needless scanning.
SEARCH_FORMATS = (
    ("Markdown · .md", (".md",), True),
    ("纯文本 · .txt", (".txt",), True),
    ("CSV · .csv", (".csv",), True),
    ("TSV · .tsv", (".tsv",), True),
    ("PDF 文件名 · .pdf", (".pdf",), False),
    ("JPEG 文件名 · .jpg/.jpeg", (".jpg", ".jpeg"), False),
    ("PNG 文件名 · .png", (".png",), False),
    ("WebP 文件名 · .webp", (".webp",), False),
    ("GIF 文件名 · .gif", (".gif",), False),
    ("BMP 文件名 · .bmp", (".bmp",), False),
)


class SearchThread(QThread):
    ready = Signal(list)

    def __init__(self, query: str, scope: str = "all", include_tags=None, exclude_tags=None,
                 current_directory=None, formats=None):
        super().__init__()
        self.query = query
        self.scope = scope
        self.include_tags = include_tags or set()
        self.exclude_tags = exclude_tags or set()
        self.current_directory = current_directory
        self.formats = formats

    def run(self):
        self.ready.emit(search_text(self.query, limit=1000, scope=self.scope,
                                    include_tags=self.include_tags, exclude_tags=self.exclude_tags,
                                    current_directory=self.current_directory, formats=self.formats))


class CommandLine(QLineEdit):
    """Optional GUI command input with terminal-like history and Tab completion."""

    COMMANDS = ("find", "search", "jump", "font", "markdown", "update", "preview", "images", "history",
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
        # Rehighlighting every block of a large OCR file stalls navigation.
        self.highlighter = ReaderHighlighter(self.document()) if path.stat().st_size < 500_000 else None
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
        if getattr(self, "formatted", False):
            self.setViewportMargins(0, 0, 0, 0)
            self.line_area.hide()
            return
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
        elif char in {"n", "N", ","}:
            self.vim_find.emit(char == "N")
        self._vim_count = ""
        event.accept()

    def _vim_move(self, operation, count):
        cursor = self.textCursor()
        cursor.movePosition(operation, QTextCursor.MoveMode.MoveAnchor, count)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()


class MarkdownBrowser(QTextBrowser):
    """Formatted Markdown with the same read-only navigation keys as text."""

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self._count = ""
        self._pending_g = False
        self.setOpenLinks(False)
        self.setReadOnly(True)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            steps = event.angleDelta().y() / 120
            if steps:
                self.owner.set_reader_font_size(self.font().pointSizeF() + steps)
            event.accept()
        else:
            super().wheelEvent(event)

    def keyPressEvent(self, event):
        if not self.owner.vim_enabled:
            super().keyPressEvent(event)
            return
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() in (Qt.Key.Key_D, Qt.Key.Key_U, Qt.Key.Key_B):
            step = 40 if event.key() == Qt.Key.Key_B else 20
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Down if event.key() == Qt.Key.Key_D else QTextCursor.MoveOperation.Up,
                                QTextCursor.MoveMode.MoveAnchor, step)
            self.setTextCursor(cursor)
            self.ensureCursorVisible()
            return
        if event.modifiers() not in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ShiftModifier):
            super().keyPressEvent(event)
            return
        char = event.text()
        if char.isdigit():
            if char == "0" and not self._count:
                self.moveCursor(QTextCursor.MoveOperation.StartOfLine)
            else:
                self._count = (self._count + char)[-5:]
            return
        count = min(int(self._count or "1"), 100000)
        if self._pending_g:
            self._pending_g = False
            if char == "g":
                block = self.document().findBlockByNumber(max(0, int(self._count or "1") - 1))
                self.setTextCursor(QTextCursor(block) if block.isValid() else QTextCursor(self.document()))
                self._count = ""
                return
        movement = {"h": QTextCursor.MoveOperation.Left, "j": QTextCursor.MoveOperation.Down,
                    "k": QTextCursor.MoveOperation.Up, "l": QTextCursor.MoveOperation.Right,
                    "w": QTextCursor.MoveOperation.NextWord, "b": QTextCursor.MoveOperation.PreviousWord,
                    "$": QTextCursor.MoveOperation.EndOfLine}.get(char)
        if movement is not None:
            cursor = self.textCursor()
            cursor.movePosition(movement, QTextCursor.MoveMode.MoveAnchor, 1 if char == "$" else count)
            self.setTextCursor(cursor)
            self.ensureCursorVisible()
        elif char == "g":
            self._pending_g = True
            return
        elif char == "G":
            if self._count:
                block = self.document().findBlockByNumber(max(0, int(self._count) - 1))
                if block.isValid():
                    self.setTextCursor(QTextCursor(block))
            else:
                self.moveCursor(QTextCursor.MoveOperation.End)
        elif char in {"/", ":"}:
            self.owner.vim_prompt.emit(char)
        elif char in {"n", "N", ","}:
            self.owner.vim_find.emit(char == "N")
        else:
            super().keyPressEvent(event)
        self._count = ""


class MarkdownReader(TextReader):
    link_activated = Signal(QUrl)
    source_requested = Signal()

    def __init__(self, path: Path, *, initial_formatted: bool = True):
        super().__init__(path)
        self.browser = MarkdownBrowser(self)
        self.browser.setFont(self.font())
        self.browser.document().setBaseUrl(QUrl.fromLocalFile(str(path.parent.resolve()) + "/"))
        self.browser.document().setDefaultStyleSheet(
            "h1,h2,h3 { color: #cce08c; margin-top: 16px; } "
            "a { color: #8cd0d3; } blockquote { color: #a8b9a7; margin-left: 18px; } "
            "code,pre { color: #d5e6c7; background-color: #29383a; }")
        self.browser.anchorClicked.connect(self.link_activated)
        self._rendered = False
        self.formatted = False
        self.set_formatted(initial_formatted)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "browser"):
            self.browser.setGeometry(self.rect())

    def set_formatted(self, enabled: bool, *, focus: bool = True):
        if enabled and not self._rendered:
            self.browser.setMarkdown(self.toPlainText())
            self._rendered = True
        self.formatted = enabled
        self._margin()
        if enabled:
            self.browser.setGeometry(self.rect())
            self.browser.show()
            self.browser.raise_()
            if focus:
                self.browser.setFocus()
        else:
            self.browser.hide()
            if focus:
                self.setFocus()

    def setFocus(self, *args):
        if getattr(self, "formatted", False):
            self.browser.setFocus(*args)
        else:
            super().setFocus(*args)

    def set_reader_font_size(self, size: float):
        size = max(8, min(40, size))
        font = self.font()
        font.setPointSizeF(size)
        self.setFont(font)
        self.browser.setFont(font)
        self._margin()
        self.line_area.update()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            steps = event.angleDelta().y() / 120
            if steps:
                self.set_reader_font_size(self.font().pointSizeF() + steps)
            event.accept()
        else:
            super().wheelEvent(event)

    def find(self, text, flags=QTextDocument.FindFlag(0)):
        return self.browser.find(text, flags) if self.formatted else super().find(text, flags)

    def moveCursor(self, operation, mode=QTextCursor.MoveMode.MoveAnchor):
        if self.formatted:
            self.browser.moveCursor(operation, mode)
        else:
            super().moveCursor(operation, mode)

    def jump(self, line: int):
        self.source_requested.emit()
        self.set_formatted(False)
        super().jump(line)


class ImageReader(QScrollArea):
    def __init__(self, path: Path):
        super().__init__()
        self.path = path
        self.original: QPixmap | None = None
        self.scale = 1.0
        self.active = True
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWidget(self.label)
        self.setWidgetResizable(False)
        self._load()
        self._draw()

    def _load(self):
        if self.original is None:
            self.original = QPixmap(str(self.path))

    def set_active(self, active: bool):
        """Keep the decoded pixmap only for the visible image tab."""
        if active == self.active:
            return
        self.active = active
        if active:
            self._load()
            self._draw()
        else:
            self.original = None
            self.label.clear()
            self.label.resize(1, 1)

    def _draw(self):
        if not self.active:
            return
        self._load()
        if self.original is None or self.original.isNull():
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
    """Common page API for Qt PDF and lightweight page-image readers."""
    page_changed = Signal(int)

    def __init__(self, path: Path):
        super().__init__()
        self.path = path

    def jump(self, page: int):
        raise NotImplementedError

    def current_page(self) -> int:
        return 1

    def page_count(self) -> int:
        return 0

    def set_active(self, active: bool):
        pass


class QtPdfReader(PdfReader):
    def __init__(self, path: Path):
        super().__init__(path)
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
        self.view.pageNavigator().currentPageChanged.connect(
            lambda _page: self.page_changed.emit(self.current_page()))

    def jump_from_box(self):
        try:
            self.jump(int(self.page_box.text()))
        except ValueError:
            pass

    def current_page(self) -> int:
        return self.view.pageNavigator().currentPage() + 1

    def page_count(self) -> int:
        return self.document.pageCount()

    def jump(self, page: int):
        if self.page_count() <= 0:
            return
        page = max(1, min(self.page_count(), page))
        self.view.pageNavigator().jump(page - 1, QPointF(), 0)
        self.page_box.setText(str(page))


class BookPageReader(PdfReader):
    """View the scanned 大地巡旅 PDF through its existing page images.

    This avoids QPdfDocument loading the whole ~400 MB scan and keeps only the
    current page's pixmap in memory.
    """

    def __init__(self, path: Path):
        super().__init__(path)
        self.pages = sorted((page for page in BOOK_IMAGE_DIR.glob("page_*")
                             if page.suffix.lower() in IMAGE_SUFFIXES),
                            key=self._page_number)
        self.numbers = [self._page_number(page) for page in self.pages]
        self.index = 0
        self.scale = 1.0
        self.active = True
        self.original: QPixmap | None = None

        self.page_box = QLineEdit("1")
        self.page_box.setMaximumWidth(55)
        self.page_box.returnPressed.connect(self.jump_from_box)
        previous = QPushButton("上一页")
        following = QPushButton("下一页")
        previous.clicked.connect(lambda: self.step(-1))
        following.clicked.connect(lambda: self.step(1))
        row = QHBoxLayout()
        row.addWidget(QLabel("PDF 页码"))
        row.addWidget(self.page_box)
        row.addWidget(previous)
        row.addWidget(following)
        row.addStretch()

        self.label = QLabel()
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.label)
        self.scroll.setWidgetResizable(False)
        self.scroll.viewport().installEventFilter(self)
        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addWidget(self.scroll)
        self.jump(1)

    @staticmethod
    def _page_number(path: Path) -> int:
        match = re.search(r"(\d+)", path.stem)
        return int(match.group(1)) if match else 0

    def page_count(self) -> int:
        return len(self.pages)

    def current_page(self) -> int:
        return self.numbers[self.index] if self.numbers else 1

    def jump_from_box(self):
        try:
            self.jump(int(self.page_box.text()))
        except ValueError:
            pass

    def step(self, delta: int):
        if self.pages:
            self.jump(self.numbers[max(0, min(len(self.pages) - 1, self.index + delta))])

    def jump(self, page: int):
        if not self.pages:
            self.page_box.setText("0")
            self.page_changed.emit(1)
            return
        page = max(self.numbers[0], min(self.numbers[-1], page))
        if page in self.numbers:
            self.index = self.numbers.index(page)
        else:
            self.index = min(range(len(self.numbers)),
                             key=lambda index: abs(self.numbers[index] - page))
        self._load_page()
        page = self.current_page()
        self.page_box.setText(str(page))
        self.page_changed.emit(page)

    def _load_page(self):
        if not self.active or not self.pages:
            return
        self.original = QPixmap(str(self.pages[self.index]))
        self._draw()

    def _draw(self):
        if not self.active or self.original is None:
            return
        if self.original.isNull():
            self.label.setText("图片无法读取")
            return
        scaled = self.original.scaled(self.original.size() * self.scale,
                                      Qt.AspectRatioMode.KeepAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation)
        self.label.setPixmap(scaled)
        self.label.resize(scaled.size())

    def set_active(self, active: bool):
        if active == self.active:
            return
        self.active = active
        if active:
            self._load_page()
        else:
            self.original = None
            self.label.clear()
            self.label.resize(1, 1)

    def eventFilter(self, watched, event):
        if (watched is self.scroll.viewport() and event.type() == QEvent.Type.Wheel
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            step = event.angleDelta().y() / 120
            if step:
                self.scale = max(.2, min(5, self.scale * (1.2 if step > 0 else .8)))
                self._draw()
            return True
        return super().eventFilter(watched, event)


def make_pdf_reader(path: Path) -> PdfReader:
    """Use page images for the local 大地巡旅 scan; QtPdf for other PDFs."""
    try:
        if (path.resolve().parent == BOOK_DIR.resolve()
                and "大地巡旅" in path.name
                and any(page.suffix.lower() in IMAGE_SUFFIXES
                        for page in BOOK_IMAGE_DIR.glob("page_*"))):
            return BookPageReader(path)
    except OSError:
        pass
    return QtPdfReader(path)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        migrate_story_layout(DEFAULT_TEXT_DIR / "avg")
        self.setWindowTitle("M3 Reader // 资料终端")
        self.setWindowIcon(QIcon(str(APP_ICON_FILE)))
        self.resize(1500, 920)
        self.current_path: Path | None = None
        self.search_worker: SearchThread | None = None
        self._search_pending = False
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
        self.markdown_formatted = True
        self.reader_font_size = 14
        self.menu_font_size = 13
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["资源目录"])
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.itemClicked.connect(self.click_tree_item)
        self.tree.itemDoubleClicked.connect(self.open_tree_item)
        self.tree.itemExpanded.connect(self._populate_tree_item)
        tree_panel = QWidget()
        tree_layout = QVBoxLayout(tree_panel)
        tree_layout.setContentsMargins(4, 4, 4, 4)
        self.tree_filter = QLineEdit()
        self.tree_filter.setPlaceholderText("筛选目录或文件名…")
        self.tree_filter.textChanged.connect(self.filter_tree)
        tree_layout.addWidget(self.tree_filter)
        tree_layout.addWidget(self.tree)
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._tab_changed)
        split = QSplitter()
        split.addWidget(tree_panel)
        split.addWidget(self.tabs)
        split.setSizes([360, 1100])
        self.setCentralWidget(split)
        self.make_toolbar()
        self.set_menu_font_size(self.menu_font_size)
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
        self.search_menu = self.menuBar().addMenu("检索")
        self.tools_menu = self.menuBar().addMenu("工具")
        self.view_menu = self.menuBar().addMenu("视图")
        self.reading_menu.addAction("继续阅读", self.resume_reading)
        self.reading_menu.addAction("返回上一个文件", self.go_back)
        self.reading_menu.addAction("上一文件", lambda: self.adjacent_file(-1))
        self.reading_menu.addAction("下一文件", lambda: self.adjacent_file(1))
        online_menu = self.online_menu = QMenu("在线采集", self.import_menu)
        local_menu = self.local_menu = QMenu("本地资料", self.import_menu)
        self.import_menu.addMenu(online_menu)
        self.import_menu.addMenu(local_menu)
        controls = self.online_controls = QWidget()
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
        controls_action = QWidgetAction(online_menu)
        controls_action.setDefaultWidget(controls)
        online_menu.addAction(controls_action)
        online_menu.addSeparator()
        self.run_button = online_menu.addAction("更新资料（选择文本或完整）…", self.choose_update)
        self.preview_button = online_menu.addAction("预览文本变动", lambda: self.run_update(preview=True))
        self.images_button = online_menu.addAction("下载泰拉记事图片", lambda: self.run_update(images=True))
        local_menu.addAction("导入新资料…", self.import_file)
        local_menu.addAction("替换当前本地资料…", self.replace_file)
        self.search_menu.addAction("文件内查找", lambda: self.find_input.setFocus())
        self.search_menu.addAction("全库检索", lambda: self.global_input.setFocus())
        wrap = QAction("自动换行", self)
        wrap.setCheckable(True)
        wrap.setChecked(True)
        wrap.triggered.connect(self.set_wrap)
        self.view_menu.addAction(wrap)
        self.markdown_action = QAction("Markdown 格式化显示", self)
        self.markdown_action.setCheckable(True)
        self.markdown_action.setChecked(True)
        self.markdown_action.setShortcut("Ctrl+M")
        self.markdown_action.toggled.connect(self.set_markdown_format)
        self.view_menu.addAction(self.markdown_action)
        font_menu = self.font_menu = QMenu("阅读字号", self.view_menu)
        self.view_menu.addMenu(font_menu)
        for size in (12, 14, 16, 18, 20, 24):
            font_menu.addAction(f"{size} pt", lambda checked=False, value=size: self.set_font_size(value))
        menu_font = self.menu_font_menu = QMenu("任务栏字号", self.view_menu)
        self.view_menu.addMenu(menu_font)
        for size in (10, 12, 13, 14, 16, 18, 20):
            menu_font.addAction(f"{size} pt", lambda checked=False, value=size: self.set_menu_font_size(value))
        self.vim_action = QAction("只读 Vim 操作", self)
        self.vim_action.setCheckable(True)
        self.vim_action.setChecked(True)
        self.vim_action.toggled.connect(self.set_vim)
        self.tools_menu.addAction(self.vim_action)
        self.command_action = QAction("命令栏", self)
        self.command_action.setCheckable(True)
        self.command_action.setShortcut("Ctrl+L")
        self.command_action.toggled.connect(self.set_command_visible)
        self.tools_menu.addAction(self.command_action)
        self.help_menu = self.menuBar().addMenu("帮助")
        self.notes_toolbar_action = self.help_menu.addAction(
            "更新意见", lambda: (self.notes_dock.show(), self.opinions_edit.setFocus()))
        self.help_menu.addAction("快捷键与命令", self.show_command_help)
        self.help_menu.addAction("关于 M3 Reader", lambda: QMessageBox.information(
            self, "关于 M3 Reader", f"M3 Reader {__version__}\nPRTS 资料阅读与采集工具"))
        right = QWidget(self)
        right_layout = self.header_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, right)
        right_layout.setContentsMargins(4, 0, 4, 0)
        right_layout.setSpacing(5)
        local_row = QWidget(right)
        local_layout = QHBoxLayout(local_row)
        local_layout.setContentsMargins(0, 0, 0, 0)
        local_layout.setSpacing(5)
        self.find_input = QLineEdit()
        self.find_input.setPlaceholderText("文件内搜索 Ctrl+F")
        self.find_input.setToolTip("文件内搜索 Ctrl+F")
        self.find_input.setFixedWidth(190)
        self.find_input.returnPressed.connect(self.find_next)
        local_layout.addWidget(self.find_input)
        next_button = QPushButton("下一个")
        next_button.clicked.connect(self.find_next)
        local_layout.addWidget(next_button)
        right_layout.addWidget(local_row, 0, Qt.AlignmentFlag.AlignRight)
        global_row = QWidget(right)
        global_layout = QHBoxLayout(global_row)
        global_layout.setContentsMargins(0, 0, 0, 0)
        global_layout.setSpacing(5)
        self.global_input = QLineEdit()
        self.global_input.setPlaceholderText("全局搜索 Ctrl+Shift+F")
        self.global_input.setToolTip("全局搜索 Ctrl+Shift+F")
        self.global_input.setFixedWidth(200)
        self.global_input.returnPressed.connect(self.global_search)
        global_layout.addWidget(self.global_input)
        self.search_format = QToolButton()
        self.search_format.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.search_format.setToolTip("选择搜索的文件格式（可多选）；PDF/图片默认关闭")
        format_menu = self.format_menu = QMenu(self.search_format)
        self._formats_dirty = False
        self.format_checks: dict[str, QCheckBox] = {}
        self.format_suffixes: dict[str, frozenset[str]] = {}
        for label, suffixes, checked in SEARCH_FORMATS:
            check = QCheckBox(label, format_menu)
            check.setChecked(checked)
            check.toggled.connect(self._search_format_toggled)
            widget_action = QWidgetAction(format_menu)
            widget_action.setDefaultWidget(check)
            format_menu.addAction(widget_action)
            self.format_checks[label] = check
            self.format_suffixes[label] = frozenset(suffixes)
        format_menu.addSeparator()
        format_menu.addAction("仅文本格式", lambda checked=False: self.set_search_formats("text"))
        format_menu.addAction("全选", lambda checked=False: self.set_search_formats("all"))
        format_menu.addAction("清空", lambda checked=False: self.set_search_formats("none"))
        format_menu.aboutToHide.connect(self._search_format_menu_closed)
        self.search_format.setMenu(format_menu)
        self._update_search_format_label()
        global_layout.addWidget(self.search_format)
        global_button = QPushButton("搜索")
        global_button.clicked.connect(self.global_search)
        global_layout.addWidget(global_button)
        self.version_label = QLabel(f"M3 Reader · v{__version__}")
        self.version_label.setToolTip(f"M3 Reader · v{__version__}")
        global_layout.addWidget(self.version_label)
        right_layout.addWidget(global_row, 0, Qt.AlignmentFlag.AlignRight)
        self.header_controls = right
        # Keep the six menus on their own row so larger menu fonts cannot hide View/Help.
        self.header_toolbar = QToolBar("搜索", self)
        self.header_toolbar.setMovable(False)
        self.header_toolbar.setFloatable(False)
        spacer = QWidget(self.header_toolbar)
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.header_toolbar.addWidget(spacer)
        self.header_toolbar.addWidget(right)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.header_toolbar)
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
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 4, 6, 4)
        self.search_summary = QLabel("输入关键词检索文件名和正文；点击结果跳转", panel)
        self.search_summary.hide()
        search_split = QSplitter()
        self.search_results = QTextBrowser()
        self.search_results.setOpenLinks(False)
        self.search_results.anchorClicked.connect(self.open_search_hit)
        self.search_hits = []
        search_split.addWidget(self.search_results)
        filters = QWidget()
        filters_layout = QVBoxLayout(filters)
        filters_layout.addWidget(QLabel("标签筛选  ·  ＋包含 / －排除"))
        self.tag_buttons = {}
        self.tag_labels = {}
        for tag in SEARCH_TAGS:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(2, 1, 2, 1)
            label = QLabel(tag)
            label.setStyleSheet("color: #8cd0d3" if tag in {"下载", "本地", "当前目录"} else "color: #cce08c")
            row_layout.addWidget(label, 1)
            yes = QPushButton("＋")
            no = QPushButton("－")
            for button in (yes, no):
                button.setCheckable(True)
                button.setFixedWidth(32)
                row_layout.addWidget(button)
            yes.toggled.connect(lambda checked, t=tag: self.set_search_tag(t, True, checked))
            no.toggled.connect(lambda checked, t=tag: self.set_search_tag(t, False, checked))
            self.tag_buttons[tag] = (yes, no)
            self.tag_labels[tag] = label
            self.paint_search_tag(tag)
            filters_layout.addWidget(row)
        filters_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(filters)
        search_split.addWidget(scroll)
        search_split.setSizes([950, 235])
        layout.addWidget(search_split)
        self.search_panel = panel
        self.search_tab_index = self.tabs.addTab(panel, "检索结果")
        self.tabs.removeTab(self.search_tab_index)

    def selected_search_formats(self) -> set[str]:
        formats: set[str] = set()
        for label, check in self.format_checks.items():
            if check.isChecked():
                formats |= self.format_suffixes[label]
        return formats

    def set_search_formats(self, mode: str):
        """Bulk-check formats: text / all / none."""
        for label, check in self.format_checks.items():
            suffixes = self.format_suffixes[label]
            checked = mode == "all" or (mode == "text" and suffixes <= TEXT_SUFFIXES)
            with QSignalBlocker(check):
                check.setChecked(checked)
        self._update_search_format_label()
        self._search_format_toggled()

    def _update_search_format_label(self):
        selected = self.selected_search_formats()
        if not selected:
            label = "格式 · 无"
        elif selected <= TEXT_SUFFIXES:
            label = "格式 · 文本"
        else:
            checked_count = sum(1 for check in self.format_checks.values() if check.isChecked())
            label = f"格式 · {checked_count}"
        self.search_format.setText(label)
        names = [name for name, check in self.format_checks.items() if check.isChecked()]
        self.search_format.setToolTip(
            "已选文件格式（可多选）：\n" + "\n".join(names)
            if names else "未选择文件格式；请至少勾选一项")

    def _search_format_toggled(self, _checked=False):
        # Do not rerun the (potentially expensive) search for every checkbox;
        # wait until the format menu closes.
        self._formats_dirty = True
        self._update_search_format_label()

    def _search_format_menu_closed(self):
        if not self._formats_dirty:
            return
        self._formats_dirty = False
        worker = getattr(self, "search_worker", None)
        if self.global_input.text().strip() and not (worker and worker.isRunning()):
            self.global_search()
        elif self.global_input.text().strip():
            self._search_pending = True

    def _search_worker_finished(self):
        if not self._search_pending:
            return
        self._search_pending = False
        QTimer.singleShot(0, self.global_search)

    def set_search_tag(self, tag: str, positive: bool, checked: bool):
        yes, no = self.tag_buttons[tag]
        opposite = no if positive else yes
        if checked and opposite.isChecked():
            with QSignalBlocker(opposite):
                opposite.setChecked(False)
        self.paint_search_tag(tag)
        if self.global_input.text().strip() and not (self.search_worker and self.search_worker.isRunning()):
            self.global_search()

    def paint_search_tag(self, tag: str):
        yes, no = self.tag_buttons[tag]
        label = self.tag_labels[tag]
        label_color = "#8cd0d3" if tag in {"下载", "本地", "当前目录"} else "#cce08c"
        if yes.isChecked():
            label_color = "#a9e8b5"
        elif no.isChecked():
            label_color = "#efadad"
        label.setStyleSheet(f"color: {label_color}")
        for button, active, background, foreground, border in (
            (yes, yes.isChecked(), "#315b46", "#c9f5cf", "#77c58a"),
            (no, no.isChecked(), "#664042", "#ffe1d8", "#d98f8c")):
            button.setStyleSheet(
                f"background-color: {background if active else '#29383a'}; "
                f"color: {foreground if active else '#81998d'}; "
                f"border: 1px solid {border if active else '#41534b'}; "
                "padding: 5px 8px; font-weight: bold;"
            )

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

    def set_markdown_format(self, enabled: bool):
        self.markdown_formatted = enabled
        for reader in self.readers.values():
            if isinstance(reader, MarkdownReader):
                reader.set_formatted(enabled, focus=reader is self.tabs.currentWidget())

    def set_font_size(self, size: float):
        if not 8 <= size <= 40:
            raise ValueError("字号范围为 8–40 pt")
        self.reader_font_size = size
        for reader in self.readers.values():
            if isinstance(reader, MarkdownReader):
                reader.set_reader_font_size(size)
            elif isinstance(reader, TextReader):
                font = reader.font()
                font.setPointSizeF(size)
                reader.setFont(font)
                reader._margin()
        self.statusBar().showMessage(f"阅读字号：{size:g} pt")

    def set_menu_font_size(self, size: float):
        if not 8 <= size <= 32:
            raise ValueError("任务栏字号范围为 8–32 pt")
        self.menu_font_size = size
        font = self.menuBar().font()
        font.setPointSizeF(size)
        self.menuBar().setFont(font)
        self.header_toolbar.setFont(font)
        self.header_controls.setFont(font)
        self.online_controls.setFont(font)
        for widget in (*self.header_controls.findChildren(QWidget),
                       *self.online_controls.findChildren(QWidget)):
            widget.setFont(font)
        large = size >= 20
        self.find_input.setFixedWidth(max(190, round(size * 8)))
        self.global_input.setFixedWidth(max(200, round(size * 8)))
        self.search_format.setFixedWidth(max(120, min(230, round(size * 7))))
        self.find_input.setPlaceholderText("文件内查找" if large else "文件内搜索 Ctrl+F")
        self.global_input.setPlaceholderText("全局搜索" if large else "全局搜索 Ctrl+Shift+F")
        self.version_label.setText(f"M3 · v{__version__}" if large else f"M3 Reader · v{__version__}")
        self.header_layout.setDirection(
            QBoxLayout.Direction.TopToBottom if large else QBoxLayout.Direction.LeftToRight)
        self.header_layout.invalidate()
        self.header_controls.adjustSize()
        self.header_controls.updateGeometry()
        self.header_toolbar.updateGeometry()
        for menu in (self.import_menu, self.reading_menu, self.search_menu,
                     self.tools_menu, self.view_menu, self.help_menu,
                     self.online_menu, self.local_menu, self.font_menu, self.menu_font_menu,
                     self.format_menu):
            menu.setFont(font)
        for check in self.format_checks.values():
            check.setFont(font)
        self.statusBar().showMessage(f"任务栏字号：{size:g} pt")

    def set_vim(self, enabled):
        for reader in self.readers.values():
            if isinstance(reader, TextReader):
                reader.vim_enabled = enabled

    def show_vim_prompt(self, prefix: str):
        if self.command_dock.isVisible():
            self.command_input.setText(prefix)
            self.command_input.setFocus()
            return
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
                self.command_input.setText(value)
                self.execute_gui_command()
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
        self.command_label = QLabel("命令 ›")
        row.addWidget(self.command_label)
        self.command_input = CommandLine()
        self.pending_command = None
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
            "可选命令栏（Ctrl+L）：font size 16、font menu 14、markdown render|source、find、search、jump、update、preview、images、history、"
            "diff 运行序号 变化序号、notes、note、save、page、open、import、replace、"
            "resume、next、prev、back、help、quit。")

    def reload_tree(self):
        """Build only the top level; children are created when a folder opens."""
        self.tree.clear()
        self.catalog_files = sorted(resource_files(), key=lambda p: p.relative_to(RESOURCES_DIR).as_posix().casefold())
        self.catalog_dirs: dict[tuple[str, ...], dict[str, Path | None]] = {}
        for path in self.catalog_files:
            parts = path.relative_to(RESOURCES_DIR).parts
            for index in range(len(parts)):
                children = self.catalog_dirs.setdefault(parts[:index], {})
                children[parts[index]] = path if index == len(parts) - 1 else None
        self._add_tree_level((), None)
        if self.tree_filter.text():
            self.filter_tree(self.tree_filter.text())

    @staticmethod
    def _item_parts(item: QTreeWidgetItem) -> tuple[str, ...]:
        parts: list[str] = []
        current = item
        while current is not None:
            part = current.data(0, Qt.ItemDataRole.UserRole + 1)
            if part is None:
                break
            parts.append(part)
            current = current.parent()
        return tuple(reversed(parts))

    def _add_tree_level(self, prefix: tuple[str, ...], parent: QTreeWidgetItem | None):
        children = self.catalog_dirs.get(prefix, {})
        for name in sorted(children, key=lambda value: display_part(value).casefold()):
            path = children[name]
            item = QTreeWidgetItem([display_part(name)])
            item.setData(0, Qt.ItemDataRole.UserRole + 1, name)
            if path is not None:
                item.setData(0, Qt.ItemDataRole.UserRole, str(path))
            elif self.catalog_dirs.get(prefix + (name,)):
                item.addChild(QTreeWidgetItem(["…"]))
            if parent is None:
                self.tree.addTopLevelItem(item)
            else:
                parent.addChild(item)

    def _populate_tree_item(self, item: QTreeWidgetItem):
        if item.data(0, Qt.ItemDataRole.UserRole):     # file
            return
        if item.data(0, Qt.ItemDataRole.UserRole + 2):  # filtered or already populated
            return
        prefix = self._item_parts(item)
        item.takeChildren()
        self._add_tree_level(prefix, item)
        item.setData(0, Qt.ItemDataRole.UserRole + 2, True)

    def filter_tree(self, term: str):
        needle = term.strip().casefold()
        if not needle:
            self.reload_tree()
            return
        matches = []
        for path in self.catalog_files:
            parts = path.relative_to(RESOURCES_DIR).parts
            shown = " / ".join(display_part(part) for part in parts).casefold()
            if needle in shown:
                matches.append(path)
        self.tree.clear()
        entries: dict[tuple[str, ...], QTreeWidgetItem] = {}
        for path in matches:
            parts = path.relative_to(RESOURCES_DIR).parts
            parent = None
            for index, part in enumerate(parts):
                key = parts[:index + 1]
                item = entries.get(key)
                if item is None:
                    item = QTreeWidgetItem([display_part(part)])
                    item.setData(0, Qt.ItemDataRole.UserRole + 1, part)
                    item.setData(0, Qt.ItemDataRole.UserRole + 2, True)  # filter tree is complete
                    if parent is None:
                        self.tree.addTopLevelItem(item)
                    else:
                        parent.addChild(item)
                    entries[key] = item
                parent = item
            parent.setData(0, Qt.ItemDataRole.UserRole, str(path))
        self.tree.expandAll()

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
            parts.append(current.data(0, Qt.ItemDataRole.UserRole + 1) or current.text(0))
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
            return 1, reader.current_page()
        return 1, None

    def execute_gui_command(self):
        raw = self.command_input.text().strip()
        self.command_input.clear()
        if self.pending_command:
            command = self.pending_command
            self.pending_command = None
            self.command_label.setText("命令 ›")
            if not raw:
                self.statusBar().showMessage(f"已退出 {command} 输入", 5000)
                return
            raw = f"{command} {raw}"
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
        if not rest and command in {"find", "search", "jump", "page", "note"}:
            self.pending_command = command
            self.command_label.setText(f"{command}:")
            self.command_input.setFocus()
            return
        try:
            if command == "find":
                if rest:
                    self.find_input.setText(rest)
                    self.find_next()
                    reader = self.tabs.currentWidget()
                    if isinstance(reader, TextReader):
                        reader.setFocus()
            elif command == "search":
                if rest:
                    query, scope = parse_search_request(rest)
                    self.global_input.setText(query)
                    self.global_search(scope=scope)
                else:
                    self.global_input.setFocus()
            elif command == "jump":
                reader = self.tabs.currentWidget()
                if not isinstance(reader, TextReader) or not rest.isdecimal() or int(rest) < 1:
                    raise ValueError("先打开文本，再输入 jump 行号")
                reader.jump(int(rest))
            elif command == "font":
                parts = rest.split()
                if len(parts) != 2 or parts[0].casefold() not in {"size", "reader", "menu"}:
                    raise ValueError("用法：font size 16 或 font menu 14")
                try:
                    size = float(parts[1])
                except ValueError:
                    raise ValueError("字号必须是数字，例如 font size 16") from None
                self.set_menu_font_size(size) if parts[0].casefold() == "menu" else self.set_font_size(size)
            elif command == "markdown":
                if rest.casefold() not in {"render", "source"}:
                    raise ValueError("用法：markdown render 或 markdown source")
                self.markdown_action.setChecked(rest.casefold() == "render")
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
                reader = MarkdownReader(path, initial_formatted=self.markdown_formatted and not line) if suffix == ".md" else TextReader(path)
                reader.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth if self.wrap_enabled else QPlainTextEdit.LineWrapMode.NoWrap)
                if isinstance(reader, MarkdownReader):
                    reader.set_formatted(self.markdown_formatted and not line)
                    reader.link_activated.connect(lambda url, source=path: self.open_markdown_link(source, url))
                    reader.source_requested.connect(lambda: self.markdown_action.setChecked(False))
                if self.reader_font_size != 14:
                    if isinstance(reader, MarkdownReader):
                        reader.set_reader_font_size(self.reader_font_size)
                    else:
                        font = reader.font()
                        font.setPointSizeF(self.reader_font_size)
                        reader.setFont(font)
                reader.vim_enabled = self.vim_action.isChecked()
                reader.vim_prompt.connect(self.show_vim_prompt)
                reader.vim_find.connect(self.vim_find)
                reader.cursorPositionChanged.connect(self._queue_position_save)
            elif suffix in IMAGE_SUFFIXES:
                reader = ImageReader(path)
            elif suffix in PDF_SUFFIXES:
                reader = make_pdf_reader(path)
                reader.page_changed.connect(self._queue_position_save)
            else:
                return
            self.readers[key] = reader
            self.tabs.addTab(reader, path.name)
            self.tabs.setTabToolTip(self.tabs.indexOf(reader), relative_id(path))
            self.tabs.setCurrentWidget(reader)
        self.current_path = path
        saved_line, saved_page = position_for(path) if not existing and not line and page is None else (1, None)
        if isinstance(reader, MarkdownReader) and (line or (not existing and saved_line > 1)):
            reader.jump(min(line or saved_line, reader.blockCount()))
        elif isinstance(reader, TextReader) and not isinstance(reader, MarkdownReader) and (line or not existing):
            reader.jump(min(line or saved_line, reader.blockCount()))
        if isinstance(reader, PdfReader) and (page or (not existing and saved_page)):
            reader.jump(page or saved_page)
        self._save_reader_position(reader)
        self.statusBar().showMessage(f"{source_kind(path)} · {relative_id(path)}")

    def open_markdown_link(self, source: Path, url: QUrl):
        if url.scheme() in {"http", "https"}:
            QDesktopServices.openUrl(url)
            return
        if not url.path() and url.fragment():
            reader = self.tabs.currentWidget()
            if isinstance(reader, MarkdownReader):
                reader.browser.scrollToAnchor(url.fragment())
            return
        target = (source.parent / url.path()).resolve() if url.isRelative() else Path(url.toLocalFile()).resolve()
        if target.is_file():
            try:
                relative_id(target)
            except ValueError:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
            else:
                self.open_resource(target)
        else:
            self.statusBar().showMessage(f"链接目标不存在：{url.toString()}", 8000)

    def close_tab(self, index):
        reader = self.tabs.widget(index)
        if reader:
            if reader is self.search_panel:
                self.tabs.removeTab(index)
                return
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
            if isinstance(self._active_reader, (ImageReader, PdfReader)):
                self._active_reader.set_active(False)
        self._active_reader = reader
        if isinstance(reader, (ImageReader, PdfReader)):
            reader.set_active(True)
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
                save_position(reader.path, page=reader.current_page())
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

    def global_search(self, *, scope: str = "all"):
        term = self.global_input.text().strip()
        if not term or (self.search_worker and self.search_worker.isRunning()):
            return
        if self.current_path:
            self.search_context_path = self.current_path
        self.search_results.clear()
        self.search_summary.setText(f"正在检索「{term}」…")
        if self.tabs.indexOf(self.search_panel) < 0:
            self.tabs.addTab(self.search_panel, "检索结果")
        self.tabs.setTabText(self.tabs.indexOf(self.search_panel), "检索中…")
        self.tabs.setCurrentWidget(self.search_panel)
        include = {tag for tag, (yes, _) in self.tag_buttons.items() if yes.isChecked()}
        exclude = {tag for tag, (_, no) in self.tag_buttons.items() if no.isChecked()}
        current_dir = relative_id(self.search_context_path.parent) if getattr(self, "search_context_path", None) else None
        formats = self.selected_search_formats()
        if not formats:
            self.statusBar().showMessage("请至少勾选一种文件格式（格式菜单在搜索框右侧）")
            return
        self.search_worker = SearchThread(term, scope, include, exclude, current_dir, formats)
        self.search_worker.ready.connect(self.show_hits)
        self.search_worker.finished.connect(self._search_worker_finished)
        self.search_worker.start()

    def show_hits(self, hits):
        self.search_hits = hits
        rows = ["<html><body style='color:#a8cfa7;font-family:monospace'>"]
        for index, hit in enumerate(hits, 1):
            suffix = Path(hit.resource_id).suffix.lower()
            binary = suffix in PDF_SUFFIXES | IMAGE_SUFFIXES
            location = ("PDF 文件名" if suffix in PDF_SUFFIXES else "图片文件名") if binary else (
                f"第 {hit.page} 页" if hit.page else f"第 {hit.line} 行")
            source = html.escape(display_resource_id(hit.resource_id))
            excerpt = html.escape(hit.excerpt)
            title = f"{index:04d}  {source}{'' if binary else f':{hit.line}'}  ·  {location}"
            body = ("[文件名] " if hit.kind == "title" and not binary else "") + excerpt
            rows.append(f"<p style='margin:9px 8px 1px'><a href='m3hit:{index - 1}' "
                        f"style='color:#8cd0d3;text-decoration:none'>{title}</a></p>")
            rows.append(f"<p style='margin:0 8px 9px 34px'><a href='m3hit:{index - 1}' "
                        f"style='color:#cce08c;text-decoration:none'>{body}</a></p>")
            if hit.page and hit.resource_id.endswith("大地巡旅_OCR.txt"):
                rows.append(f"<p style='margin:0 8px 9px 34px'><a href='m3pdf:{index - 1}' "
                            f"style='color:#8cd0d3'>查看 PDF 第 {hit.page} 页</a></p>")
        rows.append("</body></html>")
        self.search_results.setHtml("".join(rows))
        files = len({hit.resource_id for hit in hits})
        message = f"{files} 个文件 · {len(hits)} 条命中"
        if len(hits) >= 1000:
            message += " · 达到显示上限，请缩小范围或关键词"
        if not hits:
            message = "没有命中；试试更短的关键词，或调整格式与标签"
        self.search_summary.setText(message)
        tab_index = self.tabs.indexOf(self.search_panel)
        if tab_index >= 0:
            self.tabs.setTabText(tab_index, f"检索 · {files}文件/{len(hits)}条")
        self.statusBar().showMessage(message)

    def open_search_hit(self, url: QUrl):
        if url.scheme() not in {"m3hit", "m3pdf"}:
            return
        try:
            hit = self.search_hits[int(url.path())]
        except (ValueError, IndexError):
            return
        if url.scheme() == "m3pdf":
            pdf = next(BOOK_DIR.glob("*.pdf"), None)
            if pdf and hit.page:
                self.open_resource(pdf, page=hit.page)
            return
        self.open_resource(resource_path(hit.resource_id), line=hit.line)

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
