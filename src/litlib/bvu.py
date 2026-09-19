"""Bezmialem Vakif University (BVU) off-campus access via Palo Alto GlobalProtect VPN.

GlobalProtect is IP-based: while connected, publishers see a campus address, so the
generic direct routes (direct-httpx / direct-browser) are sufficient. There is no URL
rewriting gateway and no IdP form, so LitLib never handles a BVU password.

Preflight evidence comes from the publisher side, not from the local VPN client: a
GlobalProtect process can be running while disconnected, and split tunnelling can leave
publisher traffic outside the tunnel. LITLIB_BVU_PROBE_URL should point at a page of a
BVU-subscribed article whose HTML names the institution when access is recognised.
"""

from __future__ import annotations

import os
import re

import httpx

INSTITUTION = "bvu"
DEFAULT_ACCESS_PATTERN = r"Bezmialem"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36")


def is_active() -> bool:
    return os.environ.get("LITLIB_INSTITUTION", "").strip().lower() == INSTITUTION


def access_pattern() -> re.Pattern[str]:
    raw = os.environ.get("LITLIB_BVU_ACCESS_PATTERN", "").strip() or DEFAULT_ACCESS_PATTERN
    return re.compile(raw, re.I)


def detect_institutional_access(html: str) -> str:
    """Return a short evidence snippet if the page attributes access to BVU, else ''."""
    text = re.sub(r"\s+", " ", re.sub(r"<!--.*?-->|<[^>]+>", " ", html, flags=re.S))
    match = access_pattern().search(text)
    if not match:
        return ""
    start, end = max(0, match.start() - 40), min(len(text), match.end() + 40)
    return text[start:end].strip()[:120]


async def vpn_preflight(client: httpx.AsyncClient) -> tuple[bool, str]:
    """Check that the publisher recognises BVU access before spending batch attempts."""
    url = os.environ.get("LITLIB_BVU_PROBE_URL", "").strip()
    if not url:
        return False, "LITLIB_BVU_PROBE_URL is not set; cannot verify GlobalProtect access"
    try:
        resp = await client.get(url, headers={"User-Agent": UA}, follow_redirects=True,
                                timeout=30)
    except httpx.HTTPError as exc:
        return False, f"probe request failed: {type(exc).__name__}"
    if resp.status_code != 200:
        return False, f"probe HTTP {resp.status_code} (challenge or no access; check browser)"
    evidence = detect_institutional_access(resp.text)
    if not evidence:
        return False, "probe page has no BVU access attribution; is GlobalProtect connected?"
    return True, evidence
