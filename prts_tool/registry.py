#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""采集器注册表：把每一类文本做成一个 Collector，自动变成一条 click 子命令。

想新增一类文本（例如「道具描述」「敌人描述」「语音台词」）只需：
    1. 在 prts_tool/collectors/ 下新建一个 .py 文件；
    2. 写一个继承 Collector 的类，实现 run()（名字/说明写好）；
    3. 什么都不用改 —— CLI 会自动发现并注册成子命令。
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import click

from .http import PrtsClient
from .output import Manifest
from .paths import DEFAULT_TEXT_DIR, data_root

MODES = ("changed", "missing", "force")
MODE_HELP = ("changed=按 wiki 版本号增量更新（默认）；"
             "missing=只补本地没有的；force=全部重抓")


@dataclass
class Context:
    """一次采集运行的环境。"""
    out_dir: Path
    client: PrtsClient
    mode: str = "changed"
    dry_run: bool = False
    limit: int = 0
    keywords: list[str] = field(default_factory=list)
    verbose: bool = False
    log: Callable[[str], None] = print
    extra: dict = field(default_factory=dict)

    def match(self, *texts: str) -> bool:
        """--keyword 过滤（任意关键字命中即可）。"""
        if not self.keywords:
            return True
        blob = " ".join(str(t) for t in texts)
        return any(k in blob for k in self.keywords)


@dataclass
class Stat:
    written: int = 0
    skipped: int = 0
    skipped_empty: int = 0
    notes: list[str] = field(default_factory=list)
    dry_run_note: str = ""

    def summary(self, name: str) -> str:
        parts = [f"写入 {self.written}", f"跳过 {self.skipped}"]
        if self.skipped_empty:
            parts.append(f"无内容 {self.skipped_empty}")
        line = f"[{name}] " + "，".join(parts)
        if self.dry_run_note:
            line += f"（dry-run：{self.dry_run_note}）"
        return line


def need_update(ctx: Context, manifest: Manifest, key: str, sig: str, exists: bool) -> bool:
    """三种模式统一判断：要不要（重新）生成这个文件。"""
    if ctx.mode == "force":
        return True
    if not exists:
        return True
    if ctx.mode == "missing":
        return False
    return manifest.sig_of(key) != sig


class Collector:
    """采集器基类。"""

    name: str = ""            # 子命令名，例如 avg
    title: str = ""           # 一句话说明
    help: str = ""            # 详细说明（--help 显示）
    order: int = 50           # all / refresh 里的执行顺序

    #: 数据根目录名。默认 None = 所有模块共用 `-o/--out` 那个输出根（prts_text）。
    #: 设成 "terra" 时，默认布局由 paths.py 决定；自定义输出根时放在兄弟目录。
    #: 用于体积很大、不该混进文本树的数据（例如泰拉记事社的图片）。
    data_root: str | None = None

    #: 额外交互命令：每个元素形如
    #:     {"name": "terra-images", "help": "只抓图片…", "preset": {"images": True}}
    #: 会自动注册成一条独立子命令，预设参数会覆盖同名 click 参数。
    aliases: tuple = ()

    #: 该采集器额外的 click 参数（click.Option / click.Argument 对象列表）
    @classmethod
    def params(cls) -> list:
        return []

    def run(self, ctx: Context) -> Stat:      # pragma: no cover - 抽象
        raise NotImplementedError

    # ---------------- 便捷方法 ----------------
    def data_dir(self, ctx: Context) -> Path:
        """本模块的数据根目录（默认就是全局输出根）。"""
        if self.data_root:
            return data_root(ctx.out_dir, self.data_root)
        return ctx.out_dir

    def manifest(self, ctx: Context, filename: str = "_manifest.json",
                 subdir: str = "") -> Manifest:
        base = ctx.out_dir / subdir if subdir else ctx.out_dir
        return Manifest(base / filename)

    def header(self, ctx: Context, text: str) -> None:
        ctx.log("")
        ctx.log(f"=== {text} ===")


_REGISTRY: list[type[Collector]] = []


def register(cls: type[Collector]) -> type[Collector]:
    _REGISTRY.append(cls)
    return cls


def discover() -> list[type[Collector]]:
    """导入 collectors 包下的所有模块，返回已注册的采集器。"""
    from . import collectors
    for mod in pkgutil.iter_modules(collectors.__path__):
        if mod.name.startswith("_"):
            continue
        importlib.import_module(f"{collectors.__name__}.{mod.name}")
    return sorted(_REGISTRY, key=lambda c: (c.order, c.name))


# ---------------------------------------------------------------- 公共 click 参数

def common_params(default_mode: str = "changed") -> list:
    """所有采集器共用的 click 参数（直接返回 Option 对象，便于拼装成子命令）。"""
    return [
        click.Option(["-o", "--out", "out_dir"], default=str(DEFAULT_TEXT_DIR), show_default=True,
                     help="输出根目录"),
        click.Option(["-m", "--mode"], type=click.Choice(MODES), default=default_mode,
                     show_default=True, help=MODE_HELP),
        click.Option(["--force"], is_flag=True, help="等价于 -m force（全部重抓）"),
        click.Option(["--missing", "only_missing"], is_flag=True, help="等价于 -m missing（只补缺失）"),
        click.Option(["--dry-run"], is_flag=True, help="只显示会写哪些文件，不实际下载/写入"),
        click.Option(["-n", "--limit"], type=int, default=0, help="最多处理 N 条（调试用）"),
        click.Option(["-g", "--keyword", "keywords"], multiple=True,
                     help="只处理包含该关键字的条目（可重复）"),
        click.Option(["--delay"], type=float, default=0.3, show_default=True,
                     help="每次 API 请求间隔秒数"),
        click.Option(["-v", "--verbose"], is_flag=True, help="输出更多细节"),
    ]


def apply_common(kwargs: dict) -> str:
    """把 --force / --missing 折算进 mode，并把它们从参数里移除。"""
    mode = kwargs.pop("mode", "changed") or "changed"
    if kwargs.pop("force", False):
        mode = "force"
    if kwargs.pop("only_missing", False):
        mode = "missing"
    return mode


def params_of(*groups) -> list:
    """把若干参数列表拍平（入参都可以是 list[click.Parameter]）。"""
    out: list = []
    for g in groups:
        if isinstance(g, click.Parameter):
            out.append(g)
        else:
            out.extend(g)
    return out


def build_context(kwargs: dict, log=print) -> Context:
    """从 click 回调参数里构造 Context；剩下的键会放进 ctx.extra 供采集器自用。"""
    out_dir = Path(kwargs.pop("out_dir", DEFAULT_TEXT_DIR)).expanduser()
    delay = kwargs.pop("delay", 0.3)
    mode = apply_common(kwargs)
    dry_run = kwargs.pop("dry_run", False)
    limit = kwargs.pop("limit", 0) or 0
    keywords = list(kwargs.pop("keywords", ()) or ())
    verbose = kwargs.pop("verbose", False)
    return Context(
        out_dir=out_dir.resolve(),
        client=PrtsClient(delay=delay, log=log),
        mode=mode,
        dry_run=dry_run,
        limit=limit,
        keywords=keywords,
        verbose=verbose,
        log=log,
        extra=dict(kwargs),
    )
