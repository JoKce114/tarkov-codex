from __future__ import annotations

import os
import threading

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import paths
from .assets import IconCache, SvgCache
from .atlas import atlas_detail, build_task_map, floor_svg, map_catalog, map_geometry, read_tile
from .cdk import CdkStore
from .datasets import DEFAULT_MODE, GAME_MODES, MODE_ORDER, is_valid_mode
from .guides import GuideStore
from .home_sync import HomeSync
from .updates import updates_router
from .bosses import boss_router
from .mapconfig import MapConfig
from .map_icons import map_icons_router
from .maps import MapStore
from .progress import ProgressStore
from .store import DataStore
from .sync import SyncManager


def create_app(
	store: DataStore,
	sync_manager: SyncManager,
	progress: ProgressStore,
	cdk: CdkStore,
	guides: GuideStore,
	map_store: MapStore,
) -> FastAPI:
	app = FastAPI(title=paths.APP_NAME, docs_url=None, redoc_url=None)
	app.include_router(updates_router())
	app.include_router(boss_router(store))
	app.include_router(map_icons_router(store.data_dir))
	home_sync = HomeSync(store, sync_manager, guides, cdk)
	icons = IconCache(paths.ICON_DIR)
	map_config = MapConfig()
	svg_cache = SvgCache(paths.CACHE_DIR)

	@app.get("/api/health")
	def health() -> dict:
		return {"ok": True, "app": paths.APP_NAME, "version": paths.APP_VERSION}

	@app.get("/api/modes")
	def modes() -> dict:
		return {
			"ok": True,
			"current": store.mode,
			"default": DEFAULT_MODE,
			"modes": [{"key": key, "label": GAME_MODES[key]} for key in MODE_ORDER],
		}

	@app.post("/api/mode")
	def set_mode(payload: dict):
		mode = (payload or {}).get("mode")
		if not isinstance(mode, str) or not is_valid_mode(mode):
			return JSONResponse({"ok": False, "error": "无效的游戏模式"}, status_code=400)
		stats = store.set_mode(mode)
		paths.save_mode(mode)
		return {"ok": True, **stats}

	@app.get("/api/stats")
	def stats() -> dict:
		return {"ok": True, **store.stats()}

	@app.get("/api/sync/status")
	def sync_status() -> dict:
		return {"ok": True, **sync_manager.status(store.mode)}

	@app.get("/api/home-sync")
	def home_sync_status():
		return {"ok": True, **home_sync.status()}

	@app.post("/api/home-sync/{scope}")
	def home_sync_start(scope: str):
		return home_sync.start(scope)

	@app.post("/api/sync/now")
	def sync_now():
		started = sync_manager.start_background()
		return {"ok": started, "running": True, "message": "已开始同步" if started else "正在同步中"}

	@app.post("/api/data/reload")
	def data_reload() -> dict:
		return {"ok": True, **store.load()}

	@app.get("/api/categories")
	def categories() -> dict:
		return {"ok": True, "tree": store.category_tree()}

	@app.get("/api/items")
	def items(
		q: str = "",
		category: str = "",
		sort: str = "name",
		limit: int = 60,
		offset: int = 0,
	) -> dict:
		limit = max(1, min(limit, 200))
		offset = max(0, offset)
		return {"ok": True, **store.search_items(q, limit, offset, category, sort)}

	@app.get("/api/items/{item_id}")
	def item_detail(item_id: str):
		detail = store.item_detail(item_id)
		if detail is None:
			return JSONResponse({"ok": False, "error": "找不到该物品"}, status_code=404)
		return {"ok": True, "item": detail}

	@app.get("/api/progress")
	def progress_state() -> dict:
		return {"ok": True, **progress.snapshot(store.mode)}

	@app.post("/api/progress/task")
	def progress_task(payload: dict):
		data = payload if isinstance(payload, dict) else {}
		task_id = data.get("taskId")
		if not isinstance(task_id, str) or not task_id:
			return JSONResponse({"ok": False, "error": "缺少任务 ID"}, status_code=400)
		if task_id not in store.tasks:
			return JSONResponse({"ok": False, "error": "找不到该任务"}, status_code=404)
		completed = bool(data.get("completed"))
		return {"ok": True, **progress.set_task(store.mode, task_id, completed)}

	@app.post("/api/progress/level")
	def progress_level(payload: dict):
		data = payload if isinstance(payload, dict) else {}
		level = data.get("level")
		if not isinstance(level, int):
			return JSONResponse({"ok": False, "error": "等级必须是整数"}, status_code=400)
		return {"ok": True, **progress.set_level(store.mode, level)}

	@app.post("/api/progress/reset")
	def progress_reset():
		return {"ok": True, **progress.reset(store.mode)}

	@app.get("/api/traders")
	def traders() -> dict:
		snapshot = progress.snapshot(store.mode)
		return {
			"ok": True,
			"traders": store.trader_list(set(snapshot["completed"]), snapshot["playerLevel"]),
		}

	@app.get("/api/traders/{trader_id}")
	def trader_detail(trader_id: str):
		detail = store.trader_detail(trader_id)
		if detail is None:
			return JSONResponse({"ok": False, "error": "找不到该商人"}, status_code=404)
		return {"ok": True, "trader": detail}

	@app.get("/api/barters")
	def barters(q: str = "", trader: str = "", limit: int = 60, offset: int = 0) -> dict:
		return {
			"ok": True,
			**store.barter_list(q, trader, max(1, min(limit, 200)), max(0, offset)),
		}

	@app.get("/api/hideout")
	def hideout() -> dict:
		return {"ok": True, "stations": store.hideout_list()}

	@app.get("/api/crafts")
	def crafts(q: str = "", station: str = "", limit: int = 60, offset: int = 0) -> dict:
		return {
			"ok": True,
			**store.craft_list(q, station, max(1, min(limit, 200)), max(0, offset)),
		}

	@app.get("/api/tasks")
	def tasks(
		q: str = "",
		trader: str = "",
		hideCompleted: bool = False,
		hideLocked: bool = False,
		kappa: bool = False,
		lightkeeper: bool = False,
		limit: int = 80,
		offset: int = 0,
		hasGuide: bool = False,
	) -> dict:
		snapshot = progress.snapshot(store.mode)
		return {
			"ok": True,
			"playerLevel": snapshot["playerLevel"],
			"completedCount": snapshot["completedCount"],
			**store.search_tasks(
				query=q,
				trader_id=trader,
				hide_completed=hideCompleted,
				hide_locked=hideLocked,
				kappa_only=kappa,
				lightkeeper_only=lightkeeper,
				guided_task_ids=guides.guided_task_ids(),
				guided_only=hasGuide,
				completed=set(snapshot["completed"]),
				player_level=snapshot["playerLevel"],
				limit=max(1, min(limit, 200)),
				offset=max(0, offset),
			),
		}

	@app.get("/api/tasks/{task_id}")
	def task_detail(task_id: str):
		snapshot = progress.snapshot(store.mode)
		detail = store.task_detail(task_id, set(snapshot["completed"]), snapshot["playerLevel"])
		if detail is None:
			return JSONResponse({"ok": False, "error": "找不到该任务"}, status_code=404)
		return {"ok": True, "task": detail}

	@app.get("/api/tasks/{task_id}/map")
	def task_map(task_id: str):
		task = store.tasks.get(task_id)
		if task is None:
			return JSONResponse({"ok": False, "error": "找不到该任务"}, status_code=404)
		return {"ok": True, **build_task_map(task, store, map_config, svg_cache)}

	@app.get("/api/tasks/{task_id}/guides")
	def task_guides(task_id: str):
		if task_id not in store.tasks:
			return JSONResponse({"ok": False, "error": "找不到该任务"}, status_code=404)
		return {"ok": True, "guides": guides.get(task_id)}

	@app.get("/api/guide/image")
	def guide_image(path: str):
		local = guides.fetch_image(path)
		if local is None:
			return Response(status_code=404)
		suffix = local.suffix.lower()
		media = {"webp": "image/webp", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}.get(
			suffix.lstrip("."), "image/webp"
		)
		return Response(content=local.read_bytes(), media_type=media, headers={"Cache-Control": "public, max-age=604800"})

	@app.get("/api/guides/status")
	def guides_status() -> dict:
		return {"ok": True, **guides.status()}

	@app.post("/api/guides/sync")
	def guides_sync():
		if guides._syncing:
			return {"ok": False, "error": "正在同步"}
		threading.Thread(target=guides.sync, daemon=True).start()
		return {"ok": True, "message": "已开始同步"}

	@app.get("/api/cdk")
	def cdk_list() -> dict:
		return {"ok": True, "items": cdk.items(), "status": cdk.status()}

	@app.post("/api/cdk/sync")
	def cdk_sync():
		return {"ok": True, **cdk.sync()}

	@app.get("/api/game-maps")
	def game_maps() -> dict:
		maps = map_store.maps()
		summary = [
			{
				"slug": entry.get("slug"),
				"name": entry.get("name"),
				"nameEn": entry.get("nameEn"),
				"players": entry.get("players"),
				"raidDuration": entry.get("raidDuration"),
				"previewUrl": entry.get("previewUrl"),
				"exitCount": entry.get("exitCount"),
				"bossCount": entry.get("bossCount"),
				"keyCount": entry.get("keyCount"),
			}
			for entry in maps
		]
		return {"ok": True, "maps": summary, "status": map_store.status()}

	@app.get("/api/atlas")
	def atlas_maps() -> dict:
		return {"ok": True, "maps": map_catalog(store.maps, map_config)}

	@app.post("/api/atlas/sync-layers")
	def sync_atlas_layers():
		mode = store.mode
		result = sync_manager.sync_map_layers(mode)
		if not result.get("ok"):
			return JSONResponse(result, status_code=503)
		with store._lock:
			if store.mode == mode:
				store.load()
		return {"ok": True, "mode": mode}

	@app.get("/api/atlas/tile/{map_key}/{zoom}/{column}/{row}")
	def atlas_tile(map_key: str, zoom: int, column: int, row: int, floor: str = "base"):
		record = map_config.entry_by_normalized(map_key)
		payload = read_tile(paths.CACHE_DIR, record, zoom, column, row, floor)
		if payload is None:
			return Response(status_code=404)
		return Response(payload, media_type="image/png", headers={"Cache-Control": "public, max-age=604800"})

	@app.get("/api/atlas/{map_key}")
	def interactive_map(map_key: str):
		record = map_config.entry_by_normalized(map_key)
		if record is None:
			return JSONResponse({"ok": False, "error": "找不到该交互地图"}, status_code=404)
		geometry = map_geometry(record, svg_cache)
		if geometry is None:
			return JSONResponse({"ok": False, "error": "地图底图加载失败，请检查网络后重试"}, status_code=503)
		return {"ok": True, **atlas_detail(map_key, record, geometry, map_config, store, progress, svg_cache)}

	@app.get("/api/game-maps/{slug}")
	def game_map_detail(slug: str):
		for entry in map_store.maps():
			if entry.get("slug") == slug:
				return {"ok": True, "map": entry}
		return JSONResponse({"ok": False, "error": "找不到该地图"}, status_code=404)

	@app.get("/api/game-map/image")
	def game_map_image(url: str):
		local = map_store.fetch_image(url)
		if local is None:
			return Response(status_code=404)
		suffix = local.suffix.lower()
		media = {
			".jpg": "image/jpeg",
			".jpeg": "image/jpeg",
			".png": "image/png",
			".webp": "image/webp",
		}.get(suffix, "image/jpeg")
		return Response(content=local.read_bytes(), media_type=media, headers={"Cache-Control": "public, max-age=604800"})

	@app.post("/api/game-maps/sync")
	def game_maps_sync():
		if map_store._syncing:
			return {"ok": False, "error": "正在同步"}
		threading.Thread(target=map_store.sync, daemon=True).start()
		return {"ok": True, "message": "已开始同步"}

	@app.post("/api/open-file")
	def open_file(payload: dict):
		"""把地图图片在系统看图工具里打开，可以全屏、缩放、翻看。"""
		url = (payload or {}).get("url")
		if not isinstance(url, str) or not url:
			return JSONResponse({"ok": False, "error": "缺少图片地址"}, status_code=400)
		local = map_store.fetch_image(url)
		if local is None:
			return JSONResponse({"ok": False, "error": "图片还没下载好，请稍后重试"}, status_code=404)
		try:
			os.startfile(str(local))
		except OSError as error:
			return JSONResponse({"ok": False, "error": str(error)}, status_code=500)
		return {"ok": True, "path": str(local)}

	@app.get("/api/map/svg/{map_key}")
	def map_svg(map_key: str, floor: str = ""):
		record = map_config.entry_by_normalized(map_key)
		if record is None:
			return Response(status_code=404)
		text = svg_cache.get(record["key"], record.get("svg") or "")
		if text and floor:
			text = floor_svg(text, record, floor)
		if not text:
			return Response(status_code=404)
		return Response(content=text, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=604800"})

	@app.get("/api/icon/{item_id}")
	def icon(item_id: str, size: str = "icon"):
		item = store.items.get(item_id)
		if not item:
			return Response(status_code=404)
		field = {
			"icon": "iconLink",
			"grid": "gridImageLink",
			"image": "image512pxLink",
		}.get(size, "iconLink")
		remote = item.get(field) or item.get("iconLink") or ""
		cache_key = item_id if size == "icon" else f"{item_id}-{size}"
		result = icons.get(cache_key, remote)
		if result is None:
			return Response(status_code=404)
		payload, content_type = result
		return Response(content=payload, media_type=content_type, headers={"Cache-Control": "public, max-age=604800"})

	@app.get("/api/asset/{kind}/{asset_id}")
	def asset(kind: str, asset_id: str):
		if kind == "trader":
			source = store.traders.get(asset_id) or {}
			remote = source.get("imageLink") or ""
		elif kind == "task":
			source = store.tasks.get(asset_id) or {}
			remote = source.get("taskImageLink") or ""
		elif kind == "hideout":
			source = store.hideout.get(asset_id) or {}
			remote = source.get("imageLink") or ""
		else:
			return Response(status_code=404)
		if not remote:
			return Response(status_code=404)
		result = icons.get(f"{kind}-{asset_id}", remote)
		if result is None:
			return Response(status_code=404)
		payload, content_type = result
		return Response(content=payload, media_type=content_type, headers={"Cache-Control": "public, max-age=604800"})

	@app.exception_handler(Exception)
	def handle_error(request: Request, error: Exception) -> JSONResponse:
		import traceback

		try:
			log_file = paths.LOG_DIR / "request_error.log"
			log_file.parent.mkdir(parents=True, exist_ok=True)
			with log_file.open("a", encoding="utf-8") as handle:
				handle.write(f"\n=== {request.method} {request.url.path} ===\n")
				handle.write("".join(traceback.format_exception(type(error), error, error.__traceback__)))
		except OSError:
			pass
		return JSONResponse({"ok": False, "error": str(error)}, status_code=500)

	app.mount("/", StaticFiles(directory=paths.WEB_DIR, html=True), name="web")
	return app
