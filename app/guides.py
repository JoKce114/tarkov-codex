"""从 OPtarkov 任务站点地图同步攻略与实景截图。"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit
from xml.etree import ElementTree

import requests

from .assets import ASSET_HEADERS
from .datasets import MODE_ORDER
from .store import DataStore

HOME = "https://www.optarkov.com"
SITEMAP = HOME + "/sitemap.xml"
DETAIL = HOME + "/wiki/task/"
SYNC_INTERVAL = 7 * 24 * 60 * 60
WORKERS = 4
HEADERS = {**ASSET_HEADERS, "Referer": HOME + "/", "Accept": "*/*", "Accept-Language": "zh-CN,zh;q=0.9"}


def now_text() -> str:
	return datetime.now().isoformat(timespec="seconds")


def slugify(value: str) -> str:
	return re.sub(r"[^a-z0-9]+", "-", value.lower().replace("'", "").replace("’", "")).strip("-")


def sitemap_tasks(source: str) -> dict[str, str]:
	root = ElementTree.fromstring(source)
	pages = {}
	for entry in root.findall("{*}url"):
		url = entry.findtext("{*}loc", "").strip()
		match = re.fullmatch(re.escape(DETAIL) + r"([0-9]+)/?", url)
		if match:
			pages[match[1]] = entry.findtext("{*}lastmod", "").strip()
	if not pages:
		raise ValueError("OPtarkov 站点地图没有任务页面")
	return pages


def image_url(remote: str) -> str:
	url = urljoin(HOME + "/", remote)
	parts = urlsplit(url)
	path = unquote(parts.path)
	if (
		parts.scheme != "https" or parts.netloc != "www.optarkov.com"
		or not path.startswith("/images/") or ".." in path.split("/") or "\\" in path
		or Path(path).suffix.lower() not in (".webp", ".png", ".jpg", ".jpeg", ".gif", ".avif")
	):
		return ""
	return url


def parse_guide(html: str, number: str) -> dict:
	match = re.search(r'<script\b[^>]*\bid=["\']__NUXT_DATA__["\'][^>]*>(.*?)</script>', html, re.S)
	if not match:
		raise ValueError("缺少任务页面数据")
	table = json.loads(match[1])
	key = "wiki-task-meta-" + number
	ref = next((entry[key] for entry in table if isinstance(entry, dict) and key in entry), None)
	if not isinstance(ref, int) or not 0 <= ref < len(table) or not isinstance(table[ref], dict):
		raise ValueError("任务页编号与内容不符")

	def resolve(index: int, depth: int = 0):
		if type(index) is not int or not 0 <= index < len(table) or depth > 14:
			return None
		node = table[index]
		if isinstance(node, dict):
			return {key: resolve(value, depth + 1) for key, value in node.items()}
		if isinstance(node, list):
			return [resolve(value, depth + 1) for value in node]
		return node

	task = resolve(ref)
	if not task.get("name") and not task.get("localizedName"):
		raise ValueError("缺少任务名称")
	sections = []
	for field, kind in (("tips", "tip"), ("how_to", "howto")):
		for value in task.get(field) or []:
			if isinstance(value, str) and value.strip():
				sections.append({"type": kind, "text": value.strip()})
	for group in task.get("detail") or []:
		if not isinstance(group, dict):
			continue
		images = []
		for remote in group.get("img") or []:
			url = image_url(remote) if isinstance(remote, str) else ""
			if url:
				images.append({"url": url, "local": url.removeprefix(HOME + "/")})
		if images:
			sections.append({"type": "image", "title": group.get("title") or "", "images": images})
	link = task.get("link")
	if isinstance(link, str) and urlsplit(link).scheme in ("http", "https") and urlsplit(link).netloc:
		sections.append({"type": "video", "url": link})
	return {
		"url": DETAIL + number, "english": task.get("name") or "", "title": task.get("localizedName") or "",
		"sections": sections,
	}


class GuideStore:
	def __init__(self, data_store: DataStore) -> None:
		self.data_store = data_store
		self.path = data_store.data_dir / "guides" / "optarkov.json"
		self.image_dir = data_store.data_dir / "guide_images"
		self._lock = threading.RLock()
		self._image_lock = threading.Lock()
		self._local = threading.local()
		self._snapshot = {}
		self._snapshot_key = None
		self._syncing = False
		self.last_result = {}
		self._progress = {}

	def _session(self) -> requests.Session:
		if not hasattr(self._local, "session"):
			self._local.session = requests.Session()
			self._local.session.headers.update(HEADERS)
		return self._local.session

	def _read(self) -> dict:
		with self._lock:
			try:
				info = self.path.stat()
				key = (info.st_mtime_ns, info.st_size, info.st_ino)
				if key != self._snapshot_key:
					value = json.loads(self.path.read_bytes())
					self._snapshot = value if isinstance(value, dict) else {}
					self._snapshot_key = key
				return self._snapshot
			except (OSError, ValueError):
				return {}

	def _write(self, payload: dict) -> None:
		self.path.parent.mkdir(parents=True, exist_ok=True)
		temp = self.path.with_suffix(".json.tmp")
		temp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
		temp.replace(self.path)

	def _fetch(self, url: str) -> str | None:
		for attempt in range(3):
			try:
				response = self._session().get(url, timeout=(6, 20))
				response.raise_for_status()
				return response.content.decode("utf-8-sig")
			except (requests.RequestException, UnicodeError):
				if attempt < 2:
					time.sleep(0.4 * (attempt + 1))
		return None

	def _read_page(self, number: str) -> dict:
		html = self._fetch(DETAIL + number)
		if html is None:
			raise ValueError("任务页请求失败")
		return parse_guide(html, number)

	def _task_names(self) -> tuple[dict, dict, dict, dict]:
		english, variants, localized, wiki_titles = {}, {}, {}, {}
		with self.data_store._lock:
			current = self.data_store.mode
			tasks = dict(self.data_store.tasks)
		for mode in MODE_ORDER:
			if mode == current and tasks:
				continue
			folder = self.data_store.data_dir / mode
			try:
				source = json.loads((folder / "tasks.json").read_bytes())["data"]["tasks"]
			except (OSError, ValueError, KeyError):
				continue
			try:
				names = json.loads((folder / "tasks_zh.json").read_bytes()).get("data") or {}
			except (OSError, ValueError):
				names = {}
			for task_id, task in source.items():
				name = task.get("name")
				tasks.setdefault(task_id, {
					"name": names.get(name) or name, "normalizedName": task.get("normalizedName"),
					"wikiLink": task.get("wikiLink"),
				})
		for task_id, task in tasks.items():
			slug = task.get("normalizedName") or ""
			name = task.get("name") or ""
			if slug:
				english.setdefault(slug, set()).add(task_id)
				base = re.sub(r"-(bear|usec|pve-zone|pvp-zone)$", "", slug)
				if base != slug:
					variants.setdefault(base, set()).add(task_id)
			if name:
				localized.setdefault(name, set()).add(task_id)
			# Wiki 标题保留了部分任务在中文同名时省略的转生阶段。
			link = task.get("wikiLink")
			if isinstance(link, str) and link.startswith("https://escapefromtarkov.fandom.com/wiki/"):
				title = unquote(urlsplit(link).path.removeprefix("/wiki/")).replace("_", " ")
				if title:
					wiki_titles.setdefault(slugify(title), set()).add(task_id)
		return english, variants, localized, wiki_titles

	@staticmethod
	def _available_entry(ref, pages: dict) -> dict | None:
		entry = pages.get(ref) if isinstance(ref, str) else ref
		if not isinstance(entry, dict) or not entry.get("url"):
			return None
		for section in entry.get("sections") or []:
			if not isinstance(section, dict):
				continue
			kind = section.get("type")
			if kind in ("text", "table", "tip", "howto") and (section.get("text") or "").strip():
				return entry
			if kind == "image" and any(
				isinstance(image, dict) and image_url(image.get("local") or image.get("url") or "")
				for image in section.get("images") or []
			):
				return entry
			if kind == "video" and re.match(r"^https?://[^/\s]+", section.get("url") or ""):
				return entry
		return None

	def guided_task_ids(self) -> set[str]:
		payload = self._read()
		pages = payload.get("pages") or {}
		return {task_id for task_id, ref in (payload.get("byTask") or {}).items() if self._available_entry(ref, pages)}

	def get(self, task_id: str) -> list[dict]:
		payload = self._read()
		entry = self._available_entry((payload.get("byTask") or {}).get(task_id), payload.get("pages") or {})
		if entry is None:
			return []
		return [{
			"source": "optarkov", "sourceName": "OPtarkov", "sourceUrl": entry["url"],
			"updatedAt": entry.get("lastmod") or entry.get("updatedAt") or "", "title": entry.get("title") or "",
			"summary": entry.get("summary") or "", "sections": entry.get("sections") or [],
		}]

	def status(self) -> dict:
		with self._lock:
			data = self._read()
			summary = {"name": "OPtarkov", "syncedAt": data.get("syncedAt", ""), "count": len(data.get("byTask") or {})}
			statistics = data.get("statistics") or {}
			summary.update(statistics)
			summary["lastSuccessfulAt"] = data.get("lastSuccessfulAt") or ("" if summary.get("failed") else summary["syncedAt"])
			result = self.last_result or data.get("lastResult") or {}
			if not result and summary["syncedAt"] and statistics:
				ok = not statistics.get("failed")
				progress = {key: statistics.get(key, 0) for key in ("discovered", "skipped", "fetched", "failed")}
				processed = progress["fetched"] + progress["failed"]
				progress.update(stage="done" if ok else "error", processed=processed, total=processed)
				result = {"ok": ok, "finishedAt": summary["syncedAt"], "startedAt": "", "progress": progress,
					"sources": {"optarkov": {"ok": ok, **statistics}}}
			return {
				"sources": {"optarkov": summary}, "intervalSeconds": SYNC_INTERVAL, "syncing": self._syncing,
				"progress": dict(self._progress or result.get("progress") or {}), "lastResult": result,
			}

	def sync(self, force: bool = False) -> dict:
		with self._lock:
			if self._syncing:
				return {"ok": False, "error": "攻略正在同步"}
			self._syncing = True
			started = now_text()
			self._progress = {"stage": "sitemap", "startedAt": started, "total": 0, "processed": 0, "discovered": 0,
				"skipped": 0, "fetched": 0, "failed": 0, "matchProcessed": 0, "matchTotal": 0}
		cache = self._read()
		result = {"ok": False, "sources": {}, "startedAt": started}
		try:
			payload = self._sync_pages(force, cache)
			statistics = payload["statistics"]
			result["ok"] = not statistics["failed"]
			result["sources"]["optarkov"] = {"ok": result["ok"], **statistics}
			if not result["ok"]:
				result["error"] = "部分任务页获取失败，可再次同步以重试"
			result["finishedAt"] = payload["syncedAt"]
			result["progress"] = {**self._progress, "stage": "done" if result["ok"] else "error"}
			if not result["ok"]:
				result["progress"]["failedStage"] = "fetch"
			self._write({**payload, "lastResult": result})
		except Exception as error:
			result.update(ok=False, error=str(error), finishedAt=now_text())
			if "optarkov" in result["sources"]:
				result["sources"]["optarkov"]["ok"] = False
			result["progress"] = {**self._progress, "failedStage": self._progress["stage"], "stage": "error"}
			try:
				self._write({**cache, "lastResult": result})
			except OSError as save_error:
				result["error"] += f"；本次结果保存失败：{save_error}"
		finally:
			with self._lock:
				self.last_result = result
				self._progress = result.get("progress", {})
				self._syncing = False
		return result

	def _sync_pages(self, force: bool, cache: dict) -> dict:
		index = self._fetch(SITEMAP)
		if index is None:
			raise ValueError("OPtarkov 任务站点地图获取失败")
		discovered = sitemap_tasks(index)
		pages = {number: guide for number, guide in (cache.get("pages") or {}).items() if number in discovered}
		retry = {str(page) for page in (cache.get("statistics") or {}).get("failedPages", [])}
		now = time.time()
		pending = []
		for number, modified in discovered.items():
			guide = pages.get(number) or {}
			stale = modified != guide.get("lastmod") if modified else now - guide.get("checked", 0) >= SYNC_INTERVAL
			if force or number in retry or not guide or stale:
				pending.append(number)
		failed = []
		with self._lock:
			self._progress.update(stage="fetch", total=len(pending), discovered=len(discovered), skipped=len(discovered) - len(pending))
		with ThreadPoolExecutor(max_workers=WORKERS) as pool:
			futures = {pool.submit(self._read_page, number): number for number in pending}
			for future in as_completed(futures):
				number = futures[future]
				try:
					guide = future.result()
					pages[number] = {**guide, "lastmod": discovered[number], "checked": now}
				except (OSError, ValueError, TypeError, IndexError, KeyError):
					failed.append(int(number))
				with self._lock:
					self._progress["processed"] += 1
					self._progress["failed"] = len(failed)
					self._progress["fetched"] = self._progress["processed"] - len(failed)

		with self._lock:
			self._progress.update(stage="match", matchTotal=len(pages))
		english, variants, localized, wiki_titles = self._task_names()
		by_task = {}
		ranks = {}
		unmatched = []
		empty = 0
		matched_pages = 0
		for number in sorted(pages, key=int):
			guide = pages[number]
			with self._lock:
				self._progress["matchProcessed"] += 1
			if not guide["sections"]:
				empty += 1
				continue
			slug = slugify(guide["english"])
			targets = english.get(slug) or variants.get(slug)
			rank = 2 if slug in english else 1
			if not targets:
				names = localized.get(guide["title"], set())
				targets = names if len(names) == 1 else set()
				rank = 0
			if not targets and slug:
				wiki_ids = wiki_titles.get(slug, set())
				targets = wiki_ids if len(wiki_ids) == 1 else set()
				rank = -1
			if targets:
				matched_pages += 1
				for task_id in targets:
					if task_id not in ranks or rank > ranks[task_id]:
						by_task[task_id] = number
						ranks[task_id] = rank
			else:
				unmatched.append(int(number))
		# 早期缓存把攻略直接放在任务索引里。源页刷新失败时继续提供原有内容。
		failed_urls = {DETAIL + str(number) for number in failed}
		for task_id, entry in (cache.get("byTask") or {}).items():
			if isinstance(entry, dict) and (entry.get("url") or "").rstrip("/") in failed_urls:
				by_task.setdefault(task_id, entry)
		statistics = {
			"discovered": len(discovered), "fetched": len(pending) - len(failed),
			"skipped": len(discovered) - len(pending), "failed": len(failed), "failedPages": sorted(failed),
			"total": len(by_task), "matched": len(by_task), "matchedPages": matched_pages, "unmatched": len(unmatched),
			"unmatchedPages": unmatched, "empty": empty, "cached": len(pages),
		}
		stamp = now_text()
		previous_success = cache.get("lastSuccessfulAt") or ("" if (cache.get("statistics") or {}).get("failed") else cache.get("syncedAt", ""))
		with self._lock:
			self._progress["stage"] = "save"
		return {"syncedAt": stamp, "lastSuccessfulAt": previous_success if failed else stamp,
			"byTask": by_task, "pages": pages, "statistics": statistics}

	def image_path(self, remote: str) -> Path:
		url = image_url(remote)
		name = hashlib.sha256(url.encode()).hexdigest()
		return self.image_dir / (name + Path(urlsplit(url).path).suffix.lower())

	def fetch_image(self, remote: str) -> Path | None:
		url = image_url(remote)
		if not url:
			return None
		target = self.image_path(url)
		with self._image_lock:
			if target.is_file():
				return target
			try:
				response = self._session().get(url, timeout=(6, 30))
				response.raise_for_status()
				if not response.headers.get("Content-Type", "").startswith("image/") or not response.content:
					return None
				target.parent.mkdir(parents=True, exist_ok=True)
				temp = target.with_suffix(".tmp")
				temp.write_bytes(response.content)
				temp.replace(target)
				return target
			except (OSError, requests.RequestException):
				return None

	def start_scheduler(self) -> None:
		return
