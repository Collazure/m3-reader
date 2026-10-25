#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""avg 剧情采集器：把「剧情一览」下的全部剧情文本抓成
`OUT/avg/<一级分类>/<章节>/<序号> <剧情名>.txt`（一级分类=主线/支线/联动/故事集/四月辑录）。

索引是自适应的（不硬编码任何章节）：
  * `Template:剧情导航` 的两张 wikitable → 分组 / 类型 / 顺序
  * `分类:剧情` 的全部成员        → 兜底发现新页面
  * 每个剧情页自带的 `剧情类型` / `剧情分组` → 决定落在哪个文件夹

同时对外提供 `folder_maps()`，给关卡文本采集器做「关卡 → 章节文件夹」的映射。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import click

from ..http import BASE
from ..output import Manifest, natural_key, sanitize, sanitize_path, write_text
from ..registry import Collector, Context, Stat, need_update, register
from ..story import extract_story

NAV_PAGE = "Template:剧情导航"
STORY_CATEGORY = "剧情"
MODULE_DIR = "avg"

CHAPTER_FOLDER = "第{n}章 {group}"
SIDE_FOLDER = "支线 {group}"
OTHER_FOLDER = "{category} {group}"

# avg 下的一级分类：把剧情按 主线 / 支线 / 联动 / 故事集 / 四月辑录 分开存
BUCKET_MAIN = "主线"
BUCKET_SIDE = "支线"
BUCKET_COLLAB = "联动"
BUCKET_TALES = "故事集"
BUCKET_APRIL = "四月辑录"
BUCKETS = (BUCKET_MAIN, BUCKET_SIDE, BUCKET_COLLAB, BUCKET_TALES, BUCKET_APRIL)
COLLAB_CATEGORY = "联动活动"      # PRTS 自带分类，用来判定联动剧情（含复刻）

GENERIC_GROUPS = {"剧情", "主线", "支线", "活动", "特殊", ""}
TYPE_TOKENS = {"主线", "支线", "剧情", "活动", "密录", "悖论模拟"}

# 交给专门模块处理的剧情（avg 不再收录）：
#   集成战略（肉鸽）→ prts_text/roguelike/
#   生息演算        → prts_text/reclamation/
# 干员密录由 operator 模块负责（`operator/<干员>/avgN-<密录名>.txt`）。
# 旧版 avg 会把它们误收进 `avg/特殊 <干员>/`，形成两份完全相同的正文；
# 这里统一跳过，并在每次运行开始时清掉旧清单里的重复文件。
MEMORY_TITLE_RE = re.compile(r"/干员密录/\d+$")

HANDOFF_CATEGORIES = {"集成战略", "生息演算"}
HANDOFF_GROUPS = {
    # 生息演算主题（首个主题「沙中之火」在导航表里被标成了支线，只能按分组名兜底）
    "沙中之火", "沙洲遗闻", "重启锚点",
    # 集成战略主题
    "刻俄柏的灰蕈迷境", "傀影与猩红孤钻", "水月与深蓝之树", "探索者的银凇止境",
    "萨卡兹的无终奇语", "岁的界园志异", "沉沦者的黑流树海",
}


def is_memory_title(title: str) -> bool:
    """是否是干员密录剧情页（由 operator 模块负责）。"""
    return bool(MEMORY_TITLE_RE.search(title.split("#", 1)[0].strip()))


def is_handed_off(nav_category: str, group: str, title: str = "") -> bool:
    """该剧情是否由别的模块负责（肉鸽 / 生息演算）。"""
    if nav_category in HANDOFF_CATEGORIES:
        return True
    if group in HANDOFF_GROUPS:
        return True
    stem = title.split("/", 1)[0]
    return bool(re.match(r"^(RO\d?|RA\d?|ISW)[-\s]", stem))

# 个别分组的文件夹名可以在这里手动覆盖（键=分组名，值=完整文件夹名）
# 例如 {"黑暗时代·上": "序章 黑暗时代·上"}
FOLDER_OVERRIDES: dict[str, str] = {}

# 生息演算的三个场次（对应关卡 id 里的 sandbox_0 / sandbox_1 / sandbox_2），
# 它们共用 RA-* 关卡代号，只能靠关卡 id 区分
SANDBOX_THEMES = ("沙中之火", "沙洲遗闻", "重启锚点")

NUM_PREFIX_RE = re.compile(r"^(\d+)\s*[-–—]")
NUM_ANY_RE = re.compile(r"^[A-Za-z]{1,4}(\d+)\s*[-–—]")
EP_PREFIX_RE = re.compile(r"^EP\s*(\d+)", re.I)


# --------------------------------------------------------------------- 索引

@dataclass
class NavEntry:
    title: str
    label: str
    group: str
    ntype: str
    category: str
    order: int


@dataclass
class StoryItem:
    title: str
    label: str
    order: int
    stype: str = ""
    group: str = ""
    nav_group: str = ""
    nav_type: str = ""
    nav_category: str = ""
    source: str = "nav"
    folder: str = ""
    filename: str = ""
    revid: int = 0
    timestamp: str = ""
    status: str = ""


LINK_RE = re.compile(r"\[\[([^\]\|]+)(?:\|([^\]]*))?\]\]")


def _split_cell(line: str) -> tuple[str, str]:
    """拆 '! width="120px"|黑暗时代·上' 为 (属性, 内容)。"""
    body = line[1:]
    if body.startswith("!"):
        body = body[1:]
    idx = body.find("|")
    if idx == -1:
        return "", body.strip()
    head = body[:idx]
    if "=" in head and "[[" not in head:
        return head, body[idx + 1:].strip()
    return "", body.strip()


def parse_nav_tables(wikitext: str) -> list[NavEntry]:
    """解析导航模板里的两张 wikitable（主线剧情一览 / 活动剧情一览）。"""
    entries: list[NavEntry] = []
    order = 0

    tables: list[list[list[tuple[str, str]]]] = []
    rows: list[list[tuple[str, str]]] | None = None
    cur: list[tuple[str, str]] | None = None
    in_table = False
    for raw in wikitext.splitlines():
        line = raw.rstrip()
        if line.startswith("{|"):
            in_table, rows, cur = True, [], None
            continue
        if not in_table:
            continue
        if line.startswith("|}"):
            if cur:
                rows.append(cur)
            tables.append(rows)
            in_table, rows, cur = False, None, None
            continue
        if line.startswith("|-"):
            if cur:
                rows.append(cur)
            cur = []
            continue
        if line.startswith("!") or line.startswith("|"):
            attrs, value = _split_cell(line)
            if cur is None:
                cur = []
            cur.append((attrs, value))
            continue
        if cur:
            attrs, value = cur[-1]
            cur[-1] = (attrs, value + "\n" + line.strip())

    for raw_rows in tables:
        carry: dict[int, list] = {}
        for raw_cells in raw_rows:
            cells: list[str] = []
            idx, col = 0, 0
            while True:
                if col in carry and carry[col][1] > 0:
                    cells.append(carry[col][0])
                    carry[col][1] -= 1
                    if carry[col][1] <= 0:
                        del carry[col]
                    col += 1
                    continue
                if idx >= len(raw_cells):
                    break
                attrs, value = raw_cells[idx]
                idx += 1
                m = re.search(r'rowspan\s*=\s*"?(\d+)', attrs)
                if m and int(m.group(1)) > 1:
                    carry[col] = [value, int(m.group(1)) - 1]
                cells.append(value)
                col += 1
            if len(cells) < 3 or "[[" not in cells[2]:
                continue
            c1, c2, c3 = cells[0].strip(), cells[1].strip(), cells[2].strip()
            if c2 in TYPE_TOKENS:
                category, group, ntype = "", c1, c2
            else:
                category, group, ntype = c1, c2, "剧情"
            for m in LINK_RE.finditer(c3):
                target = m.group(1).strip()
                label = (m.group(2) or target).strip()
                if target.startswith(("分类:", "文件:", "File:", "Category:", "#")):
                    continue
                order += 1
                entries.append(NavEntry(target, label, group, ntype, category, order))
    return entries


def build_index(nav_entries: list[NavEntry], category_titles: list[str],
                embedded_titles: list[str] | tuple[str, ...] = ()) -> list[StoryItem]:
    """导航条目 + 剧情模拟器嵌入页 + 分类成员 → 待处理清单（去重）。

    导航表提供活动分组和显示名；embeddedin 是所有实际含剧情模拟器页面的权威兜底；
    Category:剧情 保留作兼容补充，避免漏掉尚未嵌入模拟器的分类页。
    """
    items: list[StoryItem] = []
    seen: set[str] = set()
    for e in nav_entries:
        if e.title in seen:
            continue
        seen.add(e.title)
        items.append(StoryItem(title=e.title, label=e.label, order=e.order, stype=e.ntype,
                               group=e.group, nav_group=e.group, nav_type=e.ntype,
                               nav_category=e.category, source="nav"))
    extra = nav_entries[-1].order if nav_entries else 0
    for title in embedded_titles:
        if title in seen:
            continue
        seen.add(title)
        extra += 1
        items.append(StoryItem(title=title, label=title.split("/")[0], order=extra,
                               source="embeddedin"))
    for title in category_titles:
        if title in seen:
            continue
        seen.add(title)
        extra += 1
        items.append(StoryItem(title=title, label=title.split("/")[0], order=extra, source="category"))
    return items


def stage_number(title: str) -> int | None:
    """从标题推断章节号：'2-1 …/END'→2、'R8-1 …'→8、'EP09/ENTRY'→9。"""
    stem = title.split("/", 1)[0].strip()
    m = NUM_PREFIX_RE.match(stem) or NUM_ANY_RE.match(stem) or EP_PREFIX_RE.match(stem)
    return int(m.group(1)) if m else None


def group_chapter_numbers(nav_entries: list[NavEntry]) -> dict[str, int]:
    """按导航分组统计「主章节号」（取组内出现次数最多的编号）。"""
    buckets: dict[str, dict[int, int]] = {}
    for e in nav_entries:
        n = stage_number(e.title)
        if n is None:
            continue
        buckets.setdefault(e.group, {})[n] = buckets.setdefault(e.group, {}).get(n, 0) + 1
    return {g: max(c.items(), key=lambda kv: kv[1])[0] for g, c in buckets.items() if c}


def decide_folder(stype: str, group: str, nav_category: str, chapter_no: int | None,
                  bucket: str = "") -> str:
    """剧情文件夹名（一级分类之下）。

    有分类时去掉冗余前缀，路径读起来干净：
        主线/第2章 异卵同生   支线/巴别塔   联动/源石尘行动   故事集/战地秘闻
    没有分类的（集成战略 / 生息演算 / 四月辑录 / 特殊）保留原样：
        特殊/危机合约（未归类的大类统一放进 特殊/<大类>/）
    """
    if group in FOLDER_OVERRIDES:
        return FOLDER_OVERRIDES[group]
    if bucket == BUCKET_MAIN:
        return CHAPTER_FOLDER.format(n=chapter_no, group=group) if chapter_no is not None else group
    if bucket in (BUCKET_SIDE, BUCKET_COLLAB, BUCKET_TALES, BUCKET_APRIL):
        return group
    if stype == "主线" and chapter_no is not None:
        return CHAPTER_FOLDER.format(n=chapter_no, group=group)
    if stype in ("支线", "活动"):
        return SIDE_FOLDER.format(group=group)
    category = nav_category if nav_category and nav_category not in GENERIC_GROUPS else "特殊"
    return OTHER_FOLDER.format(category=category, group=group)


def decide_bucket(stype: str, nav_type: str, nav_category: str, group: str,
                  collabs: set[str]) -> str:
    """一级分类：主线 / 支线 / 联动 / 故事集 / 四月辑录；空串表示不分类（直接放 avg 根下）。

    判定依据：
      * 页面自带的「剧情类型」为 主线            → 主线
      * 支线/活动 + 活动名在 PRTS 的 分类:联动活动 → 联动
      * 支线/活动 的其它活动                      → 支线
      * 导航表里属于「活动剧情一览」且类型是「剧情」的行 → 故事集
        （战地秘闻、洪炉示岁这类故事集都是这种行）
      * 导航表大类是「四月辑录」                  → 四月辑录
      * 其它大类（特殊等）→ 不分类（保持原文件夹名）
    """
    if stype == "主线":
        return BUCKET_MAIN
    if stype in ("支线", "活动"):
        return BUCKET_COLLAB if is_collab(group, collabs) else BUCKET_SIDE
    if nav_category == BUCKET_APRIL:
        return BUCKET_APRIL
    if nav_category:                      # 特殊 / 其它大类
        return ""
    if stype == "剧情" or nav_type == "剧情":
        return BUCKET_TALES
    return ""


def is_collab(group: str, collabs: set[str]) -> bool:
    """活动名是否属于联动活动（分类里的复刻名如「源石尘行动2024」也算）。"""
    if not group:
        return False
    name = group.strip()
    for c in collabs:
        c = c.strip()
        if not c:
            continue
        if name == c or name.startswith(c) or c.startswith(name):
            return True
    return False


def fetch_collabs(client) -> set[str]:
    """PRTS 的 分类:联动活动 成员（含复刻场次）。"""
    try:
        return {t.strip() for t in client.category(COLLAB_CATEGORY) if t.strip()}
    except Exception:
        return set()


def story_filename(item: StoryItem) -> str:
    return sanitize(f"{item.order:04d} {item.label}.txt")


def scan_story_files(root: Path) -> dict[str, str]:
    """扫描输出目录里已有的剧情 txt（供 -m missing 使用）。"""
    found: dict[str, str] = {}
    if not root.exists():
        return found
    for path in root.rglob("*.txt"):
        try:
            if path.stat().st_size > 0:
                found[path.name] = str(path.relative_to(root)).replace("\\", "/")
        except OSError:
            continue
    return found


# --------------------------------------------------------------------- 采集器

@register
class AvgCollector(Collector):
    name = "avg"
    title = "avg 剧情文本（主线 / 支线 / 联动 / 故事集 / 四月辑录）"
    help = """抓取「剧情一览」里的全部剧情文本，按一级分类存放：

\b
输出：OUT/avg/<一级分类>/<章节文件夹>/<顺序号> <剧情名>.txt
  * 主线     → 第N章 <章节名>   （N 由关卡编号推断，如 14-23 → 第14章）
  * 支线活动 → 支线 <活动名>
  * 联动     → 联动 <活动名>
  * 故事集   → 故事集 <活动名>
  * 四月辑录 → 四月辑录 <活动名>
  其余未归类的大类 → <大类> <故事名>（如 特殊 危机合约）

集成战略（肉鸽）与生息演算的剧情不在 avg，分别由 roguelike / reclamation 模块负责。

索引每次运行都重新从 wiki 构建（Template:剧情导航 + embeddedin 模板:剧情模拟器 + 分类:剧情），
所以 wiki 之后新增的章节、活动、故事集会被自动发现并新建文件夹。

三种刷新模式（-m/--mode）：
  changed（默认）按 wiki 版本号增量更新；missing 只补本地没有的；force 全部重抓。
"""
    order = 10

    @classmethod
    def params(cls) -> list:
        return [
            click.Option(["--list", "list_only"], is_flag=True,
                         help="只列出索引（分组 + 剧情名），不下载"),
            click.Option(["--format", "fmt"], type=click.Choice(["dialogue", "plain"]),
                         default="dialogue", show_default=True,
                         help="dialogue=带角色名；plain=纯文本"),
            click.Option(["--merge-speaker"], is_flag=True, help="同一角色的连续台词合并成段"),
            click.Option(["--keep-directives"], is_flag=True, help="保留 [Character(...)] 等演出指令行"),
        ]

    # ---------------- 主流程 ----------------
    def run(self, ctx: Context) -> Stat:
        stat = Stat()
        out = ctx.out_dir / MODULE_DIR
        manifest = Manifest(out / "_manifest.json")

        self._cleanup_memories(ctx, out, manifest)

        self.header(ctx, "读取剧情索引")
        nav_page = ctx.client.pages([NAV_PAGE], with_content=True).get(NAV_PAGE)
        nav_entries = parse_nav_tables(nav_page.content) if nav_page and nav_page.content else []
        embedded_titles = ctx.client.embedded_in("剧情模拟器")
        category_titles = ctx.client.category(STORY_CATEGORY)
        ctx.log(f"  导航表 {len(nav_entries)} 条 / 嵌入剧情模拟器 {len(embedded_titles)} 页"
                f" / 分类:{STORY_CATEGORY} {len(category_titles)} 页")

        items = build_index(nav_entries, category_titles, embedded_titles)
        memories = [it for it in items if is_memory_title(it.title)]
        if memories:
            ctx.log(f"  干员密录 {len(memories)} 条由 operator 模块负责，avg 跳过")
        items = [it for it in items if not is_memory_title(it.title)]
        items = [it for it in items if ctx.match(it.label, it.group, it.nav_group, it.title)]
        if ctx.limit:
            items = items[:ctx.limit]
        ctx.log(f"  待处理 {len(items)} 条")

        collabs = fetch_collabs(ctx.client)
        ctx.log(f"  联动活动（分类:{COLLAB_CATEGORY}）：{len(collabs)} 个")

        if ctx.extra.get("list_only"):
            for it in items:
                tag = it.group or it.nav_group or "（未知分组）"
                ctx.log(f"[{it.order:4d}] {tag:<16} {it.stype or '?':<4} {it.title}")
            stat.dry_run_note = f"共 {len(items)} 条"
            return stat

        ctx.log("  检查版本 …")
        revs = ctx.client.revids([it.title for it in items])

        existing: dict[str, str] = {}
        if ctx.mode == "missing":
            existing = scan_story_files(out)
            ctx.log(f"  missing 模式：目录中已有 {len(existing)} 个剧情文件")

        todo: list[StoryItem] = []
        for it in items:
            rec = revs.get(it.title)
            if rec is None or not rec.revid:
                it.status = "页面不存在"
                stat.skipped_empty += 1
                continue
            it.revid, it.timestamp = rec.revid, rec.timestamp
            old = manifest.get(it.title)

            # 肉鸽 / 生息演算的剧情交给各自的模块（roguelike / reclamation）
            if is_handed_off(it.nav_category, it.group or it.nav_group, it.title):
                it.status = "归 roguelike/reclamation 模块"
                stat.skipped += 1
                continue

            if ctx.mode == "missing":
                rel = existing.get(story_filename(it))
                if rel:
                    it.status = "已存在"
                    it.folder = rel.rsplit("/", 1)[0] if "/" in rel else ""
                    it.filename = Path(rel).name
                    self._record(manifest, it, file=rel)
                    stat.skipped += 1
                    continue
                if old and not old.get("file") and old.get("revid") == rec.revid:
                    it.status = "无剧情文本"
                    stat.skipped_empty += 1
                    continue
                todo.append(it)
                continue

            rel = old.get("file") or ""
            exists = bool(rel) and (out / rel).exists()
            if not rel and old.get("revid") == rec.revid:
                it.status = "无剧情文本"       # 纯演出/过场页，版本没变就不再重试
                stat.skipped_empty += 1
                continue
            if not need_update(ctx, manifest, it.title, str(rec.revid), exists):
                it.status = "未变化"
                it.folder = old.get("folder", "")
                it.filename = Path(rel).name if rel else ""
                stat.skipped += 1
                continue
            todo.append(it)

        if ctx.dry_run:
            for it in todo[:50]:
                ctx.log(f"  · 将抓取 {it.title}")
            if len(todo) > 50:
                ctx.log(f"  …其余 {len(todo) - 50} 条省略")
            stat.dry_run_note = f"{len(todo)} 条待抓取"
            return stat

        ctx.log(f"  需要抓取 {len(todo)} 条")
        if todo:
            docs = ctx.client.pages([it.title for it in todo], with_content=True)
            chapter_nos = group_chapter_numbers(nav_entries)
            fetch = make_raw_fetcher(ctx)
            for it in todo:
                rec = docs.get(it.title)
                if rec is None or not rec.content:
                    it.status = "无内容"
                    stat.skipped_empty += 1
                    continue
                doc = extract_story(
                    rec.content, fetch=fetch, page_title=it.title,
                    log=ctx.log if ctx.verbose else (lambda *_: None),
                    keep_directives=bool(ctx.extra.get("keep_directives")),
                    fmt=ctx.extra.get("fmt", "dialogue"),
                    merge_speaker=bool(ctx.extra.get("merge_speaker")),
                )
                if not doc.blocks:
                    it.status = "无剧情文本"
                    it.stype = doc.meta.get("剧情类型", "") or it.stype
                    it.group = doc.meta.get("剧情分组", "") or it.group
                    self._record(manifest, it, file="")
                    stat.skipped_empty += 1
                    continue

                stype = doc.meta.get("剧情类型", "") or it.stype or "剧情"
                group = doc.meta.get("剧情分组", "")
                if group in GENERIC_GROUPS:
                    group = it.label or it.nav_group or it.title.split("/")[0]
                chapter_no = stage_number(it.title)
                if chapter_no is None and it.nav_type == "主线":
                    chapter_no = chapter_nos.get(it.nav_group)
                it.stype, it.group = stype, group
                bucket = decide_bucket(stype, it.nav_type, it.nav_category, group, collabs)
                folder = decide_folder(stype, group, it.nav_category, chapter_no, bucket)
                it.folder = f"{bucket}/{folder}" if bucket else folder
                it.filename = story_filename(it)

                rel_new = f"{sanitize_path(it.folder)}/{it.filename}"
                path = out / rel_new
                path.parent.mkdir(parents=True, exist_ok=True)
                write_text(path, self._render_file(it, doc), ignore_timestamps=True)
                rel_old = (manifest.get(it.title) or {}).get("file", "")
                if rel_old and rel_old != rel_new:
                    stale = out / rel_old
                    if stale.exists():
                        stale.unlink()
                it.status = "已更新" if rel_old else "已新增"
                self._record(manifest, it, file=rel_new)
                stat.written += 1
                if ctx.verbose:
                    ctx.log(f"  + {rel_new}")
                if stat.written % 200 == 0:
                    manifest.save()
                    ctx.log(f"  …已写入 {stat.written} 个文件")

        manifest.save()
        self._write_toc(manifest, out)
        return stat

    # ---------------- 内部 ----------------
    def _cleanup_memories(self, ctx: Context, out: Path, manifest: Manifest) -> None:
        """清掉旧版 avg 误收的干员密录（已由 operator 模块保存）。

        只删除清单里记录过、且 operator/<干员>/ 确实已有密录的文件；
        不认识的文件一律不碰。删除后顺手移除空的 `特殊 <干员>` 目录。
        """
        removed = dropped = 0
        operators = ctx.out_dir / "operator"
        for key, info in list(manifest.items.items()):
            if not (is_memory_title(key) or info.get("type") == "干员密录"):
                continue
            operator = key.split("/干员密录/", 1)[0]
            if not operator or not (operators / sanitize(operator)).is_dir():
                continue          # operator 还没有这份密录，先留着，避免丢内容
            if ctx.dry_run:
                removed += 1
                continue
            rel = info.get("file", "")
            path = out / rel if rel else None
            try:
                if path is not None and path.is_file():
                    path.unlink()
                    removed += 1
                parent = path.parent if path is not None else None
                while parent is not None and parent != out and parent.is_dir():
                    try:
                        parent.rmdir()
                    except OSError:
                        break
                    parent = parent.parent
            except OSError:
                continue
            manifest.drop(key)
            dropped += 1
        if dropped:
            manifest.save()
        if removed:
            verb = "将清理" if ctx.dry_run else "已清理"
            ctx.log(f"  {verb} avg 中重复的干员密录 {removed} 个文件")

    @staticmethod
    def _record(manifest: Manifest, it: StoryItem, file: str) -> None:
        manifest.record(
            it.title, str(it.revid), revid=it.revid, file=file, folder=it.folder,
            label=it.label, type=it.stype, group=it.group, timestamp=it.timestamp,
            source=it.source, status=it.status,
        )

    @staticmethod
    def _render_file(it: StoryItem, doc) -> str:
        body = [f"# {it.label}", "",
                f"- 剧情类型：{it.stype}",
                f"- 剧情分组：{it.group}",
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
    def _write_toc(manifest: Manifest, out: Path) -> None:
        by_folder: dict[str, list[str]] = {}
        empty: list[str] = []
        for title, info in manifest.items.items():
            rel = info.get("file")
            if not rel:
                empty.append(title)
                continue
            by_folder.setdefault(info.get("folder", "未分组"), []).append(Path(rel).name)
        lines = ["# PRTS 剧情文本索引（avg）", "",
                 f"生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}"
                 f"　|　共 {len(manifest.items) - len(empty)} 段剧情　|　{len(by_folder)} 个分组", "",
                 "> 由 prts_crawler.py avg 生成；重跑会自动收录 wiki 新增的剧情。", ""]
        order = {b: i for i, b in enumerate(BUCKETS)}
        for folder in sorted(by_folder, key=lambda f: (order.get(f.split("/")[0], 9), natural_key(f))):
            rows = sorted(by_folder[folder], key=natural_key)
            lines += [f"## {folder}（{len(rows)}）", ""]
            if (out / sanitize_path(folder) / "关卡文本.txt").exists():
                lines.append("- 关卡文本")
            lines += [f"- {name[:-4] if name.endswith('.txt') else name}" for name in rows]
            lines.append("")
        if empty:
            lines += [f"## 无正文的页面（{len(empty)}）", "",
                      "以下页面在 wiki 上只有演出或视频，没有可抓取的台词：", ""]
            lines += [f"- {t}" for t in sorted(empty)]
            lines.append("")
        write_text(out / "_索引.md", "\n".join(lines), ignore_timestamps=True)


def make_raw_fetcher(ctx: Context):
    """给跨页引用（{{#lst:页面|小节}}）用的取页面函数（带缓存）。"""
    cache: dict[str, str] = {}

    def fetch(title: str) -> str:
        if title not in cache:
            cache[title] = ctx.client.raw(title)
        return cache[title]

    return fetch


# --------------------------------------------------------------------- 供其它模块复用

def folder_maps(out_dir: Path) -> tuple[dict[int, str], dict[str, str], list[str]]:
    """从 avg（以及生息演算）的清单推出「章节号 → 文件夹」「字母前缀 → 文件夹」映射。

    文件夹可能带一级分类前缀（如 `主线/第2章 异卵同生`），分类时只看最后一段，
    但返回给调用方的仍是完整相对路径。
    """
    by_chapter: dict[int, str] = {}
    by_prefix: dict[str, str] = {}
    folders: list[str] = []
    # 返回的是「相对输出根目录」的路径（含模块名），方便关卡文本直接落盘
    sources = [(out_dir / MODULE_DIR / "_manifest.json", f"{MODULE_DIR}/"),
               (out_dir / "reclamation" / "_manifest.json", "reclamation/")]
    for man_path, prefix in sources:
        manifest = Manifest(man_path)
        for title, info in manifest.items.items():
            folder = info.get("folder") or ""
            if not folder:
                continue
            full = f"{prefix}{folder}"
            if full not in folders:
                folders.append(full)
            leaf = leaf_folder(full)
            m = re.match(r"^第(\d+)章", leaf)
            if m:
                by_chapter[int(m.group(1))] = full
                continue
            pre = re.match(r"^([A-Za-z]+)", title.split("/", 1)[0])
            if pre:
                by_prefix.setdefault(pre.group(1).upper(), full)
    return by_chapter, by_prefix, folders


MODULE_PREFIXES = {"avg", "reclamation", "roguelike", "operator", "furniture", "enemies", "terra"}


def leaf_folder(folder: str) -> str:
    """去掉模块前缀与一级分类，返回真正的文件夹名。

    `avg/主线/第2章 异卵同生` → `第2章 异卵同生`；
    `reclamation/沙洲遗闻` → `沙洲遗闻`。
    """
    parts = [p for p in folder.split("/") if p]
    while parts and parts[0] in MODULE_PREFIXES:
        parts.pop(0)
    while parts and parts[0] in BUCKETS:
        parts.pop(0)
    return "/".join(parts)


def folder_for_stage(code: str, zone: str, by_chapter: dict[int, str],
                     by_prefix: dict[str, str], folders: list[str],
                     title: str = "", stage_id: str = "") -> str | None:
    """把关卡代号 / 关卡id / 标题 / 所属区域映射到剧情文件夹。

    顺序：
      1. 关卡 id 里的生息演算场次（sandbox_0=沙中之火、sandbox_1=沙洲遗闻、sandbox_2=重启锚点，
         三个场次共用 RA-* 代号，只能靠这个区分）
      2. 代号里的章号（17-1 / H17-1 → 第17章）
      3. 标题里带括号限定或直接出现的主题名（「RA-NO 驻扎地(沙洲遗闻)」）
      4. 代号字母前缀
      5. 所属区域模糊匹配
    """
    leaves = {leaf_folder(f).split("/")[-1]: f for f in folders}
    m = re.match(r"^sandbox_(\d+)_", stage_id or "")
    if m:
        idx = int(m.group(1))
        if idx < len(SANDBOX_THEMES):
            folder = leaves.get(SANDBOX_THEMES[idx])
            if folder:
                return folder
    if title:
        for name, folder in leaves.items():
            # 标题里带括号限定（沙洲遗闻的关卡都写成「xxx(沙洲遗闻)」）
            if re.search(r"[（(]" + re.escape(name) + r"[）)]", title):
                return folder
    stem = (code or "").strip()
    m = re.match(r"^([HS]?\d+)\s*[-–—]", stem)
    if m:
        folder = by_chapter.get(int(re.sub(r"^\D+", "", m.group(1))))
        if folder:
            return folder
    if title:
        for name, folder in leaves.items():
            if len(name) >= 3 and name in title:
                return folder
    m = re.match(r"^([A-Za-z]+)", stem)
    if m and m.group(1).upper() in by_prefix:
        return by_prefix[m.group(1).upper()]
    zone = (zone or "").strip()
    if zone:
        zone_norm = zone.replace(" ", "")
        best: tuple[int, str] | None = None
        for folder in folders:
            name = re.sub(r"^(第\d+章|支线|特殊|集成战略|生息演算|四月辑录)\s*", "", leaf_folder(folder))
            if name and name.replace(" ", "") in zone_norm:
                if best is None or len(name) > best[0]:
                    best = (len(name), folder)
        if best:
            return best[1]
    return None
