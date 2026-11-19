from unittest.mock import Mock

from app.assets import IconCache


def test_cold_start_and_offline_read(tmp_path):
	cache = IconCache(tmp_path / "new" / "icons")
	payload = b"\x89PNG\r\n\x1a\n" + bytes(20)
	cache._session.get = Mock(return_value=Mock(status_code=200, content=payload, headers={"Content-Type": "image/png"}))
	assert cache.get("trader-demo", "https://example.test/image") == (payload, "image/png")
	assert cache.get("trader-demo", "") == (payload, "image/png")
	assert cache._session.get.call_count == 1


def test_valid_image_survives_unwritable_cache(tmp_path):
	blocker = tmp_path / "file"
	blocker.write_bytes(b"already here")
	cache = IconCache(blocker / "icons")
	payload = b"RIFF\x14\x00\x00\x00WEBP" + bytes(16)
	cache._session.get = Mock(return_value=Mock(status_code=200, content=payload, headers={"Content-Type": "image/webp"}))
	assert cache.get("task-demo", "https://example.test/image") == (payload, "image/webp")
