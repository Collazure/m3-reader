#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Legacy avg entry point; prefer ``python prts_crawler.py avg``."""

from __future__ import annotations

import sys

from prts_tool.cli import main


def translate(argv: list[str]) -> list[str]:
    out = ["avg"]
    index = 0
    while index < len(argv):
        option = argv[index]
        if option == "--refresh":
            out += ["-m", "missing"]
        elif option == "--force":
            out += ["-m", "force"]
        elif option in {"-g", "--group"}:
            out.append("-g")
            if index + 1 < len(argv):
                index += 1
                out.append(argv[index])
        else:
            out.append(option)
        index += 1
    return out


if __name__ == "__main__":
    raise SystemExit(main(translate(sys.argv[1:])))
