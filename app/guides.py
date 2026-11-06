from __future__ import annotations

"""抓取任务攻略。

两个来源：
- tarkovbox：任务详情页内嵌 Nuxt 数据，按 slug 或英文名匹配
- optarkov：任务详情页内嵌 Nuxt 数据，附带中文标注的实景截图
"""

import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path

import requests

from .paths import DATA_DIR

GUIDE_DIR = DATA_DIR / "guides"
IMAGE_DIR = DATA_DIR / "guide_images"
SYNC_INTERVAL = 7 * 24 * 60 * 60
TIMEOUT = 40
RETRY = 3

HEADERS = {
	"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
	"Accept-Language": "zh-CN,zh;q=0.9",
}

SOURCES = {
	"tarkovbox": {
		"name": "TarkovBox",
		"home": "https://www.tarkovbox.com/gamewiki/tasks",
		"detail": "https://www.tarkovbox.com/gamewiki/tasks/{slug}",
	},
	"optarkov": {
		"name": "OPtarkov",
		"home": "https://www.optarkov.com/tasks",
		"detail": "https://www.optarkov.com/wiki/task/{id}",
	},
}


def now_text() -> str:
	return datetime.now().isoformat(timespec="seconds")


def slugify(text: str) -> str:
	text = (text or "").lower().replace("'", "").replace("’", "")
	text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
	return text


def strip_tags(text: str) -> str:
	text = re.sub(r"<[^>]+>", " ", text or "")
	text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
	return re.sub(r"[ \t]+", " ", text).strip()


def deref(data: list, value, depth: int = 0, seen: frozenset | None = None):
	"""Nuxt 载荷用索引互相引用，逐层解开。"""
	if seen is None:
		seen = frozenset()
	if depth > 14:
		return value
	if isinstance(value, int):
		if value in seen or not (0 <= value < len(data)):
			return None
		return deref(data, data[value], depth + 1, seen | {value})
	if isinstance(value, list):
		if len(value) == 2 and isinstance(value[0], str) and value[0].endswith("Reactive"):
			return deref(data, value[1], depth + 1, seen)
		return [deref(data, item, depth + 1, seen) for item in value]
	if isinstance(value, dict):
		return {key: deref(data, item, depth + 1, seen) for key, item in value.items()}
	return value


def read_nuxt(source: str) -> list | None:
	start = source.find('id="__NUXT_DATA__"')
	if start == -1:
		return None
	chunk_start = source.find(">", start) + 1
	chunk_end = source.find("</script>", chunk_start)
	if chunk_end == -1:
		return None
	try:
		return json.loads(source[chunk_start:chunk_end])
	except ValueError:
		return None


class GuideStore:
	def __init__(self, data_store) -> None:
		self.data_store = data_store
		self._lock = threading.RLock()
		self._session = requests.Session()
		self._session.headers.update(HEADERS)
		self._image_lock = threading.Lock()
		self._syncing = False
		self.last_result: dict = {}
		GUIDE_DIR.mkdir(parents=True, exist_ok=True)
		IMAGE_DIR.mkdir(parents=True, exist_ok=True)

	def _guide_path(self, source: str) -> Path:
		return GUIDE_DIR / f"{source}.json"

	def _read(self, source: str) -> dict:
		try:
			data = json.loads(self._guide_path(source).read_text(encoding="utf-8"))
			return data if isinstance(data, dict) else {}
		except (OSError, ValueError):
			return {}

	def _write(self, source: str, payload: dict) -> None:
		target = self._guide_path(source)
		tmp = target.with_suffix(".json.tmp")
		tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
		tmp.replace(target)

	ORDER = ("optarkov", "tarkovbox")

	def get(self, task_id: str) -> list[dict]:
		"""按任务 ID 取两家来源的攻略，OPtarkov 排在前。"""
		result = []
		for source in self.ORDER:
			meta = SOURCES[source]
			payload = self._read(source)
			entry = (payload.get("byTask") or {}).get(task_id)
			if not entry:
				continue
			result.append(
				{
					"source": source,
					"sourceName": meta["name"],
					"sourceUrl": entry.get("url") or meta["home"],
					"updatedAt": entry.get("updatedAt") or "",
					"title": entry.get("title") or "",
					"summary": entry.get("summary") or "",
					"sections": entry.get("sections") or [],
				}
			)
		return result

	def status(self) -> dict:
		with self._lock:
			summary = {}
			for source, meta in SOURCES.items():
				payload = self._read(source)
				summary[source] = {
					"name": meta["name"],
					"syncedAt": payload.get("syncedAt") or "",
					"count": len(payload.get("byTask") or {}),
				}
			return {"sources": summary, "intervalSeconds": SYNC_INTERVAL, "syncing": self._syncing, "lastResult": self.last_result}

	def _fetch(self, url: str) -> str | None:
		for attempt in range(RETRY):
			try:
				response = self._session.get(url, timeout=TIMEOUT)
				if response.status_code == 200:
					return response.text
			except requests.RequestException:
				pass
			if attempt < RETRY - 1:
				time.sleep(3)
		return None

	# ---------- TarkovBox ----------

	def _tarkovbox_index(self) -> list[dict]:
		cards = []
		pattern = re.compile(
			r'href="/gamewiki/tasks/([a-z0-9-]+)"[\s\S]*?'
			r'<p class="quest-card__secondary"[^>]*>([^<]*)</p>'
		)
		traders = (
			"prapor", "therapist", "fence", "skier", "peacekeeper", "mechanic",
			"ragman", "jaeger", "lightkeeper", "ref", "btr-driver",
		)
		for trader in traders:
			html = self._fetch(f"https://www.tarkovbox.com/gamewiki/tasks/traders/{trader}")
			if not html:
				continue
			for slug, english in pattern.findall(html):
				if slug in ("relations", "collector-items"):
					continue
				cards.append({"slug": slug, "english": english.strip()})
			time.sleep(0.3)
		seen = {}
		for card in cards:
			seen.setdefault(card["slug"], card)
		return list(seen.values())

	def _tarkovbox_guide(self, card: dict) -> dict | None:
		html = self._fetch(SOURCES["tarkovbox"]["detail"].format(slug=card["slug"]))
		if not html:
			return None
		data = read_nuxt(html)
		if not data:
			return None
		root = deref(data, 1)
		if not isinstance(root, dict):
			return None
		inner = root.get("data") or {}
		if isinstance(inner, list):
			inner = inner[0] if inner else {}
		if not isinstance(inner, dict):
			return None

		for ref in inner.values():
			detail = deref(data, ref)
			if not isinstance(detail, dict):
				continue
			body = deref(data, detail.get("data"))
			if not isinstance(body, dict):
				continue
			guide = body.get("guide")
			if not isinstance(guide, dict):
				continue
			sections = []
			for section in guide.get("sections") or []:
				if not isinstance(section, dict):
					continue
				content = section.get("contentZh") or section.get("content") or ""
				kind = section.get("sectionType") or "text"
				if kind == "text":
					text = strip_tags(content)
					if text:
						sections.append({"type": "text", "text": text})
				elif kind == "table":
					text = strip_tags(content)
					if text:
						sections.append({"type": "table", "text": text})
			if not sections:
				continue
			return {
				"url": SOURCES["tarkovbox"]["detail"].format(slug=card["slug"]),
				"title": guide.get("titleZh") or guide.get("title") or "",
				"summary": strip_tags(guide.get("summaryZh") or guide.get("summary") or ""),
				"updatedAt": guide.get("updatedAt") or "",
				"sections": sections,
			}
		return None

	# ---------- OPtarkov ----------

	def _optarkov_guide(self, task_number: int) -> dict | None:
		html = self._fetch(SOURCES["optarkov"]["detail"].format(id=task_number))
		if not html:
			return None
		data = read_nuxt(html)
		if not data:
			return None
		root = deref(data, 1)
		if not isinstance(root, dict):
			return None
		inner = root.get("data") or {}
		if isinstance(inner, list):
			inner = inner[0] if inner else {}
		if not isinstance(inner, dict):
			return None

		for ref in inner.values():
			task = deref(data, ref)
			if not isinstance(task, dict):
				continue
			english = task.get("name") or ""
			localized = task.get("localizedName") or ""
			if not english:
				continue
			sections = []
			for tip in task.get("tips") or []:
				if isinstance(tip, str) and tip.strip():
					sections.append({"type": "tip", "text": tip.strip()})
			for how in task.get("how_to") or []:
				if isinstance(how, str) and how.strip():
					sections.append({"type": "howto", "text": how.strip()})
			for group in task.get("detail") or []:
				if not isinstance(group, dict):
					continue
				title = group.get("title") or ""
				images = [
					{"url": f"https://www.optarkov.com/{path}", "local": path}
					for path in (group.get("img") or [])
					if isinstance(path, str)
				]
				if images:
					sections.append({"type": "image", "title": title, "images": images})
			if task.get("link"):
				sections.append({"type": "video", "url": task["link"]})
			if not sections:
				continue
			return {
				"url": SOURCES["optarkov"]["detail"].format(id=task_number),
				"title": localized,
				"english": english,
				"updatedAt": "",
				"sections": sections,
			}
		return None

	# ---------- 同步 ----------

	def sync(self, force: bool = False) -> dict:
		with self._lock:
			if self._syncing:
				return {"ok": False, "error": "正在同步"}
			self._syncing = True

		result = {"ok": True, "sources": {}}
		try:
			result["sources"]["tarkovbox"] = self._sync_tarkovbox(force)
			result["sources"]["optarkov"] = self._sync_optarkov(force)
		finally:
			self._syncing = False

		self.last_result = {**result, "finishedAt": now_text()}
		return self.last_result

	def _by_english(self) -> dict[str, str]:
		mapping = {}
		for task_id, task in self.data_store.tasks.items():
			name = task.get("normalizedName")
			if name:
				mapping[name] = task_id
		return mapping

	def _sync_tarkovbox(self, force: bool) -> dict:
		cards = self._tarkovbox_index()
		previous = self._read("tarkovbox")
		by_task = {} if force else dict(previous.get("byTask") or {})
		by_english = self._by_english()

		added = 0
		for card in cards:
			task_id = by_english.get(card["slug"]) or by_english.get(slugify(card["english"]))
			if not task_id:
				continue
			if task_id in by_task:
				continue
			guide = self._tarkovbox_guide(card)
			time.sleep(0.3)
			if not guide:
				continue
			by_task[task_id] = guide
			added += 1

		payload = {"syncedAt": now_text(), "byTask": by_task}
		self._write("tarkovbox", payload)
		return {"ok": True, "total": len(by_task), "added": added}

	def _sync_optarkov(self, force: bool) -> dict:
		previous = self._read("optarkov")
		by_task = {} if force else dict(previous.get("byTask") or {})
		by_english = self._by_english()
		known = set(by_task)

		added = 0
		empty_streak = 0
		for number in range(1, 520):
			if empty_streak >= 8:
				break
			guide = self._optarkov_guide(number)
			time.sleep(0.3)
			if not guide:
				empty_streak += 1
				continue
			empty_streak = 0
			task_id = by_english.get(slugify(guide.get("english")))
			if not task_id or task_id in known:
				continue
			by_task[task_id] = guide
			known.add(task_id)
			added += 1

		payload = {"syncedAt": now_text(), "byTask": by_task}
		self._write("optarkov", payload)
		return {"ok": True, "total": len(by_task), "added": added}

	def image_path(self, remote: str) -> Path:
		safe = re.sub(r"[^a-zA-Z0-9/_.-]", "_", remote)
		return IMAGE_DIR / re.sub(r"[/]", "__", safe)

	def fetch_image(self, remote: str) -> Path | None:
		target = self.image_path(remote)
		if target.exists():
			return target
		url = remote if remote.startswith("http") else f"https://www.optarkov.com/{remote}"
		with self._image_lock:
			try:
				response = self._session.get(url, timeout=TIMEOUT)
				if response.status_code != 200 or not response.content:
					return None
				target.parent.mkdir(parents=True, exist_ok=True)
				target.write_bytes(response.content)
				return target
			except (requests.RequestException, OSError):
				return None

	def start_scheduler(self) -> None:
		"""保留接口但不再自动运行；同步统一由界面按钮触发。"""
		return
