"""用 tarkov.dev 地图目录修复每种模式已缓存的地图图片索引。"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.datasets import MODE_ORDER
from app.maps import MapStore


def main() -> None:
	maps = MapStore()
	for mode in MODE_ORDER:
		target = maps.root / mode / "maps.json"
		if not target.is_file():
			continue
		payload = json.loads(target.read_bytes())
		count = 0
		for entry in payload.get("maps") or []:
			slug = entry.get("slug") or ""
			record = maps.config.entry_by_normalized(slug)
			images = maps.catalog.get(record["normalized"] if record else slug) or []
			entry["images"] = images
			entry["previewUrl"] = images[0]["previewUrl"] if images else ""
			count += len(images)
		temp = target.with_suffix(".repair.tmp")
		temp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
		temp.replace(target)
		print(f"{mode} 已更新 {count} 个地图图片索引")


if __name__ == "__main__":
	main()
