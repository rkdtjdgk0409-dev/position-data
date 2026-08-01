from __future__ import annotations

import os
import re
from typing import Any

import numpy as np
import requests

NOTION_VERSION = os.getenv("NOTION_VERSION", "2025-09-03")
NOTION_BASE = "https://api.notion.com/v1"
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))


def normalize_notion_id(raw: str) -> str:
    if not raw:
        raise ValueError("Notion database ID가 비어 있습니다.")
    candidates = re.findall(r"(?i)([0-9a-f]{32})", raw.replace("-", ""))
    if not candidates:
        raise ValueError("Notion database URL/ID에서 32자리 ID를 찾지 못했습니다.")
    value = candidates[0].lower()
    return f"{value[:8]}-{value[8:12]}-{value[12:16]}-{value[16:20]}-{value[20:]}"


class NotionClient:
    def __init__(self, token: str, database_id: str) -> None:
        self.database_id = normalize_notion_id(database_id)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            }
        )
        self.data_source_id: str | None = None
        self.schema: dict[str, Any] = {}

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = self.session.request(
            method,
            f"{NOTION_BASE}{path}",
            timeout=REQUEST_TIMEOUT,
            **kwargs,
        )
        if not response.ok:
            try:
                detail = response.json()
            except Exception:
                detail = response.text
            raise RuntimeError(
                f"Notion API 실패: {method} {path}, HTTP {response.status_code}, {detail}"
            )
        return response.json()

    def initialize(self) -> None:
        database = self._request("GET", f"/databases/{self.database_id}")
        sources = database.get("data_sources") or []
        if not sources:
            raise RuntimeError(
                "Notion 데이터 소스를 찾지 못했습니다. Integration을 현재 포지션 DB에 연결하세요."
            )
        override = os.getenv("NOTION_POSITIONS_DATA_SOURCE_ID", "").strip()
        self.data_source_id = normalize_notion_id(override) if override else sources[0]["id"]
        data_source = self._request("GET", f"/data_sources/{self.data_source_id}")
        self.schema = data_source.get("properties", {})
        print(f"[Notion] database={self.database_id}")
        print(f"[Notion] data_source={self.data_source_id}")
        print("[Notion] properties=", {k: v.get("type") for k, v in self.schema.items()})

    def query_all(self) -> list[dict[str, Any]]:
        if not self.data_source_id:
            raise RuntimeError("NotionClient.initialize()를 먼저 실행하세요.")
        rows: list[dict[str, Any]] = []
        payload: dict[str, Any] = {"page_size": 100}
        while True:
            result = self._request(
                "POST", f"/data_sources/{self.data_source_id}/query", json=payload
            )
            rows.extend(result.get("results", []))
            if not result.get("has_more"):
                return rows
            payload["start_cursor"] = result["next_cursor"]

    def update_page(self, page_id: str, properties: dict[str, Any]) -> None:
        self._request("PATCH", f"/pages/{page_id}", json={"properties": properties})


def get_prop(page: dict[str, Any], name: str) -> dict[str, Any]:
    return page.get("properties", {}).get(name, {})


def plain_text(prop: dict[str, Any]) -> str:
    prop_type = prop.get("type")
    items = prop.get(prop_type, []) if prop_type in {"title", "rich_text"} else []
    return "".join(item.get("plain_text", "") for item in items).strip()


def number_value(prop: dict[str, Any]) -> float:
    if prop.get("type") == "number":
        value = prop.get("number")
        return float(value) if value is not None else 0.0
    text = re.sub(r"[^0-9.\-]", "", plain_text(prop))
    try:
        return float(text)
    except ValueError:
        return 0.0


def make_number(value: float) -> dict[str, Any]:
    if not np.isfinite(value):
        return {"number": None}
    return {"number": round(float(value), 10)}
