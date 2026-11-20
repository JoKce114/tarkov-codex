from __future__ import annotations

import json
import threading
from pathlib import Path

from .datasets import DATASET_KEYS, DEFAULT_MODE, file_name, translation_file_name
from .translations import apply_translations


def read_json(path: Path):
	if not path.exists():
		return None
	with path.open("r", encoding="utf-8") as handle:
		return json.load(handle)


class DataStore:
	def __init__(self, data_dir: Path, mode: str = DEFAULT_MODE) -> None:
		self.data_dir = data_dir
		self.mode = mode
		self._lock = threading.RLock()
		self.payloads: dict[str, dict] = {}
		self.items: dict[str, dict] = {}
		self.tasks: dict[str, dict] = {}
		self.maps: dict[str, dict] = {}
		self.traders: dict[str, dict] = {}
		self.hideout: dict[str, dict] = {}
		self.barters: list[dict] = []
		self.crafts: list[dict] = []
		self.loaded_at = ""
		self.categories: dict[str, dict] = {}
		self.handbook: dict[str, dict] = {}
		self._barters_by_output: dict[str, list] = {}
		self._barters_by_input: dict[str, list] = {}
		self._crafts_by_output: dict[str, list] = {}
		self._crafts_by_input: dict[str, list] = {}
		self._tasks_by_item: dict[str, list] = {}

	def set_mode(self, mode: str) -> dict:
		with self._lock:
			self.mode = mode
			return self.load()

	def mode_dir(self) -> Path:
		return self.data_dir / self.mode

	def load(self) -> dict:
		with self._lock:
			self.payloads = {}
			base = self.mode_dir()
			for key in DATASET_KEYS:
				payload = read_json(base / file_name(key))
				if payload is None:
					continue
				table = read_json(base / translation_file_name(key)) or {}
				apply_translations(payload, table.get("data") or {})
				self.payloads[key] = payload
			self._build_indexes()
			from .sync import now_text

			self.loaded_at = now_text()
			return self.stats()

	def _build_indexes(self) -> None:
		items = self.payloads.get("items", {}).get("data", {}).get("items") or {}
		self.items = items if isinstance(items, dict) else {}
		self._slim_items()

		tasks = self.payloads.get("tasks", {}).get("data", {}).get("tasks") or {}
		self.tasks = tasks if isinstance(tasks, dict) else {}

		# tarkov.dev 的地图数据里 mobs / lootContainers / spawns 等占 45MB 且界面用不到，
		# 只保留任务要用到的「地图名 + 规范化名」，加载后立即丢弃其余部分。
		map_data = self.payloads.get("maps", {}).get("data") or {}
		raw_maps = map_data.get("maps") or {}
		self.maps = (
			{
				map_id: {
					"name": entry.get("name") or "",
					"normalizedName": entry.get("normalizedName") or "",
				}
				for map_id, entry in raw_maps.items()
			}
			if isinstance(raw_maps, dict)
			else {}
		)
		if "maps" in self.payloads:
			self.payloads["maps"]["data"] = {"maps": self.maps}

		traders = self.payloads.get("traders", {}).get("data") or {}
		self.traders = traders if isinstance(traders, dict) else {}

		hideout = self.payloads.get("hideout", {}).get("data") or {}
		self.hideout = hideout if isinstance(hideout, dict) else {}

		barters = self.payloads.get("barters", {}).get("data") or []
		self.barters = barters if isinstance(barters, list) else []

		crafts = self.payloads.get("crafts", {}).get("data") or []
		self.crafts = crafts if isinstance(crafts, list) else []

		item_data = self.payloads.get("items", {}).get("data") or {}
		categories = item_data.get("itemCategories") or {}
		self.categories = categories if isinstance(categories, dict) else {}

		# 物品数据里另外几份大表界面没用过，加载后直接丢掉
		if "items" in self.payloads:
			self.payloads["items"]["data"] = {
				"items": self.items,
				"itemCategories": self.categories,
			}

		achievements = self.payloads.get("tasks", {}).get("data", {}).get("achievements") or {}
		self.achievements = achievements if isinstance(achievements, dict) else {}
		if "tasks" in self.payloads:
			self.payloads["tasks"]["data"] = {
				"tasks": self.tasks,
				"achievements": self.achievements,
			}

		self._build_relations()

	ITEM_FIELDS = (
		"id",
		"name",
		"shortName",
		"normalizedName",
		"description",
		"iconLink",
		"gridImageLink",
		"image512pxLink",
		"wikiLink",
		"width",
		"height",
		"weight",
		"basePrice",
		"stackMaxSize",
		"avg24hPrice",
		"lastLowPrice",
		"low24hPrice",
		"high24hPrice",
		"lastOfferCount",
		"categories",
	)

	def _slim_items(self) -> None:
		"""兜底：老数据（字段完整）在此精简；已精简过的数据原样保留。"""
		if not self.items:
			return
		fields = self.ITEM_FIELDS
		for item in self.items.values():
			for key in [key for key in item if key not in fields and key not in ("sellToTrader", "buyFromTrader")]:
				del item[key]
			sell = item.get("sellToTrader") or []
			if sell and isinstance(sell[0], dict):
				item["sellToTrader"] = [
					(entry.get("trader"), entry.get("priceRUB") or entry.get("price"))
					for entry in sell
					if isinstance(entry, dict)
				]
			buy = item.get("buyFromTrader") or []
			if buy and isinstance(buy[0], dict):
				item["buyFromTrader"] = [
					(
						entry.get("trader"),
						entry.get("priceRUB") or entry.get("price"),
						entry.get("minTraderLevel"),
						entry.get("buyLimit"),
						entry.get("restockAmount"),
					)
					for entry in buy
					if isinstance(entry, dict)
				]

	def _build_relations(self) -> None:
		self._barters_by_output = {}
		self._barters_by_input = {}
		for barter in self.barters:
			output = (barter.get("offeredItem") or {}).get("item")
			if output:
				self._barters_by_output.setdefault(output, []).append(barter)
			for entry in barter.get("requiredItems") or []:
				item_id = entry.get("item")
				if item_id:
					self._barters_by_input.setdefault(item_id, []).append(barter)

		self._crafts_by_output = {}
		self._crafts_by_input = {}
		for craft in self.crafts:
			output = (craft.get("productItem") or {}).get("item")
			if output:
				self._crafts_by_output.setdefault(output, []).append(craft)
			for entry in craft.get("requiredItems") or []:
				item_id = entry.get("item")
				if item_id:
					self._crafts_by_input.setdefault(item_id, []).append(craft)

		self._tasks_by_item = {}
		self.achievements: dict[str, dict] = {}
		for task in self.tasks.values():
			for objective in task.get("objectives") or []:
				for item_id in objective.get("items") or []:
					bucket = self._tasks_by_item.setdefault(item_id, [])
					if not any(entry.get("id") == task.get("id") for entry in bucket):
						bucket.append(task)

	def stats(self) -> dict:
		with self._lock:
			return {
				"mode": self.mode,
				"loadedAt": self.loaded_at,
				"empty": not self.items,
				"datasets": {key: key in self.payloads for key in DATASET_KEYS},
				"counts": {
					"items": len(self.items),
					"tasks": len(self.tasks),
					"maps": sum(row.get("normalizedName") != "ground-zero-tutorial" for row in self.maps.values()),
					"traders": len(self.traders),
					"hideout": len(self.hideout),
					"barters": len(self.barters),
					"crafts": len(self.crafts),
				},
			}

	def item_summary(self, item: dict) -> dict:
		return {
			"id": item.get("id"),
			"name": item.get("name"),
			"shortName": item.get("shortName"),
			"normalizedName": item.get("normalizedName"),
			"iconLink": item.get("iconLink"),
			"types": item.get("types") or [],
			"width": item.get("width"),
			"height": item.get("height"),
			"basePrice": item.get("basePrice"),
			"avg24hPrice": item.get("avg24hPrice"),
			"lastLowPrice": item.get("lastLowPrice"),
			"low24hPrice": item.get("low24hPrice"),
			"high24hPrice": item.get("high24hPrice"),
			"lastOfferCount": item.get("lastOfferCount"),
			"sellToTrader": self._best_sell(item),
			"buyFromTrader": self._cheapest_buy(item),
		}

	def _trader_name(self, trader_id: str | None) -> str:
		trader = self.traders.get(trader_id or "")
		return (trader or {}).get("name") or ""

	def _best_sell(self, item: dict) -> dict | None:
		offers = item.get("sellToTrader") or []
		if not offers:
			return None
		trader_id, price = max(offers, key=lambda entry: entry[1] or 0)
		return {"trader": self._trader_name(trader_id), "price": price}

	def _cheapest_buy(self, item: dict) -> dict | None:
		offers = item.get("buyFromTrader") or []
		if not offers:
			return None
		trader_id, price, level, limit, _restock = min(offers, key=lambda entry: entry[1] or 0)
		return {
			"trader": self._trader_name(trader_id),
			"price": price,
			"traderLevel": level,
			"buyLimit": limit,
		}

	def search_items(
		self,
		query: str = "",
		limit: int = 50,
		offset: int = 0,
		category: str = "",
		sort: str = "name",
	) -> dict:
		text = (query or "").strip().lower()
		with self._lock:
			source = list(self.items.values())
			if category:
				source = [item for item in source if category in (item.get("categories") or [])]
			if text:
				source = [
					item
					for item in source
					if text in (item.get("name") or "").lower()
					or text in (item.get("shortName") or "").lower()
					or text in (item.get("normalizedName") or "").lower()
				]
			source = self._sort_items(source, sort)
			total = len(source)
			page = source[offset : offset + limit]
			return {
				"total": total,
				"offset": offset,
				"limit": limit,
				"category": category,
				"sort": sort,
				"items": [self.item_summary(item) for item in page],
			}

	def _sort_items(self, items: list[dict], sort: str) -> list[dict]:
		if sort == "priceDesc":
			return sorted(items, key=lambda item: item.get("avg24hPrice") or 0, reverse=True)
		if sort == "priceAsc":
			return sorted(items, key=lambda item: item.get("avg24hPrice") or 0)
		if sort == "baseDesc":
			return sorted(items, key=lambda item: item.get("basePrice") or 0, reverse=True)
		return sorted(items, key=lambda item: (item.get("name") or "").lower())

	def category_tree(self) -> list[dict]:
		with self._lock:
			counts: dict[str, int] = {}
			for item in self.items.values():
				for category_id in item.get("categories") or []:
					counts[category_id] = counts.get(category_id, 0) + 1

			nodes: dict[str, dict] = {}
			for category_id, category in self.categories.items():
				nodes[category_id] = {
					"id": category_id,
					"name": category.get("name") or "",
					"normalizedName": category.get("normalizedName") or "",
					"count": counts.get(category_id, 0),
					"children": [],
				}

			roots: list[dict] = []
			for category_id, node in nodes.items():
				parent_id = self.categories[category_id].get("parent")
				if parent_id and parent_id in nodes:
					nodes[parent_id]["children"].append(node)
				else:
					roots.append(node)

			def prune(entries: list[dict]) -> list[dict]:
				kept = []
				for entry in entries:
					entry["children"] = prune(entry["children"])
					entry["children"].sort(key=lambda node: (-node["count"], node["name"]))
					if entry["count"] > 0 or entry["children"]:
						kept.append(entry)
				kept.sort(key=lambda node: (-node["count"], node["name"]))
				return kept

			return prune(roots)

	def item_detail(self, item_id: str) -> dict | None:
		with self._lock:
			item = self.items.get(item_id)
			if item is None:
				return None
			summary = self.item_summary(item)
			summary["description"] = item.get("description") or ""
			summary["weight"] = item.get("weight")
			summary["stackMaxSize"] = item.get("stackMaxSize")
			summary["iconLink"] = item.get("iconLink")
			summary["imageLink"] = item.get("image512pxLink") or item.get("gridImageLink")
			summary["wikiLink"] = item.get("wikiLink")
			summary["link"] = item.get("link")
			summary["sellOffers"] = self._sell_offers(item)
			summary["buyOffers"] = self._buy_offers(item)
			summary["barterFor"] = [self._barter_view(entry) for entry in self._barters_by_output.get(item_id, [])]
			summary["barterUsedIn"] = [self._barter_view(entry) for entry in self._barters_by_input.get(item_id, [])]
			summary["craftedBy"] = [self._craft_view(entry) for entry in self._crafts_by_output.get(item_id, [])]
			summary["usedInCrafts"] = [self._craft_view(entry) for entry in self._crafts_by_input.get(item_id, [])]
			summary["tasks"] = [self._task_view(entry) for entry in self._tasks_by_item.get(item_id, [])]
			summary["categoryNames"] = [
				(self.categories.get(category_id) or {}).get("name", "")
				for category_id in (item.get("categories") or [])
			]
			return summary

	def _sell_offers(self, item: dict) -> list[dict]:
		offers = [
			{"trader": self._trader_name(trader_id), "price": price}
			for trader_id, price in (item.get("sellToTrader") or [])
		]
		return sorted(offers, key=lambda entry: entry.get("price") or 0, reverse=True)

	def _buy_offers(self, item: dict) -> list[dict]:
		offers = []
		for trader_id, price, level, limit, restock in item.get("buyFromTrader") or []:
			offers.append(
				{
					"trader": self._trader_name(trader_id),
					"price": price,
					"traderLevel": level,
					"buyLimit": limit,
					"restockAmount": restock,
				}
			)
		return sorted(offers, key=lambda entry: entry.get("price") or 0)

	def _item_brief(self, item_id: str | None) -> dict:
		item = self.items.get(item_id or "") or {}
		return {
			"id": item_id,
			"name": item.get("name") or "",
			"shortName": item.get("shortName") or "",
			"iconLink": item.get("iconLink") or "",
		}

	def _barter_view(self, barter: dict) -> dict:
		return {
			"id": barter.get("id"),
			"trader": self._trader_name(barter.get("trader")),
			"traderLevel": barter.get("minTraderLevel"),
			"buyLimit": barter.get("buyLimit"),
			"required": [
				{**self._item_brief(entry.get("item")), "count": entry.get("count")}
				for entry in barter.get("requiredItems") or []
			],
			"offered": {
				**self._item_brief((barter.get("offeredItem") or {}).get("item")),
				"count": (barter.get("offeredItem") or {}).get("count"),
			},
		}

	def _craft_view(self, craft: dict) -> dict:
		station = self.hideout.get(craft.get("station") or "") or {}
		return {
			"id": craft.get("id"),
			"station": station.get("name") or "",
			"level": craft.get("level"),
			"duration": craft.get("duration"),
			"required": [
				{**self._item_brief(entry.get("item")), "count": entry.get("count")}
				for entry in craft.get("requiredItems") or []
			],
			"product": {
				**self._item_brief((craft.get("productItem") or {}).get("item")),
				"count": (craft.get("productItem") or {}).get("count"),
			},
		}

	def _task_view(self, task: dict) -> dict:
		trader = self.traders.get(task.get("trader") or "") or {}
		map_entry = self.maps.get(task.get("map") or "") or {}
		return {
			"id": task.get("id"),
			"name": task.get("name"),
			"trader": trader.get("name") or "",
			"traderImage": trader.get("imageLink") or "",
			"minPlayerLevel": task.get("minPlayerLevel"),
			"kappaRequired": task.get("kappaRequired"),
			"map": map_entry.get("name") or "",
			"experience": task.get("experience"),
		}

	# ---------- 商人 ----------

	TRADER_SORT = (
		"prapor",
		"therapist",
		"fence",
		"skier",
		"peacekeeper",
		"mechanic",
		"ragman",
		"jaeger",
		"lightkeeper",
		"ref",
		"btr-driver",
		"taran",
		"radio-station",
		"mr-kerman",
		"voevoda",
		"survivor",
	)

	def trader_view(self, trader_id: str | None) -> dict:
		trader = self.traders.get(trader_id or "") or {}
		return {
			"id": trader_id or "",
			"name": trader.get("name") or "",
			"normalizedName": trader.get("normalizedName") or "",
			"imageLink": trader.get("imageLink") or "",
		}

	def trader_list(self, completed: set[str], player_level: int) -> list[dict]:
		with self._lock:
			stats: dict[str, dict] = {}
			for task in self.tasks.values():
				trader_id = task.get("trader") or ""
				bucket = stats.setdefault(trader_id, {"total": 0, "available": 0, "done": 0})
				bucket["total"] += 1
				if task.get("id") in completed:
					bucket["done"] += 1
				elif self.is_unlocked(task, completed, player_level):
					bucket["available"] += 1

			entries = []
			for trader_id, bucket in stats.items():
				view = self.trader_view(trader_id)
				view.update(bucket)
				entries.append(view)

			def sort_key(entry: dict) -> tuple:
				name = entry.get("normalizedName") or ""
				order = self.TRADER_SORT.index(name) if name in self.TRADER_SORT else len(self.TRADER_SORT)
				return (order, entry.get("name") or "")

			entries.sort(key=sort_key)
			return entries

	# ---------- 任务 ----------

	def is_unlocked(self, task: dict, completed: set[str], player_level: int) -> bool:
		if (task.get("minPlayerLevel") or 0) > player_level:
			return False
		for requirement in task.get("taskRequirements") or []:
			required_id = requirement.get("task")
			if "complete" in (requirement.get("status") or []) and required_id not in completed:
				return False
		return True

	def lock_reason(self, task: dict, completed: set[str], player_level: int) -> str:
		level = task.get("minPlayerLevel") or 0
		if level > player_level:
			return f"需要玩家等级 {level}"
		for requirement in task.get("taskRequirements") or []:
			required_id = requirement.get("task")
			if "complete" in (requirement.get("status") or []) and required_id not in completed:
				required = self.tasks.get(required_id or "") or {}
				return f"需先完成「{required.get('name') or '未知任务'}」"
		return ""

	def task_summary(self, task: dict, completed: set[str], player_level: int) -> dict:
		trader = self.trader_view(task.get("trader"))
		map_entry = self.maps.get(task.get("map") or "") or {}
		return {
			"id": task.get("id"),
			"name": task.get("name"),
			"normalizedName": task.get("normalizedName"),
			"trader": trader,
			"map": map_entry.get("name") or "",
			"minPlayerLevel": task.get("minPlayerLevel"),
			"experience": task.get("experience"),
			"kappaRequired": bool(task.get("kappaRequired")),
			"lightkeeperRequired": bool(task.get("lightkeeperRequired")),
			"imageLink": task.get("taskImageLink") or "",
			"completed": task.get("id") in completed,
			"unlocked": self.is_unlocked(task, completed, player_level),
			"lockReason": self.lock_reason(task, completed, player_level),
			"objectiveCount": len(task.get("objectives") or []),
		}

	def search_tasks(
		self,
		query: str = "",
		trader_id: str = "",
		hide_completed: bool = False,
		hide_locked: bool = False,
		kappa_only: bool = False,
		lightkeeper_only: bool = False,
		completed: set[str] | None = None,
		player_level: int = 1,
		limit: int = 80,
		offset: int = 0,
		guided_task_ids: set[str] | None = None,
		guided_only: bool = False,
	) -> dict:
		completed = completed or set()
		guided_task_ids = guided_task_ids or set()
		text = (query or "").strip().lower()
		with self._lock:
			source = list(self.tasks.values())
			if trader_id:
				source = [task for task in source if task.get("trader") == trader_id]
			if text:
				source = [
					task
					for task in source
					if text in (task.get("name") or "").lower()
					or text in (task.get("normalizedName") or "").lower()
				]
			if kappa_only:
				source = [task for task in source if task.get("kappaRequired")]
			if guided_only:
				source = [task for task in source if task.get("id") in guided_task_ids]
			if lightkeeper_only:
				source = [
					task
					for task in source
					if task.get("lightkeeperRequired")
					or (self.traders.get(task.get("trader") or "") or {}).get("normalizedName") == "lightkeeper"
				]
			if hide_completed:
				source = [task for task in source if task.get("id") not in completed]
			if hide_locked:
				source = [
					task
					for task in source
					if task.get("id") in completed
					or self.is_unlocked(task, completed, player_level)
				]

			source.sort(key=lambda task: (task.get("minPlayerLevel") or 0, task.get("name") or ""))
			total = len(source)
			page = source[offset : offset + limit]
			return {
				"total": total,
				"offset": offset,
				"limit": limit,
				"tasks": [
					{**self.task_summary(task, completed, player_level), "hasGuide": task.get("id") in guided_task_ids}
					for task in page
				],
			}

	def _objective_view(self, objective: dict) -> dict:
		return {
			"id": objective.get("id"),
			"type": objective.get("type"),
			"description": objective.get("description") or "",
			"optional": bool(objective.get("optional")),
			"count": objective.get("count"),
			"items": [self._item_brief(item_id) for item_id in (objective.get("items") or [])[:8]],
			"maps": [
				(self.maps.get(map_id) or {}).get("name") or ""
				for map_id in (objective.get("maps") or [])
			],
		}

	def _reward_view(self, rewards: dict) -> dict:
		rewards = rewards or {}
		return {
			"items": [
				{**self._item_brief(entry.get("item")), "count": entry.get("count")}
				for entry in rewards.get("items") or []
			],
			"traderStanding": [
				{"trader": self._trader_name(entry.get("trader")), "standing": entry.get("standing")}
				for entry in rewards.get("traderStanding") or []
			],
			"offerUnlock": [
				{
					**self._item_brief(entry.get("item")),
					"trader": self._trader_name(entry.get("trader")),
					"level": entry.get("level"),
					"count": entry.get("count"),
				}
				for entry in rewards.get("offerUnlock") or []
			],
			"skillLevelReward": [
				{"skill": entry.get("skill"), "level": entry.get("level")}
				for entry in rewards.get("skillLevelReward") or []
			],
			"traderUnlock": [self._trader_name(trader_id) for trader_id in rewards.get("traderUnlock") or []],
			"traderDialogueUnlock": [
				self._trader_name(trader_id) for trader_id in rewards.get("traderDialogueUnlock") or []
			],
			"achievement": [
				(self.achievements.get(achievement_id) or {}).get("name") or ""
				for achievement_id in rewards.get("achievement") or []
			],
			"craftUnlock": [
				{
					**self._item_brief(entry.get("item")),
					"station": (self.hideout.get(entry.get("station") or "") or {}).get("name") or "",
					"level": entry.get("level"),
					"count": entry.get("count"),
				}
				for entry in rewards.get("craftUnlock") or []
			],
			"customization": [
				{"name": entry.get("name") or "", "imageLink": entry.get("imageLink") or ""}
				for entry in rewards.get("customization") or []
			],
			"locationUnlock": [
				(self.maps.get(map_id) or {}).get("name") or ""
				for map_id in rewards.get("locationUnlock") or []
			],
		}

	def task_detail(self, task_id: str, completed: set[str], player_level: int) -> dict | None:
		with self._lock:
			task = self.tasks.get(task_id)
			if task is None:
				return None
			summary = self.task_summary(task, completed, player_level)
			summary["description"] = task.get("description") or ""
			summary["wikiLink"] = task.get("wikiLink") or ""
			summary["factionName"] = task.get("factionName") or ""
			summary["restartable"] = bool(task.get("restartable"))
			summary["objectives"] = [self._objective_view(entry) for entry in task.get("objectives") or []]
			summary["finishRewards"] = self._reward_view(task.get("finishRewards"))
			summary["startRewards"] = self._reward_view(task.get("startRewards"))
			summary["prerequisites"] = [
				{
					"id": requirement.get("task"),
					"name": (self.tasks.get(requirement.get("task") or "") or {}).get("name") or "未知任务",
					"completed": requirement.get("task") in completed,
				}
				for requirement in task.get("taskRequirements") or []
				if "complete" in (requirement.get("status") or [])
			]
			summary["traderRequirements"] = [
				{
					"type": requirement.get("requirementType"),
					"value": requirement.get("value"),
					"compare": requirement.get("compareMethod"),
					"trader": self._trader_name(requirement.get("trader")),
				}
				for requirement in task.get("traderRequirements") or []
			]
			summary["followUps"] = [
				self.task_summary(other, completed, player_level)
				for other in self.tasks.values()
				if any(
					requirement.get("task") == task_id and "complete" in (requirement.get("status") or [])
					for requirement in other.get("taskRequirements") or []
				)
			]
			summary["neededKeys"] = self._needed_keys(task)
			return summary

	def _needed_keys(self, task: dict) -> list[dict]:
		"""neededKeys 形如 [{map, keys: [...]}]，按地图分组后展开成钥匙条目。"""
		entries = []
		for group in task.get("neededKeys") or []:
			if not isinstance(group, dict):
				continue
			map_name = (self.maps.get(group.get("map") or "") or {}).get("name") or ""
			for key_id in group.get("keys") or []:
				if isinstance(key_id, str):
					entries.append({**self._item_brief(key_id), "map": map_name})
		return entries

	# ---------- 商人 ----------

	def trader_detail(self, trader_id: str) -> dict | None:
		with self._lock:
			trader = self.traders.get(trader_id)
			if trader is None:
				return None
			view = self.trader_view(trader_id)
			view["description"] = trader.get("description") or ""
			view["currency"] = trader.get("currency") or ""
			view["resetTime"] = trader.get("resetTime") or ""
			view["levels"] = [
				{
					"level": entry.get("level"),
					"requiredPlayerLevel": entry.get("requiredPlayerLevel"),
					"requiredReputation": entry.get("requiredReputation"),
					"requiredCommerce": entry.get("requiredCommerce"),
					"payRate": entry.get("payRate"),
				}
				for entry in trader.get("levels") or []
			]
			buyable = []
			for item in self.items.values():
				for offer_trader, price, level, limit, restock in item.get("buyFromTrader") or []:
					if offer_trader != trader_id:
						continue
					buyable.append(
						{
							**self.item_summary(item),
							"price": price,
							"traderLevel": level,
							"buyLimit": limit,
							"restockAmount": restock,
						}
					)
			buyable.sort(key=lambda entry: entry.get("price") or 0)
			view["offers"] = buyable[:400]
			view["offerCount"] = len(buyable)

			tasks = [
				self.task_summary(task, set(), 1)
				for task in self.tasks.values()
				if task.get("trader") == trader_id
			]
			tasks.sort(key=lambda entry: entry.get("minPlayerLevel") or 0)
			view["tasks"] = tasks
			view["taskCount"] = len(tasks)
			return view

	# ---------- 兑换 ----------

	def barter_list(
		self,
		query: str = "",
		trader_id: str = "",
		limit: int = 60,
		offset: int = 0,
	) -> dict:
		text = (query or "").strip().lower()
		with self._lock:
			source = self.barters
			if trader_id:
				source = [entry for entry in source if entry.get("trader") == trader_id]
			if text:
				matched = []
				for entry in source:
					names = []
					offered = (entry.get("offeredItem") or {}).get("item")
					names.append((self.items.get(offered or "") or {}).get("name") or "")
					for req in entry.get("requiredItems") or []:
						names.append((self.items.get(req.get("item") or "") or {}).get("name") or "")
					if any(text in name.lower() for name in names if name):
						matched.append(entry)
				source = matched

			total = len(source)
			page = source[offset : offset + limit]
			return {
				"total": total,
				"offset": offset,
				"limit": limit,
				"barters": [self._barter_view(entry) for entry in page],
			}

	# ---------- 藏身处 ----------

	def hideout_list(self) -> list[dict]:
		with self._lock:
			entries = []
			for station_id, station in self.hideout.items():
				levels = []
				for level in station.get("levels") or []:
					levels.append(
						{
							"level": level.get("level"),
							"constructionTime": level.get("constructionTime"),
							"items": [
								{**self._item_brief(req.get("item")), "count": req.get("count")}
								for req in level.get("itemRequirements") or []
							],
							"traderRequirements": [
								{
									"trader": self._trader_name(req.get("trader")),
									"level": req.get("level"),
								}
								for req in level.get("traderRequirements") or []
							],
							"stationRequirements": [
								{
									"station": (self.hideout.get(req.get("station") or "") or {}).get("name") or "",
									"level": req.get("level"),
								}
								for req in level.get("stationLevelRequirements") or []
							],
						}
					)
				entries.append(
					{
						"id": station_id,
						"name": station.get("name") or "",
						"normalizedName": station.get("normalizedName") or "",
						"areaType": station.get("areaType"),
						"imageLink": station.get("imageLink") or "",
						"levels": levels,
					}
				)
			entries.sort(key=lambda entry: (entry.get("areaType") or 0))
			return entries

	def craft_list(
		self,
		query: str = "",
		station: str = "",
		limit: int = 60,
		offset: int = 0,
	) -> dict:
		text = (query or "").strip().lower()
		with self._lock:
			source = self.crafts
			if station:
				source = [entry for entry in source if entry.get("station") == station]
			if text:
				matched = []
				for entry in source:
					names = [(self.items.get((entry.get("productItem") or {}).get("item") or "") or {}).get("name") or ""]
					for req in entry.get("requiredItems") or []:
						names.append((self.items.get(req.get("item") or "") or {}).get("name") or "")
					if any(text in name.lower() for name in names if name):
						matched.append(entry)
				source = matched

			total = len(source)
			page = source[offset : offset + limit]
			return {
				"total": total,
				"offset": offset,
				"limit": limit,
				"crafts": [self._craft_view(entry) for entry in page],
			}

