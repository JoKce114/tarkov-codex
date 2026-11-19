"""刷新打包用的出厂数据：把三种游戏模式的全部数据集下载到 app/seed 下。

用法：python -m scripts.build_seed [mode ...]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.datasets import API_BASE, DATASETS, DATASET_KEYS, LANG, MODE_ORDER, file_name, translation_file_name, translation_dataset_key
from app.sync import slim_payload

HEADERS = {
	"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
	"Referer": "https://tarkov.dev/",
	"Accept": "application/json",
}

SEED_DIR = ROOT / "app" / "seed"
TIMEOUT = 180
RETRY = 3


def fetch(url: str) -> bytes | None:
	last = None
	for attempt in range(RETRY):
		try:
			response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
			if response.status_code == 200:
				return response.content
			if response.status_code == 404:
				return None
			last = f"HTTP {response.status_code}"
		except requests.RequestException as error:
			last = str(error)
		if attempt < RETRY - 1:
			time.sleep(5)
	raise RuntimeError(f"{url} 失败：{last}")


def main(modes: list[str]) -> None:
	for mode in modes:
		target_dir = SEED_DIR / mode
		target_dir.mkdir(parents=True, exist_ok=True)
		total = 0
		for key in DATASET_KEYS:
			spec = DATASETS[key]
			payload = fetch(f"{API_BASE}/{mode}/{spec['path']}")
			if payload:
				if key == "maps":
					payload = slim_payload(key, payload, target_dir)
				(target_dir / file_name(key)).write_bytes(payload)
				total += len(payload)
				print(f"  {key:10s} {len(payload):>10,} B")
			if spec["translated"]:
				table = fetch(f"{API_BASE}/{mode}/{spec['path']}_{LANG}")
				if table:
					(target_dir / translation_file_name(key)).write_bytes(table)
					total += len(table)
					print(f"  {key + '_zh':10s} {len(table):>10,} B")
		print(f"[{mode}] 合计 {total / 1048576:.1f} MB -> {target_dir}")


if __name__ == "__main__":
	argument_modes = sys.argv[1:] or list(MODE_ORDER)
	main(argument_modes)
