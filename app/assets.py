from __future__ import annotations

from pathlib import Path

from .remotecache import RemoteCache

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
		self.cache = RemoteCache(icon_dir, timeout=8.0, headers=ASSET_HEADERS)

	def local_path(self, item_id: str) -> Path:
		return self.icon_dir / f"{item_id}.webp"

	def get(self, item_id: str, remote_url: str) -> tuple[bytes, str] | None:
		target = self.cache.fetch_path(self.local_path(item_id), remote_url)
		if target is None:
			return None
		try:
			payload = target.read_bytes()
		except OSError:
			return None
		return payload, _content_types.get(target.suffix, "image/webp")


class SvgCache:
	"""地图矢量图本地缓存，下载一次后离线可用。"""

	def __init__(self, cache_dir: Path) -> None:
		self.cache_dir = cache_dir
		self.cache = RemoteCache(cache_dir, timeout=20.0, headers=ASSET_HEADERS)
		self._text: dict[str, str] = {}

	def local_path(self, key: str) -> Path:
		return self.cache_dir / f"map-{key}.svg"

	def get(self, key: str, remote_url: str) -> str | None:
		if not key or not remote_url:
			return None
		cached = self._text.get(key)
		if cached is not None:
			return cached
		text = self.cache.fetch_text(self.local_path(key), remote_url)
		if text:
			self._text[key] = text
		return text
