#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""关卡文本采集器：为每个章节/活动文件夹生成一份《关卡文本.txt》。

内容取自关卡页 `{{普通关卡信息|关卡描述=…}}` 里的「风味文本」部分
（后面用 {{color|…}} 标注的机制说明默认去掉），例如：

    H17-1 急变预案-1
    “我宣传的并非完全严肃的道德。”

    17-1 相逢
    ……

关卡 → 章节文件夹的映射：优先用关卡代号（17-1 / H17-1 → 第17章；BB-1 → 字母前缀对应的
活动文件夹），失败时回退用「所属区域」匹配文件夹名。
"""

from __future__ import annotations

import re

import click

from ..output import Manifest, natural_key, sanitize, sanitize_path, signature, write_text
from ..registry import Collector, Context, Stat, need_update, register
from ..wikitext import flavor_text, section_text, template_params
from .avg import MODULE_DIR, folder_for_stage, folder_maps, leaf_folder

STAGE_FILE = "关卡文本.txt"
STAGE_TEMPLATE = "普通关卡信息"
STAGE_LIST_PAGE = "关卡一览/活动关卡"


def stage_text(desc: str, with_conditions: bool = False) -> str:
    """从「关卡描述」里取风味文本（机制说明默认丢掉）。"""
    return flavor_text(desc, with_conditions=with_conditions)


def exact_stage_folders(ctx: Context, folders: list[str]) -> dict[str, str]:
    """用「关卡一览/活动关卡」里各小节列出的关卡，建立精确的「关卡页 → 文件夹」映射。

    有些活动（例如生息演算的「沙中之火」「沙洲遗闻」）共用关卡代号、也没有所属区域，
    只看代号会分错组；而关卡一览的每个小节正好就是该场次的关卡清单，用它最准。
    """
    raw = ctx.client.raw(STAGE_LIST_PAGE)
    if not raw:
        return {}
    out: dict[str, str] = {}
    for folder in folders:
        leaf = re.sub(r"^(?:avg|reclamation|roguelike)/", "", folder)
        leaf = re.sub(r"^(支线|特殊|集成战略|生息演算|四月辑录|剧情)\s*", "", leaf)
        leaf = leaf.split("/")[-1]
        if not leaf:
            continue
        sec = section_text(raw, leaf)
        if not sec:
            continue
        for m in re.finditer(r"\[\[([^\]\|]+)(?:\|[^\]]*)?\]\]", sec):
            title = m.group(1).strip()
            if title.startswith(("文件:", "分类:", "#")):
                continue
            out.setdefault(title, folder)
    return out


@register
class StageCollector(Collector):
    name = "stage"
    title = "关卡文本（各章节 / 活动一份《关卡文本.txt》）"
    help = """把同一章节（或活动）下所有关卡的「关卡描述」汇总成一个文件：

\b
    OUT/avg/<章节文件夹>/关卡文本.txt
    OUT/reclamation/<场次>/关卡文本.txt

\b
文件格式（每关两行，关与关之间空一行）：

\b
    H17-1 急变预案-1
    “我宣传的并非完全严肃的道德。”

\b
    17-1 相逢
    ……

关卡页来自 `Template:普通关卡信息` 的嵌入列表（约 3500 页）；
没有风味文本的纯机制关卡会被跳过；没能匹配到章节文件夹的关卡会列出来。
用 --with-conditions 可以把作战条件/机制说明一起保留。"""
    order = 20

    @classmethod
    def params(cls) -> list:
        return [
            click.Option(["--with-conditions"], is_flag=True,
                         help="连 {{color|…}} 标注的作战条件/机制说明一起保留"),
        ]

    def run(self, ctx: Context) -> Stat:
        stat = Stat()
        # 章节文件夹路径自带模块名（avg/… 或 reclamation/…），所以直接相对输出根目录拼
        out = ctx.out_dir
        manifest = Manifest(ctx.out_dir / MODULE_DIR / "_stage_manifest.json")
        by_chapter, by_prefix, folders = folder_maps(ctx.out_dir)
        if not folders:
            ctx.log("  ! 还没抓过 avg 剧情：章节结构未知，先跑 `avg` 命令（或用 `all`）")
        # 关卡一览/活动关卡 里的小节清单：最精确的对应关系（同代号活动靠它区分）
        exact = exact_stage_folders(ctx, folders) if folders else {}
        ctx.log(f"  关卡一览可精确对应 {len(exact)} 个关卡")

        self.header(ctx, "枚举关卡页")
        titles = ctx.client.embedded_in(STAGE_TEMPLATE)
        ctx.log(f"  关卡页 {len(titles)} 个")
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
            cached = manifest.get(f"stage:{title}")
            if ctx.mode != "force" and cached and cached.get("revid") == rec.revid and cached.get("status"):
                records.append({**cached, "title": title, "revid": rec.revid})
                stat.skipped += 1
            else:
                pending.append(title)

        if pending:
            ctx.log(f"  读取 {len(pending)} 个关卡页 …")
            pages = ctx.client.pages(pending, with_content=True)
            unmatched: list[str] = []
            for title in pending:
                rec = pages.get(title)
                content = rec.content if rec else ""
                normal = (template_params(content, STAGE_TEMPLATE) or [{}])[0] if content else {}
                code = normal.get("关卡代号", "") or title.split(" ", 1)[0]
                zone = normal.get("所属区域", "")
                text = stage_text(normal.get("关卡描述", ""), bool(ctx.extra.get("with_conditions")))
                if not text:
                    stat.skipped_empty += 1
                    manifest.record(f"stage:{title}", str(rec.revid if rec else 0),
                                    revid=rec.revid if rec else 0, folder="", text="",
                                    label=title, code=code, zone=zone, status="无描述")
                    continue
                folder = exact.get(title) or folder_for_stage(
                    code, zone, by_chapter, by_prefix, folders, title,
                    stage_id=normal.get("关卡id", ""))
                if not folder:
                    unmatched.append(f"{title}（所属区域：{zone or '未知'}）")
                    manifest.record(f"stage:{title}", str(rec.revid if rec else 0),
                                    revid=rec.revid if rec else 0, folder="", text="",
                                    label=title, code=code, zone=zone, status="未匹配章节")
                    continue
                manifest.record(f"stage:{title}", str(rec.revid if rec else 0),
                                revid=rec.revid if rec else 0, folder=folder, text=text,
                                label=title, code=code, zone=zone, status="已收录")
                records.append({"title": title, "code": code, "text": text, "folder": folder,
                                "revid": rec.revid if rec else 0})
            if unmatched:
                ctx.log(f"  · {len(unmatched)} 个关卡没能匹配到章节文件夹（已跳过），例如：")
                for line in unmatched[:8]:
                    ctx.log(f"      {line}")

        # ------- 按文件夹汇总 -------
        groups: dict[str, list[dict]] = {}
        for row in records:
            if row.get("folder") and row.get("text"):
                groups.setdefault(row["folder"], []).append(row)

        written_folders = 0
        for folder in sorted(groups, key=natural_key):
            # 按关卡页标题去重（同一个代号下会有很多关卡，例如生息演算的 RA-NO 几十个）
            rows = list({r["title"]: r for r in groups[folder]}.values())
            rows.sort(key=lambda r: natural_key(r["title"]))
            sig = signature(*[f"{r['title']}:{r['revid']}" for r in rows])
            path = out / sanitize_path(folder) / STAGE_FILE
            if not ctx.match(folder):
                continue
            if not need_update(ctx, manifest, f"folder:{folder}", sig, path.exists()):
                stat.skipped += 1
                continue
            if ctx.dry_run:
                ctx.log(f"  · 将写入 {sanitize_path(folder)}/{STAGE_FILE}（{len(rows)} 关）")
                written_folders += 1
                continue
            body: list[str] = []
            for row in rows:
                body += [f"{row['code']} {row['title'].split(' ', 1)[-1]}".strip(), row["text"], ""]
            path.parent.mkdir(parents=True, exist_ok=True)
            write_text(path, "\n".join(body).rstrip() + "\n")
            manifest.record(f"folder:{folder}", sig,
                            file=f"{sanitize_path(folder)}/{STAGE_FILE}", count=len(rows))
            stat.written += 1
            written_folders += 1
            if ctx.verbose:
                ctx.log(f"  + {sanitize_path(folder)}/{STAGE_FILE}（{len(rows)} 关）")

        if ctx.dry_run:
            stat.dry_run_note = f"{written_folders} 个章节文件待写入"
        else:
            ctx.log(f"  覆盖 {written_folders} 个章节文件，共 {len(groups)} 个章节分组")
            manifest.save()
        return stat


def stage_files(out_dir) -> list[str]:
    """已经生成的关卡文本文件（相对路径）。"""
    return sorted(str(p.relative_to(out_dir)) for p in (out_dir / MODULE_DIR).rglob(STAGE_FILE))
