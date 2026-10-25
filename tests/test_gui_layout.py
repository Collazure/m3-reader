"""GUI layout smoke tests: side docks stay hidden until requested."""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from prts_tool.gui import MainWindow, TextReader
from prts_tool.paths import RESOURCES_DIR


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
