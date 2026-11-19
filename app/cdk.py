from __future__ import annotations

"""从 OPtarkov 抓取激活码（CDK）信息。"""

import json
import threading
from datetime import datetime
from pathlib import Path

import requests

from .paths import DATA_DIR

HEADERS = {
	"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
	"Referer": "https://www.optarkov.com/information?filter=cdk",
	"Accept": "application/json",
}

CDK_API = "https://www.optarkov.com/api/information"
CDK_FILE = DATA_DIR / "cdk.json"
SYNC_INTERVAL = 7 * 24 * 60 * 60
TIMEOUT = 40


def now_text() -> str:
	return datetime.now().isoformat(timespec="seconds")


class CdkStore:
	def __init__(self) -> None:
		self._lock = threading.RLock()
		self._session = requests.Session()
		self._session.headers.update(HEADERS)
		self.payload: dict = self._read()

	def _read(self) -> dict:
		try:
			data = json.loads(CDK_FILE.read_text(encoding="utf-8"))
			return data if isinstance(data, dict) else {}
		except (OSError, ValueError):
			return {}

	def _write(self, payload: dict) -> None:
		CDK_FILE.parent.mkdir(parents=True, exist_ok=True)
		tmp = CDK_FILE.with_suffix(".json.tmp")
		tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
		tmp.replace(CDK_FILE)

	def _transfer(self, entry: dict) -> dict:
		rewards = []
		for reward in entry.get("rewards") or []:
			rewards.append(
				{
					"id": reward.get("id") or "",
					"name": reward.get("localizedName") or reward.get("name") or "",
					"quantity": reward.get("quantity"),
				}
			)
		return {
			"id": entry.get("id"),
			"code": entry.get("cdk") or "",
			"title": entry.get("title") or "",
			"description": entry.get("description") or "",
			"startDate": entry.get("startDate") or "",
			"endDate": entry.get("endDate") or "",
			"endDateStatus": entry.get("endDateStatus") or "",
			"tag": entry.get("tag") or "",
			"rewards": rewards,
		}

	def items(self) -> list[dict]:
		with self._lock:
			return [self._transfer(entry) for entry in self.payload.get("items") or []]

	def sync(self) -> dict:
		with self._lock:
			try:
				response = self._session.get(CDK_API, timeout=TIMEOUT)
				response.raise_for_status()
				body = response.json()
			except (requests.RequestException, ValueError) as error:
				return {"ok": False, "error": str(error)}

			raw = body.get("data") or []
			active = [entry for entry in raw if entry.get("cdk")]
			self.payload = {"syncedAt": now_text(), "items": active}
			self._write(self.payload)
			return {"ok": True, "count": len(active), "syncedAt": self.payload["syncedAt"]}

	def status(self) -> dict:
		# 同步成功后整体替换 payload，首页可在网络请求期间读取上次结果。
		payload = self.payload
		return {
			"syncedAt": payload.get("syncedAt", ""),
			"count": len(payload.get("items") or []),
			"intervalSeconds": SYNC_INTERVAL,
		}
