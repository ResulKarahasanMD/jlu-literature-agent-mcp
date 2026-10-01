"""Salt-okur MCP sunucusu (mcp 2.x MCPServer): metadata / pdf / fulltext olmak üzere üç düzeyli okuma."""

from __future__ import annotations

import json
import re
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.tools import Tool

from litlib import __version__
from litlib.fulltext import DEFAULT_LIMIT_CHARS, MAX_LIMIT_CHARS, get_fulltext
from litlib.logging_setup import sanitize_payload
from litlib.models import normalize_doi
from litlib.state import State
from litlib.zotero_api import ZoteroReadOnly


def _json(payload: dict | list) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _open_state() -> State:
    """Görev durumunu dizin, şema, WAL ya da önbellek dosyası oluşturmadan açar."""
    return State(readonly=True)


def _search_metadata(query: str, limit: int = 20) -> list[dict]:
    limit = max(1, min(limit, 50))
    results: list[dict] = []
    try:
        zot = ZoteroReadOnly()
        try:
            for item in zot.search_items(query, limit=limit):
                data = item.get("data", {})
                if data.get("itemType") == "attachment":
                    continue
                creators = ", ".join(
                    c.get("name") or f"{c.get('lastName', '')} {c.get('firstName', '')}"
                    for c in (data.get("creators") or [])
                )
                results.append({
                    "key": item.get("key"),
                    "title": data.get("title") or data.get("publicationTitle"),
                    "year": data.get("date"),
                    "doi": data.get("DOI"),
                    "creators": creators,
                })
        finally:
            zot.close()
    except Exception as e:
        zotero_error = str(e)
    else:
        zotero_error = ""
    try:
        st = _open_state()
        try:
            for r in st.search_works(query, limit):
                creators = ", ".join(
                    " ".join(filter(None, (a.get("family"), a.get("given"))))
                    for a in r.get("authors", [])
                )
                results.append({"work_id": r["work_id"], "title": r["title"],
                                "year": r["year"], "doi": r["doi"],
                                "creators": creators, "source": "state"})
        finally:
            st.close()
    except Exception as e:
        state_error = str(e)
    else:
        state_error = ""
    if not results:
        errors = []
        if zotero_error:
            errors.append(f"Zotero kullanılamıyor: {zotero_error}")
        if state_error:
            errors.append(f"durum veritabanı kullanılamıyor: {state_error}")
        if errors:
            return [{"error": " | ".join(errors)}]
    return results[:limit]


def _find_pdf(query: str) -> dict:
    candidates: list[dict] = []
    errors: list[str] = []
    doi_query = normalize_doi(query)
    is_doi = bool(re.fullmatch(r"10\.\d{4,9}/[-._;()/:a-z0-9]+", doi_query, re.I))
    is_key = bool(re.fullmatch(r"[A-Z0-9]{8}", query.strip(), re.I))
    try:
        zot = ZoteroReadOnly()
        try:
            items = []
            if is_key:
                try:
                    items.append(zot.get_item(query.strip().upper()))
                except Exception:
                    pass
            items.extend(zot.search_items(query, limit=10))
            seen_keys: set[str] = set()
            for item in items:
                if item.get("data", {}).get("itemType") == "attachment":
                    continue
                data = item.get("data", {})
                item_key = str(item.get("key") or "")
                if not item_key or item_key in seen_keys:
                    continue
                seen_keys.add(item_key)
                if is_doi and normalize_doi(data.get("DOI") or "") != doi_query:
                    continue
                if is_key and item_key.upper() != query.strip().upper():
                    continue
                hit = zot.resolve_pdf(item)
                if hit:
                    candidates.append({
                        "key": hit["key"], "parent_key": item_key,
                        "title": data.get("title"), "doi": data.get("DOI"),
                        "path": str(hit["path"]), "source": "zotero",
                    })
        finally:
            zot.close()
    except Exception as e:
        errors.append(f"Zotero kullanılamıyor: {e}")

    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        return {
            "error": "sorgu birden fazla Zotero PDF'iyle eşleşti; tam DOI ya da 8 karakterlik item key kullanın",
            "candidates": candidates[:10],
        }

    try:
        st = _open_state()
        try:
            for r in st.search_works(query, 10):
                for file_record in st.get_files(r["work_id"]):
                    if Path(file_record["path"]).exists():
                        candidates.append({
                            "key": r["work_id"], "title": r["title"], "doi": r["doi"],
                            "path": file_record["path"], "source": "state",
                        })
                        break
        finally:
            st.close()
    except Exception as e:
        errors.append(f"durum veritabanı kullanılamıyor: {e}")
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        return {
            "error": "sorgu görev veritabanında birden fazla PDF'le eşleşti; tam DOI kullanın",
            "candidates": candidates[:10],
        }
    detail = f" ({' | '.join(errors)})" if errors else ""
    return {"error": f"PDF bulunamadı{detail}"}


def _list_collections() -> list[dict]:
    try:
        zot = ZoteroReadOnly()
        try:
            return [{"key": c.get("key"), "name": c.get("data", {}).get("name")}
                    for c in zot.list_collections()]
        finally:
            zot.close()
    except Exception as e:
        return [{"error": f"Zotero kullanılamıyor: {e}"}]


def _task_status(state: str | None = None) -> list[dict]:
    try:
        st = _open_state()
        try:
            rows = st.list_tasks(limit=200)
            if state:
                rows = [r for r in rows if r["state"] == state]
            return sanitize_payload([
                {"id": r["id"], "state": r["state"], "input": r["raw_input"][:80],
                 "error": r["last_error"]}
                for r in rows
            ])
        finally:
            st.close()
    except Exception as e:
        return [{"error": f"durum veritabanı kullanılamıyor: {e}"}]


def library_search_metadata(query: str, limit: int = 20) -> str:
    """Başlık/DOI ile Zotero'da ve bu projenin veritabanında literatür metadata'sı arar (salt-okur)"""
    return _json(_search_metadata(query, limit))


def library_get_pdf_path(query: str) -> str:
    """Eşleşen literatürün yerel PDF yolunu döndürür (salt-okur)"""
    return _json(_find_pdf(query))


def library_get_fulltext(query: str, offset: int = 0, limit_chars: int = DEFAULT_LIMIT_CHARS) -> str:
    """Eşleşen literatürün sayfalı tam metnini döndürür (varsayılan 10000 karakter, üst sınır 20000, salt-okur)"""
    hit = _find_pdf(query)
    if "error" in hit:
        return _json(hit)
    try:
        result = get_fulltext(
            Path(hit["path"]), hit["key"], offset=offset,
            limit_chars=max(1, min(limit_chars, MAX_LIMIT_CHARS)), cache=False,
        )
        result["key"] = hit["key"]
        result["path"] = hit["path"]
        return _json(result)
    except Exception as e:
        return _json({"error": str(e)})


def library_list_collections() -> str:
    """Zotero koleksiyonlarını listeler (salt-okur)"""
    return _json(_list_collections())


def library_task_status(state: str | None = None) -> str:
    """İndirme/içe aktarma görev durumunu sorgular (salt-okur); state örn. READY / REQUIRES_INST"""
    return _json(_task_status(state))


TOOLS = [
    Tool.from_function(library_search_metadata),
    Tool.from_function(library_get_pdf_path),
    Tool.from_function(library_get_fulltext),
    Tool.from_function(library_list_collections),
    Tool.from_function(library_task_status),
]

server = MCPServer(
    "litlib",
    version=__version__,
    instructions="Kişisel literatür kütüphanesi salt-okur arayüzü: metadata, PDF yolu ve sayfalı tam metin sorgulama.",
    tools=TOOLS,
)


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
