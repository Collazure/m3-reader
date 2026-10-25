#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""敌人文本采集器：按「地位级别」汇总敌人描述。

输出：OUT/enemies/精英.txt、普通.txt、领袖.txt（与 avg / operator / furniture 同级）

文件格式（只保留核心剧情文本，即 {{敌人信息/common2}} 的「描述」字段）：

    假想敌：管
    由源石创造再现的“女皇之声”，是根据源石灾难在全泰拉爆发的想象而设计的假想敌之一。
    源石在大地上蔓延，淹没一切赞美与斥责。晶体棱面泛起的余音，不过是源石的另一个名字。

    下一个敌人
    ……

敌人的能力/数值/关卡效果等功能性文本一律不抓。"""
from __future__ import annotations

import re

import click

from ..output import Manifest, natural_key, sanitize, signature, write_text
from ..registry import Collector, Context, Stat, need_update, register
from ..wikitext import plain_text, template_params

MODULE_DIR = "enemies"
ENEMY_TEMPLATE = "敌人信息/common2"
DEFAULT_FILE = "其它.txt"
# 地位级别 → 输出文件名（顺序即文件里的排序）
LEVEL_FILES = ("普通", "精英", "领袖")


def enemy_level(raw_level: str) -> str:
    """把「地位级别」归到 普通 / 精英 / 领袖 三类。"""
    level = (raw_level or "").strip()
    for key in LEVEL_FILES:
        if key in level:
            return key
    if level in ("BOSS", "boss", "首领"):
        return "领袖"
    return DEFAULT_FILE[:-4]


def parse_enemy(content: str) -> dict:
    """取敌人页的 {{敌人信息/common2}}：名称 / 地位级别 / 描述。"""
    tpls = template_params(content, ENEMY_TEMPLATE)
    if not tpls:
        return {}
    tpl = tpls[0]
    return {
        "name": (tpl.get("名称") or "").strip(),
        "level": (tpl.get("地位级别") or "").strip(),
        "kind": (tpl.get("种类") or "").strip(),
        "desc": plain_text(tpl.get("描述", "")),
    }


@register
class EnemyCollector(Collector):
    name = "enemies"
    title = "敌人文本（按地位级别分成 普通 / 精英 / 领袖）"
    help = """把敌人一览里的「敌人描述」按地位级别汇总成三个文件：

\b
    OUT/enemies/普通.txt
    OUT/enemies/精英.txt
    OUT/enemies/领袖.txt

\b
每个敌人的格式是「名称 + 描述」，只保留核心剧情文本：

\b
    假想敌：管
    由源石创造再现的“女皇之声”，是根据源石灾难在全泰拉爆发的想象而设计的假想敌之一。
    源石在大地上蔓延，淹没一切赞美与斥责。晶体棱面泛起的余音，不过是源石的另一个名字。

敌人的能力、数值、出场关卡等功能性文本不会被抓取。
敌人页来自 `Template:敌人信息/common2` 的嵌入列表（约 1800 页）。"""
    order = 45

    @classmethod
    def params(cls) -> list:
        return [
            click.Option(["--with-kind"], is_flag=True,
                         help="在每个敌人前额外加上「种类」（如 源石造物）标题行"),
        ]

    def run(self, ctx: Context) -> Stat:
        stat = Stat()
        out = ctx.out_dir / MODULE_DIR
        manifest = Manifest(out / "_manifest.json")

        self.header(ctx, "枚举敌人页")
        titles = ctx.client.embedded_in(ENEMY_TEMPLATE)
        ctx.log(f"  敌人页 {len(titles)} 个")
        if ctx.limit:
            titles = titles[:ctx.limit]

        ctx.log("  检查版本 …")
        revs = ctx.client.revids(titles)

        records: list[dict] = []
        pending: list[str] = []
        for title in titles:
            rec = revs.get(title)
            if rec is None or not rec.revid:
                continue
            cached = manifest.get(f"enemy:{title}")
            if ctx.mode != "force" and cached and cached.get("revid") == rec.revid and cached.get("status"):
                records.append({**cached, "title": title, "revid": rec.revid})
                stat.skipped += 1
            else:
                pending.append(title)

        if pending:
            ctx.log(f"  读取 {len(pending)} 个敌人页 …")
            pages = ctx.client.pages(pending, with_content=True)
            for title in pending:
                rec = pages.get(title)
                info = parse_enemy(rec.content) if rec and rec.content else {}
                if not info or not info["desc"]:
                    stat.skipped_empty += 1
                    manifest.record(f"enemy:{title}", str(rec.revid if rec else 0),
                                    revid=rec.revid if rec else 0, level="", name=title,
                                    text="", status="无描述")
                    continue
                level = enemy_level(info["level"])
                manifest.record(f"enemy:{title}", str(rec.revid if rec else 0),
                                revid=rec.revid if rec else 0, level=level,
                                name=info["name"] or title, kind=info["kind"],
                                text=info["desc"], status="已收录")
                records.append({"title": title, "revid": rec.revid if rec else 0, "level": level,
                                "name": info["name"] or title, "kind": info["kind"],
                                "text": info["desc"]})

        groups: dict[str, list[dict]] = {}
        for row in records:
            if row.get("text") and ctx.match(row.get("name", ""), row.get("kind", "")):
                groups.setdefault(row["level"], []).append(row)

        with_kind = bool(ctx.extra.get("with_kind"))
        written = 0
        for level in list(LEVEL_FILES) + ([DEFAULT_FILE[:-4]] if DEFAULT_FILE[:-4] in groups else []):
            rows = groups.get(level)
            if not rows:
                continue
            rows.sort(key=lambda r: natural_key(r["name"]))
            sig = signature(*[f"{r['name']}:{r['revid']}" for r in rows], with_kind)
            path = out / f"{level}.txt"
            if not need_update(ctx, manifest, f"file:{level}", sig, path.exists()):
                stat.skipped += 1
                continue
            if ctx.dry_run:
                ctx.log(f"  · 将写入 enemies/{level}.txt（{len(rows)} 个敌人）")
                written += 1
                continue
            body: list[str] = []
            for row in rows:
                body.append(row["name"])
                if with_kind and row["kind"]:
                    body.append(f"（{row['kind']}）")
                body.append(row["text"])
                body.append("")
            path.parent.mkdir(parents=True, exist_ok=True)
            write_text(path, "\n".join(body).rstrip() + "\n")
            manifest.record(f"file:{level}", sig, file=f"{level}.txt", count=len(rows))
            stat.written += 1
            written += 1
            if ctx.verbose:
                ctx.log(f"  + enemies/{level}.txt（{len(rows)} 个敌人）")

        if ctx.dry_run:
            stat.dry_run_note = f"{written} 个文件待写入"
        else:
            ctx.log(f"  写出 {written} 个文件，共 {len(records)} 个有描述的敌人")
            manifest.save()
        return stat
