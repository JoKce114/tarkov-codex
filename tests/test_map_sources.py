import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from requests import Response

from app.maps import MapStore, map_images, write_catalog
from app.store import DataStore
from app.sync import SyncManager


class MapSourceTests(unittest.TestCase):
	def test_static_map_tabs_use_projection_and_localized_variant(self) -> None:
		images = map_images({"maps": [
			{"key": "lighthouse-2d", "projection": "2D"},
			{"key": "lighthouse-2d-landscape", "projection": "2D", "orientation": "Landscape"},
			{"key": "customs-3d-dorms", "projection": "3D", "specific": "Dorms"},
		]})
		self.assertEqual([image["title"] for image in images], ["2D", "2D · 横版", "3D · 宿舍"])

	def test_catalog_counts_unique_bosses_and_keeps_the_spawn_rates_with_their_zones(self) -> None:
		with TemporaryDirectory() as temp:
			root = Path(temp)
			folder = root / "pve"
			source = {"data": {"maps": {"customs": {
				"normalizedName": "customs", "name": "Customs", "bosses": [
					{"mob": "bossBully", "spawnChance": 0.75, "spawnLocations": [{"name": "Dorms"}]},
					{"mob": "bossBully", "spawnChance": 0.75, "spawnLocations": [{"name": "Gas Station"}]},
					{"mob": "bossBully", "spawnChance": 0.25, "spawnLocations": [{"name": "Fortress"}]},
					{"mob": "pmcBEAR", "spawnChance": 1},
				],
			}}, "mobs": {
				"bossBully": {"name": "bossBully", "normalizedName": "reshala"},
				"pmcBEAR": {"name": "pmcBEAR", "normalizedName": "bear"},
			}}}
			names = {"bossBully": "Reshala", "Dorms": "宿舍", "Gas Station": "加油站", "Fortress": "要塞"}
			write_catalog(folder, source, names=names)
			maps = MapStore(DataStore(root))
			first = maps.maps()[0]
			self.assertEqual(first["bossCount"], 1)
			self.assertEqual([(boss["name"], boss["chance"], boss["zones"]) for boss in first["bosses"]], [
				("Reshala", 75, "宿舍、加油站"), ("Reshala", 25, "要塞"),
			])
			write_catalog(folder, names=names)
			self.assertEqual(first, maps.maps()[0])

	def test_map_sync_shares_single_large_response_and_reuses_it_on_a_translation_only_update(self) -> None:
		with TemporaryDirectory() as temp:
			root = Path(temp)
			manager = SyncManager(root)
			maps = MapStore(DataStore(root))
			map_downloads = []
			revision = 1

			def request(url: str, etag: str) -> Response:
				name = url.rsplit("/", 1)[-1]
				reply = Response()
				stamp = "map-v1" if name == "maps" else f"translation-v{revision}"
				reply.headers["ETag"] = stamp
				if etag == stamp:
					reply.status_code = 304
					return reply
				reply.status_code = 200
				if name == "maps":
					map_downloads.append(name)
					content = {"maps": {"light": {"normalizedName": "lighthouse", "name": "map-name", "extracts": []}}}
				else:
					self.assertEqual(name, "maps_zh")
					content = {"map-name": f"地图{revision}"}
				reply._content = json.dumps({"data": content}).encode()
				return reply

			with patch.object(manager, "_request", side_effect=request):
				self.assertTrue(manager.sync_map_layers("pve")["ok"])
				self.assertEqual([row["name"] for row in maps.maps()], ["地图1"])
				revision = 2
				self.assertTrue(manager.sync_map_layers("pve")["ok"])
				self.assertEqual([row["name"] for row in maps.maps()], ["地图2"])
				self.assertTrue(manager.sync_map_layers("pve")["ok"])
				self.assertEqual(map_downloads, ["maps"])

	def test_local_catalog_reuses_raw_maps_and_updates_translations_without_a_download(self) -> None:
		from app.maps import has_catalog_source, write_catalog

		with TemporaryDirectory() as temp:
			folder = Path(temp) / "regular"
			folder.mkdir()
			raw = {"data": {"maps": {"a": {
				"normalizedName": "factory", "name": "map-key", "extracts": [{"name": "exit-key"}],
				"locks": [{"key": "key-id"}], "spawns": [{"position": {"x": 1234567, "z": 98765}}],
			}}}}
			with patch("requests.sessions.Session.get", side_effect=AssertionError("unexpected download")):
				self.assertFalse(has_catalog_source(folder))
				write_catalog(folder, json.dumps(raw).encode())
				self.assertTrue(has_catalog_source(folder))
				(folder / "maps_zh.json").write_text(json.dumps({"data": {"map-key": "工厂", "exit-key": "三号门"}}), encoding="utf-8")
				(folder / "items_zh.json").write_text(json.dumps({"data": {"key-id Name": "工厂钥匙"}}), encoding="utf-8")
				result = write_catalog(folder)
				self.assertTrue(result["ok"])
				store = MapStore(DataStore(Path(temp), "regular"))
				entry = store.maps()[0]
				self.assertEqual(entry["exits"][0]["name"], "三号门")
				self.assertEqual(entry["keys"][0]["name"], "工厂钥匙")
				self.assertFalse(any(b"1234567" in f.read_bytes() for f in Path(temp).rglob("*.json")))
				with self.assertRaises(ValueError):
					write_catalog(folder, {"data": {"maps": {"a": {"name": "x", "normalizedName": "factory"}}}})
				self.assertEqual(store.maps()[0]["name"], "工厂")

	def test_map_details_images_and_cache_are_localized_and_scoped_to_mode(self) -> None:
		with TemporaryDirectory() as folder:
			store = DataStore(Path(folder))
			store.items = {"key": {"name": "仓库钥匙"}}
			maps = MapStore(store)
			source = {"data": {"maps": {
				"light": {
					"normalizedName": "lighthouse", "name": "map-name", "players": "10-12", "raidDuration": 40,
					"extracts": [{"name": "extract-name", "faction": "pmc"}],
					"locks": [{"key": "key"}, {"key": "key"}],
					"bosses": [{"mob": "boss", "spawnChance": 0.35, "spawnLocations": [{"name": "Zone"}]}],
					"transits": [{"description": "transit-name", "map": "light"}], "hazards": [],
				},
			}, "mobs": {"boss": {"name": "boss-name"}}}}
			locales = {"data": {"map-name": "灯塔", "boss-name": "游荡者", "extract-name": "南方公路", "transit-name": "转移"}}
			def fetch(url):
				return locales if url.endswith("_zh") else source
			with patch.object(maps, "_fetch", side_effect=fetch):
				self.assertTrue(maps.sync()["ok"])
			entry = maps.maps()[0]
			self.assertEqual((entry["name"], entry["exits"][0]["name"]), ("灯塔", "南方公路"))
			self.assertEqual((entry["bosses"][0]["name"], entry["bosses"][0]["chance"]), ("游荡者", 35))
			self.assertEqual((entry["keys"][0]["name"], entry["keys"][0]["lockCount"]), ("仓库钥匙", 2))
			image = entry["images"][0]
			self.assertEqual(image["originalUrl"], "https://tarkov.dev/maps/lighthouse-2d.jpg")
			self.assertEqual(image["previewUrl"], "https://tarkov.dev/maps/lighthouse-2d_thumb.jpg")
			self.assertIsNone(maps.fetch_image("https://example.com/map.jpg"))
			store.mode = "regular"
			self.assertEqual(maps.maps(), [])
