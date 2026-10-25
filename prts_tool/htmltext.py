#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 MediaWiki 渲染后的 HTML 转成便于检索的纯文本。

活动页（活动公告、综合调查数据库、审判庭纪要等）大量使用表格、折叠框和
HTML 样式，直接清理 wikitext 会留下 `{|`、`style=` 之类的噪声。走
`api.php?action=parse&prop=text` 拿渲染结果，再用本模块的解析器取正文：

    from .http import PrtsClient
    from .htmltext import html_to_text

    data = client.api(action="parse", page="孤星/综合调查数据库", prop="text")
    text = html_to_text(data["parse"]["text"])

解析器只做「块级换行 + 丢掉界面元素」，不试图还原排版；输出适合全文检索。
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser

# 这些标签本身不产生正文
SKIP_TAGS = {"style", "script", "noscript", "sup"}

# 这些类名/ id 是 MediaWiki 的界面元素（目录、编辑链接、导航框……）
DROP_CLASSES = {
    "mw-editsection", "toc", "navbox", "noprint", "mw-jump-link",
    "printfooter", "catlinks", "mw-empty-elt", "reference",
}
DROP_IDS = {"toc"}

# 会被换成换行的块级标签
BLOCK_TAGS = {
    "p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
    "hr", "center", "table", "section", "blockquote", "ul", "ol", "dl",
    "dt", "dd", "pre", "figure", "figcaption", "article", "header", "footer",
}

# 渲染结果里的固定噪声（音频播放器降级提示、折叠按钮、目录等）
NOISE_LINES = {
    "请升级浏览器。", "编辑", "[编辑]", "（编辑）", "跳转到导航", "跳转到搜索",
    "目录", "展开", "收起", "展开收起", "展开/收起",
}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.stack: list[tuple[str, bool]] = []
        self.skip = 0

    # -- HTMLParser 回调 -------------------------------------------------
    def handle_starttag(self, tag: str, attrs) -> None:
        attrs = dict(attrs)
        classes = (attrs.get("class") or "").split()
        skip = (tag in SKIP_TAGS
                or any(c in DROP_CLASSES for c in classes)
                or attrs.get("id") in DROP_IDS)
        self.stack.append((tag, skip))
        if skip:
            self.skip += 1
            return
        if tag in BLOCK_TAGS:
            self.out.append("\n")
        if tag in ("td", "th"):
            self.out.append(" | ")

    def handle_startendtag(self, tag: str, attrs) -> None:
        if tag == "br":
            self.out.append("\n")

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                skip = self.stack[i][1]
                del self.stack[i:]
                if skip and self.skip:
                    self.skip -= 1
                break
        if self.skip:
            return
        if tag in BLOCK_TAGS:
            self.out.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.out.append(data)


def _clean_lines(text: str) -> str:
    text = html.unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        line = re.sub(r"^\s*[|｜]\s*", "", line).strip()
        line = re.sub(r"\s*[|｜]\s*$", "", line).strip()
        line = line.replace("请升级浏览器。", "").strip()
        line = re.sub(r"\s*\[编辑\]\s*$", "", line).strip()
        if not line or line in NOISE_LINES:
            continue
        if re.fullmatch(r"[|\-–—·•\s]+", line):
            continue
        lines.append(line)
    out: list[str] = []
    for line in lines:
        if not line and out and not out[-1]:
            continue
        out.append(line)
    return "\n".join(out).strip()


def html_to_text(fragment: str) -> str:
    """渲染后的 HTML 片段 → 纯文本（保留段落/标题/表格单元格顺序）。"""
    parser = _TextExtractor()
    parser.feed(fragment or "")
    parser.close()
    return _clean_lines("".join(parser.out))
