"""Story folders sort naturally and old downloads remain usable after migration."""

import json

from prts_tool.collectors.avg import decide_bucket, decide_folder
from prts_tool.story_layout import migrate_story_layout, story_relative_path


def test_story_folder_rules():
    assert decide_folder("主线", "异卵同生", "", 2, "主线") == "第02章 异卵同生"
    assert decide_bucket("剧情", "", "四月辑录", "断罪者的挑战状", set()) == "特殊"
    assert decide_folder("剧情", "断罪者的挑战状", "四月辑录", None, "特殊") == "四月辑录/断罪者的挑战状"
    assert decide_folder("剧情", "危机合约", "特殊", None) == "特殊/危机合约"
    assert story_relative_path("主线/第9章 风暴/1.txt") == "主线/第09章 风暴/1.txt"


def test_story_migration_updates_files_and_manifest(tmp_path):
    root = tmp_path / "avg"
    source = root / "四月辑录/断罪者的挑战状/0001.txt"
    source.parent.mkdir(parents=True)
    source.write_text("文本", encoding="utf-8")
    chapter = root / "主线/第1章 黑暗时代/0002.txt"
    chapter.parent.mkdir(parents=True)
    chapter.write_text("主线", encoding="utf-8")
    manifest = {"items": {"one": {"folder": "四月辑录/断罪者的挑战状",
                                   "file": "四月辑录/断罪者的挑战状/0001.txt"}}}
    (root / "_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    assert migrate_story_layout(root) == 2
    assert (root / "特殊/四月辑录/断罪者的挑战状/0001.txt").read_text(encoding="utf-8") == "文本"
    assert (root / "主线/第01章 黑暗时代/0002.txt").is_file()
    assert json.loads((root / "_manifest.json").read_text(encoding="utf-8"))["items"]["one"]["folder"] == "特殊/四月辑录/断罪者的挑战状"
    assert migrate_story_layout(root) == 0
