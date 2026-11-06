"""补全已缓存地图数据的原图地址，避免重新抓一遍网页。"""

import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CONFIG_URL = "https://www.tarkovbox.com/gamewiki/maps/{slug}"


def read_nuxt(source: str):
	start = source.find('id="__NUXT_DATA__"')
	if start == -1:
		return None
	a = source.find(">", start) + 1
	b = source.find("</script>", a)
	try:
		return json.loads(source[a:b])
	except ValueError:
		return None


def main():
	import requests

	from app.maps import Table

	path = "data/maps/maps.json"
	payload = json.load(io.open(path, encoding="utf-8"))
	headers = {
		"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
		"(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
		"Accept-Language": "zh-CN,zh;q=0.9",
	}
	session = requests.Session()
	session.headers.update(headers)

	total = 0
	for entry in payload["maps"]:
		slug = entry.get("slug")
		if not slug:
			continue
		response = session.get(CONFIG_URL.format(slug=slug), timeout=40)
		data = read_nuxt(response.text)
		if not data:
			print(f"{slug}: 解析失败")
			continue
		table = Table(data)
		body = table.value(6)
		if not isinstance(body, dict):
			continue
		images = table.rows(body.get("images"))
		remap = {}
		for image in images:
			preview = image.get("previewUrl") or ""
			original = image.get("url") or image.get("assetUrl") or preview
			if preview:
				remap[preview] = original
		for image in entry.get("images") or []:
			preview = image.get("previewUrl") or image.get("url") or ""
			original = remap.get(preview, "")
			image["previewUrl"] = preview
			image["originalUrl"] = original or preview
			if original:
				total += 1

	io.open(path, "w", encoding="utf-8").write(json.dumps(payload, ensure_ascii=False, indent=1))
	print("已补全原图地址:", total)


if __name__ == "__main__":
	main()
