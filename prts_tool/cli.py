#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""click 命令行界面：把每个采集器变成一条子命令。

    m3-reader --help
    m3-reader avg                 # 抓 avg 剧情
    m3-reader operator -g 琴柳     # 只抓某个干员
    m3-reader refresh -m avg -m furniture
    m3-reader all
    m3-reader fetch raw 锡兰
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from . import __version__
from .jobs import UpdateCapture
from .output import sanitize, write_text
from .paths import DEFAULT_TERRA_DIR, DEFAULT_TEXT_DIR, LATEST_DIR
from .registry import MODE_HELP, Collector, build_context, common_params, discover, params_of

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"], "max_content_width": 110}


def _log(msg: str = "") -> None:
    click.echo(msg)


def make_command(cls: type[Collector], spec: dict | None = None) -> click.Command:
    """把采集器类包成一条 click 子命令。

    spec 是 `Collector.aliases` 里的一项，用来派生「预设参数」的额外命令
    （例如 terra-images = terra --images）；None 表示主命令。
    """
    params = params_of(*common_params(), *cls.params())
    spec = spec or {}
    preset = dict(spec.get("preset") or {})
    cmd_name = spec.get("name") or cls.name

    def callback(**kwargs) -> None:
        kwargs.update(preset)                     # 预设参数覆盖同名 click 参数
        ctx = build_context(kwargs, log=_log)
        _log(f"# {cls.title}　（输出目录：{ctx.out_dir}　模式：{ctx.mode}）")
        with UpdateCapture(ctx.out_dir, [cls], dry_run=ctx.dry_run) as capture:
            stat = cls().run(ctx)
        if capture.latest_count:
            _log(f"最新内容：{LATEST_DIR}（{capture.latest_count} 个文件）")
        _log("")
        _log(stat.summary(cls.name))

    return click.Command(
        name=cmd_name,
        callback=callback,
        params=params,
        help=spec.get("help") or cls.help or cls.title,
        short_help=spec.get("short") or cls.title,
        context_settings=CONTEXT_SETTINGS,
    )


def build_cli() -> click.Group:
    collectors = discover()
    names = [c.name for c in collectors]

    @click.group(context_settings=CONTEXT_SETTINGS)
    @click.version_option(__version__, "-V", "--version", prog_name="m3-reader")
    def cli() -> None:
        """PRTS（prts.wiki）文本采集工具。

        把所有文本抓成便于阅读的 txt，按章节 / 干员 / 主题分文件夹保存。
        """

    # 每个采集器一条子命令（外加它自己声明的别名命令）
    for cls in collectors:
        cli.add_command(make_command(cls))
        for spec in getattr(cls, "aliases", ()) or ():
            cli.add_command(make_command(cls, spec))

    # ---------------- all ----------------
    @cli.command("all", context_settings=CONTEXT_SETTINGS)
    @click.option("--only", "only", multiple=True, type=click.Choice(names),
                  help="只跑指定的模块（可重复）")
    @click.option("--skip", "skip", multiple=True, type=click.Choice(names),
                  help="跳过指定的模块（可重复）")
    @click.option("-o", "--out", "out_dir", default=str(DEFAULT_TEXT_DIR), show_default=True, help="输出根目录")
    @click.option("-m", "--mode", type=click.Choice(["changed", "missing", "force"]),
                  default="changed", show_default=True, help=MODE_HELP)
    @click.option("--force", is_flag=True, help="等价于 -m force")
    @click.option("--missing", "only_missing", is_flag=True, help="等价于 -m missing")
    @click.option("--dry-run", is_flag=True, help="只显示会写哪些文件")
    @click.option("-n", "--limit", type=int, default=0, help="每个模块最多处理 N 条（调试用）")
    @click.option("-g", "--keyword", "keywords", multiple=True, help="关键字过滤（可重复）")
    @click.option("--delay", type=float, default=0.3, show_default=True, help="请求间隔秒数")
    @click.option("-v", "--verbose", is_flag=True, help="输出更多细节")
    def all_cmd(only, skip, **kwargs) -> None:
        """依次运行所有采集模块（avg → stage → activity → operator → furniture → enemies → reclamation → roguelike → terra）。

        \b
        注意：terra 只更新 说明.txt 与索引，**不下载图片**；
        图片要单独跑 `m3-reader terra-images`。
        """
        run_modules([c for c in collectors
                     if (not only or c.name in only) and c.name not in skip], kwargs)

    # ---------------- update（更新全部内容） ----------------
    @cli.command("update", context_settings=CONTEXT_SETTINGS)
    @click.option("--only", "only", multiple=True, type=click.Choice(names),
                  help="只更新指定的模块（可重复）")
    @click.option("--skip", "skip", multiple=True, type=click.Choice(names),
                  help="跳过指定的模块（可重复）")
    @click.option("-o", "--out", "out_dir", default=str(DEFAULT_TEXT_DIR), show_default=True, help="输出根目录")
    @click.option("--force", is_flag=True, help="强制全部重抓（先删清单也一样）")
    @click.option("--missing", "only_missing", is_flag=True, help="只补本地缺失的，不更新已存在的")
    @click.option("--dry-run", is_flag=True, help="只显示会更新哪些内容")
    @click.option("--images", is_flag=True, help="文本更新后再下载 terra 图片")
    @click.option("-n", "--limit", type=int, default=0, help="每个模块最多处理 N 条")
    @click.option("-g", "--keyword", "keywords", multiple=True, help="关键字过滤（可重复）")
    @click.option("--delay", type=float, default=0.3, show_default=True, help="请求间隔秒数")
    @click.option("-v", "--verbose", is_flag=True, help="输出更多细节")
    def update_cmd(only, skip, images, **kwargs) -> None:
        """更新全部内容：把所有模块都跑一遍，只处理有变化/缺失的部分。

        \b
        这就是「更新全部内容」的指令，等价于：
            m3-reader all
            m3-reader refresh -m all

        \b
        常用：
            m3-reader update              # 全量更新（推荐日常使用）
            m3-reader update --dry-run    # 先看会更新什么
            m3-reader update --force      # 全库强制重抓

        \b
        默认仅更新文本；加 --images 会继续下载 terra 图片。
        本地 PDF 和 OCR 不由爬虫重新获取。
        """
        kwargs["mode"] = "force" if kwargs.pop("force", False) else "changed"
        if kwargs.pop("only_missing", False):
            kwargs["mode"] = "missing"
        run_modules([c for c in collectors
                     if (not only or c.name in only) and c.name not in skip], kwargs)
        if images:
            terra = next(cls for cls in collectors if cls.name == "terra")
            run_modules([terra], {**kwargs, "images": True})

    # ---------------- refresh ----------------
    @cli.command("refresh", context_settings=CONTEXT_SETTINGS)
    @click.option("-m", "--module", "modules", multiple=True,
                  type=click.Choice(names + ["all"]), default=("all",), show_default=True,
                  help="要刷新的模块（可重复；all=全部）")
    @click.option("--mode", "mode", type=click.Choice(["changed", "missing", "force"]),
                  default="changed", show_default=True, help=MODE_HELP)
    @click.option("--force", is_flag=True, help="等价于 --mode force")
    @click.option("--missing", "only_missing", is_flag=True, help="等价于 --mode missing")
    @click.option("-o", "--out", "out_dir", default=str(DEFAULT_TEXT_DIR), show_default=True, help="输出根目录")
    @click.option("--dry-run", is_flag=True, help="只显示会刷新哪些内容")
    @click.option("-n", "--limit", type=int, default=0, help="每个模块最多处理 N 条")
    @click.option("-g", "--keyword", "keywords", multiple=True, help="关键字过滤（可重复）")
    @click.option("--delay", type=float, default=0.3, show_default=True, help="请求间隔秒数")
    @click.option("-v", "--verbose", is_flag=True, help="输出更多细节")
    def refresh_cmd(modules, mode, **kwargs) -> None:
        """刷新已有内容：可只刷新某些模块，也可选择刷新策略。

        \b
        示例：
          m3-reader refresh                        # 全部模块，按 wiki 版本号增量更新
          m3-reader refresh -m avg                 # 只更新 avg 剧情
          m3-reader refresh -m operator -m furniture
          m3-reader refresh -m all --mode missing  # 只补本地缺失的
          m3-reader refresh -m furniture --force   # 家具全部重抓
        """
        kwargs["mode"] = mode
        selected = [c for c in collectors if "all" in modules or c.name in modules]
        run_modules(selected, kwargs)

    # ---------------- info ----------------
    @cli.command("gui", context_settings=CONTEXT_SETTINGS)
    def gui_cmd() -> None:
        """打开图形资料终端（需要 PySide6）。"""
        if getattr(sys, "frozen", False):
            import subprocess
            gui_executable = Path(sys.executable).with_name("m3-reader-gui.exe" if sys.platform == "win32" else "m3-reader-gui")
            if not gui_executable.is_file():
                raise click.ClickException(f"找不到图形程序：{gui_executable}")
            subprocess.Popen([str(gui_executable)], cwd=str(gui_executable.parent))
        else:
            import subprocess
            source_root = Path(__file__).resolve().parent.parent
            subprocess.run([sys.executable, "-m", "prts_tool.gui_bootstrap"],
                           cwd=str(source_root), check=True)

    @cli.command("tui", context_settings=CONTEXT_SETTINGS)
    def tui_cmd() -> None:
        """打开终端资料阅读器（需要 prompt_toolkit）。"""
        from .tui import main as tui_main
        tui_main()

    # ---------------- info ----------------
    @cli.command("info", context_settings=CONTEXT_SETTINGS)
    def info_cmd() -> None:
        """列出所有采集模块与输出位置。"""
        click.echo(f"m3-reader {__version__}　可用模块（每条都是一条子命令）：\n")
        for cls in collectors:
            click.echo(f"  {cls.name:<10} {cls.title}")
            for line in (cls.help or "").strip().splitlines():
                if line.strip():
                    click.echo(f"             {line.strip()}")
            click.echo("")
        click.echo("输出布局（目录名与命令名一致）：")
        click.echo(f"  默认文本根：{DEFAULT_TEXT_DIR}")
        click.echo(f"  默认 terra 根：{DEFAULT_TERRA_DIR}；自定义 --out 时仍放在输出根的兄弟目录。")
        click.echo("  prts_text/avg/<分类>/<章节>/<序号> <剧情名>.txt   剧情（分类=主线/支线/联动/故事集/四月辑录）")
        click.echo("  prts_text/activity/<活动>/<子页面>.txt             活动公告 / 综合调查数据库 / 审判庭纪要 等活动长文")
        click.echo("  prts_text/avg/<分类>/<章节>/关卡文本.txt           关卡文本（avg 各章节）")
        click.echo("  prts_text/reclamation/<场次>/关卡文本.txt          关卡文本（生息演算各场次）")
        click.echo("  prts_text/operator/<干员名>/*.txt                  干员：档案 / 模组 / 密录 / 悖论模拟")
        click.echo("  prts_text/furniture/<主题名>.txt                   家具（--furniture-dir 可换子目录）")
        click.echo("  prts_text/enemies/<普通|精英|领袖>.txt             敌人描述")
        click.echo("  prts_text/roguelike/<肉鸽名>/*                     集成战略（7 个主题：事件/藏品/序章/结局/月度小队…）")
        click.echo("  prts_text/reclamation/<场次>/*.txt                 生息演算（沙中之火 / 沙洲遗闻 / 重启锚点）")
        click.echo("  terra/<大节>/<条目名>/*.jpg                        泰拉记事社微博长图（位于 collected/terra）")
        click.echo("")
        click.echo("图片：terra 只写 说明.txt 与索引；图片要单独跑 `terra-images`（或 `terra --images`），")
        click.echo("      all / update / refresh 都不会下载 terra 的图片。")
        click.echo("")
        click.echo("常用：m3-reader update（更新全部内容）　/　"
                   "refresh -m avg　/　terra-images　/　fetch raw 锡兰")

    # ---------------- fetch（通用接口） ----------------
    @cli.group("fetch", context_settings=CONTEXT_SETTINGS)
    def fetch_group() -> None:
        """通用抓取接口：wikitext / 模板参数 / Cargo / 列表。

        用来快速查看或导出 PRTS 上任意文本，也是给新采集器做调研的入口。
        """

    @fetch_group.command("raw", context_settings=CONTEXT_SETTINGS)
    @click.argument("title")
    @click.option("-o", "--out", "out_file", default="", help="保存到文件（默认打印到屏幕）")
    @click.option("--delay", type=float, default=0.3, show_default=True)
    def fetch_raw(title, out_file, delay) -> None:
        """取页面的 wikitext（TITLE 形如 `锡兰`、`0-1 坍塌`、`锡兰/干员密录/1`）。"""
        from .http import PrtsClient
        text = PrtsClient(delay=delay, log=_log).raw(title)
        if out_file:
            from pathlib import Path
            write_text(Path(out_file), text)
            click.echo(f"已保存 {out_file}（{len(text)} 字）")
        else:
            click.echo(text)

    @fetch_group.command("template", context_settings=CONTEXT_SETTINGS)
    @click.argument("title")
    @click.argument("template")
    @click.option("-p", "--param", "params", multiple=True, help="只输出这些参数（可重复）")
    @click.option("--delay", type=float, default=0.3, show_default=True)
    def fetch_template(title, template, params, delay) -> None:
        """取页面上某个模板的所有参数，例如 `fetch template 锡兰 人员档案`。"""
        from .http import PrtsClient
        from .wikitext import template_params
        raw = PrtsClient(delay=delay, log=_log).raw(title)
        found = template_params(raw, template)
        if not found:
            click.echo(f"（页面 {title} 上没有找到 {{{{ {template} }}}}）")
            return
        for i, tpl in enumerate(found, 1):
            click.echo(f"--- {template} #{i} ---")
            for k, v in tpl.items():
                if params and k not in params:
                    continue
                click.echo(f"{k} = {v}")

    @fetch_group.command("cargo", context_settings=CONTEXT_SETTINGS)
    @click.argument("table")
    @click.option("--fields", default="_pageName=PAGE", show_default=True)
    @click.option("--where", "where", default=None, help="例如 `rarity=6`")
    @click.option("--limit", type=int, default=50, show_default=True)
    @click.option("--delay", type=float, default=0.3, show_default=True)
    def fetch_cargo(table, fields, where, limit, delay) -> None:
        """结构化查询，例如 `fetch cargo chara --fields _pageName=PAGE,cn --limit 5`。"""
        import json
        from .http import PrtsClient
        rows = PrtsClient(delay=delay, log=_log).cargo(table, fields, where=where, limit=limit)
        click.echo(json.dumps(rows, ensure_ascii=False, indent=1))

    @fetch_group.command("category", context_settings=CONTEXT_SETTINGS)
    @click.argument("name")
    @click.option("--delay", type=float, default=0.3, show_default=True)
    def fetch_category(name, delay) -> None:
        """列出分类成员，例如 `fetch category 干员密录`。"""
        from .http import PrtsClient
        rows = PrtsClient(delay=delay, log=_log).category(name)
        click.echo("\n".join(rows))
        click.echo(f"# 共 {len(rows)} 个", err=True)

    @fetch_group.command("embeddedin", context_settings=CONTEXT_SETTINGS)
    @click.argument("template")
    @click.option("--delay", type=float, default=0.3, show_default=True)
    def fetch_embedded(template, delay) -> None:
        """列出所有嵌入某模板的页面，例如 `fetch embeddedin 家具信息`。"""
        from .http import PrtsClient
        rows = PrtsClient(delay=delay, log=_log).embedded_in(template)
        click.echo("\n".join(rows))
        click.echo(f"# 共 {len(rows)} 个", err=True)

    return cli


def run_modules(selected: list[type[Collector]], kwargs: dict) -> None:
    """按顺序运行若干采集器，共享同一份参数。"""
    if not selected:
        click.echo("没有选择任何模块", err=True)
        return
    out_dir = Path(kwargs.get("out_dir", DEFAULT_TEXT_DIR)).expanduser().resolve()
    with UpdateCapture(out_dir, selected, dry_run=bool(kwargs.get("dry_run"))) as capture:
        for cls in selected:
            sub = {k: v for k, v in kwargs.items() if k != "mode"}
            ctx = build_context({**sub, "mode": kwargs.get("mode", "changed")}, log=_log)
            click.echo("")
            click.echo(f"# ===== {cls.name}　{cls.title} =====")
            stat = cls().run(ctx)
            click.echo(stat.summary(cls.name))
    if capture.latest_count:
        click.echo(f"最新内容：{LATEST_DIR}（{capture.latest_count} 个文件）")


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    cli = build_cli()
    try:
        cli.main(args=argv, prog_name="m3-reader", standalone_mode=True)
    except KeyboardInterrupt:
        click.echo("\n已中断", err=True)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

