#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wikitext 解析小工具：模板参数、章节切片、标记清理。"""

from __future__ import annotations

import html
import re


def balanced(text: str, start: int) -> str | None:
    """从 text[start:start+2] == '{{' 开始，返回配对完整的片段。"""
    depth, i, n = 0, start, len(text)
    while i < n - 1:
        two = text[i:i + 2]
        if two == "{{":
            depth += 1
            i += 2
            continue
        if two == "}}":
            depth -= 1
            i += 2
            if depth == 0:
                return text[start:i]
            continue
        i += 1
    return None


def split_params(inner: str) -> dict[str, str]:
    """把模板内部（去掉 {{ }}）按顶层 `|` 拆成参数字典。"""
    parts: list[str] = []
    buf: list[str] = []
    curly = square = 0
    i, n = 0, len(inner)
    while i < n:
        two = inner[i:i + 2]
        if two == "{{":
            curly += 1
            buf.append(two)
            i += 2
            continue
        if two == "}}":
            curly -= 1
            buf.append(two)
            i += 2
            continue
        if two == "[[":
            square += 1
            buf.append(two)
            i += 2
            continue
        if two == "]]":
            square -= 1
            buf.append(two)
            i += 2
            continue
        c = inner[i]
        if c == "|" and curly == 0 and square == 0:
            parts.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    parts.append("".join(buf))

    out: dict[str, str] = {}
    pos = 1
    for k, part in enumerate(parts):
        if k == 0 and "=" not in part:
            continue                        # 模板名
        if "=" not in part:
            out[str(pos)] = part.strip()
            pos += 1
            continue
        key, _, val = part.partition("=")
        out[key.strip()] = val.strip()
    return out


def template_params(text: str, name: str) -> list[dict[str, str]]:
    """抽取 text 中所有 `{{name|k=v|...}}` 的参数（按出现顺序）。"""
    out: list[dict[str, str]] = []
    pat = re.compile(r"\{\{\s*" + re.escape(name) + r"\s*(?=[|}\n])")
    for m in pat.finditer(text):
        body = balanced(text, m.start())
        if body is None:
            continue
        inner = body[2:-2] if body.endswith("}}") else body[2:]
        out.append(split_params(inner))
    return out


def iter_templates(text: str, name: str | None = None, nested: bool = False):
    """遍历 text 中的 {{模板}}，yield (起始位置, 模板体)。

    nested=False：跳过整个外层模板（不进入其内部）；
    nested=True ：继续向内扫描，可以取到嵌在别的模板里的子模板
                  （例如 {{ISEvent|…{{ISEvent/scene|…}}…}}）。
    """
    i, n = 0, len(text)
    while True:
        s = text.find("{{", i)
        if s < 0:
            return
        body = balanced(text, s)
        if body is None:
            return
        tname = body[2:].split("|", 1)[0].split("}}")[0].strip()
        if name is None or tname == name:
            yield s, (body[2:-2] if body.endswith("}}") else body[2:])
        i = s + 2 if nested else s + len(body)


def section_text(raw: str, heading: str) -> str | None:
    """按二级/三级标题从 wikitext 里粗略切出一节（找不到返回 None）。"""
    h = heading.strip().strip("=")
    m = re.search(r"^(={2,4})\s*" + re.escape(h) + r"\s*\1\s*$", raw, re.M)
    if not m:
        return None
    level = len(m.group(1))
    start = m.end()
    nxt = re.search(r"^={2,%d}[^=]" % level, raw[start:], re.M)
    return raw[start:start + (nxt.start() if nxt else len(raw))]


# ---------------------------------------------------------------- 标记清理
# 支持 [[页面]]、[[页面|显示名]]、[[文件:xxx|缩略图|说明]] 等多段写法，
# 取最后一个非空段作为可读文本。
WIKI_LINK_RE = re.compile(r"\[\[(?:[^\]\|]*\|)*([^\]\|]*)\]\]")
SIMPLE_TPL_RE = re.compile(r"\{\{[^{}]*\}\}")


def strip_templates(text: str, drop: tuple[str, ...] = (), drop_parser: bool = False) -> str:
    """删除指定名字的模板（含参数）。

    drop_parser=True 时一并删掉所有解析器函数（`{{#var:xxx}}`、`{{#if:…}}` 等）。
    """
    pats = [re.escape(d) for d in drop]
    if drop_parser:
        pats.append(r"#[^|}\s]*")
    if not pats:
        return text
    pat = re.compile(r"\{\{\s*(?:" + "|".join(pats) + r")\s*[|}:]")
    out: list[str] = []
    i = 0
    while True:
        m = pat.search(text, i)
        if not m:
            out.append(text[i:])
            break
        out.append(text[i:m.start()])
        body = balanced(text, m.start())
        i = m.start() + (len(body) if body else 2)
    return "".join(out)


def unwrap_templates(text: str, names: tuple[str, ...]) -> str:
    """把 `{{name|正文}}` 换成正文（保留内容，去掉外壳）。"""
    if not names:
        return text
    pat = re.compile(r"\{\{\s*(?:" + "|".join(re.escape(n) for n in names) + r")\s*[|}]")
    out: list[str] = []
    i = 0
    while True:
        m = pat.search(text, i)
        if not m:
            out.append(text[i:])
            break
        out.append(text[i:m.start()])
        body = balanced(text, m.start())
        if body is None:
            i = m.end()
            continue
        inner = body[2:-2] if body.endswith("}}") else body[2:]
        parts = inner.split("|", 1)
        out.append(parts[1] if len(parts) > 1 else inner)   # 去掉模板名，保留正文
        i = m.start() + len(body)
    return "".join(out)


def clean_markup(text: str) -> str:
    """把正文里残余的 wiki / 富文本标记清掉，保留可读文本。"""
    if not text:
        return ""
    # 文件 / 分类链接整段丢掉（否则会留下「64px」「link=」之类的参数）
    text = re.sub(r"\[\[(?:文件|File|Image|分类|Category):[^\]]*\]\]", "", text, flags=re.I)
    text = WIKI_LINK_RE.sub(r"\1", text)
    text = SIMPLE_TPL_RE.sub(lambda m: m.group(0)[2:-2].split("|")[-1], text)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</>|<p\s*=\s*\d+\s*>", "", text, flags=re.I)
    text = re.sub(r"</?[a-zA-Z][^>]*>", "", text)
    text = text.replace("'''", "").replace("''", "")
    text = html.unescape(text)
    text = text.replace("\\n", "\n")
    return text


def plain_text(text: str) -> str:
    """清标记 + 压掉多余空行，得到可直接写进 txt 的纯文本。"""
    text = clean_markup(text)
    lines = [ln.strip() for ln in text.split("\n")]
    out: list[str] = []
    for ln in lines:
        if ln or (out and out[-1]):
            out.append(ln)
    return "\n".join(out).strip()


def flavor_text(text: str, with_conditions: bool = False) -> str:
    """取文本里的「风味描述」部分。

    PRTS 常把风味文本和机制说明拼在一起，机制说明用 `{{color|…}}` 标注，
    并且用 <br/> 或换行分隔，例如：

        “我宣传的并非完全严肃的道德。”<br/>{{color|#FFFFFF|<泄漏标记>}}每过一段时间…

    这里在第一个 {{color|…}} 处截断，只留下风味文本（--with-conditions 可保留全部）。
    """
    if not text:
        return ""
    normalized = re.sub(r"<br\s*/?>", "\n", text)
    keep: list[str] = []
    for seg in normalized.split("\n"):
        if not with_conditions and seg.strip().startswith("{{color"):
            break
        keep.append(seg)
    out = plain_text("\n".join(keep))
    return out or plain_text(text)
