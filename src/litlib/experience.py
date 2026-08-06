"""个人经验库：本地自进化（learn）。

canonical 站点经验（仓库内 SITE_RECIPES.md）保持只读、随 Git 分发；本模块把每个用户在
本地成功解决过的、未收录网站的路线写入运行目录（git 忽略），下次遇到同一站点时
Agent 优先读取个人经验，实现"用一次、记一次、越用越顺"。

合规边界与 canonical 相同：只有通过严格 PDF 校验（PDF success contract）的成功才
允许自动记录；PAYWALLED / HUMAN_REQUIRED / RATE_LIMITED 不构成可学习经验；记录内容
一律脱敏（URL 去 query token、WebVPN token、cookie、凭证字段），不保存任何密钥。
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
    """读取全部个人经验；文件缺失或损坏时返回空列表（不抛异常）。"""
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
    """记录一次成功解决的经验；同 domain+route 合并计数，不重复追加。

    仅允许明确标记为成功的 route（见 _UNSAFE_ROUTES）；记录内容全部脱敏。
    返回写入后的经验条目。
    """
    domain_key = _domain_key(domain)
    if not domain_key:
        raise ValueError("经验需要站点域名")
    route_key = _route_key(route)
    if route_key in {r.lower() for r in _UNSAFE_ROUTES} or not route_key:
        raise ValueError(f"不允许把 {route} 记录为成功经验")

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
    """手动补充经验（人工观察、非本程序成功路径），route 允许任意非空描述。"""
    domain_key = _domain_key(domain)
    if not domain_key:
        raise ValueError("经验需要站点域名")
    if not notes.strip():
        raise ValueError("手动经验必须有说明（--note）")
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
    """按 id 删除一条经验；不存在返回 False。"""
    with _LOCK:
        experiences = load_experiences()
        remaining = [e for e in experiences if e.get("id") != exp_id]
        if len(remaining) == len(experiences):
            return False
        _save(remaining)
        return True


def find_for(domain: str, doi: str = "") -> list[dict]:
    """返回与站点/DOI 前缀相关的全部经验（含子域匹配，按成功率排序）。"""
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
    """把个人经验渲染成 Agent 可直接阅读的 Markdown（用于 learn export）。"""
    experiences = load_experiences()
    if not experiences:
        return (
            "# 个人经验库（空）\n\n还没有本地经验。每次成功解决新站点后会自动记录，"
            "也可用 `litlib learn add --domain <域名> --route <路线> --note <说明>` 手动补充。\n"
        )
    lines = ["# 个人经验库（本地自进化）", "",
             "> canonical 站点档案在仓库 `skills/litlib-literature-workflow/references/"
             "SITE_RECIPES.md`，本文件是本地新增经验，读取顺序：先个人经验、后 canonical。",
             ""]
    for e in experiences:
        lines.append(f"## {e.get('domain')}")
        lines.append(f"- 路线: `{e.get('route')}`")
        if e.get("url_pattern"):
            lines.append(f"- URL 模式: `{e.get('url_pattern')}`")
        if e.get("doi_prefix"):
            lines.append(f"- DOI 前缀: `{e.get('doi_prefix')}`")
        lines.append(f"- 成功次数: {int(e.get('success_count') or 0)}")
        lines.append(f"- 来源: {e.get('source')} | 首次: {e.get('first_seen')}"
                     + (f" | 最近成功: {e.get('last_success')}" if e.get("last_success") else ""))
        if e.get("notes"):
            lines.append(f"- 说明: {e.get('notes')}")
        lines.append("")
    return "\n".join(lines)
