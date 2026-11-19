import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.map_layers import write_map_layers, read_map_layers
from app.store import DataStore


class BossTests(unittest.TestCase):
	def test_mode_specific_gear_loot_and_linked_spawns(self):
		from app.bosses import boss_router

		with TemporaryDirectory() as dirname:
			root = Path(dirname)
			store = DataStore(root)
			store.items = {"gun": {"name": "测试装备"}, "pass": {"name": "门卡"}}
			point = {"x": 1, "y": 2, "z": 3}
			source = {"data": {
				"maps": {"map": {"normalizedName": "factory", "name": "Factory", "spawns": [
					{"position": point, "categories": ["boss"], "sides": ["scav"], "zoneName": "Office"}],
					"bosses": [{"mob": "bossTagilla", "spawnChance": 0.25,
						"spawnLocations": [{"name": "Office", "spawnKey": "Office"}, {"name": "Office", "spawnKey": "Office"}],
						"escorts": [{"mob": "guard"}, {"mob": "guard"}]}]}},
				"mobs": {"bossTagilla": {
					"name": "bossTagilla", "normalizedName": "tagilla", "equipment": [{"item": "gun", "contains": []}],
					"items": [{"id": "pass", "attributes": {"prevalence": 33}}], "health": [{"id": "Head", "max": 110}],
				}, "guard": {"name": "Guard Name", "normalizedName": "guard"}},
			}}
			write_map_layers(root / "pve", source)
			(root / "pve/maps_zh.json").write_text(json.dumps({"data": {
				"bossTagilla": "塔吉拉", "Factory": "工厂", "Office": "办公室", "Guard Name": "守卫",
			}}))
			app = FastAPI()
			app.include_router(boss_router(store))
			client = TestClient(app)
			boss = client.get("/api/bosses/bossTagilla").json()
			self.assertEqual((boss["name"], boss["equipment"][0]["name"], boss["loot"][0]["id"]), ("塔吉拉", "测试装备", "pass"))
			self.assertEqual(boss["maps"][0]["chances"], [0.25])
			self.assertEqual(boss["maps"][0]["pointCount"], 1)
			self.assertEqual(boss["maps"][0]["zones"], ["办公室"])
			self.assertEqual(boss["maps"][0]["escorts"], ["守卫"])
			points = read_map_layers(root, "pve", "map")["points"]
			self.assertEqual((points[0]["icon"], points[0]["bossIds"]), ("spawn_boss", ["bossTagilla", "guard"]))
			self.assertEqual(client.get("/api/bosses").json()["bosses"][0]["id"], "bossTagilla")
			store.mode = "regular"
			self.assertFalse(client.get("/api/bosses").json()["available"])
			self.assertEqual(client.get("/api/bosses/bossTagilla").status_code, 404)
