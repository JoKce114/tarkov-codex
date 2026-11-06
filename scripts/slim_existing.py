"""把已下载的数据和出厂数据精简一遍，减小体积和加载内存。

用法：python scripts/slim_existing.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import slim

TARGETS = [
	("data", ("pve", "regular", "pvp-season")),
	("app/seed", ("pve", "regular", "pvp-season")),
]

KEYS = ("items", "maps", "tasks")


def process(path: Path, key: str) -> tuple[int, int]:
	if not path.exists():
		return 0, 0
	before = path.stat().st_size
	try:
		payload = json.loads(path.read_text(encoding="utf-8"))
	except (OSError, ValueError):
		return before, before
	payload = slim.apply(key, payload)
	text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
	path.write_text(text, encoding="utf-8")
	return before, path.stat().st_size


def main() -> None:
	total_before = 0
	total_after = 0
	for base, modes in TARGETS:
		for mode in modes:
			folder = ROOT / base / mode
			for key in KEYS:
				before, after = process(folder / f"{key}.json", key)
				if before:
					total_before += before
					total_after += after
					print(f"{base}/{mode}/{key}.json  {before/1048576:6.1f} MB -> {after/1048576:6.1f} MB")
	print()
	print(f"合计: {total_before/1048576:.0f} MB -> {total_after/1048576:.0f} MB")


if __name__ == "__main__":
	main()
