"""GUI layout smoke tests: side docks stay hidden until requested."""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtCore import QPoint, Qt, QUrl
from PySide6.QtGui import QImage, QTextCursor, QTextDocument

from prts_tool.gui import CommandLine, MainWindow, MarkdownReader, TextReader
from prts_tool.library import SearchHit
from prts_tool.paths import RESOURCES_DIR
from prts_tool import reading


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_side_docks_hidden_and_history_toggle(app):
    window = MainWindow()
    try:
        assert window.history_dock.isHidden()
        assert window.notes_dock.isHidden()
        assert window.history_action.isCheckable()
        assert not window.history_action.isChecked()

        window.history_action.trigger()
        assert not window.history_dock.isHidden()
        assert window.history_action.isChecked()

        window.history_action.trigger()
        assert window.history_dock.isHidden()
        assert not window.history_action.isChecked()
    finally:
        window.close()


def test_text_reader_shows_absolute_line_numbers(app):
    reader = TextReader(RESOURCES_DIR / "README.md")
    reader.resize(640, 480)
    reader.show()
    app.processEvents()
    try:
        assert not reader.line_area.isHidden()
        assert reader.line_area.width() > 0
        assert reader.viewportMargins().left() == reader.line_width()
        assert reader.document().findBlockByNumber(0).blockNumber() + 1 == 1
    finally:
        reader.close()


def test_menus_command_bar_and_icon(app):
    window = MainWindow()
    try:
        labels = [action.text() for action in window.menuBar().actions()]
        assert labels == ["导入", "阅读", "检索", "工具", "视图", "帮助"]
        assert [action.text() for action in window.import_menu.actions() if action.menu()] == ["在线采集", "本地资料"]
        assert any(action.text().startswith("更新资料") for action in window.online_menu.actions())
        assert any(action.text().startswith("导入新资料") for action in window.local_menu.actions())
        assert any(action.text() == "更新意见" for action in window.help_menu.actions())
        assert any(action.text() == "命令栏" for action in window.tools_menu.actions())
        assert [action.text() for action in window.view_menu.actions()] == ["自动换行", "Markdown 格式化显示", "阅读字号", "任务栏字号"]
        assert window.header_toolbar.actions()[-1].defaultWidget() is window.header_controls
        assert not window.windowIcon().isNull()
        assert window.command_dock.isHidden()
        window.tree_filter.setText("不存在的资源名 12345")
        assert all(window.tree.topLevelItem(i).isHidden() for i in range(window.tree.topLevelItemCount()))
        window.tree_filter.clear()
        assert any(not window.tree.topLevelItem(i).isHidden() for i in range(window.tree.topLevelItemCount()))
        window.command_action.trigger()
        assert not window.command_dock.isHidden()
        window.command_action.trigger()
        assert window.command_dock.isHidden()
    finally:
        window.close()


def test_command_line_completion_and_history(app):
    from PySide6.QtCore import Qt

    line = CommandLine()
    line.setText("resu")
    QTest.keyClick(line, Qt.Key.Key_Tab)
    assert line.text() == "resume "
    line.remember("jump 15")
    line.clear()
    QTest.keyClick(line, Qt.Key.Key_Up)
    assert line.text() == "jump 15"
    QTest.keyClick(line, Qt.Key.Key_Down)
    assert line.text() == ""


def test_search_results_in_reader_tab_with_two_line_entries(app):
    window = MainWindow()
    try:
        window.show_hits([SearchHit("local/a.md", 1, "文件名：a.md", kind="title"),
                          SearchHit("local/a.md", 5, "正文命中"),
                          SearchHit("collected/b.txt", 2, "另一条命中")])
        text = window.search_results.toPlainText()
        assert text.count("本地/a.md") == 2
        assert "[文件名] 文件名：a.md" in text
        assert "正文命中" in text
        assert "下载/b.txt:2" in text
        assert "2 个文件" in window.search_summary.text()
        assert window.search_summary.isHidden()
        assert window.tabs.indexOf(window.search_panel) < 0  # the tab opens when a search starts
        calls = []
        window.global_search = lambda *, scope="all": calls.append((window.global_input.text(), scope))
        window.command_input.setText("search --scope local 泰拉 年表")
        window.execute_gui_command()
        assert calls == [("泰拉 年表", "local")]
    finally:
        window.close()


def test_search_hit_opens_source_without_eager_markdown_or_pdf(app):
    window = MainWindow()
    try:
        window.show_hits([SearchHit("README.md", 3, "内容")])
        window.open_search_hit(QUrl("m3hit:0"))
        reader = window.tabs.currentWidget()
        assert isinstance(reader, MarkdownReader)
        assert reader.path == RESOURCES_DIR / "README.md"
        assert reader.textCursor().blockNumber() == 2
        assert not reader._rendered
    finally:
        window.close()


def test_format_menu_checkboxes_support_multiselect(app):
    window = MainWindow()
    window.show()
    app.processEvents()
    menu = window.format_menu
    menu.popup(QPoint(20, 20))
    app.processEvents()
    try:
        assert menu.isVisible()
        assert window.format_checks["Markdown · .md"].isChecked()
        assert not window.format_checks["PDF 文件名 · .pdf"].isChecked()

        pdf = window.format_checks["PDF 文件名 · .pdf"]
        QTest.mouseClick(pdf, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, pdf.rect().center())
        app.processEvents()

        # Selecting one format must not close the menu; more can be checked.
        assert menu.isVisible()
        assert pdf.isChecked()
        assert window.selected_search_formats() == {".md", ".txt", ".csv", ".tsv", ".pdf"}
    finally:
        menu.hide()
        window.close()


def test_search_tab_tags_and_independent_font_commands(app):
    window = MainWindow()
    try:
        # Text formats are checked by default; PDF/images stay off.
        assert window.selected_search_formats() == {".md", ".txt", ".csv", ".tsv"}
        for label in ("Markdown · .md", "纯文本 · .txt", "CSV · .csv", "TSV · .tsv"):
            assert window.format_checks[label].isChecked()
        for label in ("PDF 文件名 · .pdf", "PNG 文件名 · .png",
                      "JPEG 文件名 · .jpg/.jpeg"):
            assert not window.format_checks[label].isChecked()

        # Multi-select: uncheck everything, then check Markdown only.
        window.set_search_formats("none")
        window.format_checks["Markdown · .md"].setChecked(True)
        window.global_input.setText("故事")
        window.global_search()
        assert window.tabs.currentWidget() is window.search_panel
        assert window.search_worker.formats == {".md"}
        window.search_worker.wait(30000)

        # Adding PDF and PNG keeps Markdown selected too.
        window.format_checks["PDF 文件名 · .pdf"].setChecked(True)
        window.format_checks["PNG 文件名 · .png"].setChecked(True)
        assert window.selected_search_formats() == {".md", ".pdf", ".png"}
        if window.search_worker and window.search_worker.isRunning():
            window.search_worker.wait(30000)
        window.global_search()
        assert window.search_worker.formats == {".md", ".pdf", ".png"}
        window.search_worker.wait(30000)
        yes, no = window.tag_buttons["特殊"]
        yes.setChecked(True)
        assert yes.isChecked() and not no.isChecked()
        assert "#315b46" in yes.styleSheet()
        assert "#a9e8b5" in window.tag_labels["特殊"].styleSheet()
        no.setChecked(True)
        assert no.isChecked() and not yes.isChecked()
        assert "#664042" in no.styleSheet()
        assert "#efadad" in window.tag_labels["特殊"].styleSheet()
        no.setChecked(False)
        assert "#29383a" in no.styleSheet()
        assert "#cce08c" in window.tag_labels["特殊"].styleSheet()
        window.command_input.setText("font menu 16")
        window.execute_gui_command()
        assert window.menu_font_size == 16
        assert window.reader_font_size == 14
        assert window.online_menu.font().pointSizeF() == 16
        assert [action.text() for action in window.menuBar().actions()][:2] == ["导入", "阅读"]
        window.resize(1500, 920)
        window.show()
        window.set_menu_font_size(32)
        app.processEvents()
        assert all(widget.font().pointSizeF() == 32 for widget in (
            window.menuBar(), window.global_input, window.search_format,
            window.version_label, window.module, window.mode))
        assert window.menuBar().actionGeometry(window.menuBar().actions()[-1]).right() < window.menuBar().width()
        assert window.header_controls.sizeHint().width() <= window.header_toolbar.width()
        assert window.header_layout.direction().name == "TopToBottom"
        window.command_input.setText("font size 18")
        window.execute_gui_command()
        assert window.reader_font_size == 18
    finally:
        if window.search_worker and window.search_worker.isRunning():
            window.search_worker.wait(30000)
        window.close()


def test_command_argument_prompt_and_vim_colon(app):
    window = MainWindow()
    try:
        window.command_input.setText("find")
        window.execute_gui_command()
        assert window.pending_command == "find"
        assert window.command_label.text() == "find:"
        window.command_input.setText("a b c")
        window.execute_gui_command()
        assert window.pending_command is None
        assert window.find_input.text() == "a b c"
        window.command_input.setText("search")
        window.execute_gui_command()
        window.command_input.clear()
        window.execute_gui_command()
        assert window.pending_command is None
    finally:
        window.close()


def test_read_only_vim_moves_without_editing(app, tmp_path):
    path = tmp_path / "sample.txt"
    path.write_text("一\n二\n三\n", encoding="utf-8")
    reader = TextReader(path)
    reader.show()
    reader.setFocus()
    app.processEvents()
    try:
        QTest.keyClicks(reader, "jj")
        assert reader.textCursor().blockNumber() == 2
        QTest.keyClicks(reader, "gg")
        assert reader.textCursor().blockNumber() == 0
        QTest.keyClicks(reader, "G")
        assert reader.textCursor().blockNumber() >= 2
        QTest.keyClicks(reader, "aicr")
        assert reader.toPlainText() == "一\n二\n三\n"
    finally:
        reader.close()


def test_markdown_render_source_and_font_command(app, tmp_path, monkeypatch):
    monkeypatch.setattr(reading, "READING_FILE", tmp_path / "reading.json")
    QImage(4, 4, QImage.Format.Format_RGB32).save(str(tmp_path / "pic.png"))
    path = tmp_path / "sample.md"
    path.write_text("# 章节标题\n\n**加粗** 正文\n\n![图](pic.png)\n", encoding="utf-8")
    reader = MarkdownReader(path)
    try:
        assert reader.formatted
        assert "章节标题" in reader.browser.toPlainText()
        assert "**加粗**" not in reader.browser.toPlainText()
        reader.show()
        app.processEvents()
        image = reader.browser.document().resource(
            QTextDocument.ResourceType.ImageResource, QUrl.fromLocalFile(str(tmp_path / "pic.png")))
        assert image is not None
        reader.browser.moveCursor(QTextCursor.MoveOperation.End)
        QTest.keyClicks(reader.browser, "gg")
        assert reader.browser.textCursor().position() == 0
        reader.set_formatted(False)
        assert "**加粗**" in reader.toPlainText()
        reader.set_formatted(True)
        reader.jump(3)
        assert not reader.formatted
        assert reader.textCursor().blockNumber() == 2
    finally:
        reader.close()

    window = MainWindow()
    try:
        window.open_resource(RESOURCES_DIR / "README.md")
        assert isinstance(window.tabs.currentWidget(), MarkdownReader)
        assert window.tabs.currentWidget().formatted
        window.command_input.setText("font size 18")
        window.execute_gui_command()
        assert window.reader_font_size == 18
        assert window.tabs.currentWidget().font().pointSizeF() == 18
        window.markdown_action.setChecked(False)
        assert not window.tabs.currentWidget().formatted
        window.markdown_action.setChecked(True)
        assert window.tabs.currentWidget().formatted
    finally:
        window.close()


def test_directory_index_and_optional_command_bar(app, tmp_path, monkeypatch):
    monkeypatch.setattr(reading, "READING_FILE", tmp_path / "reading.json")
    window = MainWindow()
    try:
        collected = next(window.tree.topLevelItem(i) for i in range(window.tree.topLevelItemCount())
                         if window.tree.topLevelItem(i).text(0) == "下载")
        text_root = next(collected.child(i) for i in range(collected.childCount())
                         if collected.child(i).text(0) == "PRTS 文本")
        avg = next(text_root.child(i) for i in range(text_root.childCount())
                   if text_root.child(i).text(0) == "剧情")
        window.click_tree_item(avg, 0)
        assert window.current_path == RESOURCES_DIR / "collected" / "prts_text" / "avg" / "_索引.md"
        window.command_action.trigger()
        window.command_input.setText("jump 2")
        window.execute_gui_command()
        assert window.tabs.currentWidget().textCursor().blockNumber() == 1
        window.command_action.trigger()
        reader = window.tabs.currentWidget()
        reader.setFocus()
        QTest.keyClicks(reader, "gg")
        assert reader.textCursor().blockNumber() == 0
    finally:
        window.close()
