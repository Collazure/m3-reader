"""Search prioritizes names, respects source scope, and keeps exact lines."""

from prts_tool import library


def test_search_scopes_and_name_priority(tmp_path, monkeypatch):
    root = tmp_path / "resources"
    collected = root / "collected" / "prts_text"
    local = root / "local"
    ocr = root / "ocr" / "terra_text"
    for folder in (collected, local, ocr):
        folder.mkdir(parents=True)
    (collected / "故事.md").write_text("第一行\n关键词在第二行\n", encoding="utf-8")
    (local / "关键词目录.md").write_text("本地正文\n", encoding="utf-8")
    (ocr / "图片.md").write_text("关键词 OCR\n", encoding="utf-8")
    monkeypatch.setattr(library, "RESOURCES_DIR", root)
    hits = library.search_text("关键词", files=iter((collected / "故事.md", local / "关键词目录.md", ocr / "图片.md")))
    assert hits[0].kind == "title"
    assert hits[0].resource_id == "local/关键词目录.md"
    assert any(hit.resource_id == "collected/prts_text/故事.md" and hit.line == 2 for hit in hits)
    assert {hit.resource_id for hit in library.search_text("关键词", scope="ocr")} == {"ocr/terra_text/图片.md"}
    assert {hit.resource_id for hit in library.search_text("关键词", scope="collected")} == {"collected/prts_text/故事.md"}


def test_parse_search_request():
    assert library.parse_search_request("--scope local 泰拉 年表") == ("泰拉 年表", "local")
    assert library.parse_search_request("泰拉 年表") == ("泰拉 年表", "all")
