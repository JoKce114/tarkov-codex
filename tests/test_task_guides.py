from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import create_app
from app.guides import GuideStore
from app.progress import ProgressStore
from app.store import DataStore


class TaskGuideListTests(unittest.TestCase):
	def test_filter_and_badges_share_detail_ids_before_paging(self) -> None:
		with TemporaryDirectory() as folder:
			data = DataStore(Path(folder))
			for pos, key in enumerate(("empty", "first", "second", "other", "non-kappa", "completed", "locked", "different-name")):
				data.tasks[key] = {
					"id": key, "name": f"Route {pos}" if key != "different-name" else "Unrelated",
					"trader": "trader" if key != "other" else "another", "kappaRequired": key != "non-kappa",
					"minPlayerLevel": 10 if key == "locked" else 1,
				}
			guides = GuideStore(data)
			guides._write({"byTask": {key: key for key in data.tasks}, "pages": {key: {
				"url": "source", "sections": [] if key == "empty" else [{"type": "tip", "text": "A"}],
			} for key in data.tasks}})
			progress = ProgressStore(data.data_dir / "progress.json")
			client = TestClient(create_app(data, None, progress, None, guides, None))
			client.post("/api/progress/task", json={"taskId": "completed", "completed": True}).raise_for_status()
			params = {"q": "Route", "trader": "trader", "kappa": True, "hideLocked": True, "hideCompleted": True, "limit": 1}
			with patch.object(guides, "guided_task_ids", wraps=guides.guided_task_ids) as read_ids:
				first = client.get("/api/tasks", params=params).json()
				self.assertEqual(first["total"], 3)
				self.assertFalse(first["tasks"][0]["hasGuide"])
				read_ids.assert_called_once()
			params["hasGuide"] = True
			for offset, expected in enumerate(("first", "second")):
				result = client.get("/api/tasks", params={**params, "offset": offset}).json()
				self.assertEqual(result["total"], 2)
				self.assertEqual(result["tasks"][0]["id"], expected)
				self.assertTrue(result["tasks"][0]["hasGuide"])
				self.assertTrue(client.get(f"/api/tasks/{expected}/guides").json()["guides"])
			self.assertFalse(client.get("/api/tasks/empty/guides").json()["guides"])
