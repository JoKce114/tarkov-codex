import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.guides import GuideStore
from app.store import DataStore


class GuideSourceTests(unittest.TestCase):
	def test_available_ids_match_displayable_detail_and_refresh_after_replacement(self) -> None:
		with TemporaryDirectory() as folder:
			store = GuideStore(DataStore(Path(folder)))
			good = {"url": "source", "sections": [{"type": "howto", "text": "提示"}]}
			empty = {"url": "source", "title": "只有标题", "sections": [
				{"type": "text", "text": " "}, {"type": "image", "images": []}, {"type": "unsupported"},
			]}
			store._write({"byTask": {"id": "2", "alias": "2", "legacy": good, "empty": empty, "orphan": "3"}, "pages": {"2": good}})
			with patch("app.guides.json.loads", wraps=json.loads) as parse:
				self.assertEqual(store.guided_task_ids(), {"id", "alias", "legacy"})
				self.assertEqual({key for key in ("id", "alias", "legacy", "empty", "orphan") if store.get(key)}, store.guided_task_ids())
				store.status()
				self.assertLessEqual(parse.call_count, 1)
			store._write({"byTask": {"id": "2"}, "pages": {"2": empty}})
			self.assertFalse(store.guided_task_ids())
			self.assertFalse(store.get("id"))

	def test_wiki_titles_recover_only_the_correct_cached_prestige_guides(self) -> None:
		with TemporaryDirectory() as folder:
			root = Path(folder)
			data = DataStore(root, "pve")
			data.tasks = {"other": {"normalizedName": "unrelated", "name": "其他任务"}}
			regular = root / "regular"
			regular.mkdir()
			tasks = {
				str(stage): {
					"name": "新起点", "normalizedName": f"new-beginning-{stage}",
					"wikiLink": f"https://escapefromtarkov.fandom.com/wiki/New_Beginning_%28Prestige_{stage}%29",
				} for stage in (2, 3, 4)
			}
			tasks["ambiguous"] = {**tasks["4"], "normalizedName": "different-task"}
			(regular / "tasks.json").write_text(json.dumps({"data": {"tasks": tasks}}), encoding="utf-8")
			guides = GuideStore(data)
			pages = {str(stage): {
				"english": f"New Beginning (Prestige {stage})", "title": f"新起点（{stage}转）",
				"url": f"https://www.optarkov.com/wiki/task/{stage}", "sections": [{"type": "tip", "text": "test"}],
				"lastmod": "2026-01-01",
			} for stage in (2, 3, 4, 5)}
			guides._write({"pages": pages})
			sitemap = "<urlset>" + "".join(
				f"<url><loc>{guide['url']}</loc><lastmod>{guide['lastmod']}</lastmod></url>" for guide in pages.values()
			) + "</urlset>"
			with patch.object(guides, "_fetch", return_value=sitemap), patch.object(guides, "_read_page") as read_page:
				for mode in ("pve", "regular"):
					data.set_mode(mode)
					result = guides.sync()["sources"]["optarkov"]
					self.assertEqual(result["unmatchedPages"], [4, 5])
					self.assertEqual(guides._read()["byTask"], {"2": "2", "3": "3"})
				read_page.assert_not_called()

	def test_generic_guides_link_to_each_mode_and_faction_task_id(self) -> None:
		with TemporaryDirectory() as folder:
			data = DataStore(Path(folder))
			data.tasks = {"bear": {"normalizedName": "textile-part-1-bear", "name": "纺织业"}}
			other = Path(folder) / "regular"
			other.mkdir()
			(other / "tasks.json").write_text(json.dumps({"data": {"tasks": {
				"usec": {"normalizedName": "textile-part-1-usec", "name": "USEC Name"},
			}}}), encoding="utf-8")
			guides = GuideStore(data)
			sitemap = '<urlset><url><loc>https://www.optarkov.com/wiki/task/1</loc></url></urlset>'
			guide = {"english": "Textile - Part 1", "title": "纺织业", "url": "source", "sections": [{"type": "tip", "text": "A"}]}
			with patch.object(guides, "_fetch", return_value=sitemap), patch.object(guides, "_read_page", return_value=guide):
				guides.sync()
			self.assertTrue(guides.get("bear"))
			self.assertTrue(guides.get("usec"))

	def test_sparse_sitemap_resumes_failed_pages_and_preserves_a_previous_guide(self) -> None:
		with TemporaryDirectory() as folder:
			data = DataStore(Path(folder))
			data.tasks = {"game-id": {"normalizedName": "task-2", "name": "任务二"}}
			guides = GuideStore(data)
			sitemap = '<urlset>' + ''.join(f'<url><loc>https://www.optarkov.com/wiki/task/{n}</loc></url>' for n in (2, 706)) + '</urlset>'
			page = [{"wiki-task-meta-2": 1}, {"name": 2, "localizedName": 3, "tips": 4}, "Task 2", "任务二", [5], "路线"]
			html = '<script id="__NUXT_DATA__">' + json.dumps(page) + '</script>'
			def fetch(url):
				if url.endswith("sitemap.xml"):
					return sitemap
				return html if url.endswith("/2") else None
			with patch.object(guides, "_fetch", side_effect=fetch):
				result = guides.sync()
			self.assertFalse(result["ok"])
			self.assertEqual(result["sources"]["optarkov"]["failedPages"], [706])
			self.assertEqual(guides.get("game-id")[0]["sections"][0]["text"], "路线")
			with patch.object(guides, "_fetch", side_effect=lambda url: sitemap if url.endswith(".xml") else None) as retry:
				result = guides.sync()
			self.assertEqual(result["sources"]["optarkov"]["skipped"], 1)
			self.assertEqual(len(retry.call_args_list), 2)
			with patch.object(guides, "_fetch", side_effect=lambda url: sitemap if url.endswith(".xml") else None):
				guides.sync(force=True)
			self.assertEqual(guides.get("game-id")[0]["sections"][0]["text"], "路线")
