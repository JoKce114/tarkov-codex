from __future__ import annotations

import os
import threading
from pathlib import Path

from anyio import CapacityLimiter, to_thread
from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import paths
from .assets import IconCache, SvgCache
from .datasets import DEFAULT_MODE, GAME_MODES, MODE_ORDER, is_valid_mode
from .map_atlas import AtlasCache
from .mapconfig import MapConfig
from .maps import build_map_detail, build_map_summary
from .progress import ProgressStore
from .store import DataStore
from .sync import SyncManager
from .updater import Updater


def build_task_map(task: dict, store: DataStore, map_config: MapConfig) -> dict:
	"""返回归一化点位，不读取底图。"""
	groups: dict[str, dict] = {}
	for objective in task.get("objectives") or []:
		description = objective.get("description") or ""
		locations = list(objective.get("zones") or [])
		for group in objective.get("possibleLocations") or []:
			locations.extend({"map": group.get("map"), "position": point} for point in group.get("positions") or [])
		for zone in locations:
			position = zone.get("position") or {}
			if "x" not in position or "z" not in position:
				continue
			map_entry = store.maps.get(zone.get("map") or "") or {}
			normalized = map_entry.get("normalizedName") or ""
			record = map_config.entry_by_normalized(normalized)
			if record is None or not record.get("svg"):
				continue
			point = map_config.to_normalized(record["key"], position["x"], position["z"])
			if point is None:
				continue

			# 少量数据源坐标本身有误（如 Ground Zero 的 UN Roadblock），落在图外就不画
			if not all(-0.02 <= coordinate <= 1.02 for coordinate in point):
				continue

			group = groups.setdefault(
				record["key"],
				{
					"mapKey": record["normalized"],
					"mapName": map_entry.get("name") or "",
					"points": [],
				},
			)
			if normalized == record["normalized"]:
				group["mapName"] = map_entry.get("name") or group["mapName"]
			group["points"].append(
				{
					"x": point[0],
					"y": point[1],
					"label": description,
					"type": objective.get("type") or "",
					"optional": bool(objective.get("optional")),
				}
			)
	return {"maps": list(groups.values())}


def create_app(
	sync_manager: SyncManager,
	progress: ProgressStore,
	*,
	auto_update: bool = True,
) -> FastAPI:
	app = FastAPI(title=paths.APP_NAME, docs_url=None, redoc_url=None)
	icons = IconCache(paths.ICON_DIR)
	map_config = MapConfig()
	svg_cache = SvgCache(paths.CACHE_DIR)
	updater = Updater(paths.DATA_DIR)
	atlas = AtlasCache(paths.DATA_DIR / "maps" / "images")
	map_assets = {url: key for key, url in map_config.svg_jobs()}
	media_workers = None

	async def load_media(loader, *args):
		nonlocal media_workers
		if media_workers is None:
			media_workers = CapacityLimiter(6)
		return await to_thread.run_sync(loader, *args, limiter=media_workers)

	async def current_store() -> DataStore:
		return sync_manager.current

	@app.get("/api/health")
	def health() -> dict:
		return {"ok": True, "app": paths.APP_NAME, "version": paths.APP_VERSION}

	@app.get("/api/modes")
	def modes(store: DataStore = Depends(current_store)) -> dict:
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
		stats = sync_manager.set_mode(mode).stats()
		paths.save_mode(mode)
		return {"ok": True, **stats}

	@app.get("/api/stats")
	def stats(store: DataStore = Depends(current_store)) -> dict:
		return {"ok": True, **store.stats()}

	@app.get("/api/sync/status")
	def sync_status() -> dict:
		return {"ok": True, **sync_manager.status()}

	@app.get("/api/update/status")
	def update_status() -> dict:
		return {"ok": True, **updater.status()}

	@app.post("/api/update/check")
	def update_check() -> dict:
		return updater.check_async(manual=True)

	@app.post("/api/update/auto")
	def update_auto(payload: dict):
		enabled = bool((payload or {}).get("enabled"))
		updater.save_settings({"autoCheck": enabled})
		return {"ok": True, "autoCheck": enabled}

	@app.post("/api/update/proxy")
	def update_proxy(payload: dict):
		return updater.set_proxy(str((payload or {}).get("proxy") or ""))

	@app.post("/api/update/download")
	def update_download() -> dict:
		return updater.start_download()

	@app.post("/api/update/install")
	def update_install() -> dict:
		return updater.install()

	@app.post("/api/sync/now")
	def sync_now():
		started = sync_manager.start_background()
		return {"ok": started, "running": True, "message": "已开始同步" if started else "正在同步中"}

	@app.get("/api/categories")
	def categories(store: DataStore = Depends(current_store)) -> dict:
		return {"ok": True, "tree": store.category_tree()}

	@app.get("/api/items")
	def items(
		q: str = "",
		category: str = "",
		sort: str = "name",
		limit: int = 60,
		offset: int = 0,
		store: DataStore = Depends(current_store),
	) -> dict:
		limit = max(1, min(limit, 200))
		offset = max(0, offset)
		return {"ok": True, **store.search_items(q, limit, offset, category, sort)}

	@app.get("/api/items/{item_id}")
	def item_detail(item_id: str, store: DataStore = Depends(current_store)):
		detail = store.item_detail(item_id)
		if detail is None:
			return JSONResponse({"ok": False, "error": "找不到该物品"}, status_code=404)
		return {"ok": True, "item": detail}

	@app.get("/api/progress")
	def progress_state(store: DataStore = Depends(current_store)) -> dict:
		return {"ok": True, **progress.snapshot(store.mode)}

	@app.post("/api/progress/task")
	def progress_task(payload: dict, store: DataStore = Depends(current_store)):
		data = payload if isinstance(payload, dict) else {}
		task_id = data.get("taskId")
		if not isinstance(task_id, str) or not task_id:
			return JSONResponse({"ok": False, "error": "缺少任务 ID"}, status_code=400)
		if task_id not in store.tasks:
			return JSONResponse({"ok": False, "error": "找不到该任务"}, status_code=404)
		completed = bool(data.get("completed"))
		return {"ok": True, **progress.set_task(store.mode, task_id, completed)}

	@app.post("/api/progress/level")
	def progress_level(payload: dict, store: DataStore = Depends(current_store)):
		data = payload if isinstance(payload, dict) else {}
		level = data.get("level")
		if not isinstance(level, int):
			return JSONResponse({"ok": False, "error": "等级必须是整数"}, status_code=400)
		return {"ok": True, **progress.set_level(store.mode, level)}

	@app.post("/api/progress/reset")
	def progress_reset(store: DataStore = Depends(current_store)):
		return {"ok": True, **progress.reset(store.mode)}

	@app.get("/api/traders")
	def traders(store: DataStore = Depends(current_store)) -> dict:
		snapshot = progress.snapshot(store.mode)
		return {
			"ok": True,
			"traders": store.trader_list(set(snapshot["completed"]), snapshot["playerLevel"]),
		}

	@app.get("/api/traders/{trader_id}")
	def trader_detail(trader_id: str, store: DataStore = Depends(current_store)):
		detail = store.trader_detail(trader_id)
		if detail is None:
			return JSONResponse({"ok": False, "error": "找不到该商人"}, status_code=404)
		return {"ok": True, "trader": detail}

	@app.get("/api/barters")
	def barters(q: str = "", trader: str = "", limit: int = 60, offset: int = 0, store: DataStore = Depends(current_store)) -> dict:
		return {
			"ok": True,
			**store.barter_list(q, trader, max(1, min(limit, 200)), max(0, offset)),
		}

	@app.get("/api/hideout")
	def hideout(store: DataStore = Depends(current_store)) -> dict:
		return {"ok": True, "stations": store.hideout_list()}

	@app.get("/api/crafts")
	def crafts(q: str = "", station: str = "", limit: int = 60, offset: int = 0, store: DataStore = Depends(current_store)) -> dict:
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
		store: DataStore = Depends(current_store),
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
				completed=set(snapshot["completed"]),
				player_level=snapshot["playerLevel"],
				limit=max(1, min(limit, 200)),
				offset=max(0, offset),
			),
		}

	@app.get("/api/tasks/{task_id}")
	def task_detail(task_id: str, store: DataStore = Depends(current_store)):
		snapshot = progress.snapshot(store.mode)
		detail = store.task_detail(task_id, set(snapshot["completed"]), snapshot["playerLevel"])
		if detail is None:
			return JSONResponse({"ok": False, "error": "找不到该任务"}, status_code=404)
		return {"ok": True, "task": detail}

	@app.get("/api/tasks/{task_id}/map")
	def task_map(task_id: str, store: DataStore = Depends(current_store)):
		task = store.tasks.get(task_id)
		if task is None:
			return JSONResponse({"ok": False, "error": "找不到该任务"}, status_code=404)
		return {"ok": True, **build_task_map(task, store, map_config)}

	@app.get("/api/game-maps")
	def game_maps(store: DataStore = Depends(current_store)) -> dict:
		return {"ok": True, "maps": [build_map_summary(store, map_id, map_config) for map_id in store.visible_map_ids()]}

	@app.get("/api/game-maps/{slug}")
	def game_map_detail(slug: str, store: DataStore = Depends(current_store)):
		map_id = store.map_ids_by_slug.get(slug, slug)
		if map_id in store.maps:
			return {"ok": True, "map": build_map_detail(store, map_id, map_config)}
		return JSONResponse({"ok": False, "error": "找不到该地图"}, status_code=404)

	def map_image_path(url: str) -> Path | None:
		key = map_assets.get(url)
		if key:
			return svg_cache.cache.fetch_path(svg_cache.local_path(key), url)
		return atlas.get(url)

	@app.get("/api/game-map/image")
	async def game_map_image(url: str):
		local = await load_media(map_image_path, url)
		if local is None:
			return Response(status_code=404)
		media = {".svg": "image/svg+xml", ".webp": "image/webp", ".jpg": "image/jpeg"}
		return FileResponse(local, media_type=media[local.suffix], headers={"Cache-Control": "public, max-age=604800"})

	@app.post("/api/open-file")
	async def open_file(payload: dict):
		"""把地图图片在系统看图工具里打开，可以全屏、缩放、翻看。"""
		url = (payload or {}).get("url")
		if not isinstance(url, str) or not url:
			return JSONResponse({"ok": False, "error": "缺少图片地址"}, status_code=400)
		local = await load_media(map_image_path, url)
		if local is None:
			return JSONResponse({"ok": False, "error": "图片还没下载好，请稍后重试"}, status_code=404)
		try:
			os.startfile(str(local))
		except OSError as error:
			return JSONResponse({"ok": False, "error": str(error)}, status_code=500)
		return {"ok": True, "path": str(local)}

	@app.get("/api/map/svg/{map_key}")
	async def map_svg(map_key: str):
		record = map_config.entry_by_normalized(map_key)
		if record is None:
			return Response(status_code=404)
		text = await load_media(svg_cache.get, record["key"], record.get("svg") or "")
		if not text:
			return Response(status_code=404)
		return Response(content=text, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=604800"})

	@app.get("/api/icon/{item_id}")
	async def icon(item_id: str, size: str = "icon", store: DataStore = Depends(current_store)):
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
		result = await load_media(icons.get, cache_key, remote)
		if result is None:
			return Response(status_code=404)
		payload, content_type = result
		return Response(content=payload, media_type=content_type, headers={"Cache-Control": "public, max-age=604800"})

	@app.get("/api/asset/{kind}/{asset_id}")
	async def asset(kind: str, asset_id: str, store: DataStore = Depends(current_store)):
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
		result = await load_media(icons.get, f"{kind}-{asset_id}", remote)
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

	@app.get("/", response_class=HTMLResponse)
	def index() -> str:
		"""首页由服务端渲染，把版本号填进静态资源地址。

		这样升级后浏览器不会继续用缓存里的旧 app.js / style.css。
		"""
		try:
			page = (paths.WEB_DIR / "index.html").read_text(encoding="utf-8")
		except OSError:
			return ""
		return page.replace("__VERSION__", paths.APP_VERSION)

	app.mount("/", StaticFiles(directory=paths.WEB_DIR, html=True), name="web")

	# 启动后异步查一次；24 小时内或没开自动检查都不会发请求
	if auto_update:
		timer = threading.Timer(5.0, updater.auto_check)
		timer.daemon = True
		timer.start()
	return app
