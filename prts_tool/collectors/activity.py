#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""活动文本采集器：活动公告 + 活动专属长文（综合调查数据库、审判庭纪要……）。

剧情模拟器（avg）只收「关卡剧情」；活动页面里还有大量**只存在于活动页**的文本，
例如：

    * 孤星/综合调查数据库          —— 调查报告中克丽斯腾与“保存者”的通信
    * 叙拉古人/待办事项记录        —— 多视角任务线的全部对话
    * 崔林特尔梅之金/PRTS金律记录  —— 乐章、乐器与酒馆故事
    * 愚人号/审判庭纪要            —— 审判庭档案与物品说明
    * 长夜临光/信息端口            —— 三报新闻、日记、后记
    * 沙中之火、沙洲遗闻、重启锚点  —— PRTS 绿洲记录、日志、敌袭记录、剧情链

这些页面不是 `{{剧情模拟器}}`，avg 不会收录；本模块用 `action=parse` 取渲染后的
HTML 再转纯文本，按活动名分目录存放：

    OUT/activity/<活动名>/<子页面名>.txt
    OUT/activity/<活动名>/<子子页面>/活动公告.txt

只收「有正文」的页面：活动公告、以及名称命中 `LORE_HINTS` 的活动长文。
关卡信息、商店、地图、合约指标、肉鸽图鉴等机制页会被 `NOISE_HINTS` 排除。

去重约定：
  * avg / reclamation 清单里已有的页面（例如 `危机合约/剧情`）不再重复收录；
  * 集成战略七个主题的图鉴 / 记录页由 roguelike 模块负责，这里只收它们的活动公告。
"""

from __future__ import annotations

import json
import re
import time
from urllib.parse import quote

import click

from ..htmltext import html_to_text
from ..http import BASE
from ..output import Manifest, natural_key, sanitize, sanitize_path, write_text
from ..registry import Collector, Context, Stat, need_update, register

MODULE_DIR = "activity"
NAV_PAGE = "Template:剧情导航"
CACHE_NAME = "_pages.json"
CACHE_TTL = 7 * 24 * 3600      # 子页面索引缓存 7 天，避免每次全站扫描

GENERIC_GROUPS = {"剧情", "主线", "支线", "活动", "特殊", ""}
ANNOUNCE_NAME = "活动公告"

# 名称含这些词的活动子页面视为「有正文的长文」
LORE_HINTS = (
    "记录", "日志", "纪要", "档案", "数据库", "手记", "笔记", "来信", "访谈",
    "见闻", "评论", "委托", "报告", "剧情", "故事", "情报", "答案", "庆典",
    "留言", "通讯", "邮件", "信息端口", "互动", "剧情链", "OBSERVE", "PRTS",
    "涂写本", "辞旧迎新", "样片", "重建评价", "工坊日志", "罗德岛来信",
    "猎人笔记", "今日答案", "艺术评论", "待办事项", "见闻陈列", "调查",
    "记录中心", "金律", "绿洲", "御影", "餐食", "黑曜石节", "新闻", "报纸",
    "简报", "实录", "手札", "游记", "回忆", "人物志",
)

# 机制页 / 数据页 / 已被其它模块负责的页面
NOISE_HINTS = (
    "事件一览", "收藏品", "图鉴", "图标", "速查", "关卡", "地图", "合约",
    "指标", "任务地图", "任务", "商店", "材料", "素材", "/data", "/doc",
    "styles.css", "卡片", "sandbox", "模板", "预览", "钱盒", "通宝", "零件",
    "密文板", "思绪", "引擎配件", "应急助力", "后勤部", "外勤储备中心",
    "诡意行商", "秘境行商", "小队编队", "月度小队", "深入调查", "深入探索",
    "记录仪", "珍藏", "档案库", "见字图册", "巫仪档案库", "黑流数据库",
    "冬夜展览馆", "深蓝记录仪", "长生者宝盒", "生物制品陈设", "仪式用品索引",
    "想象实体图鉴", "珍玩集册", "拟造物质编目", "标志物", "行囊", "藏钱木盒",
    "易与", "雕伥速查", "炎国干员速查", "合约详情", "指标详情", "数据表",
)

CJK_RE = re.compile(r"[一-鿿]")


def _cjk_count(text: str) -> int:
    return len(CJK_RE.findall(text or ""))


def _all_subpages(client, group: str) -> list[str] | None:
    """活动页下的所有子页面（含子子页面）；失败返回 None，避免把空结果缓存 7 天。"""
    try:
        return list(client._paginate("allpages", list="allpages",
                                     apprefix=group + "/", aplimit=500,
                                     apnamespace=0))
    except Exception:
        return None


def _covered_titles(out: Path) -> set[str]:
    """avg / reclamation 已经收录的页面标题，避免活动模块重复写一遍。"""
    covered: set[str] = set()
    for name in ("avg", "reclamation"):
        manifest = Manifest(out / name / "_manifest.json")
        covered.update(manifest.items)
    return covered


def _is_announcement(rel: str) -> bool:
    return rel == ANNOUNCE_NAME or rel.endswith("/" + ANNOUNCE_NAME)


def _is_lore(rel: str) -> bool:
    if any(token in rel for token in NOISE_HINTS):
        return False
    return any(token in rel for token in LORE_HINTS)


def _render_page(client, title: str) -> tuple[str, int, str]:
    """取页面渲染后的 HTML 并转纯文本；返回 (text, revid, timestamp)。"""
    data = client.api(action="parse", page=title, prop="text",
                      disablelimitreport=1, disableeditsection=1)
    parsed = data.get("parse", {})
    text = html_to_text(parsed.get("text", ""))
    return text, int(parsed.get("revid", 0) or 0), parsed.get("timestamp", "")


@register
class ActivityCollector(Collector):
    name = "activity"
    title = "活动文本：活动公告 / 综合调查数据库 / 审判庭纪要 等活动专属长文"
    help = """抓取活动页面里不属于「关卡剧情」的正文。

\b
输出：OUT/activity/<活动名>/<子页面名>.txt
      OUT/activity/<活动名>/<子页面>/活动公告.txt

收录范围：
  * 所有 `活动公告` 子页面；
  * 名称命中 LORE_HINTS 的活动长文（综合调查数据库、审判庭纪要、待办事项记录、
    PRTS 金律记录、信息端口、PRTS 绿洲记录、日志、敌袭记录、剧情链……）。
自动排除关卡信息、商店、地图、合约指标、肉鸽图鉴等机制页；
avg / reclamation 已收录的页面不再重复；集成战略主题的图鉴与记录页仍由
roguelike 模块负责，这里只收它们各自的活动公告。

刷新方式与其它模块一致：changed（默认，按 revid）/ missing / force。
用 `-g 孤星` 可以只抓某个活动。"""
    order = 25

    @classmethod
    def params(cls) -> list:
        return [
            click.Option(["--no-announcements"], is_flag=True,
                         help="跳过所有「活动公告」，只收活动长文"),
            click.Option(["--min-cjk"], type=int, default=40, show_default=True,
                         help="正文少于该汉字数时视为无内容（默认 40）"),
            click.Option(["--refresh-index"], is_flag=True,
                         help="忽略子页面索引缓存，重新扫描所有活动子页面"),
        ]

    def run(self, ctx: Context) -> Stat:
        stat = Stat()
        out = ctx.out_dir / MODULE_DIR
        manifest = Manifest(out / "_manifest.json")

        self.header(ctx, "读取活动列表与子页面")
        nav_page = ctx.client.pages([NAV_PAGE], with_content=True).get(NAV_PAGE)
        if nav_page is None or not nav_page.content:
            ctx.log("  ! 无法读取剧情导航，活动列表为空")
            return stat

        # 复用 avg 的导航解析：分组名就是活动名
        from .avg import parse_nav_tables
        entries = parse_nav_tables(nav_page.content)
        groups: list[str] = []
        seen_groups: set[str] = set()
        for e in entries:
            group = (e.group or "").strip()
            if group and group not in GENERIC_GROUPS and group not in seen_groups:
                seen_groups.add(group)
                groups.append(group)
        # 复刻活动页（`孤星2024`、`长夜临光2022`…）不在剧情导航里，但每期都有
        # 「活动公告」；用 `分类:复刻活动` 补进来。它们通常没有独立长文。
        try:
            reruns = ctx.client.category("复刻活动")
        except Exception:
            reruns = []
        added = 0
        for group in reruns:
            group = (group or "").strip()
            if group and group not in seen_groups:
                seen_groups.add(group)
                groups.append(group)
                added += 1
        ctx.log(f"  活动 {len(groups)} 个（含复刻 {added} 个）")
        if ctx.keywords:
            groups = [g for g in groups if ctx.match(g)]

        from .roguelike import THEMES
        roguelike_groups = set(THEMES)
        covered = _covered_titles(ctx.out_dir)

        # 子页面索引缓存：活动列表每次从导航重建，但 `allpages` 枚举很贵
        # （114 个活动 = 114 次请求，容易触发 503）。缓存 7 天，
        # `--refresh-index` 可强制重扫；新活动（缓存里没有的组）仍会即时枚举。
        cache_path = out / CACHE_NAME
        cache: dict = {}
        if cache_path.exists():
            try:
                cache = json.loads(cache_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                cache = {}
        cached_groups: dict = cache.get("groups", {}) if isinstance(cache, dict) else {}
        cached_at = float(cache.get("generated_at_ts", 0) or 0) if isinstance(cache, dict) else 0
        cache_fresh = (time.time() - cached_at) < CACHE_TTL
        force_index = bool(ctx.extra.get("refresh_index"))
        reused = rescanned = failed = 0
        failed_groups: set[str] = set()
        subpages_by_group: dict[str, list[str]] = {}
        for group in groups:
            if cache_fresh and not force_index and group in cached_groups:
                subpages_by_group[group] = list(cached_groups[group])
                reused += 1
                continue
            found = _all_subpages(ctx.client, group)
            if found is None:
                failed += 1
                failed_groups.add(group)
                subpages_by_group[group] = list(cached_groups.get(group, []))
                continue
            subpages_by_group[group] = found
            rescanned += 1
        note = f"  子页面索引：复用 {reused} 个活动，重新枚举 {rescanned} 个活动"
        if failed:
            note += f"，失败 {failed} 个（沿用旧缓存）"
        ctx.log(note)
        for group in groups:
            if group not in failed_groups:
                cached_groups[group] = subpages_by_group[group]
        try:
            cache_path.write_text(json.dumps({
                "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "generated_at_ts": time.time() if rescanned else cached_at or time.time(),
                "groups": cached_groups,
            }, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass

        candidates: list[tuple[str, str, str, str]] = []   # (group, rel, title, kind)
        for group in groups:
            for title in subpages_by_group.get(group, []):
                rel = title[len(group):].lstrip("/")
                if not rel:
                    continue
                announcement = _is_announcement(rel)
                if announcement and ctx.extra.get("no_announcements"):
                    continue
                if not announcement:
                    # 肉鸽主题的图鉴 / 记录页由 roguelike 模块负责
                    if group in roguelike_groups:
                        continue
                    if not _is_lore(rel):
                        continue
                if title in covered:
                    continue
                kind = ANNOUNCE_NAME if announcement else "活动长文"
                candidates.append((group, rel, title, kind))

        # 同名路径去重（极少见，但避免互相覆盖）
        used: set[str] = set()
        unique: list[tuple[str, str, str, str]] = []
        for group, rel, title, kind in candidates:
            base = f"{sanitize(group)}/{sanitize_path(rel)}"
            path_key = base.lower()
            if path_key in used:
                continue
            used.add(path_key)
            unique.append((group, rel, title, kind))
        candidates = unique
        candidates.sort(key=lambda c: (natural_key(c[0]), natural_key(c[1])))
        ctx.log(f"  待检查 {len(candidates)} 个活动子页面")

        # ---------------- 版本检查 ----------------
        ctx.log("  检查版本 …")
        revs = ctx.client.revids([c[2] for c in candidates])
        todo: list[tuple[str, str, str, str, int, str]] = []
        for group, rel, title, kind in candidates:
            rec = revs.get(title)
            if rec is None or not rec.revid:
                stat.skipped_empty += 1
                continue
            path = out / sanitize(group) / sanitize_path(rel + ".txt")
            old = manifest.get(f"activity:{title}")
            if old.get("status") == "无正文" and old.get("revid") == rec.revid:
                stat.skipped_empty += 1
                continue
            if not need_update(ctx, manifest, f"activity:{title}", str(rec.revid), path.exists()):
                stat.skipped += 1
                continue
            todo.append((group, rel, title, kind, rec.revid, rec.timestamp))

        if ctx.dry_run:
            for group, rel, title, kind, _revid, _ts in todo[:50]:
                ctx.log(f"  · 将抓取 [{kind}] {title}")
            if len(todo) > 50:
                ctx.log(f"  …其余 {len(todo) - 50} 条省略")
            stat.dry_run_note = f"{len(todo)} 个页面待抓取"
            return stat

        ctx.log(f"  需要抓取 {len(todo)} 个页面")
        for i, (group, rel, title, kind, revid, rev_timestamp) in enumerate(todo, 1):
            try:
                text, parsed_revid, parsed_timestamp = _render_page(ctx.client, title)
            except Exception as exc:              # 单页失败不影响整批
                ctx.log(f"  ! {title} 抓取失败：{exc}")
                stat.skipped_empty += 1
                continue
            revid = parsed_revid or revid
            timestamp = parsed_timestamp or rev_timestamp
            key = f"activity:{title}"
            path = out / sanitize(group) / sanitize_path(rel + ".txt")

            if _cjk_count(text) < int(ctx.extra.get("min_cjk", 40)):
                manifest.record(key, str(revid), revid=revid, file="", activity=group,
                                page=title, kind=kind, status="无正文")
                stat.skipped_empty += 1
                continue

            head = [
                f"# {rel.split('/')[-1]}",
                f"- 活动：{group}",
                f"- 页面：{BASE}/w/{quote(title.replace(' ', '_'))}",
                f"- 类型：{kind}",
                f"- 版本：rev {revid}（{timestamp}）",
                "",
                f"- 抓取时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
                "",
                "---",
                "",
            ]
            rel_new = str(path.relative_to(out)).replace("\\", "/")
            write_text(path, "\n".join(head) + text.rstrip() + "\n", ignore_timestamps=True)

            old = manifest.get(key)
            rel_old = old.get("file", "")
            if rel_old and rel_old != rel_new:
                stale = out / rel_old
                if stale.exists():
                    stale.unlink()
            manifest.record(key, str(revid), revid=revid, file=rel_new, activity=group,
                            page=title, kind=kind, chars=len(text), status="已写入")
            stat.written += 1
            if ctx.verbose:
                ctx.log(f"  + {rel_new}")
            if i % 20 == 0:
                manifest.save()
                ctx.log(f"  …已处理 {i}/{len(todo)}")

        manifest.save()
        self._write_index(manifest, out)
        return stat

    @staticmethod
    def _write_index(manifest: Manifest, out: Path) -> None:
        import time
        rows = [v for v in manifest.items.values() if v.get("file")]
        by_activity: dict[str, list[dict]] = {}
        for info in rows:
            by_activity.setdefault(info.get("activity", "未分组"), []).append(info)
        lines = [
            "# PRTS 活动文本索引（activity）",
            "",
            f"生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}"
            f"　|　共 {len(rows)} 个文件　|　{len(by_activity)} 个活动",
            "",
            "> 由 prts_crawler.py activity 生成；收活动公告与活动专属长文，"
            "不重复 avg / roguelike / reclamation 的内容。",
            "",
        ]
        for activity in sorted(by_activity, key=natural_key):
            items = sorted(by_activity[activity], key=lambda x: natural_key(x.get("file", "")))
            lines += [f"## {activity}（{len(items)}）", ""]
            for info in items:
                rel = info.get("file", "")
                sub = rel.split("/", 1)[-1] if "/" in rel else rel
                chars = info.get("chars", 0)
                lines.append(f"- {sub}（{chars} 字，{info.get('kind', '')}）")
            lines.append("")
        write_text(out / "_索引.md", "\n".join(lines), ignore_timestamps=True)
