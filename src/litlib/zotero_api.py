"""Zotero Local API'ye salt-okur erişim（http://127.0.0.1:23119/api/）。"""

from __future__ import annotations

import os
from pathlib import Path

import httpx

from litlib.models import Work, normalize_doi, normalize_identity_text

ZOTERO_API = "http://127.0.0.1:23119/api"
DEFAULT_DATA_DIR = Path("D:/ZoteroData")


class ZoteroError(Exception):
    pass


class ZoteroReadOnly:
    def __init__(self, client: httpx.Client | None = None, data_dir: Path = DEFAULT_DATA_DIR):
        self._client = client or httpx.Client(timeout=15.0)
        self._owns_client = client is None
        self.data_dir = Path(os.environ.get("LITLIB_ZOTERO_DATA", str(data_dir)))

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _get(self, path: str, params: dict | None = None) -> dict | list:
        resp = self._client.get(f"{ZOTERO_API}{path}", params=params)
        if resp.status_code == 404:
            raise ZoteroError(f"Zotero'da kayıt yok: {path}")
        resp.raise_for_status()
        return resp.json()

    def list_collections(self) -> list[dict]:
        return self._get("/users/0/collections", {"limit": 100})

    def search_items(self, query: str, limit: int = 20) -> list[dict]:
        return self._get("/users/0/items", {"q": query, "qmode": "everything", "limit": limit})

    def find_exact_items(self, work: Work, limit: int = 20) -> list[dict]:
        """Ek olmayan öğeleri tam DOI ile, bulunamazsa tam normalleştirilmiş başlıkla bulur."""
        query = work.doi or work.title or ""
        if not query:
            return []
        items = self.search_items(query, limit=limit)
        candidates = []
        for item in items:
            data = item.get("data", {})
            if data.get("itemType") == "attachment":
                continue
            if work.doi:
                if normalize_doi(data.get("DOI") or "") != normalize_doi(work.doi):
                    continue
            elif normalize_identity_text(data.get("title") or "") != normalize_identity_text(work.title or ""):
                continue
            candidates.append(item)
        if candidates or not work.doi or not work.title:
            return candidates

        for item in self.search_items(work.title, limit=limit):
            data = item.get("data", {})
            if data.get("itemType") == "attachment":
                continue
            item_doi = normalize_doi(data.get("DOI") or "")
            if item_doi and item_doi != normalize_doi(work.doi):
                continue
            if normalize_identity_text(data.get("title") or "") == normalize_identity_text(work.title):
                candidates.append(item)
        return candidates

    def get_item(self, key: str) -> dict:
        return self._get(f"/users/0/items/{key}")

    def get_item_children(self, key: str) -> list[dict]:
        return self._get(f"/users/0/items/{key}/children", {"limit": 100})

    def attachment_abs_path(self, attachment: dict) -> Path | None:
        """Ek öğesi → yerel mutlak yol.

        Zotero 9 Local API'de yol links.enclosure içindedir (file:/// bağlantısı),
        data.path None olabilir. storage: önekiyle ve storage dizini tahminiyle uyumludur.
        """
        enclosure = (attachment.get("links") or {}).get("enclosure") or {}
        href = enclosure.get("href", "")
        if href.startswith("file:///"):
            from urllib.parse import unquote, urlparse

            parsed = urlparse(href)
            path_text = unquote(parsed.path)
            if os.name == "nt" and len(path_text) >= 3 and path_text[0] == "/" and path_text[2] == ":":
                path_text = path_text[1:]
            p = Path(path_text)
            if p.exists():
                return p
        data = attachment.get("data", {})
        path = data.get("path", "")
        link_mode = data.get("linkMode")
        if path.startswith("storage:") and link_mode == "imported_file":
            filename = path[len("storage:"):]
            key = attachment.get("key")
            candidate = self.data_dir / "storage" / key / filename
            if candidate.exists():
                return candidate
        if link_mode in ("linked_file", "linked_url"):
            p = Path(path) if path else None
            return p if p and p.exists() else None
        key = attachment.get("key")
        filename = data.get("filename")
        if key and filename:
            candidate = self.data_dir / "storage" / key / filename
            if candidate.exists():
                return candidate
        return None

    def resolve_pdf(self, item: dict) -> dict | None:
        """Verilen literatür öğesinin ilk PDF ekini bulur, {key, path} döndürür."""
        if item.get("data", {}).get("itemType") == "attachment":
            p = self.attachment_abs_path(item)
            return {"key": item.get("key"), "path": p} if p else None
        key = item.get("key")
        if not key:
            return None
        for child in self.get_item_children(key):
            if child.get("data", {}).get("itemType") == "attachment" and \
               child.get("data", {}).get("contentType", "").lower() == "application/pdf":
                p = self.attachment_abs_path(child)
                if p and p.exists():
                    return {"key": child.get("key"), "path": p}
        return None
