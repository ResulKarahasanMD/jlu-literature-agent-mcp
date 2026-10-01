"""Kişisel deneyim kütüphanesi: yerel olarak kendini geliştirme (learn).

Kanonik site deneyimi (depodaki SITE_RECIPES.md) salt-okur kalır ve Git ile dağıtılır; bu modül her
kullanıcının yerelde başarıyla çözdüğü, listede olmayan sitelerin rotalarını çalışma dizinine (git yok sayar) yazar;
aynı siteyle yeniden karşılaşınca Agent önce kişisel deneyimi okur: "bir kez kullan, bir kez kaydet, kullandıkça kolaylaşsın".

Uyum sınırları kanonik olanla aynıdır: yalnız sıkı PDF doğrulamasından (PDF success contract) geçen
başarılar otomatik kaydedilebilir; PAYWALLED / HUMAN_REQUIRED / RATE_LIMITED öğrenilebilir deneyim sayılmaz;
kayıt içeriği her zaman maskelenir (URL query token'ı, WebVPN token'ı, çerezler, kimlik bilgisi alanları), hiçbir anahtar saklanmaz.
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone

from litlib.config import ensure_storage_path, paths
from litlib.logging_setup import sanitize

EXPERIENCE_VERSION = 1
EXPERIENCE_FILE = paths.runtime_root / "experience" / "experiences.json"

_LOCK = threading.Lock()

_UNSAFE_ROUTES = {"PAYWALLED", "HUMAN_REQUIRED", "RATE_LIMITED", "FAILED", "DOWNLOAD_FAILED"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _domain_key(domain: str) -> str:
    return re.sub(r"^www\.", "", domain.strip().lower()).rstrip(".")


def _route_key(route: str) -> str:
    return sanitize(route.strip().lower())


def load_experiences() -> list[dict]:
    """Tüm kişisel deneyimleri okur; dosya yoksa ya da bozuksa boş liste döndürür (istisna fırlatmaz)."""
    try:
        if not EXPERIENCE_FILE.exists():
            return []
        data = json.loads(EXPERIENCE_FILE.read_text(encoding="utf-8"))
        experiences = data.get("experiences") if isinstance(data, dict) else None
        if not isinstance(experiences, list):
            return []
        return [e for e in experiences if isinstance(e, dict)]
    except (OSError, json.JSONDecodeError):
        return []


def _save(experiences: list[dict]) -> None:
    EXPERIENCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    ensure_storage_path(EXPERIENCE_FILE)
    payload = {"version": EXPERIENCE_VERSION, "experiences": experiences}
    tmp = EXPERIENCE_FILE.with_suffix(".json.part")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(EXPERIENCE_FILE)


def record_success(
    domain: str,
    route: str,
    url_pattern: str = "",
    doi_prefix: str = "",
    notes: str = "",
) -> dict:
    """Başarıyla çözülmüş bir deneyimi kaydeder; aynı domain+route sayaçta birleştirilir, yinelenen kayıt eklenmez.

    Yalnız açıkça başarılı işaretlenen route'lara izin verilir (bkz. _UNSAFE_ROUTES); kayıt içeriği tamamen maskelenir.
    Yazılan deneyim kaydını döndürür.
    """
    domain_key = _domain_key(domain)
    if not domain_key:
        raise ValueError("deneyim için site alan adı gerekli")
    route_key = _route_key(route)
    if route_key in {r.lower() for r in _UNSAFE_ROUTES} or not route_key:
        raise ValueError(f"{route} başarılı deneyim olarak kaydedilemez")

    with _LOCK:
        experiences = load_experiences()
        for entry in experiences:
            if (_domain_key(entry.get("domain", "")) == domain_key
                    and _route_key(entry.get("route", "")) == route_key):
                entry["success_count"] = int(entry.get("success_count") or 0) + 1
                entry["last_success"] = _now()
                entry["source"] = "auto"
                if url_pattern and not entry.get("url_pattern"):
                    entry["url_pattern"] = sanitize(url_pattern)
                if doi_prefix and doi_prefix not in (entry.get("doi_prefix") or ""):
                    entry["doi_prefix"] = doi_prefix
                _save(experiences)
                return entry
        entry = {
            "id": uuid.uuid4().hex[:12],
            "domain": domain_key,
            "route": route_key,
            "url_pattern": sanitize(url_pattern) if url_pattern else "",
            "doi_prefix": doi_prefix,
            "notes": sanitize(notes)[:500] if notes else "",
            "source": "auto",
            "success_count": 1,
            "first_seen": _now(),
            "last_success": _now(),
        }
        experiences.append(entry)
        _save(experiences)
        return entry


def add_manual(
    domain: str,
    route: str,
    notes: str,
    url_pattern: str = "",
    doi_prefix: str = "",
) -> dict:
    """Elle deneyim ekler (insan gözlemi, bu programın başarılı yolu olmayan); route boş olmayan herhangi bir açıklama olabilir."""
    domain_key = _domain_key(domain)
    if not domain_key:
        raise ValueError("deneyim için site alan adı gerekli")
    if not notes.strip():
        raise ValueError("elle eklenen deneyimin açıklaması (--note) olmalı")
    with _LOCK:
        experiences = load_experiences()
        for entry in experiences:
            if (_domain_key(entry.get("domain", "")) == domain_key
                    and _route_key(entry.get("route", "")) == _route_key(route)):
                entry["notes"] = sanitize(notes)[:500]
                entry["updated_at"] = _now()
                entry["source"] = "manual"
                entry["url_pattern"] = sanitize(url_pattern) if url_pattern else entry.get("url_pattern", "")
                if doi_prefix:
                    entry["doi_prefix"] = doi_prefix
                _save(experiences)
                return entry
        entry = {
            "id": uuid.uuid4().hex[:12],
            "domain": domain_key,
            "route": _route_key(route),
            "url_pattern": sanitize(url_pattern) if url_pattern else "",
            "doi_prefix": doi_prefix,
            "notes": sanitize(notes)[:500],
            "source": "manual",
            "success_count": 0,
            "first_seen": _now(),
            "last_success": "",
            "updated_at": _now(),
        }
        experiences.append(entry)
        _save(experiences)
        return entry


def remove_experience(exp_id: str) -> bool:
    """id ile bir deneyimi siler; yoksa False döndürür."""
    with _LOCK:
        experiences = load_experiences()
        remaining = [e for e in experiences if e.get("id") != exp_id]
        if len(remaining) == len(experiences):
            return False
        _save(remaining)
        return True


def find_for(domain: str, doi: str = "") -> list[dict]:
    """Site/DOI önekiyle ilgili tüm deneyimleri döndürür (alt alan adı eşleşmesi dahil, başarı oranına göre sıralı)."""
    domain_key = _domain_key(domain)
    doi_prefix = doi.strip().lower() if doi else ""
    hits: list[dict] = []
    for e in load_experiences():
        d = _domain_key(e.get("domain", ""))
        matches_domain = d and (d == domain_key or d.endswith("." + domain_key)
                                or domain_key.endswith("." + d))
        matches_prefix = bool(
            doi_prefix and e.get("doi_prefix")
            and doi_prefix.startswith(e["doi_prefix"].lower()))
        if matches_domain or matches_prefix:
            hits.append(e)
    hits.sort(key=lambda e: (int(e.get("success_count") or 0), e.get("last_success") or ""),
              reverse=True)
    return hits


def render_markdown() -> str:
    """Kişisel deneyimleri Agent'ın doğrudan okuyabileceği Markdown'a dönüştürür (learn export için)."""
    experiences = load_experiences()
    if not experiences:
        return (
            "# Kişisel deneyim kütüphanesi (boş)\n\nHenüz yerel deneyim yok. Her yeni site başarıyla çözüldüğünde otomatik kaydedilir, "
            "ya da `litlib learn add --domain <alan-adı> --route <rota> --note <açıklama>` ile elle eklenebilir.\n"
        )
    lines = ["# Kişisel deneyim kütüphanesi (yerel, kendini geliştiren)", "",
             "> Kanonik (canonical) site profilleri depoda, `skills/litlib-literature-workflow/references/"
             "SITE_RECIPES.md` içinde; bu dosya yerelde eklenen deneyimlerdir. Okuma sırası: önce kişisel deneyim, sonra canonical.",
             ""]
    for e in experiences:
        lines.append(f"## {e.get('domain')}")
        lines.append(f"- Rota: `{e.get('route')}`")
        if e.get("url_pattern"):
            lines.append(f"- URL kalıbı: `{e.get('url_pattern')}`")
        if e.get("doi_prefix"):
            lines.append(f"- DOI öneki: `{e.get('doi_prefix')}`")
        lines.append(f"- Başarı sayısı: {int(e.get('success_count') or 0)}")
        lines.append(f"- Kaynak: {e.get('source')} | İlk görülme: {e.get('first_seen')}"
                     + (f" | Son başarı: {e.get('last_success')}" if e.get("last_success") else ""))
        if e.get("notes"):
            lines.append(f"- Açıklama: {e.get('notes')}")
        lines.append("")
    return "\n".join(lines)
