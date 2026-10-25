#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生息演算（Reclamation Algorithm）文本采集器。

输出：OUT/reclamation/<主题>/<序号> <剧情名>.txt（与 avg / roguelike 同级）

主题：沙中之火（RA）、沙洲遗闻（RA1）、重启锚点（RA2）。

生息演算的剧情页和普通剧情页格式一样（`{{剧情模拟器}}`），
只是它们不该混在 avg 里，所以单独一个模块、单独一棵目录树。
索引同样每次运行都重新从 wiki 构建（`Template:剧情导航` + `分类:剧情`），
以后新增的生息演算场次会自动出现。
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from urllib.parse import quote

from ..http import BASE
from ..output import Manifest, natural_key, sanitize, signature, write_text
from ..registry import Collector, Context, Stat, need_update, register
from ..story import extract_story
from ..wikitext import plain_text, template_params
from .avg import NAV_PAGE, STORY_CATEGORY, build_index, make_raw_fetcher, parse_nav_tables
from .roguelike import split_sections

MODULE_DIR = "reclamation"
EVENT_DIR = "事件"
EVENT_LIST = "事件一览"
# 生息演算各场次（首个场次「沙中之火」在导航表里被标成支线，只能按分组名识别）
THEMES = ("沙中之火", "沙洲遗闻", "重启锚点")
RA_CATEGORY = "生息演算"
OVERVIEW_PAGE = "生息演算"


def _is_reclamation(item) -> bool:
    return (item.nav_category == RA_CATEGORY
            or item.group in THEMES or item.nav_group in THEMES
            or bool(re.match(r"^RA\d*(-|\s|/|$)", item.title)))


@register
class ReclamationCollector(Collector):
    name = "reclamation"
    title = "生息演算：剧情文本（沙中之火 / 沙洲遗闻 / 重启锚点）"
    help = """把生息演算的剧情文本单独存到自己的目录里（不混在 avg 中）：

\b
    OUT/reclamation/沙中之火/<序号> <剧情名>.txt
    OUT/reclamation/沙洲遗闻/…
    OUT/reclamation/重启锚点/…

每个主题一份 `_索引.md`，`OUT/reclamation/_manifest.json` 记录增量信息。
索引实时从 `Template:剧情导航` + `分类:剧情` 构建，新场次会自动收录。"""
    order = 55

    def run(self, ctx: Context) -> Stat:
        stat = Stat()
        out = ctx.out_dir / MODULE_DIR
        manifest = Manifest(out / "_manifest.json")

        self.header(ctx, "读取生息演算剧情索引")
        nav = ctx.client.pages([NAV_PAGE], with_content=True).get(NAV_PAGE)
        entries = parse_nav_tables(nav.content) if nav and nav.content else []
        items = [it for it in build_index(entries, ctx.client.category(STORY_CATEGORY))
                 if _is_reclamation(it)]
        items = [it for it in items if ctx.match(it.label, it.group, it.nav_group, it.title)]
        if ctx.limit:
            items = items[:ctx.limit]
        ctx.log(f"  待处理 {len(items)} 条")
        # 事件一览与剧情页相互独立，先处理（dry-run 下只统计不写盘）
        self._events(ctx, out, manifest, stat)
        if not items:
            manifest.save()
            if not ctx.dry_run:
                self._write_toc(out, manifest)
            return stat

        ctx.log("  检查版本 …")
        revs = ctx.client.revids([it.title for it in items])
        todo = []
        for it in items:
            rec = revs.get(it.title)
            if rec is None or not rec.revid:
                stat.skipped_empty += 1
                continue
            it.revid, it.timestamp = rec.revid, rec.timestamp
            old = manifest.get(it.title)
            rel = old.get("file") or ""
            if not need_update(ctx, manifest, it.title, str(rec.revid),
                               bool(rel) and (out / rel).exists()):
                it.folder = old.get("folder", "")
                it.filename = Path(rel).name if rel else ""
                stat.skipped += 1
                continue
            todo.append(it)

        if ctx.dry_run:
            for it in todo[:50]:
                ctx.log(f"  · 将抓取 {it.title}")
            stat.dry_run_note = f"{len(todo)} 条待抓取"
            return stat

        ctx.log(f"  需要抓取 {len(todo)} 条")
        if todo:
            pages = ctx.client.pages([it.title for it in todo], with_content=True)
            fetch = make_raw_fetcher(ctx)
            for it in todo:
                rec = pages.get(it.title)
                if rec is None or not rec.content:
                    stat.skipped_empty += 1
                    continue
                doc = extract_story(rec.content, fetch=fetch, page_title=it.title,
                                    log=ctx.log if ctx.verbose else (lambda *_: None),
                                    fmt=ctx.extra.get("fmt", "dialogue"),
                                    merge_speaker=bool(ctx.extra.get("merge_speaker")))
                if not doc.blocks:
                    stat.skipped_empty += 1
                    manifest.record(it.title, str(it.revid), revid=it.revid, file="", folder="",
                                    label=it.label, status="无剧情文本")
                    continue
                theme = doc.meta.get("剧情分组", "") or it.nav_group or it.group or "未分组"
                if theme not in THEMES:
                    theme = it.nav_group if it.nav_group in THEMES else theme
                it.group = theme
                it.folder = sanitize(theme)
                it.filename = sanitize(f"{it.order:04d} {it.label}.txt")
                rel_new = f"{it.folder}/{it.filename}"
                path = out / rel_new
                path.parent.mkdir(parents=True, exist_ok=True)
                write_text(path, self._render(it, doc), ignore_timestamps=True)
                old_rel = (manifest.get(it.title) or {}).get("file", "")
                if old_rel and old_rel != rel_new and (out / old_rel).exists():
                    (out / old_rel).unlink()
                manifest.record(it.title, str(it.revid), revid=it.revid, file=rel_new,
                                folder=it.folder, label=it.label, group=theme,
                                timestamp=it.timestamp, status="已写入")
                stat.written += 1
                if ctx.verbose:
                    ctx.log(f"  + {rel_new}")

        manifest.save()
        self._write_toc(out, manifest)
        return stat

    # ---------------- 事件一览 ----------------
    def _events(self, ctx: Context, out: Path, manifest: Manifest, stat: Stat) -> None:
        """生息演算「事件一览」里的奇遇/远派/集结区/关隘/陌域事件。

        这些页面不是剧情模拟器，reclamation 原来只收剧情页，会把 112 段事件描述
        整个漏掉。事件按 `{{生息演算事件}}` 拆成单个 txt，放在
        `reclamation/<场次>/事件/<分类>/<事件名>.txt`。
        """
        for theme in THEMES:
            page_title = f"{theme}/{EVENT_LIST}"
            rec = ctx.client.pages([page_title], with_content=True).get(page_title)
            if rec is None or not rec.content:
                continue
            events = parse_reclamation_events(rec.content)
            if not events:
                continue
            ctx.log(f"  事件（{theme}）：{len(events)} 个")
            for ev in events:
                if not ctx.match(ev["name"], ev["category"], theme):
                    continue
                rel = f"{sanitize(theme)}/{EVENT_DIR}/{sanitize(ev['category'])}/{sanitize(ev['name'])}.txt"
                path = out / rel
                sig = signature(rec.revid, ev["category"], ev["name"], ev["text"])
                key = f"event:{theme}:{ev['category']}/{ev['name']}"
                if not need_update(ctx, manifest, key, sig, path.exists()):
                    stat.skipped += 1
                    continue
                if ctx.dry_run:
                    continue
                write_text(path, self._render_event(theme, page_title, rec, ev), ignore_timestamps=True)
                manifest.record(key, sig, file=rel, theme=theme, category=ev["category"],
                                name=ev["name"], revid=rec.revid, status="已写入")
                stat.written += 1
                if ctx.verbose:
                    ctx.log(f"  + {rel}")

    @staticmethod
    def _render_event(theme: str, page_title: str, rec, ev: dict) -> str:
        body = [f"# {ev['name']}", "",
                f"- 生息演算：{theme}",
                f"- 事件分类：{ev['category']}",
                f"- 类型：{ev['type'] or '未标注'}",
                f"- 页面：{BASE}/w/{quote(page_title.replace(' ', '_'))}",
                f"- 版本：rev {rec.revid}（{rec.timestamp}）", "",
                f"- 抓取时间：{time.strftime('%Y-%m-%d %H:%M:%S')}", "", "---", ""]
        body += [ev["text"].rstrip(), ""]
        return "\n".join(body).rstrip() + "\n"

    @staticmethod
    def _render(it, doc) -> str:
        body = [f"# {it.label}", "",
                f"- 生息演算：{it.group}",
                f"- 页面：{BASE}/w/{quote(it.title.replace(' ', '_'))}"]
        if doc.meta.get("文本路径"):
            body.append(f"- 文本路径：{doc.meta['文本路径']}")
        body += [f"- 版本：rev {it.revid}（{it.timestamp}）", "",
                 f"- 抓取时间：{time.strftime('%Y-%m-%d %H:%M:%S')}", "", "---", ""]
        for i, (textpath, text) in enumerate(doc.blocks):
            if len(doc.blocks) > 1:
                body += [f"===== 第 {i + 1} 段剧情（{textpath or '未标注'}） =====", ""]
            body += [text.rstrip(), ""]
        return "\n".join(body).rstrip() + "\n"

    @staticmethod
    def _write_toc(out: Path, manifest: Manifest) -> None:
        stories: dict[str, list[str]] = {}
        events: dict[str, list[str]] = {}
        for key, info in manifest.items.items():
            rel = info.get("file")
            if not rel:
                continue
            theme = info.get("theme") or info.get("group") or "未分组"
            if key.startswith("event:"):
                events.setdefault(theme, []).append(
                    f"{info.get('category', '未分类')}/{info.get('name', '')}")
            else:
                stories.setdefault(theme, []).append(Path(rel).name)
        themes = sorted(set(stories) | set(events), key=natural_key)
        lines = ["# PRTS 生息演算文本索引", "",
                 f"生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}　|　"
                 f"{sum(len(v) for v in stories.values())} 段剧情　|　"
                 f"{sum(len(v) for v in events.values())} 个事件　|　{len(themes)} 个场次", "",
                 "> 由 prts_crawler.py reclamation 生成。", ""]
        for theme in themes:
            story_rows = stories.get(theme, [])
            event_rows = events.get(theme, [])
            lines += [f"## {theme}（剧情 {len(story_rows)} / 事件 {len(event_rows)}）", ""]
            if story_rows:
                lines += [f"### 剧情（{len(story_rows)}）", ""]
                lines += [f"- {name[:-4] if name.endswith('.txt') else name}"
                          for name in sorted(story_rows, key=natural_key)]
                lines.append("")
            if event_rows:
                lines += [f"### 事件（{len(event_rows)}）", ""]
                lines += [f"- {name}" for name in sorted(event_rows, key=natural_key)]
                lines.append("")
        write_text(out / "_索引.md", "\n".join(lines), ignore_timestamps=True)


# --------------------------------------------------------------------- 事件解析

def _event_options(raw: str) -> list[str]:
    """把 `{{生息演算事件|选项=…}}` 的选项渲染成可读文本。

    两种写法：
      * 嵌套 `{{生息演算事件/选项|选项1=…|描述1=…|结果1=…}}`（多数事件）；
      * 直接写 `描述1=…` 换行分隔（早期事件）。
    """
    out: list[str] = []
    sets = template_params(raw, "生息演算事件/选项")
    if sets:
        for tpl in sets:
            n = 1
            while any(k in tpl for k in (f"选项{n}", f"描述{n}", f"结果{n}", f"决断{n}")):
                action = plain_text(tpl.get(f"选项{n}", "")).strip()
                desc = plain_text(tpl.get(f"描述{n}", "")).strip()
                result = plain_text(tpl.get(f"结果{n}", "")).strip()
                cost = plain_text(tpl.get(f"决断{n}", "")).strip()
                if action or desc or result:
                    line = [f"· 选项{n}：{action}" if action else f"· 分支{n}"]
                    if cost:
                        line.append(f"  决断：{cost}")
                    if desc:
                        line.append(f"  描述：{desc}")
                    if result:
                        line.append(f"  结果：{result}")
                    out.append("\n".join(line))
                n += 1
            sub = plain_text(tpl.get("子事件", "")).strip()
            if sub:
                out.append(f"· 子事件：{sub}")
        return out

    pat = re.compile(
        r"(?:^|\n)\s*(选项|描述|结果|决断)(\d+)\s*=\s*(.*?)"
        r"(?=\n\s*(?:选项|描述|结果|决断)\d+\s*=|\Z)", re.S)
    for m in pat.finditer(raw or ""):
        kind, num, value = m.group(1), m.group(2), plain_text(m.group(3)).strip()
        if not value:
            continue
        label = "分支" if kind == "描述" else kind
        out.append(f"· {label}{num}：{value}")
    return out


def parse_reclamation_events(raw: str) -> list[dict]:
    """解析「事件一览」页：按 == 分类 == / === 事件名 === 取 {{生息演算事件}}。

    同一个「事件名」会在页面里重复出现（不同分支的选项组不同）。这里按
    `(分类, 事件名)` 合并：描述取第一份，选项去重后全部保留，避免生成多个
    几乎相同的文件，同时不丢分支文本。
    """
    merged: dict[tuple[str, str], dict] = {}
    order: list[tuple[str, str]] = []

    def add(category: str, name: str, tpl: dict) -> None:
        key = (category or "未分类", name)
        if key not in merged:
            merged[key] = {"category": category or "未分类", "name": name,
                           "types": set(), "desc": "", "options": [], "option_set": set()}
            order.append(key)
        item = merged[key]
        etype = (tpl.get("type") or "").strip()
        if etype:
            item["types"].add(etype)
        desc = plain_text(tpl.get("描述", "")).strip()
        if desc and not item["desc"]:
            item["desc"] = desc
        for opt in _event_options(tpl.get("选项", "")):
            if opt not in item["option_set"]:
                item["option_set"].add(opt)
                item["options"].append(opt)

    category = ""
    for level, title, block in split_sections(raw or ""):
        if level == 2:
            category = title
            continue
        if level != 3:
            continue
        for tpl in template_params(block, "生息演算事件"):
            name = plain_text(tpl.get("标题", "")).strip() or title
            add(category, name, tpl)

    if not merged:
        # 兜底：页面没有三级标题时，直接扫全文
        for tpl in template_params(raw or "", "生息演算事件"):
            name = plain_text(tpl.get("标题", "")).strip()
            if name:
                add("未分类", name, tpl)

    events: list[dict] = []
    for key in order:
        item = merged[key]
        body = [item["desc"]] if item["desc"] else []
        if item["options"]:
            body += ["", *item["options"]]
        events.append({
            "category": item["category"],
            "name": item["name"],
            "type": "/".join(sorted(item["types"])),
            "text": "\n".join(body).strip(),
        })
    return events
