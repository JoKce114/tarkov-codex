import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.guides import DETAIL, GuideStore
from app.store import DataStore


class GuideProgressTests(unittest.TestCase):
	def setUp(self):
		temp = TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
		self.addCleanup(temp.cleanup)
		self.store = DataStore(Path(temp.name))
		self.store.tasks = {"task": {"normalizedName": "delivery", "name": "交货"}}
		self.guides = GuideStore(self.store)
		self.page = {"english": "Delivery", "title": "交货", "sections": [{"type": "tip", "text": "攻略"}],
			"lastmod": "v1", "url": DETAIL + "1"}
		self.legacy = {"syncedAt": "2024-01-01T12:00:00", "pages": {"1": self.page}, "byTask": {"task": "1"},
			"statistics": {"discovered": 1, "fetched": 1, "skipped": 0, "failed": 0, "matched": 1}}
		self.guides._write(self.legacy)

	def sitemap(self, **pages):
		return "<urlset>" + "".join(
			f"<url><loc>{DETAIL}{number}</loc><lastmod>{modified}</lastmod></url>"
			for number, modified in pages.items()
		) + "</urlset>"

	def test_all_reused_reports_matching_and_survives_restart(self):
		seen = []
		def observe():
			status = self.guides.status()
			self.assertTrue(status["syncing"])
			seen.append(status["progress"])
		save = self.guides._write
		names = self.guides._task_names
		def fetch(url):
			observe()
			return self.sitemap(**{"1": "v1"})
		def match():
			observe()
			return names()
		def write(payload):
			observe()
			save(payload)
		with patch.object(self.guides, "_fetch", side_effect=fetch), patch.object(self.guides, "_task_names", side_effect=match), patch.object(self.guides, "_write", side_effect=write):
			result = self.guides.sync()
		self.assertEqual([row["stage"] for row in seen], ["sitemap", "match", "save"])
		self.assertEqual((seen[1]["total"], seen[1]["skipped"], seen[1]["matchTotal"]), (0, 1, 1))
		self.assertEqual(seen[2]["matchProcessed"], 1)
		status = GuideStore(self.store).status()
		self.assertEqual(status["lastResult"], result)
		self.assertEqual(result["progress"]["stage"], "done")
		self.assertTrue(result["startedAt"])
		self.assertEqual(status["sources"]["optarkov"]["lastSuccessfulAt"], result["finishedAt"])

	def test_partial_failure_reports_current_counts_preserves_previous_success_and_retries(self):
		sitemap = self.sitemap(**{"1": "v2", "2": "v1"})
		seen = []
		def fetch_page(number):
			seen.append(self.guides.status()["progress"])
			if number == "1":
				raise ValueError("offline")
			return {**self.page, "url": DETAIL + number, "sections": []}
		with patch.object(self.guides, "_fetch", return_value=sitemap), patch.object(self.guides, "_read_page", side_effect=fetch_page):
			result = self.guides.sync()
		self.assertTrue(all(row["stage"] == "fetch" and row["total"] == 2 for row in seen))
		status = GuideStore(self.store).status()
		self.assertEqual(status["lastResult"], result)
		self.assertFalse(result["ok"])
		self.assertTrue(result["error"])
		progress = result["progress"]
		self.assertEqual((progress["stage"], progress["fetched"], progress["failed"], progress["processed"]), ("error", 1, 1, 2))
		self.assertEqual(result["sources"]["optarkov"]["failedPages"], [1])
		self.assertEqual(status["sources"]["optarkov"]["lastSuccessfulAt"], self.legacy["syncedAt"])
		self.assertTrue(self.guides.get("task"))
		with patch.object(self.guides, "_fetch", return_value=sitemap), patch.object(self.guides, "_read_page", return_value=self.page) as read:
			retry = self.guides.sync()
		read.assert_called_once_with("1")
		self.assertEqual((retry["progress"]["skipped"], retry["progress"]["fetched"]), (1, 1))
		self.assertTrue(retry["ok"])

	def test_failed_sitemap_persists_attempt_independently_of_previous_statistics(self):
		old = self.guides.status()
		self.assertEqual(old["lastResult"]["finishedAt"], self.legacy["syncedAt"])
		self.assertTrue(old["lastResult"]["ok"])
		with patch.object(self.guides, "_fetch", side_effect=RuntimeError("offline")):
			result = self.guides.sync()
		new = GuideStore(self.store).status()
		self.assertFalse(new["syncing"])
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"], "offline")
		self.assertEqual(new["lastResult"], result)
		self.assertEqual(result["progress"]["discovered"], 0)
		self.assertEqual(result["progress"]["failedStage"], "sitemap")
		self.assertEqual(new["sources"]["optarkov"], old["sources"]["optarkov"])
		self.assertTrue(self.guides.get("task"))

	def test_legacy_direct_guide_is_retained_if_its_source_page_fails(self):
		self.guides._write({"syncedAt": self.legacy["syncedAt"], "byTask": {"task": self.page}})
		with patch.object(self.guides, "_fetch", return_value=self.sitemap(**{"1": "v2"})), patch.object(self.guides, "_read_page", side_effect=ValueError("offline")):
			result = self.guides.sync()
		self.assertFalse(result["ok"])
		self.assertEqual(self.guides.get("task")[0]["sections"], self.page["sections"])

	def test_failed_cache_commit_records_failure_without_publishing_new_statistics(self):
		original = self.guides._write
		def write(payload):
			if payload["lastResult"]["ok"]:
				raise OSError("disk busy")
			original(payload)
		with patch.object(self.guides, "_fetch", return_value=self.sitemap(**{"1": "v1"})), patch.object(self.guides, "_write", side_effect=write):
			result = self.guides.sync()
		self.assertFalse(result["ok"])
		self.assertFalse(result["sources"]["optarkov"]["ok"])
		self.assertEqual(result["progress"]["failedStage"], "save")
		reopened = GuideStore(self.store).status()
		self.assertEqual(reopened["lastResult"], result)
		self.assertEqual(reopened["sources"]["optarkov"]["fetched"], 1)
		self.assertEqual(reopened["sources"]["optarkov"]["lastSuccessfulAt"], self.legacy["syncedAt"])
