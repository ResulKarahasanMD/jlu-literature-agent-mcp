from __future__ import annotations

import logging

from litlib.logging_setup import SanitizingFilter, sanitize_payload


def test_logging_filter_sanitizes_format_arguments():
    record = logging.LogRecord(
        name="litlib.test",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="request failed: %s",
        args=("https://example.test/file.pdf?token=secret",),
        exc_info=None,
    )
    assert SanitizingFilter().filter(record)
    assert "secret" not in record.getMessage()
    assert "<redacted>" in record.getMessage()


def test_sanitize_payload_preserves_shape():
    payload = {
        "steps": ["token=abc123", "https://example.test/path?signature=xyz"],
        "ok": True,
    }
    cleaned = sanitize_payload(payload)
    assert cleaned["ok"] is True
    assert "abc123" not in cleaned["steps"][0]
    assert "signature=xyz" not in cleaned["steps"][1]


def test_sanitize_handles_json_authorization_and_cookies():
    payload = {
        "message": '{"password": "abc", "Authorization": "Bearer token123"}',
        "Cookie": "session=secret; other=value",
    }
    cleaned = sanitize_payload(payload)
    assert "abc" not in cleaned["message"]
    assert "token123" not in cleaned["message"]
    assert cleaned["Cookie"] == "<redacted>"
