from __future__ import annotations

"""数据精简：同步落盘时就把界面用不到的大字段去掉，避免每次启动都白占内存。"""

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


def _compact_sell(offers) -> list[list]:
	result = []
	for entry in offers or []:
		if not isinstance(entry, dict):
			continue
		result.append([entry.get("trader"), entry.get("priceRUB") or entry.get("price")])
	return result


def _compact_buy(offers) -> list[list]:
	result = []
	for entry in offers or []:
		if not isinstance(entry, dict):
			continue
		result.append(
			[
				entry.get("trader"),
				entry.get("priceRUB") or entry.get("price"),
				entry.get("minTraderLevel"),
				entry.get("buyLimit"),
				entry.get("restockAmount"),
			]
		)
	return result


def slim_items(payload: dict) -> dict:
	"""物品：只保留界面用到的字段；商人价格压成数组，去掉重复的货币字段。"""
	body = payload.get("data")
	if not isinstance(body, dict):
		return payload
	items = body.get("items")
	if not isinstance(items, dict):
		return payload

	slim = {}
	for item_id, item in items.items():
		row = {key: item[key] for key in ITEM_FIELDS if key in item}
		row["sellToTrader"] = _compact_sell(item.get("sellToTrader"))
		row["buyFromTrader"] = _compact_buy(item.get("buyFromTrader"))
		slim[item_id] = row

	body["items"] = slim
	# 这几张表界面没用到，占空间还大
	for key in ("fleaMarket", "armorMaterials", "playerLevels", "mastering", "skills", "specialItems", "settings"):
		body.pop(key, None)
	return payload


def slim_maps(payload: dict) -> dict:
	"""保留地图页和任务点位所需信息，去掉体积较大的战利品及刷新点。"""
	body = payload.get("data")
	if not isinstance(body, dict):
		return payload
	maps = body.get("maps")
	if not isinstance(maps, dict):
		return payload

	fields = ("name", "normalizedName", "description", "players", "raidDuration", "wiki",
		"extracts", "bosses", "transits", "hazards", "locks", "accessKeys")
	payload["data"] = {
		"maps": {map_id: {field: entry[field] for field in fields if field in entry}
			for map_id, entry in maps.items()},
		"mobs": {mob_id: {"name": entry.get("name")} for mob_id, entry in (body.get("mobs") or {}).items()},
	}
	return payload


def slim_tasks(payload: dict) -> dict:
	"""任务：保留任务和成就，其余（任务物品表、威望）界面没用到。"""
	body = payload.get("data")
	if not isinstance(body, dict):
		return payload
	for key in ("questItems", "prestige"):
		body.pop(key, None)
	return payload


def apply(dataset_key: str, payload: dict) -> dict:
	if dataset_key == "items":
		return slim_items(payload)
	if dataset_key == "maps":
		return slim_maps(payload)
	if dataset_key == "tasks":
		return slim_tasks(payload)
	return payload
