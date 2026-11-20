from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")
WEB_DIR = Path(__file__).resolve().parents[1] / "web"


@pytest.mark.parametrize("dimensions", ["", 'width="180" height="240"'], ids=["viewbox-only", "fixed-size"])
def test_task_map_and_marker_share_visible_bounds(dimensions):
	svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-20 35 180 240" {dimensions}><rect width="180" height="240" fill="green"/></svg>'
	with playwright.sync_playwright() as runtime:
		browser = runtime.chromium.launch()
		page = browser.new_page()
		page.route("http://map.test/**", lambda route: route.abort())
		page.route("http://map.test/", lambda route: route.fulfill(path=WEB_DIR / "index.html"))
		page.route("**/app.js*", lambda route: route.fulfill(path=WEB_DIR / "app.js"))
		page.route("**/style.css*", lambda route: route.fulfill(path=WEB_DIR / "style.css"))
		page.route("**/api/map/svg/sample", lambda route: route.fulfill(content_type="image/svg+xml", body=svg))
		page.goto("http://map.test/")
		page.evaluate("""() => {
			const group = { mapKey: "sample", mapName: "地图", width: 180, height: 240, originX: -20, originY: 35, points: [{ x: 45, y: 180, label: "目标" }] };
			document.body.replaceChildren(renderMapBlock(group));
		}""")
		marker = page.locator(".map_dot")
		marker.wait_for(state="attached")
		for button in (None, "放大", "重置视图"):
			if button:
				page.get_by_title(button, exact=True).click()
			bounds = page.locator(".task_map_image").bounding_box()
			assert bounds and min(bounds["width"], bounds["height"]) > 0
			point = marker.bounding_box()
			assert point
			for axis, length, fraction in (("x", "width", 0.25), ("y", "height", 0.75)):
				center = point[axis] + point[length] / 2
				assert center == pytest.approx(bounds[axis] + bounds[length] * fraction, abs=1)
		browser.close()

def test_unavailable_original_falls_back_to_selected_preview():
	with playwright.sync_playwright() as runtime:
		browser = runtime.chromium.launch()
		page = browser.new_page()
		page.route("http://map.test/**", lambda route: route.abort())
		page.route("http://map.test/", lambda route: route.fulfill(path=WEB_DIR / "index.html"))
		page.route("**/app.js", lambda route: route.fulfill(path=WEB_DIR / "app.js"))
		page.route("**/api/game-map/image?url=original.webp", lambda route: route.fulfill(status=404))
		page.route("**/api/game-map/image?url=preview.jpg", lambda route: route.fulfill(
			content_type="image/svg+xml", body='<svg xmlns="http://www.w3.org/2000/svg" width="40" height="50"/>'))
		page.goto("http://map.test/")
		page.evaluate('openMapViewer("original.webp", "海关", "preview.jpg")')
		page.wait_for_function('viewer.sourceUrl === "preview.jpg" && document.querySelector("#viewer_image").naturalWidth === 40')
		assert "预览图" in page.locator("#viewer_title").inner_text()
		browser.close()
