"""日志基础设施：轮转 + 脱敏（§19/§27.13）。

- 单日志 ≤ 20 MB，保留 ≤ 5 个历史（RotatingFileHandler）。
- 日志脱敏：URL 去 query 参数（token）、不记录密钥类字段。
- 所有 litlib.* logger 挂到同一 handler；由 cli.main 统一初始化。
"""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler

from litlib.config import paths

LOG_MAX_BYTES = 20 * 1024 * 1024
LOG_BACKUP_COUNT = 5

_URL_QUERY_RE = re.compile(r"(https?://\S+?)\?[^\s)\]]+")
_AUTH_FIELD_RE = re.compile(
    r"(?i)((?:[\"']?authorization[\"']?)\s*[:=]\s*[\"']?(?:bearer\s+)?)[^\"'\s,;}]+"
)
_COOKIE_FIELD_RE = re.compile(
    r"(?i)((?:[\"']?(?:cookie|set-cookie)[\"']?)\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\n,}]+)"
)
_KEY_FIELD_RE = re.compile(
    r"(?i)((?:[\"']?(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|"
    r"password|cookie|set-cookie)[\"']?)\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^,\s;}]+)"
)
_WEBVPN_TOKEN_RE = re.compile(
    r"(?i)(https?://vpn\.jlu\.edu\.cn/(?:https|http)/)[^/\s]+"
)


def sanitize(message: str) -> str:
    """脱敏：URL 去 query（token 常在 query），敏感字段值打码。"""
    message = _WEBVPN_TOKEN_RE.sub(r"\1<redacted>", message)
    message = _URL_QUERY_RE.sub(r"\1?<redacted>", message)
    message = _AUTH_FIELD_RE.sub(r"\1<redacted>", message)
    message = _COOKIE_FIELD_RE.sub(r"\1<redacted>", message)
    message = _KEY_FIELD_RE.sub(r"\1<redacted>", message)
    return message


def sanitize_payload(value):
    """Recursively sanitize strings in CLI/MCP payloads without changing their shape."""
    if isinstance(value, str):
        return sanitize(value)
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            normalized_key = re.sub(r"[^a-z0-9]", "", str(key).casefold())
            sensitive = any(marker in normalized_key for marker in (
                "apikey", "token", "secret", "password", "authorization", "cookie",
            ))
            cleaned[key] = "<redacted>" if sensitive else sanitize_payload(item)
        return cleaned
    if isinstance(value, list):
        return [sanitize_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_payload(item) for item in value)
    return value


class SanitizingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = sanitize(record.getMessage())
            record.args = ()
        except Exception:
            pass
        return True


def setup_logging() -> None:
    paths.logs.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger("litlib")
    if getattr(root, "_litlib_configured", False):
        return
    root.setLevel(logging.INFO)
    handler = RotatingFileHandler(
        paths.logs / "litlib.log",
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.addFilter(SanitizingFilter())
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)
    root._litlib_configured = True
