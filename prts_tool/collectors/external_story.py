"""Curated PRTS pages that contain external story and puzzle transcripts."""

from ..htmltext import html_to_text
from ..output import Manifest, signature, write_text
from ..registry import Collector, Context, Stat, need_update, register

PAGES = {
    "ORACLE_DATABASE/index": "总索引",
    "ORACLE_DATABASE/index/pv1": "PV1解谜",
    "ORACLE_DATABASE/index/pv2": "PV2解谜",
    "ORACLE_DATABASE/index/pv3": "PV3解谜",
    "ORACLE_DATABASE/index/pv4": "PV4解谜",
    "ORACLE_DATABASE/index/ep15": "第15章解谜",
    "ORACLE_DATABASE/index/2beta test": "二测解谜",
    "ORACLE_DATABASE/index/WHY SO MYSTERIOUS": "神秘档案",
    "ORACLE_DATABASE/index/knowledge base": "知识库",
    "记录者的故事": "记录者的故事",
    "大拓荒周报": "大拓荒周报",
    "午间邮报特刊": "午间邮报特刊",
}


@register
class ExternalStoryCollector(Collector):
    name = "external-story"
    title = "外部剧情：解谜档案与世界观文本"
    help = """采集 PRTS ORACLE_DATABASE 的解谜档案和三份世界观文本，包括 PV1–PV4。

输出：OUT/外部剧情/解谜档案/<页面名>.txt
      OUT/外部剧情/世界观文本/<页面名>.txt
这些页面来自 PRTS，可按修订号增量更新；本地 PDF 与 OCR 不在此范围。"""
    order = 27

    def run(self, ctx: Context) -> Stat:
        out = ctx.out_dir / "外部剧情"
        manifest = Manifest(out / "_manifest.json")
        stat = Stat()
        selected = {title: label for title, label in PAGES.items() if ctx.match(title, label)}
        if ctx.limit:
            selected = dict(list(selected.items())[:ctx.limit])
        revs = ctx.client.revids(selected)
        for title, label in selected.items():
            record = revs.get(title)
            if not record or not record.revid:
                stat.skipped_empty += 1
                continue
            group = "解谜档案" if title.startswith("ORACLE_DATABASE/") else "世界观文本"
            target = out / group / f"{label}.txt"
            sig = signature(record.revid)
            if not need_update(ctx, manifest, title, sig, target.exists()):
                stat.skipped += 1
                continue
            if ctx.dry_run:
                stat.dry_run_note = f"待抓取 {label} 等页面"
                continue
            parsed = ctx.client.api(action="parse", page=title, prop="text",
                                    disablelimitreport=1, disableeditsection=1).get("parse", {})
            body = html_to_text(parsed.get("text", "")).strip()
            if not body:
                stat.skipped_empty += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            write_text(target, f"{label}\n来源：https://prts.wiki/w/{title.replace(' ', '_')}\n\n{body}\n")
            manifest.record(title, sig, revid=record.revid, files=[target.name], count=1)
            stat.written += 1
        if not ctx.dry_run:
            manifest.save()
            for group in ("解谜档案", "世界观文本"):
                labels = [label for title, label in PAGES.items()
                          if (title.startswith("ORACLE_DATABASE/")) == (group == "解谜档案")]
                index = f"# 外部剧情 · {group}\n\n" + "\n".join(
                    f"- [{label}]({label}.txt)" for label in labels) + "\n"
                write_text(out / group / "_索引.md", index)
            write_text(out / "_索引.md", "# 外部剧情\n\n- [解谜档案](解谜档案/_索引.md)\n- [世界观文本](世界观文本/_索引.md)\n")
        return stat
