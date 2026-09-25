"""Geçici taşıma hataları için sınırlı yeniden deneme (litlib.transport_retry)."""

from __future__ import annotations

import logging
import socket
import ssl

import httpcore
import httpx
import pytest

from litlib import transport_retry
from litlib.transport_retry import (
    RETRY_DELAYS,
    is_retryable_transport_error,
    is_ssl_certificate_error,
    retry_transport,
)

LOGGER = "litlib.transport_retry"
DNS_MESSAGE = "[Errno 8] nodename nor servname provided, or not known"
CERT_MESSAGE = ("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
                "certificate has expired (_ssl.c:1010)")


def _chained(outer: BaseException, *inner: BaseException) -> BaseException:
    """httpx'in taşıma hatalarını sardığı gibi bir __cause__ zinciri kurar (dıştan içe)."""
    links = (outer, *inner)
    for parent, child in zip(links, links[1:]):
        parent.__cause__ = child
    return outer


def _certificate_connect_error(message: str = "certificate verify failed") -> httpx.ConnectError:
    """httpx 0.28 zinciri: httpx.ConnectError <- httpcore.ConnectError <- ssl.SSLCertVerificationError."""
    return _chained(httpx.ConnectError(message), httpcore.ConnectError(message),
                    ssl.SSLCertVerificationError(message))


def _dns_connect_error() -> httpx.ConnectError:
    """httpx 0.28 zinciri: httpx.ConnectError <- httpcore.ConnectError <- socket.gaierror."""
    return _chained(httpx.ConnectError(DNS_MESSAGE), httpcore.ConnectError(DNS_MESSAGE),
                    socket.gaierror(8, "nodename nor servname provided, or not known"))


def _status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://publisher.test/article")
    return httpx.HTTPStatusError(f"HTTP {status}", request=request,
                                 response=httpx.Response(status, request=request))


class Flaky:
    """İlk `failures` çağrıda `error` fırlatır, sonra 'ok' döndürür; çağrı sayısını tutar."""

    def __init__(self, error: BaseException, failures: int):
        self.error, self.failures, self.calls = error, failures, 0

    async def __call__(self) -> str:
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error
        return "ok"


@pytest.fixture()
def sleeps() -> list[float]:
    return []


@pytest.fixture()
def sleep(sleeps):
    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
    return fake_sleep


# ---- sınıflandırma --------------------------------------------------------------

def test_schedule_is_four_attempts_with_3_to_5_second_backoff():
    assert RETRY_DELAYS == (3.0, 4.0, 5.0)


@pytest.mark.parametrize(("error", "expected"), [
    (_certificate_connect_error(), True),                       # zincirde SSLCertVerificationError
    (httpx.ConnectError(CERT_MESSAGE), True),                   # zincir yok, yalnız mesaj (örn. iş parçacığından)
    (_dns_connect_error(), False),
    (httpx.ConnectError(DNS_MESSAGE), False),
    (_chained(httpx.ConnectError("[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred"),
              httpcore.ConnectError("EOF"), ssl.SSLError(8, "EOF occurred")), False),  # el sıkışma koptu: sertifika değil
])
def test_is_ssl_certificate_error(error, expected):
    assert is_ssl_certificate_error(error) is expected


@pytest.mark.parametrize(("error", "expected"), [
    (_dns_connect_error(), True),
    (httpx.ConnectTimeout("connect timed out"), True),
    (httpx.ReadTimeout("read timed out"), True),
    (httpx.RemoteProtocolError("server disconnected"), True),
    (_certificate_connect_error(), False),
    (_status_error(429), False),
    (_status_error(503), False),
    (ValueError("not a transport error"), False),
])
def test_is_retryable_transport_error(error, expected):
    assert is_retryable_transport_error(error) is expected


# ---- retry_transport -------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("error", [_dns_connect_error(), httpx.ConnectTimeout("connect timed out")])
async def test_transient_failure_then_success_is_retried(error, sleep, sleeps, caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER)
    fn = Flaky(error, failures=1)

    result = await retry_transport(fn, what="BVU probe https://publisher.test/a", sleep=sleep)

    assert result == "ok" and fn.calls == 2
    assert sleeps == [3.0]
    [record] = [r for r in caplog.records if r.name == LOGGER]
    assert record.levelno == logging.WARNING
    message = record.getMessage()
    assert "BVU probe https://publisher.test/a" in message
    assert type(error).__name__ in message and str(error) in message
    assert "retry 1/3" in message and "3 s" in message


@pytest.mark.asyncio
async def test_gives_up_after_four_attempts_and_reraises_last_error(sleep, sleeps, caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER)
    fn = Flaky(_dns_connect_error(), failures=99)

    with pytest.raises(httpx.ConnectError, match="nodename nor servname"):
        await retry_transport(fn, what="download https://publisher.test/a.pdf", sleep=sleep)

    assert fn.calls == 4
    assert sleeps == [3.0, 4.0, 5.0]
    messages = [r.getMessage() for r in caplog.records if r.name == LOGGER]
    assert [m for m in messages if "retry" in m] == messages[:3]
    assert "retry 3/3" in messages[2]
    assert "giving up" in messages[3] and "4 attempts" in messages[3]


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [
    _certificate_connect_error(),
    httpx.ConnectError(CERT_MESSAGE),
    _status_error(429),
    _status_error(503),
    ValueError("not a transport error"),
])
async def test_non_transient_errors_are_raised_immediately(error, sleep, sleeps, caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER)
    fn = Flaky(error, failures=99)

    with pytest.raises(type(error)):
        await retry_transport(fn, what="x", sleep=sleep)

    assert fn.calls == 1 and sleeps == []
    assert [r for r in caplog.records if r.name == LOGGER] == []


@pytest.mark.asyncio
async def test_default_schedule_is_read_at_call_time(monkeypatch, sleep, sleeps):
    """Testler RETRY_DELAYS'i yamalayabilsin diye varsayılan plan çağrı anında okunur."""
    monkeypatch.setattr(transport_retry, "RETRY_DELAYS", (0.25,))
    fn = Flaky(_dns_connect_error(), failures=1)
    assert await retry_transport(fn, what="x", sleep=sleep) == "ok"
    assert sleeps == [0.25]

    fn = Flaky(_dns_connect_error(), failures=2)
    with pytest.raises(httpx.ConnectError):
        await retry_transport(fn, what="x", sleep=sleep)
    assert fn.calls == 2 and sleeps == [0.25, 0.25]


@pytest.mark.asyncio
async def test_explicit_delays_override_schedule(sleep, sleeps):
    fn = Flaky(httpx.ReadTimeout("read timed out"), failures=1)
    assert await retry_transport(fn, what="x", delays=(0.5, 0.5), sleep=sleep) == "ok"
    assert sleeps == [0.5]
