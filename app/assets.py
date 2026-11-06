from __future__ import annotations

import threading
from pathlib import Path

import requests

ASSET_HEADERS = {
	"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
	"Referer": "https://tarkov.dev/",
	"Accept": "image/avif,image/webp,image/png,*/*",
}

_content_types = {
	".webp": "image/webp",
	".png": "image/png",
	".jpg": "image/jpeg",
	".svg": "image/svg+xml",
}


class IconCache:
	def __init__(self, icon_dir: Path) -> None:
		self.icon_dir = icon_dir
		self._session = requests.Session()
		self._session.headers.update(ASSET_HEADERS)
		self._lock = threading.Lock()

	def local_path(self, item_id: str) -> Path:
		return self.icon_dir / f"{item_id}.webp"

	def get(self, item_id: str, remote_url: str) -> tuple[bytes, str] | None:
		target = self.local_path(item_id)
		if target.exists():
			return target.read_bytes(), _content_types.get(target.suffix, "image/webp")
		if not remote_url:
			return None
		with self._lock:
			try:
				response = self._session.get(remote_url, timeout=20)
				if response.status_code != 200 or not response.content:
					return None
				target.write_bytes(response.content)
				return response.content, response.headers.get("Content-Type", "image/webp")
			except requests.RequestException:
				return None


class SvgCache:
	"""地图矢量图本地缓存，下载一次后离线可用。"""

	def __init__(self, cache_dir: Path) -> None:
		self.cache_dir = cache_dir
		self._session = requests.Session()
		self._session.headers.update(ASSET_HEADERS)
		self._lock = threading.Lock()

	def get(self, key: str, remote_url: str) -> str | None:
		if not key or not remote_url:
			return None
		target = self.cache_dir / f"map-{key}.svg"
		if target.exists():
			try:
				return target.read_text(encoding="utf-8")
			except OSError:
				return None
		with self._lock:
			try:
				response = self._session.get(remote_url, timeout=60)
				if response.status_code != 200 or not response.text:
					return None
				target.parent.mkdir(parents=True, exist_ok=True)
				target.write_text(response.text, encoding="utf-8")
				return response.text
			except (requests.RequestException, OSError):
				return None
