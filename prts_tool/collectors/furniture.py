#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""家具文本采集器：按「主题（套组）」汇总家具描述。

输出：OUT/furniture/<主题名>.txt（与 OUT/avg、OUT/operator 同级；可用 --furniture-dir 改子目录）

文件格式：

    套组名:龙门食坊
    再现了龙门食坊的概念房间。欢庆佳节，恭迎宾客。

    子家具:
    转角木桌
    龙门食坊用的大木桌。无米不成炊，无客不成食。
    用途
    能够用来装扮宿舍，提高宿舍的氛围

    食坊圆凳
    ……

主题描述来自主题页的 {{家具主题总览}}（并回退到 Cargo furniture_themes）；
家具按主题页「快速布置」表的顺序排列，取不到时按名称排序。
"""

from __future__ import annotations

import re

import click

from ..output import Manifest, natural_key, sanitize, signature, write_text
from ..registry import Collector, Context, Stat, need_update, register
from ..wikitext import plain_text, template_params

FURNITURE_TEMPLATE = "家具信息"
THEME_TEMPLATE = "家具主题总览"
THEME_TABLE = "furniture_themes"
UNGROUPED = "独立家具"
DEFAULT_SUBDIR = "furniture"        # 与 avg / 干员 同级


def parse_furniture(raw: str) -> dict:
    tpl = (template_params(raw, FURNITURE_TEMPLATE) or [{}])[0]
    return {
        "name": (tpl.get("名称") or "").strip(),
        "desc": plain_text(tpl.get("描述", "")),
        "usage": plain_text(tpl.get("用途", "")),
        "theme": (tpl.get("所属套装") or "").strip(),
        "group": (tpl.get("所属组件") or "").strip(),
    }


def parse_theme(raw: str) -> tuple[str, str, list[str]]:
    """主题页 → (主题名, 主题描述, 快速布置里的家具顺序)。"""
    tpls = template_params(raw, THEME_TEMPLATE)
    name = desc = ""
    if tpls:
        t = tpls[0]
        name = (t.get("1") or t.get("主题名") or "").strip()
        desc = plain_text(t.get("2") or t.get("主题描述") or "")
    order: list[str] = []
    m = re.search(r"==\s*快速布置\s*==(.*?)(?=\n==[^=]|\Z)", raw, re.S)
    if m:
        for link in re.finditer(r"\[\[([^\]\|]+)(?:\|[^\]]*)?\]\]", m.group(1)):
            target = link.group(1).strip()
            if target and not target.startswith(("分类:", "文件:")):
                order.append(target)
    return name, desc, order


@register
class FurnitureCollector(Collector):
    name = "furniture"
    title = "家具文本（按主题/套组汇总）"
    help = """把家具按所属套装汇总成一个个文件：

\b
    OUT/furniture/<主题名>.txt        （与 OUT/avg、OUT/operator 同级）

\b
格式（家具之间空一行）：

\b
    套组名:龙门食坊
    再现了龙门食坊的概念房间。欢庆佳节，恭迎宾客。

\b
    子家具:
    转角木桌
    龙门食坊用的大木桌。无米不成炊，无客不成食。
    用途
    能够用来装扮宿舍，提高宿舍的氛围

\b
    ……（下一件家具）

家具页来自 `Template:家具信息` 的嵌入列表（约 2800 页），
主题名与排序取自主题页（`Template:家具主题总览` + 快速布置表）。
--furniture-dir 可以换子目录名，传空字符串则直接放在输出根目录。"""
    order = 40

    @classmethod
    def params(cls) -> list:
        return [
            click.Option(["--furniture-dir"], default=DEFAULT_SUBDIR, show_default=True,
                         help="家具 txt 的子目录名（传空字符串则放输出根目录）"),
            click.Option(["--with-usage/--no-usage"], default=True, show_default=True,
                         help="是否在描述后附上「用途」一段"),
        ]

    def run(self, ctx: Context) -> Stat:
        stat = Stat()
        sub = ctx.extra.get("furniture_dir")
        sub = DEFAULT_SUBDIR if sub is None else sub
        out = ctx.out_dir / sub if sub else ctx.out_dir
        with_usage = ctx.extra.get("with_usage", True)
        manifest = Manifest(out / "_manifest.json")

        self.header(ctx, "读取家具主题")
        theme_desc: dict[str, str] = {}
        for row in ctx.client.cargo_all(THEME_TABLE, "_pageName=PAGE,theme_desc"):
            page = row.get("PAGE")
            if page:
                theme_desc[page] = plain_text(row.get("theme desc") or row.get("theme_desc") or "")

        self.header(ctx, "枚举家具页")
        titles = ctx.client.embedded_in(FURNITURE_TEMPLATE)
        ctx.log(f"  家具页 {len(titles)} 个")
        if ctx.limit:
            titles = titles[:ctx.limit]

        ctx.log("  检查版本 …")
        revs = ctx.client.revids(titles)
        all_theme_names = set(theme_desc)
        records: list[dict] = []
        pending: list[str] = []
        for title in titles:
            rec = revs.get(title)
            if rec is None or not rec.revid:
                continue
            cached = manifest.get(f"item:{title}")
            if (ctx.mode != "force" and cached and cached.get("revid") == rec.revid
                    and cached.get("theme") is not None and "desc" in cached):
                records.append({**cached, "title": title})
                all_theme_names.add(cached.get("theme") or "")
                stat.skipped += 1
            else:
                pending.append(title)

        if pending:
            ctx.log(f"  读取 {len(pending)} 个家具页 …")
            pages = ctx.client.pages(pending, with_content=True)
            for title in pending:
                rec = pages.get(title)
                info = parse_furniture(rec.content) if rec and rec.content else {}
                theme = info.get("theme") or UNGROUPED
                records.append({"title": title, "code": theme, "theme": theme,
                                "name": info.get("name") or title,
                                "desc": info.get("desc", ""), "usage": info.get("usage", ""),
                                "group": info.get("group", ""), "revid": rec.revid if rec else 0})
                all_theme_names.add(theme)
                # 描述/用途也存进清单，这样下次增量运行时不必重新下载页面
                manifest.record(f"item:{title}", str(rec.revid if rec else 0),
                                revid=rec.revid if rec else 0, theme=theme,
                                name=info.get("name") or title, group=info.get("group", ""),
                                desc=info.get("desc", ""), usage=info.get("usage", ""))

        # ------- 主题页（描述 + 排序） -------
        theme_names = sorted({t for t in all_theme_names if t and t != UNGROUPED}, key=natural_key)
        need_theme = [t for t in theme_names
                      if ctx.mode == "force" or not manifest.get(f"theme:{t}")]
        theme_order: dict[str, list[str]] = {}
        if need_theme:
            ctx.log(f"  读取 {len(need_theme)} 个主题页 …")
            trecs = ctx.client.pages(need_theme, with_content=True)
            for t in need_theme:
                rec = trecs.get(t)
                if not rec or not rec.content:
                    continue
                name, desc, order = parse_theme(rec.content)
                if desc:
                    theme_desc[t] = desc
                theme_order[t] = order
                manifest.record(f"theme:{t}", str(rec.revid), revid=rec.revid,
                                desc=desc, order=order)
        for t in theme_names:
            cached = manifest.get(f"theme:{t}")
            if cached.get("order") is not None:
                theme_order.setdefault(t, cached.get("order") or [])
            if not theme_desc.get(t) and cached.get("desc"):
                theme_desc[t] = cached["desc"]

        # ------- 汇总落盘 -------
        groups: dict[str, list[dict]] = {}
        for row in records:
            groups.setdefault(row["theme"], []).append(row)

        written = 0
        for theme in sorted(groups, key=natural_key):
            rows = groups[theme]
            order = theme_order.get(theme, [])
            pos = {name: i for i, name in enumerate(order)}
            rows.sort(key=lambda r: (pos.get(r["title"], pos.get(r["name"], 9999)), natural_key(r["name"])))
            sig = signature(theme_desc.get(theme, ""), *[f"{r['title']}:{r['revid']}" for r in rows])
            path = out / f"{sanitize(theme)}.txt"
            if not ctx.match(theme):
                continue
            if not need_update(ctx, manifest, f"group:{theme}", sig, path.exists()):
                stat.skipped += 1
                continue
            if ctx.dry_run:
                ctx.log(f"  · 将写入 {sanitize(theme)}.txt（{len(rows)} 件家具）")
                written += 1
                continue
            body = [f"套组名:{theme}", theme_desc.get(theme, ""), "", "子家具:"]
            for row in rows:
                body.append(row["name"])
                body.append(row["desc"])
                if with_usage and row["usage"]:
                    body += ["用途", row["usage"]]
                body.append("")
            path.parent.mkdir(parents=True, exist_ok=True)
            write_text(path, "\n".join(body).rstrip() + "\n")
            manifest.record(f"group:{theme}", sig, file=path.name, count=len(rows))
            stat.written += 1
            written += 1
            if ctx.verbose:
                ctx.log(f"  + {sanitize(theme)}.txt（{len(rows)} 件）")

        if ctx.dry_run:
            stat.dry_run_note = f"{written} 个主题文件待写入"
        else:
            ctx.log(f"  写出 {written} 个主题文件，共 {len(groups)} 个套组")
            manifest.save()
            self._write_index(out, groups, manifest)
        return stat

    @staticmethod
    def _write_index(out, groups: dict[str, list[dict]], manifest: Manifest) -> None:
        import time
        lines = ["# PRTS 家具文本索引", "",
                 f"生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}　|　"
                 f"{len(groups)} 个套组　|　{sum(len(v) for v in groups.values())} 件家具", "",
                 "> 由 prts_crawler.py furniture 生成，每个套组一个 txt。", ""]
        for theme in sorted(groups, key=natural_key):
            rows = groups[theme]
            lines += [f"## {theme}（{len(rows)}）", ""]
            lines += [f"- {r['name']}" for r in rows]
            lines.append("")
        write_text(out / "_家具索引.md", "\n".join(lines), ignore_timestamps=True)
