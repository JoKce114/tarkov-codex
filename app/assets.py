from __future__ import annotations

import logging
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
		self._locks = [threading.Lock() for _ in range(24)]

	def local_path(self, item_id: str) -> Path:
		return self.icon_dir / f"{item_id}.webp"

	def get(self, item_id: str, remote_url: str) -> tuple[bytes, str] | None:
		target = self.local_path(item_id)
		with self._locks[hash(item_id) % len(self._locks)]:
			try:
				payload = target.read_bytes()
				media = self._media_type(payload)
				if media:
					return payload, media
			except OSError:
				pass
			if not remote_url:
				return None
			try:
				response = self._session.get(remote_url, timeout=20)
			except requests.RequestException:
				return None
			media = self._media_type(response.content)
			if response.status_code != 200 or not media:
				return None
			try:
				target.parent.mkdir(parents=True, exist_ok=True)
				tmp = target.with_suffix(".part")
				tmp.write_bytes(response.content)
				tmp.replace(target)
			except OSError:
				logging.getLogger(__name__).warning("无法保存图片 %s", target, exc_info=True)
			return response.content, media

	@staticmethod
	def _media_type(payload: bytes) -> str:
		if payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
			return "image/webp"
		if payload.startswith(b"\x89PNG\r\n\x1a\n"):
			return "image/png"
		if payload.startswith(b"\xff\xd8\xff"):
			return "image/jpeg"
		if payload.startswith((b"GIF87a", b"GIF89a")):
			return "image/gif"
		if payload[4:8] == b"ftyp" and payload[8:12] in (b"avif", b"avis"):
			return "image/avif"
		return ""


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
