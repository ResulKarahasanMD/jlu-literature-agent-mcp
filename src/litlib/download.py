"""Akışlı indirme: .part → artımlı SHA-256 → atomik yeniden adlandırma (§27.7)."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import httpx

from litlib.models import sha256_of_file

log = logging.getLogger(__name__)

CHUNK_SIZE = 4 * 1024 * 1024
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
# Bağlantı kurulamadan (yanıt gövdesinden bayt gelmeden) oluşan geçici taşıma hataları
# (DNS, bağlantı reddi, zaman aşımı) için sınırlı yeniden deneme; HTTP durum kodları ve
# sertifika hataları yinelenmez. Gerekçe: bvu.py'deki GlobalProtect DNS notu.
TRANSIENT_RETRIES = 4
RETRY_BACKOFF_SECONDS = 3.0


async def download_to_file(
    client: httpx.AsyncClient,
    url: str,
    dest: Path,
    max_bytes: int | None = None,
) -> tuple[Path, str, int]:
    """dest.part'a akışlı indirir, doğrulamadan sonra atomik olarak yeniden adlandırır. (son yol, sha256, bayt sayısı) döndürür."""
    from litlib.bvu import is_transient_transport_error

    for attempt in range(1, TRANSIENT_RETRIES + 1):
        try:
            return await _download_once(client, url, dest, max_bytes)
        except httpx.TransportError as exc:
            if attempt == TRANSIENT_RETRIES or not is_transient_transport_error(exc) \
                    or getattr(exc, "_litlib_bytes_received", False):
                raise
            delay = RETRY_BACKOFF_SECONDS * attempt
            log.warning("geçici ağ hatası (%s) %s — %d/%d, %.0fs sonra yeniden",
                        type(exc).__name__, url, attempt, TRANSIENT_RETRIES, delay)
            await asyncio.sleep(delay)
    raise AssertionError("unreachable")


async def _download_once(
    client: httpx.AsyncClient,
    url: str,
    dest: Path,
    max_bytes: int | None = None,
) -> tuple[Path, str, int]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    tmp_digest = Path(str(part) + ".sha256")
    part.unlink(missing_ok=True)
    tmp_digest.unlink(missing_ok=True)
    total = 0
    resp: httpx.Response | None = None
    try:
        async with client.stream("GET", url, headers=HEADERS, follow_redirects=True) as resp:
            resp.raise_for_status()
            with open(part, "wb") as f:
                async for chunk in resp.aiter_bytes(CHUNK_SIZE):
                    total += len(chunk)
                    if max_bytes and total > max_bytes:
                        raise ValueError(f"boyut üst sınırı aşıldı: {max_bytes} bayt")
                    f.write(chunk)
        digest = sha256_of_file(part)
        tmp_digest.write_text(digest)
        os.replace(part, dest)
        tmp_digest.unlink(missing_ok=True)
        return dest, digest, total
    except BaseException as exc:
        part.unlink(missing_ok=True)
        tmp_digest.unlink(missing_ok=True)
        # aiter_bytes 4 MB tamponlar; ham sayaç gövdenin başlayıp başlamadığını gösterir.
        if isinstance(exc, httpx.TransportError) and resp is not None and resp.num_bytes_downloaded:
            exc._litlib_bytes_received = True  # gövde başlamıştı: yarım indirme yinelenmez
        raise
