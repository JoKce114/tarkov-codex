from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from requests import ConnectionError, Response

from app import paths


class MapIconTests(unittest.TestCase):
	def setUp(self):
		from app.map_icons import map_icons_router, sync_map_icons

		self.temp = TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
		self.addCleanup(self.temp.cleanup)
		root = Path(self.temp.name)
		self.data = root / "data"
		self.original = (paths.WEB_DIR / "map_icons" / "lock.png").read_bytes()
		self.updated = (paths.WEB_DIR / "map_icons" / "key.png").read_bytes()
		web = root / "web"
		folder = web / "map_icons"
		folder.mkdir(parents=True)
		(folder / "lock.png").write_bytes(self.original)
		(folder / "LICENSE.txt").write_text("license", encoding="utf-8")
		self.enterContext(patch.object(paths, "WEB_DIR", web))
		self.sync = sync_map_icons
		app = FastAPI()
		app.include_router(map_icons_router(self.data))
		self.client = self.enterContext(TestClient(app))
		self.url = "/map_icons/lock.png"

	def sync_with(self, status, body=b"", **headers):
		response = Response()
		response.status_code = status
		response.headers.update(headers)
		response._content = body
		with patch("requests.sessions.Session.send", return_value=response) as send:
			result = self.sync(self.data)
		self.assertEqual(send.call_count, 1)
		request = send.call_args.args[0]
		self.assertEqual(request.url, "https://tarkov.dev/maps/interactive/lock.png")
		self.assertEqual(request.headers["Accept"], "image/png")
		return result, request.headers

	def test_first_sync_and_304_refresh_browser_and_preserve_local_copy(self):
		bundled = self.client.get(self.url)
		first, _ = self.sync_with(200, self.updated, ETag='"v2"')
		self.assertEqual((first["ok"], first["count"], first["changed"]), (True, 1, 1))
		new = self.client.get(self.url, headers={"If-None-Match": bundled.headers["ETag"]})
		self.assertEqual((new.status_code, new.content), (200, self.updated))
		self.assertIn("no-cache", new.headers["Cache-Control"])
		head = self.client.head(self.url)
		self.assertEqual(head.status_code, 200)
		self.assertEqual(head.headers["ETag"], new.headers["ETag"])
		self.assertEqual(int(head.headers["Content-Length"]), len(self.updated))
		second, conditional = self.sync_with(304)
		self.assertEqual(conditional["If-None-Match"], '"v2"')
		self.assertEqual((second["ok"], second["count"], second["changed"]), (True, 1, 0))
		self.assertEqual(self.client.get(self.url, headers={"If-None-Match": new.headers["ETag"]}).status_code, 304)

	def test_unchanged_bundled_icon_uses_last_modified_for_next_check(self):
		modified = "Mon, 26 Jan 2026 00:00:00 GMT"
		result, _ = self.sync_with(200, self.original, **{"Last-Modified": modified})
		self.assertEqual(result["changed"], 0)
		checked, headers = self.sync_with(304)
		self.assertTrue(checked["ok"])
		self.assertEqual(headers["If-Modified-Since"], modified)

	def test_corrupt_or_failed_response_keeps_last_good_icon(self):
		self.sync_with(200, self.updated, ETag='"v2"')
		for status, body in ((200, b"<html>error</html>"), (200, self.original[:-6]), (503, b"offline")):
			with self.subTest(status=status, length=len(body)):
				result, _ = self.sync_with(status, body)
				self.assertFalse(result["ok"])
				self.assertIn("lock.png", result["error"])
				self.assertEqual(self.client.get(self.url).content, self.updated)

	def test_offline_read_uses_only_bundled_names(self):
		cache = self.data / "map_icons"
		cache.mkdir(parents=True)
		(cache / "unknown.png").write_bytes(self.updated)
		with patch("requests.sessions.Session.send", side_effect=ConnectionError("offline")) as send:
			self.assertEqual(self.client.get(self.url).content, self.original)
			self.assertEqual(self.client.get("/map_icons/unknown.png").status_code, 404)
			send.assert_not_called()
			self.assertFalse(self.sync(self.data)["ok"])
			self.assertEqual(self.client.get(self.url).content, self.original)
