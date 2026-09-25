"""Kurum girişi uyarlaması (Shibboleth/OpenAthens/SSO).

Akış: yayıncı sitesine git → "kurum girişi" bağlantısını bul → Jilin Üniversitesi'ni seç →
hesap parolasını yalnız güvenilir JLU IdP'sine gir → kullanıcı koşulları/öznitelik paylaşımını elle onaylar → yayıncıya geri dön.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from litlib import chrome_cdp
from litlib.creds import load_institution_cred
from litlib.pdf import PDFError, validate_pdf_for_work

logger = logging.getLogger("litlib.inst_login")

SESSION_COOKIES_FILE: Path | None = None  # config tarafından atanan çerez önbelleği yolu

# Yaygın kurum girişi anahtar sözcükleri (giriş bağlantısını/giriş sayfasını tanımak için; web sayfası metniyle eşleşir, çevrilmez)
INST_LOGIN_HINTS = (
    "institution", "institutional", "机构登录", "机构用户", "登录机构",
    "shibboleth", "openathens", "sso", "wayf", "campus", "remote access",
    "通过机构", "via your institution", "log in through",
)
IDP_LOGIN_HINTS = (
    "统一身份认证", "统一认证", "login.jlu.edu.cn", "cas.jlu.edu.cn",
    "idp", "sso.jlu.edu.cn", "passport.jlu.edu.cn", "吉林大学",
)
DEFAULT_JLU_IDP_HOSTS = (
    "login.jlu.edu.cn",
    "cas.jlu.edu.cn",
    "idp.jlu.edu.cn",
    "sso.jlu.edu.cn",
    "passport.jlu.edu.cn",
    "shenfen.jlu.edu.cn",
)


def allowed_jlu_idp_hosts() -> set[str]:
    configured = os.environ.get("LITLIB_JLU_IDP_HOSTS", "")
    extra = {host.strip().lower().rstrip(".") for host in configured.split(",") if host.strip()}
    return set(DEFAULT_JLU_IDP_HOSTS) | extra


def is_allowed_jlu_idp_url(url: str) -> bool:
    """Kimlik bilgileri yalnız açıkça listelenmiş HTTPS JLU IdP sunucularına gönderilebilir."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    return parsed.scheme.lower() == "https" and host in allowed_jlu_idp_hosts()


def is_explicit_paywall(text: str, dc_format: str = "") -> bool:
    """Genel abonelik pazarlamasını değil, açık satın alma/kiralama ifadelerini tanır."""
    purchase_text = f"{dc_format}\n{text}"
    return bool(re.search(
        r"buy protocol|purchase (?:this )?(?:article|pdf)|rent (?:this )?article|"
        r"\$\s*\d+\s*/\s*48 hours|需购买|购买全文|付费阅读|purchase-only",
        purchase_text,
        re.I,
    ))


async def connect_tab(client: httpx.AsyncClient) -> chrome_cdp.Tab:
    """Kullanılabilir tarayıcı sayfasına bağlanır (ya da yenisini açar), Tab döndürür."""
    await chrome_cdp.wait_for_cdp(timeout=10)
    pages = (await client.get(
        f"http://{chrome_cdp.CDP_HOST}:{chrome_cdp.CDP_PORT}/json/list",
        timeout=10)).json()
    page = next((p for p in pages if p.get("type") == "page"), None)
    if not page:
        raise RuntimeError("kullanılabilir sayfa yok; önce `litlib inst open` ile tarayıcıyı başlatın")
    tab = chrome_cdp.Tab(page["webSocketDebuggerUrl"])
    await tab.connect()
    return tab


async def find_and_click_institution_login(tab: chrome_cdp.Tab) -> str:
    """Açılış sayfasında 'kurum girişi' bağlantısını/düğmesini bulup tıklar, yapılan işlemin açıklamasını döndürür."""
    js = r'''
    (() => {
      const norm = (s) => (s || '').trim().toLowerCase().replace(/\s+/g, ' ');
      const all = [...document.querySelectorAll('a, button, [role="button"]')];
      // 0) href'inde type=institution / idLogin geçen kurum girişi önceliklidir
      for (const e of all) {
        const href = norm(e.getAttribute('href') || '');
        if (/type\s*=\s*institution/.test(href) || /institutionallogin/.test(href)) {
          const info = (e.textContent || '').trim().slice(0, 40) + ' | ' + href.slice(0, 100);
          e.click();
          return 'clicked: ' + info;
        }
      }
      // 1) metninde kurum girişi geçenler (institution içerenler önce)
      const cands = all.filter(e => {
        const t = norm(e.textContent);
        const href = norm(e.getAttribute('href') || '');
        const cls = norm(e.className || '');
        const all = t + ' ' + href + ' ' + cls;
        if (all.length < 4 || all.length > 300) return false;
        return /institution|机构登录|institutional|shibboleth|openathens|wayf|log ?in|sign ?in|登录/.test(all)
               && !/logout|sign ?out|退出/.test(all);
      });
      if (!cands.length) return 'no-login-link';
      cands.sort((a, b) => {
        const ta = norm(a.textContent), tb = norm(b.textContent);
        const ia = /institution|机构|shibboleth|openathens/.test(ta) ? 1 : 0;
        const ib = /institution|机构|shibboleth|openathens/.test(tb) ? 1 : 0;
        if (ia !== ib) return ib - ia;
        return ta.length - tb.length;
      });
      const e = cands[0];
      const info = (e.textContent || '').trim().slice(0, 40) + ' | ' + (e.getAttribute('href') || '').slice(0, 100);
      e.click();
      return 'clicked: ' + info;
    })()
    '''
    r = await tab.cmd("Runtime.evaluate", {"expression": js, "returnByValue": True})
    return str(r.get("result", {}).get("value", ""))


async def pick_jilin_wayf(tab: chrome_cdp.Tab) -> str:
    """WAYF/kurum seçim sayfasında Jilin Üniversitesi'ni seçer (arama kutusuna yazıp sonuca tıklar)."""
    js = r'''
    (() => {
      const norm = (s) => (s || '').toLowerCase();
      // 1) görünür giriş kutusunu bul (öncelik id=bdd-email / els_institution / institutionSearchInput)
      const inputs = [...document.querySelectorAll('input')].filter(i => {
        const r = i.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
      });
      const inp = inputs.find(i => /bdd-email|els_institution|institutionSearchInput|idpFilterSubstring/i.test(i.id + i.name))
                  || inputs.find(i => !i.type || i.type === 'text');
      if (!inp) return 'no-search-input';
      inp.click();
      inp.focus();
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(inp, 'jilin university');
      inp.dispatchEvent(new Event('input', {bubbles: true}));
      return 'typed: jilin university';
    })()
    '''
    r = await tab.cmd("Runtime.evaluate", {"expression": js, "returnByValue": True})
    typed = str(r.get("result", {}).get("value", ""))
    if typed != "typed: jilin university":
        return typed
    # Arama sonuçları çıkınca Jilin Üniversitesi'ne tıkla (kimya/finans gibi ekli adlı okulları dışla)
    await asyncio.sleep(4)
    js2 = r'''
    (() => {
      const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
      const cands = [...document.querySelectorAll('form, button, li, a, [role=option], div')].filter(e => {
        const t = norm(e.textContent);
        const head = t.slice(0, 30);
        if (!/^吉林大学|^jilin(\s+univ(ersity)?)?\b/i.test(head)) return false;
        // ekli, benzer okul adlarını dışla
        if (/of |学院|理工|化工|财经|艺术/.test(head)) return false;
        return t.length < 120;
      });
      cands.sort((a, b) => (a.textContent || '').length - (b.textContent || '').length);
      if (!cands.length) return 'no-jilin-option';
      const e = cands[0];
      e.click();
      return 'clicked: ' + norm(e.textContent).slice(0, 50);
    })()
    '''
    await asyncio.sleep(3)
    r2 = await tab.cmd("Runtime.evaluate", {"expression": js2, "returnByValue": True})
    clicked = str(r2.get("result", {}).get("value", ""))
    if clicked == "no-jilin-option":
        await asyncio.sleep(4)
        r3 = await tab.cmd("Runtime.evaluate", {"expression": js2, "returnByValue": True})
        clicked = str(r3.get("result", {}).get("value", ""))
    return clicked


async def fill_idp_login(tab: chrome_cdp.Tab, username: str, password: str) -> str:
    """Birleşik kimlik doğrulama sayfasında hesap parolasını doldurup gönderir."""
    location = await tab.cmd("Runtime.evaluate", {
        "expression": "location.href", "returnByValue": True,
    })
    current_url = str(location.get("result", {}).get("value", ""))
    if not is_allowed_jlu_idp_url(current_url):
        host = (urlparse(current_url).hostname or "unknown").lower()
        raise PermissionError(f"güvenilir olmayan IdP'ye kimlik bilgisi gönderimi reddedildi: {host}")
    js = r'''
    (() => {
      const fields = [...document.querySelectorAll('input')];
      const user = fields.find(i => /user|account|username|login|j_username|邮箱|账号|工号|学号/i.test((i.name||'') + ' ' + (i.id||'') + ' ' + (i.placeholder||'')));
      const pass = fields.find(i => i.type === 'password');
      if (!user || !pass) return 'no-fields';
      user.value = __USER__;
      user.dispatchEvent(new Event('input', {bubbles: true}));
      pass.value = __PASS__;
      pass.dispatchEvent(new Event('input', {bubbles: true}));
      return 'filled';
    })()
    '''.replace("__USER__", json.dumps(username)).replace("__PASS__", json.dumps(password))
    r = await tab.cmd("Runtime.evaluate", {"expression": js, "returnByValue": True})
    return str(r.get("result", {}).get("value", ""))


async def pick_tandf_wayf(tab: chrome_cdp.Tab) -> str:
    """T&F (Atypon) WAYF: önce CARSI federasyonunu seçer, sonra pinyin 'jilin' yazıp Jilin Üniversitesi'ni seçer."""
    js = r'''
    (() => {
      const fed = document.querySelector('select#shib-search--fed');
      if (!fed) return 'no-federation-select';
      const opt = [...fed.options].find(o => /CARSI|CERNET/i.test(o.textContent + ' ' + o.value));
      if (!opt) return 'no-carsi-option';
      const setter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set;
      setter.call(fed, opt.value);
      fed.dispatchEvent(new Event('change', {bubbles: true}));
      return 'fed-selected: ' + opt.textContent.slice(0, 30);
    })()
    '''
    r = await tab.cmd("Runtime.evaluate", {"expression": js, "returnByValue": True})
    step = str(r.get("result", {}).get("value", ""))
    if not step.startswith("fed-selected"):
        return step
    await asyncio.sleep(4)
    js2 = r'''
    (() => {
      const inputs = [...document.querySelectorAll('input')].filter(i => {
        const r = i.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
      });
      const inp = inputs.find(i => /institution|instit|idp|search/i.test(i.id + ' ' + i.name + ' ' + (i.placeholder || '')))
                  || inputs.find(i => !i.type || i.type === 'text' || i.type === 'search');
      if (!inp) return 'no-search-input';
      inp.click();
      inp.focus();
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(inp, 'jilin');
      inp.dispatchEvent(new Event('input', {bubbles: true}));
      return 'typed: jilin';
    })()
    '''
    r2 = await tab.cmd("Runtime.evaluate", {"expression": js2, "returnByValue": True})
    typed = str(r2.get("result", {}).get("value", ""))
    if typed != "typed: jilin":
        return typed
    js3 = r'''
    (() => {
      const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
      const cands = [...document.querySelectorAll('a, button, li, [role=option], div')].filter(e => {
        const t = norm(e.textContent);
        const head = t.slice(0, 30);
        if (!/^jilin(\s+univ(ersity)?)?\b/i.test(head) && !/^吉林大学/.test(head)) return false;
        if (/of |学院|理工|化工|财经|艺术/.test(head)) return false;
        return t.length < 120;
      });
      cands.sort((a, b) => (a.textContent || '').length - (b.textContent || '').length);
      if (!cands.length) return 'no-jilin-option';
      const e = cands[0];
      e.click();
      return 'clicked: ' + norm(e.textContent).slice(0, 50);
    })()
    '''
    await asyncio.sleep(2)
    r3 = await tab.cmd("Runtime.evaluate", {"expression": js3, "returnByValue": True})
    clicked = str(r3.get("result", {}).get("value", ""))
    if clicked == "no-jilin-option":
        await asyncio.sleep(4)
        r4 = await tab.cmd("Runtime.evaluate", {"expression": js3, "returnByValue": True})
        clicked = str(r4.get("result", {}).get("value", ""))
    return clicked


async def submit_idp_login(tab: chrome_cdp.Tab) -> str:
    """Önceden doldurulmuş giriş formunu koşulları kabul etmeden ve kutu işaretlemeden gönderir."""
    js = r'''
    (() => {
      const norm = (s) => (s || '').trim().toLowerCase();
      const btns = [...document.querySelectorAll('button, input[type=submit], a')];
      for (const b of btns) {
        const t = norm(b.textContent || b.value || '');
        if (/^登 ?录$|^log ?in$|^sign ?in$|^submit$|^提交$|^进入$/.test(t)) {
          b.click();
          return 'submitted:' + t.slice(0, 10);
        }
      }
      const form = document.querySelector('input[type=password]')?.form;
      if (form && form.requestSubmit) { form.requestSubmit(); return 'submitted:form'; }
      return 'no-login-submit';
    })()
    '''
    r = await tab.cmd("Runtime.evaluate", {"expression": js, "returnByValue": True})
    return str(r.get("result", {}).get("value", ""))


async def handle_post_login(tab: chrome_cdp.Tab, host_hint: str = "",
                            timeout: float = 120.0) -> str:
    """Kullanıcının koşulları/öznitelik paylaşımını onaylamasını ve yayıncıya yönlendirmeyi bekler."""
    deadline = time.monotonic() + timeout
    last_url = ""
    human_checkpoint = ""
    while time.monotonic() < deadline:
        try:
            r = await tab.cmd("Runtime.evaluate", {"expression": "location.href", "returnByValue": True})
            last_url = str(r.get("result", {}).get("value", ""))
        except Exception:
            await asyncio.sleep(2)
            continue
        text = ""
        try:
            r = await tab.cmd("Runtime.evaluate", {
                "expression": "document.body ? document.body.innerText.slice(0, 2000) : ''",
                "returnByValue": True})
            text = str(r.get("result", {}).get("value", ""))
        except Exception:
            pass

        # Elsevier kişiselleştirme sayfası ("We now know you're from ..." / personalize experience) → Skip'e tıkla
        if re.search(r"personalize your experience|we now know you'?re from", text, re.I):
            js = r'''
            (() => {
              const btns = [...document.querySelectorAll('a, button, input[type=submit]')];
              const skip = btns.find(b => {
                const t = (b.textContent || b.value || '').trim().toLowerCase();
                return /^skip$|^跳过$|^稍后$/.test(t);
              });
              if (skip) { skip.click(); return 'skipped'; }
              return 'no-skip-btn';
            })()
            '''
            r = await tab.cmd("Runtime.evaluate", {"expression": js, "returnByValue": True})
            print(f"  [Elsevier kişiselleştirme sayfası] {r.get('result', {}).get('value')}")
            await asyncio.sleep(6)
            continue

        # Koşul/beyan sayfası (Çince desenler gerçek sayfa metnini eşler)
        if re.search(r"声明|agreement|同意此使用条款|使用条款", text, re.I) and re.search(r"提交|同意", text, re.I):
            if human_checkpoint != "terms":
                print("  HUMAN_REQUIRED: özel tarayıcıda beyanı/kullanım koşullarını okuyup elle onaylayın")
            human_checkpoint = "terms"
            await asyncio.sleep(5)
            continue

        # Bilgi paylaşımı (öznitelik paylaşımı) onay sayfası
        if re.search(r"信息发布|attribute|共享|shib-attr-release", text, re.I) and re.search(r"接受|accept", text, re.I):
            if human_checkpoint != "attribute-release":
                print("  HUMAN_REQUIRED: özel tarayıcıda paylaşılan öznitelikleri kontrol edip elle kabul/ret'e tıklayın")
            human_checkpoint = "attribute-release"
            await asyncio.sleep(5)
            continue

        # İnsan doğrulaması (Turnstile vb.): kendiliğinden tamamlanması ya da kullanıcı müdahalesi beklenir
        if re.search(r"请稍候|just a moment|安全验证|captcha|人机", text, re.I):
            await asyncio.sleep(5)
            continue

        # Yayıncıya geri dönüldü (query parametreleri yanıltmasın diye hostname kesin karşılaştırılır)
        current_host = (urlparse(last_url).hostname or "").lower().removeprefix("www.")
        expected_host = host_hint.lower().removeprefix("www.")
        if expected_host and (current_host == expected_host or current_host.endswith("." + expected_host)):
            if not re.search(r"idp|sso|login", current_host, re.I):
                return f"redirected: {last_url[:100]}"
        if not expected_host and not re.search(r"idp|sso|login\.jlu|elsevier\.com", last_url, re.I):
            if last_url and "shenfen" not in last_url:
                return f"redirected: {last_url[:100]}"

        # Giriş başarısız (form hâlâ sayfada)
        if re.search(r"密码|password|错误|失败|invalid", text, re.I) and "idp" in last_url:
            return f"login-failed-page: {last_url[:100]}"

        await asyncio.sleep(3)
    if human_checkpoint:
        return f"human-required:{human_checkpoint}: {last_url[:100]}"
    return f"timeout: {last_url[:100]}"


async def wait_redirect_back(tab: chrome_cdp.Tab, timeout: float = 60.0,
                            host_hint: str = "") -> str:
    """Giriş sonrası geri yönlendirmenin bitmesini bekler, son URL önekini döndürür."""
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        try:
            r = await tab.cmd("Runtime.evaluate", {"expression": "location.href", "returnByValue": True})
            last = str(r.get("result", {}).get("value", ""))
        except Exception:
            await asyncio.sleep(2)
            continue
        title = ""
        try:
            t = await tab.cmd("Runtime.evaluate", {"expression": "document.title", "returnByValue": True})
            title = str(t.get("result", {}).get("value", ""))
        except Exception:
            pass
        if host_hint and host_hint in last:
            return last
        if "login" not in last.lower() and "sso" not in last.lower() and "idp" not in last.lower() and title:
            if not re.search(r"请稍候|just a moment|安全验证", title, re.I):
                return last
        await asyncio.sleep(3)
    return last


async def wait_for_human_challenge(tab: chrome_cdp.Tab, timeout: float = 180.0) -> bool:
    """CAPTCHA/Turnstile'ı algılar; varsa kullanıcının görünür tarayıcıda elle tamamlamasını bekler."""
    challenge = re.compile(
        r"are you a robot|captcha|turnstile|just a moment|请稍候|安全验证|人机",
        re.I,
    )
    deadline = time.monotonic() + timeout
    announced = False
    while time.monotonic() < deadline:
        try:
            r = await tab.cmd("Runtime.evaluate", {
                "expression": "(document.title || '') + '\\n' + (document.body ? document.body.innerText.slice(0, 500) : '')",
                "returnByValue": True,
            })
            text = str(r.get("result", {}).get("value", ""))
        except Exception:
            text = ""
        if not challenge.search(text):
            return True
        if not announced:
            print(f"  insan doğrulaması algılandı, özel tarayıcıda elle tamamlayın; en fazla {int(timeout)} sn beklenecek ...")
            announced = True
        await asyncio.sleep(5)
    return False


async def export_cookies(tab: chrome_cdp.Tab, dest: Path) -> int:
    """Tarayıcının tüm çerezlerini DPAPI ile şifreli dosyaya aktarır."""
    from litlib import creds
    r = await tab.cmd("Network.getAllCookies", {})
    cookies = r.get("cookies", [])
    if not cookies:
        return 0
    creds.encrypt_file(
        json.dumps(cookies, ensure_ascii=False).encode("utf-8"), dest)
    return len(cookies)


async def import_cookies(tab: chrome_cdp.Tab, src: Path) -> int:
    """Çerezleri DPAPI dosyasından tarayıcıya geri yükler."""
    if not src.exists():
        return 0
    from litlib import creds
    try:
        data = creds.decrypt_file(src)
        cookies = json.loads(data)
    except Exception:
        return 0
    n = 0
    for c in cookies:
        try:
            await tab.cmd("Network.setCookie", {
                "name": c.get("name", ""),
                "value": c.get("value", ""),
                "domain": c.get("domain", ""),
                "path": c.get("path", "/"),
                "expires": c.get("expires", -1),
                "secure": c.get("secure", True),
                "httpOnly": c.get("httpOnly", False),
            })
            n += 1
        except Exception:
            continue
    return n


async def fetch_file_via_browser(tab: chrome_cdp.Tab, url: str | None, dest: Path,
                                 file_kind: str = "binary", referer: str = "",
                                 max_bytes: int = 50 * 1024 * 1024) -> dict:
    """Dosya URL'ini geçerli sayfa bağlamında fetch eder (aynı köken şartı), base64 parçalar halinde alıp kaydeder.

    url None ise sayfanın geçerli location'ı kullanılır. Cloudflare'li ve kurum oturumlu siteler için uygundur.
    """
    import base64 as _b64

    js_fetch = r"""
    (async () => {
      const url = __URL__;
       const opts = {redirect: 'follow', referrer: __REFERER__ || undefined};
      const r = await fetch(url || location.href, opts);
      const ct = r.headers.get('content-type') || '';
      const buf = await r.arrayBuffer();
      const btype = (r.headers.get('content-type') || '') || '';
       if (__PDF__ && !ct.includes('pdf') && !r.url.includes('.pdf')) {
         return 'NOTFILE:' + ct + ':status=' + r.status + ':len=' + buf.byteLength;
       }
       if (!__PDF__ && (ct.includes('text/html') || ct.includes('text/plain'))) {
         return 'NOTFILE:' + ct + ':status=' + r.status + ':len=' + buf.byteLength;
      }
      window.__litlib_pdfbuf = buf;
      return 'OK:' + buf.byteLength;
    })()
    """.replace("__URL__", json.dumps(url) if url else "null").replace("__REFERER__", json.dumps(referer) if referer else "null").replace("__PDF__", "true" if file_kind == "pdf" else "false")
    r = await tab.cmd("Runtime.evaluate", {"expression": js_fetch, "awaitPromise": True, "returnByValue": True})
    if r.get("exceptionDetails"):
        detail = r["exceptionDetails"].get("text", "JavaScript fetch error")
        raise PDFError(f"fetch başarısız: {detail}")
    v = str(r.get("result", {}).get("value", ""))
    if not v.startswith("OK:"):
        raise PDFError(f"dosya fetch edilemedi: {v[:120]}")
    total = int(v.split(":")[1])
    if total > max_bytes:
        try:
            await tab.cmd("Runtime.evaluate", {"expression": "delete window.__litlib_pdfbuf"})
        except Exception:
            pass
        raise PDFError(f"tarayıcıdaki dosya boyut üst sınırını aşıyor: {total} > {max_bytes}")
    CH = 3 * 1024 * 1024
    nchunks = (total + CH - 1) // CH
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    part.unlink(missing_ok=True)
    try:
        with part.open("wb") as f:
            for i in range(nchunks):
                js_chunk = f"""
                (() => {{
                  const u8 = new Uint8Array(window.__litlib_pdfbuf, {i * CH}, Math.min({CH}, {total} - {i * CH}));
                  let bin = '';
                  const S = 0x8000;
                  for (let j = 0; j < u8.length; j += S) bin += String.fromCharCode.apply(null, u8.subarray(j, j + S));
                  return btoa(bin);
                }})()
                """
                r2 = await tab.cmd("Runtime.evaluate", {"expression": js_chunk, "returnByValue": True})
                chunk = _b64.b64decode(str(r2.get("result", {}).get("value", "")))
                if file_kind == "pdf" and i == 0 and chunk[:4] != b"%PDF":
                    raise PDFError(f"tarayıcıdan indirilen içerik PDF değil (ilk parça {len(chunk)}B)")
                f.write(chunk)
        os.replace(part, dest)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    finally:
        try:
            await tab.cmd("Runtime.evaluate", {"expression": "delete window.__litlib_pdfbuf"})
        except Exception:
            pass
    return {"size": total, "content_type": "application/pdf" if file_kind == "pdf" else "application/octet-stream", "via": "browser-fetch"}


async def fetch_pdf_via_browser(tab: chrome_cdp.Tab, url: str | None, dest: Path,
                                referer: str = "", max_bytes: int = 50 * 1024 * 1024) -> dict:
    return await fetch_file_via_browser(tab, url, dest, "pdf", referer, max_bytes)


async def find_pdf_link(tab: chrome_cdp.Tab) -> str:
    """Makale açılış sayfasında PDF indirme bağlantısını bulur (showPdf/pdfft/download/pdf)."""
    js = r'''
    (() => {
      const norm = (s) => (s || '').trim().toLowerCase();
      const meta = document.querySelector('meta[name="citation_pdf_url"]');
      if (meta && meta.content) return meta.content;
      const anchors = [...document.querySelectorAll('a')];
       const cands = anchors.filter(a => {
        const href = norm(a.href);
        const t = norm(a.textContent);
        if (!href || href.startsWith('javascript')) return false;
         if (/showpdf|pdfft|article-pdf|articlepdf|\/doi\/(pdf|epdf)|(^|\/)pdf([/?]|$)|\.pdf([/?]|$)/.test(href)) return true;
        if (t.length < 40 && /^(download|view|get).{0,12}pdf|全文|下载|pdf(\s|\(|$)/.test(t)) return true;
        return false;
      });
      if (!cands.length) return '';
      const main = cands.filter(a => !/suppl|supplement|supporting|reporting.summary|mediaobjects|esm\b/.test(
        norm(a.href) + ' ' + norm(a.textContent)));
      if (!main.length) return '';
      const pool = main;
      // ana metin PDF'i ek materyallerden ve rastgele PDF bağlantılarından önce gelir
       const best = pool.find(a => /showpdf|pdfft|article-pdf|articlepdf|\/doi\/(pdf|epdf)/.test(norm(a.href))) || pool[0];
      return best.href;
    })()
    '''
    r = await tab.cmd("Runtime.evaluate", {"expression": js, "returnByValue": True})
    return str(r.get("result", {}).get("value", ""))


async def capture_pdf_after_click(tab: chrome_cdp.Tab, pdf_url: str, dest: Path,
                                  timeout: float = 45.0) -> dict | None:
    """Wiley'ye özel: epdf görüntüleme sayfasına gider, sayfa içinden aynı kökenle pdfdirect baytlarının tamamını fetch eder.

    CDP getResponseBody yalnız görüntüleyicinin parçalı aralık yanıtını alabiliyor (262 KB'ta kesiliyor);
    epdf sayfa bağlamında aynı kökenli pdfdirect?hmac=... fetch edilince PDF'in tamamı alınır.
    """
    if not re.search(r"/doi/(?:e)?pdf(?:direct)?/", pdf_url):
        return None
    if "/doi/epdf/" not in pdf_url:
        pdf_url = pdf_url.replace("/doi/pdfdirect/", "/doi/epdf/")
    pdf_url = pdf_url.split("?")[0]
    await chrome_cdp.navigate(tab, pdf_url)

    expr = r"""
    (async () => {
      const name = performance.getEntriesByType('resource')
        .map(e => e.name).find(n => n.includes('/doi/pdfdirect/'));
      if (!name) return '';
      const r = await fetch(name);
      const b = await r.arrayBuffer();
      const bytes = new Uint8Array(b);
      let bin = '';
      const chunk = 0x8000;
      for (let i = 0; i < bytes.length; i += chunk)
        bin += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
      return JSON.stringify({url: name, size: bytes.length, b64: btoa(bin)});
    })()
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = await tab.cmd("Runtime.evaluate", {
                "expression": expr, "awaitPromise": True, "returnByValue": True,
            })
            raw = str(result.get("result", {}).get("value", ""))
            if raw:
                data = json.loads(raw)
                content = base64.b64decode(data["b64"])
                if content.startswith(b"%PDF") and content.rstrip().endswith(b"%%EOF"):
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    part = dest.with_suffix(dest.suffix + ".part")
                    part.write_bytes(content)
                    os.replace(part, dest)
                    return {"size": len(content), "content_type": "application/pdf", "via": "browser-sameorigin"}
        except (json.JSONDecodeError, KeyError, ValueError):
            pass
        await asyncio.sleep(2)
    return None


def known_pdf_url(doi: str, current_url: str = "") -> str:
    """Kararlı yayıncı kurallarından ana metin PDF URL'ini kurar; yalnız açılış sayfasında bulunamazsa aday olarak kullanılır."""
    value = doi.lower().strip()
    host = (urlparse(current_url).hostname or "").lower()
    if value.startswith("10.1126/") or host.endswith("science.org"):
        return f"https://www.science.org/doi/pdf/{value}"
    if value.startswith("10.1038/") or host.endswith("nature.com"):
        return f"https://www.nature.com/articles/{value[len('10.1038/'):]}.pdf"
    if value.startswith("10.1007/") or host.endswith("link.springer.com"):
        return f"https://link.springer.com/content/pdf/{value}.pdf"
    if value.startswith("10.1002/") or host.endswith("onlinelibrary.wiley.com"):
        return f"https://onlinelibrary.wiley.com/doi/epdf/{value}"
    return ""


async def download_doi_via_browser(doi: str, dest: Path) -> dict:
    """Kurum kanalının tüm zinciri: DOI → makale sayfası → PDF bağlantısı → indir ve kaydet.

    Tarayıcının kurum oturumunu tutması için önce `litlib inst login <url>` tamamlanmalıdır.
    İki mod otomatik seçilir:
    - Aynı kökenli fetch (Cell: showPdf doğrudan PDF döndürür)
    - PDF'e gidip CDN yönlendirmesini tetikler, yeni sekmede aynı kökenli fetch (OUP: silverchair CDN)
    """
    ws = await chrome_cdp.create_tab_navigate(f"https://doi.org/{doi}", timeout=30)
    if not ws:
        raise PDFError("DOI indirme sekmesi oluşturulamadı")
    tab = chrome_cdp.Tab(ws)
    await tab.connect()
    keep_download_tab_open = False
    try:
        await asyncio.sleep(12)
        pdf_url = ""
        for _ in range(6):
            pdf_url = await find_pdf_link(tab)
            if pdf_url:
                break
            await asyncio.sleep(5)
        if not pdf_url:
            # İnsan doğrulamasını kullanıcı görünür tarayıcıda elle tamamlar; bitince otomatik devam edilir.
            try:
                r = await tab.cmd("Runtime.evaluate", {
                    "expression": "document.body ? document.body.innerText.slice(0, 300) : ''",
                    "returnByValue": True})
                body_text = str(r.get("result", {}).get("value", ""))
            except Exception:
                body_text = ""
            if re.search(r"are you a robot|captcha|turnstile|just a moment|安全验证|人机", body_text, re.I):
                print("  insan doğrulaması algılandı, özel tarayıcıda tamamlayın; en fazla 180 sn beklenecek ...")
                deadline = time.monotonic() + 180
                while time.monotonic() < deadline:
                    await asyncio.sleep(5)
                    pdf_url = await find_pdf_link(tab)
                    if pdf_url:
                        break
                if not pdf_url:
                    keep_download_tab_open = True
                    raise PDFError("HUMAN_REQUIRED: insan doğrulaması kullanıcı tarafından henüz tamamlanmadı")
        if not pdf_url:
            # Bazı yayıncılar yalnız JS düğmesi/yerel indirme sunar, kararlı bir href vermez.
            try:
                chrome_cdp.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
                before = set(chrome_cdp.DOWNLOAD_DIR.glob("*.pdf"))
                await chrome_cdp.set_download_dir(tab, chrome_cdp.DOWNLOAD_DIR)
                clicked = await chrome_cdp.click_pdf_link(tab)
                if clicked.startswith("clicked:"):
                    await asyncio.sleep(3)
                    pdf_url = await find_pdf_link(tab)
                    if not pdf_url:
                        downloaded = await asyncio.to_thread(
                            chrome_cdp.wait_for_download_file,
                            chrome_cdp.DOWNLOAD_DIR, 45, 5_000, before)
                        if downloaded:
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            os.replace(downloaded, dest)
                            return {
                                "size": dest.stat().st_size,
                                "content_type": "application/pdf",
                                "via": "browser-native-download",
                            }
            except Exception:
                pass
        if not pdf_url:
            try:
                r = await tab.cmd("Runtime.evaluate", {
                    "expression": r'''JSON.stringify({
                      text: document.body ? document.body.innerText.slice(0, 2500) : '',
                      format: document.querySelector('meta[name="dc.Format" i]')?.content || ''
                    })''',
                    "returnByValue": True})
                access_info = json.loads(str(r.get("result", {}).get("value", "{}")))
                body_text = str(access_info.get("text", ""))
                dc_format = str(access_info.get("format", ""))
            except Exception:
                body_text = ""
                dc_format = ""
            if re.search(r"429 too many requests|you have sent too many requests|just a moment|cf-error", body_text, re.I):
                raise PDFError(f"site hız sınırı/anti-bot: {body_text[:60]}")
            html_only = dc_format.strip().casefold() == "text/html"
            if is_explicit_paywall(body_text, dc_format) or html_only:
                reason = "yalnız HTML, PDF yetkisi bulunamadı" if html_only else "sayfa açıkça satın alma/kiralama gösteriyor"
                raise PDFError(f"PAYWALLED: {reason} ({dc_format or 'format unknown'})")
            # Açılış sayfası özetse (Cell vb.) tam metin sayfasına geçip orada aranır
            cur = ""
            try:
                r = await tab.cmd("Runtime.evaluate", {"expression": "location.href", "returnByValue": True})
                cur = str(r.get("result", {}).get("value", ""))
            except Exception:
                pass
            if re.search(r"/abstract/|/article/abstract", cur, re.I):
                ft = re.sub(r"/abstract/", "/fulltext/", cur, count=1)
                ft = ft.split("?")[0]
                print(f"  özet açılış sayfası, tam metne geçiliyor: {ft[:90]}")
                await chrome_cdp.navigate(tab, ft)
                await asyncio.sleep(10)
                for _ in range(4):
                    pdf_url = await find_pdf_link(tab)
                    if pdf_url:
                        break
                    await asyncio.sleep(4)
            if not pdf_url:
                pdf_url = known_pdf_url(doi, cur)
        if not pdf_url:
            raise PDFError(f"makale sayfasında PDF bağlantısı bulunamadı (geçerli {cur[:100]})")
        if pdf_url.startswith("/"):
            r = await tab.cmd("Runtime.evaluate", {"expression": "location.origin", "returnByValue": True})
            pdf_url = str(r.get("result", {}).get("value", "")) + pdf_url
        try:
            network_capture = await capture_pdf_after_click(tab, pdf_url, dest)
            if network_capture:
                return network_capture
            return await fetch_pdf_via_browser(tab, pdf_url, dest)
        except PDFError as e:
            print(f"  aynı kökenli fetch başarısız ({str(e)[:60]}), gezinmeli CDN indirmesi deneniyor ...")
        pdf_tab_ws = await chrome_cdp.create_tab_navigate(pdf_url, timeout=30)
        if not pdf_tab_ws:
            raise PDFError("gezinmeden sonra CDN sekmesi bulunamadı")
        cdn_tab = chrome_cdp.Tab(pdf_tab_ws)
        await cdn_tab.connect()
        try:
            cdn_url = ""
            for _ in range(20):
                try:
                    r = await cdn_tab.cmd("Runtime.evaluate", {
                        "expression": "location.href",
                        "returnByValue": True})
                    cdn_url = str(r.get("result", {}).get("value", ""))
                except Exception:
                    cdn_url = ""
                if cdn_url and "about:blank" not in cdn_url:
                    break
                await asyncio.sleep(2)
            if not cdn_url or "about:blank" in cdn_url:
                raise PDFError("CDN sekmesinde gezinme tamamlanmadı")
            return await fetch_pdf_via_browser(cdn_tab, None, dest)
        finally:
            await cdn_tab.close_target()
    finally:
        if keep_download_tab_open:
            await tab.close()
        else:
            await tab.close_target()


def _advance_to_ready(st, task_id: int) -> bool:
    """Görevi durum makinesine göre adım adım READY'e ilerletir (indirme zaten yapılmış, yalnız kayıt için)."""
    from litlib.models import TaskState
    chains = {
        TaskState.REQUIRES_INST: (TaskState.INST_QUEUED, TaskState.DOWNLOADING, TaskState.VERIFYING),
        TaskState.INST_QUEUED: (TaskState.DOWNLOADING, TaskState.VERIFYING),
        TaskState.DOWNLOADING: (TaskState.VERIFYING,),
        TaskState.VERIFYING: (),
        TaskState.OA_OK: (TaskState.DOWNLOADING, TaskState.VERIFYING),
        TaskState.DEDUPED: (TaskState.OA_OK, TaskState.DOWNLOADING, TaskState.VERIFYING),
        TaskState.METADATA_FETCH: (TaskState.DEDUPED, TaskState.OA_OK, TaskState.DOWNLOADING, TaskState.VERIFYING),
        TaskState.QUEUED: (TaskState.METADATA_FETCH, TaskState.DEDUPED, TaskState.OA_OK,
                           TaskState.DOWNLOADING, TaskState.VERIFYING),
        TaskState.FAILED: (TaskState.QUEUED, TaskState.METADATA_FETCH, TaskState.DEDUPED,
                           TaskState.OA_OK, TaskState.DOWNLOADING, TaskState.VERIFYING),
        TaskState.HUMAN_REQUIRED: (TaskState.QUEUED, TaskState.METADATA_FETCH, TaskState.DEDUPED,
                                   TaskState.OA_OK, TaskState.DOWNLOADING, TaskState.VERIFYING),
        TaskState.RATE_LIMITED: (TaskState.QUEUED, TaskState.METADATA_FETCH, TaskState.DEDUPED,
                                  TaskState.OA_OK, TaskState.DOWNLOADING, TaskState.VERIFYING),
    }
    row = st._conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if row is None:
        return False
    cur = TaskState(row["state"])
    if cur in {
        TaskState.READY, TaskState.PROPOSAL_GENERATED,
        TaskState.USER_REVIEWED, TaskState.IMPORTED,
    }:
        return True
    chain = chains.get(cur)
    if chain is None:
        return False
    for target in chain:
        st.set_state(task_id, target)
    st.set_state(task_id, TaskState.READY)
    return True


def register_download_to_db(doi: str, dest: Path, channel: str) -> bool:
    """İndirilmiş dosyayı DOI ile görev veritabanına kaydeder ve READY yapar (idempotent, otomatik eşitleme).

    İlgili work/task bulunamazsa ya da dosya doğrulaması başarısızsa hata fırlatmaz, False döndürür.
    """
    from litlib.models import sha256_of_file
    from litlib.state import State
    st = State()
    try:
        conn = st._conn
        work = conn.execute(
            "SELECT work_id FROM works WHERE LOWER(doi)=?", (doi.lower(),)
        ).fetchone()
        if work is None:
            return False
        task = conn.execute(
            "SELECT * FROM tasks WHERE work_id=? ORDER BY id LIMIT 1", (work["work_id"],)).fetchone()
        if task is None:
            return False
        n_pages, n_chars = validate_pdf_for_work(dest, doi)
        sha = sha256_of_file(dest)
        st.add_file(work["work_id"], str(dest), sha, dest.stat().st_size, channel)
        return _advance_to_ready(st, task["id"])
    except Exception as exc:
        logger.warning("indirme kaydı başarısız: %s (%s)", doi, exc)
        return False
    finally:
        st.close()


async def download_doi_and_register(doi: str, dest: Path, channel: str | None = None) -> dict:
    """Ana metni indirir ve görev veritabanına otomatik kaydeder (indirme + otomatik eşitleme tek adımda)."""
    info = await download_doi_via_browser(doi, dest)
    registered = register_download_to_db(doi, dest, channel or info.get("via", "browser"))
    if not registered:
        raise PDFError(
            "PDF indirildi ama görev veritabanına kaydedilemedi; dosyayı saklayın, DOI için görev açılıp açılmadığını ve durum veritabanı günlüğünü kontrol edin"
        )
    info["registered"] = True
    return info


async def download_doi_inst_with_retry(doi: str, dest: Path) -> dict:
    """Kurum kanalı + başarısızlıkta otomatik giriş ile yeniden deneme.
    Kurum oturumu yoksa (sayfada giriş bağlantısı görünüyorsa) önce DOI'nin alan adında
    `auto_login` çalıştırılır, sonra indirme bir kez daha denenir.
    """
    from litlib.inst import doi_to_publisher
    mapped_domain = (doi_to_publisher(doi) or ("", ""))[0]
    try:
        return await download_doi_via_browser(doi, dest)
    except PDFError as e:
        actual_domain = await resolve_doi_host(doi)
        domain = mapped_domain if mapped_domain == "cell.com" else actual_domain or mapped_domain
        if not domain:
            raise
        print(f"  kurum kanalı başarısız ({str(e)[:60]}), {domain} için otomatik kurum girişi deneniyor ...")
        return await login_and_download_doi(doi, dest, domain)


async def login_and_download_doi(doi: str, dest: Path, domain: str = "") -> dict:
    """DOI'nin nihai yayıncısında kurum girişi yapar, sonra ana metni indirir."""
    from litlib.inst import doi_to_publisher
    domain = domain or await resolve_doi_host(doi) or (doi_to_publisher(doi) or ("", ""))[0]
    if not domain:
        raise PDFError("DOI'nin yayıncı alan adı çözümlenemedi")
    base = {"cell.com": "https://www.cell.com/",
            "academic.oup.com": "https://academic.oup.com/"}.get(domain)
    if not base:
        base = f"https://{domain}/"
    result = await auto_login(base, host_hint=domain)
    if not result.get("ok"):
        raise PDFError(f"otomatik giriş başarısız: {result.get('reason', 'unknown')}")
    return await download_doi_via_browser(doi, dest)


async def resolve_doi_host(doi: str) -> str:
    """Yayıncı host'unu DOI'nin gerçek yönlendirmesinden çözer; yalnız önek eşlemesine dayanmaz."""
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            r = await client.get(
                f"https://doi.org/{doi}",
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        return (urlparse(str(r.url)).hostname or "").lower().removeprefix("www.")
    except httpx.HTTPError:
        return ""


async def auto_login(url: str, host_hint: str = "") -> dict:
    """Sıkı IdP host doğrulaması ve insan onayı checkpoint'leriyle kurum girişi."""
    ws = await chrome_cdp.create_tab_navigate(url, timeout=30)
    if not ws:
        return {"ok": False, "reason": "kurum girişi sekmesi oluşturulamadı"}
    tab = chrome_cdp.Tab(ws)
    await tab.connect()
    steps: list[str] = []
    keep_tab_open = False
    try:
        await asyncio.sleep(8)
        if not await wait_for_human_challenge(tab):
            keep_tab_open = True
            return {
                "ok": False, "human_required": True,
                "reason": "HUMAN_REQUIRED: insan doğrulaması beklenirken zaman aşımı", "steps": steps,
            }

        # 1) Kurum girişi bağlantısı
        step = await find_and_click_institution_login(tab)
        steps.append(f"login-entry: {step}")
        await asyncio.sleep(6)
        if not await wait_for_human_challenge(tab):
            keep_tab_open = True
            return {
                "ok": False, "human_required": True,
                "reason": "HUMAN_REQUIRED: kurum girişinde insan doğrulaması beklenirken zaman aşımı", "steps": steps,
            }

        # 2) WAYF'ta okul seçimi (T&F'de önce CARSI federasyonu seçilmeli)
        r = await tab.cmd("Runtime.evaluate", {
            "expression": "!!document.querySelector('select#shib-search--fed')",
            "returnByValue": True})
        if r.get("result", {}).get("value"):
            step = await pick_tandf_wayf(tab)
        else:
            step = await pick_jilin_wayf(tab)
        steps.append(f"wayf: {step}")
        await asyncio.sleep(6)
        if not await wait_for_human_challenge(tab):
            keep_tab_open = True
            return {
                "ok": False, "human_required": True,
                "reason": "HUMAN_REQUIRED: WAYF'ta insan doğrulaması beklenirken zaman aşımı", "steps": steps,
            }

        # 3) Form yalnız HTTPS JLU IdP izin listesindeyse doldurulur; oturum hatırlanıyorsa kimlik bilgisi gerekmez.
        filled = False
        on_post_login_page = False
        page_text = ""
        for _ in range(5):
            try:
                r = await tab.cmd("Runtime.evaluate", {
                    "expression": "location.href", "returnByValue": True})
                cur_url = str(r.get("result", {}).get("value", ""))
                r = await tab.cmd("Runtime.evaluate", {
                    "expression": "document.body ? document.body.innerText.slice(0, 300) : ''",
                    "returnByValue": True})
                page_text = str(r.get("result", {}).get("value", ""))
            except Exception:
                cur_url = ""
                page_text = ""
            if (re.search(r"声明|同意此使用条款|agreement|信息发布|attribute|共享|接受", page_text, re.I)
                    or re.search(r"idp/profile|shib-attr|SAML2", cur_url, re.I)
                    or re.search(r"personalize your experience|we now know you'?re from", page_text, re.I)):
                on_post_login_page = True
                break
            if re.search(r"429 too many requests|you have sent too many requests|cloudflare|cf-error|are you a robot|just a moment", page_text, re.I):
                return {"ok": False, "reason": f"site hız sınırı/anti-bot: {page_text[:80]}", "steps": steps}
            current_host = (urlparse(cur_url).hostname or "").lower().removeprefix("www.")
            expected_host = host_hint.lower().removeprefix("www.")
            still_selecting_institution = bool(re.search(
                r"institutional-login|access-through-institution|shibboleth|wayf",
                cur_url + "\n" + page_text,
                re.I,
            ))
            if (expected_host and not still_selecting_institution
                    and (current_host == expected_host or current_host.endswith("." + expected_host))):
                return {"ok": True, "final_url": f"already-redirected: {cur_url[:100]}",
                        "steps": ["idp-fill: skipped", "post-login: session remembered"]}

            has_password = False
            try:
                r = await tab.cmd("Runtime.evaluate", {
                    "expression": "!!document.querySelector('input[type=password]')",
                    "returnByValue": True,
                })
                has_password = bool(r.get("result", {}).get("value"))
            except Exception:
                pass
            if has_password and not is_allowed_jlu_idp_url(cur_url):
                host = current_host or "unknown"
                return {
                    "ok": False,
                    "reason": f"güvenilir olmayan IdP'ye kimlik bilgisi gönderimi reddedildi: {host}",
                    "steps": steps,
                }
            if is_allowed_jlu_idp_url(cur_url):
                cred = load_institution_cred()
                if not cred:
                    return {"ok": False, "reason": "kurum kimlik bilgisi yok; önce `litlib inst set-cred` çalıştırın"}
                username, password = cred
                step = await fill_idp_login(tab, username, password)
                steps.append(f"idp-fill: {step}")
                if step == "filled":
                    submit = await submit_idp_login(tab)
                    steps.append(f"idp-submit: {submit}")
                    if submit.startswith("submitted:"):
                        filled = True
                        break
            await asyncio.sleep(3)
        if not filled and not on_post_login_page:
            return {
                "ok": False,
                "reason": "güvenilir HTTPS JLU IdP'sinde gönderilebilir giriş formu bulunamadı",
                "steps": steps,
            }

        step = await handle_post_login(tab, timeout=150, host_hint=host_hint)
        steps.append(f"post-login: {step}")
        if step.startswith("human-required:"):
            keep_tab_open = True
            return {"ok": False, "human_required": True, "reason": step, "steps": steps}
        if step.startswith(("timeout:", "login-failed-page:")):
            return {"ok": False, "reason": step, "steps": steps}

        await asyncio.sleep(5)
        if SESSION_COOKIES_FILE:
            n = await export_cookies(tab, SESSION_COOKIES_FILE)
            steps.append(f"cookies-exported: {n}")
        return {"ok": True, "final_url": step, "steps": steps}
    finally:
        if keep_tab_open:
            await tab.close()
        else:
            await tab.close_target()
