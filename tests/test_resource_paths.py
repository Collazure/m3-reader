"""Checks that the migrated resource library remains reachable from its sources."""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from urllib.parse import unquote

from prts_tool import ocr_book
from prts_tool.paths import (
    BOOK_DIR,
    DEFAULT_TERRA_DIR,
    DEFAULT_TEXT_DIR,
    TERRA_OCR_DIR,
    data_root,
)
from prts_tool.registry import build_context


class ResourcePathsTest(unittest.TestCase):
    def test_default_paths_and_custom_terra(self):
        context = build_context({}, log=lambda _: None)
        self.assertEqual(context.out_dir, DEFAULT_TEXT_DIR)
        self.assertEqual(data_root(context.out_dir, "terra"), DEFAULT_TERRA_DIR)
        self.assertEqual(data_root(Path("other/prts_text"), "terra"),
                         Path("other/terra").resolve())
        self.assertTrue(DEFAULT_TEXT_DIR.is_dir())
        self.assertTrue(DEFAULT_TERRA_DIR.is_dir())
        self.assertTrue(TERRA_OCR_DIR.is_dir())

    def test_ocr_defaults_and_source_links(self):
        self.assertEqual(ocr_book.DEFAULT_PDF.parent, BOOK_DIR)
        self.assertTrue(ocr_book.DEFAULT_PDF.is_file())
        self.assertTrue(ocr_book.DEFAULT_TXT.is_file())
        self.assertEqual(ocr_book.DEFAULT_TXT.parent, ocr_book.DEFAULT_TEXT_DIR)
        self.assertTrue(ocr_book.DEFAULT_IMAGE_DIR.is_dir())
        self.assertTrue(ocr_book.DEFAULT_PAGE_TEXT_DIR.is_dir())
        self.assertFalse((BOOK_DIR / "大地巡旅_OCR_pages").exists())

        seen = 0
        for article in TERRA_OCR_DIR.rglob("*.md"):
            for target in re.findall(r"\]\(([^)]+)\)", article.read_text(encoding="utf-8")):
                if "collected/terra/" not in target:
                    continue
                path = (article.parent / unquote(target)).resolve()
                self.assertTrue(path.is_file(), f"{article}: {target}")
                seen += 1
        self.assertGreaterEqual(seen, 169)


class OcrLayoutMigrationTest(unittest.TestCase):
    def test_old_mixed_layout_moves_to_images_and_text(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            book = Path(temp)
            legacy = book / "大地巡旅_OCR_pages"
            legacy.mkdir()
            (legacy / "page_0001.jpg").write_bytes(b"jpg")
            (legacy / "page_0001.txt").write_text("正文\n", encoding="utf-8")
            (legacy / "manifest.tsv").write_text("page\tpath\tchars\n", encoding="utf-8")
            (book / "大地巡旅_OCR.txt").write_text("全文\n", encoding="utf-8")

            moved = ocr_book.migrate_layout(book)

            self.assertEqual(len(moved), 4)
            self.assertTrue((book / "images" / "page_0001.jpg").is_file())
            self.assertTrue((book / "text" / "pages" / "page_0001.txt").is_file())
            self.assertTrue((book / "text" / "manifest.tsv").is_file())
            self.assertTrue((book / "text" / "大地巡旅_OCR.txt").is_file())
            self.assertFalse(legacy.exists())


if __name__ == "__main__":
    unittest.main()
