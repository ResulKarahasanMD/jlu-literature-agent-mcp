"""Geçici taşıma hataları (DNS / bağlantı) için sınırlı yeniden deneme.

GlobalProtect'in DNS sunucusu (10.100.4.211) ara sıra zaman aşımına düşer: httpx ilk denemede
`ConnectError: [Errno 8] nodename nor servname provided, or not known` verir, aynı ana bilgisayar
3-5 s sonra sorunsuz çözülür (2026-09-25 canlı koşusu, out_20260925_dbcheck r1.json → r2.json).

Yalnız httpx.TransportError alt sınıfları (ConnectError, ConnectTimeout, ReadTimeout, ...) yeniden
denenir. HTTP durum kodları yanıt olarak döner, buraya hiç uğramaz. Sertifika doğrulama hataları
kalıcıdır ve hemen yükseltilir; httpx bunları da ConnectError olarak sardığı için istisna
zincirine bakılır (httpx.ConnectError <- httpcore.ConnectError <- ssl.SSLCertVerificationError).
"""

from __future__ import annotations

import asyncio
import logging
import ssl
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

import httpx

logger = logging.getLogger("litlib.transport_retry")

# Denemeler arası bekleme (s). 3 bekleme = toplam 4 deneme, en fazla 12 s ek süre.
RETRY_DELAYS: tuple[float, ...] = (3.0, 4.0, 5.0)
CERTIFICATE_MARKER = "CERTIFICATE_VERIFY_FAILED"

T = TypeVar("T")


def is_ssl_certificate_error(exc: BaseException) -> bool:
    """__cause__/__context__ zincirinde SSLCertVerificationError ya da mesajda sertifika imzası var mı."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        if isinstance(current, ssl.SSLCertVerificationError):
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return CERTIFICATE_MARKER in str(exc)


def is_retryable_transport_error(exc: BaseException) -> bool:
    """Taşıma katmanı hatası ve sertifika hatası değil: yeniden denemeye değer."""
    return isinstance(exc, httpx.TransportError) and not is_ssl_certificate_error(exc)


async def retry_transport(
    fn: Callable[[], Awaitable[T]],
    *,
    what: str,
    delays: Sequence[float] | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    """`fn()` sonucunu döndürür; geçici taşıma hatasında `delays` boyunca bekleyip yeniden dener.

    Plan `delays` (varsayılan RETRY_DELAYS, çağrı anında okunur) uzunluğu + 1 denemeyle sınırlıdır.
    Her yeniden deneme WARNING düzeyinde günlüğe yazılır; son hata olduğu gibi yükseltilir.
    """
    schedule = tuple(RETRY_DELAYS if delays is None else delays)
    for attempt, delay in enumerate(schedule, start=1):
        try:
            return await fn()
        except httpx.TransportError as exc:
            if not is_retryable_transport_error(exc):
                raise
            logger.warning("%s: %s: %s; retry %d/%d in %g s",
                           what, type(exc).__name__, exc, attempt, len(schedule), delay)
        await sleep(delay)
    try:
        return await fn()
    except httpx.TransportError as exc:
        if is_retryable_transport_error(exc):
            logger.warning("%s: %s: %s; giving up after %d attempts",
                           what, type(exc).__name__, exc, len(schedule) + 1)
        raise
