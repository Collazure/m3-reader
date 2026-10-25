#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PRTS 文本采集工具的入口（click 命令行）。

    python prts_crawler.py --help              # 查看全部命令
    python prts_crawler.py info                # 各模块说明与输出布局
    python prts_crawler.py all                 # 全量采集（avg → stage → operator → furniture）
    python prts_crawler.py refresh -m avg      # 只刷新 avg 剧情
    python prts_crawler.py fetch raw 锡兰       # 通用抓取接口

依赖：click（`python -m pip install click`）。
"""

from __future__ import annotations

import sys


def _bootstrap() -> None:
    """在脚本目录下也能直接 import prts_tool。"""
    from pathlib import Path
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)


_bootstrap()

try:
    import click  # noqa: F401
except ImportError:  # pragma: no cover
    sys.stderr.write(
        "缺少依赖 click。请先安装：\n"
        "    python -m pip install click\n"
        "（本机也可以用 Anaconda 的 python：D:\\Dprograms\\Anaconda\\python.exe，它自带 click）\n"
    )
    raise SystemExit(2)

from prts_tool.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
