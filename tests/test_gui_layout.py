"""GUI layout smoke tests: side docks stay hidden until requested."""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from prts_tool.gui import CommandLine, MainWindow, TextReader
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
        assert labels[:4] == ["导入", "阅读", "工具", "视图"]
        assert window.menuBar().cornerWidget() is not None
        assert not window.windowIcon().isNull()
        assert window.command_dock.isHidden()
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


def test_directory_index_and_optional_command_bar(app, tmp_path, monkeypatch):
    monkeypatch.setattr(reading, "READING_FILE", tmp_path / "reading.json")
    window = MainWindow()
    try:
        collected = next(window.tree.topLevelItem(i) for i in range(window.tree.topLevelItemCount())
                         if window.tree.topLevelItem(i).text(0) == "collected")
        text_root = next(collected.child(i) for i in range(collected.childCount())
                         if collected.child(i).text(0) == "prts_text")
        avg = next(text_root.child(i) for i in range(text_root.childCount())
                   if text_root.child(i).text(0) == "avg")
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
