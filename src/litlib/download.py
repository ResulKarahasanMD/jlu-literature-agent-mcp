"""Akışlı indirme: .part → artımlı SHA-256 → atomik yeniden adlandırma (§27.7)."""

from __future__ import annotations

import os
from pathlib import Path

import httpx

from litlib.models import sha256_of_file

CHUNK_SIZE = 4 * 1024 * 1024
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


async def download_to_file(
    client: httpx.AsyncClient,
    url: str,
    dest: Path,
    max_bytes: int | None = None,
) -> tuple[Path, str, int]:
    """dest.part'a akışlı indirir, doğrulamadan sonra atomik olarak yeniden adlandırır. (son yol, sha256, bayt sayısı) döndürür."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    tmp_digest = Path(str(part) + ".sha256")
    part.unlink(missing_ok=True)
    tmp_digest.unlink(missing_ok=True)
    try:
        async with client.stream("GET", url, headers=HEADERS, follow_redirects=True) as resp:
            resp.raise_for_status()
            total = 0
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
    except BaseException:
        part.unlink(missing_ok=True)
        tmp_digest.unlink(missing_ok=True)
        raise
