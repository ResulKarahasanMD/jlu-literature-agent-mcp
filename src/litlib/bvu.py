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

import asyncio
import os
import re

import httpx

from litlib import chrome_cdp

INSTITUTION = "bvu"
DEFAULT_ACCESS_PATTERN = r"Bezmialem"
BROWSER_FALLBACK_STATUSES = {403, 503}
CHALLENGE_MARKERS = re.compile(
    r"just a moment|cf-chl|challenge-platform|cf-turnstile|captcha|are you a robot", re.I)
PAGE_SETTLE_SECONDS = 4
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


def is_bot_challenge(status: int, html: str) -> bool:
    """httpx was stopped by an anti-bot wall (e.g. Cloudflare), not told 'no access'."""
    return status in BROWSER_FALLBACK_STATUSES or bool(CHALLENGE_MARKERS.search(html[:20000]))


async def browser_probe(url: str) -> tuple[bool, str]:
    """Open the probe page in the already-running dedicated Chrome and look for BVU access.

    Challenges are never solved automatically: the upstream human wait is reused and, on
    timeout, the tab stays open for the user.
    """
    try:
        await chrome_cdp.wait_for_cdp(timeout=5)
        ws = await chrome_cdp.create_tab_navigate(url, timeout=30)
    except Exception as exc:
        return False, (f"browser probe unavailable ({type(exc).__name__}); "
                       "start the dedicated browser with `litlib inst open`")
    if not ws:
        return False, "browser probe could not open a tab"
    from litlib.inst_login import wait_for_human_challenge

    tab = chrome_cdp.Tab(ws)
    await tab.connect()
    keep_tab_open = False
    try:
        await asyncio.sleep(PAGE_SETTLE_SECONDS)
        if not await wait_for_human_challenge(tab):
            keep_tab_open = True
            return False, "HUMAN_REQUIRED: complete the challenge in the dedicated browser"
        r = await tab.cmd("Runtime.evaluate", {
            "expression": "document.documentElement ? document.documentElement.outerHTML : ''",
            "returnByValue": True,
        })
        evidence = detect_institutional_access(str(r.get("result", {}).get("value", "")))
    finally:
        if keep_tab_open:
            await tab.close()
        else:
            await tab.close_target()
    if not evidence:
        return False, "browser probe page has no BVU access attribution; is GlobalProtect on?"
    return True, f"{evidence} (via browser)"


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
    if resp.status_code == 429:
        return False, "RATE_LIMITED: probe HTTP 429; wait before retrying"
    if is_bot_challenge(resp.status_code, resp.text):
        return await browser_probe(url)
    if resp.status_code != 200:
        return False, f"probe HTTP {resp.status_code}"
    evidence = detect_institutional_access(resp.text)
    if not evidence:
        return False, "probe page has no BVU access attribution; is GlobalProtect connected?"
    return True, evidence
