#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""泰拉记事社（terra）模块：抓取 PRTS 收录的微博长图。

图片来源：PRTS 的 `泰拉记事` 页面，它用 `{{微博|…}}` 模板收录了新浪微博
**@泰拉记事社** 与 **@明日方舟Arknights** 发布的各类外部剧情资料（剧情长图）。
这些图片已经上传到 prts.wiki，所以直接从 PRTS 拉，不用去微博。

输出：terra/<大节>/<条目名>/
    ├── 说明.txt        微博链接 / 日期 / 标题 / 描述文本
    └── <原文件名>.jpg   （保持 wiki 上的文件名，按日期可排序）

注意默认 `terra/` 位于 `resources/collected/terra/`，不在 prts_text 里面：
图片动辄几 MB，不该混进文本树里。默认**只写 `说明.txt` 与索引、不下载图片**，
想连图一起抓必须显式说明：

    python prts_crawler.py terra --images        # 文本 + 图片
    python prts_crawler.py terra-images          # 只抓图片（等价于上面）
    python prts_crawler.py all                   # 全量爬取：不含图片

图片很大，可以先 `--dry-run` 看规模，或用 `--limit` 只抓前几条。
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import click

from ..output import Manifest, natural_key, sanitize, write_text
from ..registry import Collector, Context, Stat, need_update, register
from ..wikitext import clean_markup, plain_text, template_params

MODULE_DIR = "terra"
INDEX_PAGES = ("泰拉记事",)
TEMPLATE = "微博"
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
NOTE_FILE = "说明.txt"


def parse_entries(raw: str, page: str) -> list[dict]:
    """解析 `{{微博|链接 日期 标题|<poem>描述</poem>|图1|图2|…}}`。"""
    out: list[dict] = []
    section = ""
    # 先按标题切块，记录每个块所属的二级/三级标题
    marks = [(m.start(), len(m.group(1)), m.group(2).strip())
             for m in re.finditer(r"^(={2,4})\s*([^=\n]+?)\s*\1\s*$", raw, re.M)]
    for i, (pos, level, title) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(raw)
        block = raw[pos:end]
        if level == 2:
            section = title
            continue
        if level != 3:
            continue
        for tpl in template_params(block, TEMPLATE):
            link = tpl.get("1", "").strip()
            desc = plain_text(tpl.get("2", ""))
            images = [v.strip() for k, v in tpl.items()
                      if k not in ("1", "2") and v.strip().lower().endswith(IMAGE_EXT)]
            others = [v.strip() for k, v in tpl.items()
                      if k not in ("1", "2") and v.strip() and v.strip() not in images]
            if not images:
                continue
            date = ""
            m = re.search(r"(\d{4}-\d{2}-\d{2})", link)
            if m:
                date = m.group(1)
            # 标题里可能带 wiki 链接（例如 [[大地巡旅：…|大地巡旅]]），取纯文本
            name = clean_markup(title).strip() or title
            out.append({"page": page, "section": section or "未分组", "name": name,
                        "link": link, "date": date, "desc": desc,
                        "images": images, "others": others})
    return out


@register
class TerraCollector(Collector):
    name = "terra"
    title = "泰拉记事社（微博长图，来自 PRTS 的「泰拉记事」页）"
    help = """抓取 PRTS 收录的泰拉记事社 / 明日方舟官方微博长图。

\b
    terra/<大节>/<条目名>/说明.txt
    terra/<大节>/<条目名>/微博@…_2026-08-12_(1).jpg
    terra/_索引.md / _manifest.json

默认位于 `resources/collected/terra/`；自定义输出根时位于其同级，不放进文本树里。

\b
    默认只写 说明.txt 和索引，不下载图片：
        python prts_crawler.py terra
    要抓图片必须显式说明（图片很大，约几百 MB）：
        python prts_crawler.py terra --images
        python prts_crawler.py terra-images          # 等价
        python prts_crawler.py terra-images --force  # 已有图片也重下

`all` / `update` / `refresh` 这些「爬取全部内容」的指令**永远不下载图片**，
只更新说明文本与索引；想要图片请单独跑 terra-images。

图片来源页：`泰拉记事`（`{{微博}}` 模板里挂的就是上传到 PRTS 的原图），
所以不会去微博抓，链接只作为出处记在 `说明.txt` 里。"""
    order = 65
    data_root = MODULE_DIR
    aliases = (
        {"name": "terra-images", "short": "泰拉记事社：只抓图片（等价于 terra --images）",
         "help": "单独抓取泰拉记事社的微博长图（图片很大，默认的全量爬取不会跑这个）。\n\n"
                 "等价于 `python prts_crawler.py terra --images`；\n"
                 "加 `--force` 可以把已有的图片全部重下一遍。",
         "preset": {"images": True}},
    )

    @classmethod
    def params(cls) -> list:
        return [
            click.Option(["--images/--no-images"], default=False, show_default=True,
                         help="是否下载图片本身（默认不下载，只写说明与索引；"
                              "全量爬取 all/update 也不会下载）"),
            click.Option(["--page", "pages"], multiple=True,
                         help="额外的收录页面（默认泰拉记事）"),
        ]

    def run(self, ctx: Context) -> Stat:
        stat = Stat()
        out = self.data_dir(ctx)
        manifest = Manifest(out / "_manifest.json")

        pages = list(ctx.extra.get("pages") or ()) or list(INDEX_PAGES)
        entries: list[dict] = []
        self.header(ctx, "解析收录页面")
        for page in pages:
            raw = ctx.client.raw(page)
            if not raw:
                ctx.log(f"  ! 页面不存在：{page}")
                continue
            found = parse_entries(raw, page)
            ctx.log(f"  {page}：{len(found)} 条")
            entries += found

        if ctx.limit:
            entries = entries[:ctx.limit]
        if not entries:
            return stat

        want_images = bool(ctx.extra.get("images", False))
        filtered = bool(ctx.keywords) or bool(ctx.limit)

        # 汇总所有图片，一次批量查 URL / 大小 / sha1
        names: list[str] = []
        for e in entries:
            names += e["images"]
        info = ctx.client.file_info(names)
        total_bytes = sum(info.get(n, {}).get("size", 0) for n in names)
        ctx.log(f"  共 {len(entries)} 条、{len(names)} 张图，约 {total_bytes / 1024 / 1024:.1f} MB")
        if not want_images:
            ctx.log("  （本次只写说明与索引，不下载图片；要图片请跑 terra-images 或加 --images）")

        written = 0
        skipped = 0
        seen: dict[tuple[str, str], int] = {}
        live: set[str] = set()
        from collections import Counter
        pair_counts = Counter((e["section"], e["name"]) for e in entries)
        from ..output import signature
        for e in entries:
            if not ctx.match(e["name"], e["section"]):
                continue
            # 同一条目名可能有多期（例如「大地巡旅」有多条微博），用日期区分目录
            pair = (e["section"], e["name"])
            seen[pair] = seen.get(pair, 0) + 1
            leaf = sanitize(e["name"])
            if pair_counts[pair] > 1:
                leaf = sanitize(f"{e['name']}（{e['date'] or seen[pair]}）")
            folder = out / sanitize(e["section"]) / leaf
            note_path = folder / NOTE_FILE
            sig_parts = [e["link"], e["desc"]]
            for n in e["images"]:
                rec = info.get(n) or {}
                sig_parts.append(f"{n}:{rec.get('sha1', '')}")
            sig = signature(*sig_parts)
            # 用「大节 + 条目名 + 首图文件名」做键：条目名可能重复
            key = f"entry:{e['section']}/{leaf}/{e['images'][0]}"
            live.add(key)
            exists = note_path.exists() and all(
                (folder / sanitize(n)).exists() for n in e["images"]) if want_images else note_path.exists()
            if not need_update(ctx, manifest, key, sig, exists):
                stat.skipped += 1
                skipped += 1
                continue
            if ctx.dry_run:
                ctx.log(f"  · {e['section']}/{leaf}（{len(e['images'])} 张）")
                written += 1
                continue

            folder.mkdir(parents=True, exist_ok=True)
            note = [f"# {e['name']}", "",
                    f"- 分类：{e['section']}",
                    f"- 日期：{e['date'] or '未标注'}",
                    f"- 出处：{e['link']}",
                    f"- 收录页：{e['page']}",
                    "", "---", "", e["desc"] or "（无描述）", "", "图片："]
            note += [f"- {n}" for n in e["images"]]
            if e["others"]:
                note += ["", "其它文件："] + [f"- {n}" for n in e["others"]]
            write_text(note_path, "\n".join(note).rstrip() + "\n")
            stat.written += 1
            written += 1

            if want_images:
                for n in e["images"]:
                    rec = info.get(n) or {}
                    if not rec.get("url"):
                        ctx.log(f"    ! 没有找到文件：{n}")
                        stat.skipped_empty += 1
                        continue
                    dest = folder / sanitize(n)
                    if dest.exists() and dest.stat().st_size == rec.get("size", -1) and ctx.mode != "force":
                        continue
                    try:
                        ctx.client.download(rec["url"], dest)
                        stat.notes.append(f"{dest.relative_to(out)} ({rec['size'] / 1024 / 1024:.1f} MB)")
                        if ctx.verbose:
                            ctx.log(f"    + {dest.relative_to(out)}")
                    except Exception as exc:                     # noqa: BLE001
                        ctx.log(f"    ! 下载失败 {n}：{exc}")

            manifest.record(key, sig, folder=str(folder.relative_to(out)), section=e["section"],
                            name=e["name"], date=e["date"], link=e["link"],
                            count=len(e["images"]), updated=time.strftime("%Y-%m-%d %H:%M:%S"))
            if written % 10 == 0:
                manifest.save()

        # 页面上删掉 / 改名的条目：清掉清单里的旧键（不动磁盘上的文件）。
        # 带 --keyword / --limit 时不清理——那只是「这次没处理到」。
        if not filtered and not ctx.dry_run:
            for stale in [k for k in manifest.items if k not in live]:
                manifest.drop(stale)
        manifest.save()
        if not ctx.dry_run:
            self._write_index(out, manifest)
        ctx.log(f"  跳过 {skipped} 条（未变化）")
        return stat

    @staticmethod
    def _write_index(out: Path, manifest: Manifest) -> None:
        have = sum(1 for p in out.rglob("*")
                   if p.is_file() and p.suffix.lower() in IMAGE_EXT)
        lines = ["# PRTS 泰拉记事社图片索引", "",
                 f"生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}　|　"
                 f"{len(manifest.items)} 条　|　"
                 f"{sum(v.get('count', 0) for v in manifest.items.values())} 张图　|　"
                 f"本地已下载 {have} 张", "",
                 "> 由 prts_crawler.py terra 生成；来源是 PRTS 的「泰拉记事」页面（@泰拉记事社 / @明日方舟Arknights）。",
                 "> 图片默认不下载：`prts_crawler.py terra-images` 才是单独抓图的指令。", ""]
        by_section: dict[str, list[dict]] = {}
        for v in manifest.items.values():
            by_section.setdefault(v.get("section") or "未分组", []).append(v)
        for sec in sorted(by_section, key=natural_key):
            rows = sorted(by_section[sec], key=lambda v: (v.get("date") or "", natural_key(v.get("name") or "")))
            lines += [f"## {sec}（{len(rows)}）", ""]
            for v in rows:
                lines.append(f"- {v.get('date', '')}　{v.get('name')}（{v.get('count', 0)} 张）")
            lines.append("")
        write_text(out / "_索引.md", "\n".join(lines), ignore_timestamps=True)
