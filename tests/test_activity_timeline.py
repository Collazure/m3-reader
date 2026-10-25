"""泰拉年表 parsing is part of the activity collector (no separate crawler)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from prts_tool.collectors.activity import (TIMELINE_FILE, ActivityCollector,
                                           parse_timeline, render_timeline)
from prts_tool.output import Manifest
from prts_tool.registry import Context, Stat

SAMPLE = """\
==结晶纪元之前==
{| class="wikitable"
|-
!rowspan="2"|前文明时期
|{{并行折叠框|第一段<br>第二行|* [[大地巡旅]]：1.1 源石
* [https://example.com 示例资料]}}
|-
|{{并行折叠框|带弹窗的正文{{popup|内容=平行世界|mdi=eye}}继续|*巴别塔：[[BB-7 阴影显现/BEG|BB-7 行动前]]}}
|-
! TT 197/19/09
|{{并行折叠框|录音内容|* Mon3tr：[[Mon3tr#干员档案|档案资料四]]}}
|}
==可确认的大致时间点==
{| class="wikitable"
|{{并行折叠框|（说明）无日期的条目|*[[情报处理室#去咧嘴谷|去咧嘴谷]]}}
|}
"""


def test_parse_timeline_handles_rowspan_and_multiline_templates():
    events = parse_timeline(SAMPLE)
    assert ("heading", 2, "结晶纪元之前") in events
    labels = [event[1] for event in events if event[0] == "label"]
    assert labels == ["前文明时期", "TT 197/19/09"]
    entries = [event for event in events if event[0] == "entry"]
    assert len(entries) == 4
    assert entries[0][1] == "第一段\n第二行"
    assert entries[0][2] == ["大地巡旅：1.1 源石", "示例资料"]
    # popup notes are removed, the rest of the body survives
    assert entries[1][1] == "带弹窗的正文继续"
    assert ("heading", 2, "可确认的大致时间点") in events


def test_render_timeline_is_readable_text():
    text = render_timeline(SAMPLE)
    assert "来源：PRTS Wiki" in text
    assert "== 结晶纪元之前 ==" in text
    assert "【前文明时期】" in text
    assert "    - 大地巡旅：1.1 源石" in text
    assert "{{" not in text and "[[" not in text


class _FakeClient:
    def __init__(self, content: str, revid: int):
        self.content = content
        self.revid = revid

    def pages(self, titles, with_content=True):
        return {titles[0]: type("Page", (), {"content": self.content, "revid": self.revid})()}


def test_activity_collector_writes_timeline_at_first_level():
    with tempfile.TemporaryDirectory() as temp:
        out = Path(temp)
        client = _FakeClient(SAMPLE, 123)
        ctx = Context(out_dir=out, client=client, log=lambda _="": None)
        collector = ActivityCollector()
        manifest = Manifest(out / "activity" / "_manifest.json")
        stat = Stat()

        collector._collect_timeline(ctx, manifest, stat)
        path = out / TIMELINE_FILE
        assert path.is_file()
        assert "== 结晶纪元之前 ==" in path.read_text(encoding="utf-8")
        assert stat.written == 1

        # unchanged revid -> skipped on the next run
        again = Stat()
        collector._collect_timeline(ctx, manifest, again)
        assert again.skipped == 1
