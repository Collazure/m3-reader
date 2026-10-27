"""Line-preserving terminal preview for Markdown resources."""

from __future__ import annotations

import re
import unicodedata

_IMAGE = re.compile(r"!\[([^]]*)\]\(([^)]+)\)")
_LINK = re.compile(r"\[([^]]+)\]\(([^)]+)\)")
_FENCE = re.compile(r"^\s*(```|~~~)")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+)$")
_QUOTE = re.compile(r"^\s*>\s?(.*)$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(.+)$")
_TABLE_RULE = re.compile(r"^\s*\|?[\s:|-]+\|\s*$")
_TABLE_DELIMITER = re.compile(r"^:?-{3,}:?$")


def display_width(text: str) -> int:
    """Count terminal cells rather than Python characters (CJK occupies two)."""
    return sum(0 if unicodedata.combining(char) else
               2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1
               for char in text)


def _table_cells(line: str) -> list[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith(r"\|"):
        body = body[:-1]
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for char in body:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "|":
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if escaped:
        current.append("\\")
    cells.append("".join(current).strip())
    return cells


def _is_table_delimiter(line: str, columns: int) -> bool:
    cells = _table_cells(line)
    return len(cells) == columns and all(_TABLE_DELIMITER.fullmatch(cell) for cell in cells)


def _inline_preview(text: str) -> str:
    text = _IMAGE.sub(lambda match: f"[图片: {match.group(1)}] {match.group(2)}", text)
    text = _LINK.sub(lambda match: f"{match.group(1)} <{match.group(2)}>", text)
    text = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda match: match.group(1) or match.group(2), text)
    text = re.sub(r"(?<!\*)\*([^*\s][^*]*?)\*(?!\*)", r"\1", text)
    text = re.sub(r"(?<!\x60)\x60([^\x60]+)\x60(?!\x60)", r"\1", text)
    return re.sub(r"~~(.+?)~~", r"\1", text)


def _wrap_cell(text: str, width: int) -> list[str]:
    parts = []
    current = ""
    for char in text:
        if current and display_width(current + char) > width:
            parts.append(current)
            current = ""
        current += char
    parts.append(current)
    return parts


def _render_table(rows: list[str], max_width: int | None = None) -> list[list[str]]:
    columns = len(_table_cells(rows[0]))
    alignment = [("center" if cell.startswith(":") and cell.endswith(":")
                  else "right" if cell.endswith(":") else "left")
                 for cell in _table_cells(rows[1])]
    cells = [[_inline_preview(cell) for cell in _table_cells(row)] for row in rows]
    widths = [max(3, *(display_width(row[index]) for row in cells if index < len(row)))
              for index in range(columns)]
    if max_width is not None:
        available = max(columns * 2, max_width - (3 * columns + 1))
        while sum(widths) > available and max(widths) > 2:
            widest = max(range(columns), key=lambda index: widths[index])
            widths[widest] -= 1
    result: list[list[str]] = []
    for number, row in enumerate(cells):
        if number == 1:
            result.append(["├" + "┼".join("─" * (width + 2) for width in widths) + "┤"])
            continue
        wrapped = [_wrap_cell(cell, width) for cell, width in zip(row, widths)]
        wrapped.extend([[""]] for _ in widths[len(wrapped):])
        height = max(map(len, wrapped))
        rendered_rows = []
        for line in range(height):
            padded = [(column[line] if line < len(column) else "") for column in wrapped]
            aligned = []
            for cell, width, mode in zip(padded, widths, alignment):
                gap = width - display_width(cell)
                left = gap if mode == "right" else gap // 2 if mode == "center" else 0
                aligned.append(" " * left + cell + " " * (gap - left))
            padded = aligned
            rendered_rows.append("│ " + " │ ".join(padded) + " │")
        result.append(rendered_rows)
    return result


def _table_previews(raw_lines: list[str], max_width: int | None = None) -> dict[int, list[str]]:
    """Map source row numbers to aligned display rows outside code blocks."""
    previews: dict[int, list[str]] = {}
    in_code = False
    index = 0
    while index < len(raw_lines):
        body = raw_lines[index].rstrip("\r\n")
        if _FENCE.match(body):
            in_code = not in_code
            index += 1
            continue
        if not in_code and "|" in body and index + 1 < len(raw_lines):
            columns = len(_table_cells(body))
            delimiter = raw_lines[index + 1].rstrip("\r\n")
            if columns >= 2 and _is_table_delimiter(delimiter, columns):
                end = index + 2
                while end < len(raw_lines):
                    row = raw_lines[end].rstrip("\r\n")
                    if "|" not in row or len(_table_cells(row)) != columns:
                        break
                    end += 1
                aligned = _render_table([line.rstrip("\r\n") for line in raw_lines[index:end]], max_width)
                for row_index, display in enumerate(aligned, index):
                    raw = raw_lines[row_index]
                    newline = raw[len(raw.rstrip("\r\n")):]
                    previews[row_index] = [line + ("\n" if part < len(display) - 1 else newline)
                                           for part, line in enumerate(display)]
                index = end
                continue
        index += 1
    return previews


def render_terminal_markdown_with_map(
    source: str, *, table_width: int | None = None
) -> tuple[str, list[int]]:
    """Render Markdown and map every display line back to its source line."""
    result = []
    line_map: list[int] = []
    in_code = False
    raw_lines = source.splitlines(keepends=True)
    previews = _table_previews(raw_lines, table_width)
    for index, raw in enumerate(raw_lines):
        if index in previews:
            result.extend(previews[index])
            line_map.extend([index + 1] * len(previews[index]))
            continue
        line_map.append(index + 1)
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
    return "".join(result), line_map


def render_terminal_markdown(source: str) -> str:
    """Line-preserving default preview; TUI may request wrapped tables."""
    return render_terminal_markdown_with_map(source)[0]
