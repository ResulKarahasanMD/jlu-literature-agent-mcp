"""CNKI kampüs ağı arama/indirme ve kampüs dışı CARSI girişi uyarlaması."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

from litlib import chrome_cdp
from litlib.inst_login import auto_login, fetch_file_via_browser, fetch_pdf_via_browser
from litlib.pdf import PDFError

CNKI_SEARCH_URL = "https://kns.cnki.net/kns8s/defaultresult/index"
CNKI_CARSI_URL = "https://fsso.cnki.net/"


class CNKIError(RuntimeError):
    pass


class CNKIHumanRequired(CNKIError):
    pass


@dataclass
class CNKIResult:
    title: str
    url: str
    source: str = ""


def is_cnki_challenge(url: str, text: str) -> bool:
    return bool(re.search(
        r"/verify/|安全验证|向右滑动|captcha|blockpuzzle|请完成安全验证", url + "\n" + text,
        re.I,
    ))


async def _page_state(tab: chrome_cdp.Tab) -> tuple[str, str]:
    url_result = await tab.cmd("Runtime.evaluate", {
        "expression": "location.href", "returnByValue": True,
    })
    text_result = await tab.cmd("Runtime.evaluate", {
        "expression": "document.body ? document.body.innerText.slice(0, 800) : ''",
        "returnByValue": True,
    })
    return (
        str(url_result.get("result", {}).get("value", "")),
        str(text_result.get("result", {}).get("value", "")),
    )


async def _has_visible_cnki_challenge(tab: chrome_cdp.Tab, url: str, text: str) -> bool:
    """DOM'da kalan ama ekran dışına taşınmış Tencent doğrulama bileşenini yok sayar."""
    if re.search(r"/verify/|[?&]captchaId=", url, re.I):
        return True
    if not is_cnki_challenge(url, text):
        return False
    result = await tab.cmd("Runtime.evaluate", {
        "expression": r'''
        (() => [...document.querySelectorAll(
          '#tcaptcha_transform_dy, [id*="captcha" i], [class*="captcha" i], [id*="verify" i], [class*="verify" i]'
        )].some(e => {
          const r = e.getBoundingClientRect();
          const s = getComputedStyle(e);
          return r.width > 20 && r.height > 20 && r.bottom > 0 && r.top < innerHeight
            && r.right > 0 && r.left < innerWidth && s.display !== 'none'
            && s.visibility !== 'hidden' && s.opacity !== '0';
        }))()
        ''',
        "returnByValue": True,
    })
    return bool(result.get("result", {}).get("value", False))


async def _connect_or_open_cnki(url: str) -> chrome_cdp.Tab:
    """Mevcut CNKI sekmesini yeniden kullanır; CNKI'nin her yeni sekmede kaydırıcı doğrulamayı yeniden tetiklemesini önler."""
    await chrome_cdp.wait_for_cdp(timeout=10)
    async with httpx.AsyncClient(timeout=10) as client:
        pages = (await client.get(
            f"http://{chrome_cdp.CDP_HOST}:{chrome_cdp.CDP_PORT}/json/list")).json()
    candidates = []
    for page in pages:
        if page.get("type") != "page":
            continue
        page_url = str(page.get("url", ""))
        host = urlparse(page_url).hostname or ""
        if host == "kns.cnki.net" or host.endswith(".cnki.net"):
            is_requested_page = page_url.split("?", 1)[0] == url.split("?", 1)[0]
            is_challenge_page = bool(re.search(r"/verify/|[?&]captchaId=", page_url, re.I))
            # Doğrulama yönlendirmesi yerine özgün, doğrulanmış CNKI sayfası tercih edilir.
            candidates.append((not is_requested_page, is_challenge_page, page))
    if candidates:
        _, _, page = min(candidates, key=lambda candidate: candidate[:2])
        tab = chrome_cdp.Tab(page["webSocketDebuggerUrl"])
        await tab.connect()
        return tab
    ws = await chrome_cdp.create_tab_navigate(url, timeout=30)
    if not ws:
        raise CNKIError("CNKI sekmesi oluşturulamadı")
    tab = chrome_cdp.Tab(ws)
    await tab.connect()
    return tab


async def open_cnki_campus() -> str:
    """CNKI kampüs ağı girişini açar; kullanıcının güvenlik doğrulamasını tamamlaması için sekmeyi görünür bırakır."""
    tab = await _connect_or_open_cnki(CNKI_SEARCH_URL)
    try:
        current_url, current_text = await _page_state(tab)
        if not current_url.startswith(CNKI_SEARCH_URL) or await _has_visible_cnki_challenge(tab, current_url, current_text):
            await chrome_cdp.navigate(tab, CNKI_SEARCH_URL)
        await asyncio.sleep(8)
        url, text = await _page_state(tab)
        if await _has_visible_cnki_challenge(tab, url, text):
            raise CNKIHumanRequired("CNKI güvenlik doğrulaması özel tarayıcıda açıldı; kaydırıcıyı elle tamamlayıp komutu yeniden çalıştırın")
        return url
    finally:
        await tab.close()


async def search_cnki_campus(query: str, limit: int = 10) -> list[CNKIResult]:
    """Geçerli kampüs ağı/CARSI oturumunda CNKI'de arar; kaydırıcı doğrulamada sekmeyi açık bırakıp durur."""
    tab = await _connect_or_open_cnki(CNKI_SEARCH_URL)
    try:
        url, text = await _page_state(tab)
        if not url.startswith(CNKI_SEARCH_URL):
            await chrome_cdp.navigate(tab, CNKI_SEARCH_URL)
            await asyncio.sleep(8)
            url, text = await _page_state(tab)
        if await _has_visible_cnki_challenge(tab, url, text):
            raise CNKIHumanRequired("CNKI güvenlik doğrulaması özel tarayıcıda açıldı; kaydırıcıyı elle tamamlayıp aramayı yeniden deneyin")

        js = r'''
        (() => {
          const visible = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
          const inputs = [...document.querySelectorAll('input')].filter(visible);
          const input = inputs.find(e => /txt_search|txt_searchtext|searchtext|searchinput|query/i.test(e.id + e.name + e.className))
            || inputs.find(e => /检索|搜索|关键词|主题|篇名/i.test(e.placeholder || ''))
            || inputs.find(e => /text|search/i.test(e.type || ''));
          if (!input) return 'no-search-input';
          const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
          setter.call(input, __QUERY__);
          input.dispatchEvent(new Event('input', {bubbles: true}));
          input.dispatchEvent(new Event('change', {bubbles: true}));
          const controls = [...document.querySelectorAll('button, a, input[type=button], input[type=submit], [role=button]')].filter(visible);
          const button = controls.find(e => /btnsearch|searchbtn|search/i.test(e.id + e.name + e.className))
            || controls.find(e => /^(检索|搜索|search)$/i.test((e.textContent || e.value || '').trim()));
          if (!button) return 'no-search-button';
          button.click();
          return 'submitted';
        })()
        '''.replace("__QUERY__", json.dumps(query))
        result = await tab.cmd("Runtime.evaluate", {"expression": js, "returnByValue": True})
        action = str(result.get("result", {}).get("value", ""))
        if action != "submitted":
            raise CNKIError(f"CNKI arama denetimi tanınmadı: {action}")
        await asyncio.sleep(10)
        url, text = await _page_state(tab)
        if await _has_visible_cnki_challenge(tab, url, text):
            raise CNKIHumanRequired("CNKI aramasından sonra güvenlik doğrulaması çıktı; özel tarayıcıda kaydırıcıyı tamamlayıp yeniden deneyin")

        result_js = r'''
        (() => {
          const out = [];
          for (const a of document.querySelectorAll('a')) {
            const href = a.href || '';
            const title = (a.textContent || '').replace(/\s+/g, ' ').trim();
            if (!title || title.length < 4 || title.length > 500) continue;
            if (!/detail|kcms|kns8s|article/i.test(href)) continue;
            if (/login|defaultresult|download/i.test(href)) continue;
            out.push({title, url: href, source: (a.closest('tr, li, div')?.innerText || '').slice(0, 200)});
          }
          const seen = new Set();
          return JSON.stringify(out.filter(x => !seen.has(x.url) && seen.add(x.url)).slice(0, __LIMIT__));
        })()
        '''.replace("__LIMIT__", str(max(1, min(limit, 50))))
        result = await tab.cmd("Runtime.evaluate", {"expression": result_js, "returnByValue": True})
        raw = str(result.get("result", {}).get("value", "[]"))
        return [CNKIResult(**item) for item in json.loads(raw)]
    finally:
        await tab.close()


async def _find_cnki_download(tab: chrome_cdp.Tab) -> tuple[str, str]:
    js = r'''
    (() => {
      const norm = s => (s || '').replace(/\s+/g, ' ').trim();
      const candidates = [...document.querySelectorAll('a, button, [role=button]')].map(e => ({
        text: norm(e.textContent), href: e.href || '', id: e.id || '', cls: String(e.className || '')
      })).filter(e => /pdf|caj|下载|download|fulltext/i.test(e.text + e.href + e.id + e.cls));
       const pdf = candidates.find(e => /pdfdown/i.test(e.id + e.cls))
         || candidates.find(e => /pdf下载/i.test(e.text) && /bar\.cnki\.net\/bar\/download/i.test(e.href));
       const caj = candidates.find(e => /cajdown/i.test(e.id + e.cls))
         || candidates.find(e => /caj下载/i.test(e.text) && /bar\.cnki\.net\/bar\/download/i.test(e.href));
      return JSON.stringify(pdf ? {kind: 'pdf', ...pdf} : caj ? {kind: 'caj', ...caj} : {});
    })()
    '''
    result = await tab.cmd("Runtime.evaluate", {"expression": js, "returnByValue": True})
    data = json.loads(str(result.get("result", {}).get("value", "{}")))
    return str(data.get("kind", "")), str(data.get("href", ""))


async def _connect_existing_cnki_verification() -> chrome_cdp.Tab | None:
    """Açık bar.cnki.net doğrulama sekmesini yeniden kullanır; doğrulamanın tekrar oluşturulmasını önler."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            pages = (await client.get(
                f"http://{chrome_cdp.CDP_HOST}:{chrome_cdp.CDP_PORT}/json/list")).json()
    except httpx.HTTPError:
        return None
    for page in pages:
        if page.get("type") != "page":
            continue
        page_url = str(page.get("url", ""))
        host = urlparse(page_url).hostname or ""
        if host == "bar.cnki.net" and "/verify/" in page_url:
            tab = chrome_cdp.Tab(page["webSocketDebuggerUrl"])
            await tab.connect()
            return tab
    return None


async def _click_cnki_download(tab: chrome_cdp.Tab, kind: str) -> chrome_cdp.Tab | None:
    """CNKI indirme/doğrulama sekmesini gerçek bir tarayıcı tıklamasıyla açar."""
    selector = "#pdfDown, [name=pdfDown]" if kind == "pdf" else "#cajDown, [name=cajDown]"
    result = await tab.cmd("Runtime.evaluate", {
        "expression": f'''(() => {{
          const e = [...document.querySelectorAll({json.dumps(selector)})].find(e => {{
            const r = e.getBoundingClientRect();
            const s = getComputedStyle(e);
            return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
          }});
          if (!e) return '';
          e.scrollIntoView({{block: 'center'}});
          const r = e.getBoundingClientRect();
          return JSON.stringify({{x: r.x + r.width / 2, y: r.y + r.height / 2}});
        }})()''',
        "returnByValue": True,
    })
    raw = str(result.get("result", {}).get("value", ""))
    if not raw:
        return None
    point = json.loads(raw)
    await tab.cmd("Input.dispatchMouseEvent", {
        "type": "mousePressed", "x": point["x"], "y": point["y"],
        "button": "left", "buttons": 1, "clickCount": 1,
    })
    await tab.cmd("Input.dispatchMouseEvent", {
        "type": "mouseReleased", "x": point["x"], "y": point["y"],
        "button": "left", "buttons": 0, "clickCount": 1,
    })
    deadline = asyncio.get_running_loop().time() + 8
    while asyncio.get_running_loop().time() < deadline:
        async with httpx.AsyncClient(timeout=5) as client:
            pages = (await client.get(
                f"http://{chrome_cdp.CDP_HOST}:{chrome_cdp.CDP_PORT}/json/list")).json()
        for page in pages:
            page_url = str(page.get("url", ""))
            if page.get("type") == "page" and urlparse(page_url).hostname == "bar.cnki.net":
                new_tab = chrome_cdp.Tab(page["webSocketDebuggerUrl"])
                await new_tab.connect()
                return new_tab
        await asyncio.sleep(0.5)
    return None


async def download_cnki_campus(article_url: str, dest: Path) -> dict:
    """CNKI PDF'ini ya da CAJ'ını indirir; çıktı uzantısının gerçek biçimle aynı olmasını ister."""
    existing_verification = await _connect_existing_cnki_verification()
    if existing_verification:
        raise CNKIHumanRequired("CNKI indirme doğrulama sayfası özel tarayıcıda açıldı; yapbozu tamamlayıp indirmeyi yeniden deneyin")
    tab = await _connect_or_open_cnki(article_url)
    download_tab: chrome_cdp.Tab | None = None
    try:
        await chrome_cdp.navigate(tab, article_url)
        await asyncio.sleep(10)
        url, text = await _page_state(tab)
        if await _has_visible_cnki_challenge(tab, url, text):
            raise CNKIHumanRequired("CNKI makale sayfasında güvenlik doğrulaması çıktı; kaydırıcıyı tamamlayıp indirmeyi yeniden deneyin")
        kind, file_url = await _find_cnki_download(tab)
        if kind not in {"pdf", "caj"} or not file_url:
            raise CNKIError("CNKI PDF ya da CAJ indirme bağlantısı bulunamadı")
        expected_suffix = f".{kind}"
        if dest.suffix.lower() != expected_suffix:
            raise CNKIError(f"bu kayıt {kind.upper()} sunuyor; --output değerini {expected_suffix} uzantılı bir dosya adı yapın")
        download_tab = await _click_cnki_download(tab, kind)
        if download_tab:
            download_url, download_text = await _page_state(download_tab)
            if "/verify/" in download_url or is_cnki_challenge(download_url, download_text):
                raise CNKIHumanRequired("CNKI indirme doğrulama sayfası özel tarayıcıda açıldı; yapbozu tamamlayıp indirmeyi yeniden deneyin")
            await download_tab.close_target()
            download_tab = None
        try:
            fetch = fetch_pdf_via_browser if kind == "pdf" else fetch_file_via_browser
            return await fetch(tab, file_url, dest, referer=article_url) if kind == "pdf" else await fetch(tab, file_url, dest, "caj", referer=article_url)
        except PDFError as first_error:
            file_ws = await chrome_cdp.create_tab_navigate(file_url, timeout=30)
            if not file_ws:
                raise CNKIError(f"CNKI {kind.upper()} yetkili bağlantısı açılamadı: {first_error}") from first_error
            file_tab = chrome_cdp.Tab(file_ws)
            await file_tab.connect()
            try:
                await asyncio.sleep(5)
                try:
                    fetch = fetch_pdf_via_browser if kind == "pdf" else fetch_file_via_browser
                    return await fetch(file_tab, None, dest, referer=article_url) if kind == "pdf" else await fetch(file_tab, None, dest, "caj", referer=article_url)
                except PDFError as second_error:
                    raise CNKIError(f"CNKI {kind.upper()} yetkilendirme arayüzü dosya döndürmedi: {second_error}") from second_error
            finally:
                await file_tab.close_target()
    finally:
        if download_tab:
            await download_tab.close()
        await tab.close()


async def login_cnki_carsi() -> dict:
    """Kampüs dışı CNKI CARSI/kurum girişi. Okulun SP yapılandırması kampüs ağı dışında doğrulanmalıdır."""
    return await auto_login(CNKI_CARSI_URL, host_hint="cnki.net")
