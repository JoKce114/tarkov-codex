"""生成打包用的补充出厂数据：地图点位、预览图、攻略、激活码。

只打包预览图（约 3MB），原图按需下载，避免 exe 膨胀。

用法：python scripts/build_extra_seed.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.datasets import MODE_ORDER
SOURCE = ROOT / "data"
TARGET = ROOT / "app" / "seed"


def copy_file(relative: str) -> bool:
	source = SOURCE / relative
	if not source.exists():
		return False
	target = TARGET / relative
	target.parent.mkdir(parents=True, exist_ok=True)
	shutil.copy2(source, target)
	return True


def main() -> None:
	copied = []

	# 地图点位数据
	for mode in MODE_ORDER:
		relative = f"maps/{mode}/maps.json"
		if copy_file(relative):
			copied.append(relative)

	# 地图预览图（原图不打包，按需下载）
	preview_dir = SOURCE / "maps" / "images"
	target_dir = TARGET / "maps" / "images"
	target_dir.mkdir(parents=True, exist_ok=True)
	count = 0
	if preview_dir.is_dir():
		for image in preview_dir.glob("*_thumb.jpg"):
			shutil.copy2(image, target_dir / image.name)
			count += 1
	copied.append(f"maps/images ({count} 张)")

	# 攻略
	if copy_file("guides/optarkov.json"):
		copied.append("guides/optarkov.json")

	# 攻略截图
	guide_images = SOURCE / "guide_images"
	if guide_images.is_dir():
		target = TARGET / "guide_images"
		target.mkdir(parents=True, exist_ok=True)
		n = 0
		for image in guide_images.iterdir():
			if image.is_file():
				shutil.copy2(image, target / image.name)
				n += 1
		copied.append(f"guide_images ({n} 张)")

	# 激活码
	if copy_file("cdk.json"):
		copied.append("cdk.json")

	print("已加入出厂数据:")
	for item in copied:
		print("  -", item)

	total = sum(f.stat().st_size for f in TARGET.rglob("*") if f.is_file())
	print(f"\n出厂数据总体积: {total / 1048576:.0f} MB")


if __name__ == "__main__":
	main()
