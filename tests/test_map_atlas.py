from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import paths
from app.api import create_app
from app.mapconfig import MapConfig
from app.maps import build_map_detail, build_map_summary
from app.progress import ProgressStore
from app.remotecache import RemoteCache
from app.store import DataStore


def test_chinese_maps_for_all_locations_and_variants(tmp_path):
	config = MapConfig()
	store = DataStore(tmp_path)
	groups = {
		"factory": 1, "customs": 2, "woods": 2, "lighthouse": 1, "shoreline": 2, "reserve": 1,
		"interchange": 1, "streets-of-tarkov": 1, "the-lab": 2, "ground-zero": 1,
		"terminal": 1, "the-labyrinth": 1, "icebreaker": 1,
	}
	for slug, count in groups.items():
		store.maps[slug] = {"normalizedName": slug}
		summary = build_map_summary(store, slug, config)
		detail = build_map_detail(store, slug, config)
		pictures = detail["images"][:count]
		assert len(pictures) == count
		assert all(image["url"].startswith("https://assets.tarkovbox.com/") for image in pictures)
		assert len({image["originalUrl"] for image in pictures}) == count
		assert summary["previewUrl"] == pictures[0]["url"]
		assert summary["originalUrl"] == pictures[0]["originalUrl"]
	for alias, base in (("ground-zero-21", "ground-zero"), ("night-factory", "factory"), ("infected-lab", "the-lab")):
		store.maps[alias] = {"normalizedName": alias}
		assert build_map_summary(store, alias, config)["originalUrl"] == build_map_summary(store, base, config)["originalUrl"]


def test_cached_atlas_routes_and_system_viewer(tmp_path, monkeypatch):
	monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
	monkeypatch.setattr(paths, "CACHE_DIR", tmp_path / "cache")
	store = DataStore(tmp_path)
	store.maps["ground-zero"] = {"normalizedName": "ground-zero"}
	app = create_app(SimpleNamespace(current=store), ProgressStore(tmp_path / "progress.json"), auto_update=False)
	client = TestClient(app)
	entry, = client.get("/api/game-maps").json()["maps"]
	image = client.get("/api/game-maps/ground-zero").json()["map"]["images"][0]
	assert entry["originalUrl"] == image["originalUrl"]
	folder = tmp_path / "maps" / "images"
	folder.mkdir(parents=True)
	preview = folder / Path(entry["previewUrl"]).name
	original = folder / Path(entry["originalUrl"]).name
	preview.write_bytes(b"jpeg preview")
	original.write_bytes(b"webp original")
	monkeypatch.setattr(RemoteCache, "_session", lambda self: pytest.fail("unexpected download"))
	opened = []
	monkeypatch.setattr("os.startfile", opened.append, raising=False)
	for url, path, mime in ((entry["previewUrl"], preview, "image/jpeg"), (entry["originalUrl"], original, "image/webp")):
		response = client.get("/api/game-map/image", params={"url": url})
		assert response.content == path.read_bytes()
		assert response.headers["content-type"] == mime
	assert client.post("/api/open-file", json={"url": entry["originalUrl"]}).json()["ok"]
	assert opened == [str(original)]
	for unknown in ("https://example.invalid/map.webp", str(original)):
		assert client.get("/api/game-map/image", params={"url": unknown}).status_code == 404
		assert client.post("/api/open-file", json={"url": unknown}).status_code == 404


def test_static_map_viewer_opens_selected_original_and_falls_back_to_preview():
	playwright = pytest.importorskip("playwright.sync_api")
	web = Path(__file__).resolve().parents[1] / "web"
	with playwright.sync_playwright() as runtime:
		browser = runtime.chromium.launch()
		page = browser.new_page()
		page.route("http://map.test/**", lambda route: route.fulfill(json={}))
		page.route("http://map.test/", lambda route: route.fulfill(path=web / "index.html"))
		page.route("**/app.js?*", lambda route: route.fulfill(path=web / "app.js"))
		page.route("**/style.css?*", lambda route: route.fulfill(path=web / "style.css"))
		page.route("**/api/game-map/image?*", lambda route: route.fulfill(
			content_type="image/svg+xml", body='<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100"/>'))
		page.goto("http://map.test/")
		page.evaluate("""() => {
			setupMapViewer();
			state.currentMapOriginal = "different-map.webp";
			renderQuickMapList([{name: "中心区", previewUrl: "preview.jpg", originalUrl: "original.webp"}]);
			document.querySelector(".quick_map_item").click();
		}""")
		viewer = page.locator("#viewer_image")
		assert viewer.get_attribute("src").endswith("url=original.webp")
		with page.expect_request(lambda request: request.url.endswith("/api/open-file")) as opened:
			page.locator("#viewer_external").dispatch_event("click")
		assert opened.value.post_data_json == {"url": "original.webp"}
		page.route("**/api/game-map/image?url=missing.webp", lambda route: route.fulfill(status=404))
		page.evaluate('openMapViewer("missing.webp", "中心区", "preview.jpg")')
		page.wait_for_function('viewer.sourceUrl === "preview.jpg" && document.querySelector("#viewer_image").naturalWidth > 0')
		assert "预览" in page.locator("#viewer_title").inner_text()
		browser.close()


def test_map_picker_and_home_count_hide_only_ground_zero_tutorial(tmp_path):
	store = DataStore(tmp_path)
	store.maps = {
		"base": {"normalizedName": "ground-zero", "name": "中心区"},
		"training": {"normalizedName": "ground-zero-tutorial", "name": "新手教程"},
		"veteran": {"normalizedName": "ground-zero-21", "name": "中心区 21+"},
	}
	app = create_app(SimpleNamespace(current=store), ProgressStore(tmp_path / "progress.json"), auto_update=False)
	client = TestClient(app)
	entries = client.get("/api/game-maps").json()["maps"]
	assert [entry["slug"] for entry in entries] == ["ground-zero", "ground-zero-21"]
	assert client.get("/api/stats").json()["counts"]["maps"] == len(entries)
