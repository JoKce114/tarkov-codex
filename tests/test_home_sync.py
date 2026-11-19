import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from app.datasets import DATASET_KEYS
from app.guides import GuideStore
from app.home_sync import HomeSync
from app.store import DataStore
from app.sync import SyncManager


class HomeSyncTests(unittest.TestCase):
	def test_guide_coverage_matches_each_modes_unfiltered_task_list(self) -> None:
		with TemporaryDirectory() as temp:
			root = Path(temp)
			for mode, task_ids in {"pve": ("shared", "pve", "missing"), "regular": ("shared", "pvp")}.items():
				folder = root / mode
				folder.mkdir()
				tasks = {task_id: {"id": task_id, "name": task_id} for task_id in task_ids}
				(folder / "tasks.json").write_text(json.dumps({"data": {"tasks": tasks}}), encoding="utf-8")
			store = DataStore(root)
			guides = GuideStore(store)
			page = {"url": "https://www.optarkov.com/task/1", "title": "任务攻略", "sections": [{"type": "text", "text": "攻略正文"}]}
			guides._write({
				"pages": {"1": page, "2": {**page, "sections": []}},
				"byTask": {"shared": "1", "pve": page, "otherMode": "1", "missing": "2"},
				"statistics": {"matched": 3, "discovered": 5},
			})
			cdk = Mock()
			cdk.status.return_value = {"syncedAt": "", "count": 0}
			home = HomeSync(store, SyncManager(root), guides, cdk)
			for mode, covered in (("pve", 2), ("regular", 1), ("pvp-season", 0)):
				with self.subTest(mode=mode):
					store.set_mode(mode)
					history = home.status()["history"]["guides"]
					self.assertEqual(history["coverage"], {
						"mode": mode, "guided": covered, "total": store.search_tasks()["total"],
					})
					self.assertEqual((history["matched"], history["discovered"]), (3, 5))

	def test_home_reports_a_guide_sync_started_outside_the_home(self) -> None:
		with TemporaryDirectory() as temp:
			root = Path(temp)
			store = DataStore(root)
			guides = GuideStore(store)
			guides._syncing = True
			guides._progress = {"processed": 4, "total": 7}
			cdk = Mock()
			cdk.status.return_value = {"syncedAt": "", "count": 0}
			home = HomeSync(store, SyncManager(root), guides, cdk)
			status = home.status()
			self.assertTrue(status["running"])
			self.assertEqual(status["jobs"]["guides"], {"state": "running", "progress": guides._progress})
			guides._syncing = False
			guides.last_result = {"ok": False, "error": "OPtarkov 任务站点地图获取失败", "finishedAt": "2026-11-19T17:42:11"}
			self.assertFalse(home.status()["running"])
			self.assertEqual(home.status()["history"]["guides"]["lastResult"], guides.last_result)
			self.assertNotIn("guides", home.status()["jobs"])

	def test_reopen_keeps_successful_checks_without_changes_and_counts_by_mode(self) -> None:
		with TemporaryDirectory() as temp:
			root = Path(temp)
			manager = SyncManager(root)
			with patch.object(manager, "_sync_one", return_value={"changed": False}):
				self.assertTrue(manager.sync_all()["ok"])
				self.assertTrue(manager.sync_map_layers("pve")["ok"])
			with patch.object(manager, "_sync_one", side_effect=RuntimeError("offline")):
				self.assertFalse(manager.sync_map_layers("pve")["ok"])
			folder = root / "maps" / "pve"
			folder.mkdir(parents=True)
			(folder / "maps.json").write_text(json.dumps({"maps": [
				{"bosses": [{"slug": "killa"}, {"slug": "killa"}]}, {"bosses": [{"slug": "reshala"}]},
			]}), encoding="utf-8")
			store = DataStore(root)
			guides = GuideStore(store)
			guides._write({
				"syncedAt": "2026-03-02T11:12:13", "lastSuccessfulAt": "2026-03-01T11:12:13",
				"statistics": {"matched": 368, "discovered": 505, "unmatched": 32, "failed": 1},
			})
			cdk = Mock()
			cdk.status.return_value = {"syncedAt": "2026-03-03T11:12:13", "count": 12}
			home = HomeSync(store, SyncManager(root), guides, cdk)
			history = home.status()["history"]
			self.assertTrue(history["game"]["lastSuccessfulAt"])
			self.assertTrue(history["maps"]["lastSuccessfulAt"])
			self.assertEqual(history["game"]["changedCount"], 0)
			self.assertEqual(history["game"]["total"], len(DATASET_KEYS))
			self.assertEqual((history["maps"]["maps"], history["maps"]["bosses"]), (2, 2))
			self.assertEqual(history["guides"]["lastSuccessfulAt"], "2026-03-01T11:12:13")
			self.assertEqual(history["guides"]["failed"], 1)
			self.assertEqual(history["cdk"]["count"], 12)
			store.mode = "regular"
			self.assertEqual(home.status()["history"]["maps"]["maps"], 0)
