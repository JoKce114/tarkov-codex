import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from requests import Response

from app.sync import SyncManager, seed_if_missing


class MapLayerTests(unittest.TestCase):
	def setUp(self):
		self.temp = tempfile.TemporaryDirectory()
		self.addCleanup(self.temp.cleanup)
		self.data = Path(self.temp.name) / "data"
		self.folder = self.data / "pve"
		self.folder.mkdir(parents=True)
		point = {"x": 0, "y": 30, "z": -11.5}
		self.full = {"data": {
			"maps": {"map-id": {
				"name": "Map Name", "normalizedName": "lighthouse", "players": "10-12", "raidDuration": 40,
				"extracts": [{"position": point, "name": "Exit Name", "faction": "shared"}],
				"spawns": [
					{"position": point, "categories": ["player"], "sides": ["all"]},
					{"position": point, "categories": ["bot"], "sides": ["scav"]},
					{"position": point, "categories": ["boss"], "sides": ["scav"], "zoneName": "zone"},
				],
				"bosses": [{"mob": "exUsecFree", "spawnLocations": [{"spawnKey": "zone"}]}],
				"lootContainers": [{"position": point, "lootContainer": "bag"}],
				"lootLoose": [{"position": point, "items": ["item1", "item2", "item1"]}],
				"switches": [{"position": point, "name": "Switch Name"}],
				"locks": [{"position": point, "lockType": "door", "key": "key-id"}],
				"hazards": [{"position": {"x": None, "z": 50}, "hazardType": "sniper"}],
				"btrStops": [{"name": "BTR Stop", **point}],
			}},
			"lootContainers": {"bag": {"name": "Bag Name", "normalizedName": "duffle-bag"}},
			"mobs": {"exUsecFree": {"name": "exUsecFree", "normalizedName": "rogue"}},
		}}
		self.slim = {"data": {"maps": {"map-id": {"name": "Map Name", "normalizedName": "lighthouse"}}}}
		self.table = {"data": {"Bag Name": "旅行包", "Exit Name": "装甲列车"}}
		(self.folder / "maps_zh.json").write_text(json.dumps(self.table))

	def test_offline_full_source_produces_per_map_points_and_translates_current_names(self):
		from app.map_layers import read_map_layers

		(self.folder / "maps.json").write_text(json.dumps(self.full))
		result = read_map_layers(self.data, "pve", "map-id")
		self.assertEqual((result["players"], result["raidDuration"]), ("10-12", 40))
		points = result["points"]
		self.assertEqual({(p["x"], p["z"]) for p in points}, {(0, -11.5)})
		self.assertSetEqual({p["type"] for p in points if p["group"] == "spawns"}, {"PMC", "Scav", "游荡者"})
		self.assertIn(("extracts", "共享", "装甲列车"), [(p["group"], p["type"], p["label"]) for p in points])
		self.assertEqual([p["itemIds"] for p in points if p["group"] == "loot"], [["item1", "item2"]])
		self.assertEqual([p["keyId"] for p in points if p["type"] == "锁"], ["key-id"])
		self.assertEqual([p["type"] for p in points if p["group"] == "containers"], ["旅行包"])
		self.assertTrue(any(p["group"] == "transport" for p in points))
		self.assertFalse(any(p["group"] == "hazards" for p in points))
		(self.folder / "maps.json").write_text(json.dumps(self.slim))
		(self.folder / "maps_zh.json").write_text(json.dumps({"data": {"Bag Name": "新名称"}}))
		again = read_map_layers(self.data, "pve", "map-id")
		self.assertIn("新名称", [p["type"] for p in again["points"]])
		self.assertIsNone(read_map_layers(self.data, "regular", "map-id"))

	def test_sync_recovers_old_slim_maps_with_same_etag(self):
		(self.folder / "maps.json").write_text(json.dumps(self.slim))
		(self.data / "sync_meta.json").write_text(json.dumps({"pve": {"maps": {"etag": "same"}}}))
		manager = SyncManager(self.data)

		def request(url, etag):
			response = Response()
			response.status_code = 304 if etag == "same" else 200
			response.headers["ETag"] = "same"
			response._content = json.dumps(self.full).encode()
			return response

		with patch.object(manager, "_request", side_effect=request):
			first = manager._sync_one("pve", "maps", "maps", False)
			self.assertTrue(first["changed"])
			from app.map_layers import read_map_layers

			self.assertTrue(read_map_layers(self.data, "pve", "map-id")["points"])
			self.assertEqual(json.loads((self.folder / "maps.json").read_bytes()), self.slim)
			self.assertFalse(manager._sync_one("pve", "maps", "maps", False)["changed"])

	def test_full_seed_can_supply_layers_to_existing_slim_installation(self):
		from app.map_layers import read_map_layers

		(self.folder / "maps.json").write_text(json.dumps(self.slim))
		seed = Path(self.temp.name) / "seed"
		(seed / "pve").mkdir(parents=True)
		(seed / "pve" / "maps.json").write_text(json.dumps(self.full))
		seed_if_missing(self.data, seed)
		self.assertEqual(json.loads((self.folder / "maps.json").read_bytes()), self.slim)
		self.assertTrue(read_map_layers(self.data, "pve", "map-id")["points"])

	def test_map_only_sync_loads_chinese_for_selected_mode_and_recovers_after_failure(self):
		from app.map_layers import read_map_layers

		manager = SyncManager(self.data)
		should_fail = True

		def request(url, etag):
			response = Response()
			if url.endswith("/regular/maps"):
				response._content = json.dumps(self.full).encode()
			elif url.endswith("/regular/maps_zh"):
				if should_fail:
					raise RuntimeError("网络断开")
				response._content = json.dumps(self.table).encode()
			else:
				self.fail(f"地图同步请求了无关数据 {url}")
			response.status_code = 200
			response.headers["ETag"] = "map-revision"
			return response

		with patch.object(manager, "_request", side_effect=request):
			self.assertFalse(manager.sync_map_layers("regular")["ok"])
			should_fail = False
			self.assertTrue(manager.sync_map_layers("regular")["ok"])
		meta = json.loads((self.data / "sync_meta.json").read_bytes())
		self.assertEqual(set(meta["regular"]), {"maps", "maps_zh"})
		result = read_map_layers(self.data, "regular", "map-id")
		self.assertIn("装甲列车", [point["label"] for point in result["points"]])
		self.assertIsNone(read_map_layers(self.data, "pve", "map-id"))

	def test_missing_extract_faction_is_shared_and_container_variants_share_a_filter(self):
		from app.map_layers import read_map_layers

		entry = self.full["data"]["maps"]["map-id"]
		del entry["extracts"][0]["faction"]
		self.full["data"]["lootContainers"]["bag-variant"] = {"name": "Variant Name", "normalizedName": "duffle-bag"}
		entry["lootContainers"].append({"position": {"x": 0, "z": 3}, "lootContainer": "bag-variant"})
		self.table["data"]["Variant Name"] = "旅行 包"
		(self.folder / "maps.json").write_text(json.dumps(self.full))
		(self.folder / "maps_zh.json").write_text(json.dumps(self.table))
		result = read_map_layers(self.data, "pve", "map-id")
		self.assertEqual([p["type"] for p in result["points"] if p["group"] == "extracts"], ["共享"])
		self.assertEqual([p["type"] for p in result["points"] if p["group"] == "containers"], ["旅行包", "旅行包"])

	def test_invalid_sync_payload_preserves_last_working_cache(self):
		from app.map_layers import read_map_layers

		(self.folder / "maps.json").write_text(json.dumps(self.full))
		original = read_map_layers(self.data, "pve", "map-id")
		manager = SyncManager(self.data)
		for invalid_map, invalid_table in (([], False), (self.full, True)):
			with self.subTest(invalid_table=invalid_table):
				def request(url, etag):
					reply = Response()
					reply.status_code = 200
					reply._content = b"<html>" if url.endswith("maps_zh") else json.dumps(invalid_map).encode()
					return reply

				with patch.object(manager, "_request", side_effect=request):
					self.assertFalse(manager.sync_map_layers("pve")["ok"])
				self.assertEqual(read_map_layers(self.data, "pve", "map-id"), original)

	def test_floor_elevation_is_preserved_when_finite_and_optional_otherwise(self):
		from app.map_layers import read_map_layers

		entry = self.full["data"]["maps"]["map-id"]
		entry["lootLoose"] = [
			{"position": {"x": 0, "z": 2, "y": height}, "items": []}
			for height in (-6.75, 0, 12.5, None, float("nan"), float("inf"), True)
		]
		(self.folder / "maps.json").write_text(json.dumps(self.full))
		points = read_map_layers(self.data, "pve", "map-id")["points"]
		self.assertEqual([p.get("height") for p in points if p["group"] == "loot"], [-6.75, 0, 12.5, None, None, None, None])
		self.assertEqual({p.get("height") for p in points if p["group"] != "loot"}, {30})

	def test_offline_previous_cache_remains_readable_until_height_data_is_available(self):
		from app.map_layers import read_map_layers

		entry = {"points": [{"group": "spawns", "type": "PMC", "label": "PMC", "x": 0, "z": 2}]}
		with ZipFile(self.folder / "map_layers_v1.zip", "w") as archive:
			archive.writestr("map-id", json.dumps(entry))
		(self.folder / "maps.json").write_text(json.dumps(self.slim))
		self.assertEqual(read_map_layers(self.data, "pve", "map-id"), entry)
		(self.folder / "maps.json").write_text(json.dumps(self.full))
		current = read_map_layers(self.data, "pve", "map-id")
		self.assertTrue(all(p["height"] == 30 for p in current["points"]))
