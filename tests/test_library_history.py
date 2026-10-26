from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from click.testing import CliRunner

from prts_tool.cli import build_cli
from prts_tool.history import HistoryCapture, _snapshot, diff_rows, diff_text, import_local, load_run
from prts_tool.jobs import UpdateCapture, update_command_sequence
from prts_tool.library import append_opinion, note_location, read_opinions, save_note, search_text
from prts_tool.paths import BOOK_TEXT_DIR, DEFAULT_TEXT_DIR, PROJECT_DIR


class LibraryHistoryTest(unittest.TestCase):
    def test_cli_full_update_includes_terra_images(self):
        with patch("prts_tool.cli.run_modules") as run:
            result = CliRunner().invoke(build_cli(), ["update", "--images"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[1].args[0][0].name, "terra")
        self.assertTrue(run.call_args_list[1].args[1]["images"])

    def test_full_update_adds_image_stage(self):
        self.assertEqual(update_command_sequence("avg", "changed"),
                         [["refresh", "-m", "avg", "--mode", "changed"]])
        self.assertEqual(update_command_sequence("avg", "missing", full=True),
                         [["refresh", "-m", "all", "--mode", "missing"],
                          ["terra-images", "--mode", "missing"]])

    def test_only_one_writer_can_hold_update_lock(self):
        with UpdateCapture(DEFAULT_TEXT_DIR, [], dry_run=True):
            with self.assertRaises(RuntimeError):
                with UpdateCapture(DEFAULT_TEXT_DIR, [], dry_run=True):
                    pass

    def test_search_maps_book_ocr_hit_to_page(self):
        path = BOOK_TEXT_DIR / "大地巡旅_OCR.txt"
        hits = search_text("伊比利亚", files=iter([path]), limit=20)
        self.assertTrue(hits)
        self.assertTrue(all(hit.page and hit.line > 0 for hit in hits))

    def test_history_keeps_old_and_new_lines(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_DIR) as temp:
            root = Path(temp)
            resource = root / "sample.txt"
            resource.write_text("旧行\n共有\n", encoding="utf-8")
            with patch("prts_tool.history.relative_id", side_effect=lambda p: p.name), \
                 patch("prts_tool.history.HISTORY_DIR", root / "history"):
                before = {"sample.txt": ("text", resource.read_text(encoding="utf-8"))}
                capture = HistoryCapture("test", (root,), before, "2026-10-25T00:00:00+08:00")
                resource.write_text("新行\n共有\n", encoding="utf-8")
                run = capture.finish()
                self.assertEqual(len(run["changes"]), 1)
                self.assertIn("-旧行", diff_text(run["changes"][0]))
                self.assertIn("+新行", diff_text(load_run(run["id"])["changes"][0]))

    def test_disk_snapshot_keeps_change_semantics_and_cleans_up(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_DIR) as temp:
            root = Path(temp)
            unchanged = root / "unchanged.txt"
            changed = root / "changed.txt"
            removed = root / "removed.txt"
            image = root / "cover.jpg"
            for path, content in ((unchanged, "不变\n"), (changed, "旧正文\n"), (removed, "删除\n")):
                path.write_text(content, encoding="utf-8")
            image.write_bytes(b"old-image")
            with patch("prts_tool.history.relative_id", side_effect=lambda p: p.name), \
                 patch("prts_tool.history.HISTORY_DIR", root / "history"):
                before = _snapshot((root,))
                snapshot_dir = Path(before._temporary.name)
                capture = HistoryCapture("test", (root,), before, "2026-10-25T00:00:00+08:00")
                changed.write_text("新正文\n", encoding="utf-8")
                removed.unlink()
                (root / "added.txt").write_text("新增\n", encoding="utf-8")
                image.write_bytes(b"new-image")
                run = capture.finish(status="failed", error="test failure")
                changes = {item["resource_id"]: item for item in run["changes"]}
                self.assertEqual(set(changes), {"changed.txt", "removed.txt", "added.txt", "cover.jpg"})
                self.assertEqual((changes["changed.txt"]["old"], changes["changed.txt"]["new"]),
                                 ("旧正文\n", "新正文\n"))
                self.assertEqual(changes["removed.txt"]["action"], "deleted")
                self.assertEqual(changes["added.txt"]["action"], "added")
                self.assertEqual(changes["cover.jpg"]["kind"], "image")
                self.assertEqual(run["status"], "failed")
                self.assertFalse(snapshot_dir.exists())

    def test_disk_snapshot_ignores_timestamp_only_changes_and_cleans_on_save_error(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_DIR) as temp:
            root = Path(temp)
            resource = root / "sample.txt"
            resource.write_text("抓取时间：2026-10-25 00:00:00\n正文\n", encoding="utf-8")
            with patch("prts_tool.history.relative_id", side_effect=lambda p: p.name), \
                 patch("prts_tool.history.HISTORY_DIR", root / "history"):
                before = _snapshot((root,))
                snapshot_dir = Path(before._temporary.name)
                capture = HistoryCapture("test", (root,), before, "2026-10-25T00:00:00+08:00")
                resource.write_text("抓取时间：2026-10-26 00:00:00\n正文\n", encoding="utf-8")
                self.assertEqual(capture.finish()["changes"], [])
                self.assertFalse(snapshot_dir.exists())

                before = _snapshot((root,))
                snapshot_dir = Path(before._temporary.name)
                capture = HistoryCapture("test", (root,), before, "2026-10-25T00:00:00+08:00")
                with patch("prts_tool.history._save_run", side_effect=OSError("disk full")):
                    with self.assertRaises(OSError):
                        capture.finish()
                self.assertFalse(snapshot_dir.exists())

    def test_update_initialization_failure_cleans_snapshot_and_unlocks(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_DIR) as temp:
            root = Path(temp)
            with patch("prts_tool.jobs.WORKSPACE_DIR", root), \
                 patch("prts_tool.history.WORKSPACE_DIR", root), \
                 patch("prts_tool.jobs.LatestCapture", side_effect=OSError("setup failed")):
                with self.assertRaises(OSError):
                    with UpdateCapture(DEFAULT_TEXT_DIR, []):
                        pass
                self.assertFalse(list(root.glob(".history-snapshot-*")))
                with UpdateCapture(DEFAULT_TEXT_DIR, [], dry_run=True):
                    pass

    def test_local_replace_preserves_previous_version(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_DIR) as temp:
            root = Path(temp)
            resources = root / "resources"
            workspace = root / "workspace"
            source = root / "incoming.txt"
            source.write_text("第一版\n", encoding="utf-8")

            def local_id(path):
                return path.relative_to(resources).as_posix()

            with patch("prts_tool.history.RESOURCES_DIR", resources), \
                 patch("prts_tool.history.WORKSPACE_DIR", workspace), \
                 patch("prts_tool.history.HISTORY_DIR", workspace / "history"), \
                 patch("prts_tool.history.relative_id", side_effect=local_id), \
                 patch("prts_tool.history.resource_path", side_effect=lambda value: resources / value):
                first = import_local(source)
                target_id = first["changes"][0]["resource_id"]
                source.write_text("第二版\n", encoding="utf-8")
                second = import_local(source, target_id)
                change = second["changes"][0]
                self.assertEqual(change["old"], "第一版\n")
                self.assertEqual(change["new"], "第二版\n")
                self.assertEqual((workspace / change["backup"]).read_text(encoding="utf-8"), "第一版\n")

    def test_note_quote_follows_moved_text(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_DIR) as temp:
            root = Path(temp)
            path = root / "story.txt"
            path.write_text("首行\n目标句子\n", encoding="utf-8")
            with patch("prts_tool.library.NOTES_FILE", root / "notes.json"), \
                 patch("prts_tool.library.resource_path", return_value=path):
                note = save_note("local/story.txt", "请校对", line=2, quote="目标句子")
                path.write_text("新增行\n首行\n目标句子\n", encoding="utf-8")
                self.assertEqual(note_location(note), (3, False))
                path.write_text("新增行\n首行\n", encoding="utf-8")
                self.assertEqual(note_location(note), (2, True))

    def test_opinion_file_needs_no_resource(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_DIR) as temp:
            opinions = Path(temp) / "更新意见.md"
            with patch("prts_tool.library.OPINIONS_FILE", opinions):
                append_opinion("核对下一次更新")
                self.assertIn("核对下一次更新", read_opinions())
                self.assertTrue(opinions.is_file())

    def test_diff_rows_include_both_line_numbers(self):
        change = {"kind": "text", "action": "updated", "resource_id": "local/a.txt",
                  "old": "相同\n旧句\n", "new": "相同\n新句\n"}
        rows = diff_rows(change)
        self.assertIn(("remove", 2, None, "旧句"), rows)
        self.assertIn(("add", None, 2, "新句"), rows)


if __name__ == "__main__":
    unittest.main()
