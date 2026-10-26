"""Choose and validate the resource library before importing path-bound GUI modules."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .resource_settings import configured_root, initialize_resources, save_resources


def _project_dir() -> Path:
    if os.environ.get("M3_READER_HOME"):
        return Path(os.environ["M3_READER_HOME"]).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent.parent.parent
    return Path(__file__).resolve().parent.parent


def main() -> int:
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

    app = QApplication.instance() or QApplication(sys.argv)
    default = _project_dir() / "resources"
    override = os.environ.get("M3_READER_RESOURCES")
    configured = configured_root()
    selected = Path(override).expanduser().resolve() if override else configured
    first_run = selected is None
    if selected is None:
        choice = QMessageBox.question(
            None, "首次使用 · resources 目录",
            f"资料默认保存在：\n{default}\n\n是否选择其他 resources 目录？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.No)
        if choice == QMessageBox.StandardButton.Cancel:
            return 0
        if choice == QMessageBox.StandardButton.Yes:
            name = QFileDialog.getExistingDirectory(None, "选择 resources 目录", str(default.parent))
            if not name:
                return 0
            selected = Path(name)
        else:
            selected = default
    while True:
        try:
            if not selected.exists() and not first_run:
                raise ValueError(f"已配置的 resources 目录不存在：{selected}")
            count = initialize_resources(selected)
            if not override:
                save_resources(selected)
            if first_run and count:
                QMessageBox.information(None, "已有资源", f"检测到 {count} 个现有文件，将继续使用并保留它们。")
            break
        except (OSError, ValueError) as exc:
            QMessageBox.warning(None, "resources 目录无效", str(exc))
            name = QFileDialog.getExistingDirectory(None, "重新选择 resources 目录", str(default.parent))
            if not name:
                return 1
            selected = Path(name)
            override = None
            first_run = True
    from .gui import main as gui_main
    return gui_main(app=app)


if __name__ == "__main__":
    raise SystemExit(main())
