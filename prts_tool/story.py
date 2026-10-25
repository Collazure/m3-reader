#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""剧情脚本（{{剧情模拟器}} 的 文本数据=）解析。

脚本 DSL 的行格式：
    [Cmd(arg=val, ...)]         演出指令
    [name="角色"]  台词          带说话人的台词（[name=""] 表示无名旁白）
    [multiline(name="角色")] 台词 多行台词
    [Cmd="值"]                  少数指令写成这样（如 [name="X"]）
    [Subtitle(text="…")]        电影式字幕
    [Sticker(text="…")]         屏幕上的贴纸文字（地点名等）
    [animtext(...)]<p=1>文字</> 屏幕文字
    [Decision(options="A;B")]   选项
    [HEADER(...)] 小标题        小节标题
    [Dialog]                    场景分隔
    纯文本行                     旁白
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .wikitext import clean_markup

# ---------------------------------------------------------------- 指令解析


def split_directive(line: str):
    """若形如 [xxx(...)] 正文 或 [xxx="值"] 正文，返回 (指令名, 参数串, 正文)。"""
    if not line.startswith("["):
        return None
    depth, quote = 0, None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in "\"'“”":
            quote = ch
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "]" and depth <= 0:
            head, rest = line[1:i], line[i + 1:].strip()
            m = re.match(r"^([A-Za-z_][\w]*)\s*(?:\((.*)\))?$", head, re.S)
            if m:
                return m.group(1), (m.group(2) or ""), rest
            m = re.match(r"^([A-Za-z_][\w]*)\s*=\s*(.+)$", head, re.S)
            if m:
                return m.group(1), f"{m.group(1)}={m.group(2)}", rest
            return None
    return None


def get_param(params: str, key: str) -> str | None:
    """从参数串里取值，支持带引号/不带引号。"""
    m = re.search(r'(?:^|[\s,])' + re.escape(key) + r'\s*=\s*("([^"]*)"|\'([^\']*)\'|([^,\s\)]+))', params)
    if not m:
        return None
    for g in (2, 3, 4):
        if m.group(g) is not None:
            return m.group(g)
    return None


@dataclass
class Line:
    kind: str        # dialogue / narration / title / note / choice / break / directive
    speaker: str
    text: str


def parse_script(script: str, keep_directives: bool = False) -> list[Line]:
    """把「文本数据=」里的演出脚本解析成台词/旁白序列。"""
    lines: list[Line] = []
    pending: str | None = None

    for raw in script.splitlines():
        line = clean_markup(raw).strip()
        if not line:
            continue
        parsed = split_directive(line)
        if parsed:
            name, params, rest = parsed
            low = name.lower()
            if low in ("name", "multiline"):
                speaker = (get_param(params, "name") or "").strip()
                if rest:
                    lines.append(Line("dialogue", speaker, rest))
                    pending = None
                else:
                    pending = speaker
            elif low == "subtitle":
                text = get_param(params, "text")
                if text:
                    lines.append(Line("narration", "", clean_markup(text).strip()))
            elif low == "header":
                if rest:
                    lines.append(Line("title", "", rest))
            elif low == "sticker":
                text = get_param(params, "text")
                if text:
                    lines.append(Line("note", "", clean_markup(text).strip()))
            elif low == "animtext":
                if rest:
                    lines.append(Line("note", "", rest))
            elif low == "decision":
                options = get_param(params, "options")
                if options:
                    lines.append(Line("choice", "", " / ".join(re.split(r"[;；]", options))))
            elif low == "dialog":
                lines.append(Line("break", "", ""))
            elif keep_directives:
                lines.append(Line("directive", "", line))
            continue

        if pending is not None:
            lines.append(Line("dialogue", pending, line))
            pending = None
        else:
            lines.append(Line("narration", "", line))
    return lines


def render(lines: list[Line], fmt: str = "dialogue", merge_speaker: bool = False) -> str:
    """渲染成文本。fmt: dialogue（带角色名）/ plain（纯文本）。"""
    out: list[str] = []
    last: str | None = None

    def push(text: str, prefix: str = "") -> None:
        for part in str(text).split("\n"):
            out.append((prefix + part).rstrip())

    for ln in lines:
        if ln.kind == "break":
            if out and out[-1] != "":
                out.append("")
            last = None
        elif ln.kind == "title":
            push(f"【{ln.text}】")
            last = None
        elif ln.kind == "choice":
            push(f"（选项：{ln.text}）")
            last = None
        elif ln.kind == "note":
            parts = [p for p in ln.text.split("\n") if p.strip()]
            push("\n".join(parts) if len(parts) > 1 else f"〔{ln.text.strip()}〕")
            last = None
        elif ln.kind == "directive":
            push(ln.text)
        elif ln.kind == "narration":
            push(ln.text)
            last = None
        else:
            if fmt == "plain" or not ln.speaker:
                push(ln.text)
                last = ln.speaker or None
            elif merge_speaker:
                if ln.speaker != last:
                    if out and out[-1] != "":
                        out.append("")
                    out.append(f"{ln.speaker}：")
                    last = ln.speaker
                push(ln.text, prefix="　　")
            else:
                push(f"{ln.speaker}：{ln.text}")
                last = ln.speaker

    rendered: list[str] = []
    for line in out:
        if line == "" and (not rendered or rendered[-1] == ""):
            continue
        rendered.append(line)
    return "\n".join(rendered).strip() + "\n"


# ---------------------------------------------------------------- 跨页引用

SECTION_RE = re.compile(
    r'<section\s+begin\s*=\s*"?([^"/>\s]+)"?\s*/?>(.*?)<section\s+end\s*=\s*"?\1"?\s*/?>', re.S)
LST_RE = re.compile(
    r"\{\{\s*#(?:lst|lstx|section|section-h|section-x)\s*:\s*([^|}\[]+?)\s*\|\s*([^|}]+?)\s*\}\}")
TRANSCLUDE_RE = re.compile(r"\{\{\s*:\s*([^|}]+?)\s*\}\}")


def resolve_transclusions(text: str, fetch, log=print, depth: int = 0, cache: dict | None = None,
                          page_title: str = "") -> str:
    """展开 {{#lst:页面|小节}} 与 {{:页面}} 引用。

    少数剧情页把正文放在子页面里（`{{:{{PAGENAME}}/data}}`），
    所以这里先把 {{PAGENAME}} 换成当前页面标题。
    """
    if page_title:
        text = text.replace("{{PAGENAME}}", page_title).replace("{{FULLPAGENAME}}", page_title)
    if depth >= 3 or ("#lst" not in text and "#section" not in text and "{{:" not in text):
        return text
    cache = cache if cache is not None else {}

    def get(title: str) -> str:
        key = title.replace("_", " ").strip()
        if key not in cache:
            log(f"    · 展开引用：{key}")
            cache[key] = fetch(key)
        return cache[key]

    def lst(m: re.Match) -> str:
        page, section = m.group(1).strip(), m.group(2).strip()
        src = get(page)
        for sm in SECTION_RE.finditer(src):
            if sm.group(1).strip() == section:
                return sm.group(2)
        log(f"    ! 未能定位小节 {page}#{section}")
        return ""

    text = LST_RE.sub(lst, text)
    text = TRANSCLUDE_RE.sub(lambda m: get(m.group(1)), text)
    return resolve_transclusions(text, fetch, log, depth + 1, cache, page_title)


# ---------------------------------------------------------------- 页面级抽取

@dataclass
class StoryDoc:
    blocks: list[tuple[str, str]] = field(default_factory=list)   # (文本路径, 渲染后的正文)
    meta: dict[str, str] = field(default_factory=dict)


def extract_story(content: str, fetch=None, log=print, keep_directives: bool = False,
                   fmt: str = "dialogue", merge_speaker: bool = False, page_title: str = "") -> StoryDoc:
    """从一个页面的 wikitext 中抽出所有 {{剧情模拟器}} 的剧本正文。"""
    from .wikitext import template_params
    doc = StoryDoc()
    for _pos, body in _iter_simulator(content):
        meta: dict[str, str] = {}
        for key in ("剧情类型", "剧情分组", "文本路径"):
            m = re.search(r"\|\s*" + key + r"\s*=\s*([^|}\n]*)", body)
            if m:
                meta[key] = m.group(1).strip()
        for k, v in meta.items():
            doc.meta.setdefault(k, v)
        m = re.search(r"\|\s*文本数据\s*=", body)
        if not m:
            continue
        script = body[m.end():]
        if fetch is not None:
            script = resolve_transclusions(script, fetch, log, page_title=page_title)
        lines = parse_script(script, keep_directives=keep_directives)
        text = render(lines, fmt=fmt, merge_speaker=merge_speaker)
        if text.strip():
            doc.blocks.append((meta.get("文本路径", ""), text))
    return doc


def _iter_simulator(content: str):
    """yield (位置, {{剧情模拟器}} 的模板体)。"""
    from .wikitext import iter_templates
    yield from iter_templates(content, "剧情模拟器")
