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


def test_search_formats_filter_name_and_content(tmp_path, monkeypatch):
    root = tmp_path / "resources"
    local = root / "local"
    local.mkdir(parents=True)
    for suffix in (".md", ".txt", ".csv", ".tsv"):
        (local / f"匹配{suffix}").write_text("匹配正文\n", encoding="utf-8")
    monkeypatch.setattr(library, "RESOURCES_DIR", root)
    hits = library.search_text("匹配", formats={".md"})
    assert {hit.resource_id for hit in hits} == {"local/匹配.md"}
    assert {hit.kind for hit in hits} == {"title", "content"}


def test_binary_formats_are_filename_only_and_off_by_default(tmp_path, monkeypatch):
    root = tmp_path / "resources"
    local = root / "local"
    local.mkdir(parents=True)
    (local / "匹配.txt").write_text("匹配正文\n", encoding="utf-8")
    (local / "匹配.pdf").write_bytes(b"%PDF-1.7\n")
    (local / "匹配.png").write_bytes(b"PNG")
    monkeypatch.setattr(library, "RESOURCES_DIR", root)
    assert {hit.resource_id for hit in library.search_text("匹配")} == {"local/匹配.txt"}
    hits = library.search_text("匹配", formats={".pdf", ".png"})
    assert {hit.resource_id for hit in hits} == {"local/匹配.pdf", "local/匹配.png"}
    assert {hit.kind for hit in hits} == {"title"}


def test_nested_search_tags_and_exclusion(tmp_path, monkeypatch):
    root = tmp_path / "resources"
    main = root / "collected/prts_text/avg/主线/第01章"
    special = root / "collected/prts_text/avg/特殊/四月辑录"
    local = root / "local"
    for folder in (main, special, local):
        folder.mkdir(parents=True)
        (folder / "sample.txt").write_text("匹配\n", encoding="utf-8")
    monkeypatch.setattr(library, "RESOURCES_DIR", root)
    assert library.resource_tags("collected/prts_text/avg/主线/第01章/sample.txt") >= {"下载", "主线"}
    assert library.resource_tags("collected/prts_text/avg/特殊/四月辑录/sample.txt") >= {"下载", "特殊"}
    hits = library.search_text("匹配", include_tags={"下载"}, exclude_tags={"特殊"})
    assert {hit.resource_id for hit in hits} == {"collected/prts_text/avg/主线/第01章/sample.txt"}
    hits = library.search_text("匹配", include_tags={"当前目录"},
                               current_directory="collected/prts_text/avg/特殊")
    assert {hit.resource_id for hit in hits} == {"collected/prts_text/avg/特殊/四月辑录/sample.txt"}


def test_operator_tag_covers_operator_directory(tmp_path, monkeypatch):
    root = tmp_path / "resources"
    operator = root / "collected/prts_text/operator/阿米娅"
    main = root / "collected/prts_text/avg/主线"
    for folder in (operator, main):
        folder.mkdir(parents=True)
        (folder / "sample.txt").write_text("匹配\n", encoding="utf-8")
    monkeypatch.setattr(library, "RESOURCES_DIR", root)
    assert "干员" in library.SEARCH_TAGS
    assert "干员" in library.resource_tags("collected/prts_text/operator/阿米娅/sample.txt")
    hits = library.search_text("匹配", include_tags={"干员"})
    assert {hit.resource_id for hit in hits} == {"collected/prts_text/operator/阿米娅/sample.txt"}
