"""Line-preserving terminal preview for Markdown resources."""

from __future__ import annotations

import re

_IMAGE = re.compile(r"!\[([^]]*)\]\(([^)]+)\)")
_LINK = re.compile(r"\[([^]]+)\]\(([^)]+)\)")
_FENCE = re.compile(r"^\s*(```|~~~)")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+)$")
_QUOTE = re.compile(r"^\s*>\s?(.*)$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(.+)$")
_TABLE_RULE = re.compile(r"^\s*\|?[\s:|-]+\|\s*$")


def render_terminal_markdown(source: str) -> str:
    """Improve terminal readability without changing line numbers or code blocks."""
    result = []
    in_code = False
    for raw in source.splitlines(keepends=True):
        body = raw.rstrip("\r\n")
        newline = raw[len(body):]
        if _FENCE.match(body):
            in_code = not in_code
            label = body.strip().strip("`~").strip()
            result.append(("── " + (label or "代码") + " ──") + newline)
            continue
        if in_code:
            result.append(raw)
            continue
        if match := _HEADING.match(body):
            body = "▸ " + match.group(1)
        elif match := _QUOTE.match(body):
            body = "│ " + match.group(1)
        elif match := _BULLET.match(body):
            body = match.group(1) + "• " + match.group(2)
        elif _TABLE_RULE.fullmatch(body) and "-" in body:
            body = "─" * max(8, min(60, len(body)))
        elif body.strip() in {"---", "***", "___"}:
            body = "─" * 30
        body = _IMAGE.sub(lambda match: f"[图片: {match.group(1)}] {match.group(2)}", body)
        body = _LINK.sub(lambda match: f"{match.group(1)} <{match.group(2)}>", body)
        body = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda match: match.group(1) or match.group(2), body)
        body = re.sub(r"(?<!\*)\*([^*\s][^*]*?)\*(?!\*)", r"\1", body)
        body = re.sub(r"(?<!`)`([^`]+)`(?!`)", r"\1", body)
        body = re.sub(r"~~(.+?)~~", r"\1", body)
        result.append(body + newline)
    return "".join(result)
