#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""干员文本采集器：档案 / 模组故事 / 干员密录（avg 剧情）/ 悖论模拟。

输出：OUT/operator/<干员名>/
    干员档案.txt            ← 干员页 ==干员档案== 里的 {{人员档案}} 各段
    模组1-<模组名>.txt      ← 干员页 ==模组== 里的 {{模组|基础信息=…}}（模组故事）
    模组2-… .txt
    avg1-<密录名>.txt       ← 干员密录剧情（Cargo char_memory → 密录页），首行是剧情前的文本
    avg2-… .txt
    悖论模拟.txt            ← 干员页 ==悖论模拟== 的 {{悖论模拟|description=…}}

干员名单与密录索引都来自 Cargo（chara / char_memory），因此新干员、新密录会自动跟上。
"""

from __future__ import annotations

import re

import click

from ..http import BASE
from ..output import Manifest, natural_key, sanitize, signature, write_text
from ..registry import Collector, Context, Stat, need_update, register
from ..story import extract_story
from ..wikitext import flavor_text, plain_text, section_text, template_params
from .avg import make_raw_fetcher

MODULE_DIR = "operator"
CHARA_TABLE = "chara"
MEMORY_TABLE = "char_memory"


# --------------------------------------------------------------------- 解析

def parse_archive(raw: str, title: str) -> str:
    """干员档案：{{人员档案|档案N=标题|档案N条件=条件|档案N文本=正文}}。"""
    section = section_text(raw, "干员档案") or raw
    items: list[str] = []
    for tpl in template_params(section, "人员档案"):
        n = 1
        while f"档案{n}" in tpl or f"档案{n}文本" in tpl:
            name = (tpl.get(f"档案{n}") or "").strip()
            cond = (tpl.get(f"档案{n}条件") or "").strip()
            text = plain_text(tpl.get(f"档案{n}文本", ""))
            if text or name:
                head = f"【{name}】" + (f"（{cond}）" if cond else "")
                items.append(f"{head}\n{text}".strip())
            n += 1
    if not items:
        return ""
    return f"{title} 干员档案\n\n" + "\n\n".join(items) + "\n"


def parse_modules(raw: str) -> list[tuple[str, str]]:
    """模组：返回 [(模组名, 模组故事正文)]（只保留有故事的）。"""
    section = section_text(raw, "模组") or raw
    out: list[tuple[str, str]] = []
    for tpl in template_params(section, "模组"):
        name = (tpl.get("名称") or tpl.get("模组名") or "").strip()
        story = plain_text(tpl.get("基础信息", ""))
        if story:
            out.append((name or f"模组{len(out) + 1}", story))
    return out


def parse_paradox(raw: str) -> tuple[str, str]:
    """悖论模拟：{{悖论模拟|name=…|description=…}} → (名字, 描述文本)。

    description 里也会跟一段 {{color|…}} 标注的特殊规则，这里只取描述部分。
    """
    for tpl in template_params(raw, "悖论模拟"):
        name = (tpl.get("name") or "").strip()
        desc = flavor_text(tpl.get("description", ""))
        if desc:
            return name, desc
    return "", ""


# --------------------------------------------------------------------- 采集器

@register
class OperatorCollector(Collector):
    name = "operator"
    title = "干员：档案 / 模组故事 / 干员密录(avg) / 悖论模拟"
    help = """按干员建文件夹，抓取四类文本：

\b
    OUT/operator/<干员名>/干员档案.txt        ← ==干员档案== 的全部 {{人员档案}} 段落
    OUT/operator/<干员名>/模组1-<模组名>.txt   ← 模组故事（{{模组|基础信息=…}}）
    OUT/operator/<干员名>/avg1-<密录名>.txt    ← 干员密录剧情，首行是密录的前置文本
    OUT/operator/<干员名>/悖论模拟.txt         ← ==悖论模拟== 的 description

干员名单（Cargo chara）与密录索引（Cargo char_memory）都实时查询，
新干员 / 新密录 / 新模组会自动出现。用 -g 干员名 可以只处理指定干员。"""
    order = 30

    @classmethod
    def params(cls) -> list:
        return [
            click.Option(["--no-memory"], is_flag=True, help="跳过干员密录(avg)剧情"),
            click.Option(["--no-module"], is_flag=True, help="跳过模组故事"),
        ]

    def run(self, ctx: Context) -> Stat:
        stat = Stat()
        out = ctx.out_dir / MODULE_DIR
        manifest = Manifest(out / "_manifest.json")

        self.header(ctx, "读取干员名单与密录索引")
        operators: list[str] = []
        for row in ctx.client.cargo_all(CHARA_TABLE, "_pageName=PAGE,cn,rarity", order_by="charIndex"):
            name = row.get("PAGE") or row.get("cn")
            if name and (ctx.match(name) or not ctx.keywords):
                operators.append(name)
        operators = sorted(set(operators), key=natural_key)
        if ctx.limit:
            operators = operators[:ctx.limit]
        ctx.log(f"  干员 {len(operators)} 人")

        memories: dict[str, list[dict]] = {}
        if not ctx.extra.get("no_memory"):
            for row in ctx.client.cargo_all(
                    MEMORY_TABLE,
                    "_pageName=PAGE,storySetName,storyIntro,storyTxt,storyIndex,elite,level,favor"):
                page = row.get("PAGE")
                if not page:
                    continue
                memories.setdefault(page, []).append({
                    "set": row.get("storySetName", ""),
                    "intro": row.get("storyIntro", ""),
                    "page": row.get("storyTxt", ""),
                    "index": story_index_of(row.get("storyTxt", ""), row.get("storyIndex", "")),
                    "cond": _memory_condition(row),
                })
            for rows in memories.values():
                rows.sort(key=lambda r: natural_key(r["index"]))
            ctx.log(f"  密录 {sum(len(v) for v in memories.values())} 篇 / {len(memories)} 人")

        # ------- 版本检查 -------
        ctx.log("  检查版本 …")
        page_titles = list(operators)
        memory_titles = [m["page"] for rows in memories.values() for m in rows if m["page"]]
        revs = ctx.client.revids(page_titles + memory_titles)

        todo: list[str] = []
        for name in operators:
            mem = memories.get(name, [])
            sig = signature(
                revs.get(name).revid if revs.get(name) else 0,
                *[f"{m['page']}:{revs.get(m['page']).revid if revs.get(m['page']) else 0}" for m in mem],
            )
            folder = out / sanitize(name)
            exists = folder.exists() and any(folder.glob("*.txt"))
            old = manifest.get(name)
            if ctx.mode != "force" and old.get("status") == "无文本" and old.get("sig") == sig:
                stat.skipped_empty += 1        # 该干员确实没有可抓文本，版本没变就不再重试
                continue
            if need_update(ctx, manifest, name, sig, exists):
                todo.append(name)
            else:
                stat.skipped += 1

        if ctx.dry_run:
            for name in todo[:50]:
                ctx.log(f"  · 将抓取 干员/{name}")
            if len(todo) > 50:
                ctx.log(f"  …其余 {len(todo) - 50} 人省略")
            stat.dry_run_note = f"{len(todo)} 名干员待抓取"
            return stat

        ctx.log(f"  需要处理 {len(todo)} 人")
        if todo:
            pages = ctx.client.pages(todo, with_content=True)
            mem_pages = ctx.client.pages([m["page"] for n in todo for m in memories.get(n, []) if m["page"]],
                                         with_content=True)
            fetch = make_raw_fetcher(ctx)
            for n, name in enumerate(todo, 1):
                rec = pages.get(name)
                if rec is None or not rec.content:
                    stat.skipped_empty += 1
                    continue
                folder = out / sanitize(name)
                written: list[str] = []

                def put(fname: str, text: str) -> None:
                    folder.mkdir(parents=True, exist_ok=True)   # 有内容才建目录
                    write_text(folder / fname, text)
                    written.append(fname)

                archive = parse_archive(rec.content, name)
                if archive:
                    put("干员档案.txt", archive)

                if not ctx.extra.get("no_module"):
                    for i, (mod_name, story) in enumerate(parse_modules(rec.content), 1):
                        put(f"模组{i}-{sanitize(mod_name)}.txt",
                            f"{name} 模组{i}：{mod_name}\n\n{story}\n")

                if not ctx.extra.get("no_memory"):
                    for i, mem in enumerate(memories.get(name, []), 1):
                        mrec = mem_pages.get(mem["page"])
                        if mrec is None or not mrec.content:
                            continue
                        doc = extract_story(mrec.content, fetch=fetch, page_title=mem["page"],
                                            log=ctx.log if ctx.verbose else (lambda *_: None))
                        if not doc.blocks:
                            continue
                        head = [f"{name} 干员密录{i}：{mem['set']}",
                                f"- 解锁条件：{mem['cond']}" if mem["cond"] else "",
                                f"- 页面：{BASE}/w/{mem['page'].replace(' ', '_')}",
                                "",
                                (mem["intro"] or "").strip(),
                                "", "---", ""]
                        text = "\n".join(x for x in head if x != "") + "\n"
                        for _tp, block in doc.blocks:
                            text += block.rstrip() + "\n\n"
                        put(f"avg{i}-{sanitize(mem['set'] or str(i))}.txt", text.rstrip() + "\n")

                pname, pdesc = parse_paradox(rec.content)
                if pdesc:
                    head = f"{name} 悖论模拟" + (f"：{pname}" if pname else "") + "\n\n"
                    put("悖论模拟.txt", head + pdesc + "\n")

                sig_now = signature(
                    rec.revid,
                    *[f"{m['page']}:{mem_pages.get(m['page']).revid if mem_pages.get(m['page']) else 0}"
                      for m in memories.get(name, [])],
                )
                if not written:
                    stat.skipped_empty += 1
                    # 记一笔，避免以后每次刷新都重抓这个没有文本的干员
                    manifest.record(name, sig_now, revid=rec.revid, folder=sanitize(name),
                                    files=[], count=0, status="无文本")
                    continue
                manifest.record(name, sig_now, revid=rec.revid, folder=sanitize(name),
                                files=written, count=len(written), status="已写入")
                stat.written += 1
                if ctx.verbose:
                    ctx.log(f"  + 干员/{sanitize(name)}（{len(written)} 个文件）")
                if stat.written % 50 == 0:
                    manifest.save()
                    ctx.log(f"  …已处理 {stat.written} 人")

        manifest.save()
        self._write_index(out, manifest)
        return stat

    @staticmethod
    def _write_index(out, manifest: Manifest) -> None:
        import time
        lines = ["# PRTS 干员文本索引", "",
                 f"生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}　|　{len(manifest.items)} 名干员", "",
                 "> 由 prts_crawler.py operator 生成。每名干员的文件夹里包含：",
                 "> 干员档案 / 模组N-<模组名> / avgN-<密录名> / 悖论模拟", ""]
        for name in sorted(manifest.items, key=natural_key):
            info = manifest.items[name]
            files = info.get("files", [])
            lines.append(f"## {name}（{len(files)}）")
            lines.append("")
            lines += [f"- {f}" for f in files]
            lines.append("")
        write_text(out / "_索引.md", "\n".join(lines), ignore_timestamps=True)


def story_index_of(story_txt: str, fallback: str) -> str:
    """从密录页标题 `干员名/干员密录/2` 里取序号 2。"""
    m = re.search(r"/(\d+)\s*$", story_txt or "")
    return m.group(1) if m else (fallback or "0")


def _memory_condition(row: dict) -> str:
    bits: list[str] = []
    if row.get("elite"):
        bits.append(f"精英{row['elite']}")
    if row.get("level"):
        bits.append(f"等级{row['level']}")
    if row.get("favor"):
        bits.append(f"信赖{row['favor']}")
    return "、".join(bits)
