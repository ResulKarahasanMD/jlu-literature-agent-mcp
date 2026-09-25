"""Akışlı indirme: .part → artımlı SHA-256 → atomik yeniden adlandırma (§27.7)."""

from __future__ import annotations

import os
from pathlib import Path

import httpx

from litlib.models import sha256_of_file
from litlib.transport_retry import retry_transport

CHUNK_SIZE = 4 * 1024 * 1024
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


async def download_to_file(
    client: httpx.AsyncClient,
    url: str,
    dest: Path,
    max_bytes: int | None = None,
) -> tuple[Path, str, int]:
    """dest.part'a akışlı indirir, doğrulamadan sonra atomik olarak yeniden adlandırır. (son yol, sha256, bayt sayısı) döndürür.

    Bağlantı aşaması (DNS, TCP/TLS, yanıt başlıkları) geçici taşıma hatalarında sınırlı sayıda
    yeniden denenir (transport_retry); gövde akarken kopan bağlantı yeniden denenmez.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    tmp_digest = Path(str(part) + ".sha256")
    part.unlink(missing_ok=True)
    tmp_digest.unlink(missing_ok=True)
    try:
        # client.stream() ile aynı: build_request + send(stream=True) + aclose(); yalnız bağlantı
        # aşaması yeniden denenir, gövde akışı değil.
        resp = await retry_transport(
            lambda: client.send(client.build_request("GET", url, headers=HEADERS),
                                stream=True, follow_redirects=True),
            what=f"download {url}",
        )
        try:
            resp.raise_for_status()
            total = 0
            with open(part, "wb") as f:
                async for chunk in resp.aiter_bytes(CHUNK_SIZE):
                    total += len(chunk)
                    if max_bytes and total > max_bytes:
                        raise ValueError(f"boyut üst sınırı aşıldı: {max_bytes} bayt")
                    f.write(chunk)
        finally:
            await resp.aclose()
        digest = sha256_of_file(part)
        tmp_digest.write_text(digest)
        os.replace(part, dest)
        tmp_digest.unlink(missing_ok=True)
        return dest, digest, total
    except BaseException:
        part.unlink(missing_ok=True)
        tmp_digest.unlink(missing_ok=True)
        raise
