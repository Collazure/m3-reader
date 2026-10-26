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
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    default = _project_dir() / "resources"
    override = os.environ.get("M3_READER_RESOURCES")
    configured = configured_root()
    selected = Path(override).expanduser().resolve() if override else configured
    first_run = selected is None
    if first_run:
        # A modal dialog without an owning window can crash some Qt/Windows
        # desktops before the reader has had a chance to show itself.
        # The library can still be changed from 导入 → resources 目录.
        selected = default
    try:
        if not selected.exists() and not first_run:
            raise ValueError(f"已配置的 resources 目录不存在：{selected}")
        initialize_resources(selected)
        if not override and not first_run:
            save_resources(selected)
    except (OSError, ValueError) as exc:
        print(f"resources 目录无效：{exc}", file=sys.stderr)
        return 1
    from .gui import main as gui_main
    return gui_main(app=app)


if __name__ == "__main__":
    raise SystemExit(main())
