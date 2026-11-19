from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from xml.etree import ElementTree
from unittest.mock import patch

from fastapi.testclient import TestClient
import requests

from app import paths
from app.api import create_app
from app.progress import ProgressStore
from app.store import DataStore


class AtlasTests(unittest.TestCase):
	def setUp(self) -> None:
		temp = TemporaryDirectory()
		self.addCleanup(temp.cleanup)
		base = Path(temp.name)
		self.store = DataStore(base)
		self.progress = ProgressStore(base / "progress.json")
		self.store.maps = {
			"light": {"name": "灯塔", "normalizedName": "lighthouse"},
			"factory": {"name": "工厂", "normalizedName": "factory"},
			"night": {"name": "夜间工厂", "normalizedName": "night-factory"},
			"lab": {"name": "实验室", "normalizedName": "the-lab"},
			"tutorial": {"name": "零号区教学", "normalizedName": "ground-zero-tutorial"},
		}
		cache = patch.object(paths, "CACHE_DIR", base)
		cache.start()
		self.addCleanup(cache.stop)
		(base / "map-lighthouse.svg").write_text('<svg viewBox="-20 35 1060 1723"/>', encoding="utf-8")
		(base / "map-factory.svg").write_text(
			'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 131 141"><g id="Basement"/>'
			'<g id="Ground_Floor"/><g id="Second_Floor"/><g id="Third_Floor"/></svg>', encoding="utf-8",
		)
		(base / "map-reserve.svg").write_text('<svg viewBox="0 0 592 546"/>', encoding="utf-8")
		(base / "map-ground-zero.svg").write_text('<svg viewBox="0 0 348 488"/>', encoding="utf-8")
		self.client = TestClient(create_app(self.store, None, self.progress, None, None, None))

	def test_catalog_includes_current_mode_variants_and_offline_base_maps(self) -> None:
		response = self.client.get("/api/atlas")
		self.assertEqual(response.status_code, 200)
		maps = {entry["key"]: entry["name"] for entry in response.json()["maps"]}
		self.assertEqual(maps["night-factory"], "夜间工厂")
		self.assertEqual(maps["ground-zero-tutorial"], "零号区教学")
		self.assertEqual(maps["lighthouse"], "灯塔")
		self.store.maps.clear()
		self.assertIn("lighthouse", {entry["key"] for entry in self.client.get("/api/atlas").json()["maps"]})

	def test_task_and_atlas_share_stable_zone_and_item_location_indices(self) -> None:
		task = {
			"id": "quest", "name": "测试任务", "minPlayerLevel": 3,
			"objectives": [
				{"description": "交付", "type": "giveItem"},
				{
					"description": "寻找", "optional": True, "type": "findQuestItem",
					"zones": [
						{"map": "light", "position": {"x": 30000, "z": 20000}},
						{"map": "light", "position": {"x": 415, "z": -898}, "size": {"x": 4}},
					],
					"possibleLocations": [{"map": "light", "positions": [{"x": 15, "z": -98}]}],
				},
			],
		}
		self.store.tasks = {"quest": task}
		result = self.client.get("/api/tasks/quest/map").json()["maps"][0]
		self.assertEqual((result.get("originX"), result.get("originY")), (-20, 35))
		points = result["points"]
		self.assertEqual([(p["x"], p["y"]) for p in points], [(100, 100), (500, 900)])
		self.assertEqual([(p["objectiveIndex"], p["pointIndex"]) for p in points], [(1, 1), (1, 2)])
		self.assertEqual(points[0]["radiusX"], 2)
		self.assertTrue(points[0]["optional"])
		# Loading Lighthouse must not fetch an SVG for an unrelated task or map.
		self.store.tasks["other"] = {"id": "other", "objectives": [
			{"zones": [{"map": "factory", "position": {"x": 1, "z": 2}}]},
		]}
		with patch("requests.sessions.Session.get", side_effect=AssertionError("unexpected network")):
			for level, completed, status in [(1, False, "未解锁"), (3, False, "可接"), (3, True, "已完成")]:
				self.progress.set_level("pve", level)
				self.progress.set_task("pve", "quest", completed)
				result = self.client.get("/api/atlas/lighthouse").json()
				markers = [p for p in result["points"] if p["group"] == "tasks"]
				self.assertEqual([p["taskKind"] for p in markers], ["目标", "物品"])
				self.assertEqual([p["type"] for p in markers], [status, status])
				self.assertEqual([(p["objectiveIndex"], p["pointIndex"]) for p in markers], [(1, 1), (1, 2)])
				self.assertEqual(markers[1]["taskId"], "quest")
				self.assertEqual(markers[1]["taskName"], "测试任务")
				self.assertFalse(result["hasLayers"])

	def test_loot_and_keys_use_localized_item_metadata_and_project_like_landmarks(self) -> None:
		self.store.items = {"key": {"name": "房间钥匙", "categories": ["mechanical", "general"]}}
		self.store.categories = {"mechanical": {"name": "机械钥匙"}, "general": {"name": "物品"}}
		layers = {
			"players": "10-12", "raidDuration": 40,
			"points": [
				{"group": "loot", "type": "散落物资", "label": "散落物资", "x": -30, "z": -882, "itemIds": ["key"]},
				{"group": "interactives", "type": "锁", "label": "门", "x": 415, "z": -898, "keyId": "key"},
			],
		}
		with patch("app.atlas.read_map_layers", return_value=layers):
			result = self.client.get("/api/atlas/lighthouse").json()
		self.assertTrue(result["hasLayers"])
		self.assertEqual(result["itemNames"], {"key": "房间钥匙"})
		self.assertEqual(result["itemCategories"], {"key": "机械钥匙"})
		self.assertEqual((result["players"], result["raidDuration"]), ("10-12", 40))
		landmark = next(p for p in result["points"] if p["group"] == "landmarks" and p["label"] == "Train Yard")
		loot = next(p for p in result["points"] if p["group"] == "loot")
		self.assertEqual((loot["x"], loot["y"]), (landmark["x"], landmark["y"]))
		lock = next(p for p in result["points"] if p["type"] == "锁")
		self.assertIn("key", lock["itemIds"])

	def test_tile_map_uses_leaflet_pixel_projection_and_bounds_its_tile_requests(self) -> None:
		self.store.tasks = {"quest": {"id": "quest", "objectives": [
			{"description": "一层", "zones": [{"map": "lab", "position": {"x": -80, "z": -477}}]},
		]}}
		response = self.client.get("/api/atlas/the-lab")
		self.assertEqual(response.status_code, 200)
		result = response.json()
		self.assertFalse(result["hasSvg"])
		self.assertTrue(result["tiles"])
		marker = next(p for p in result["points"] if p["group"] == "tasks")
		self.assertAlmostEqual(marker["x"], 0, places=1)
		self.assertAlmostEqual(marker["y"], result["height"], places=1)
		real = result["tiles"][0]
		self.assertRegex(real["url"], r"^/api/atlas/tile/the-lab/3/-?\d+/-?\d+$")
		self.assertEqual(self.client.get("/api/atlas/tile/the-lab/3/99999/-99999").status_code, 404)
		self.assertEqual(self.client.get("/api/atlas/tile/lighthouse/3/1/2").status_code, 404)

	def test_missing_svg_is_reported_and_unknown_map_uses_404(self) -> None:
		with patch("app.assets.SvgCache.get", return_value=None):
			response = self.client.get("/api/atlas/lighthouse")
		self.assertEqual(response.status_code, 503)
		self.assertTrue(response.json()["error"])
		self.assertEqual(self.client.get("/api/atlas/unknown").status_code, 404)

	def test_tile_download_requests_png_and_reuses_the_local_copy(self) -> None:
		def serve_asset(url: str, *, headers: dict, **options) -> requests.Response:
			response = requests.Response()
			response.status_code = 200
			response._content = b"\x89PNG\r\n\x1a\nfixture" if headers["Accept"] == "image/png" else b"RIFF....WEBP"
			response._content_consumed = True
			return response

		url = "/api/atlas/tile/the-lab/3/4/4"
		with patch("requests.get", side_effect=serve_asset):
			first = self.client.get(url)
		self.assertEqual(first.status_code, 200)
		self.assertEqual(first.headers["content-type"], "image/png")
		with patch("requests.get", side_effect=AssertionError("cached tile fetched again")):
			self.assertEqual(self.client.get(url).content, first.content)

	def test_svg_floor_renders_selected_overlay_and_matches_marker_elevations(self) -> None:
		self.store.tasks = {"q": {"id": "q", "objectives": [{
			"zones": [{"map": "night", "position": {"x": 1, "y": -2, "z": 0}}],
		}]}}
		layers = {"points": [
			{"x": 0, "z": 0, "height": height, "group": "loot", "type": "散落物资", "label": str(height)}
			for height in (-2, 0, 3, 7, None)
		]}
		with patch("app.atlas.read_map_layers", return_value=layers):
			data = self.client.get("/api/atlas/night-factory").json()
		points = [point for point in data["points"] if point["group"] == "loot"]
		self.assertEqual([p["floorKeys"] for p in points], [["floor-2"], ["base"], ["floor-0"], ["floor-1"], []])
		self.assertEqual(next(p for p in data["points"] if p["group"] == "tasks")["floorKeys"], ["floor-2"])
		floor = next(f for f in data["floors"] if f["key"] == "floor-2")
		response = self.client.get(floor["svgUrl"])
		self.assertEqual(response.status_code, 200)
		root = ElementTree.fromstring(response.content)
		groups = [g.get("id") for g in root if g.tag.endswith("}g")]
		self.assertEqual(groups, ["Ground_Floor", "Basement"])

	def test_lab_floors_match_horizontal_extents_and_provide_distinct_tiles(self) -> None:
		layers = {"points": [
			{"x": x, "z": -300, "height": 4, "group": "loot", "type": "散落物资", "label": str(x)}
			for x in (-200, -90)
		]}
		with patch("app.atlas.read_map_layers", return_value=layers):
			data = self.client.get("/api/atlas/the-lab").json()
		points = [point for point in data["points"] if point["group"] == "loot"]
		self.assertEqual([p["floorKeys"] for p in points], [["floor-0"], ["base"]])
		floor = next(f for f in data["floors"] if f["key"] == "floor-0")
		self.assertNotEqual(floor["tiles"][0]["url"], data["tiles"][0]["url"])
		self.assertEqual(floor["tiles"][0]["x"], data["tiles"][0]["x"])

	def test_shared_task_minimap_links_to_the_exact_variant_and_stable_position(self) -> None:
		self.store.tasks = {"q": {"id": "q", "name": "工厂任务", "objectives": [{
			"zones": [
				{"map": "night", "position": {"x": 1, "z": 0}},
				{"map": "factory", "position": {"x": 2, "z": 3}},
			],
		}]}}
		groups = self.client.get("/api/tasks/q/map").json()["maps"]
		self.assertEqual([group["mapKey"] for group in groups], ["factory"])
		points = groups[0]["points"]
		self.assertEqual([(p.get("mapKey"), p.get("mapName")) for p in points], [
			("night-factory", "夜间工厂"), ("factory", "工厂"),
		])
		for source in points:
			result = self.client.get("/api/atlas/" + source["mapKey"]).json()
			targets = [p for p in result["points"] if p["group"] == "tasks"]
			self.assertEqual([(p["pointIndex"], p["x"]) for p in targets], [(source["pointIndex"], source["x"])])

	def test_reserve_markers_and_overlay_tiles_use_svg_bounds_while_minimap_preserves_legacy_projection(self) -> None:
		self.store.maps["reserve"] = {"normalizedName": "reserve", "name": "储备站"}
		self.store.tasks = {"q": {"id": "q", "objectives": [{
			"zones": [{"map": "reserve", "position": {"x": 0, "z": 0}}],
		}]}}
		old = self.client.get("/api/tasks/q/map").json()["maps"][0]["points"][0]
		self.assertEqual((old["x"], old["y"]), (289, 297.9))
		data = self.client.get("/api/atlas/reserve").json()
		point = next(p for p in data["points"] if p["group"] == "tasks")
		self.assertEqual((point["x"], point["y"]), (289, 274))
		self.assertEqual((point["mapKey"], point["objectiveIndex"], point["pointIndex"]), ("reserve", 0, 0))
		tile = next(t for f in data["floors"] if f["key"] == "floor-0" for t in f["tiles"] if "/3/4/4?" in t["url"])
		self.assertAlmostEqual(tile["y"], 249.56962, places=4)

	def test_landmarks_match_ranges_ground_floor_and_point_elevations(self) -> None:
		factory = self.client.get("/api/atlas/factory").json()["points"]
		keys = {p["label"]: p["floorKeys"] for p in factory if p["group"] == "landmarks"}
		self.assertEqual(keys["Main Office"], ["floor-1"])
		self.assertEqual(keys["Locker Rooms"], ["floor-0"])
		self.assertEqual(set(keys["Office Building"]), {"base", "floor-0", "floor-1"})
		zero = self.client.get("/api/atlas/ground-zero").json()["points"]
		keys = {p["label"]: p["floorKeys"] for p in zero if p["group"] == "landmarks"}
		self.assertEqual(keys["Science Office"], ["floor-0"])
		self.assertEqual(keys["ASAP Winery"], ["base"])
