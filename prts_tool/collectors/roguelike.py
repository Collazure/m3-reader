#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""集成战略（肉鸽）文本采集器。

不同主题的网页结构差别很大，所以这里对每个主题「量身打造」一套解析方式，
共用一个输出骨架：

    OUT/roguelike/<主题>/
    ├── 事件/<事件大类>/<事件名>.txt     各分支及其文本
    ├── 藏品.txt                          按藏品分类分组（分类为主标题、藏品名为次级标题）
    ├── 结局/结局N <名称>/avg.txt         avg 剧情
    │                    /partN.txt       该结局附带的其它文本
    ├── 月度小队/<小队名或角色名>.txt      通讯记录（Part.01、Part.02…）
    ├── 关卡.txt                          各关卡名 + 关卡描述
    ├── 加载文本.txt                       过场/加载界面出现的剧情文本
    └── 其他文本/                          其它结构性可抓的剧情文本

已实现全部 7 个主题，各主题的网页结构差别很大，因此在 THEMES 里逐个配置
（事件用哪套模板、藏品/记录页叫什么、月度小队是按小队还是按角色）：
  * 刻俄柏的灰蕈迷境（RO）       事件用 {{集成战略事件}}，收藏品在「收藏品图鉴」，无月度小队
  * 傀影与猩红孤钻（RO1）        事件用 {{ISEvent/scene}}，收藏品在「长生者宝盒」，
                                月度小队通讯记录（Part.01~03）在「猩红珍藏」
  * 水月与深蓝之树（RO2）        事件同为 scene 式，藏品页「生物制品陈设」，
  * 探索者的银凇止境（RO3）      藏品页「仪式用品索引」，
  * 萨卡兹的无终奇语（RO4）      藏品页「想象实体图鉴」，
  * 岁的界园志异（RO5）          藏品页「珍玩集册」，
  * 沉沦者的黑流树海（RO6）      藏品页「拟造物质编目」，
                                以上五者的记录页与月度小队目录名各不相同

想再加一个主题：在下面的 THEMES 里加一条 ThemeSpec（页面名 + 解析方式 + 小节名），
必要时补一个解析函数即可（event_style 决定事件用哪套解析）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import click

from ..http import BASE
from ..output import Manifest, natural_key, sanitize, signature, write_text
from ..registry import Collector, Context, Stat, need_update, register
from ..story import extract_story
from ..wikitext import (balanced, clean_markup, flavor_text, iter_templates, plain_text,
                        section_text, split_params, strip_templates, template_params,
                        unwrap_templates)
from .avg import make_raw_fetcher

MODULE_DIR = "roguelike"
STAGE_LIST_PAGE = "关卡一览/活动关卡"
CN_NUM = "零一二三四五六七八九十"

EVENT_DIR = "事件"
RELIC_FILE = "藏品.txt"
ENDING_DIR = "结局"
MONTHLY_DIR = "月度小队"
STAGE_FILE = "关卡.txt"
LOADING_FILE = "加载文本.txt"
EXTRA_DIR = "其他文本"


# ====================================================================== 通用解析

def split_sections(raw: str) -> list[tuple[int, str, str]]:
    """把 wikitext 按 == / === / ==== 标题切成 [(层级, 标题, 正文), ...]。"""
    out: list[tuple[int, str, str]] = []
    marks = [(m.start(), len(m.group(1)), m.group(2).strip()) for m in
             re.finditer(r"^(={2,4})\s*([^=\n]+?)\s*\1\s*$", raw, re.M)]
    for i, (pos, level, title) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(raw)
        out.append((level, title, raw[pos:end]))
    return out


def cn_ordinal(n: int) -> str:
    """1 → 一，2 → 二 ……（只用到十几）。"""
    if n <= 10:
        return CN_NUM[n]
    if n < 20:
        return "十" + CN_NUM[n - 10]
    return str(n)


def render_dialogue_table(block: str) -> str:
    """把「头像 + 台词」的表格渲染成 `角色：台词`。

    用于月度小队的通讯记录（Part.01/02/03）这类结构：
        |[[文件:头像 华法琳.png|40px|link=]]
        | style="text-align:left;" |所以说，我们血魔一般只会给有亲密联系的人打上烙印。
    """
    lines: list[str] = []
    speaker = ""
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line.startswith("|") or line.startswith(("|-", "|}", "|+", "!")):
            continue
        body = line[1:]
        if "|" in body and re.match(r"^\s*(rowspan|colspan|style|class)\s*=", body):
            body = body.split("|", 1)[1]
        body = body.strip()
        if not body:
            continue
        m = re.match(r"\[\[文件:头像\s*([^\|\]]+)[^\]]*\]\]", body)
        if m:
            speaker = re.sub(r"\.(png|jpg|jpeg)\s*$", "", m.group(1).strip(), flags=re.I).strip()
            body = body[m.end():].strip()
            if not body:
                continue
        text = plain_text(body)
        if not text:
            continue
        lines.append(f"{speaker}：{text}" if speaker else text)
    return "\n".join(lines)


PART_RE = re.compile(r"'''\s*(?:Part\.?|PART)\s*0*(\d+)\s*'''", re.I)


def render_story_block(seg: str) -> str:
    """渲染一个 Part 段落：有头像行的按对话渲染，否则按 <poem> 正文渲染。"""
    if "文件:头像" in seg:
        return render_dialogue_table(seg)
    text = re.sub(r"<poem>|</poem>", "", seg)
    text = re.sub(r"<small>.*?</small>", "", text, flags=re.S)
    text = re.sub(r"'''?", "", text)
    text = re.sub(r"\{\{[^{}]*\}\}", "", text)
    out: list[str] = []
    for line in clean_markup(text).splitlines():
        line = line.strip()
        if not line or line.startswith(("{|", "|}", "|-", "!", "|+", "<")):
            continue
        line = line.lstrip("|").strip()
        if "|" in line:
            head, _, tail = line.partition("|")
            if ATTR_RE.match(head) or head.startswith(("style", "class", "css")):
                line = tail.strip()
        line = line.strip().strip("|").strip()
        if line:
            out.append(line)
    return "\n".join(out)


def render_parts(block: str) -> list[tuple[str, str]]:
    """把带 `Part.01` / `PART 01` 标记的表格块拆成 [(part 标题, 文本)]。"""
    marks = [(m.start(), m.group(1)) for m in PART_RE.finditer(block)]
    if not marks:
        return []
    out: list[tuple[str, str]] = []
    for i, (pos, num) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(block)
        seg = block[pos:end]
        # 去掉 Part 标题行上的解锁条件说明
        seg = re.sub(r"'''.*?'''\s*(<small>.*?</small>)?", "", seg, count=1, flags=re.S)
        out.append((f"Part.{int(num):02d}", render_story_block(seg)))
    return out


# ====================================================================== 主题配置

@dataclass
class ThemeSpec:
    key: str                       # 本地目录名
    page: str                      # 主题主页面
    event_page: str                # 事件一览页面（可多个）
    event_style: str               # "template"（灰蕈迷境）或 "scene"（其余主题）
    relics: list[tuple[str, str]]  # [(标题, 藏品页面)]
    stage_section: str             # 关卡一览/活动关卡 中的小节标题
    code: str = ""                 # 剧情页前缀，如 RO1 / RO2（用于自动发现序章与结局）
    endings: list[tuple[int, str, str]] = field(default_factory=list)
    monthly: dict = field(default_factory=dict)   # 月度小队（各主题名称不同）
    ending_notes: dict = field(default_factory=dict)   # 结局额外说明的页面（如「戏剧彩排」）
    loading: list[tuple[str, str, str, str]] = field(default_factory=list)  # [(小标题, 页面, 小节, 模式)]
    extras: list[tuple[str, str, str, str]] = field(default_factory=list)
    # extras: [(文件名, 页面, 小节, 模式)] 模式 = "section" / "gallery"


# 各主题的记录页里「PRTS额外资料 → 探索情报板」的小节（名字基本一致，个别主题少几节）
LOADING_SECTIONS = ("主题专属贴士", "故事的引言", "背景故事", "探索途中", "探索之外")


def _loading(record_page: str) -> list[tuple[str, str, str, str]]:
    return [(name, record_page, name, "tips" if name == "主题专属贴士" else "")
            for name in LOADING_SECTIONS]


def _base_extras(theme: str, record_page: str, gallery: str) -> list[tuple[str, str, str, str]]:
    return [("区域", theme, "区域", "section"),
            (gallery, record_page, gallery, "gallery")]


THEMES: dict[str, ThemeSpec] = {
    "刻俄柏的灰蕈迷境": ThemeSpec(
        key="刻俄柏的灰蕈迷境", code="RO",
        page="刻俄柏的灰蕈迷境",
        event_page="刻俄柏的灰蕈迷境/事件一览",
        event_style="template",
        relics=[("收藏品图鉴", "刻俄柏的灰蕈迷境/收藏品图鉴")],
        endings=[(1, "迷尘幻梦", "RO-END-1/NBT"),
                 (2, "茫然行者", "RO-END-2/NBT"),
                 (3, "归于荒野", "RO-END-3/NBT")],
        stage_section="刻俄柏的灰蕈迷境",
        monthly={},
        loading=[],       # 首个主题在 wiki 上没有专门的过场文本页面
        extras=[("区域", "刻俄柏的灰蕈迷境", "区域", "section")],
    ),
    "傀影与猩红孤钻": ThemeSpec(
        key="傀影与猩红孤钻", code="RO1",
        page="傀影与猩红孤钻",
        event_page="傀影与猩红孤钻/事件一览",
        event_style="scene",
        relics=[("长生者宝盒", "傀影与猩红孤钻/长生者宝盒")],
        endings=[(1, "舞会终场", "RO1-END-1/NBT"),
                 (2, "滑稽喜剧", "RO1-END-2/NBT"),
                 (3, "盛大揭幕", "RO1-END-3/NBT"),
                 (4, "沉默之章", "RO1-END-4/NBT")],
        stage_section="傀影与猩红孤钻",
        monthly={"page": "傀影与猩红孤钻/月度小队",
                 "story_page": "傀影与猩红孤钻/猩红珍藏",
                 "story_section": "通讯记录仪",
                 "dir": "月度小队",
                 "kind": "squad"},
        ending_notes={"page": "傀影与猩红孤钻/猩红珍藏", "section": "戏剧彩排"},
        loading=_loading("傀影与猩红孤钻/猩红珍藏"),
        extras=_base_extras("傀影与猩红孤钻", "傀影与猩红孤钻/猩红珍藏", "过往演出展览")
        + [("深入调查", "傀影与猩红孤钻/深入调查", "", "section"),
           ("幻觉报告册", "傀影与猩红孤钻/猩红珍藏", "幻觉报告册", "section"),
           ("战术道具箱", "傀影与猩红孤钻/猩红珍藏", "战术道具箱", "section"),
           ("活页剧目集", "傀影与猩红孤钻/猩红珍藏", "活页剧目集", "section")],
    ),
    "水月与深蓝之树": ThemeSpec(
        key="水月与深蓝之树", code="RO2",
        page="水月与深蓝之树",
        event_page="水月与深蓝之树/事件一览",
        event_style="scene",
        relics=[("生物制品陈设", "水月与深蓝之树/生物制品陈设")],
        endings=[(1, "平凡即是喜乐", "RO2-END-1/NBT"),
                 (2, "静谧时代", "RO2-END-2/NBT"),
                 (3, "息潮的代价", "RO2-END-3/NBT"),
                 (4, "如星空般深蓝", "RO2-END-4/NBT")],
        stage_section="水月与深蓝之树",
        monthly={"page": "水月与深蓝之树/追忆映射",
                 "story_page": "水月与深蓝之树/深蓝记录仪",
                 "story_section": "万象追忆录",
                 "dir": "追忆映射",
                 "kind": "operator"},
        loading=_loading("水月与深蓝之树/深蓝记录仪"),
        extras=_base_extras("水月与深蓝之树", "水月与深蓝之树/深蓝记录仪", "影印展览")
        + [("深入探索", "水月与深蓝之树/深入探索", "", "section"),
           ("壳中回响", "水月与深蓝之树/深蓝记录仪", "壳中回响", "section"),
           ("刻时碑林", "水月与深蓝之树/深蓝记录仪", "刻时碑林", "section")],
    ),
    "探索者的银凇止境": ThemeSpec(
        key="探索者的银凇止境", code="RO3",
        page="探索者的银凇止境",
        event_page="探索者的银凇止境/事件一览",
        event_style="scene",
        relics=[("仪式用品索引", "探索者的银凇止境/仪式用品索引")],
        endings=[(1, "越过群山", "RO3-END-1/NBT"),
                 (2, "直至冬夜降临", "RO3-END-2/NBT"),
                 (3, "自深处的一瞥", "RO3-END-3/NBT"),
                 (4, "终始", "RO3-END-4/NBT")],
        stage_section="探索者的银凇止境",
        monthly={"page": "探索者的银凇止境/探索者档案",
                 "story_page": "探索者的银凇止境/冬夜展览馆",
                 "story_section": "队员访谈录",
                 "dir": "探索者档案",
                 "kind": "operator"},
        loading=_loading("探索者的银凇止境/冬夜展览馆"),
        extras=_base_extras("探索者的银凇止境", "探索者的银凇止境/冬夜展览馆", "留影展览")
        + [("深入调查", "探索者的银凇止境/深入调查", "", "section"),
           ("边缘历史集", "探索者的银凇止境/冬夜展览馆", "边缘历史集", "section"),
           ("坍缩范式辑录", "探索者的银凇止境/冬夜展览馆", "坍缩范式辑录", "section"),
           ("密文板研究", "探索者的银凇止境/密文板研究", "",
            "items:探索者的银凇止境/密文板")],
    ),
    "萨卡兹的无终奇语": ThemeSpec(
        key="萨卡兹的无终奇语", code="RO4",
        page="萨卡兹的无终奇语",
        event_page="萨卡兹的无终奇语/事件一览",
        event_style="scene",
        relics=[("想象实体图鉴", "萨卡兹的无终奇语/想象实体图鉴")],
        endings=[(1, "憧憬未来", "RO4-END-1/NBT"),
                 (2, "双王记", "RO4-END-2/NBT"),
                 (3, "天使之城", "RO4-END-3/NBT"),
                 (4, "遁入阇那", "RO4-END-4/NBT"),
                 (5, "无瑕之日", "RO4-END-5/NBT")],
        stage_section="萨卡兹的无终奇语",
        monthly={"page": "萨卡兹的无终奇语/讲述者列表",
                 "story_page": "萨卡兹的无终奇语/巫仪档案库",
                 "story_section": "遐想交织录",
                 "dir": "讲述者列表",
                 "kind": "operator"},
        loading=_loading("萨卡兹的无终奇语/巫仪档案库"),
        extras=_base_extras("萨卡兹的无终奇语", "萨卡兹的无终奇语/巫仪档案库", "虚构展览")
        + [("深入探索", "萨卡兹的无终奇语/深入探索", "", "section"),
           ("年代追忆", "萨卡兹的无终奇语/巫仪档案库", "年代追忆", "section"),
           ("预言诗篇", "萨卡兹的无终奇语/巫仪档案库", "预言诗篇", "section"),
           ("佚散思维辑录", "萨卡兹的无终奇语/佚散思维辑录", "",
            "items:萨卡兹的无终奇语/思绪")],
    ),
    "岁的界园志异": ThemeSpec(
        key="岁的界园志异", code="RO5",
        page="岁的界园志异",
        event_page="岁的界园志异/事件一览",
        event_style="scene",
        relics=[("珍玩集册", "岁的界园志异/珍玩集册")],
        endings=[(1, "依律镇抚", "RO5-END-1/NBT"),
                 (2, "长卷留痕", "RO5-END-2/NBT"),
                 (3, "黑白入玄", "RO5-END-3/NBT"),
                 (4, "无中生有", "RO5-END-4/NBT"),
                 (5, "落子无悔", "RO5-END-5/NBT")],
        stage_section="岁的界园志异",
        monthly={"page": "岁的界园志异/游览者列表",
                 "story_page": "岁的界园志异/见字图册",
                 "story_section": "游园访谈",
                 "dir": "游园访谈",       # 该主题的月度小队叫「游园访谈」
                 "kind": "operator"},
        loading=_loading("岁的界园志异/见字图册"),
        extras=_base_extras("岁的界园志异", "岁的界园志异/见字图册", "戏剧展演")
        + [("深入探索", "岁的界园志异/深入探索", "", "section"),
           ("秉烛岁谱", "岁的界园志异/见字图册", "秉烛岁谱", "section"),
           ("古韵今音", "岁的界园志异/见字图册", "古韵今音", "section"),
           ("界园秘辛", "岁的界园志异/见字图册", "界园秘辛", "section"),
           ("藏钱木盒", "岁的界园志异/藏钱木盒", "",
            "items:岁的界园志异/通宝"),
           ("易与", "岁的界园志异/易与", "互动记录", "section")],
    ),
    "沉沦者的黑流树海": ThemeSpec(
        key="沉沦者的黑流树海", code="RO6",
        page="沉沦者的黑流树海",
        event_page="沉沦者的黑流树海/事件一览",
        event_style="scene",
        relics=[("拟造物质编目", "沉沦者的黑流树海/拟造物质编目")],
        endings=[(1, "强制重启", "RO6-END-1/NBT"),
                 (2, "维度重构", "RO6-END-2/NBT"),
                 (3, "纠缠，调和", "RO6-END-3/NBT")],
        stage_section="沉沦者的黑流树海",
        monthly={"page": "沉沦者的黑流树海/实践者列表",
                 "story_page": "沉沦者的黑流树海/黑流数据库",
                 "story_section": "实践随行录",
                 "dir": "实践者列表",
                 "kind": "operator"},
        loading=_loading("沉沦者的黑流树海/黑流数据库"),
        extras=_base_extras("沉沦者的黑流树海", "沉沦者的黑流树海/黑流数据库", "拓扑展览")
        + [("乌托邦幸福论", "沉沦者的黑流树海/黑流数据库", "乌托邦幸福论", "section"),
           ("谐波序列", "沉沦者的黑流树海/黑流数据库", "谐波序列", "section"),
           ("分形索引", "沉沦者的黑流树海/黑流数据库", "分形索引", "section"),
           ("引擎配件目录", "沉沦者的黑流树海/引擎配件目录", "",
            "items:沉沦者的黑流树海/零件")],
    ),
}


# ====================================================================== 采集器

@register
class RoguelikeCollector(Collector):
    name = "roguelike"
    title = "集成战略（肉鸽）：事件 / 藏品 / 结局 / 月度小队 / 关卡 / 加载文本"
    help = """抓取集成战略主题的剧情文本，按主题分目录：

\b
    OUT/roguelike/<主题>/事件/<事件大类>/<事件名>.txt
    OUT/roguelike/<主题>/藏品.txt
    OUT/roguelike/<主题>/序章/avg.txt
    OUT/roguelike/<主题>/结局/结局N <名称>/avg.txt 与 partN.txt
    OUT/roguelike/<主题>/<月度小队目录>/<小队名或角色名>.txt
    OUT/roguelike/<主题>/关卡.txt
    OUT/roguelike/<主题>/加载文本.txt
    OUT/roguelike/<主题>/其他文本/*

已实现全部 7 个主题：刻俄柏的灰蕈迷境、傀影与猩红孤钻、水月与深蓝之树、
探索者的银凇止境、萨卡兹的无终奇语、岁的界园志异、沉沦者的黑流树海。
各主题的网页结构差别很大（事件用 {{集成战略事件}} 还是 {{ISEvent/scene}}、
月度小队是按小队还是按角色、记录页叫法都不同），因此每个主题在 THEMES 里单独配置。

用 --theme 主题名 或 -g 关键字 可以只抓其中一部分。"""
    order = 60

    @classmethod
    def params(cls) -> list:
        return [
            click.Option(["--theme", "themes"], multiple=True,
                         help="只抓指定主题（可重复，默认全部）"),
            click.Option(["--no-events"], is_flag=True, help="跳过事件"),
            click.Option(["--no-relics"], is_flag=True, help="跳过藏品"),
            click.Option(["--no-endings"], is_flag=True, help="跳过序章与结局"),
            click.Option(["--no-monthly"], is_flag=True, help="跳过月度小队/访谈录"),
            click.Option(["--no-stages"], is_flag=True, help="跳过关卡"),
        ]

    # ---------------- 主流程 ----------------
    def run(self, ctx: Context) -> Stat:
        stat = Stat()
        out = ctx.out_dir / MODULE_DIR
        manifest = Manifest(out / "_manifest.json")

        wanted = list(ctx.extra.get("themes") or ())
        themes = [t for name, t in THEMES.items()
                  if (not wanted or name in wanted) and ctx.match(name)]
        if not themes:
            ctx.log("  没有匹配的主题")
            return stat

        for spec in themes:
            self.header(ctx, f"集成战略：{spec.key}")
            sub = Stat()
            pg = ctx.client.pages([f"{spec.code}-BEG/NBT"], with_content=True)
            sub.written = self._prologue(ctx, spec, out, manifest, stat, pg, {})
            sub.written += self._events(ctx, spec, out, manifest, stat)
            sub.written += self._relics(ctx, spec, out, manifest, stat)
            sub.written += self._endings(ctx, spec, out, manifest, stat)
            sub.written += self._monthly(ctx, spec, out, manifest, stat)
            sub.written += self._stages(ctx, spec, out, manifest, stat)
            sub.written += self._loading(ctx, spec, out, manifest, stat)
            sub.written += self._extras(ctx, spec, out, manifest, stat)
            ctx.log(f"  · {spec.key} 共写出 {sub.written} 个文件")

        manifest.save()
        if not ctx.dry_run:
            self._write_index(out, manifest)
        return stat

    # ---------------- 0. 序章 ----------------
    def _prologue(self, ctx: Context, spec: ThemeSpec, out: Path, manifest: Manifest,
                  stat: Stat, pages: dict, revids: dict) -> int:
        """序章（ROn-BEG/NBT）的 avg 剧情，存到主题自己的目录下。"""
        page = f"{spec.code}-BEG/NBT"
        rec = pages.get(page)
        if rec is None or not rec.content:
            return 0
        revid = rec.revid
        sig = signature(revid)
        path = out / spec.key / "序章" / "avg.txt"
        if not need_update(ctx, manifest, f"prologue:{spec.key}", sig, path.exists()):
            stat.skipped += 1
            return 0
        if ctx.dry_run:
            return 1
        doc = extract_story(rec.content, fetch=make_raw_fetcher(ctx), page_title=page,
                            fmt=ctx.extra.get("fmt", "dialogue"),
                            merge_speaker=bool(ctx.extra.get("merge_speaker")))
        text = "\n\n".join(block.rstrip() for _tp, block in doc.blocks)
        head = (f"{spec.key} 序章\n- 页面：{BASE}/w/{page.replace(' ', '_')}\n"
                f"- 版本：rev {revid}\n\n---\n\n")
        path.parent.mkdir(parents=True, exist_ok=True)
        write_text(path, head + text.rstrip() + "\n")
        manifest.record(f"prologue:{spec.key}", sig, file=str(path.relative_to(out)))
        stat.written += 1
        if ctx.verbose:
            ctx.log("    + 序章/avg.txt")
        return 1

    # ---------------- 1. 事件 ----------------
    def _events(self, ctx: Context, spec: ThemeSpec, out: Path, manifest: Manifest, stat: Stat) -> int:
        if ctx.extra.get("no_events"):
            return 0
        # 事件一览可能拆成多个子页面（例如「岁的界园志异/事件一览/代理人」）
        pages = [spec.event_page]
        extra = list(ctx.client._paginate("allpages", list="allpages",
                                           apprefix=spec.event_page + "/", aplimit=200, apnamespace=0))
        pages += [p for p in extra if p not in pages]
        events: list[dict] = []
        seen: set[str] = set()
        for page in pages:
            raw = ctx.client.raw(page)
            if not raw:
                continue
            found = (parse_events_template(raw) if spec.event_style == "template"
                     else parse_events_scene(raw))
            for ev in found:
                key = f"{ev['category']}/{ev['name']}"
                if key in seen:
                    continue
                seen.add(key)
                events.append(ev)
        if not events:
            ctx.log("  ! 事件一览页面不存在或没有事件")
            return 0
        ctx.log(f"  事件：{len(events)} 个（{len(pages)} 个页面）")
        written = 0
        for ev in events:
            if not ctx.match(ev["name"], ev["category"]):
                continue
            key = f"event:{spec.key}:{ev['category']}/{ev['name']}"
            sig = signature(ev["category"], ev["text"])
            path = out / spec.key / EVENT_DIR / sanitize(ev["category"]) / f"{sanitize(ev['name'])}.txt"
            if not need_update(ctx, manifest, key, sig, path.exists()):
                stat.skipped += 1
                continue
            if ctx.dry_run:
                written += 1
                continue
            body = [f"{ev['name']}", f"（{ev['category']}）", "", ev["text"]]
            path.parent.mkdir(parents=True, exist_ok=True)
            write_text(path, "\n".join(body).rstrip() + "\n")
            manifest.record(key, sig, file=str(path.relative_to(out)), category=ev["category"])
            stat.written += 1
            written += 1
            if ctx.verbose:
                ctx.log(f"    + 事件/{ev['category']}/{ev['name']}.txt")
        return written

    # ---------------- 2. 藏品 ----------------
    def _relics(self, ctx: Context, spec: ThemeSpec, out: Path, manifest: Manifest, stat: Stat) -> int:
        if ctx.extra.get("no_relics"):
            return 0
        written = 0
        for title, page in spec.relics:
            raw = ctx.client.raw(page)
            if not raw:
                continue
            groups = parse_relics(raw)
            total = sum(len(v) for v in groups.values())
            ctx.log(f"  藏品（{title}）：{total} 个 / {len(groups)} 个分类")
            sig = signature(*[f"{g}:{len(v)}:{v[0][0] if v else ''}" for g, v in groups.items()])
            path = out / spec.key / RELIC_FILE
            if not need_update(ctx, manifest, f"relics:{spec.key}", sig, path.exists()):
                stat.skipped += 1
                continue
            if ctx.dry_run:
                written += 1
                continue
            body: list[str] = []
            for group in sorted(groups, key=natural_key):
                items = groups[group]
                if group:
                    body += [f"{'=' * 20} {group} {'=' * 20}", ""]
                for name, desc in items:
                    body += [name, desc, ""]
            path.parent.mkdir(parents=True, exist_ok=True)
            write_text(path, "\n".join(body).rstrip() + "\n")
            manifest.record(f"relics:{spec.key}", sig, file=str(path.relative_to(out)), count=total)
            stat.written += 1
            written += 1
            if ctx.verbose:
                ctx.log(f"    + 藏品.txt（{total} 个）")
        return written

    # ---------------- 3. 结局 ----------------
    def _endings(self, ctx: Context, spec: ThemeSpec, out: Path, manifest: Manifest, stat: Stat) -> int:
        if ctx.extra.get("no_endings"):
            return 0
        page_raw = ctx.client.raw(spec.page)
        texts = ending_texts(page_raw)                     # 主页面「结局」表里的说明
        endings = discover_endings(page_raw, spec.code) or spec.endings   # 用页面自动发现结局页
        conf = {i: n for i, n, _p in spec.endings}
        # 结局名以配置为准（新主题的表格里链接文字常常是「回放记录」之类）
        endings = [(i, conf.get(i) or name, page) for i, name, page in endings]
        extra = dict(spec.ending_notes)
        extra_texts: dict[str, list[str]] = {}
        if extra:
            note_raw = ctx.client.raw(extra["page"])
            if note_raw:
                extra_texts = ending_texts(note_raw, extra.get("section", "结局"), by_section=True)
        written = 0
        pages = ctx.client.pages([p for _i, _n, p in endings], with_content=True)
        recs = ctx.client.revids([p for _i, _n, p in endings])
        fetch = make_raw_fetcher(ctx)
        for idx, name, page in endings:
            folder = f"结局{cn_ordinal(idx)} {sanitize(name)}"
            base = out / spec.key / ENDING_DIR / folder
            rec = pages.get(page)
            revid = recs.get(page).revid if recs.get(page) else 0
            parts = list(dict.fromkeys(list(texts.get(page, [])) + list(extra_texts.get(page, []))))
            sig = signature(revid, *parts)
            if not need_update(ctx, manifest, f"ending:{spec.key}:{idx}", sig, (base / "avg.txt").exists()):
                stat.skipped += 1
                continue
            if ctx.dry_run:
                written += 1
                continue
            base.mkdir(parents=True, exist_ok=True)
            if rec and rec.content:
                doc = extract_story(rec.content, fetch=fetch, page_title=page,
                                    fmt=ctx.extra.get("fmt", "dialogue"),
                                    merge_speaker=bool(ctx.extra.get("merge_speaker")))
                text = "\n\n".join(block.rstrip() for _tp, block in doc.blocks)
                head = (f"{name}\n"
                        f"- 页面：{BASE}/w/{page.replace(' ', '_')}\n"
                        f"- 版本：rev {revid}\n\n---\n\n")
                write_text(base / "avg.txt", head + text.rstrip() + "\n")
                stat.written += 1
                written += 1
            for i, part in enumerate(parts, 1):
                write_text(base / f"part{i}.txt", part.rstrip() + "\n")
                stat.written += 1
                written += 1
            # 清掉上一次运行多出来的 partN.txt
            for stale in base.glob("part*.txt"):
                num = re.sub(r"\D", "", stale.stem)
                if num and int(num) > len(parts):
                    stale.unlink()
            manifest.record(f"ending:{spec.key}:{idx}", sig, folder=folder,
                            file=f"{ENDING_DIR}/{folder}/avg.txt", parts=len(parts))
            if ctx.verbose:
                ctx.log(f"    + {ENDING_DIR}/{folder}（avg + {len(parts)} 个 part）")
        return written

    # ---------------- 4. 月度小队（各主题名称不同：通讯记录仪 / 追忆映射 / 游园访谈 …） ----------------
    def _monthly(self, ctx: Context, spec: ThemeSpec, out: Path, manifest: Manifest, stat: Stat) -> int:
        if ctx.extra.get("no_monthly") or not spec.monthly:
            return 0
        cfg = spec.monthly
        raw = ctx.client.raw(cfg["story_page"])
        if not raw:
            return 0
        entries = monthly_stories(raw, cfg.get("story_section", ""), cfg.get("kind", "squad"),
                                  theme=spec.key)
        ctx.log(f"  {cfg.get('dir', MONTHLY_DIR)}：{len(entries)} 条")
        written = 0
        base_dir = out / spec.key / sanitize(cfg.get("dir") or MONTHLY_DIR)
        for name, text in entries:
            if not ctx.match(name):
                continue
            sig = signature(name, text)
            path = base_dir / f"{sanitize(name)}.txt"
            if not need_update(ctx, manifest, f"monthly:{spec.key}:{name}", sig, path.exists()):
                stat.skipped += 1
                continue
            if ctx.dry_run:
                written += 1
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            write_text(path, text.rstrip() + "\n")
            manifest.record(f"monthly:{spec.key}:{name}", sig, file=str(path.relative_to(out)))
            stat.written += 1
            written += 1
            if ctx.verbose:
                ctx.log(f"    + {base_dir.name}/{name}.txt")
        return written

    # ---------------- 5. 关卡 ----------------
    def _stages(self, ctx: Context, spec: ThemeSpec, out: Path, manifest: Manifest, stat: Stat) -> int:
        if ctx.extra.get("no_stages"):
            return 0
        raw = ctx.client.raw(STAGE_LIST_PAGE)
        sec = section_text(raw, spec.stage_section) if raw else None
        if not sec:
            ctx.log("  ! 关卡一览里没找到该主题的小节")
            return 0
        titles = []
        for m in re.finditer(r"\[\[([^\]\|]+)(?:\|[^\]]*)?\]\]", sec):
            t = m.group(1).strip()
            if t.startswith(("文件:", "分类:", "#")):
                continue
            if t not in titles:
                titles.append(t)
        ctx.log(f"  关卡：{len(titles)} 个")
        revs = ctx.client.revids(titles)
        pages = ctx.client.pages(titles, with_content=True)
        rows: list[tuple[str, str]] = []
        row_titles: list[str] = []        # 与 rows 一一对应的关卡页标题（用于签名）
        for title in titles:
            rec = pages.get(title)
            if not rec or not rec.content:
                continue
            tpl = (template_params(rec.content, "普通关卡信息") or [{}])[0]
            desc = flavor_text(tpl.get("关卡描述", ""))
            code = tpl.get("关卡代号", "") or title.split(" ", 1)[0]
            if desc:
                rows.append((f"{code} {title.split(' ', 1)[-1]}".strip(), desc))
                row_titles.append(title)
            stat.skipped += 0 if desc else 1
        # rows 只含「有关卡描述」的关卡，必须与对应标题一起配对，不能拿 rows 直接 zip 全量 titles
        sig = signature(*[f"{r[0]}:{revs.get(t).revid if revs.get(t) else 0}"
                          for r, t in zip(rows, row_titles)])
        path = out / spec.key / STAGE_FILE
        if not need_update(ctx, manifest, f"stages:{spec.key}", sig, path.exists()):
            stat.skipped += 1
            return 0
        if ctx.dry_run:
            return 1
        body: list[str] = []
        for title, desc in rows:
            body += [title, desc, ""]
        path.parent.mkdir(parents=True, exist_ok=True)
        write_text(path, "\n".join(body).rstrip() + "\n")
        manifest.record(f"stages:{spec.key}", sig, file=str(path.relative_to(out)), count=len(rows))
        stat.written += 1
        if ctx.verbose:
            ctx.log(f"    + {STAGE_FILE}（{len(rows)} 关）")
        return 1

    # ---------------- 6. 加载文本 ----------------
    def _loading(self, ctx: Context, spec: ThemeSpec, out: Path, manifest: Manifest, stat: Stat) -> int:
        if not spec.loading:
            return 0
        chunks: list[str] = []
        for title, page, sec_name, mode in spec.loading:
            raw = ctx.client.raw(page)
            if not raw:
                continue
            sec = section_text(raw, sec_name) if sec_name else raw
            if not sec:
                continue
            body = extract_boxes(sec, only_lore=(mode == "tips")) or plain_text(sec)
            if body.strip():
                chunks += [f"【{title}】", "", body.strip(), ""]
        if not chunks:
            ctx.log("  加载文本：无（该主题没有对应页面）")
            return 0
        sig = signature(*chunks)
        path = out / spec.key / LOADING_FILE
        if not need_update(ctx, manifest, f"loading:{spec.key}", sig, path.exists()):
            stat.skipped += 1
            return 0
        if ctx.dry_run:
            return 1
        path.parent.mkdir(parents=True, exist_ok=True)
        write_text(path, "\n".join(chunks).rstrip() + "\n")
        manifest.record(f"loading:{spec.key}", sig, file=str(path.relative_to(out)))
        stat.written += 1
        if ctx.verbose:
            ctx.log(f"    + {LOADING_FILE}")
        return 1

    # ---------------- 7. 其他文本 ----------------
    def _extras(self, ctx: Context, spec: ThemeSpec, out: Path, manifest: Manifest, stat: Stat) -> int:
        written = 0
        for name, page, sec_name, mode in spec.extras:
            raw = ctx.client.raw(page)
            if not raw:
                continue
            sec = section_text(raw, sec_name) if sec_name else raw
            if not sec:
                continue
            if mode == "gallery":
                body = extract_gallery(sec)
            elif mode.startswith("items:"):
                body = extract_item_entries(sec, mode.split(":", 1)[1])
            else:
                body = (extract_boxes(sec) or plain_text(sec))
                body = strip_subheadings(body)
            if not body.strip():
                continue
            sig = signature(body)
            path = out / spec.key / EXTRA_DIR / f"{sanitize(name)}.txt"
            if not need_update(ctx, manifest, f"extra:{spec.key}:{name}", sig, path.exists()):
                stat.skipped += 1
                continue
            if ctx.dry_run:
                written += 1
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            write_text(path, body.rstrip() + "\n")
            manifest.record(f"extra:{spec.key}:{name}", sig, file=str(path.relative_to(out)))
            stat.written += 1
            written += 1
            if ctx.verbose:
                ctx.log(f"    + {EXTRA_DIR}/{name}.txt")
        return written

    # ---------------- 索引 ----------------
    @staticmethod
    def _write_index(out: Path, manifest: Manifest) -> None:
        import time
        lines = ["# PRTS 集成战略（肉鸽）文本索引", "",
                 f"生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}", "",
                 "> 由 prts_crawler.py roguelike 生成。每个主题一个目录，包含：",
                 "> 事件 / 藏品 / 结局 / 月度小队 / 关卡 / 加载文本 / 其他文本", ""]
        for theme in sorted({k.split(":")[1] for k in manifest.items if k.startswith(("event:", "relics:", "ending:", "monthly:", "stages:", "loading:", "extra:"))},
                            key=natural_key):
            lines += [f"## {theme}", ""]
            for kind, label in (("event", "事件"), ("relics", "藏品"), ("ending", "结局"),
                                ("monthly", "月度小队"), ("stages", "关卡"),
                                ("loading", "加载文本"), ("extra", "其他文本")):
                rows = [k for k in manifest.items
                        if k.startswith(f"{kind}:{theme}:") or k == f"{kind}:{theme}"]
                if rows:
                    lines.append(f"- {label}（{len(rows)}）")
            lines.append("")
        write_text(out / "_索引.md", "\n".join(lines), ignore_timestamps=True)


# ====================================================================== 解析函数

def parse_events_template(raw: str) -> list[dict]:
    """灰蕈迷境式事件：《== 大类 ==》《=== 事件名 ===》+ {{集成战略事件}}。"""
    events: list[dict] = []
    category = ""
    for level, title, block in split_sections(raw):
        if level == 2:
            category = title
            continue
        if level != 3:
            continue
        tpls = template_params(block, "集成战略事件")
        if not tpls:
            continue
        tpl = tpls[0]
        desc = plain_text(tpl.get("描述", ""))
        branches: list[str] = []
        for opt in template_params(tpl.get("选项", ""), "集成战略事件/选项"):
            action = plain_text(opt.get("行动", ""))
            result = plain_text(opt.get("结果", ""))
            if action or result:
                branches.append(f"· 选项：{action}".rstrip() + (f"\n  结果：{result}" if result else ""))
        body = [desc] if desc else []
        if branches:
            body += ["", *branches]
        events.append({"category": category, "name": title, "text": "\n".join(body)})
    return events


def parse_events_scene(raw: str) -> list[dict]:
    """傀影及后续主题式事件：{{ISEvent/scene|…|开始|图片|事件名|描述|选项={{ISEvent/choose|…}}}}。

    同一事件由「开始」场景和若干「结束」场景组成，按事件名归并。
    """
    order: list[str] = []
    data: dict[str, dict] = {}
    current_etype = ""      # etype 只标在每个大类的第一个场景上，后面的沿用（和页面渲染逻辑一致）
    for _pos, body in iter_templates(raw, "ISEvent/scene", nested=True):
        tpl = template_params("{{" + body + "}}", "ISEvent/scene")
        if not tpl:
            continue
        t = tpl[0]
        etype = (t.get("etype") or "").strip()
        if etype:
            current_etype = etype
        name = (t.get("3") or "").strip()
        text = plain_text(t.get("4", ""))
        nav = (t.get("1") or "").strip()
        if not name:
            continue
        # 事件名唯一，用它归并「开始 / 结束」多个场景
        key = name
        if key not in data:
            data[key] = {"category": current_etype, "name": name, "start": "", "after": [], "options": []}
            order.append(key)
        item = data[key]
        if nav == "开始":
            item["start"] = text
            for opt in template_params(t.get("选项", ""), "ISEvent/choose"):
                action = (opt.get("2") or "").strip()
                effect = plain_text(opt.get("desc1", ""))
                if action or effect:
                    item["options"].append((action, effect))
        elif text:
            item["after"].append(text)

    out: list[dict] = []
    for key in order:
        item = data[key]
        body: list[str] = []
        if item["start"]:
            body += [item["start"], ""]
        for action, effect in item["options"]:
            body.append(f"· 选项：{action}".rstrip() + (f"\n  效果：{effect}" if effect else ""))
        if item["after"]:
            body.append("· 后续剧情：")
            body += [f"  {t}" for t in item["after"]]
        out.append({"category": item["category"] or "未分类", "name": item["name"],
                    "text": "\n".join(body).strip()})
    return out


def parse_relics(raw: str) -> dict[str, list[tuple[str, str]]]:
    """藏品：按 == 分类 == 分组（没有分类的页面归到「藏品」一组）。"""
    groups: dict[str, list[tuple[str, str]]] = {}
    category = ""
    order: list[tuple[str, str, str]] = []
    for level, title, block in split_sections(raw):
        if level == 2:
            category = title
        elif level > 2:
            continue          # 用二级小节的整块，跳过子标题以免重复
        for tpl in template_params(block, "收藏品"):
            name = (tpl.get("名称") or "").strip()
            desc = plain_text(tpl.get("描述", ""))
            if name and desc:
                order.append((category, name, desc))
    # 有些页面的 {{收藏品}} 不在小节里（例如灰蕈迷境的收藏品图鉴），补扫一遍全文
    if not order:
        for tpl in template_params(raw, "收藏品"):
            name = (tpl.get("名称") or "").strip()
            desc = plain_text(tpl.get("描述", ""))
            if name and desc:
                order.append(("藏品", name, desc))
    for cat, name, desc in order:
        groups.setdefault(cat, []).append((name, desc))
    return groups


ITEM_FIELDS = ("类型", "币制", "描述", "效果", "获取", "条件", "占卜", "唱词中文", "唱词外文")


def extract_item_entries(sec: str, template_page: str) -> str:
    """把 `{{:主题/思绪|名称=…|描述=…}}` 这类道具条目转成可读文本。

    集成战略除「收藏品」外，还有思绪（萨卡兹）、密文板（银凇止境）、
    通宝（岁的界园）、零件（黑流树海）等图鉴；它们用子页面转写模板
    （`{{:…}}`）而不是 `{{收藏品}}`，原来的藏品解析收不到。这里按条目
    提取 名称/描述/效果/获取 等字段，保留风味文本与解锁说明。
    """
    out: list[str] = []
    pat = re.compile(r"\{\{:\s*" + re.escape(template_page) + r"\s*[|}]")
    for m in pat.finditer(sec or ""):
        body = balanced(sec, m.start())
        if not body:
            continue
        inner = body[2:-2] if body.endswith("}}") else body[2:]
        tpl = split_params(inner)
        name = plain_text(tpl.get("名称", "")).strip()
        if not name:
            continue
        lines = [f"===== {name} ====="]
        for key in ITEM_FIELDS:
            value = plain_text(tpl.get(key, ""))
            value = re.sub(r"<!--.*?-->", "", value, flags=re.S)      # HTML 注释
            value = re.sub(r"\{\{[^{}]*\}\}", "", value)              # 残留的 {{color|…}}
            value = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", value)  # [[页|名]]
            value = re.sub(r"\[\[([^\]]*)\]\]", r"\1", value)          # [[页]]
            value = re.sub(r"颜色=#[0-9a-fA-F]{3,8}", "", value)
            value = re.sub(r"[ \t]{2,}", " ", value).strip()
            if value:
                lines.append(f"{key}：{value}")
        if len(lines) > 1:
            out.append("\n".join(lines))
    return "\n\n".join(out)


CONDITION_HINTS = ("达成条件", "解锁条件", "完成关卡", "在任意难度", "情况下", "未持有", "持有收藏品")


ATTR_RE = re.compile(r'^\s*(?:style|class|css|rowspan|colspan|width|id|align|background|color)\s*=', re.I)

# 结局表里每张卡片都重复的装饰性文案，不是该结局独有的内容。
# 旧版会把它们写进每个结局的 partN.txt，造成大量重复文件。
BOILERPLATE_LINES = {
    "探索走向了不同的结局……",
    "我走入了不同的结局……",
    "—— · ——",
    "<!------>",
    "function() {",
}
# HTML 注释 / 脚本残片 / 纯花括号，不是结局说明正文
JUNK_LINE_RE = re.compile(r"^(?:<!-|<![A-Za-z/]|-->|\}|\{|function\s*\()")


def _clean_block_text(block: str, skip_titles: tuple[str, ...] = ()) -> list[str]:
    """把结局格子里的说明文字抽成若干段（去掉图片、表格属性、达成条件等）。"""
    text = re.sub(r"\[\[文件:[^\]]*\]\]", "", block)
    text = re.sub(r"<small>(.*?)</small>", r"\1", text, flags=re.S)
    text = re.sub(r"\{\{(?:color|Color)\|[^|]*\|([^{}]*)\}\}", r"\1", text)
    text = re.sub(r"\{\{[^{}]*\}\}", "", text)     # {{fa|chevron-right}} 之类
    text = re.sub(r"'''?", "", text)               # 粗体 / 斜体标记（可能相互嵌套）
    text = clean_markup(text)
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        line = re.sub(r"^=+\s*|\s*=+$", "", line).strip()   # 小节标题
        line = line.lstrip("|").strip()                     # 行首的表格竖线
        if "|" in line:                                    # style="…"|正文
            head, _, tail = line.partition("|")
            if ATTR_RE.match(head):
                line = tail.strip()
        line = line.strip("|").strip()
        if not line or line.startswith(("!", "-", "}", "{")) or ATTR_RE.match(line):
            continue
        if any(h in line for h in CONDITION_HINTS):
            continue
        if line in BOILERPLATE_LINES or JUNK_LINE_RE.match(line):
            continue
        if line in skip_titles or any(h in line for h in ("chevron", "mw-customtoggle", "mw-collapsible")):
            continue
        if len(line) < 4:
            continue
        if line not in out:
            out.append(line)
    return out


def ending_texts(raw: str, section: str = "结局", by_section: bool = False) -> dict[str, list[str]]:
    """主题页「结局」章节里，每个结局附带的说明文本（按结局页标题索引）。

    结构大致是：每个结局一个折叠表格，
        ![[RO1-END-1/NBT|{{color|#fff|CRIMSON FINALE<br>舞会终场}}]]
        |[[文件:结局插画.png]]<br>''戏剧落幕，…''
        !达成条件  |在任意难度下完成关卡[[ISW-DF 覆水难收]]
    默认取「结局链接之后」的文字；by_section=True 则按三级小节归组
    （有些页面把「播放」链接放在小节末尾，只能用小节来界定归属）。
    """
    sec = section_text(raw or "", section) or ""
    out: dict[str, list[str]] = {}

    def add(page: str, texts: list[str]) -> None:
        page = page.strip()
        if not page:
            return
        bucket = out.setdefault(page, [])
        for t in texts:
            if t not in bucket:
                bucket.append(t)

    if by_section:
        for level, title, block in split_sections(sec):
            if level != 3:
                continue
            pages = [m.group(1) for m in re.finditer(r"\[\[([^\]\|]*END[^\]\|]*)", block)]
            if not pages:
                continue
            texts = _clean_block_text(block, skip_titles=(title,))
            for p in pages:
                add(p, texts)
        return {k: v for k, v in out.items() if v}

    marks: list[tuple[int, int, str]] = []
    for m in re.finditer(r"\[\[([^\]\|]*END[^\]\|]*)(?:\|(.*?))?\]\]", sec, re.S):
        marks.append((m.start(), m.end(), m.group(1).strip()))
    for i, (_s, e, page) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(sec)
        add(page, _clean_block_text(sec[e:end]))
    return {k: v for k, v in out.items() if v}


SUBJECT_RE = re.compile(
    r"(?:小队成员|映射对象|访谈对象|奇遇讲述者|界园游客|理想践行者|实践者|讲述者|游览者)[：:]\s*"
    r"(?:\{\{[^}]*\}\})?\s*\[\[([^\]\|]+)")
SUBJECT_LABEL_RE = re.compile(r"(小队成员|映射对象|访谈对象|奇遇讲述者|界园游客|理想践行者)[：:]")


def entry_subject(block: str) -> tuple[str, str]:
    """取条目对应的角色/小队：返回 (类型名, 名字)。"""
    m = SUBJECT_RE.search(block)
    if not m:
        return "", ""
    name = m.group(1).strip()
    label_m = SUBJECT_LABEL_RE.search(block)
    return (label_m.group(1) if label_m else "对象"), name


def discover_endings(page_raw: str, code: str) -> list[tuple[int, str, str]]:
    """从主题主页面的「结局」章节里自动发现结局（序号、中文名、avg 页面）。"""
    sec = section_text(page_raw or "", "结局") or ""
    found: dict[int, tuple[int, str, str]] = {}
    for m in re.finditer(r"\[\[(" + re.escape(code) + r"-END-(\d+)/[^\]\|]*)\|(.*?)\]\]", sec, re.S):
        page, idx, label = m.group(1).strip(), int(m.group(2)), clean_markup(m.group(3))
        names = re.findall(r"[\u4e00-\u9fa5·“”，、]{2,12}", label)
        name = names[-1] if names else f"结局{idx}"
        found[idx] = (idx, name, page)
    return [found[i] for i in sorted(found)]


def monthly_stories(raw: str, section: str, kind: str = "squad", theme: str = "") -> list[tuple[str, str]]:
    """月度小队/访谈录：=== 条目名 === 下的 PART 表格。

    kind="squad"    → 一个条目（一个小队）一个文件，文件名用条目名（傀影肉鸽）；
    kind="operator" → 按角色拆分，同一角色的多个条目合并到一个文件（其余主题）。
    """
    scope = section_text(raw, section) if section else raw
    if not scope:
        return []
    collected: dict[str, list[str]] = {}
    order: list[str] = []
    for level, title, block in split_sections(scope):
        if level != 3:
            continue
        parts = render_parts(block)
        if not parts:
            continue
        label, subject = entry_subject(block)
        key = subject if (kind == "operator" and subject) else title
        body = [f"{theme} {title}".strip() if theme else title]
        if subject:
            body.append(f"{label}：{subject}")
        body.append("")
        for pname, ptext in parts:
            body += [f"===== {pname} =====", "", ptext, ""]
        if key not in collected:
            collected[key] = []
            order.append(key)
        collected[key].append("\n".join(body).rstrip())
    return [(k, "\n\n".join(collected[k])) for k in order]


DROPPED_TEMPLATES = ("#widget:style", "#widget:ISEvent", "#vardefine", "#var", "cbox2", "Cbox2",
                     "AKCollapse/title", "参阅", "fa")


def extract_boxes(sec: str, only_lore: bool = False) -> str:
    """把页面小节整理成正文：去掉提示框/微件/表格语法，可选只保留剧情型条目。"""
    body = strip_templates(sec, drop=DROPPED_TEMPLATES, drop_parser=True)
    body = unwrap_templates(body, ("Cquote", "cquote", "Cquote2", "Poem", "poem"))
    body = re.sub(r"<templatestyles[^>]*/>", "", body)
    body = plain_text(body)
    lines: list[str] = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith(("{|", "|-", "|}", "!", "|+", "}", "<!--")):
            continue
        if re.fullmatch(r"-{3,}", line):          # wikitext 的水平分隔线
            continue
        if line.startswith("|"):
            line = line.lstrip("|").strip()
            if "|" in line:
                head, _, tail = line.partition("|")
                if ATTR_RE.match(head) or head.startswith(("style", "class", "css")):
                    line = tail.strip()
        line = line.strip()
        line = re.sub(r"^(css|style)\s*=.*$", "", line).strip()
        line = re.sub(r"^(rowspan|colspan)\s*=\s*\d+\s*\|?", "", line).strip()
        if not line or line.isdigit():
            continue
        # 过场提示里既有世界观介绍（“名称——说明”），也有游戏指引，只留前者
        if only_lore and "——" not in line:
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def strip_subheadings(text: str) -> str:
    """去掉纯表头的行（==== 之类），让正文更干净。"""
    lines = [ln for ln in text.splitlines() if not re.match(r"^\s*={2,6}.*={2,6}\s*$", ln)]
    return "\n".join(lines).strip()


def extract_gallery(sec: str) -> str:
    """插画展览：表格里「名称 + 说明」的条目（说明在名称行的下一行）。"""
    entries: list[tuple[str, list[str]]] = []
    for row in re.split(r"\n\|-\n?", sec):
        title = re.search(r"'''([^']{2,40})'''", row)
        body = re.sub(r"\[\[文件:[^\]]*\]\]", "", row)
        body = re.sub(r"\{[^{}]*\}", "", body)
        lines = [ln.strip().lstrip("|").strip() for ln in clean_markup(body).splitlines()]
        text = " ".join(ln for ln in lines
                        if ln and not ATTR_RE.match(ln) and not ln.startswith(("{|", "|}", "!", "-", "style")))
        text = re.sub(r"\s{2,}", " ", text).replace("'''", "").strip()
        if title:
            entries.append((clean_markup(title.group(1)).strip(), [text] if text else []))
        elif text and entries:
            entries[-1][1].append(text)
    out: list[str] = []
    for name, texts in entries:
        out.append(name)
        out.extend(t for t in texts if t)
        out.append("")
    return "\n".join(out).strip()
